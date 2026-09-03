"""A warm-up must never influence what to lift next time — OG2-A1.

`last_target_weight_for_exercise` picks next session's load from the mean
weight, reps and rating of the last completed session. It filtered skipped
sets and nothing else, so a row the user tagged `warmup` or `drop` was
averaged straight into that decision.

Both are logged at a deliberately reduced load, and the two errors compound
in the same direction: the ramp row drags the mean weight down, while an easy
warm-up drags the mean rating up toward "add weight". The result is a working
weight that walks down a little every session, from data that looks
completely ordinary in the log.

It was reachable two ways. The web set logger has had a set-type picker since
TD-6, and imported Strong/Hevy history carries the source file's own set
types (`api/imports.py` writes `set_type` verbatim).

The divergence is what makes this worth a test rather than a one-line fix.
Thirteen query sites read `strength_sets` and at least three predicates were
in use at once: `_advance_program_on_complete` already excluded warm-up and
drop, `weekly_muscle_volume` and the PR scan exclude only warm-up, and the
prescription reducer excluded neither. Those are answers to two different
questions — "was this real work" versus "what does this tell me to lift next"
— and a drop set is genuinely yes to the first and no to the second. So the
fix is a shared constant rather than a repeated literal, and this file exists
to keep the progression readers on it.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from myvitals.analytics import strength as strength_algo

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"

# Functions that answer "what should be prescribed next time". Every one of
# them must read the shared constant. Adding a fourth progression reader
# without it should turn this suite red — that is the whole point.
# OG2-B1 moved the prescription reader's filtering out of its query and into
# the pure `read_session`, so the rule is now enforced in one place instead of
# in a WHERE clause. The invariant is unchanged and the check follows it.
PROGRESSION_READERS = [
    (SRC / "analytics" / "strength.py", "read_session"),
    (SRC / "api" / "workout" / "strength.py", "_advance_program_on_complete"),
]


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(path.read_text(), node) or ""
    raise AssertionError(f"{name} not found in {path} — did it get renamed?")


def test_the_excluded_types_are_warmup_and_drop():
    assert strength_algo.PROGRESSION_EXCLUDED_SET_TYPES == ("warmup", "drop")


def test_failure_sets_still_drive_progression():
    """Greyskull's last set is taken to failure and is the AMRAP.

    It is tagged `set_type="failure"` and is precisely the set that decides
    whether the next jump is single or double. Excluding it would make the
    scheme's headline feature invisible to the reader that implements it.
    """
    assert "failure" not in strength_algo.PROGRESSION_EXCLUDED_SET_TYPES


def test_every_progression_reader_filters_set_type():
    """The reducer shipped without this predicate for a release.

    Asserting on the shared name rather than on a literal is deliberate: a
    reader that hard-codes `("warmup", "drop")` is correct today and free to
    drift tomorrow, which is exactly how the three predicates got out of step
    in the first place.

    Two ways to satisfy it, and DELEGATING is the better one. This check was
    written when each reader carried its own WHERE clause, so naming the
    constant was the only available evidence. Since OG2-D-1,
    `_advance_program_on_complete` reads its session through `read_session`
    instead — which applies the predicate itself, and brought the `skipped`
    filter that reader had never had. Insisting it still name the constant
    would have meant keeping the hand-rolled query the delegation deleted,
    which is the opposite of what this test exists to protect.
    """
    for path, name in PROGRESSION_READERS:
        src = _function_source(path, name)
        delegates = "read_session" in src and name != "read_session"
        if delegates:
            continue
        assert "set_type" in src, f"{name} does not filter set_type at all"
        assert "PROGRESSION_EXCLUDED_SET_TYPES" in src, (
            f"{name} neither names the shared constant nor delegates to "
            "read_session — two copies of this rule is how it diverged before"
        )


def test_the_ratings_reader_shares_the_constant_too():
    """OG2-D-1. `recent_ratings_by_exercise` gates exercise SELECTION at
    `AUTO_AVOID_THRESHOLD` off an average rating, and counted warm-ups and
    drop sets while doing it.

    It is not in PROGRESSION_READERS because it decides what to OFFER, not
    what to load — but it reads the same column for the same reason, and both
    directions of the error are wrong without cancelling: a warm-up rated Easy
    makes a hard lift look comfortable, and a drop set is taken near failure
    by design, so counting it makes a lift the user chose to push look like
    one they are failing.
    """
    src = _function_source(SRC / "analytics" / "strength.py",
                           "recent_ratings_by_exercise")
    assert "PROGRESSION_EXCLUDED_SET_TYPES" in src


def test_the_volume_and_pr_readers_are_deliberately_more_permissive():
    """A drop set is real work; it just is not evidence about next week.

    This is the distinction the shared constant encodes, so it is worth
    pinning that the other readers were NOT swept along with the fix. If a
    later change makes the volume audit exclude drop sets too, the constant
    has stopped meaning what its name says and this test should be the thing
    that notices.
    """
    src = inspect.getsource(strength_algo.weekly_muscle_volume)
    assert 'set_type != "warmup"' in src or "set_type !=" in src
    assert "PROGRESSION_EXCLUDED_SET_TYPES" not in src
