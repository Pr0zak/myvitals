"""The weight tile's goal line, and the unit it is denominated in (OG3-A4).

`MetricCard.vue` has drawn a dashed rule at `target` and included it in the
y-extent since it shipped, but `build_tiles` never passed one for the weight
tile, so the goal was visible only on the /weight detail view. The wiring was
one argument short.

The reason this file exists rather than the change going in unguarded is the
unit. `user_profile.weight_goal_kg` is KILOGRAMS and the tile reports POUNDS,
and this project has already shipped that exact mistake once: in v0.32.x
`_goal_progress`'s caller emitted `baseline_value` as raw kilograms beside a
pounds target, one line outside the reach of the test that walked
`_goal_progress` itself. A 90.7 that should read 200 is not an obviously
wrong number — it is a plausible one, in the wrong unit, on a screen the user
checks daily.

The second thing pinned here is that the tile stays neutral. Passing a target
is what makes a dashed line appear; it must not also start colouring the
number, because direction and tone belong to GOAL-STATE, which has a noise
band and a sober-safe `state_tone` this builder does not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from myvitals.analytics import tiles

SRC = Path(tiles.__file__).read_text()


def _weight_add_call() -> ast.Call:
    """The `add(key="weight", ...)` call node from build_tiles."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "add"):
            continue
        for kw in node.keywords:
            if (
                kw.arg == "key"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "weight"
            ):
                return node
    raise AssertionError('no add(key="weight", ...) call found in tiles.py')


class TestTheGoalIsInPounds:
    def test_the_tile_declares_pounds(self):
        call = _weight_add_call()
        unit = next(
            kw.value.value for kw in call.keywords
            if kw.arg == "unit" and isinstance(kw.value, ast.Constant)
        )
        assert unit == "lb"

    def test_the_target_is_converted_not_passed_raw(self):
        """`target=goal_kg` beside a pounds value is the v0.32.x bug.

        The conversion must happen before the value reaches `add`. Reading
        the source rather than calling the function keeps this test free of
        a database, which is what makes it cheap enough to keep.
        """
        call = _weight_add_call()
        target_kw = next((kw for kw in call.keywords if kw.arg == "target"), None)
        assert target_kw is not None, "the weight tile no longer passes a target"
        name = getattr(target_kw.value, "id", "")
        assert name.endswith("_lb"), (
            f"weight target is passed as `{name}`, which is not named as pounds. "
            "The stored column is kilograms and this tile reports pounds."
        )

        # And the variable it names is actually built through the conversion.
        assign = re.search(rf"\b{re.escape(name)}\s*=\s*(.+)", SRC)
        assert assign and "KG_TO_LB" in assign.group(1), (
            f"`{name}` is not derived through KG_TO_LB"
        )

    def test_the_note_is_in_pounds_too(self):
        """The sentence beside the number shares the tile's unit."""
        assert re.search(r'f"\{gap:g\} lb to lose"', SRC)
        assert re.search(r'f"\{abs\(gap\):g\} lb to gain"', SRC)
        # The gap is computed against the converted value, not the raw kg.
        gap = re.search(r"gap = round\((.+?), 1\)", SRC)
        assert gap and "KG_TO_LB" in gap.group(1), (
            "the distance-to-goal is computed in the wrong unit"
        )


class TestTheTileStaysNeutral:
    def test_a_target_does_not_make_the_weight_tile_judged(self):
        """A dashed line is not a verdict.

        `kind="target"` makes the grid colour a tile against its goal.
        Weight must stay `neutral` with no direction: a losing week and a
        gaining week render the same grey here, and the judgement lives in
        `_goal_progress`, which has the noise band and the sober-safe tone.
        """
        call = _weight_add_call()
        kinds = {
            kw.arg: kw.value for kw in call.keywords if kw.arg in
            {"kind", "higher_is_better", "status", "status_reason"}
        }
        assert isinstance(kinds["kind"], ast.Constant)
        assert kinds["kind"].value == "neutral"
        assert isinstance(kinds["higher_is_better"], ast.Constant)
        assert kinds["higher_is_better"].value is None
        assert "status" not in kinds, "the weight tile must not carry a verdict"

    def test_goal_note_is_its_own_field(self):
        """A NEW field, not a reuse of `status_reason`.

        GOAL-STATE's rule: every new fact goes in a new field, so a client
        that has not been updated stays incomplete rather than wrong.
        `status_reason` is tied to a `status` this tile deliberately lacks,
        and a client rendering it would imply a verdict that was never made.
        """
        assert 'kw.setdefault("goal_note", None)' in SRC, (
            "goal_note must default on every tile so clients read one shape"
        )
        call = _weight_add_call()
        assert any(kw.arg == "goal_note" for kw in call.keywords)
