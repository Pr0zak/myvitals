"""Strength workout generation — split selection, exercise picking,
recovery-aware adjustment, micro-loader-aware weight rounding.

The catalog is loaded once at module import (same JSON as
api/workout/strength.py) so the planner can filter without DB hits.

Inputs come from three sources:
1. user_equipment        — what the user can actually load
2. user_profile           — strength_recovery_aware flag
3. daily_summary + history — recovery context + last-trained timestamps

Outputs are persisted as a strength_workouts row + child rows; see
generate_and_persist().
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import chain, combinations
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

# ------------------------------------------------------------------
# Catalog (in-memory, loaded once)
# ------------------------------------------------------------------

_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "exercises.json"
)
_CATALOG_SUPPLEMENT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "exercises_supplement.json"
)
with open(_CATALOG_PATH, encoding="utf-8") as _f:
    CATALOG: list[dict[str, Any]] = json.load(_f)
# Supplement file fills gaps in yuhonas/free-exercise-db (e.g. dumbbell-only
# home-gym exercises Fitbod uses but the source dataset is missing).
if _CATALOG_SUPPLEMENT_PATH.exists():
    with open(_CATALOG_SUPPLEMENT_PATH, encoding="utf-8") as _f:
        CATALOG.extend(json.load(_f))
CATALOG_BY_ID: dict[str, dict[str, Any]] = {e["id"]: e for e in CATALOG}

# #WP-5 (SCS-9 D) — catalog overrides for entries whose upstream tagging
# disagrees with how the exercise is universally programmed. Free-
# exercise-db tags Bent-Arm / Straight-Arm Dumbbell Pullover as
# primary=chest, but every coaching tradition (Schoenfeld, Helms,
# Heafner) treats it as a lat exercise — the long head of lats is the
# prime mover through the shoulder-extension arc. Without this fix
# users without a pull-up bar permanently show lats=untrained because
# the planner substitutes pullovers into the vertical_pull slot and
# the audit gives credit to chest instead.
_CATALOG_OVERRIDES: dict[str, dict[str, Any]] = {
    "Bent-Arm_Dumbbell_Pullover": {
        "primary_muscle": "lats",
        "secondary_muscles": ["chest", "shoulders", "triceps"],
    },
    "Straight-Arm_Dumbbell_Pullover": {
        "primary_muscle": "lats",
        "secondary_muscles": ["chest", "shoulders", "triceps"],
    },
}
for _eid, _patch in _CATALOG_OVERRIDES.items():
    if _eid in CATALOG_BY_ID:
        CATALOG_BY_ID[_eid].update(_patch)


# ------------------------------------------------------------------
# Defaults — pull from user_equipment.payload['training'] when set,
# fall back to these. Configurable in v2.
# ------------------------------------------------------------------

DEFAULT_LEVEL = "intermediate"
DEFAULT_DAYS_PER_WEEK = 3
DEFAULT_SPLIT_PREFERENCE = "auto"
# Inter-set rest periods (seconds). Bumped 2026-05 after user feedback +
# Frontiers 2024 Bayesian meta — compound rest plateau is ~3 min, not 2.
DEFAULT_REST_S_HEAVY = 210            # was 180; ≤5-rep main compounds
DEFAULT_REST_S_MODERATE = 150         # was 120; 6-8-rep secondary compounds
DEFAULT_REST_S_ISOLATION = 90         # was 75
DEFAULT_REST_S_SUPERSET_AFTER = 120   # was 90; rest after a full superset round
# Within-round (partner-swap) rest for supersets — used by the active
# workout flow when alternating between A and B mid-round.
DEFAULT_REST_S_SUPERSET_WITHIN = 35

# Per-movement-pattern starting weights (lb on each dumbbell, or single
# weight for goblet-style). Tuned for dumbbell-only home gym.
STARTING_WEIGHTS_DB_LB: dict[str, tuple[float, float, float]] = {
    "horizontal_push":   (15, 25, 35),
    "vertical_push":     (10, 17.5, 25),
    "horizontal_pull":   (15, 25, 35),
    "vertical_pull":     (10, 17.5, 25),
    "squat":             (25, 35, 45),
    "hinge":             (20, 30, 40),
    "lunge":             (15, 25, 35),
    "isolation_arm":     (10, 15, 22.5),
    "isolation_shoulder":(5,  10, 15),
    "isolation_leg":     (10, 17.5, 25),
    "isolation_core":    (10, 15, 22.5),
}
LEVEL_INDEX = {"beginner": 0, "intermediate": 1, "advanced": 2}

# Movement patterns each split focuses on.
# Per-split slot specs. Each entry describes ONE exercise the generator
# should fill, with explicit role + movement pattern + optional muscle
# filter (so e.g. push day's `isolation_arm` slot sees only triceps,
# never biceps) + an optional superset_group tag.
#
# Slots tagged with the same superset_group get paired into a superset
# in pair_supersets() (overriding the older antagonist auto-detect).
#
# Built from research-backed PPL canon — see commit body / TODO.md for
# Schoenfeld + RP volume-landmark refs.
SPLIT_SLOTS: dict[str, list[dict[str, Any]]] = {
    "full_body": [
        {"role": "main_compound",      "pattern": "squat",            "muscles": None,                      "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_push",  "muscles": ["chest"],                 "superset_group": "A"},
        {"role": "secondary_compound", "pattern": "horizontal_pull",  "muscles": ["back", "lats"],          "superset_group": "A"},
        {"role": "secondary_compound", "pattern": "hinge",            "muscles": None,                      "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_shoulder","muscles": ["shoulders"],            "superset_group": "B"},
        {"role": "isolation",          "pattern": "isolation_core",   "muscles": ["abdominals"],            "superset_group": "B"},
    ],
    "upper": [
        {"role": "main_compound",      "pattern": "horizontal_push",  "muscles": ["chest"],                 "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_pull",  "muscles": ["back", "lats"],          "superset_group": None},
        {"role": "secondary_compound", "pattern": "vertical_push",    "muscles": ["shoulders", "chest"],    "superset_group": "A"},
        {"role": "secondary_compound", "pattern": "vertical_pull",    "muscles": ["lats", "back"],          "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["biceps"],                "superset_group": "B"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["triceps"],               "superset_group": "B"},
    ],
    "lower": [
        {"role": "main_compound",      "pattern": "squat",            "muscles": None,                      "superset_group": None},
        {"role": "secondary_compound", "pattern": "hinge",            "muscles": None,                      "superset_group": None},
        {"role": "secondary_compound", "pattern": "lunge",            "muscles": None,                      "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_leg",    "muscles": ["quadriceps"],            "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_leg",    "muscles": ["hamstrings", "glutes"],  "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_core",   "muscles": ["abdominals"],            "superset_group": None},
    ],
    # WP-5E (v0.7.281) — push trimmed 6→5: dropped 2nd triceps iso.
    # Triceps secondary stimulus from chest pressing (~4-5 fractional
    # sets from 3 press slots) compounded with 1 direct iso (3 sets)
    # is plenty. The 6-slot version was landing triceps at 26 sets/wk,
    # well above the 14-set MAV. Freed slot becomes the WP-5F finisher
    # budget when an under-MEV muscle calls for one.
    "push": [
        {"role": "main_compound",      "pattern": "horizontal_push",  "muscles": ["chest"],                 "superset_group": None},
        {"role": "secondary_compound", "pattern": "vertical_push",    "muscles": ["shoulders", "chest"],    "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_push",  "muscles": ["chest", "triceps"],      "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_shoulder","muscles": ["shoulders"],            "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["triceps"],               "superset_group": "A"},
    ],
    # WP-5E (v0.7.281) — pull trimmed 6→5: dropped rear-delt iso.
    # Shoulders were 34 sets/wk vs 16-set MAV. Direct rear-delt work
    # is nice but every horizontal pull hits rear delts at 0.5× secondary
    # already (~4 fractional sets across 3 pull slots), and OHP on push
    # day covers front/side delts. Freed slot reserved for WP-5F.
    "pull": [
        {"role": "main_compound",      "pattern": "horizontal_pull",  "muscles": ["back", "lats"],          "superset_group": None},
        {"role": "secondary_compound", "pattern": "vertical_pull",    "muscles": ["lats", "back"],          "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_pull",  "muscles": ["back", "lats", "traps"], "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["biceps"],                "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["biceps", "forearms"],    "superset_group": None},
    ],
    "legs": [
        {"role": "main_compound",      "pattern": "squat",            "muscles": ["quadriceps", "glutes"],  "superset_group": None},
        {"role": "secondary_compound", "pattern": "hinge",            "muscles": ["hamstrings", "glutes", "lower_back"], "superset_group": None},
        {"role": "secondary_compound", "pattern": "lunge",            "muscles": ["quadriceps", "glutes"],  "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_leg",    "muscles": ["hamstrings", "glutes"],  "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_leg",    "muscles": ["calves", "quadriceps"],  "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_core",   "muscles": ["abdominals"],            "superset_group": None},
    ],
}

# Back-compat alias for any external caller still expecting the old
# bare-pattern map. Derived; do not edit.
SPLIT_PATTERNS: dict[str, list[str]] = {
    k: [s["pattern"] for s in slots] for k, slots in SPLIT_SLOTS.items()
}

# Antagonist pairings for supersets — keyed by primary muscle.
ANTAGONIST_PAIRS: list[tuple[str, str]] = [
    ("biceps", "triceps"),
    ("chest", "back"),
    ("chest", "lats"),
    ("quadriceps", "hamstrings"),
    ("shoulders", "lats"),
]


# ------------------------------------------------------------------
# Types
# ------------------------------------------------------------------

@dataclass
class RecoveryInputs:
    """Per-day signals from daily_summary (when strength_recovery_aware=True).

    Sleep was previously a direct input here (rest-day if <4h, deload if
    <5h). Removed in v0.7.269 — Pixel Watch sleep duration is unreliable
    enough that it was flipping legitimate strength days into yoga
    flows. Field stays on the dataclass so `sleep_h_used` persistence
    on StrengthWorkout doesn't break; just no longer drives decisions.
    """
    recovery_score: float | None = None
    readiness_score: float | None = None
    sleep_h: float | None = None  # informational only — see class docstring

    def is_blocking(self) -> tuple[bool, str | None]:
        """Should we recommend a rest day outright?"""
        if self.recovery_score is not None and self.recovery_score < 25:
            return True, f"recovery score {self.recovery_score:.0f} (very low)"
        if self.readiness_score is not None and self.readiness_score < 20:
            return True, f"readiness {self.readiness_score:.0f} (very low)"
        return False, None

    def deload_factor(self) -> float:
        """Multiplier on prescribed weight (1.0 = full, 0.85 = 15% deload)."""
        f = 1.0
        if self.recovery_score is not None:
            if self.recovery_score < 40:
                f *= 0.85
            elif self.recovery_score < 60:
                f *= 0.92
        if self.readiness_score is not None and self.readiness_score < 30:
            f *= 0.90
        return round(f, 3)


@dataclass
class ExerciseInPlan:
    exercise_id: str
    order_index: int
    superset_id: str | None
    target_sets: int
    target_reps_low: int
    target_reps_high: int
    target_weight_lb: float | None
    target_rest_s: int


@dataclass
class GeneratedPlan:
    seed: str
    split_focus: str
    exercises: list[ExerciseInPlan] = field(default_factory=list)
    recovery: RecoveryInputs | None = None
    rest_day_recommended: bool = False
    rest_day_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    # FAST-18 — active-fast snapshot the API surfaces to clients so
    # they can render an amber "fasted training" banner. None when
    # no fast is in progress at plan-generation time.
    fasting_context: dict[str, Any] | None = None


# ------------------------------------------------------------------
# Pure: split selection
# ------------------------------------------------------------------

ROTATION = {
    "full_body":    ["full_body"],
    "upper_lower":  ["upper", "lower"],
    "ppl":          ["push", "pull", "legs"],
}


def select_split(
    days_per_week: int, preference: str, last_split: str | None
) -> str:
    """Pick today's split focus.

    `preference` is one of {"auto", "full_body", "upper_lower", "ppl"}.
    "auto" maps days_per_week to the simplest workable split:
        2-3 days → full_body
        4 days   → upper_lower
        5-6 days → ppl
    """
    if preference == "auto":
        if days_per_week <= 3:
            preference = "full_body"
        elif days_per_week == 4:
            preference = "upper_lower"
        else:
            preference = "ppl"

    rotation = ROTATION.get(preference) or ROTATION["full_body"]
    if last_split is None or last_split not in rotation:
        return rotation[0]
    idx = rotation.index(last_split)
    return rotation[(idx + 1) % len(rotation)]


# ------------------------------------------------------------------
# Pure: micro-loader-aware weight rounder
# ------------------------------------------------------------------

def _all_combos(items: list[float]) -> list[float]:
    """Sums of every subset of `items`, including the empty subset (0).
    Deduplicated. For len(items) ≤ 8 this is at most 256 sums."""
    sums = set()
    for r in range(len(items) + 1):
        for combo in combinations(items, r):
            sums.add(round(sum(combo), 3))
    return sorted(sums)


def valid_dumbbell_loads(
    pairs_lb: list[float], wrist_weights_lb: list[float]
) -> list[float]:
    """Every loadable weight (per dumbbell) given fixed pairs + micro-loaders.

    For each pair P, valid loads are P + (any subset of wrist weights).
    If two wrist weights are owned (e.g. 1.5 + 2 = 3.5), both can stack.
    """
    if not pairs_lb:
        return []
    micros = _all_combos(wrist_weights_lb)
    out = set()
    for p in pairs_lb:
        for m in micros:
            out.add(round(p + m, 3))
    return sorted(out)


def round_weight(
    target_lb: float | None,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
) -> float | None:
    """Snap target_lb to a loadable weight.

    Tie-break prefers the lighter side — never recommend more weight than
    asked for unless within 0.25 lb. If the target is heavier than the
    heaviest valid load, return the heaviest valid load (and let the
    caller surface a "you've maxed out the rack" advisory if needed).

    Returns None if the user has no dumbbells (use bodyweight prescriptions).
    """
    if target_lb is None:
        return None
    valid = valid_dumbbell_loads(pairs_lb, wrist_weights_lb)
    if not valid:
        return None

    if target_lb >= valid[-1]:
        return valid[-1]
    if target_lb <= valid[0]:
        return valid[0]

    # Closest. On tie, prefer lighter unless target is within 0.25 lb of
    # the heavier option (rounding up by a hair is fine).
    best = valid[0]
    best_diff = abs(target_lb - best)
    for v in valid[1:]:
        diff = abs(target_lb - v)
        if diff < best_diff - 1e-6:
            best = v
            best_diff = diff
        elif abs(diff - best_diff) < 1e-6 and v < best:
            best = v
    if best > target_lb and (best - target_lb) > 0.25:
        # Find the closest one ≤ target_lb instead.
        below = [v for v in valid if v <= target_lb]
        if below:
            best = below[-1]
    return best


# ------------------------------------------------------------------
# Pure: starting weight + rating-driven progression
# ------------------------------------------------------------------

# Rating scale is RPE-style (1 failed … 5 easy/RIR 6+; see ratingTitle
# in StrengthToday.vue). These gates are shared by progress_from_rating
# (weight policy) and double_progression (rep+weight policy).
FAIL_THRESHOLD = 2.5   # ≤ this → cut weight next session
EASY_THRESHOLD = 4.5   # ≥ this → the rating policy wants a weight jump
REP_PROGRESS_MIN = 3.0  # ≥ this (RIR ≳2) → safe to add a rep


def starting_weight_lb(movement_pattern: str, level: str) -> float | None:
    """First-session weight when no history exists. Returns None for
    movement patterns we don't seed (caller falls back to bodyweight)."""
    table = STARTING_WEIGHTS_DB_LB.get(movement_pattern)
    if table is None:
        return None
    return table[LEVEL_INDEX.get(level, 1)]


def progress_from_rating(
    last_weight_lb: float, avg_rating: float, is_compound: bool,
    goal: str = "hypertrophy",
) -> float:
    """Apply Fitbod-style RPE-driven progression, modulated by goal.

    Fail handling is goal-agnostic: rating ≤ 2.5 → -7.5%.
    Hold zone: 2.5 < rating < easy_threshold → no change.
    Easy zone (rating ≥ easy_threshold) → goal-specific jump.

    Strength favours bigger weight jumps because neural adaptation
    benefits from heavier loads; hypertrophy uses moderate jumps so
    rep volume stays in the productive range; general uses small
    nudges so the user can keep hitting the higher rep targets.

    Thresholds:
        strength    → compound +10%, isolation +7.5%, easy_thr=4.5
        hypertrophy → compound +7.5%, isolation +5%,   easy_thr=4.5
        general     → compound +5%,   isolation +2.5%, easy_thr=4.5
    """
    if avg_rating <= FAIL_THRESHOLD:
        return last_weight_lb * 0.925
    if avg_rating < EASY_THRESHOLD:
        return last_weight_lb
    if goal == "strength":
        return last_weight_lb * (1.10 if is_compound else 1.075)
    if goal == "general":
        return last_weight_lb * (1.05 if is_compound else 1.025)
    # hypertrophy default
    return last_weight_lb * (1.075 if is_compound else 1.05)


def double_progression(
    *,
    base_reps_lo: int,
    base_reps_hi: int,
    last_weight_lb: float,
    last_avg_rating: float,
    last_avg_reps: float | None,
    is_compound: bool,
    goal: str,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
    deload: float = 1.0,
) -> tuple[float | None, int, int, str | None]:
    """Double progression for weighted lifts: add REPS toward the top of
    the range, and only add WEIGHT once you're at the top.

    Solves the fixed-dumbbell dead zone. A +5% isolation jump on a light
    DB (10 → 10.5 lb) rounds straight back to 10 when the rack steps in
    5 lb and no micro-loaders are owned, so weight-only progression
    freezes a lift you could do for 6+ RIR. Here the rep range carries
    the progression until the weight can actually move.

    Returns (target_weight_lb, reps_lo, reps_hi, advisory). reps_lo may
    be shifted up from the base to encode "do more reps at this weight".
    `advisory` is a non-None note string only for the weight-locked
    plateau case (at the top of the range, rating it easy, but the rack
    can't deliver a heavier load → suggest micro-loaders).

    `progress_from_rating` stays the weight oracle (deload / hold / jump);
    this layers reps on top, so the swap path that still calls
    progress_from_rating directly is unaffected.
    """
    def _round(w: float) -> float | None:
        return round_weight(w * deload, pairs_lb, wrist_weights_lb)

    base_reps_lo = min(base_reps_lo, base_reps_hi)
    held = _round(last_weight_lb)

    # 1. Failure → cut weight, reset to the base rep range.
    if last_avg_rating <= FAIL_THRESHOLD:
        cut = _round(progress_from_rating(
            last_weight_lb, last_avg_rating, is_compound, goal=goal))
        return cut, base_reps_lo, base_reps_hi, None

    at_top = last_avg_reps is not None and last_avg_reps >= base_reps_hi
    jumped = _round(progress_from_rating(
        last_weight_lb, last_avg_rating, is_compound, goal=goal))

    # 2. At the top of the range AND the rating wants a jump AND the rack
    #    can deliver it → add weight, reset reps to the bottom.
    if at_top and jumped is not None and held is not None and jumped > held:
        return jumped, base_reps_lo, base_reps_hi, None

    # 3. Not yet at the top (and not near-failure) → add a rep, hold weight.
    if (
        last_avg_reps is not None
        and last_avg_reps < base_reps_hi
        and last_avg_rating >= REP_PROGRESS_MIN
    ):
        next_lo = max(base_reps_lo, min(int(last_avg_reps) + 1, base_reps_hi))
        return held, next_lo, base_reps_hi, None

    # 4. At the top, rating it easy, but the rack can't add weight →
    #    weight-locked plateau. Keep them at the top and flag it.
    if at_top and last_avg_rating >= EASY_THRESHOLD:
        advisory = None
        if jumped is not None and held is not None and jumped <= held:
            advisory = (
                "weight-locked: maxing the rep range but the dumbbell "
                "step is too coarse to add load — add wrist/micro weights "
                "in Equipment to keep progressing."
            )
        return held, base_reps_hi, base_reps_hi, advisory

    # 5. Hold zone (moderate rating, mid-range) → hold weight + base reps.
    return held, base_reps_lo, base_reps_hi, None


# ------------------------------------------------------------------
# Pure: equipment filter for the catalog
# ------------------------------------------------------------------

# Catalog quirk: free-exercise-db tags pull-up / chin-up / hanging
# movements as equipment=['bodyweight'] because the body is the load.
# But the bar is the *gate* — without a doorway pull-up bar (or rack
# with a chinning bar), the user physically can't do any of these.
# Listed by catalog id so we can drop them when pull_up_bar=false.
_BAR_REQUIRED_EXERCISES: frozenset[str] = frozenset({
    "Chin-Up",
    "Gorilla_Chin_Crunch",
    "Hanging_Leg_Raise",
    "Hanging_Pike",
    "Pullups",
    "Scapular_Pull-Up",
    "V-Bar_Pullup",
    "Wide-Grip_Rear_Pull-Up",
})


def filter_catalog_for_equipment(
    catalog: list[dict[str, Any]], equipment: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep only exercises whose every required piece of equipment is owned.

    'bodyweight' is always considered owned (free movement).
    'bench' requires equipment.bench.flat OR .incline OR .decline.
    'dumbbell' requires equipment.dumbbells.type != 'none'.
    Other tags ('barbell', 'cable', 'kettlebell', 'machine', 'bands')
    require the corresponding equipment flag to be true.

    Bar-required bodyweight exercises (Pullups, Chin-Up, hanging-leg-
    raise, etc.) are filtered by id when pull_up_bar=false — see the
    _BAR_REQUIRED_EXERCISES note above for why this is by-id instead
    of by-tag.
    """
    bench_owned = (
        equipment.get("bench", {}).get("flat")
        or equipment.get("bench", {}).get("incline")
        or equipment.get("bench", {}).get("decline")
    )
    db_owned = equipment.get("dumbbells", {}).get("type", "none") != "none"
    bar_owned = bool(equipment.get("pull_up_bar"))

    def can_do(ex: dict[str, Any]) -> bool:
        if not bar_owned and ex["id"] in _BAR_REQUIRED_EXERCISES:
            return False
        for tag in ex["equipment"]:
            if tag == "bodyweight":
                continue
            if tag == "bench" and not bench_owned:
                return False
            if tag == "dumbbell" and not db_owned:
                return False
            if tag == "barbell" and not equipment.get("barbell"):
                return False
            if tag == "cable" and not equipment.get("cable_stack"):
                return False
            if tag == "kettlebell" and not equipment.get("kettlebells_lb"):
                return False
            if tag == "bands" and not equipment.get("resistance_bands"):
                return False
        return True

    return [e for e in catalog if can_do(e)]


# ------------------------------------------------------------------
# Pure: exercise selection for a given split focus
# ------------------------------------------------------------------

def _exercises_for_pattern(
    catalog: list[dict[str, Any]], pattern: str, level: str,
    muscles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Catalog rows matching this movement pattern, ranked.

    `muscles` (optional): restrict to exercises whose primary_muscle is
    one of these. Used by the split slot specs to e.g. force "isolation_
    arm" on push day to only pick triceps.

    Ranking:
    1. Compound first when the pattern is a compound slot (squat/hinge/...)
    2. Level-match (beginner sees beginner-level lifts highest, advanced
       sees the harder variants). Off-by-one mismatches OK.
    3. Stable by id (deterministic).
    """
    matches = [e for e in catalog if e["movement_pattern"] == pattern]
    if muscles is not None:
        wanted = set(muscles)
        matches = [e for e in matches if e["primary_muscle"] in wanted]
    is_compound_slot = not pattern.startswith("isolation")

    def rank_key(e: dict[str, Any]) -> tuple:
        compound_score = 0 if (is_compound_slot and e["is_compound"]) else 1
        lvl = LEVEL_INDEX.get(e["level"], 1)
        target_lvl = LEVEL_INDEX.get(level, 1)
        level_score = abs(lvl - target_lvl)
        return (compound_score, level_score, e["id"])

    return sorted(matches, key=rank_key)


def select_exercises_for_split(
    catalog: list[dict[str, Any]],
    focus: str,
    level: str,
    rng: random.Random,
    exercise_prefs: dict[str, str] | None = None,
    recent_ratings: dict[str, float] | None = None,
    recent_frequency: dict[str, int] | None = None,
    muscle_volume: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Pick exercises for the focus's slot list, in slot order.

    `exercise_prefs` (optional) lets the user opt out of disliked
    exercises and bias toward favorites:
        "disabled"  — fully excluded
        "favorite"  — picked first if any of that slot's candidates is favorited
        "avoid"     — pushed to bottom of candidates (last-resort pick)

    Returns (chosen_exercises, slot_specs_for_each_chosen, advisory_notes).
    The second list is parallel to the first — each entry is the slot spec
    that produced that exercise (so the caller can read role/superset_group
    without re-deriving). Skipped slots don't appear in either list.

    Determinism: pass a seeded random.Random and the same input always
    returns the same output.
    """
    notes: list[str] = []
    prefs = exercise_prefs or {}
    ratings = recent_ratings or {}
    freq = recent_frequency or {}
    slots = SPLIT_SLOTS.get(focus) or SPLIT_SLOTS["full_body"]

    # WP-5C (v0.7.282) — muscle-balance pressure. When the slot allows
    # multiple muscle options (e.g. legs hinge → ["hamstrings", "glutes",
    # "lower_back"]), prefer candidates whose primary_muscle has the
    # widest weekly MEV gap so volume rotates instead of pigeonholing
    # the same muscle every regenerate. Reuses the volume snapshot
    # generate_plan already computes for WP-5F.
    vol = muscle_volume or {}

    def _balance_score(e: dict[str, Any]) -> int:
        """Higher = more preferred. 0 if no snapshot or muscle is in
        range; positive (1..N) when the muscle is under MEV by that gap;
        negative when at/over MAV so we soft-deprioritise."""
        m = e.get("primary_muscle")
        snap = vol.get(m) if m else None
        if not snap:
            return 0
        sets = int(snap.get("sets", 0))
        mev = int(snap.get("mev", 0))
        mav = int(snap.get("mav", 0))
        if sets >= mav:
            return -1
        if sets >= mev:
            return 0
        return mev - sets

    # Auto-avoid: exercises the user has rated consistently low over the
    # last few weeks (≤2 avg). Treated like a soft 'avoid' pref unless
    # explicitly favorited. Lets the algo learn from feedback without
    # the user having to manage a preferences list manually.
    auto_avoid = {
        eid for eid, avg in ratings.items()
        if avg is not None and avg <= 2.0
        and prefs.get(eid) != "favorite"
    }

    # Pre-filter: drop disabled exercises entirely
    catalog = [e for e in catalog if prefs.get(e["id"]) != "disabled"]

    chosen: list[dict[str, Any]] = []
    chosen_slots: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()
    fallback_used: list[str] = []  # slots that fell back to muscles=None

    for slot in slots:
        pattern = slot["pattern"]
        muscles = slot.get("muscles")
        candidates = _exercises_for_pattern(catalog, pattern, level, muscles)
        # Drop any already chosen (avoid duplicates across passes).
        candidates = [c for c in candidates if c["id"] not in chosen_ids]
        # If muscle filter was unsatisfiable, retry without it and note.
        if not candidates and muscles is not None:
            candidates = _exercises_for_pattern(catalog, pattern, level, None)
            candidates = [c for c in candidates if c["id"] not in chosen_ids]
            if candidates:
                fallback_used.append(f"{pattern}({'/'.join(muscles)})")

        # Apply user prefs + rotation pressure:
        #   - favorites: if any candidate is favorited, pick from favorites only
        #   - avoid / auto-avoid: pushed to the back (last-resort picks)
        #   - frequency: among non-avoided candidates, lower 4-week
        #     count wins — anti-staleness so the seeded RNG over time
        #     surfaces variety instead of grinding the same lifts.
        if candidates:
            favs = [c for c in candidates if prefs.get(c["id"]) == "favorite"]
            if favs:
                candidates = favs
            else:
                def _sort_key(e: dict[str, Any]) -> tuple[int, int, int]:
                    eid = e["id"]
                    if prefs.get(eid) == "avoid":
                        avoid_bucket = 2
                    elif eid in auto_avoid:
                        avoid_bucket = 1
                    else:
                        avoid_bucket = 0
                    # WP-5C: muscle-balance pressure between avoid and
                    # frequency. Negate so higher gap = lower sort value
                    # = front of list.
                    bal = -_balance_score(e)
                    return (avoid_bucket, bal, freq.get(eid, 0))
                candidates = sorted(candidates, key=_sort_key)

        if not candidates:
            if pattern == "vertical_pull":
                notes.append(
                    "No vertical-pull exercise available for your equipment. "
                    "DB pullover + chest-supported row used as substitutes "
                    "where possible. Adding a doorway pull-up bar (~$30) "
                    "would unlock pull-ups, chin-ups, and lat width work."
                )
            continue
        # Among the top 3 candidates, pick one (lets seeded RNG vary across
        # regen calls without dropping into low-quality picks).
        top = candidates[: min(3, len(candidates))]
        pick = rng.choice(top)
        chosen.append(pick)
        chosen_slots.append(slot)
        chosen_ids.add(pick["id"])

    if fallback_used:
        notes.append(
            "Some slots couldn't satisfy their muscle filter and fell back "
            "to the broader pattern: " + ", ".join(fallback_used) +
            ". Catalog gap — usually means the target muscle isn't well-"
            "covered by your equipment."
        )

    return chosen, chosen_slots, notes


# ------------------------------------------------------------------
# Pure: superset pairing for the isolation block
# ------------------------------------------------------------------

def pair_supersets(
    exercises: list[dict[str, Any]],
    slots: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Return {exercise_id: superset_id} for the isolation block.

    Three-pass strategy:
    1. **Slot-spec pairs** (preferred) — when `slots` is provided, slots
       sharing a non-null `superset_group` get paired directly. This is
       the explicit, intentional pairing from `SPLIT_SLOTS`.
    2. **Antagonist pairs** — fill any remaining isolations with the
       textbook bicep↔tricep / chest↔back style pairings.
    3. **Encounter-order fallback** — pair anything still loose so every
       isolation slot ends up in a superset (different primary muscles
       only; same-muscle pairs would defeat the rest-while-other-works
       point).

    Compounds always stand alone — never paired.
    """
    iso = [e for e in exercises if e["movement_pattern"].startswith("isolation")]
    iso_ids = {e["id"] for e in iso}
    pairs: dict[str, str] = {}
    used: set[str] = set()
    sid = 0

    # Pass 0: explicit slot-spec groups (when caller passed parallel slots)
    if slots is not None and len(slots) == len(exercises):
        groups: dict[str, list[str]] = {}
        for ex, slot in zip(exercises, slots, strict=False):
            if ex["id"] not in iso_ids:
                continue   # only isolation slots get paired
            tag = slot.get("superset_group")
            if tag is not None:
                groups.setdefault(tag, []).append(ex["id"])
        for tag, ex_ids in groups.items():
            if len(ex_ids) >= 2:
                sid += 1
                out_tag = f"S{sid}"
                for eid in ex_ids:
                    pairs[eid] = out_tag
                    used.add(eid)

    # Pass 1: antagonist pairs over remaining
    for a, b in ANTAGONIST_PAIRS:
        ax = next((e for e in iso if e["primary_muscle"] == a and e["id"] not in used), None)
        bx = next((e for e in iso if e["primary_muscle"] == b and e["id"] not in used), None)
        if ax is not None and bx is not None:
            sid += 1
            tag = f"S{sid}"
            pairs[ax["id"]] = tag
            pairs[bx["id"]] = tag
            used.add(ax["id"])
            used.add(bx["id"])

    # Pass 2: encounter-order fallback for stragglers (skip same-muscle pairs).
    remaining = [e for e in iso if e["id"] not in used]
    i = 0
    while i + 1 < len(remaining):
        a, b = remaining[i], remaining[i + 1]
        if a["primary_muscle"] != b["primary_muscle"]:
            sid += 1
            tag = f"S{sid}"
            pairs[a["id"]] = tag
            pairs[b["id"]] = tag
            used.add(a["id"])
            used.add(b["id"])
            i += 2
        else:
            i += 1

    return pairs


# ------------------------------------------------------------------
# Pure: prescribe sets / reps / rest for an exercise slot
# ------------------------------------------------------------------

def _is_bodyweight_only(ex: dict[str, Any]) -> bool:
    """True when an exercise has no external-load equipment — load is
    fixed at body mass, so progression is rep-based, not weight-based."""
    eq = ex.get("equipment") or []
    if not eq:
        return False
    # Bench is non-load-bearing for some BW moves (e.g. dips) but the
    # generator still wires up a weight slot via micro-loaders. Treat
    # bench as bodyweight-allowed when the rest of the equipment list
    # is bodyweight only.
    load_bearing = {"dumbbell", "barbell", "cable", "kettlebell", "bands"}
    return not any(tag in load_bearing for tag in eq)


def _scale_bw_reps(rl: int, rh: int, bodyweight_lb: float | None) -> tuple[int, int]:
    """Bodyweight exercises can't be progressively loaded with external
    weight, so we scale rep targets in two ways:
      1. Shift up by 50% across the board (more reps to drive stimulus).
      2. Inverse-scale by bodyweight against a 150 lb baseline so
         heavier users do fewer reps and lighter users do more,
         keeping relative load roughly comparable. Clamped to [0.6, 1.6].
    """
    factor = 1.0
    if bodyweight_lb is not None and bodyweight_lb > 0:
        factor = max(0.6, min(1.6, 150.0 / bodyweight_lb))
    new_rl = max(5, round(rl * 1.5 * factor))
    new_rh = max(new_rl + 2, round(rh * 1.5 * factor))
    return new_rl, new_rh


def _age_scale(
    rest_s: int, sets: int, age: int | None, slot_role: str,
) -> tuple[int, int]:
    """Age-aware rest + volume scaling. Older lifters need longer rest
    between sets and slightly lower total set count, especially on
    isolation work where local fatigue compounds. Loosely based on
    ACSM 2009 / Peterson 2011 SR on age-related strength training.

      <40:  no change (baseline)
      40-49: +15 s rest
      50-59: +30 s rest, -1 set on isolation
      60+:   +45 s rest, -1 set on isolation + secondary
    """
    if age is None or age < 40:
        return rest_s, sets
    if age < 50:
        return rest_s + 15, sets
    if age < 60:
        return rest_s + 30, max(2, sets - 1) if slot_role == "isolation" else sets
    # 60+
    new_sets = sets - 1 if slot_role in ("isolation", "secondary_compound") else sets
    return rest_s + 45, max(2, new_sets)


def prescribe_slot(
    ex: dict[str, Any], slot_role: str, goal: str = "hypertrophy",
    age: int | None = None, bodyweight_lb: float | None = None,
    fasted_hours: float | None = None,
) -> tuple[int, int, int, int]:
    """Reps-or-seconds prescription. When the exercise is marked
    `is_timed` in the catalog (planks, side bridges, isometric neck,
    …), the returned (reps_low, reps_high) are HOLD SECONDS, not rep
    counts. The UI keys on the same `is_timed` flag on the exercise to
    label the field appropriately.

    FAST-18 hard rule: at `fasted_hours >= 18` AND `goal=='strength'`
    AND `slot_role=='main_compound'`, route to hypertrophy rep ranges
    (8-12) instead of 3-6 strength ranges. Fasted heavy lifts under
    near-max load carry an outsized injury risk; the rep-range bump
    cuts the load enough to remove that risk while still letting the
    user train."""
    if (
        goal == "strength" and slot_role == "main_compound"
        and fasted_hours is not None and fasted_hours >= 18
    ):
        goal = "hypertrophy"  # downstream cascade picks 6-8 reps
    if ex.get("is_timed"):
        if slot_role == "main_compound":
            sets, rl, rh, rest = 3, 45, 60, 90
        elif slot_role == "secondary_compound":
            sets, rl, rh, rest = 3, 30, 60, 75
        else:
            sets, rl, rh, rest = 3, 30, 45, 60
        rest, sets = _age_scale(rest, sets, age, slot_role)
        return (sets, rl, rh, rest)

    # Rep-based prescription. `goal` shifts rep ranges + rest periods
    # per Schoenfeld 2010/2017:
    #   strength    → 3-6 reps,  long rest, ~80-90% 1RM
    #   hypertrophy → 6-12 reps, moderate rest, ~65-80% 1RM
    #   general     → 8-15 reps, short rest, ~55-70% 1RM
    # `age` scales rest up and trims an isolation/secondary set at 60+.
    # `bodyweight_lb` scales bodyweight-only rep targets up inversely
    # so a heavier lifter doesn't get the same target as a lighter one.
    if goal == "strength":
        if slot_role == "main_compound":
            sets, rl, rh, rest = 5, 3, 5, 240
        elif slot_role == "secondary_compound":
            sets, rl, rh, rest = 4, 4, 6, 180
        else:
            sets, rl, rh, rest = 3, 6, 10, 120
    elif goal == "general":
        if slot_role == "main_compound":
            sets, rl, rh, rest = 4, 8, 10, 75
        elif slot_role == "secondary_compound":
            sets, rl, rh, rest = 3, 10, 12, 60
        else:
            sets, rl, rh, rest = 3, 12, 15, 45
    else:  # hypertrophy
        if slot_role == "main_compound":
            sets, rl, rh, rest = 4, 6, 8, 120
        elif slot_role == "secondary_compound":
            sets, rl, rh, rest = 4, 8, 10, 90
        else:
            sets, rl, rh, rest = 3, 10, 12, 60

    if _is_bodyweight_only(ex):
        rl, rh = _scale_bw_reps(rl, rh, bodyweight_lb)

    rest, sets = _age_scale(rest, sets, age, slot_role)
    return (sets, rl, rh, rest)


# ------------------------------------------------------------------
# DB-bound: read recovery context + history
# ------------------------------------------------------------------

async def read_recovery_inputs(
    db: AsyncSession, target_date: date
) -> RecoveryInputs:
    """Pull the day's daily_summary and project to RecoveryInputs.

    Sleep duration is intentionally NOT projected — see RecoveryInputs
    docstring. Pixel Watch sleep duration was unreliable enough to flip
    legitimate strength days; recovery_score / readiness_score still
    capture sleep indirectly via the HRV/RHR they're derived from.
    """
    row = await db.get(models.DailySummary, target_date)
    if row is None:
        return RecoveryInputs()
    return RecoveryInputs(
        recovery_score=row.recovery_score,
        readiness_score=row.readiness_score,
    )


log = logging.getLogger(__name__)


_ROTATION_FOCUSES = ("push", "pull", "legs", "upper", "lower", "full_body")


async def auto_skip_stale_workouts(
    db: AsyncSession, today_local: date,
) -> int:
    """Mark any past-dated planned/in_progress workouts as skipped.

    Lazy-triggered from the read endpoints (/today, /workouts, /by-date)
    so the user doesn't see yesterday's "still planned" card hanging
    around. Idempotent — the WHERE clause filters to the exact rows
    that need flipping, so repeated calls are no-ops once cleaned up.

    Returns the number of rows updated (for log visibility).

    Excludes the cardio-day rows that get auto-completed by activity
    sync (those go directly planned → completed). Anything still in
    planned/in_progress past midnight in the user's TZ is treated as
    a missed session by definition.

    Downstream:
    - `last_split_for_user` already filters to completed/in_progress
      so skipped rows are correctly ignored for rotation.
    - Day-spacing check (the no-back-to-back-strength guard in
      generate_plan) only counts completed, so a skipped Saturday
      doesn't gate Sunday's plan as a rest day.
    - No need to eagerly regenerate future days — `/today` is
      lazy-generating per call, and the next call will pick the right
      split given the (now correct) last-completed history.
    """
    from sqlalchemy import update as _update
    res = await db.execute(
        _update(models.StrengthWorkout)
        .where(models.StrengthWorkout.date < today_local)
        .where(models.StrengthWorkout.status.in_(
            ("planned", "in_progress", "paused")))
        .values(status="skipped", paused_at=None)
    )
    n = res.rowcount or 0
    if n > 0:
        await db.commit()
        log.info("auto-skipped %d stale planned workout(s)", n)
    return n


async def last_split_for_user(
    db: AsyncSession, before: datetime | None = None
) -> str | None:
    """Most recent rotation-relevant strength workout's split_focus.

    Filters to PPL / upper-lower / full_body focuses so that an
    intervening cardio or yoga session doesn't collapse the rotation
    to its first element. Without this filter, push→yoga→strength
    sequences read last_split='yoga', which is not in any rotation,
    and select_split falls back to rotation[0]=push every time —
    pull and legs never get picked.
    """
    stmt = (
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
        .where(models.StrengthWorkout.split_focus.in_(_ROTATION_FOCUSES))
        .order_by(models.StrengthWorkout.date.desc())
        .limit(1)
    )
    if before is not None:
        stmt = stmt.where(models.StrengthWorkout.generated_at < before)
    row = (await db.execute(stmt)).scalar_one_or_none()
    return row.split_focus if row else None


async def missed_strength_carryover(
    db: AsyncSession, target_date: date, lookback_days: int = 2,
) -> tuple[str, date] | None:
    """If the most recent past-date plan was a skipped rotation-strength
    workout (within `lookback_days`), return (split_focus, missed_date).

    Lets the user override today's scheduled day-type (cardio / yoga)
    with the strength session they skipped yesterday. Lookback default
    of 2 days handles the Fri-pull → Sat-yoga → Sun case so a Friday
    miss still carries through Sunday.

    Returns None when:
    - No skipped row in the lookback window
    - A more-recent completed rotation-strength row exists (the missed
      workout was effectively superseded)
    - The most recent past-date row was already cardio / yoga / rest
      (nothing to carry)
    """
    since = target_date - timedelta(days=lookback_days)
    rows = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.date < target_date)
        .order_by(models.StrengthWorkout.date.desc())
    )).scalars().all()
    for row in rows:
        if row.split_focus not in _ROTATION_FOCUSES:
            continue  # skip cardio/yoga/rest — they don't carry
        if row.status in ("completed", "in_progress"):
            return None  # already done, no carryover needed
        if row.status == "skipped":
            return row.split_focus, row.date
        # planned / regenerated rows in the past shouldn't happen
        # (auto_skip_stale_workouts flips them to skipped), but treat
        # them as "still to do" if encountered.
        if row.status == "planned":
            return row.split_focus, row.date
    return None


async def recent_ratings_by_exercise(
    db: AsyncSession, since_days: int = 14,
) -> dict[str, float]:
    """Average rating per exercise across the last `since_days` of completed
    workouts. Used by the picker to auto-down-rank exercises the user has
    been struggling with — they get pushed to the back of candidates the
    same way a manual 'avoid' pref does.

    Excludes skipped sets and sets without a rating.
    """
    from datetime import timedelta as _td
    since = datetime.now(timezone.utc).date() - _td(days=since_days)

    rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id,
            models.StrengthSet.rating,
        )
        .join(
            models.StrengthWorkoutExercise,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id,
        )
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.rating.is_not(None))
    )).all()

    by_ex: dict[str, list[int]] = {}
    for ex_id, rating in rows:
        by_ex.setdefault(ex_id, []).append(rating)
    return {
        eid: sum(rs) / len(rs) for eid, rs in by_ex.items() if rs
    }


# #WP-4 — research-backed weekly direct-set targets per muscle group.
# Sources: Schoenfeld 2017 SR + Helms / Wolf / Israetel volume framework.
# Tuple is (minimum_effective_volume, maximum_adaptive_volume).
# WP-5 (SCS-9 A): the audit now credits secondary movers at 0.5×, so
# muscles that mostly receive secondary stimulus (forearms from rows,
# traps from deadlifts, lower_back from hinges) have their MEV/MAV
# halved relative to a direct-only count. Neck dropped — no PPL/UL/FB
# template trains it directly and few home gyms have neck-specific
# equipment; report a permanent "untrained" was noise, not signal.
MUSCLE_VOLUME_TARGETS: dict[str, tuple[int, int]] = {
    "chest":       (10, 20),
    "back":        (10, 20),
    "lats":        (10, 20),
    "shoulders":   (8,  16),
    "biceps":      (8,  16),
    "triceps":     (6,  14),
    "quadriceps":  (10, 18),
    "hamstrings":  (8,  16),
    "glutes":      (10, 18),
    "calves":      (8,  14),
    "abdominals":  (8,  16),
    "forearms":    (2,  8),
    "traps":       (2,  8),
    "lower_back":  (2,  8),
}


async def weekly_muscle_volume(
    db: AsyncSession, days: int = 7,
) -> dict[str, dict[str, Any]]:
    """Sum of working sets per primary muscle over the last `days` of
    completed / in-progress strength workouts. Returns:

        {
          "chest":     {"sets": 12, "mev": 10, "mav": 20, "status": "in_range"},
          "biceps":    {"sets": 4,  "mev": 8,  "mav": 16, "status": "under"},
          ...
        }

    Skipped sets and unrated empty sets don't count — only sets where
    actual_reps is not None and skipped is false. Mobility / cardio
    workouts are excluded by status filter on split_focus.
    """
    from datetime import timedelta as _td
    since = datetime.now(timezone.utc).date() - _td(days=days)

    # Join through to get the exercise_id for each logged set.
    rows = (await db.execute(
        select(models.StrengthWorkoutExercise.exercise_id, func.count(models.StrengthSet.id))
        .join(
            models.StrengthSet,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkout.id == models.StrengthWorkoutExercise.workout_id,
        )
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
        .where(models.StrengthWorkout.split_focus.notin_(["yoga", "cardio"]))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.skipped.is_(False))
        .group_by(models.StrengthWorkoutExercise.exercise_id)
    )).all()

    # WP-5 (SCS-9 A): credit primary mover at 1.0× and each catalog-tagged
    # secondary mover at 0.5× — Helms/Wolf "fractional sets" convention.
    # Without this, a back squat with `primary=quadriceps` left glutes/
    # hamstrings/lower-back at 0 despite obvious training stress.
    SECONDARY_WEIGHT = 0.5
    sets_by_muscle: dict[str, float] = {}
    for ex_id, n_sets in rows:
        info = CATALOG_BY_ID.get(ex_id)
        if info is None:
            continue
        n = int(n_sets)
        primary = info.get("primary_muscle")
        if primary:
            sets_by_muscle[primary] = sets_by_muscle.get(primary, 0.0) + n
        for sec in info.get("secondary_muscles") or []:
            sets_by_muscle[sec] = sets_by_muscle.get(sec, 0.0) + n * SECONDARY_WEIGHT

    out: dict[str, dict[str, Any]] = {}
    for muscle in MUSCLE_VOLUME_TARGETS:
        raw = sets_by_muscle.get(muscle, 0.0)
        sets = round(raw)
        mev, mav = MUSCLE_VOLUME_TARGETS[muscle]
        if sets == 0:
            status = "untrained"
        elif sets < mev:
            status = "under"
        elif sets <= mav:
            status = "in_range"
        else:
            status = "over"
        out[muscle] = {"sets": sets, "mev": mev, "mav": mav, "status": status}
    return out


async def recent_frequency_by_exercise(
    db: AsyncSession, since_days: int = 28,
) -> dict[str, int]:
    """Count how many times each exercise appeared in the user's last
    `since_days` of completed / in-progress workouts. Used to add
    anti-staleness rotation pressure in selection: heavily-used
    exercises are pushed lower in the candidate list so the picker
    naturally favours less-recently-seen alternatives. Skipped sets
    don't decrement — a slot only counts if there was at least one
    real logged set.
    """
    from datetime import timedelta as _td
    since = datetime.now(timezone.utc).date() - _td(days=since_days)

    rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id,
            func.count(models.StrengthSet.id).label("real_sets"),
        )
        .join(
            models.StrengthSet,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id,
        )
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.skipped.is_(False))
        .group_by(models.StrengthWorkoutExercise.exercise_id)
    )).all()
    return {ex_id: int(n) for ex_id, n in rows if n}


async def recent_mobility_history(
    db: AsyncSession, since_days: int = 14,
) -> dict[str, dict[str, float | int]]:
    """Per-exercise mobility performance over the last `since_days`. Used
    by the yoga / mobility planners to nudge target hold-times or reps
    based on how the user has actually been performing them.

    Returns a dict: exercise_id → {
        'avg_rating': float (1-5; mean of non-null ratings),
        'max_actual': int  (longest hold or highest rep count),
        'fail_count': int  (sets with rating=1 or skipped=True),
        'sample_count': int  (total sets considered),
    }
    """
    from datetime import timedelta as _td
    since = datetime.now(timezone.utc).date() - _td(days=since_days)

    rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id,
            models.StrengthSet.rating,
            models.StrengthSet.actual_reps,
            models.StrengthSet.skipped,
        )
        .join(
            models.StrengthWorkoutExercise,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id,
        )
        .where(models.StrengthWorkout.date >= since)
    )).all()

    by_ex: dict[str, dict[str, list[int] | int]] = {}
    for ex_id, rating, actual_reps, skipped in rows:
        b = by_ex.setdefault(ex_id, {"ratings": [], "actuals": [],
                                       "fails": 0, "samples": 0})
        b["samples"] += 1  # type: ignore[operator]
        if skipped or rating == 1:
            b["fails"] += 1  # type: ignore[operator]
        if rating is not None and not skipped:
            b["ratings"].append(rating)  # type: ignore[union-attr]
        if actual_reps is not None and not skipped:
            b["actuals"].append(actual_reps)  # type: ignore[union-attr]

    out: dict[str, dict[str, float | int]] = {}
    for ex_id, b in by_ex.items():
        ratings = b["ratings"]
        actuals = b["actuals"]
        out[ex_id] = {
            "avg_rating": sum(ratings) / len(ratings) if ratings else 0.0,  # type: ignore[arg-type,operator]
            "max_actual": max(actuals) if actuals else 0,  # type: ignore[arg-type,type-var]
            "fail_count": b["fails"],  # type: ignore[typeddict-item]
            "sample_count": b["samples"],  # type: ignore[typeddict-item]
        }
    return out


def adjust_mobility_target(
    base_low: int, base_high: int, hist: dict[str, float | int] | None,
    is_timed: bool,
) -> tuple[int, int]:
    """Nudge a mobility target up or down based on prior performance.

    Rules (applied in order):
    - 2+ recent fails → drop 1 step (−5 s / −1 rep)
    - avg_rating ≥ 4.5 across ≥ 2 samples → bump 1 step (+5 s / +1 rep)
    - max_actual > base_low (user has held longer than prescribed) →
      raise base_low to that ceiling, capped at the max
    - Otherwise: unchanged
    Caps: 15-90 s for timed, 5-15 reps for rep-based.
    """
    if hist is None or hist.get("sample_count", 0) == 0:
        return base_low, base_high
    step = 5 if is_timed else 1
    cap_lo, cap_hi = (15, 90) if is_timed else (5, 15)
    low, high = base_low, base_high
    if hist.get("fail_count", 0) >= 2:
        low = max(cap_lo, low - step)
        high = max(low, high - step)
        return low, high
    if hist.get("sample_count", 0) >= 2 and hist.get("avg_rating", 0) >= 4.5:
        low = min(cap_hi, low + step)
        high = min(cap_hi, high + step)
    actual_max = int(hist.get("max_actual", 0))
    if actual_max > low and actual_max <= cap_hi:
        low = actual_max
        high = max(low, high)
    return low, high


async def last_target_weight_for_exercise(
    db: AsyncSession, exercise_id: str
) -> tuple[float | None, float | None, float | None]:
    """Find the most recent (avg_rating, avg_actual_weight_lb,
    avg_actual_reps) for an exercise.

    Used to compute next-session prescription: if you crushed 25 lb x 8
    last session (avg_rating 4.8), this session should prescribe ~30 lb;
    avg_reps feeds the double-progression rep ladder.
    """
    wex = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .join(
            models.StrengthWorkout,
            models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id,
        )
        .where(models.StrengthWorkoutExercise.exercise_id == exercise_id)
        .where(models.StrengthWorkout.status == "completed")
        .order_by(models.StrengthWorkout.completed_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if wex is None:
        return None, None, None

    sets = (await db.execute(
        select(models.StrengthSet)
        .where(models.StrengthSet.workout_exercise_id == wex.id)
        .where(models.StrengthSet.skipped.is_(False))
    )).scalars().all()
    if not sets:
        return None, None, None

    rated = [s for s in sets if s.rating is not None]
    weighted = [s for s in sets if s.actual_weight_lb is not None]
    repped = [s for s in sets if s.actual_reps is not None]
    avg_rating = sum(s.rating for s in rated) / len(rated) if rated else None
    avg_weight = (
        sum(s.actual_weight_lb for s in weighted) / len(weighted)
        if weighted else None
    )
    avg_reps = (
        sum(s.actual_reps for s in repped) / len(repped)
        if repped else None
    )
    return avg_rating, avg_weight, avg_reps


# ------------------------------------------------------------------
# Top-level orchestrator
# ------------------------------------------------------------------

def _seed(target_date: date, regen_count: int) -> str:
    """Deterministic seed: same date + regen yields same plan."""
    s = f"{target_date.isoformat()}#{regen_count}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


_STRENGTH_WEEKDAYS_BY_COUNT: dict[int, set[int]] = {
    # Anchor to Mon/Wed/Fri-style spacing — Monday is weekday 0.
    2: {0, 4},                 # M, F
    3: {0, 2, 4},              # M, W, F
    4: {0, 1, 3, 4},           # M, T, Th, F
    5: {0, 1, 2, 3, 4},        # M-F
    6: {0, 1, 2, 3, 4, 5},     # M-Sat
}


def schedule_day_type(
    target_date: date, strength_per_week: int, cardio_per_week: int,
) -> str:
    """Returns 'strength', 'cardio', 'yoga', or 'rest' for the given
    date based on a deterministic weekly pattern. Strength days are
    spaced for recovery; cardio fills the next-most-rested non-strength
    days; one yoga day absorbs whatever remains; the last non-yoga
    non-cardio non-strength day is rest."""
    weekday = target_date.weekday()
    s_days = _STRENGTH_WEEKDAYS_BY_COUNT.get(strength_per_week, {0, 2, 4})
    if weekday in s_days:
        return "strength"
    # Non-strength weekdays in fixed order; cardio fills the first N.
    non_s = [d for d in range(7) if d not in s_days]
    cardio_slots = set(non_s[:max(0, cardio_per_week)])
    if weekday in cardio_slots:
        return "cardio"
    yoga_slots = set(non_s[len(cardio_slots):len(cardio_slots) + 1])
    if weekday in yoga_slots:
        return "yoga"
    return "rest"


def build_yoga_plan(
    target_date: date, regen_count: int = 0,
    mobility_history: dict[str, dict[str, float | int]] | None = None,
    duration_minutes: int | None = None,
    difficulty: str | None = None,
) -> GeneratedPlan:
    """Standalone yoga session.

    `duration_minutes` (10-120) sizes the pose count: ~5 min per pose,
    so 30 min → 6 poses, 60 min → 12 poses. Defaults to 5 poses.
    `difficulty` shifts hold-time: easy=30 s, normal=45 s, hard=60 s.
    """
    seed = _seed(target_date, regen_count)
    rng = random.Random(seed)
    pool = [
        e for e in CATALOG
        if e.get("movement_pattern") == "mobility"
        and "bodyweight" in (e.get("equipment") or [])
    ]
    if duration_minutes is None:
        n_target = 5
    else:
        n_target = max(3, min(15, duration_minutes // 5))
    n = min(n_target, len(pool))
    picks = rng.sample(pool, k=n) if pool else []
    base_hold = {"easy": 30, "hard": 60}.get(difficulty or "", 45)
    exs = []
    for i, ex in enumerate(picks):
        bilateral = bool(ex.get("is_bilateral", False))
        timed = ex.get("is_timed", True)
        rl, rh = (base_hold, base_hold) if timed else (8, 10)
        if mobility_history is not None:
            rl, rh = adjust_mobility_target(
                rl, rh, mobility_history.get(ex["id"]), timed,
            )
        exs.append(ExerciseInPlan(
            exercise_id=ex["id"], order_index=i, superset_id=None,
            target_sets=2 if bilateral else 1,
            target_reps_low=rl, target_reps_high=rh,
            target_weight_lb=None, target_rest_s=15,
        ))
    return GeneratedPlan(
        seed=seed, split_focus="yoga", exercises=exs,
        notes=[
            f"Yoga / mobility flow — {n} poses, "
            f"~{base_hold} s holds."
            + (f" ({difficulty})" if difficulty and difficulty != "normal" else ""),
        ],
    )


def build_cardio_plan(
    target_date: date, regen_count: int = 0,
    duration_minutes: int | None = None,
    difficulty: str | None = None,
    equipment: dict[str, Any] | None = None,
) -> GeneratedPlan:
    """Standalone cardio recommendation — surfaces as a notes-only
    workout. The Today screen renders the prescription text rather
    than an exercise list. `duration_minutes` and `difficulty` shift
    the prescribed length and HR target.

    `equipment.cardio_*` flags suggest a specific modality. Both
    rowing (Concept2 ERG → /activities) and MTB / road bike (Strava)
    sync data through their own integrations — this plan is a
    placeholder only. When weather context is available the suggestion
    leans outdoor; otherwise the indoor option is the safer default.
    """
    seed = _seed(target_date, regen_count)
    minutes = duration_minutes or 35
    hr_low, hr_high = {
        "easy": (115, 125),
        "hard": (145, 160),
    }.get(difficulty or "", (125, 135))
    zone = {"easy": "Z2", "hard": "Z3-Z4"}.get(difficulty or "", "Z2")

    # Pick a modality suggestion from the user's cardio equipment list.
    # Outdoor options listed first so they take precedence when both
    # categories are enabled — bias toward "go outside when possible"
    # for the canonical case.
    eq = equipment or {}
    options: list[str] = []
    if eq.get("cardio_mtb_outdoor"):  options.append("mountain bike outdoors (Strava will log)")
    if eq.get("cardio_road_bike"):    options.append("road bike outdoors (Strava will log)")
    if eq.get("cardio_rower"):        options.append("rower (Concept2 ERG will log)")
    if eq.get("cardio_bike_indoor"):  options.append("indoor bike")
    if eq.get("cardio_treadmill"):    options.append("treadmill")
    if not options:
        options = ["rower, bike, walk, or trail — whatever's available"]
    suggestion = options[0] if len(options) == 1 else (
        "Pick one: " + "; ".join(options)
    )

    return GeneratedPlan(
        seed=seed, split_focus="cardio", exercises=[],
        notes=[
            f"Cardio: {minutes} min {zone} effort. "
            f"Target HR ~{hr_low}-{hr_high} bpm "
            f"({'conversational' if zone == 'Z2' else 'comfortably hard'} pace). "
            + suggestion + ".",
        ],
    )


_FASTING_STAGE_LABELS = (
    "fed", "gut_rest", "glycogen_depleting", "ketosis",
    "autophagy", "deep_autophagy", "extended_36", "extended_48", "extended_72",
)


async def _active_fasting_context(db: AsyncSession) -> dict[str, Any] | None:
    """FAST-18 — read the in-progress fast (if any) and return a
    bounded dict the generator + clients can both consume.

    Shape:
      - active: bool
      - current_hours: float
      - stage: str            (fed / ketosis / autophagy / ...)
      - modulation: str       (normal / volume_-20% / volume_-30%_cardio_priority)

    Returns None when no fast is in progress."""
    row = (await db.execute(
        select(models.FastingSession)
        .where(models.FastingSession.ended_at.is_(None))
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    elapsed_h = (
        datetime.now(timezone.utc) - row.started_at
    ).total_seconds() / 3600.0
    # Stage lookup mirrors api/fasting._stage_for thresholds.
    thresholds = [
        (72.0, "extended_72"), (48.0, "extended_48"),
        (36.0, "extended_36"), (24.0, "deep_autophagy"),
        (18.0, "autophagy"), (16.0, "ketosis"),
        (12.0, "glycogen_depleting"), (4.0, "gut_rest"),
        (0.0, "fed"),
    ]
    stage = "fed"
    for thresh, label in thresholds:
        if elapsed_h >= thresh:
            stage = label
            break
    if elapsed_h >= 24:
        modulation = "volume_-30%_cardio_priority"
    elif elapsed_h >= 18:
        modulation = "volume_-20%"
    else:
        modulation = "normal"
    return {
        "active": True,
        "current_hours": round(elapsed_h, 1),
        "stage": stage,
        "modulation": modulation,
    }


async def generate_plan(
    db: AsyncSession,
    target_date: date,
    equipment: dict[str, Any],
    profile: models.UserProfile | None,
    regen_count: int = 0,
    force_no_rest: bool = False,
    override_split: str | None = None,
    duration_minutes: int | None = None,
    difficulty: str | None = None,
) -> GeneratedPlan:
    """Build (but don't persist) a strength plan for the given date.

    - Filters catalog by equipment
    - Reads recovery context if user opts in (strength_recovery_aware)
    - Picks exercises deterministically from a date-derived seed
    - Sets target weights from history (or starting tables) + recovery deload

    `force_no_rest=True` overrides the rest-day recommendation: the plan
    is built normally, only the deload factor still applies. Used when
    the user explicitly forces regeneration past a rest-day banner.
    """
    seed = _seed(target_date, regen_count)
    rng = random.Random(seed)

    # Training preferences (currently defaulted; can move to user_equipment.payload later).
    training = (equipment.get("training") or {}) if isinstance(equipment, dict) else {}
    level = training.get("level", DEFAULT_LEVEL)
    days_per_week = int(training.get("days_per_week", DEFAULT_DAYS_PER_WEEK))
    split_pref = training.get("split_preference", DEFAULT_SPLIT_PREFERENCE)
    # Match the Pydantic default in TrainingPreferences — when the
    # stored payload predates these fields, treat them as enabled.
    include_mobility = bool(training.get("include_mobility", True))
    yoga_on_rest = bool(training.get("yoga_on_rest_days", True))
    cardio_per_week = int(training.get("cardio_days_per_week", 2))
    goal = training.get("goal", "hypertrophy")

    # Age + bodyweight context for prescribe_slot — drives age-scaled
    # rest / volume and bodyweight-scaled rep targets on BW exercises.
    user_age: int | None = None
    if profile is not None and getattr(profile, "birth_date", None) is not None:
        user_age = (target_date - profile.birth_date).days // 365
    user_bodyweight_lb: float | None = None
    latest_bw = (await db.execute(
        select(models.BodyMetric)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .order_by(models.BodyMetric.time.desc())
        .limit(1)
    )).scalar_one_or_none()
    if latest_bw is not None and latest_bw.weight_kg:
        user_bodyweight_lb = float(latest_bw.weight_kg) * 2.20462

    # Missed-strength carry-over — if yesterday (or within the lookback
    # window) was a skipped rotation-strength workout, pin today's split
    # to that focus so the user doesn't lose the rotation slot to a
    # weekend yoga day. Acts like a soft override_split: bypasses the
    # day-type cardio/yoga dispatch but still respects override_split
    # set explicitly via /today/swap-type.
    carryover_note: str | None = None
    if not override_split:
        carry = await missed_strength_carryover(db, target_date)
        if carry is not None:
            override_split = carry[0]
            carryover_note = (
                f"Carried over from {carry[1].isoformat()}'s missed "
                f"{carry[0]} session — schedule slot would have been "
                "rest/cardio/yoga today."
            )

    # Day-type allocation by weekday — runs before recovery / rest
    # checks. If today's slot is cardio or yoga (auto), we short-circuit
    # to that plan instead of building a strength session. Override
    # ONLY via /today/swap-type (which sets override_split explicitly).
    # `force_no_rest` used to bypass this too, which meant every
    # Regenerate tap on a cardio day silently flipped the plan to
    # strength — wrong. force_no_rest now scopes strictly to the
    # recovery-rest-day check below.
    if not override_split:
        day_type = schedule_day_type(target_date, days_per_week, cardio_per_week)
        if day_type == "cardio":
            return build_cardio_plan(
                target_date, regen_count=regen_count, equipment=equipment,
            )
        if day_type == "yoga" and yoga_on_rest:
            return build_yoga_plan(
                target_date, regen_count=regen_count,
                mobility_history=await recent_mobility_history(db),
            )

    def _yoga_session(_seed_str: str, n_poses: int = 5,
                      hold_s: int = 45) -> list[ExerciseInPlan]:
        """Pick `n_poses` mobility poses from the catalog, deterministic
        on the seed string. Honors per-pose `is_bilateral` (2 sets so
        the phone can label them R / L) and `is_timed` (false → 8-10
        slow controlled reps instead of a hold)."""
        local_rng = random.Random(_seed_str)
        pool = [
            e for e in CATALOG
            if e.get("movement_pattern") == "mobility"
            and "bodyweight" in (e.get("equipment") or [])
        ]
        if not pool:
            return []
        n = min(n_poses, len(pool))
        picks = local_rng.sample(pool, k=n)
        out: list[ExerciseInPlan] = []
        for i, ex in enumerate(picks):
            bilateral = bool(ex.get("is_bilateral", False))
            timed = ex.get("is_timed", True)
            rl, rh = (hold_s, hold_s) if timed else (8, 10)
            out.append(ExerciseInPlan(
                exercise_id=ex["id"], order_index=i, superset_id=None,
                target_sets=2 if bilateral else 1,
                target_reps_low=rl, target_reps_high=rh,
                target_weight_lb=None, target_rest_s=15,
            ))
        return out

    # Recovery integration
    recovery: RecoveryInputs | None = None
    if profile is None or profile.strength_recovery_aware:
        recovery = await read_recovery_inputs(db, target_date)

    # Fasting integration (FAST-18) — affects prescribe_slot rep ranges
    # via fasted_hours, and triggers volume trimming on the chosen list.
    fasting_ctx = await _active_fasting_context(db)
    fasted_hours = fasting_ctx["current_hours"] if fasting_ctx else None

    notes: list[str] = []
    if recovery is not None and not force_no_rest:
        blocked, reason = recovery.is_blocking()
        if blocked:
            yoga_exs = _yoga_session(seed, n_poses=5, hold_s=45) if yoga_on_rest else []
            return GeneratedPlan(
                seed=seed,
                split_focus="yoga" if yoga_exs else "rest",
                rest_day_recommended=not yoga_exs,
                rest_day_reason=reason if not yoga_exs else None,
                exercises=yoga_exs,
                recovery=recovery,
                notes=[
                    (
                        f"Active-recovery yoga flow generated — "
                        f"{reason} suggested rest day. 5 poses, ~45 s holds."
                        if yoga_exs else
                        f"Rest day recommended — {reason}. You can override "
                        f"via the regenerate button."
                    ),
                ],
            )

    # Day-spacing check: don't recommend back-to-back STRENGTH sessions.
    # Yoga + cardio are intentionally excluded — a daily yoga habit
    # shouldn't push every strength day into yoga. (Same fix as v0.7.142
    # in /upcoming; this is the sibling path inside generate_plan.)
    if not force_no_rest:
        recent_q = await db.execute(
            select(func.max(models.StrengthWorkout.date))
            .where(models.StrengthWorkout.status == "completed")
            .where(models.StrengthWorkout.date < target_date)
            .where(models.StrengthWorkout.split_focus.notin_(["yoga", "cardio"]))
        )
        last_completed = recent_q.scalar()
        if last_completed is not None:
            gap_days = (target_date - last_completed).days
            if gap_days <= 1:
                yoga_exs = _yoga_session(seed, n_poses=5, hold_s=45) if yoga_on_rest else []
                rest_reason = (
                    f"trained {last_completed.strftime('%a')} — "
                    f"give the muscle group at least one off day"
                )
                return GeneratedPlan(
                    seed=seed,
                    split_focus="yoga" if yoga_exs else "rest",
                    rest_day_recommended=not yoga_exs,
                    rest_day_reason=rest_reason if not yoga_exs else None,
                    exercises=yoga_exs,
                    recovery=recovery,
                    notes=[
                        (
                            f"Active-recovery yoga flow generated — "
                            f"trained {last_completed.isoformat()}, no "
                            f"back-to-back strength. 5 poses, ~45 s holds."
                            if yoga_exs else
                            f"Last session was {last_completed.isoformat()}. "
                            "Back-to-back strength days bypass the recovery "
                            "your plan assumes — regenerate with force=true "
                            "to override."
                        ),
                    ],
                )

    last_split = await last_split_for_user(db)
    focus = override_split or select_split(days_per_week, split_pref, last_split)

    # #WP-8 frequency advisory — compare declared days_per_week against
    # actual completed strength sessions in the trailing 14 days. If
    # they're off by ≥2 sessions (i.e. user declared 4 but actually
    # does 2/wk, or declared 2 but actually does 5/wk), surface a
    # one-line note suggesting they update the pref so the split
    # mapping matches their real cadence.
    freq_advisory_note: str | None = None
    if split_pref == "auto" and not override_split:
        since14 = target_date - timedelta(days=14)
        actual_count_q = await db.execute(
            select(func.count(models.StrengthWorkout.id))
            .where(models.StrengthWorkout.date >= since14)
            .where(models.StrengthWorkout.date < target_date)
            .where(models.StrengthWorkout.status == "completed")
            .where(models.StrengthWorkout.split_focus.notin_(["yoga", "cardio"]))
        )
        actual_14d = int(actual_count_q.scalar() or 0)
        actual_per_week = actual_14d / 2.0  # 14 days = 2 weeks
        # Suggested days based on actual cadence, rounded.
        suggested = max(1, min(6, round(actual_per_week)))
        if actual_14d >= 4 and abs(suggested - days_per_week) >= 2:
            suggested_split = (
                "full_body" if suggested <= 3 else
                "upper_lower" if suggested == 4 else "ppl"
            )
            freq_advisory_note = (
                f"You've completed {actual_14d} strength sessions in the "
                f"last 14 days (~{actual_per_week:.1f}/week), but your "
                f"setting is {days_per_week}/week → {focus.replace('_', ' ')}. "
                f"Consider bumping days_per_week to {suggested} → "
                f"{suggested_split.replace('_', ' ')} split for a better "
                f"per-muscle frequency match."
            )

    catalog = filter_catalog_for_equipment(CATALOG, equipment)
    if not catalog:
        return GeneratedPlan(
            seed=seed,
            split_focus=focus,
            recovery=recovery,
            notes=["No exercises match your equipment. Add gear in Settings."],
        )

    exercise_prefs = (
        equipment.get("exercise_prefs") or {}
        if isinstance(equipment, dict) else {}
    )
    recent_ratings = await recent_ratings_by_exercise(db, since_days=14)
    recent_frequency = await recent_frequency_by_exercise(db, since_days=28)
    # WP-5C/F: snapshot weekly muscle volume once. select_exercises_for_split
    # uses it as muscle-balance pressure; the finisher block below uses
    # it to decide which gaps to fill.
    try:
        current_volume = await weekly_muscle_volume(db, days=7)
    except Exception:  # noqa: BLE001
        current_volume = {}
    chosen, chosen_slots, sel_notes = select_exercises_for_split(
        catalog, focus, level, rng,
        exercise_prefs=exercise_prefs,
        recent_ratings=recent_ratings,
        recent_frequency=recent_frequency,
        muscle_volume=current_volume,
    )
    notes.extend(sel_notes)
    if freq_advisory_note:
        notes.append(freq_advisory_note)
    if carryover_note:
        notes.append(carryover_note)
    auto_avoid_count = sum(
        1 for r in recent_ratings.values() if r is not None and r <= 2.0
    )
    if auto_avoid_count:
        notes.append(
            f"{auto_avoid_count} exercise(s) auto-avoided based on recent "
            f"ratings ≤2 over the last 14 days. Override by marking them "
            f"'favorite' in the catalog if you want them back."
        )

    superset_map = pair_supersets(chosen, chosen_slots)

    # Compute target weights for each exercise, applying history + deload
    deload = recovery.deload_factor() if recovery else 1.0
    # Ad-hoc difficulty knob: easy -10% on top of deload, hard +5%.
    if difficulty == "easy":
        deload *= 0.90
    elif difficulty == "hard":
        deload *= 1.05
    if deload < 1.0:
        notes.append(
            f"Targets reduced by {round((1 - deload) * 100)}% based on today's "
            f"recovery / sleep / readiness. Toggle this off in Settings if you "
            f"prefer the algorithm to ignore those signals."
        )
    if difficulty and difficulty != "normal":
        notes.append(f"Ad-hoc session — difficulty: {difficulty}.")
    # Ad-hoc duration: rough rule = 8 min per exercise (incl. rest).
    # Trim or extend the chosen list. Default plans run 5-6 exercises.
    if duration_minutes is not None:
        target_count = max(3, min(10, duration_minutes // 8))
        if len(chosen) > target_count:
            chosen = chosen[:target_count]
            chosen_slots = chosen_slots[:target_count]
            notes.append(
                f"Trimmed to {target_count} exercises for ~{duration_minutes} min session."
            )

    plan_exs: list[ExerciseInPlan] = []
    pairs_lb = (equipment.get("dumbbells") or {}).get("pairs_lb") or []
    wrist = equipment.get("wrist_weights_lb") or []
    dp_plateau_names: list[str] = []

    for i, ex in enumerate(chosen):
        if i == 0:
            slot_role = "main_compound"
        elif i <= 2 and not ex["movement_pattern"].startswith("isolation"):
            slot_role = "secondary_compound"
        else:
            slot_role = "isolation"
        sets, reps_lo, reps_hi, rest_s = prescribe_slot(
            ex, slot_role, goal=goal,
            age=user_age, bodyweight_lb=user_bodyweight_lb,
            fasted_hours=fasted_hours,
        )
        # FAST-18 volume modulation. -20% (≥18h) drops 1 set on every
        # exercise. -30% (≥24h) drops 1 from compounds and 2 from
        # isolation. Rest extends 15/30s respectively. Floor sets at 2
        # so the user isn't doing single-set sessions.
        if fasting_ctx and fasting_ctx["modulation"] == "volume_-20%":
            sets = max(2, sets - 1)
            rest_s += 15
        elif fasting_ctx and fasting_ctx["modulation"] == "volume_-30%_cardio_priority":
            if slot_role == "isolation":
                sets = max(2, sets - 2)
            else:
                sets = max(2, sets - 1)
            rest_s += 30

        # History-driven progression first, then starting weight.
        avg_rating, avg_weight, avg_reps = await last_target_weight_for_exercise(
            db, ex["id"])
        is_weighted = "dumbbell" in ex["equipment"] and not ex.get("is_timed")

        if avg_rating is not None and avg_weight is not None and is_weighted:
            # Double progression: fill the rep range, then add weight. This
            # is the path that unsticks light fixed-pair dumbbells whose
            # +5% jump would otherwise round straight back to the same load.
            target, reps_lo, reps_hi, advisory = double_progression(
                base_reps_lo=reps_lo, base_reps_hi=reps_hi,
                last_weight_lb=avg_weight, last_avg_rating=avg_rating,
                last_avg_reps=avg_reps, is_compound=ex["is_compound"],
                goal=goal, pairs_lb=pairs_lb, wrist_weights_lb=wrist,
                deload=deload,
            )
            if advisory:
                dp_plateau_names.append(ex["name"])
        elif avg_rating is not None and avg_weight is not None:
            # Non-dumbbell-but-rated (e.g. timed holds carrying a load) —
            # keep the weight-only policy; reps/seconds handled elsewhere.
            target = round_weight(
                progress_from_rating(
                    avg_weight, avg_rating, ex["is_compound"], goal=goal,
                ) * deload, pairs_lb, wrist,
            )
        else:
            target = starting_weight_lb(ex["movement_pattern"], level)
            if target is not None:
                target = round_weight(target * deload, pairs_lb, wrist)

        # Bodyweight-only exercise (or no DBs owned): leave weight null,
        # progress by reps.
        if "dumbbell" not in ex["equipment"]:
            target = None

        plan_exs.append(ExerciseInPlan(
            exercise_id=ex["id"],
            order_index=i,
            superset_id=superset_map.get(ex["id"]),
            target_sets=sets,
            target_reps_low=reps_lo,
            target_reps_high=reps_hi,
            target_weight_lb=target,
            target_rest_s=(
                DEFAULT_REST_S_SUPERSET_AFTER if ex["id"] in superset_map else rest_s
            ),
        ))

    if dp_plateau_names:
        names = ", ".join(dp_plateau_names[:3])
        notes.append(
            f"Weight-locked on {names} — you're maxing the rep range but the "
            f"dumbbell jump is too coarse to add load. Add wrist/micro weights "
            f"in Equipment to keep progressing."
        )

    # WP-5F (v0.7.281) — adaptive MEV-filler finisher slots.
    # If the trailing 7-day audit shows a muscle is meaningfully under
    # its MEV (≥3 sets short), append a 2-set isolation finisher for
    # the worst-offending muscle that has a matching pattern available
    # for this split. Capped at 2 finishers per session so the freed
    # WP-5E budget (push/pull went 6→5 main slots) translates back into
    # productive volume without overshooting session length. Skip on
    # cardio / yoga / mobility-only days — they reach this point only
    # for strength splits.
    if focus in SPLIT_SLOTS:
        # `current_volume` was fetched up-front (used by WP-5C as well).
        # Pre-credit today's main slots so finishers don't double-count
        # muscles we're already hitting hard.
        projected = {m: v["sets"] for m, v in current_volume.items()}
        for ex_row in chosen:
            n = 3  # main-slot working sets, close enough
            pm = ex_row.get("primary_muscle")
            if pm in projected:
                projected[pm] += n
            for sm in ex_row.get("secondary_muscles") or []:
                if sm in projected:
                    projected[sm] += n * 0.5

        # Rank under-MEV muscles by absolute gap (worst first), then
        # filter to ones we can actually train with an isolation pattern.
        FINISHER_PATTERNS: dict[str, str] = {
            "calves":      "isolation_leg",
            "abdominals":  "isolation_core",
            "hamstrings":  "isolation_leg",
            "glutes":      "isolation_leg",
            "quadriceps":  "isolation_leg",
            "biceps":      "isolation_arm",
            "triceps":     "isolation_arm",
            "forearms":    "isolation_arm",
            "shoulders":   "isolation_shoulder",
            "lats":        "vertical_pull",  # substitutes to pullover via WP-5D
        }
        gaps: list[tuple[float, str]] = []
        for muscle, payload in current_volume.items():
            mev = payload["mev"]
            sets_now = projected.get(muscle, 0)
            gap = mev - sets_now
            if gap >= 3 and muscle in FINISHER_PATTERNS:
                gaps.append((gap, muscle))
        gaps.sort(reverse=True)  # widest gap first

        finishers_added: list[str] = []
        already_chosen_ids = {e["id"] for e in chosen}
        finisher_seed_rng = random.Random(seed + "::finishers")
        for _gap, muscle in gaps:
            if len(finishers_added) >= 2:
                break
            pattern = FINISHER_PATTERNS[muscle]
            candidates = _exercises_for_pattern(catalog, pattern, level, [muscle])
            candidates = [c for c in candidates if c["id"] not in already_chosen_ids]
            if not candidates:
                continue
            # Use rotation pressure (low frequency wins) for variety.
            candidates = sorted(
                candidates,
                key=lambda e: recent_frequency.get(e["id"], 0),
            )
            pick = finisher_seed_rng.choice(candidates[:min(3, len(candidates))])
            already_chosen_ids.add(pick["id"])
            # Reps: 12-15 light pump range for isolation finishers.
            # 2 sets keeps the time cost low (~3-5 min per finisher).
            plan_exs.append(ExerciseInPlan(
                exercise_id=pick["id"],
                order_index=len(plan_exs),
                superset_id=None,
                target_sets=2,
                target_reps_low=12,
                target_reps_high=15,
                target_weight_lb=None,  # let the user pick a light DB
                target_rest_s=45,
            ))
            finishers_added.append(muscle)

        if finishers_added:
            notes.append(
                f"+{len(finishers_added)} finisher slot"
                f"{'s' if len(finishers_added) > 1 else ''} added "
                f"to chip away at weekly volume gap: {', '.join(finishers_added)}."
            )

    # Mobility / yoga block — append 2 poses tagged movement_pattern=mobility
    # to the end of the plan when the user has opted in. Reps are interpreted
    # as seconds-to-hold by the UI; sets=1, weight=null, rest=15.
    if include_mobility:
        mobility_pool = [
            e for e in CATALOG
            if e.get("movement_pattern") == "mobility"
            and "bodyweight" in (e.get("equipment") or [])
        ]
        mobility_history = await recent_mobility_history(db)
        if mobility_pool:
            picks = rng.sample(mobility_pool, k=min(2, len(mobility_pool)))
            for j, ex in enumerate(picks):
                bilateral = bool(ex.get("is_bilateral", False))
                timed = ex.get("is_timed", True)
                rl, rh = (30, 30) if timed else (8, 10)
                if mobility_history is not None:
                    rl, rh = adjust_mobility_target(
                        rl, rh, mobility_history.get(ex["id"]), timed,
                    )
                plan_exs.append(ExerciseInPlan(
                    exercise_id=ex["id"],
                    order_index=len(plan_exs),  # auto-counts finishers (WP-5F)
                    superset_id=None,
                    target_sets=2 if bilateral else 1,
                    target_reps_low=rl, target_reps_high=rh,
                    target_weight_lb=None, target_rest_s=15,
                ))
            notes.append(
                "Mobility block appended — 2 yoga poses, ~30 s hold each."
            )

    # FAST-18 note — only when modulation actually changed the plan.
    # The cue ties the trimmed sets / extended rest back to the active
    # fast so the user understands why their volume looks lighter.
    if fasting_ctx and fasting_ctx["modulation"] != "normal":
        hrs = fasting_ctx["current_hours"]
        if fasting_ctx["modulation"] == "volume_-20%":
            notes.append(
                f"Fasted {hrs:.0f}h — strength block scaled back ~20% "
                f"(dropped 1 set per exercise, rest +15s)."
            )
        else:
            notes.append(
                f"Fasted {hrs:.0f}h — strength block scaled back ~30% "
                f"(dropped 1-2 sets per exercise, rest +30s). "
                f"A Z2 cardio block alongside is a strong option."
            )

    return GeneratedPlan(
        seed=seed,
        split_focus=focus,
        exercises=plan_exs,
        recovery=recovery,
        notes=notes,
        fasting_context=fasting_ctx,
    )


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------

async def persist_plan(
    db: AsyncSession,
    plan: GeneratedPlan,
    target_date: date,
) -> models.StrengthWorkout:
    """Write the plan as a strength_workouts row + child rows.

    Prior planned-but-not-started rows for this date are marked
    status='regenerated' (not deleted) so that the regen_count keeps
    incrementing across regenerates and each new seed differs. Workouts
    that are already in_progress / completed are left alone (caller
    refuses to regenerate). Use status filters to hide 'regenerated'
    rows from history listings.
    """
    now = datetime.now(timezone.utc)

    prior = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == target_date)
        .where(models.StrengthWorkout.status == "planned")
    )).scalars().all()
    for p in prior:
        p.status = "regenerated"

    workout = models.StrengthWorkout(
        date=target_date,
        generated_at=now,
        split_focus=plan.split_focus,
        status="planned",
        seed=plan.seed,
        recovery_score_used=plan.recovery.recovery_score if plan.recovery else None,
        readiness_score_used=plan.recovery.readiness_score if plan.recovery else None,
        sleep_h_used=plan.recovery.sleep_h if plan.recovery else None,
        notes="\n".join(plan.notes) if plan.notes else None,
    )
    db.add(workout)
    await db.flush()

    for ex in plan.exercises:
        db.add(models.StrengthWorkoutExercise(
            workout_id=workout.id,
            exercise_id=ex.exercise_id,
            order_index=ex.order_index,
            superset_id=ex.superset_id,
            target_sets=ex.target_sets,
            target_reps_low=ex.target_reps_low,
            target_reps_high=ex.target_reps_high,
            target_weight_lb=ex.target_weight_lb,
            target_rest_s=ex.target_rest_s,
        ))

    await db.commit()
    await db.refresh(workout)
    return workout
