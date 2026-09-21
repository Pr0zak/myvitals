"""Health Connect exercise routes -> the activities feed (SA-P3).

SA-P2 shipped a probe rather than the feature, because Health Connect only
holds a route if the writing app wrote one and Fitbit historically did not.
The probe answered on 2026-09-21: `result=CONSENT_REQUIRED` for the
2026-09-19 walk, from BOTH writers. `ExerciseRouteResult` distinguishes
Data / ConsentRequired / NoData, so that is specifically "a route is stored
and is being withheld", not "there is no route".

The backend was never the blocker here either -- `activities.polyline`
exists, is populated for 68 of 71 Strava rows and 452 of 698 Garmin rows,
`activity_sink.upsert_activity` already derives `polyline_simple` from it,
and both clients already draw it. What was missing was a wire field and a
path from it into the row HC-1's promotion writes, plus somewhere to record
WHY there is no route when there is not one.

Four things this file pins:

1. **The encoding is the one already stored.** A Google encoded polyline at
   precision 5. Verified against a real production row rather than assumed:
   a Strava polyline pulled from the live database decodes at precision 5
   to 2,920 points in the user's own city and re-encodes byte-identically,
   and decodes at precision 6 to coordinates a factor of ten away. Getting
   this wrong on the phone would draw every walk in the Gulf of Guinea.
2. **A Health Connect route never overwrites a richer provider's.** Same
   skip-None rule as SA-P1's distance, and it matters more here, because a
   watch track replacing a Strava track is a visible downgrade rather than
   a missing number.
3. **Null is not "no route".** Three states, deliberately: withheld, none,
   and unasked. Collapsing the last two is what made the Route card vanish.
4. **`workouts` gained no column.** Same side-channel as `distance_m`, for
   the same reason -- the raw ingest table is not being grown to carry a
   field only `activities` has.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import polyline as _polyline

from myvitals.api.ingest import _WORKOUT_PROMOTION_ONLY, WorkoutSample
from myvitals.db import models
from myvitals.integrations import activity_sink

#: The walk from the report. `source_id` for a promoted Health Connect
#: session is this instant's isoformat.
T = datetime(2026, 9, 19, 14, 5, 5, tzinfo=timezone.utc)
SID = T.isoformat()

#: A two-point track near the user's own city, encoded the way the phone's
#: `Polylines.encode` does it.
TRACK = _polyline.encode([(39.16700, -94.50582), (39.16698, -94.50581)],
                         precision=5)


def _hc_workout(**kw: object) -> models.Workout:
    defaults: dict[str, object] = dict(
        time=T, type="walking", duration_s=8217, kcal=None,
        avg_hr=None, max_hr=None, source="com.fitbit.FitbitMobile",
        title=None,
    )
    defaults.update(kw)
    return models.Workout(**defaults)


def _update_set(values: dict) -> dict:
    """What `upsert_activity` would actually write on a CONFLICT.

    Mirrors the two comprehensions in `upsert_activity`: restrict to
    provider columns, then drop every None. Reproduced rather than called
    because the real function needs a live session.
    """
    insert_values = {
        k: v for k, v in values.items()
        if k in activity_sink.PROVIDER_COLUMNS or k in ("source", "source_id")
    }
    return {
        k: v for k, v in insert_values.items()
        if k in activity_sink.PROVIDER_COLUMNS and v is not None
    }


class TestTheEncodingMatchesWhatIsAlreadyStored:
    """The phone must produce exactly what Strava's `summary_polyline`
    already is, or the renderers -- `@mapbox/polyline` on the web, a
    hand-written `lat * 1e-5` in the phone's map WebView, and
    `analytics/geo.py` server-side -- all decode it wrong in the same
    direction, silently.
    """

    def test_the_repo_encodes_and_decodes_at_precision_five(self):
        """`analytics/geo.py` and `api/imports.py` are the two places this
        project encodes a polyline itself, and both are precision 5 -- one
        by the library default, one explicitly. Pinned so a later "let us
        get more resolution" edit has to come here first.
        """
        from myvitals.analytics import geo
        src = inspect.getsource(geo) + inspect.getsource(
            __import__("myvitals.api.imports", fromlist=["x"]),
        )
        assert "precision=6" not in src

    def test_precision_six_would_put_the_track_in_the_wrong_hemisphere(self):
        """Not a style preference. The same bytes read at precision 6 are a
        factor of ten out -- Kansas City becomes a point in the Atlantic,
        and the map still renders, which is why this has to be pinned by a
        test rather than noticed by eye.
        """
        at5 = _polyline.decode(TRACK, precision=5)
        at6 = _polyline.decode(TRACK, precision=6)
        assert round(at5[0][0]) == 39
        assert round(at6[0][0]) == 4
        assert abs(at5[0][0] / at6[0][0] - 10) < 0.001

    def test_a_stored_polyline_round_trips(self):
        assert _polyline.encode(_polyline.decode(TRACK, precision=5),
                                precision=5) == TRACK


class TestTheWireModelDefaultsToNull:
    def test_a_sample_with_no_route_keys_carries_neither(self):
        w = WorkoutSample(time=T, type="workout", duration_s=600)
        assert w.polyline is None
        assert w.route_state is None

    def test_an_empty_string_is_not_the_default(self):
        """An empty-string default would post `""` for every indoor
        session. That is a present key, so it would reach the update set
        and blank a track a previous sync found -- and a non-null empty
        polyline makes both clients open a Route card onto nothing."""
        w = WorkoutSample(time=T, type="workout", duration_s=600)
        assert w.polyline != ""

    def test_an_explicit_route_survives(self):
        w = WorkoutSample(time=T, type="walking", duration_s=8217,
                          polyline=TRACK, route_state=None)
        assert w.polyline == TRACK

    def test_a_state_without_a_track_is_a_valid_sample(self):
        """The common case: Health Connect answered, and the answer was
        that it will not release the route."""
        w = WorkoutSample(time=T, type="walking", duration_s=8217,
                          route_state="consent_required")
        assert w.polyline is None
        assert w.route_state == "consent_required"


class TestNoMigrationWasNeededOnTheRawTable:
    def test_workouts_has_neither_column(self):
        cols = models.Workout.__table__.columns.keys()
        assert "polyline" not in cols
        assert "route_state" not in cols

    def test_both_are_excluded_from_the_raw_insert(self):
        """An unrecognised key in the multi-row VALUES list `_bulk_upsert`
        builds fails the WHOLE insert -- every sample in the batch, not
        just the one carrying the extra key."""
        assert "polyline" in _WORKOUT_PROMOTION_ONLY
        assert "route_state" in _WORKOUT_PROMOTION_ONLY
        assert "distance_m" in _WORKOUT_PROMOTION_ONLY
        w = WorkoutSample(time=T, type="walking", duration_s=8217,
                          polyline=TRACK, route_state="none", distance_m=1.0)
        dumped = w.model_dump(exclude=_WORKOUT_PROMOTION_ONLY)
        for gone in ("polyline", "route_state", "distance_m"):
            assert gone not in dumped
        for kept in ("time", "type", "duration_s", "kcal", "avg_hr",
                     "max_hr", "source", "title"):
            assert kept in dumped

    def test_activities_carries_both(self):
        cols = models.Activity.__table__.columns.keys()
        assert "polyline" in cols
        assert "route_state" in cols
        assert "polyline" in activity_sink.PROVIDER_COLUMNS
        assert "route_state" in activity_sink.PROVIDER_COLUMNS


class TestTheRouteLandsOnThePromotedRow:
    def test_a_track_reaches_the_row(self):
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {SID: TRACK}, {},
        )
        assert values["polyline"] == TRACK

    def test_a_withheld_route_records_the_state_and_no_track(self):
        """The 2026-09-19 walk, exactly as the probe found it."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {},
            {SID: "consent_required"},
        )
        assert values["polyline"] is None
        assert values["route_state"] == "consent_required"

    def test_an_unasked_session_records_neither(self):
        """Nobody asked. Not the same as `route_state="none"`, and writing
        "none" here would claim Health Connect was consulted."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {}, {},
        )
        assert values["polyline"] is None
        assert values["route_state"] is None
        assert "polyline" in values and "route_state" in values, (
            "must be explicit Nones so a fresh INSERT stores real NULLs"
        )

    def test_none_maps_behave_like_empty_ones(self):
        """The post-Strava-sync rescan in `strava.py` calls the promoter
        with no batch context, so these are None there rather than {}."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, None, None, None,
        )
        assert values["polyline"] is None
        assert values["route_state"] is None

    def test_lookup_is_keyed_by_source_id(self):
        other = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {},
            {other: TRACK}, {other: "none"},
        )
        assert values["polyline"] is None
        assert values["route_state"] is None


class TestNeverOverwritesARicherRoute:
    """`upsert_activity`'s skip-None-on-update rule is what enforces this
    for every provider column. These confirm route data gets no exemption
    -- easy to grant accidentally to a column that has just been added.
    """

    def test_no_route_this_round_does_not_blank_a_stored_track(self):
        """A backfill re-run over a session whose route was already found,
        or the Strava rescan passing no batch context at all, must leave
        the polyline exactly where it is."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {}, {},
        )
        written = _update_set(values)
        assert "polyline" not in written
        assert "route_state" not in written

    def test_a_real_track_does_reach_the_update(self):
        """Skip-None is about None, not about the column being unwritable
        on an update -- a second read that finally gets the route has to
        be able to store it."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {SID: TRACK}, {},
        )
        assert _update_set(values)["polyline"] == TRACK

    def test_a_promotion_cannot_reach_another_providers_row_at_all(self):
        """The stronger guarantee, above the column rule: a promoted row
        is keyed `(healthconnect, <start isoformat>)`, so it is physically
        a different row from Strava's or Garmin's and the upsert cannot
        target theirs. And when a richer provider's activity OVERLAPS,
        the session is skipped outright -- and a row promoted earlier is
        retired in favour of the richer one."""
        values = activity_sink._hc_activity_values(
            _hc_workout(), "walking", T, SID, {}, {SID: TRACK}, {},
        )
        assert values["source"] == activity_sink.HC_SOURCE
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert "Activity.source != HC_SOURCE" in src
        assert "skipped_overlap += 1" in src
        assert "superseded by a richer provider" in src


class TestTrailLinkingFollowsTheRoute:
    def test_linking_runs_only_when_a_track_was_actually_read(self):
        """`link_trail` was unconditionally False on the premise that
        these sessions have no GPS. That premise is what SA-P3 falsified.
        It stays off without a polyline: `_auto_link_trail` reads
        `act.polyline` and would cost a query per indoor session to do
        nothing."""
        src = inspect.getsource(activity_sink.promote_health_connect_workouts)
        assert 'link_trail=values.get("polyline") is not None' in src

    def test_upsert_gates_the_link_on_a_polyline_too(self):
        src = inspect.getsource(activity_sink.upsert_activity)
        assert "if link_trail and act.trail_id is None and act.polyline:" in src


class TestTheSimplifiedCopyIsInvalidatedOnANewTrack:
    """`polyline_simple` is a cached RDP simplification used by the
    all-activities map. A Health Connect track arriving on a row that had
    none must drop it so the map endpoint recomputes -- otherwise the
    detail page draws the new route and the overview map draws nothing.
    """

    def test_a_changed_polyline_clears_the_simplification(self):
        src = inspect.getsource(activity_sink.upsert_activity)
        assert 'update_set["polyline_simple"] = None' in src
        assert "existing.polyline != new_polyline" in src


class TestTheIngestSideChannel:
    def test_the_batch_builds_both_maps_with_an_is_not_none_filter(self):
        """The filter is what makes "this sample says nothing" different
        from "this sample says there is nothing". A sample with a null
        polyline must contribute no key, so the update set never carries
        it and a stored track survives."""
        from myvitals.api import ingest
        src = inspect.getsource(ingest.ingest_batch)
        assert "polyline_by_start" in src
        assert "route_state_by_start" in src
        assert "if w.polyline is not None" in src
        assert "if w.route_state is not None" in src

    def test_promotion_failure_still_cannot_fail_an_ingest(self):
        """Unchanged by SA-P3, and worth re-pinning now that the promotion
        does more: the raw samples are the irreplaceable part."""
        from myvitals.api import ingest
        src = inspect.getsource(ingest.ingest_batch)
        assert "HC-1 promotion failed" in src


class TestTheStateVocabularyIsShared:
    """Three spellings, in four places -- the Kotlin `RouteRead.wireState`,
    the Pydantic field, the column, and both clients' copy. A typo makes
    the card fall through to its default branch and say "nobody asked"
    about a route that is sitting there withheld, which is the exact
    failure this whole finding is about.
    """

    def test_the_backend_never_invents_a_fourth_value(self):
        """The backend stores what the phone measured and never derives a
        state of its own -- same rule as `analytics/compare.py` owning
        `better`, in the other direction."""
        src = inspect.getsource(activity_sink._hc_activity_values)
        assert '"route_state": (route_state_by_start or {}).get(source_id)' in src
        # The docstring names the states to explain them; the code must
        # not, because naming one in code is how a branch on it starts.
        body = src.split('"""')[-1]
        assert '"consent_required"' not in body
        assert '"none"' not in body

    def test_the_two_clients_spell_the_states_the_same_way(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        web = (root / "frontend/src/views/ActivityDetail.vue").read_text()
        phone = (
            root
            / "android/app/src/main/kotlin/app/myvitals/ui/activities"
            / "ActivityDetailScreen.kt"
        ).read_text()
        kotlin_states = (
            root
            / "android/app/src/main/kotlin/app/myvitals/health"
            / "HealthConnectGateway.kt"
        ).read_text()
        for state in ('"consent_required"', '"none"'):
            assert state in web, f"web is missing {state}"
            assert state in phone, f"phone is missing {state}"
            assert state in kotlin_states, f"RouteRead is missing {state}"


class TestTheEmptyStateExistsOnBothSurfaces:
    """The card vanishing IS the reported bug -- "it shows no path on the
    map" was a missing card, not a broken renderer. Parity is enforced by
    `scripts/parity_check.py` for the file pair; this pins the behaviour.
    """

    @staticmethod
    def _read(rel: str) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[2] / rel).read_text()

    def test_the_web_renders_a_route_card_without_a_polyline(self):
        web = self._read("frontend/src/views/ActivityDetail.vue")
        assert "v-else-if=\"activity.source === 'healthconnect'\"" in web
        assert "routeEmptyText" in web

    def test_the_phone_renders_one_too(self):
        phone = self._read(
            "android/app/src/main/kotlin/app/myvitals/ui/activities/"
            "ActivityDetailScreen.kt",
        )
        assert "RouteMissingCard" in phone

    def test_the_web_offers_no_button_it_cannot_honour(self):
        """The route lives in Health Connect on the phone. A browser
        cannot read it, and Google requires the read to happen while the
        user is engaged with the app's own UI -- so the web says where to
        go rather than offering an action that would always fail."""
        web = self._read("frontend/src/views/ActivityDetail.vue")
        assert "phone app" in web

    def test_the_settled_state_offers_no_action_on_either_surface(self):
        """`none` means the provider answered. A button there can only
        ever fail, and a card that invites a pointless tap is how an
        honest empty state turns back into noise."""
        web = self._read("frontend/src/views/ActivityDetail.vue")
        assert "activity.route_state !== 'none'" in web
        phone = self._read(
            "android/app/src/main/kotlin/app/myvitals/ui/activities/"
            "ActivityDetailScreen.kt",
        )
        assert 'val actionable = a.routeState != "none"' in phone


class TestARetiredDuplicateDoesNotTakeTheTrackWithIt:
    """The 2026-09-19 walk is exactly this case.

    TWO Health Connect writers published it -- `com.fitbit.FitbitMobile` at
    8217 s and `nl.appyhapps.healthsync` at 8213 s, four seconds apart, both
    answering CONSENT_REQUIRED to the probe. The dedupe keeps one and
    DELETES the other, and nothing guarantees the survivor is the one whose
    route Health Connect released. Until routes existed a promoted row had
    no track to lose, so `_retire_promotion` never had to think about it.

    Losing the only copy of a track the user had just granted access to
    would be the worst available outcome for a feature whose whole point is
    that the track appears -- and it would look like the grant had not
    worked.
    """

    def test_the_track_is_carried_to_the_survivor(self):
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "winner.polyline = stale.polyline" in src

    def test_only_onto_a_survivor_that_has_none(self):
        """Strictly gap-filling. A Strava or Garmin row that clashed and won
        keeps its own full-fidelity track -- the carry must never be a
        downgrade dressed as a rescue."""
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "if winner is not None and stale.polyline and not winner.polyline:" in src

    def test_the_cached_simplification_goes_with_the_old_track(self):
        """`polyline_simple` is derived from the value being replaced. Left
        behind, the detail page draws the carried route and the overview
        map draws whatever the winner used to have -- or nothing."""
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "winner.polyline_simple = None" in src

    def test_the_explanation_is_carried_too(self):
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "winner.route_state = stale.route_state" in src

    def test_the_carry_happens_before_the_delete(self):
        """Reading it off the row afterwards would read nothing."""
        src = inspect.getsource(activity_sink._retire_promotion)
        assert src.index("winner.polyline = stale.polyline") < src.index(
            "delete(models.Activity)",
        )

    def test_a_retirement_with_no_survivor_still_cannot_delete_a_track(self):
        """`winner=None` is the cross-provider clash path before a winner
        row is known, and the user-owned veto. The guard is on `winner is
        not None`, so there is no branch where a track is dropped onto the
        floor by a carry that silently did nothing -- either it moves or
        the row that holds it is not being deleted for a reason this
        function chose."""
        src = inspect.getsource(activity_sink._retire_promotion)
        # Both carries are guarded on a winner existing.
        assert src.count("if winner is not None and stale.") == 2


class TestTheBulkImportPathCannotWipeIt:
    """Found while wiring this, and it is the same bug that once erased
    every Garmin track.

    `_upsert_activities_chunk` is the one Activity writer that bypasses the
    sink, and it cannot honour the skip-None rule -- one bulk statement
    covers many rows, so there is no per-row "this provider said nothing".
    It builds its update set from `stmt.excluded`, which for a column no
    import parser emits is the column default: NULL. Adding `route_state`
    to `PROVIDER_COLUMNS` therefore silently enrolled it in "reset to NULL
    on the next import", which would turn "Health Connect is withholding a
    route for this session" back into "nobody asked" -- an actionable card
    quietly becoming an inert one, on a schedule nobody associates with it.
    """

    def test_route_state_is_excluded_alongside_polyline(self):
        from myvitals.api import imports
        src = inspect.getsource(imports._upsert_activities_chunk)
        assert 'set(PROVIDER_COLUMNS) - {"polyline", "route_state"}' in src

    def test_neither_reaches_the_update_set(self):
        from myvitals.api import imports
        src = inspect.getsource(imports._upsert_activities_chunk)
        writable = set(activity_sink.PROVIDER_COLUMNS) - {"polyline", "route_state"}
        assert "polyline" not in writable
        assert "route_state" not in writable
        # ...and the rest still is, so this is an exclusion, not a
        # rewrite of the allowlist.
        assert "distance_m" in writable
        assert "PROVIDER_COLUMNS" in src


class TestTheConsentFlowIsTheOneThatCanWork:
    """The trap this feature is one line away from, and the one the first
    cut of it fell into.

    `android.permission.health.READ_EXERCISE_ROUTES` looks like every other
    Health Connect permission and is not one. Its platform javadoc:
    "This permission can only be granted manually by a user in Health
    Connect settings or in the route request activity which can be launched
    using ACTION_REQUEST_EXERCISE_ROUTE. Attempts to request the permission
    by applications will be ignored." Protection level dangerous, added in
    API 35, where this app's minSdk is 28.

    So a button wired to the ordinary permission sheet opens a sheet that
    silently does nothing, and on any pre-Android-15 phone the permission
    does not exist at all. The per-session `ExerciseRouteRequestContract`
    is the path that works, and it hands back the route rather than a
    grant.
    """

    @staticmethod
    def _read(rel: str) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[2] / rel).read_text()

    def test_the_permission_is_declared(self):
        """Required even though it is never requested: without the manifest
        entry the toggle does not appear in Health Connect settings, so the
        user has no way to grant it there either."""
        manifest = self._read("android/app/src/main/AndroidManifest.xml")
        assert "android.permission.health.READ_EXERCISE_ROUTES" in manifest

    def test_it_is_never_pushed_through_a_permission_request(self):
        for rel in (
            "android/app/src/main/kotlin/app/myvitals/ui/activities/"
            "ActivityDetailScreen.kt",
            "android/app/src/main/kotlin/app/myvitals/MainActivity.kt",
        ):
            src = self._read(rel)
            assert "launch(setOf(gateway.routePermission))" not in src
            assert "permissionLauncher.launch(setOf(" not in src

    def test_the_card_launches_the_per_session_route_request(self):
        src = self._read(
            "android/app/src/main/kotlin/app/myvitals/ui/activities/"
            "ActivityDetailScreen.kt",
        )
        assert "ExerciseRouteRequestContract()" in src
        assert "routeRequest.launch(session.metadata.id)" in src

    def test_routes_are_not_in_the_required_permission_set(self):
        """`requiredPermissions` is the gate `SyncWorker` gets past before
        reading anything. An unrequestable permission in it would hold that
        gate shut forever -- no heart rate, no sleep, no steps -- and
        report itself through the "Health Connect permissions lost" banner
        as a revoked grant."""
        gw = self._read(
            "android/app/src/main/kotlin/app/myvitals/health/"
            "HealthConnectGateway.kt",
        )
        required = gw.split("val requiredPermissions")[1].split("    )")[0]
        assert "ROUTE" not in required

    def test_a_denied_route_never_sets_permissions_lost(self):
        """Same rule from the other side: the worker's route wrapper must
        not route a route failure into the banner, because the banner means
        telemetry has stopped."""
        sw = self._read(
            "android/app/src/main/kotlin/app/myvitals/sync/SyncWorker.kt",
        )
        wrapper = sw.split("private suspend fun safeRouteProbe")[1].split(
            "\n    /**",
        )[0]
        assert "permissionsLost" not in wrapper


class TestTheRouteIsNeverLogged:
    """A GPS track is the most sensitive thing this app touches -- it is a
    map of where the user lives. `app_logs` is shipped to the server and
    rendered in a log viewer.
    """

    @staticmethod
    def _read(rel: str) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[2] / rel).read_text()

    def test_the_gateway_encodes_and_discards_the_coordinates(self):
        gw = self._read(
            "android/app/src/main/kotlin/app/myvitals/health/"
            "HealthConnectGateway.kt",
        )
        # RouteRead.Track carries a polyline and a count, and has nowhere
        # to put a position -- the cheapest way to keep one out of a log.
        assert "data class Track(val polyline: String, val points: Int)" in gw

    def test_the_probe_line_logs_a_count_not_a_position(self):
        for rel in (
            "android/app/src/main/kotlin/app/myvitals/sync/SyncWorker.kt",
            "android/app/src/main/kotlin/app/myvitals/health/RouteBackfill.kt",
        ):
            src = self._read(rel)
            assert "points=%d" in src
            assert "latitude" not in src
            assert "longitude" not in src

    def test_the_session_title_is_still_not_copied(self):
        """Unchanged, and re-pinned here because the promotion grew: the
        title is the field that carries a location name."""
        src = (
            inspect.getsource(activity_sink.promote_health_connect_workouts)
            + inspect.getsource(activity_sink._hc_activity_values)
        )
        assert "w.title" not in src
