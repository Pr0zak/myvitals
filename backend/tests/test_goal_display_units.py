"""A goal card must not print a kilogram number under a pounds label.

Reported from the phone, twice, in two different places. The AI payload
was fixed in v0.30.3; this is the UI path, and it had the identical
shape:

    {"current_value": 115.2, "target_value": 200, "target_unit": "lb"}

The arithmetic behind it was never wrong — `_goal_progress` converts the
target to kilograms and compares like with like, so the percentage was
right. What was wrong was the OUTPUT: `current_value` carried the raw
storage unit while the response's only unit label described its
neighbour. Every client renders the pair together, so a 115.3 kg user
read "115.2 / 200 lb" — a figure that is not their weight in any unit
the label claims.

The lesson this file exists to hold: a correct calculation and a correct
display are separate problems, and getting the first right is no
evidence about the second.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
AI = (SRC / "api" / "ai.py").read_text()


def test_a_weight_goal_reports_in_the_unit_it_was_set_in() -> None:
    """115.33 kg against a 200 lb goal must read as 254.3, not 115.3."""
    from myvitals.analytics.targets import kg_to_goal_unit
    assert round(kg_to_goal_unit(115.33, "lb"), 1) == 254.3
    assert round(kg_to_goal_unit(115.33, "lbs"), 1) == 254.3
    assert round(kg_to_goal_unit(115.33, "pounds"), 1) == 254.3
    # A metric goal is left alone.
    assert round(kg_to_goal_unit(115.33, "kg"), 1) == 115.3
    assert round(kg_to_goal_unit(115.33, None), 1) == 115.3


def test_the_conversion_round_trips_with_its_inverse() -> None:
    """`goal_target_kg` and `kg_to_goal_unit` are two halves of one idea
    and must not drift apart."""
    from myvitals.analytics.targets import goal_target_kg, kg_to_goal_unit
    for unit in ("lb", "kg", None):
        kg = goal_target_kg(200, unit)
        assert kg is not None
        back = kg_to_goal_unit(kg, unit)
        assert back is not None and abs(back - 200) < 1e-6


def test_absent_stays_absent() -> None:
    """No weigh-in is not a weight of zero."""
    from myvitals.analytics.targets import kg_to_goal_unit
    assert kg_to_goal_unit(None, "lb") is None


def test_the_weight_branch_converts_before_returning() -> None:
    """Checked by resolving what `_goal_progress` calls, not by grepping
    for a string — the pantry NameError taught that lesson."""
    import myvitals.api.ai as ai_mod

    tree = ast.parse(AI)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_goal_progress"
    )
    called = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "kg_to_goal_unit" in called, \
        "_goal_progress returns a weight without converting it"
    assert hasattr(ai_mod, "kg_to_goal_unit"), \
        "kg_to_goal_unit is called but not imported"
