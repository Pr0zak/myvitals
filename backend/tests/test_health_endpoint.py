"""SA-O4: `/health` used to be a literal `{"status": "ok"}` regardless of
whether the database was reachable — the sole gate on
`deploy/auto-update.sh`'s 60s rollback probe, and the intended target of
an external uptime check, could not distinguish "serving" from "every
request 500s".

This repo has no fixture that stands up a real async engine (no test in
the suite hits a live Postgres — see conftest.py), so rather than fake
that infrastructure for one endpoint, these call the route coroutine
directly with a stub session object. That is not theatre: `db` is an
ordinary parameter once you call the function outside of FastAPI's
dependency injection, so this genuinely exercises the success path, the
DB-exception path, and the timeout path — the three branches the fix
adds — without needing a database at all.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.responses import JSONResponse

from myvitals import main as main_mod
from myvitals import version as version_mod


class _OkSession:
    async def execute(self, _stmt):
        return None


class _DeadSession:
    async def execute(self, _stmt):
        raise ConnectionRefusedError("db unreachable")


class _HangingSession:
    async def execute(self, _stmt):
        # Never resolves on its own — only asyncio.wait_for's timeout
        # can end this. If the health handler stopped wrapping the
        # query in a timeout, this test would hang instead of failing.
        await asyncio.Event().wait()


def _body(response: JSONResponse) -> dict:
    import json
    return json.loads(response.body)


class TestHealthDbRoundTrip:
    async def test_db_reachable_returns_ok_with_version(self):
        response = await main_mod.health(db=_OkSession())
        assert response.status_code == 200
        body = _body(response)
        assert body["status"] == "ok"
        # Same fields /version exposes — no new information disclosed by
        # folding them into an already-unauthenticated endpoint.
        assert body == {"status": "ok", **version_mod.info()}

    async def test_db_unreachable_returns_503_not_200(self):
        """The whole point: a dead DB must flip the HTTP status, because
        deploy/auto-update.sh's probe is `curl -fsS` — `-f` only treats a
        non-2xx response as failure. A 200 with an "error" body in it
        would sail through the probe unnoticed, same as today's bug."""
        response = await main_mod.health(db=_DeadSession())
        assert response.status_code == 503
        assert _body(response)["status"] == "error"

    async def test_db_unreachable_does_not_leak_exception_detail(self):
        """/health is unauthenticated by design (it's a liveness probe).
        Whatever the DB failure was, its exception text must not ride
        along in the response body."""
        response = await main_mod.health(db=_DeadSession())
        assert "db unreachable" not in str(_body(response))
        assert "ConnectionRefusedError" not in str(_body(response))

    async def test_hung_query_times_out_and_returns_503(self, monkeypatch):
        """A wedged DB must not hang the request. auto-update.sh's curl
        has no --max-time, so a hang here would stall the deploy probe's
        30 retries for however long the query took — the exact opposite
        of 'safe to poll every few seconds'."""
        monkeypatch.setattr(main_mod, "_HEALTH_DB_TIMEOUT_S", 0.05)
        response = await asyncio.wait_for(
            main_mod.health(db=_HangingSession()), timeout=2.0
        )
        assert response.status_code == 503
        assert _body(response)["status"] == "error"

    async def test_ok_response_is_actually_json_200_not_just_dict(self):
        """Guards against a future edit reverting the handler to
        `return {"status": "ok"}` (bypassing JSONResponse and therefore
        never able to carry a non-200 status)."""
        response = await main_mod.health(db=_OkSession())
        assert isinstance(response, JSONResponse)
