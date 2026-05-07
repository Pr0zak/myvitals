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
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import chain, combinations
from pathlib import Path
from typing import Any

from sqlalchemy import select
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
    "push": [  # chest + front/side delts + triceps. NEVER biceps.
        {"role": "main_compound",      "pattern": "horizontal_push",  "muscles": ["chest"],                 "superset_group": None},
        {"role": "secondary_compound", "pattern": "vertical_push",    "muscles": ["shoulders", "chest"],    "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_push",  "muscles": ["chest", "triceps"],      "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_shoulder","muscles": ["shoulders"],            "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["triceps"],               "superset_group": "A"},
        {"role": "isolation",          "pattern": "isolation_arm",    "muscles": ["triceps"],               "superset_group": None},
    ],
    "pull": [  # back + lats + rear delts + biceps + forearms. NEVER triceps.
        {"role": "main_compound",      "pattern": "horizontal_pull",  "muscles": ["back", "lats"],          "superset_group": None},
        {"role": "secondary_compound", "pattern": "vertical_pull",    "muscles": ["lats", "back"],          "superset_group": None},
        {"role": "secondary_compound", "pattern": "horizontal_pull",  "muscles": ["back", "lats", "traps"], "superset_group": None},
        {"role": "isolation",          "pattern": "isolation_shoulder","muscles": ["shoulders"],            "superset_group": "A"},  # rear-delt slot — catalog has only one shoulder bucket
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
    """Per-day signals from daily_summary (when strength_recovery_aware=True)."""
    recovery_score: float | None = None
    readiness_score: float | None = None
    sleep_h: float | None = None

    def is_blocking(self) -> tuple[bool, str | None]:
        """Should we recommend a rest day outright?"""
        if self.recovery_score is not None and self.recovery_score < 25:
            return True, f"recovery score {self.recovery_score:.0f} (very low)"
        if self.readiness_score is not None and self.readiness_score < 20:
            return True, f"readiness {self.readiness_score:.0f} (very low)"
        if self.sleep_h is not None and self.sleep_h < 4:
            return True, f"sleep {self.sleep_h:.1f}h (severely under-slept)"
        return False, None

    def deload_factor(self) -> float:
        """Multiplier on prescribed weight (1.0 = full, 0.85 = 15% deload)."""
        f = 1.0
        if self.recovery_score is not None:
            if self.recovery_score < 40:
                f *= 0.85
            elif self.recovery_score < 60:
                f *= 0.92
        if self.sleep_h is not None and self.sleep_h < 5:
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

def starting_weight_lb(movement_pattern: str, level: str) -> float | None:
    """First-session weight when no history exists. Returns None for
    movement patterns we don't seed (caller falls back to bodyweight)."""
    table = STARTING_WEIGHTS_DB_LB.get(movement_pattern)
    if table is None:
        return None
    return table[LEVEL_INDEX.get(level, 1)]


def progress_from_rating(
    last_weight_lb: float, avg_rating: float, is_compound: bool
) -> float:
    """Apply Fitbod-style RPE-driven progression.

    - rating ≤ 2  → -7.5%  (failed)
    - rating 3-4  →  hold
    - rating ≥ 4.5 → +5% isolation, +10% compound  (easy)
    """
    if avg_rating <= 2.5:
        return last_weight_lb * 0.925
    if avg_rating < 4.5:
        return last_weight_lb
    return last_weight_lb * (1.10 if is_compound else 1.05)


# ------------------------------------------------------------------
# Pure: equipment filter for the catalog
# ------------------------------------------------------------------

def filter_catalog_for_equipment(
    catalog: list[dict[str, Any]], equipment: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep only exercises whose every required piece of equipment is owned.

    'bodyweight' is always considered owned (free movement).
    'bench' requires equipment.bench.flat OR .incline OR .decline.
    'dumbbell' requires equipment.dumbbells.type != 'none'.
    Other tags ('barbell', 'cable', 'kettlebell', 'machine', 'bands')
    require the corresponding equipment flag to be true.
    """
    bench_owned = (
        equipment.get("bench", {}).get("flat")
        or equipment.get("bench", {}).get("incline")
        or equipment.get("bench", {}).get("decline")
    )
    db_owned = equipment.get("dumbbells", {}).get("type", "none") != "none"

    def can_do(ex: dict[str, Any]) -> bool:
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
    slots = SPLIT_SLOTS.get(focus) or SPLIT_SLOTS["full_body"]

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

        # Apply user prefs:
        #   - favorites: if any candidate is favorited, pick from favorites only
        #   - avoid: only consider these as a last resort (push to back)
        if candidates:
            favs = [c for c in candidates if prefs.get(c["id"]) == "favorite"]
            if favs:
                candidates = favs
            else:
                # Combine explicit "avoid" prefs with auto-avoids (low
                # recent ratings) — both pushed to the back.
                def _avoid_score(e: dict[str, Any]) -> int:
                    if prefs.get(e["id"]) == "avoid":
                        return 2
                    if e["id"] in auto_avoid:
                        return 1
                    return 0
                candidates = sorted(candidates, key=_avoid_score)

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

def prescribe_slot(
    ex: dict[str, Any], slot_role: str
) -> tuple[int, int, int, int]:
    """Return (sets, reps_low, reps_high, rest_s) given the exercise + slot role.

    slot_role ∈ {"main_compound", "secondary_compound", "isolation"}.
    """
    if slot_role == "main_compound":
        return (5, 5, 5, DEFAULT_REST_S_HEAVY)
    if slot_role == "secondary_compound":
        return (4, 6, 8, DEFAULT_REST_S_MODERATE)
    return (3, 8, 12, DEFAULT_REST_S_ISOLATION)


# ------------------------------------------------------------------
# DB-bound: read recovery context + history
# ------------------------------------------------------------------

async def read_recovery_inputs(
    db: AsyncSession, target_date: date
) -> RecoveryInputs:
    """Pull the day's daily_summary and project to RecoveryInputs."""
    row = await db.get(models.DailySummary, target_date)
    if row is None:
        return RecoveryInputs()
    sleep_h = (row.sleep_duration_s or 0) / 3600.0 if row.sleep_duration_s else None
    return RecoveryInputs(
        recovery_score=row.recovery_score,
        readiness_score=row.readiness_score,
        sleep_h=sleep_h,
    )


async def last_split_for_user(
    db: AsyncSession, before: datetime | None = None
) -> str | None:
    """Most recent strength workout's split_focus (completed or in progress)."""
    stmt = (
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
        .order_by(models.StrengthWorkout.date.desc())
        .limit(1)
    )
    if before is not None:
        stmt = stmt.where(models.StrengthWorkout.generated_at < before)
    row = (await db.execute(stmt)).scalar_one_or_none()
    return row.split_focus if row else None


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


async def last_target_weight_for_exercise(
    db: AsyncSession, exercise_id: str
) -> tuple[float | None, float | None]:
    """Find the most recent (avg_rating, avg_actual_weight_lb) for an exercise.

    Used to compute next-session weight: if you crushed 25 lb x 8 last
    session (avg_rating 4.8), this session should prescribe ~30 lb.
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
        return None, None

    sets = (await db.execute(
        select(models.StrengthSet)
        .where(models.StrengthSet.workout_exercise_id == wex.id)
        .where(models.StrengthSet.skipped.is_(False))
    )).scalars().all()
    if not sets:
        return None, None

    rated = [s for s in sets if s.rating is not None]
    weighted = [s for s in sets if s.actual_weight_lb is not None]
    avg_rating = sum(s.rating for s in rated) / len(rated) if rated else None
    avg_weight = (
        sum(s.actual_weight_lb for s in weighted) / len(weighted)
        if weighted else None
    )
    return avg_rating, avg_weight


# ------------------------------------------------------------------
# Top-level orchestrator
# ------------------------------------------------------------------

def _seed(target_date: date, regen_count: int) -> str:
    """Deterministic seed: same date + regen yields same plan."""
    s = f"{target_date.isoformat()}#{regen_count}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


async def generate_plan(
    db: AsyncSession,
    target_date: date,
    equipment: dict[str, Any],
    profile: models.UserProfile | None,
    regen_count: int = 0,
    force_no_rest: bool = False,
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

    # Recovery integration
    recovery: RecoveryInputs | None = None
    if profile is None or profile.strength_recovery_aware:
        recovery = await read_recovery_inputs(db, target_date)

    notes: list[str] = []
    if recovery is not None and not force_no_rest:
        blocked, reason = recovery.is_blocking()
        if blocked:
            return GeneratedPlan(
                seed=seed,
                split_focus="rest",
                rest_day_recommended=True,
                rest_day_reason=reason,
                recovery=recovery,
                notes=[
                    f"Rest day recommended — {reason}. You can override via "
                    f"the regenerate button.",
                ],
            )

    last_split = await last_split_for_user(db)
    focus = select_split(days_per_week, split_pref, last_split)

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
    chosen, chosen_slots, sel_notes = select_exercises_for_split(
        catalog, focus, level, rng,
        exercise_prefs=exercise_prefs,
        recent_ratings=recent_ratings,
    )
    notes.extend(sel_notes)
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
    if deload < 1.0:
        notes.append(
            f"Targets reduced by {round((1 - deload) * 100)}% based on today's "
            f"recovery / sleep / readiness. Toggle this off in Settings if you "
            f"prefer the algorithm to ignore those signals."
        )

    plan_exs: list[ExerciseInPlan] = []
    pairs_lb = (equipment.get("dumbbells") or {}).get("pairs_lb") or []
    wrist = equipment.get("wrist_weights_lb") or []

    for i, ex in enumerate(chosen):
        if i == 0:
            slot_role = "main_compound"
        elif i <= 2 and not ex["movement_pattern"].startswith("isolation"):
            slot_role = "secondary_compound"
        else:
            slot_role = "isolation"
        sets, reps_lo, reps_hi, rest_s = prescribe_slot(ex, slot_role)

        # History-driven progression first, then starting weight.
        avg_rating, avg_weight = await last_target_weight_for_exercise(db, ex["id"])
        if avg_rating is not None and avg_weight is not None:
            target = progress_from_rating(avg_weight, avg_rating, ex["is_compound"])
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

    return GeneratedPlan(
        seed=seed,
        split_focus=focus,
        exercises=plan_exs,
        recovery=recovery,
        notes=notes,
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
