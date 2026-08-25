"""Recents and repeat-day — the friction fix for a diet that repeats.

Reported directly: the meals feature is hard to use. The largest single
cause was that no surface anywhere offered a food back. No favourites,
no "same as yesterday", no repeat — a grep for any of those words across
`LogTab.kt`, `Log.vue` and `meals.py` returned nothing. Every entry ever
made started at an empty search box and then went through the ranked
catalog search that exists precisely because finding the right food is
hard. About half this diet is packaged or eaten out, so the same items
recur constantly and the app made the user re-find each one.

Nothing new is recorded to support it. The log already held everything.

The design decisions worth pinning are all about not handing back an
answer the user then has to correct, because a correction costs more
than the search it replaced.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
MEALS = (SRC / "api" / "meals.py").read_text()


def _fn_src(name: str) -> str:
    """Source of one endpoint with docstrings and comments stripped, so a
    test cannot pass on prose that merely describes the behaviour."""
    tree = ast.parse(MEALS)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef, ast.Module)):
                    if (sub.body and isinstance(sub.body[0], ast.Expr)
                            and isinstance(sub.body[0].value, ast.Constant)
                            and isinstance(sub.body[0].value.value, str)):
                        sub.body.pop(0)
            return ast.unparse(node)
    raise AssertionError(f"{name} not found in meals.py")


def test_both_endpoints_exist() -> None:
    assert '@router.get("/log/recent"' in MEALS
    assert '@router.post("/log/repeat-day"' in MEALS


def test_recents_group_by_the_whole_portion_not_just_the_food() -> None:
    """Two eggs and six eggs are different things to re-log.

    Collapsing on food id alone hands back a quantity the user then has
    to correct, and a correction costs more than the search it replaced —
    which would leave the feature a net loss on exactly the entries it
    exists to speed up.
    """
    src = _fn_src("recent_log_entries")
    for field in ("quantity", "unit", "servings"):
        assert f"r.{field}" in src, f"portion field {field} missing from the key"


def test_recents_rank_on_frequency_AND_recency() -> None:
    """Either one alone gets the list wrong in a predictable direction.

    Pure recency turns the whole list over after one unusual day. Pure
    frequency pins it to whatever was eaten most six months ago and never
    surfaces a new staple. The decay makes it both.
    """
    src = _fn_src("recent_log_entries")
    assert "HALF_LIFE_DAYS" in src, "no recency decay — this is a frequency list"
    assert "0.5 **" in src, "decay is not exponential"
    assert "b['times'] += 1" in src, "frequency is not counted"


def test_the_half_life_stays_in_a_defensible_range() -> None:
    """Short enough that a dropped food falls off within a couple of
    months, long enough that a fortnight away does not erase a habit."""
    src = _fn_src("recent_log_entries")
    line = next(x for x in src.splitlines() if "HALF_LIFE_DAYS" in x and "=" in x)
    value = float(line.split("=")[1].strip())
    assert 14.0 <= value <= 45.0, f"half-life of {value} days is outside the range"


def test_usual_slot_is_the_mode_not_the_latest() -> None:
    """One late-night bowl of cereal must not re-file porridge as a snack
    for good. The most COMMON slot is the useful default."""
    src = _fn_src("recent_log_entries")
    assert "max(b['slots'].items()" in src, \
        "usual_slot is not derived from a count of slots"


def test_repeat_day_refuses_an_empty_source() -> None:
    """"I copied yesterday" and "yesterday had nothing to copy" are
    different answers, and the second is the user's cue that they did not
    log yesterday either. Silently succeeding with nothing hides that."""
    src = _fn_src("repeat_day")
    assert "if not src:" in src
    assert "HTTPException(404" in src


def test_repeat_day_appends_and_never_deletes() -> None:
    """The user may have logged breakfast before reaching for this.
    Clearing the target day to make room would destroy a real record to
    save a tap, which is the wrong trade in a tracker."""
    src = _fn_src("repeat_day")
    assert "db.delete" not in src, "repeat-day must not remove existing entries"
    assert "delete(" not in src, "repeat-day must not issue a delete"


def test_recents_add_no_new_stored_state() -> None:
    """The whole point is that the log already held this. A new table or
    column would mean the feature only starts working from today, for a
    user who has been logging for months."""
    src = _fn_src("recent_log_entries")
    assert "db.add(" not in src, "recents must be derived, never recorded"
    assert "commit" not in src, "a read endpoint must not write"


def test_recents_window_is_bounded() -> None:
    """`vitals_heartrate` taught this lesson: an unbounded scan of a
    growing table on a screen the user opens constantly."""
    src = _fn_src("recent_log_entries")
    assert "FoodLogEntry.day >= since" in src, "no time predicate on the scan"
