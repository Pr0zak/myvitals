"""A weight number without its unit is a wrong number waiting to happen.

Reported from the app: it thought this user weighed 115 lb. They weigh
115.3 KILOGRAMS — 254 lb. The AI payload was sending

    {"target_value": 200, "target_unit": "lb", "current_value": 115.3}

with the target in pounds, the current weight in kilograms, and one unit
label between them. A model reading two adjacent numbers under a single
"lb" takes both as pounds. It then concludes the user is 85 lb UNDER a
weight-loss goal — and that is the direction that matters, because the
advice it produces is "eat more" to someone trying to lose weight.

This is the second time this exact confusion has shipped. v0.26.1 fixed
the mirror image: a goal stored in pounds read as kilograms, which made
the prep planner return a surplus next to a weight-loss goal. The
conversion helper written then, `goal_target_kg`, is shared — this call
site simply never used it.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
CLAUDE = (SRC / "integrations" / "claude.py").read_text()


def _fn(name: str) -> str:
    tree = ast.parse(CLAUDE)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name} not found")


def test_the_goal_payload_names_a_unit_on_every_weight() -> None:
    """The unit belongs in the KEY. A separate `target_unit` field only
    labels the value it sits beside, and says nothing about its
    neighbour."""
    src = _fn("_active_weight_goal_ctx")
    assert "'target_kg'" in src and "'current_kg'" in src
    # The old shape is what caused this; it must not come back.
    assert "'current_value'" not in src, \
        "an unlabelled weight is back in the payload"
    assert "'target_value':" not in src, \
        "an unlabelled target is back in the payload"


def test_the_target_is_converted_with_the_shared_helper() -> None:
    """Not re-derived here. Two conversions in two places is how the two
    halves of one comparison end up in different units."""
    src = _fn("_active_weight_goal_ctx")
    assert "goal_target_kg" in src


def test_a_pounds_goal_and_a_kilo_weight_compare_correctly() -> None:
    """The reported case, end to end: 200 lb against 115.33 kg is 24.6 kg
    still TO LOSE — not 85 units already lost."""
    from myvitals.analytics.targets import goal_target_kg
    target = goal_target_kg(200, "lb")
    assert target is not None
    assert abs(target - 90.7) < 0.1
    to_lose = 115.33 - target
    assert to_lose > 0, "a weight-loss goal must read as weight still to lose"
    assert abs(to_lose - 24.6) < 0.2


def test_a_goal_with_no_target_stays_none_rather_than_zero() -> None:
    """"No goal set" and "goal of zero" are different, and one of them is
    a nonsense instruction to a meal planner."""
    from myvitals.analytics.targets import goal_target_kg
    assert goal_target_kg(None, "lb") is None
    assert goal_target_kg(None, None) is None
