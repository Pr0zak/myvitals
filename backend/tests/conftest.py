"""Pytest fixtures shared across the strength algorithm tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def user_equipment() -> dict:
    """The user's real home gym: 5–45 lb dumbbell pairs in 5s, wrist
    weights 1/1.5/2/3 lb, flat+incline bench, no barbell/rack/bar/bands."""
    return {
        "dumbbells": {
            "type": "fixed_pairs",
            "pairs_lb": [5, 10, 15, 20, 25, 30, 35, 40, 45],
            "min_lb": None, "max_lb": None, "increment_lb": None,
        },
        "wrist_weights_lb": [1, 1.5, 2, 3],
        "bench": {"flat": True, "incline": True, "decline": False},
        "barbell": False,
        "barbell_plates_lb": [],
        "squat_rack": False,
        "pull_up_bar": False,
        "cable_stack": False,
        "cable_increment_lb": None,
        "kettlebells_lb": [],
        "resistance_bands": False,
        "bodyweight": True,
    }


@pytest.fixture
def bare_equipment() -> dict:
    """Bodyweight-only — no DBs, no bench. Tests catalog filter edge case."""
    return {
        "dumbbells": {"type": "none", "pairs_lb": [],
                      "min_lb": None, "max_lb": None, "increment_lb": None},
        "wrist_weights_lb": [],
        "bench": {"flat": False, "incline": False, "decline": False},
        "barbell": False, "barbell_plates_lb": [], "squat_rack": False,
        "pull_up_bar": False, "cable_stack": False, "cable_increment_lb": None,
        "kettlebells_lb": [], "resistance_bands": False, "bodyweight": True,
    }


@pytest.fixture
def equipment_with_pullup_bar(user_equipment: dict) -> dict:
    """User's setup + a doorway pull-up bar. Verifies the catalog
    filter expands when gear is added (no code change required)."""
    user_equipment["pull_up_bar"] = True
    return user_equipment
