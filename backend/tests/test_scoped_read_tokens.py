"""Scoped read tokens (SCOPED_READ_TOKENS).

INGEST_TOKEN writes everything and QUERY_TOKEN reads everything — the MCP
endpoint, bulk export, sobriety, fasting, blood pressure and the journal
included. A scoped read token is the credential another self-hosted app
can hold instead: GET only, a fixed route allow-list, and every response
redacted on the way out.

What this file pins down:

* the env format and what a malformed entry does (dropped, never fatal);
* the allow-list, both as a truth table and against the real app's routes,
  so a new route under an allow-listed prefix cannot slip in unreviewed;
* the middleware: 403 before routing, redaction after, fail-closed on a
  body it cannot read;
* that the INGEST / QUERY tokens behave exactly as they did.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

from myvitals import auth, scoped_access
from myvitals.config import settings

SCOPED = "scoped-test-token-000000000000000001"
SCOPED_2 = "scoped-test-token-000000000000000002"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        settings, "scoped_read_tokens", f"aggregator:{SCOPED}, dashboard:{SCOPED_2}",
    )


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Parsing ────────────────────────────────────────────────────────────

class TestParsing:
    def _parse(self, raw: str):
        return auth._parse_scoped(raw, settings.ingest_token, settings.query_token)

    def test_name_token_pairs(self):
        assert self._parse(f"a:{SCOPED},b:{SCOPED_2}") == (("a", SCOPED), ("b", SCOPED_2))

    def test_whitespace_and_empty_entries_are_ignored(self):
        assert self._parse(f" a : {SCOPED} ,, ,") == (("a", SCOPED),)

    def test_unset_means_no_tokens(self, monkeypatch):
        monkeypatch.setattr(settings, "scoped_read_tokens", "")
        assert auth.scoped_tokens() == ()
        assert auth.scoped_token_name(SCOPED) is None

    @pytest.mark.parametrize("raw", [
        SCOPED,                          # no name
        f"bad name:{SCOPED}",            # name with a space
        f":{SCOPED}",                    # empty name
        "short:abc123",                  # guessable
    ])
    def test_malformed_entries_are_dropped_not_fatal(self, raw):
        assert self._parse(f"{raw},ok:{SCOPED_2}") == (("ok", SCOPED_2),)

    def test_a_full_access_token_can_never_be_scoped(self):
        """Otherwise the full-access check matches first and the 'scoped'
        caller silently gets everything."""
        raw = f"x:{settings.query_token}-pad-pad-pad,y:{SCOPED}"
        assert self._parse(raw) == (("x", f"{settings.query_token}-pad-pad-pad"), ("y", SCOPED))
        for full in (settings.query_token, settings.ingest_token):
            assert auth._parse_scoped(f"x:{full}", full, full) == ()

    def test_duplicate_names_and_tokens_keep_the_first(self):
        assert self._parse(f"a:{SCOPED},a:{SCOPED_2},b:{SCOPED}") == (("a", SCOPED),)

    def test_logs_never_contain_a_token(self, caplog):
        caplog.set_level("ERROR")
        self._parse(f"bad name:{SCOPED},short:tiny-secret-xyz,dup:{SCOPED_2},dup2:{SCOPED_2}")
        assert caplog.records, "malformed entries should be reported"
        assert SCOPED not in caplog.text
        assert SCOPED_2 not in caplog.text
        assert "tiny-secret-xyz" not in caplog.text


class TestMatching:
    def test_match_returns_the_name(self, configured):
        assert auth.scoped_token_name(SCOPED) == "aggregator"
        assert auth.scoped_token_name(SCOPED_2) == "dashboard"

    @pytest.mark.parametrize("tok", [None, "", "nope", SCOPED[:-1], SCOPED + "x"])
    def test_no_match(self, configured, tok):
        assert auth.scoped_token_name(tok) is None

    def test_classic_tokens_are_not_scoped(self, configured):
        assert auth.scoped_token_name(settings.query_token) is None
        assert auth.scoped_token_name(settings.ingest_token) is None

    def test_compares_every_entry_in_constant_time(self, configured, monkeypatch):
        """No early exit: matching the FIRST entry costs as many
        compare_digest calls as matching none, and every comparison goes
        through compare_digest rather than ==."""
        calls = []
        real = auth.secrets.compare_digest

        def counting(a, b):
            calls.append(1)
            return real(a, b)

        monkeypatch.setattr(auth.secrets, "compare_digest", counting)
        auth.scoped_token_name(SCOPED)
        first = len(calls)
        calls.clear()
        auth.scoped_token_name("definitely-not-configured-000000")
        assert first == len(calls) == len(auth.scoped_tokens()) == 2


# ── The allow-list ─────────────────────────────────────────────────────

ALLOWED = sorted(auth.SCOPED_READ_EXACT) + [
    "/workout/strength/workouts",
    "/workout/strength/workouts/12",
    "/workout/strength/today",
    "/trails/daily",
    "/trails/alerts",
    "/trails/7/visits",
]

DENIED_PATHS = [
    "/sober/current", "/sober/stats", "/fasting/current", "/fasting/stats",
    "/query/blood-pressure", "/query/heartrate", "/query/steps", "/query/weight",
    "/export/heartrate.csv", "/export/daily_summary.json", "/mcp",
    "/ai/coach/sleep/latest", "/ai/latest", "/ai/goals", "/journal", "/log",
    "/summary/today/snapshot", "/summary/range/stats", "/summary/sleep-need",
    "/activities/map", "/activities/strava/123", "/activities/records",
    "/analytics/discoveries", "/debug/logs", "/profile", "/meals/log",
    "/ingest/heartrate", "/trails/resolve-link",
    # Prefix edge cases.
    "/workout/strength", "/workout/strength/", "/trails/", "/trailsx",
    "/summary/range/", "/SUMMARY/range", "//summary/range", "", None,
]


class TestAllowList:
    @pytest.mark.parametrize("path", ALLOWED)
    def test_allowed_gets(self, path):
        assert auth.scoped_path_allowed("GET", path)

    @pytest.mark.parametrize("path", DENIED_PATHS)
    def test_denied_gets(self, path):
        assert not auth.scoped_path_allowed("GET", path)

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get"])
    @pytest.mark.parametrize("path", ["/summary/range", "/workout/strength/equipment", "/trails"])
    def test_only_get(self, method, path):
        assert not auth.scoped_path_allowed(method, path)


def _main_app():
    from myvitals.main import app
    return app


@pytest.fixture(scope="module")
def paths():
    return _main_app().openapi()["paths"]


class TestAllowListAgainstTheRealApp:
    """The allow-list is strings; these tie it to the routes that exist."""

    def test_every_exact_entry_is_a_real_get_route(self, paths):
        missing = [p for p in auth.SCOPED_READ_EXACT if "get" not in paths.get(p, {})]
        assert not missing, f"allow-listed but no such GET route: {missing}"

    def test_no_route_can_capture_an_allow_listed_path(self, paths):
        """The middleware checks the raw path; that is only equivalent to
        checking the handler if no route template starts with a parameter
        (a catch-all like `/{rest:path}` could route `/trails/x` anywhere)."""
        assert not [p for p in paths if p.startswith("/{")]

    def test_get_routes_under_allowed_prefixes_are_reviewed(self):
        """Everything GET under /trails/ and /workout/strength/ is readable
        by a scoped token. A new route there must be added below on purpose
        (or to SCOPED_READ_DENY) — this fails until someone decides."""
        from myvitals.api import trails
        from myvitals.api.workout import strength

        reviewed = {
            "/trails", "/trails/config", "/trails/daily", "/trails/alerts",
            "/trails/resolve-link", "/trails/{trail_id}/osm-paths",
            "/trails/{trail_id}/visits",
            # Which OSM state packs are imported + trail counts (0070).
            "/trails/trailmap/status",
            "/workout/strength/equipment", "/workout/strength/exercises",
            "/workout/strength/exercises/{exercise_id}",
            "/workout/strength/exercises-stats-summary",
            "/workout/strength/exercises/{exercise_id}/stats",
            "/workout/strength/workouts", "/workout/strength/workouts/{workout_id}",
            "/workout/strength/upcoming", "/workout/strength/today",
            "/workout/strength/stats", "/workout/strength/volume-trend",
            "/workout/strength/records", "/workout/strength/explain/{workout_id}",
            "/workout/strength/by-date/{date_iso}", "/workout/strength/muscle-volume",
            "/workout/strength/recovery",
        }
        actual = {
            r.path for router in (trails.router, strength.router) for r in router.routes
            if "GET" in getattr(r, "methods", set())
        }
        assert actual == reviewed, (
            f"new: {sorted(actual - reviewed)}  gone: {sorted(reviewed - actual)}"
        )


# ── The dependencies on their own ──────────────────────────────────────

class TestDependencies:
    def test_require_query_and_ingest_refuse_a_scoped_token(self, configured):
        for dep in (auth.require_query, auth.require_ingest):
            with pytest.raises(Exception) as ei:
                dep(f"Bearer {SCOPED}")
            assert ei.value.status_code == 403

    def test_require_any_refuses_a_scoped_token_without_a_vetted_request(self, configured):
        """Called directly (no request), or on a request the middleware did
        not mark: fail closed."""
        with pytest.raises(Exception) as ei:
            auth.require_any(f"Bearer {SCOPED}")
        assert ei.value.status_code == 403

    def test_classic_behaviour_is_unchanged(self, configured):
        auth.require_any(f"Bearer {settings.ingest_token}")
        auth.require_any(f"Bearer {settings.query_token}")
        auth.require_query(f"Bearer {settings.query_token}")
        auth.require_ingest(f"Bearer {settings.ingest_token}")
        for dep in (auth.require_any, auth.require_query, auth.require_ingest):
            with pytest.raises(Exception) as ei:
                dep("Bearer not-a-real-token")
            assert ei.value.status_code == 401


# ── Middleware + redaction, on a small app ─────────────────────────────

def _stub_app(with_middleware: bool = True) -> FastAPI:
    router = APIRouter(dependencies=[Depends(auth.require_any)])

    @router.get("/summary/day")
    async def day():
        return {
            "date": "2026-09-01",
            "annotations": [{"note": "private"}],
            "blood_pressure": {"points": [{"systolic": 120}]},
            "weight": {"points": [{"kg": 90.0}]},
            "tiles": {"tiles": [
                {"key": "hrv", "value": 20.0},
                {"key": "blood_pressure", "value": "120/80"},
            ]},
            "activities": [{"source_id": "1", "polyline": "abc", "distance_m": 1000.0}],
        }

    @router.get("/summary/range")
    async def rng():
        return [{"date": "2026-09-01", "resting_hr": 55.0, "bp_systolic_avg": 120.0,
                 "bp_diastolic_avg": 80.0, "fasting_hours": 16.0,
                 "carried_from": {"hrv_avg": "2026-08-31", "bp_systolic_avg": "2026-08-01"}}]

    @router.get("/ai/alerts")
    async def alerts():
        return [
            {"id": 1, "kind": "anomaly", "metric": "hrv", "title": "HRV anomaly"},
            {"id": 2, "kind": "goal_reached", "metric": "sober", "title": "Goal reached"},
            {"id": 3, "kind": "goal_reached", "metric": "fast_streak", "title": "Goal"},
        ]

    @router.get("/query/data-health")
    async def health():
        return {"streams": [{"key": "heart_rate"}, {"key": "blood_pressure"}],
                "problem_keys": ["blood_pressure", "steps"]}

    @router.get("/trails/text")
    async def text():
        return PlainTextResponse("not json")

    @router.get("/trails/stream")
    async def stream():
        async def gen():
            yield b'{"a": 1, "polyline": '
            yield b'"xyz"}'
        return StreamingResponse(gen(), media_type="application/json")

    @router.get("/sober/current")
    async def sober():
        return {"days": 10}

    @router.post("/summary/range")
    async def write():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)

    @app.get("/version")
    async def version():  # no auth dependency of its own
        return {"version": "x"}

    @app.get("/update/check")
    async def unauthenticated_but_not_allowed():
        return {"ok": True}

    if with_middleware:
        app.add_middleware(scoped_access.ScopedReadMiddleware)
    return app


@pytest.fixture
def client(configured):
    return TestClient(_stub_app())


class TestMiddleware:
    @pytest.mark.parametrize("method,path", [
        ("GET", "/sober/current"),
        ("POST", "/summary/range"),
        ("GET", "/update/check"),       # no auth dep of its own: still 403
        ("GET", "/no/such/route"),
        ("HEAD", "/version"),
    ])
    def test_refused_before_routing(self, client, method, path):
        r = client.request(method, path, headers=_h(SCOPED))
        assert r.status_code == 403
        if method != "HEAD":
            assert r.json() == {"detail": "this token cannot access this route"}

    def test_classic_tokens_reach_the_same_routes(self, client):
        assert client.get("/sober/current", headers=_h(settings.query_token)).json() == {"days": 10}
        assert client.post("/summary/range", headers=_h(settings.query_token)).status_code == 200
        assert client.get("/update/check").status_code == 200

    def test_classic_tokens_get_unredacted_bodies(self, client):
        full = client.get("/summary/day", headers=_h(settings.query_token)).json()
        assert full["annotations"] and full["blood_pressure"]
        assert full["activities"][0]["polyline"] == "abc"
        assert client.get("/trails/text", headers=_h(settings.ingest_token)).text == "not json"

    def test_unauthenticated_and_wrong_tokens_still_401(self, client):
        assert client.get("/summary/day").status_code == 401
        assert client.get("/summary/day", headers=_h("nope")).status_code == 401

    def test_allowed_route_without_its_own_auth(self, client):
        assert client.get("/version", headers=_h(SCOPED)).json() == {"version": "x"}

    def test_summary_day_is_redacted(self, client):
        r = client.get("/summary/day", headers=_h(SCOPED))
        assert r.status_code == 200
        body = r.json()
        assert "annotations" not in body
        assert "blood_pressure" not in body
        assert body["weight"] == {"points": [{"kg": 90.0}]}
        assert [t["key"] for t in body["tiles"]["tiles"]] == ["hrv"]
        assert body["activities"] == [{"source_id": "1", "distance_m": 1000.0}]
        assert int(r.headers["content-length"]) == len(r.content)

    def test_summary_range_drops_bp_and_fasting_even_in_carried_from(self, client):
        row = client.get("/summary/range", headers=_h(SCOPED)).json()[0]
        assert row == {"date": "2026-09-01", "resting_hr": 55.0,
                       "carried_from": {"hrv_avg": "2026-08-31"}}

    def test_ai_alerts_drop_sobriety_and_fasting_goals(self, client):
        rows = client.get("/ai/alerts", headers=_h(SCOPED)).json()
        assert [r["id"] for r in rows] == [1]

    def test_data_health_drops_the_bp_stream(self, client):
        body = client.get("/query/data-health", headers=_h(SCOPED)).json()
        assert body == {"streams": [{"key": "heart_rate"}], "problem_keys": ["steps"]}

    def test_streamed_json_is_reassembled_and_redacted(self, client):
        assert client.get("/trails/stream", headers=_h(SCOPED)).json() == {"a": 1}

    def test_non_json_fails_closed(self, client):
        r = client.get("/trails/text", headers=_h(SCOPED))
        assert r.status_code == 500
        assert "not json" not in r.text

    def test_without_the_middleware_a_scoped_token_is_refused(self, configured):
        """require_any insists on the middleware's mark: an app that forgot
        to install it fails closed, not open."""
        c = TestClient(_stub_app(with_middleware=False))
        assert c.get("/summary/range", headers=_h(SCOPED)).status_code == 403
        assert c.get("/summary/range", headers=_h(settings.query_token)).status_code == 200

    def test_middleware_is_inert_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(settings, "scoped_read_tokens", "")
        c = TestClient(_stub_app())
        assert c.get("/summary/day", headers=_h(SCOPED)).status_code == 401

    async def test_websocket_is_closed(self, configured):
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "websocket.connect"}

        async def app(scope, receive, send):  # pragma: no cover - must not run
            raise AssertionError("scoped websocket reached the app")

        mw = scoped_access.ScopedReadMiddleware(app)
        await mw({"type": "websocket", "path": "/summary/range",
                  "headers": [(b"authorization", f"Bearer {SCOPED}".encode())]},
                 receive, send)
        assert sent == [{"type": "websocket.close", "code": 1008}]


class TestRedact:
    def test_nested_keys_and_tagged_items(self):
        data = {
            "a": [{"polyline": "x", "b": 1}, "sober", "hrv", {"metric": "bp", "v": 1}],
            "fasting": {"x": 1},
            "deep": {"deeper": {"summary_polyline": "y", "keep": True}},
            "tiles": [{"key": {"not": "a string"}}],
        }
        assert scoped_access.redact(data) == {
            "a": [{"b": 1}, "hrv"],
            "deep": {"deeper": {"keep": True}},
            "tiles": [{"key": {"not": "a string"}}],
        }

    def test_scalars_pass_through(self):
        for v in (None, 1, 1.5, "x", True):
            assert scoped_access.redact(v) == v


# ── The real app, end to end ───────────────────────────────────────────

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _activity(**kw):
    base = dict(
        source="strava", source_id="1", type="Ride", name="Morning ride",
        start_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc), duration_s=3600,
        distance_m=16093.4, elevation_gain_m=120.0, avg_hr=130.0, max_hr=160.0,
        avg_power_w=None, max_power_w=None, kcal=500.0, suffer_score=None,
        polyline="_p~iF~ps|U_ulLnnqC", polyline_simple="_p~iF~ps|U", route_state=None,
        recorded_type=None, notes=None, tags=None, trail_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestRealApp:
    @pytest.fixture
    def real(self, configured):
        from myvitals.db.session import get_session

        app = _main_app()

        class _Db:
            async def execute(self, _stmt):
                return _Rows([_activity()])

        async def fake_session():
            yield _Db()

        app.dependency_overrides[get_session] = fake_session
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_session, None)

    @pytest.mark.parametrize("method,path", [
        ("GET", "/sober/current"), ("GET", "/fasting/current"),
        ("GET", "/query/blood-pressure"), ("GET", "/export/heartrate.csv"),
        ("POST", "/mcp"), ("GET", "/ai/coach/sleep/latest"), ("GET", "/journal"),
        ("GET", "/summary/today/snapshot"), ("GET", "/activities/map"),
        ("POST", "/ingest/heartrate"), ("PUT", "/workout/strength/equipment"),
        ("DELETE", "/workout/strength/workouts/1"), ("POST", "/trails/refresh"),
    ])
    def test_refused_on_the_real_app(self, real, method, path):
        assert real.request(method, path, headers=_h(SCOPED)).status_code == 403

    def test_activities_never_carry_a_route_for_a_scoped_token(self, real, monkeypatch):
        from myvitals.api import strava

        modes = []
        real_to_out = strava._activity_to_out

        def spy(a, trail_name=None, route="full"):
            modes.append(route)
            return real_to_out(a, trail_name=trail_name, route=route)

        monkeypatch.setattr(strava, "_activity_to_out", spy)
        r = real.get("/activities?polyline=full", headers=_h(SCOPED))
        assert r.status_code == 200
        assert modes == ["none"]  # geometry never even loaded
        row = r.json()[0]
        assert "polyline" not in row
        assert row["distance_m"] == 16093.4

    def test_activities_unchanged_for_the_query_token(self, real):
        row = real.get("/activities", headers=_h(settings.query_token)).json()[0]
        assert row["polyline"] == "_p~iF~ps|U_ulLnnqC"

    def test_health_and_version_open_to_a_scoped_token(self, real):
        assert real.get("/version", headers=_h(SCOPED)).status_code == 200


def test_json_bodies_round_trip_unicode():
    """Re-serialisation must not mangle non-ASCII (trail names, notes)."""
    out = json.loads(json.dumps(scoped_access.redact({"name": "Café trail"}), ensure_ascii=False))
    assert out == {"name": "Café trail"}
