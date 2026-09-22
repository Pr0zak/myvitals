"""Health Connect dedupe, from the provider side and on content.

Two defects, both exposed by one walk on 2026-09-19. Health Connect
published it at 14:05:05 (8,217 s) and Strava published the same walk at
14:05:06 (8,213 s). The Health Connect row had already been promoted into
`activities`; the Strava row simply landed beside it, and the duplicate sat
in the feed until a human ran the maintenance endpoint.

**Reconciliation only ever ran from one side.** Both calls to
`_retire_promotion` were inside `promote_health_connect_workouts`, which
scans the Health Connect sessions in the batch being ingested. A Strava,
Garmin or Concept2 sync that superseded an already-promoted row therefore
triggered nothing at all, and the clash would only be noticed if a later
Health Connect batch happened to carry that same session again -- which,
for a session recorded days ago, never happens.

**The winner was chosen by provider, not by content.** The rule's own
docstring stated the premise: "Providers with GPS are strictly richer".
SA-P3 made that false. In this case the Health Connect row held a
5,598-point route and the Strava row held no polyline at all -- the
supposedly richer provider was the poorer row. The outcome was right only
because the carry filled the winner's empty polyline; where the winner holds
its own coarser track the carry declined, and the better track would have
been deleted with the row.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone

import polyline as pl
from sqlalchemy import Delete

from myvitals.analytics.geo import track_extent
from myvitals.db import models
from myvitals.integrations import activity_sink
from myvitals.integrations.activity_sink import (
    CARRYABLE_COLUMNS,
    HC_SOURCE,
    PROVIDER_COLUMNS,
    TRACK_MARGIN,
    USER_OWNED_COLUMNS,
    track_is_materially_better,
)

T = datetime(2026, 9, 19, 14, 5, 5, tzinfo=timezone.utc)


# ── Track fixtures, shaped from the production measurements ─────────
#
# The four overlapping pairs in this database that carry a track on BOTH
# sides are the only direct evidence of what two recordings of one event
# look like, so the fixtures reproduce their measured shapes rather than
# inventing new ones.

def _line(n: int, metres: float, *, lat0: float = 41.0) -> str:
    """A straight track of `n` points spanning roughly `metres`."""
    step = (metres / 111_320.0) / max(n - 1, 1)
    return pl.encode([(lat0 + i * step, -87.0) for i in range(n)])


def _jitter(n: int, metres: float) -> str:
    """`n` points confined to a `metres`-wide box -- a stationary fragment.

    The 2026-02-22 walk: 1,760 points inside a 149 m box, for a walk both
    rows agree was 1,965.9 m.
    """
    d = metres / 111_320.0
    return pl.encode([
        (41.0 + (i % 7) * d / 7, -87.0 + (i % 5) * d / 5) for i in range(n)
    ])


#: Health Connect's actual 2026-09-19 route: 5,598 points, 1,076 m span.
HC_ROUTE = _line(5598, 1076.0)
#: Strava's median stored track is 334 points -- the FIT decode cap at work.
STRAVA_TRACK = _line(334, 1076.0)
#: A real row in production: strava/2025-12-11, five points, 25 m of path.
STRAVA_STUB = _line(5, 25.0)


class TestPointCountIsTheWrongDiscriminator:
    """It is the available and obvious number. It measures the encoder.

    Every provider track in this database is decimated before it is ever
    stored: `fit_tracks._MAX_POLYLINE_POINTS` caps a FIT decode at 500
    points, and the retired OAuth path stored Strava's own server-thinned
    `map.summary_polyline`. A Health Connect route is the raw sample stream.
    Measured on production, Strava's median track is 334 points and the one
    Health Connect route in the table is 5,598.
    """

    def test_the_provider_cap_that_makes_it_meaningless_still_exists(self):
        from myvitals.integrations import fit_tracks
        assert fit_tracks._MAX_POLYLINE_POINTS == 500

    def test_a_denser_track_does_not_win_on_density_alone(self):
        """5,598 points against 334, describing the same ground. Seventeen
        times the samples and not one metre more of route."""
        dense, sparse = track_extent(HC_ROUTE), track_extent(STRAVA_TRACK)
        assert len(pl.decode(HC_ROUTE)) > 16 * len(pl.decode(STRAVA_TRACK))
        assert round(dense[0]) == round(sparse[0])
        assert not track_is_materially_better(HC_ROUTE, STRAVA_TRACK)
        assert not track_is_materially_better(STRAVA_TRACK, HC_ROUTE)

    def test_the_denser_track_can_be_the_fragment(self):
        """On the four production pairs where both sides carry a track the
        denser side has more points in all four and is the poorer
        description of the route in three."""
        fragment = _jitter(1760, 149.0)      # the 2026-02-22 fitbit walk
        complete = _line(229, 1762.0)        # the 2026-02-22 strava walk
        assert len(pl.decode(fragment)) > 7 * len(pl.decode(complete))
        assert track_is_materially_better(complete, fragment)
        assert not track_is_materially_better(fragment, complete)

    def test_the_rule_never_counts_points(self):
        src = inspect.getsource(activity_sink.track_is_materially_better)
        body = src.split('"""')[-1]
        assert "len(" not in body
        assert "decode" not in body
        # Nor does the measurement it delegates to expose one to be reached
        # for -- `track_extent` returns two distances and nothing else.
        assert len(track_extent(HC_ROUTE)) == 2


class TestTheRichnessRuleIsMeasurable:
    def test_coverage_is_measured_two_ways(self):
        span, path = track_extent(_line(100, 1000.0))
        assert 950 < span < 1050
        assert 950 < path < 1050

    def test_span_alone_is_blind_to_a_truncated_circuit(self):
        """Half the laps of a circuit reach the same ground, which is why
        the traversed length gets a say once the spans are comparable."""
        loop = [(41.0, -87.0), (41.005, -87.0), (41.005, -86.995),
                (41.0, -86.995), (41.0, -87.0)]
        full = pl.encode(loop * 6)
        half = pl.encode(loop * 2)
        assert round(track_extent(full)[0]) == round(track_extent(half)[0])
        assert track_is_materially_better(full, half)
        assert not track_is_materially_better(half, full)

    def test_length_cannot_win_from_inside_a_smaller_box(self):
        """Otherwise a jittery 1 Hz stream standing still beats a track that
        actually goes somewhere -- the 149 m box against a 1,965.9 m walk."""
        assert not track_is_materially_better(
            _jitter(4000, 149.0), _line(229, 1762.0),
        )

    def test_any_track_beats_none(self):
        assert track_is_materially_better(HC_ROUTE, None)
        assert track_is_materially_better(HC_ROUTE, "")
        assert not track_is_materially_better(None, HC_ROUTE)

    def test_a_degenerate_track_never_displaces_a_real_one(self):
        """`polyline.decode` raises IndexError on a truncated string, and a
        single-point track measures as nothing. Neither may take a route's
        place, and neither may take down an ingest."""
        for junk in ("?", "~~~~~~", pl.encode([(41.0, -87.0)])):
            assert track_extent(junk) == (0.0, 0.0)
            assert not track_is_materially_better(junk, HC_ROUTE)

    def test_the_five_point_stub_that_exists_in_production(self):
        """strava/2025-12-11 really is stored as five points and 25 m. It
        must never displace a complete route."""
        assert not track_is_materially_better(STRAVA_STUB, HC_ROUTE)
        assert track_is_materially_better(HC_ROUTE, STRAVA_STUB)

    def test_a_track_is_never_better_than_itself(self):
        """The stability property. A re-sync bringing the identical track
        must not churn the row, invalidate `polyline_simple` and make the
        map recompute forever."""
        for t in (HC_ROUTE, STRAVA_TRACK, STRAVA_STUB, _jitter(500, 149.0)):
            assert not track_is_materially_better(t, t)

    def test_the_margin_is_sourced_from_the_measurement(self):
        """This project refuses constants it cannot source. The span ratios
        of the four production pairs are 1.00, 1.08, 3.51 and 11.83 and the
        path ratios are 1.22, 1.90, 3.07 and 3.68; 2.0 sits inside both
        empty bands."""
        assert TRACK_MARGIN == 2.0
        doc = inspect.getdoc(activity_sink) or ""
        src = inspect.getsource(activity_sink)
        marker = src[src.index("TRACK_MARGIN = 2.0") - 1400:]
        for ratio in ("1.08", "3.51", "1.90", "3.07"):
            assert ratio in marker, ratio
        assert doc  # module docstring still records the design decision


class TestNothingTheLosingRowHoldsIsLost:
    """The carry used to be two hand-picked columns. A function that deletes
    a row has to answer "what can be lost", and answering it one field at a
    time is how the GPS track came to be at risk for a release."""

    def test_every_provider_column_is_classified(self):
        classified = set(CARRYABLE_COLUMNS) | activity_sink._NOT_CARRYABLE
        assert classified == set(PROVIDER_COLUMNS)

    def test_the_carry_set_is_derived_not_retyped(self):
        """So a column added to `PROVIDER_COLUMNS` has to be considered
        here, rather than silently falling through the gap."""
        src = inspect.getsource(activity_sink)
        assert "for c in PROVIDER_COLUMNS if c not in _NOT_CARRYABLE" in src

    def test_everything_health_connect_writes_is_carryable(self):
        """`_hc_activity_values` is the full list of what a promoted row can
        hold. Every provider column in it must be able to move."""
        written = inspect.getsource(activity_sink._hc_activity_values)
        for col in ("distance_m", "polyline", "route_state",
                    "avg_hr", "max_hr", "kcal"):
            assert f'"{col}":' in written
            assert col in CARRYABLE_COLUMNS

    def test_the_survivors_own_account_of_the_event_is_not_spliced(self):
        """A second recorder disagreeing about when a walk started is not a
        gap. Splicing one recorder's duration onto another's start produces
        an interval neither of them observed."""
        for col in ("type", "start_at", "duration_s", "name", "raw"):
            assert col not in CARRYABLE_COLUMNS

    def test_the_borrowed_title_stays_banned(self):
        """`name` comes from whichever app wrote the Health Connect record
        and is exactly the field that carries a location."""
        assert "name" in activity_sink._NOT_CARRYABLE

    def test_user_owned_columns_keep_their_own_conflict_veto(self):
        """Two different trails on two rows is a conflict between two of the
        user's own decisions, and this is not the code to resolve it."""
        src = inspect.getsource(activity_sink._retire_promotion)
        assert "USER_OWNED_COLUMNS" in src
        assert "conflicts" in src
        assert set(USER_OWNED_COLUMNS).isdisjoint(CARRYABLE_COLUMNS)


# ── The carry, run for real against plain ORM instances ─────────────

class _Result:
    def __init__(self, obj: object) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> object:
        return self._obj

    def scalars(self) -> _Result:
        return self

    def first(self) -> object:
        return self._obj

    def all(self) -> list:
        return list(self._obj) if isinstance(self._obj, list) else []


class _Session:
    """Just enough of `AsyncSession` for `_retire_promotion`.

    It does one SELECT for the row it is retiring and one DELETE. No
    database is needed to check that the carry moves what it claims to --
    `models.Activity` is a plain ORM class.
    """

    def __init__(self, stale: models.Activity) -> None:
        self.stale = stale
        self.deletes = 0

    async def execute(self, stmt: object) -> _Result:
        if isinstance(stmt, Delete):
            self.deletes += 1
            return _Result(None)
        return _Result(self.stale)


def _act(source: str, **kw: object) -> models.Activity:
    defaults: dict[str, object] = dict(
        source=source, source_id="x", type="walking", start_at=T,
        duration_s=8217,
    )
    defaults.update(kw)
    return models.Activity(**defaults)


def _retire(stale: models.Activity, winner: models.Activity | None) -> bool:
    db = _Session(stale)
    return asyncio.run(
        activity_sink._retire_promotion(db, "sid", "test", winner=winner)
    )


class TestTheCarryActuallyMovesEverything:
    def test_the_2026_09_19_walk(self):
        """Health Connect held the route and the Strava row held none."""
        stale = _act(HC_SOURCE, polyline=HC_ROUTE, route_state="consent_required",
                     distance_m=6361.2, kcal=410.0, avg_hr=104.0, trail_id=13)
        winner = _act("strava", source_id="20243722685", duration_s=8213)
        assert _retire(stale, winner) is True
        assert winner.polyline == HC_ROUTE
        assert winner.route_state == "consent_required"
        assert winner.distance_m == 6361.2
        assert winner.kcal == 410.0
        assert winner.avg_hr == 104.0
        assert winner.trail_id == 13

    def test_the_case_the_old_gap_fill_got_wrong(self):
        """Same walk, but the Strava row holds a five-point stub. Under
        gap-filling the 5,598-point route was simply deleted with the row."""
        stale = _act(HC_SOURCE, polyline=HC_ROUTE)
        winner = _act("strava", polyline=STRAVA_STUB, polyline_simple="cached")
        assert _retire(stale, winner) is True
        assert winner.polyline == HC_ROUTE
        assert winner.polyline_simple is None

    def test_a_comparable_track_on_the_winner_is_left_alone(self):
        """No churn, and no invalidation of the cached simplification."""
        stale = _act(HC_SOURCE, polyline=HC_ROUTE)
        winner = _act("strava", polyline=STRAVA_TRACK,
                      polyline_simple="cached")
        assert _retire(stale, winner) is True
        assert winner.polyline == STRAVA_TRACK
        assert winner.polyline_simple == "cached"

    def test_the_winners_own_measurements_are_never_overwritten(self):
        stale = _act(HC_SOURCE, distance_m=6100.0, avg_hr=99.0)
        winner = _act("strava", distance_m=6361.2, avg_hr=104.0)
        assert _retire(stale, winner) is True
        assert winner.distance_m == 6361.2
        assert winner.avg_hr == 104.0

    def test_a_conflicting_user_decision_still_vetoes_the_delete(self):
        stale = _act(HC_SOURCE, trail_id=13, polyline=HC_ROUTE)
        winner = _act("strava", trail_id=7)
        db = _Session(stale)
        kept = asyncio.run(
            activity_sink._retire_promotion(db, "sid", "test", winner=winner)
        )
        assert kept is False
        assert db.deletes == 0
        # And nothing was mutated on the way to declining.
        assert winner.trail_id == 7
        assert winner.polyline is None

    def test_no_winner_means_no_delete_when_the_row_holds_a_decision(self):
        stale = _act(HC_SOURCE, notes="felt good")
        db = _Session(stale)
        assert asyncio.run(
            activity_sink._retire_promotion(db, "sid", "test", winner=None)
        ) is False
        assert db.deletes == 0


# ── Defect 1: the rule now runs from both sides ─────────────────────

def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class TestReconciliationRunsFromTheProviderSide:
    def test_the_provider_side_exists_at_all(self):
        assert callable(activity_sink.reconcile_promotions)

    def test_the_shared_sink_is_where_it_lives(self):
        """Every provider funnels through `upsert_activity`, so attaching it
        to any one integration would leave the others uncovered -- which is
        the shape of the original defect."""
        src = inspect.getsource(activity_sink.upsert_activity)
        assert "await reconcile_promotions(db, act)" in src

    def test_the_predicate_is_the_promotions_own_with_roles_swapped(self):
        """Not a similar test -- the same inequality. Two halves that can
        disagree produce a row the scan would re-promote, or one it would
        have skipped surviving as a duplicate."""
        promote = _normalise(
            inspect.getsource(activity_sink.promote_health_connect_workouts))
        recon = _normalise(
            inspect.getsource(activity_sink.reconcile_promotions))
        overlap = _normalise('''
            func.extract("epoch", start - models.Activity.start_at)
            < func.coalesce(models.Activity.duration_s, 0)
        ''')
        assert overlap in promote
        assert overlap in recon
        assert ".where(models.Activity.start_at < end)" in _normalise(recon)
        assert ".where(models.Activity.start_at < end)" in _normalise(promote)

    def test_it_retires_every_overlapping_promotion_not_the_first(self):
        """Promotion tests each session independently and would have skipped
        all of them. The three 20-minute `workout` sessions on 2026-08-23 are
        the shape that needs it."""
        src = inspect.getsource(activity_sink.reconcile_promotions)
        assert ".limit(1)" not in src
        assert "for stale_id in stale_ids:" in src

    def test_the_query_compiles_against_the_real_model(self):
        """Source inspection cannot catch a bad column reference; this can.
        The same gap `test_hc_promotion.TestTheQueryActuallyCompiles` exists
        for."""
        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        start = T
        end = start + timedelta(seconds=8213)
        stmt = (
            select(models.Activity.source_id)
            .where(models.Activity.source == HC_SOURCE)
            .where(models.Activity.start_at < end)
            .where(
                func.extract("epoch", start - models.Activity.start_at)
                < func.coalesce(models.Activity.duration_s, 0)
            )
        )
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "activities.source_id" in sql
        assert "EXTRACT" in sql.upper()

    def test_a_failure_cannot_cost_the_ingest(self):
        """The row is the valuable part. A failure here leaves the duplicate
        on screen, which is exactly the state that existed before."""
        src = inspect.getsource(activity_sink.upsert_activity)
        assert "HC reconciliation failed" in src


class TestItCannotRecurse:
    def test_the_promotion_opts_out_explicitly(self):
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts)
        assert "reconcile=False" in src

    def test_and_it_refuses_health_connect_rows_anyway(self):
        """Two guards, neither load-bearing alone."""
        src = inspect.getsource(activity_sink.reconcile_promotions)
        assert "if act.source == HC_SOURCE:" in src
        assert "return 0" in src
        upsert = inspect.getsource(activity_sink.upsert_activity)
        assert "source != HC_SOURCE" in upsert

    def test_a_promotion_reconciling_would_retire_itself(self):
        """Why the guard is not cosmetic: the row it just wrote overlaps
        itself, and `_retire_promotion` is keyed on source_id alone."""
        act = _act(HC_SOURCE, source_id=T.isoformat())
        assert asyncio.run(
            activity_sink.reconcile_promotions(_Session(act), act)
        ) == 0


class TestItDoesNotFireOnAnOrdinaryUpdate:
    def test_gated_on_the_row_being_new(self):
        """A re-sync changes no row's existence, so there is nothing for the
        overlap rule to notice that it did not notice the first time."""
        src = inspect.getsource(activity_sink.upsert_activity)
        assert "if reconcile and existing is None and source != HC_SOURCE:" in src

    def test_the_existing_lookup_already_happens_anyway(self):
        """No extra query is added for the gate -- `upsert_activity` already
        reads the row to decide whether to invalidate `polyline_simple`."""
        src = inspect.getsource(activity_sink.upsert_activity)
        assert src.index("existing = (await db.execute(") < src.index(
            "if reconcile and existing is None")


class TestItCannotMakeABulkImportQuadratic:
    def test_the_historical_importers_do_not_reach_the_sink(self):
        """`api/imports._upsert_activities_chunk` is deliberately the one
        Activity writer outside this sink, so a three-year backfill fires no
        per-row side-effects at all."""
        from myvitals.api import imports
        src = inspect.getsource(imports._upsert_activities_chunk)
        assert "upsert_activity" not in src
        assert "insert(models.Activity).values(rows)" in src

    def test_it_is_one_indexed_lookup_and_no_scan(self):
        src = inspect.getsource(activity_sink.reconcile_promotions)
        # Bounded to the promoted rows and to an interval, both indexed.
        assert "models.Activity.source == HC_SOURCE" in src
        assert "models.Activity.start_at < end" in src
        # One statement, not one per candidate.
        assert src.count("await db.execute(") == 1

    def test_the_columns_it_filters_on_are_indexed(self):
        assert models.Activity.__table__.c.start_at.index
        assert models.Activity.__table__.primary_key.columns.keys()[0] == "source"

    def test_imports_are_still_reconciled_by_the_full_sweep(self):
        """From the promotion side, which walks all history when `since` is
        None -- so the path that skips the sink is not left uncovered."""
        from myvitals.api import strava as strava_api
        src = inspect.getsource(strava_api.promote_health_connect)
        assert "promote_health_connect_workouts(db)" in src


class TestOnlyAPromotionIsEverDeleted:
    """The scope that makes the delete safe, kept deliberately.

    Choosing the survivor genuinely on content means sometimes deleting a
    provider row, and that is not symmetric with deleting a promotion:
    `promote_health_connect_workouts` checks for a clash BEFORE it writes, so
    a retired promotion is never recreated, while no provider sync has an
    equivalent check -- a deleted Strava row is rebuilt by the next cookie
    sync, reconciled away again, and rebuilt again.
    """

    def test_the_delete_is_scoped_to_health_connect_and_one_source_id(self):
        src = inspect.getsource(activity_sink._retire_promotion)
        delete_stmt = src[src.index("delete(models.Activity)"):]
        assert "models.Activity.source == HC_SOURCE" in delete_stmt
        assert "models.Activity.source_id == source_id" in delete_stmt

    def test_reconciliation_deletes_nothing_itself(self):
        """It can only route through `_retire_promotion`, which is scoped."""
        src = inspect.getsource(activity_sink.reconcile_promotions)
        assert "delete(" not in src
        assert "_retire_promotion(" in src

    def test_the_sink_has_exactly_one_delete_of_an_activity(self):
        src = inspect.getsource(activity_sink)
        assert src.count("delete(models.Activity)") == 1

    def test_the_promotion_scan_cannot_recreate_a_retired_row(self):
        """The no-flip-flop guarantee at row level: the scan's skip test is
        the same overlap the reconciliation used, so the provider row that
        caused the delete also blocks the re-promotion, permanently."""
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts)
        assert "Activity.source != HC_SOURCE" in src
        assert "skipped_overlap += 1" in src
        assert src.index("if clash is not None:") < src.index(
            "await upsert_activity(")

    def test_a_dangling_completion_pointer_is_a_real_cost(self):
        """`strength_workouts` points at an activity by (source, source_id)
        with no foreign key behind it, which is one of the reasons deleting a
        provider row is not free."""
        cols = models.StrengthWorkout.__table__.c
        assert "completed_by_activity_source" in cols
        assert "completed_by_activity_source_id" in cols


class TestAPoorerSyncCannotEraseARicherTrack:
    """The founding rule of the module, applied to the case it only ever
    covered for None.

    `parse_fit_bytes` returning nothing was fixed by skip-None. A FIT that
    parses to five points is not an absent track, so skip-None lets it
    through -- and it would overwrite a complete one. It matters most for a
    track the dedupe CARRIED onto this row from a row it then deleted: that
    copy is the only one left.
    """

    def test_the_guard_is_on_the_update_path(self):
        src = inspect.getsource(activity_sink.upsert_activity)
        assert "track_is_materially_better(existing.polyline, new_polyline)" in src
        assert 'update_set.pop("polyline", None)' in src

    def test_it_uses_the_same_comparison_as_the_carry(self):
        """One primitive, read in both directions, so the two cannot
        disagree about which track is the better one."""
        carry = inspect.getsource(activity_sink._retire_promotion)
        guard = inspect.getsource(activity_sink.upsert_activity)
        assert "track_is_materially_better(" in carry
        assert "track_is_materially_better(" in guard

    def test_an_identical_resync_is_not_treated_as_a_downgrade(self):
        assert not track_is_materially_better(HC_ROUTE, HC_ROUTE)

    def test_a_genuinely_better_track_still_lands(self):
        assert not track_is_materially_better(STRAVA_STUB, HC_ROUTE)

    def test_the_simplification_is_only_invalidated_when_the_track_changes(self):
        src = inspect.getsource(activity_sink.upsert_activity)
        # The invalidation is in the else-branch of the downgrade guard, so a
        # refused write does not make the map recompute for nothing.
        assert 'update_set["polyline_simple"] = None' in src
        assert src.index('update_set.pop("polyline", None)') < src.index(
            'update_set["polyline_simple"] = None')


class TestTheDocstringNoLongerTeachesTheFalsePremise:
    def test_the_strictly_richer_claim_is_gone(self):
        src = inspect.getsource(
            activity_sink.promote_health_connect_workouts)
        assert "strictly richer" not in src

    def test_the_correction_names_what_falsified_it(self):
        src = inspect.getsource(activity_sink)
        assert "SA-P3" in src
        assert "5,598" in src
