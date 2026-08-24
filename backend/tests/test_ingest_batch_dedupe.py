"""One batch, two writers, the same instant — and seventeen hours of silence.

Health Connect is a bus. Strava and the Fitbit/Google Health app both
wrote the same cycling session, both stamped `2026-05-24 16:45:21+00`,
and both arrived in a single `/ingest/batch` post. `workouts` conflicts
on `time` alone, so those are one row as far as the upsert is concerned
— and Postgres refuses an ON CONFLICT DO UPDATE whose statement would
touch a row twice, raising CardinalityViolationError instead of picking
a winner.

The failure mode is what makes this worth a test rather than a one-line
guard. A rejected batch is not dropped; it stays in the phone's Room
buffer and is replayed on every sync, so a single unrepresentable pair
does not cost one upload, it stops ingest entirely. It ran from
2026-08-24 03:27 UTC until the fix, with WorkManager stretching the
retries out to hourly as the failures accumulated, and the only outward
sign was `error_summary = "buffer flush failed"` on a heartbeat row that
nothing surfaces.

Which row survives is deliberately unchanged from what Postgres would do
if the pair had arrived in separate statements: last wins under DO
UPDATE, first wins under DO NOTHING. Collapsing the tie is a fix for the
crash. Choosing a winner properly means widening the table's key so it
can hold both readings, which is a schema question and not this one.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import datetime, timezone

from myvitals.api import ingest
from myvitals.api.ingest import _bulk_upsert, _dedupe_on_conflict_key

T = datetime(2026, 5, 24, 16, 45, 21, tzinfo=timezone.utc)


def _workout(source: str, kcal: int) -> dict:
    return {"time": T, "type": "biking", "duration_s": 5135,
            "kcal": kcal, "source": source}


def test_the_batch_that_stopped_ingest_no_longer_collides() -> None:
    """The exact shape from the outage: two sources, one timestamp."""
    rows = [_workout("com.strava", 500), _workout("com.fitbit.FitbitMobile", 512)]
    out = _dedupe_on_conflict_key(rows, ["time"], "workouts", keep_last=True)
    assert len(out) == 1, "a DO UPDATE statement may not touch one row twice"


def test_do_update_keeps_the_last_of_a_tie() -> None:
    """Matches what a second statement would have done: later row wins."""
    rows = [_workout("com.strava", 500), _workout("com.fitbit.FitbitMobile", 512)]
    out = _dedupe_on_conflict_key(rows, ["time"], "workouts", keep_last=True)
    assert out[0]["source"] == "com.fitbit.FitbitMobile"
    assert out[0]["kcal"] == 512


def test_do_nothing_keeps_the_first_of_a_tie() -> None:
    """DO NOTHING never overwrites, so the incumbent stands. Preserving this
    keeps the fix to the crash and out of the question of who should win."""
    rows = [{"time": T, "weight_kg": 115.4}, {"time": T, "weight_kg": 115.6}]
    out = _dedupe_on_conflict_key(rows, ["time"], "body_metrics", keep_last=False)
    assert len(out) == 1
    assert out[0]["weight_kg"] == 115.4


def test_a_multi_column_key_only_collapses_a_full_tie() -> None:
    """Sleep stages share a timestamp legitimately — they conflict on
    (time, stage), and collapsing on the timestamp alone would eat a night."""
    rows = [
        {"time": T, "stage": "deep", "duration_s": 600},
        {"time": T, "stage": "rem", "duration_s": 900},
        {"time": T, "stage": "rem", "duration_s": 950},
    ]
    out = _dedupe_on_conflict_key(rows, ["time", "stage"], "sleep_stages", keep_last=True)
    assert len(out) == 2
    assert {r["stage"] for r in out} == {"deep", "rem"}
    assert next(r for r in out if r["stage"] == "rem")["duration_s"] == 950


def test_distinct_rows_pass_through_untouched_and_in_order() -> None:
    """The common case must not be reordered — chunking and the bind-param
    ceiling both assume the list it was handed."""
    rows = [_workout("com.strava", i) for i in range(5)]
    for i, r in enumerate(rows):
        r["time"] = datetime(2026, 5, 24, 16, 45, i, tzinfo=timezone.utc)
    out = _dedupe_on_conflict_key(rows, ["time"], "workouts", keep_last=True)
    assert out == rows


def test_empty_batch_is_not_an_error() -> None:
    assert _dedupe_on_conflict_key([], ["time"], "workouts", keep_last=True) == []


def test_bulk_upsert_dedupes_before_it_reaches_postgres() -> None:
    """Every table goes through the de-dup, not just workouts.

    The guard matters because the next collision will be on a different
    table: `workouts` was simply the first key narrow enough for two
    writers to tie on, and `body_metrics` is one toggle away from the
    same thing the moment Garmin Connect's Health Connect export is on.
    """
    tree = ast.parse(inspect.getsource(_bulk_upsert))
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_dedupe_on_conflict_key" in called, (
        "_bulk_upsert must de-dupe before inserting, or a single "
        "unrepresentable batch permanently blocks the phone's buffer"
    )


def test_no_upsert_bypasses_the_helper() -> None:
    """A raw insert().on_conflict_do_update() elsewhere in ingest would
    reintroduce the crash with none of this protection."""
    src = pathlib.Path(inspect.getfile(ingest)).read_text()
    bodies = src.split("async def _bulk_upsert", 1)
    assert len(bodies) == 2
    outside = bodies[0] + bodies[1].split("\nclass ", 1)[-1]
    assert "on_conflict_do_update" not in outside, (
        "route ingest upserts through _bulk_upsert so they inherit the de-dup"
    )
