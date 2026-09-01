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
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import chain, combinations
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models
from . import taxonomy
from .taxonomy import MUSCLE_VOLUME_TARGETS  # noqa: F401  (re-exported)

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

# DEDUP-1 — entries that are the SAME movement as another catalog row, not
# merely a variant. free-exercise-db and our supplement independently name a
# few identical exercises, which let the generator put both in one session
# ("Incline Dumbbell Row" + "Dumbbell Incline Row" on the same pull day) and
# split progression history across two ids.
#
# Suppressed from *selection* only — the rows stay in CATALOG_BY_ID so
# existing history keeps resolving names, images and PRs. Maps
# superseded_id → the id that supersedes it.
SUPERSEDED_EXERCISE_IDS: dict[str, str] = {
    # Identical chest-supported incline row. Keep the supplement entry: 5
    # coaching steps incl. the chest-pinned cue vs the upstream row's 4.
    "Dumbbell_Incline_Row": "Incline_Dumbbell_Row",
    # Both render as the display name "Decline Push-Up". The upstream row's
    # instructions actually describe a flat wide push-up ("lie on the floor
    # face down... hands about 36 inches apart"), not a decline; the
    # supplement entry correctly elevates the feet on a bench.
    "Decline_Push-Up": "Decline_Push_Up",
    # TD-1: the same crosswise-bench pullover as the Bent-Arm row, down to
    # pointing `image_front` / `image_side` at that row's own directory. It
    # also contradicts itself -- `mechanic: isolation` against
    # `is_compound: true` -- and it was the only carrier of the orphaned
    # `chest_isolation` pattern.
    "Dumbbell_Pullover": "Bent-Arm_Dumbbell_Pullover",
}

# The pool the generator picks from. CATALOG stays complete for history.
CATALOG_SELECTABLE: list[dict[str, Any]] = [
    e for e in CATALOG if e["id"] not in SUPERSEDED_EXERCISE_IDS
]

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
    # free-exercise-db tags the one-arm push-up "intermediate", but a
    # strict single-arm push-up is a genuine advanced calisthenics skill
    # (its sibling Handstand/Archer push-ups are already "advanced").
    # Re-rate so the skill-gated level logic keeps it away from non-
    # advanced users instead of prescribing 4×8 of it to an intermediate.
    "Single-Arm_Push-Up": {"level": "advanced"},
    # Same reasoning as the two pullovers above. It is superseded for
    # selection, but sets already logged against it must credit lats like
    # its siblings rather than chest.
    "Dumbbell_Pullover": {
        "primary_muscle": "lats",
        "secondary_muscles": ["chest", "shoulders", "triceps"],
    },
}
for _eid, _patch in _CATALOG_OVERRIDES.items():
    if _eid in CATALOG_BY_ID:
        CATALOG_BY_ID[_eid].update(_patch)

# TD-1 -- fold the catalog's muscle and movement-pattern vocabulary onto the
# canonical set before anything reads it. The two source files disagree on
# spelling ("quads" vs "quadriceps", "abs" vs "abdominals") and on how finely
# to name a pattern ("tricep_isolation" vs "isolation_arm"), and every
# consumer downstream of here matches by exact equality. Runs after the
# overrides so patched values are folded too, and mutates the row dicts that
# CATALOG, CATALOG_BY_ID and CATALOG_SELECTABLE all share.
taxonomy.normalise_catalog(CATALOG)


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

# Set types that must never influence what to lift NEXT time (OG2-A1).
#
# Both are logged at a deliberately reduced load, so averaging them into the
# next prescription walks the working weight down a little every session: a
# ramp row drags the mean weight, and an easy warm-up drags the mean rating
# toward "add weight" at the same moment. `failure` is deliberately absent —
# Greyskull's last set is taken to failure and is precisely the set that
# should drive the next jump.
#
# This is a narrower question than "was this real work". The volume audit,
# the PR scan and the tonnage total exclude only `warmup`, because a drop set
# IS work performed; it simply is not evidence about the load to prescribe.
# Every reader that answers the progression question imports this tuple, so
# the two cannot drift apart again — they already had, for one release.
PROGRESSION_EXCLUDED_SET_TYPES: tuple[str, ...] = ("warmup", "drop")

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
    # The automatic recovery/readiness-driven deload multiplier that was
    # applied to target weights (1.0 = none). Surfaced on WorkoutOut so the
    # UI can show a "load eased for recovery — use full weight" banner and
    # let the user override via regenerate(force_full_weight=True). Excludes
    # the user-chosen difficulty knob (that's not something to "confirm").
    deload_factor: float = 1.0


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

    `preference` is one of {"auto", "adaptive", "full_body", "upper_lower",
    "ppl"}. "auto" maps days_per_week to the simplest workable split:
        2-3 days → full_body
        4 days   → upper_lower
        5-6 days → ppl

    "adaptive" resolves to the same family here and then rotates. The real
    adaptive pick is `select_split_adaptive`, which needs live volume data;
    this path exists for callers that can only project (the week-ahead
    strip, which can't know future volume). Under adaptive that forecast is
    indicative — the actual day type is chosen on the day.
    """
    if preference in ("auto", "adaptive"):
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
# ADAPT-1: need-based split selection
# ------------------------------------------------------------------
#
# The rotation above only advances on a COMPLETED session, so repeatedly
# skipping one day type parks the schedule on it — the generator keeps
# re-prescribing the session the user is actively avoiding, and the other
# two thirds of the split never reach the calendar. Worse, it's blind to
# volume: it will serve push day after push day while the push muscles sit
# far above MAV.
#
# Adaptive mode scores each candidate focus by how much its muscles
# actually need work (volume vs MEV/MAV) and how long they've been rested,
# and picks the winner. A skip becomes information rather than a lock.

# Relative influence of the two signals. Volume leads — it's the thing
# rotation was blind to — but without a recency term the same
# most-deficient focus would be picked several days running, since one
# session doesn't move a 7-day volume total much.
_ADAPT_VOLUME_WEIGHT = 1.0
_ADAPT_RECENCY_WEIGHT = 0.6
# Rest beyond this many days stops counting as extra need — past a week
# the muscle is fully recovered and more rest isn't more reason.
_ADAPT_RECENCY_CAP_DAYS = 7.0


def muscles_for_focus(focus: str) -> set[str]:
    """Muscles a focus's slot list actually targets.

    Derived from SPLIT_SLOTS rather than a second hand-maintained table,
    so editing a split's slots keeps the adaptive scorer honest. Slots
    with `muscles: None` are pattern-driven (e.g. "squat") and contribute
    nothing here; every push/pull/legs slot names its muscles.
    """
    out: set[str] = set()
    for slot in SPLIT_SLOTS.get(focus) or []:
        for m in slot.get("muscles") or []:
            out.add(m)
    return out


def muscle_need(sets: float, mev: int, mav: int) -> float:
    """How much a muscle wants work, on a continuous scale.

    1.0 at MEV, falling linearly to 0.0 at MAV, negative above it, and
    rising above 1.0 the further below MEV it sits. Continuous at both
    landmarks, so no cliff makes the pick jitter between days.
    """
    if mev <= 0 or mav <= mev:
        return 0.0
    if sets < mev:
        return 1.0 + (mev - sets) / mev
    if sets <= mav:
        return (mav - sets) / (mav - mev)
    return -(sets - mav) / mav


def score_focus(
    focus: str,
    volume: dict[str, dict[str, Any]],
    days_since: dict[str, float],
) -> float:
    """Blended need score for one candidate focus. Higher wants it more."""
    muscles = muscles_for_focus(focus)
    if not muscles:
        return 0.0
    needs = []
    rests = []
    for m in muscles:
        v = volume.get(m)
        if v is not None:
            needs.append(muscle_need(
                float(v.get("sets", 0)), int(v["mev"]), int(v["mav"]),
            ))
        rests.append(min(
            float(days_since.get(m, _ADAPT_RECENCY_CAP_DAYS)),
            _ADAPT_RECENCY_CAP_DAYS,
        ))
    vol = sum(needs) / len(needs) if needs else 0.0
    rec = (sum(rests) / len(rests)) / _ADAPT_RECENCY_CAP_DAYS if rests else 0.0
    return _ADAPT_VOLUME_WEIGHT * vol + _ADAPT_RECENCY_WEIGHT * rec


def select_split_adaptive(
    days_per_week: int,
    preference: str,
    volume: dict[str, dict[str, Any]],
    days_since: dict[str, float],
    last_split: str | None = None,
) -> tuple[str, dict[str, float]]:
    """Pick the focus whose muscles most need work.

    `preference` selects the candidate family the same way `select_split`
    does ("adaptive" resolves like "auto"); adaptive only changes WHICH
    member of that family is chosen, never the family itself. Returns
    `(focus, scores)` so callers can explain the pick to the user.

    Never repeats `last_split` when another candidate exists — one session
    barely moves a 7-day volume total, so without this guard a deep
    deficit could win several days in a row.
    """
    if preference in ("adaptive", "auto"):
        if days_per_week <= 3:
            preference = "full_body"
        elif days_per_week == 4:
            preference = "upper_lower"
        else:
            preference = "ppl"
    candidates = ROTATION.get(preference) or ROTATION["full_body"]
    scores = {f: score_focus(f, volume, days_since) for f in candidates}
    eligible = [f for f in candidates if f != last_split] or list(candidates)
    # Tie-break on rotation order so an exact tie stays deterministic.
    best = max(eligible, key=lambda f: (scores[f], -candidates.index(f)))
    return best, scores


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


def next_loadable_above(
    current: float | None,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
    tol: float = 0.01,
) -> float | None:
    """Smallest loadable weight strictly heavier than `current`.

    The escape hatch from the fixed-dumbbell dead zone. When a percentage
    progression rounds back onto the weight already being used, this is
    what the rack can actually deliver next — coarse, but real. Returns
    None only when `current` is already the heaviest loadable weight.
    """
    if current is None:
        return None
    for w in valid_dumbbell_loads(pairs_lb, wrist_weights_lb):
        if w > current + tol:
            return w
    return None


def _fmt_lb(x: float) -> str:
    """Trim trailing .0 — 30.0 -> '30', 2.5 -> '2.5'."""
    return f"{round(float(x), 2):g}"


def _subset_for_sum(
    items: list[float], target: float, tol: float = 0.05
) -> list[float] | None:
    """Smallest subset of `items` summing to `target` (within tol), or None.
    Fewest items first, so the hint uses the least hardware. items are few
    (wrist weights, ≤8) so brute force is fine."""
    if abs(target) < tol:
        return []
    for r in range(1, len(items) + 1):
        for combo in combinations(items, r):
            if abs(sum(combo) - target) < tol:
                return list(combo)
    return None


def describe_load(
    weight_lb: float | None,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
) -> str | None:
    """LOAD-1: a one-line "how to load it" hint for a prescribed per-dumbbell
    weight — the heaviest owned pair the target sits on, plus the micro-loaders
    that make up the difference (e.g. "30 lb DB + 2.5 lb wrist").

    Returns None when there's nothing worth saying: no weight, no dumbbells,
    the target IS a plain owned pair (the number already tells you), or no
    combo of owned gear reconstructs it. Deliberately silent unless micro-
    loaders are actually involved, to keep it out of the default path."""
    if weight_lb is None or not pairs_lb:
        return None
    w = round(float(weight_lb), 2)
    # A plain dumbbell already answers "how to load it".
    if any(abs(w - p) < 0.05 for p in pairs_lb):
        return None
    if not wrist_weights_lb:
        return None
    # Heaviest base pair that the wrist weights can top up to the target —
    # fewest, lightest add-ons.
    for p in sorted(pairs_lb, reverse=True):
        if p > w + 0.05:
            continue
        combo = _subset_for_sum(wrist_weights_lb, round(w - p, 2))
        if combo:
            micros = " + ".join(_fmt_lb(x) for x in sorted(combo))
            return f"{_fmt_lb(p)} lb DB + {micros} lb wrist"
    return None


def estimate_1rm(weight_lb: float | None, reps: int | None) -> float | None:
    """Epley estimated 1-rep-max: weight * (1 + reps/30). Reps are capped at
    12 (Epley over-estimates for very high reps); a single rep returns the
    weight itself. Returns None for missing/non-positive input. Rounded to
    1dp. Epley is a public formula — implemented from scratch (e1RM-1)."""
    if weight_lb is None or reps is None:
        return None
    try:
        w = float(weight_lb)
        r = int(reps)
    except (TypeError, ValueError):
        return None
    if w <= 0 or r <= 0:
        return None
    if r == 1:
        return round(w, 1)
    return round(w * (1.0 + min(r, 12) / 30.0), 1)


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


def deload_round(
    target_lb: float | None,
    deload: float,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
) -> float | None:
    """Round a deloaded target to a loadable weight, but DON'T let coarse
    equipment turn a light/moderate deload into a disproportionate cut.

    With only 5-lb dumbbell pairs and no micro-loaders, an 8% recovery deload
    on a 15 lb lift (→13.8) rounds DOWN to the next pair (10 lb = −33%), and a
    10 lb lift (→9.2) drops to 5 (−50%). That made a gentle, intended easing
    feel like a brutal one. Here, when the forced cut is far larger than
    intended (>2× the intended reduction) AND the deload was only light/
    moderate (≥0.85), we hold the full-weight rounding instead — a gentle
    deload should never knock off a whole pair. Severe deloads (<0.85, i.e.
    multiple low recovery signals) still take the pair drop, and fine-grained
    setups (micro-loaders) are unaffected because the deloaded weight lands
    close to intended so the guard never trips.
    """
    if target_lb is None:
        return None
    full = round_weight(target_lb, pairs_lb, wrist_weights_lb)
    if deload >= 1.0 or full is None:
        return full
    deloaded = round_weight(target_lb * deload, pairs_lb, wrist_weights_lb)
    if deloaded is None or deloaded >= full:
        return full
    intended_cut = target_lb * (1.0 - deload)
    actual_cut = full - deloaded
    if actual_cut > 2.0 * intended_cut and deload >= 0.85:
        return full  # coarse rounding over-corrected — hold full weight
    return deloaded


# ------------------------------------------------------------------
# Pure: starting weight + rating-driven progression
# ------------------------------------------------------------------

# Rating scale (WP-16): the UI presents four buttons that map to these
# numeric values — Failed=1, Hard=2, Good=4, Easy=5. The thresholds below
# split that into the four progression actions; historical 1–5 RPE data
# still interprets correctly under the same gates. Shared by
# progress_from_rating (weight) and double_progression (rep+weight).
#   Failed (1) → deload      (≤ FAIL_THRESHOLD)
#   Hard   (2) → hold        (FAIL < r < REP_PROGRESS_MIN)
#   Good   (4) → add a rep   (REP_PROGRESS_MIN ≤ r < EASY)
#   Easy   (5) → add weight  (≥ EASY_THRESHOLD, at top of rep range)
FAIL_THRESHOLD = 1.5   # ≤ this → cut weight next session (mostly-failed)
EASY_THRESHOLD = 4.5   # ≥ this → the rating policy wants a weight jump
REP_PROGRESS_MIN = 3.0  # ≥ this → solid set, add a rep (double progression)
AUTO_AVOID_THRESHOLD = 1.5  # 14d avg ≤ this → rotate the exercise out


def starting_weight_lb(movement_pattern: str, level: str) -> float | None:
    """First-session weight when no history exists. Returns None for
    movement patterns we don't seed (caller falls back to bodyweight)."""
    table = STARTING_WEIGHTS_DB_LB.get(movement_pattern)
    if table is None:
        return None
    return table[LEVEL_INDEX.get(level, 1)]


#: What one logged set contributes to an aggregate (OG2-A3).
#:
#: ``excluded``   not work: skipped, a warm-up, or never actually logged.
#: ``unweighted`` real work carrying no poundage — a pull-up, a plank.
#: ``weighted``   real work with a load, so it can enter a pounds total.
SET_EXCLUDED = "excluded"
SET_UNWEIGHTED = "unweighted"
SET_WEIGHTED = "weighted"


def rest_after_set(
    is_last_set_of_session: bool,
    superset_partner_owes_this_round: bool,
    target_rest_s: int,
    within_round_rest_s: int = DEFAULT_REST_S_SUPERSET_WITHIN,
) -> int:
    """How long to rest after the set just logged. 0 means do not rest.

    One predicate, server-side, because both clients had their own and both
    were wrong in the same two ways (OG2-A7).

    A rest belongs after every completed set — including the last set of an
    exercise, because another exercise follows and you rest before that too.
    The ONE set with nothing left to time is the last set of the SESSION,
    where there is no next effort. Both surfaces guarded only on
    `if (!skipped)`, so finishing a workout started a countdown while the
    user racked the weights.

    Mid-round in a superset the rest is short, because the point of the
    pairing is to work the partner while this muscle recovers. Once the
    partner has taken this round, the full rest applies. Both clients
    hard-coded `35` for this, in Vue and again in Kotlin, so the two
    surfaces could disagree about how long a rest was and a change had to be
    made twice.
    """
    if is_last_set_of_session:
        return 0
    if superset_partner_owes_this_round:
        return within_round_rest_s
    return target_rest_s


def classify_set_row(
    skipped: bool, reps: int | None, set_type: str | None,
    weight_lb: float | None,
) -> str:
    """Sort one logged set into what it may contribute to.

    The distinction this draws is the whole of OG2-A3. Two aggregates asked
    "does this set have poundage" when they meant "was this set performed",
    and dropped every null-weight row before counting anything — so
    ``n_workouts``, ``n_sets``, the daily series, the ratings and the muscle
    split all excluded pull-ups, planks and push-ups, and a calisthenics-only
    day read as no session at all. On this database that is 233 of 760 logged
    sets and 101 of 275 catalog exercises, on a home gym of dumbbells, a
    bench and a pull-up bar.

    Being performed and being costable in pounds are separate questions, and
    conflating them is what made a whole training day disappear. An
    unweighted set is counted as work and withheld from the pounds figures —
    never costed at zero, because a volume total that quietly absorbs a set
    of pull-ups as 0 lb is worse than one that admits it is partial. That is
    the same rule ``_sum_nutrition`` follows for an ingredient it cannot
    cost, and the same reason ``/records`` reports bodyweight bests on their
    own metric rather than as a weight of nothing.

    ``/records`` already fixed this in PR-1b and ``list_workouts`` always had
    it right; the two remaining sites did not. Sharing the predicate is what
    stops a third reader inventing a fourth answer.
    """
    if skipped or reps is None or set_type == "warmup":
        return SET_EXCLUDED
    if weight_lb is None:
        return SET_UNWEIGHTED
    return SET_WEIGHTED


@dataclass(frozen=True)
class SetFacts:
    """One logged set, without a database. What the reducer reads and no more.

    Separating this from the ORM row is what makes the judgement testable at
    all — the house style for anything that decides what to lift, matching
    `analytics/targets.py` (numbers in, numbers out) and
    `analytics/projection.py`.
    """
    skipped: bool
    actual_reps: int | None
    set_type: str | None
    actual_weight_lb: float | None
    rating: int | None


@dataclass(frozen=True)
class SessionRead:
    """How one past session of one exercise actually went — OG2-B1.

    The point of this type is `enough`. `target_sets` was written on seven
    construction sites in this module and read back by no progression reader,
    so logging 2 of 4 prescribed sets and rating them Easy produced the same
    weight jump as logging all 4 — a +20% advance off half the work, and the
    truncation biases BOTH inputs toward advancing: the sets a user abandons
    are the late ones, which are the hard ones.

    `prescribed_sets` is read off the HISTORICAL slot, never today's freshly
    generated number. FAST-18 modulates the count before it is persisted —
    fewer sets at 18h and 24h fasted — so comparing last session against
    today's prescription would let a fasted day retroactively declare a
    complete session incomplete, or the reverse.
    """
    prescribed_sets: int
    performed_sets: int
    declined: bool
    avg_rating: float | None
    avg_weight_lb: float | None
    avg_reps: float | None

    @property
    def enough(self) -> bool:
        """Did the user perform what was prescribed?

        A declined slot (SKIP-1) is not a short session — it is a decision,
        and it carries no sets to judge.
        """
        return not self.declined and self.performed_sets >= self.prescribed_sets

    @property
    def has_history(self) -> bool:
        return self.performed_sets > 0


def read_session(
    *,
    target_sets: int,
    slot_declined: bool,
    sets: Sequence[SetFacts],
) -> SessionRead:
    """Reduce one session's logged sets to the facts a prescription needs.

    Pure. The qualifying predicate is the same one `PROGRESSION_EXCLUDED_SET_TYPES`
    names: a warm-up and a drop set are real work but are not evidence about
    the load to prescribe next.
    """
    performed = [
        s for s in sets
        if not s.skipped
        and s.actual_reps is not None
        and (s.set_type or "working") not in PROGRESSION_EXCLUDED_SET_TYPES
    ]
    rated = [s.rating for s in performed if s.rating is not None]
    weighted = [s.actual_weight_lb for s in performed if s.actual_weight_lb is not None]
    repped = [s.actual_reps for s in performed if s.actual_reps is not None]
    return SessionRead(
        prescribed_sets=max(0, target_sets),
        performed_sets=len(performed),
        declined=slot_declined,
        avg_rating=sum(rated) / len(rated) if rated else None,
        avg_weight_lb=sum(weighted) / len(weighted) if weighted else None,
        avg_reps=sum(repped) / len(repped) if repped else None,
    )


def stall_count(sessions: Sequence[SessionRead]) -> int:
    """Consecutive recent sessions, NEWEST FIRST, that were not `enough`.

    Reported, never acted on — deliberately, and this is the load-bearing
    restraint of OG2-B1. There are already three deloads: the rating policy
    cuts 7.5% at `avg_rating <= FAIL_THRESHOLD`, the recovery factor
    multiplies up to 0.85 x 0.90 and `generate_plan` multiplies again by 0.90
    on an easy day, and PROG-1 cuts the stored weight on its own fail streak.
    0.6885 is reachable today with no stall logic at all, so a fourth
    multiplier is exactly the compounding this codebase refuses elsewhere.

    It exists because the AI coach cannot currently see a stall at all:
    `build_deload_payload` sends four coarse 14-day numbers with no
    per-exercise resolution, and its `missed_or_skipped_sets` counts rows
    with null reps — of which production has zero, because an unlogged set
    has no row. So a partial session is invisible to the deload check today.
    A count lets the coach say "bench has fallen short three sessions
    running" instead of "average rating is down 0.4", and leaves the decision
    with the model and the user rather than silently multiplying a weight.

    A single `enough` session zeroes it.
    """
    n = 0
    for s in sessions:
        if s.enough:
            break
        n += 1
    return n


def weight_from_history(
    avg_weight_lb: float | None,
    avg_rating: float | None,
    is_compound: bool,
    goal: str = "hypertrophy",
    enough: bool = True,
) -> tuple[float | None, str]:
    """Next session's load from the last one, and the reason for it.

    Three outcomes, and the middle one is the fix (OG2-A2). Every call site
    used to test `avg_rating is not None and avg_weight is not None` and fall
    all the way through to `starting_weight_lb` otherwise — a table indexed by
    declared experience level. So a session logged with real weights but no
    rating threw its own history away: press 40 lb, forget to tap
    Hard/Good/Easy, get re-prescribed 25 lb. `avg_weight` was in scope on that
    line and discarded.

    Reachable because a rating is optional on the way in. The phone requires
    one before a set can be logged, but the web logger does not, and imported
    Strong/Hevy history carries a rating only when the source file had an RPE
    column.

    * Both known — the rating says how the load felt, so `progress_from_rating`
      decides: fail backs off, the middle holds, easy advances.
    * Weight known, rating absent — hold at what was actually lifted. "Same as
      last time" is the honest reading of an unrated session. It is not
      evidence to advance on, and it is certainly not evidence that the lifter
      has reverted to a beginner's table.
    * Neither — return None so the caller falls back to the starting table,
      which is the right answer only when there is genuinely no history.

    Returns the reason alongside the number because three code paths produce a
    weight and, until now, two of them were indistinguishable on inspection.
    """
    if avg_weight_lb is None:
        return None, "no_history"
    if avg_rating is None:
        return avg_weight_lb, "held_unrated"

    proposed = progress_from_rating(
        avg_weight_lb, avg_rating, is_compound, goal=goal,
    )
    # OG2-B1: a short session gates the ADVANCE and never the deload, and the
    # asymmetry is the whole decision. Two sets rated Easy out of four
    # prescribed are not evidence the prescription was met — and the sets a
    # user abandons are the late ones, which are the hard ones, so truncation
    # biases the average toward "advance" precisely when it is least earned.
    # Two sets rated Failed, though, are real evidence to cut: refusing to
    # act on them would leave a weight the user could not lift standing
    # because they stopped early, which is the wrong way round.
    if not enough and proposed > avg_weight_lb:
        return avg_weight_lb, "held_incomplete"
    return proposed, "rated"


def progress_from_rating(
    last_weight_lb: float, avg_rating: float, is_compound: bool,
    goal: str = "hypertrophy",
) -> float:
    """Apply Fitbod-style RPE-driven progression, modulated by goal.

    Fail handling is goal-agnostic: rating ≤ FAIL_THRESHOLD → -7.5%.
    Hold zone: FAIL_THRESHOLD < rating < EASY_THRESHOLD → no change.
    Easy zone (rating ≥ EASY_THRESHOLD) → goal-specific jump.

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
    session_complete: bool = True,
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
        return deload_round(w, deload, pairs_lb, wrist_weights_lb)

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

    # OG2-B1: every branch below this point ADVANCES — more weight in 2 and
    # 4, more reps in 3. A session that fell short of its prescribed sets is
    # not evidence that any of them were earned, so they are all skipped and
    # the load holds. Branch 1 (the near-failure cut) sits above this line
    # deliberately: a short session is still real evidence to back off.
    if not session_complete:
        return held, base_reps_lo, base_reps_hi, None

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

    # 4. At the top, rating it easy, but the percentage jump rounded back
    #    to the same load. Take the next weight the rack CAN deliver.
    #
    #    This used to hold the current weight and tell the user to buy
    #    micro-loaders — which pins the lift forever if they never do.
    #    A 25 lb pullover topping out at 12 reps has 30 lb sitting right
    #    there; +20% is coarser than the +5% the policy wanted, but it is
    #    real progression and reps reset to the bottom of the range to
    #    absorb it. Warn about the size of the step, don't refuse it.
    if at_top and last_avg_rating >= EASY_THRESHOLD:
        step = next_loadable_above(held, pairs_lb, wrist_weights_lb)
        if step is not None and held:
            pct = (step - held) / held
            # Compare against the UNROUNDED policy target. Using `jumped`
            # here read "~+0% was wanted", because in this branch it has by
            # definition rounded back onto the current load.
            raw_target = progress_from_rating(
                last_weight_lb, last_avg_rating, is_compound, goal=goal,
            )
            ideal = (
                (raw_target / last_weight_lb - 1.0)
                if raw_target and last_weight_lb else 0.0
            )
            advisory = None
            # Only worth a word when the forced step is materially bigger
            # than the progression policy asked for.
            if pct > max(ideal, 0.0) + 0.02:
                advisory = (
                    f"next dumbbell is a +{pct * 100:.0f}% jump "
                    f"({held:g} → {step:g} lb) where ~+{max(ideal, 0.0) * 100:.0f}% "
                    "was wanted — reps reset to the bottom of the range. "
                    "Wrist/micro weights in Equipment would make this "
                    "gradual, or log fewer reps and build back up."
                )
            return step, base_reps_lo, base_reps_hi, advisory
        # Genuinely nothing heavier exists — the top of the rack.
        advisory = (
            "at the heaviest load you own and maxing the rep range — "
            "add heavier dumbbells or wrist/micro weights in Equipment "
            "to keep progressing."
        )
        return held, base_reps_hi, base_reps_hi, advisory

    # 5. Hold zone (moderate rating, mid-range) → hold weight + base reps.
    return held, base_reps_lo, base_reps_hi, None


# ------------------------------------------------------------------
# Pure: PROG-1 program mode (named linear-progression schemes)
# ------------------------------------------------------------------

# Sensible per-scheme defaults used when seeding a new program lift.
# The config UI only asks for {scheme, exercise, starting weight}; the
# rest come from here. Kept in sync with ProgramLiftState defaults.
#   greyskull — 5×5 with the last set AMRAP; a single miss deloads 10%.
#   linear    — straight 3×5 (StrongLifts-ish); 3 misses → 10% deload.
#   double    — 3×8-12; add reps to the top of the range, then +weight.
PROGRAM_SCHEME_DEFAULTS: dict[str, dict] = {
    "greyskull": {
        "sets": 3, "reps_low": 5, "reps_high": 5, "amrap_last_set": True,
        "increment_lb": 5.0, "fails_before_deload": 1, "deload_pct": 0.10,
        "rest_s": 180,
    },
    "linear": {
        "sets": 3, "reps_low": 5, "reps_high": 5, "amrap_last_set": False,
        "increment_lb": 5.0, "fails_before_deload": 3, "deload_pct": 0.10,
        "rest_s": 180,
    },
    "double": {
        "sets": 3, "reps_low": 8, "reps_high": 12, "amrap_last_set": False,
        "increment_lb": 5.0, "fails_before_deload": 3, "deload_pct": 0.10,
        "rest_s": 150,
    },
}


def prescribe_program_lift(
    state: dict,
    pairs_lb: list[float],
    wrist_weights_lb: list[float],
) -> dict:
    """Today's prescription for a program-mode lift — a fixed scheme,
    NOT the recovery/rating oracle. Deterministic from the stored
    working weight; snapped to a loadable combo via round_weight so the
    number is always achievable on the user's rack.

    Returns a dict the generate_plan Hook B consumes directly:
      {sets, reps_lo, reps_hi, weight_lb, rest_s, amrap_last, note}
    weight_lb is None for a bodyweight program lift (rep-only scheme).
    """
    scheme = state.get("scheme", "linear")
    sets = int(state.get("sets", 3))
    lo = int(state.get("reps_low", 5))
    hi = max(int(state.get("reps_high", lo)), lo)
    rest = int(state.get("rest_s", 180))
    inc = float(state.get("increment_lb", 5.0))
    cw = state.get("current_weight_lb")
    weight = (
        round_weight(float(cw), pairs_lb, wrist_weights_lb)
        if cw is not None else None
    )
    amrap = bool(state.get("amrap_last_set")) and scheme == "greyskull"

    if scheme == "greyskull":
        note = (
            f"Greyskull LP · last set AMRAP (aim {lo}+) · "
            f"+{_fmt_lb(inc)} lb when it clears, double at {lo * 2}+"
        )
    elif scheme == "double":
        note = (
            f"Double progression · {lo}-{hi} reps · "
            f"+{_fmt_lb(inc)} lb once you hit {hi} on every set"
        )
    else:
        note = f"Linear progression · {sets}×{lo} · +{_fmt_lb(inc)} lb next session"

    return {
        "sets": sets,
        "reps_lo": lo,
        "reps_hi": hi,
        "weight_lb": weight,
        "rest_s": rest,
        "amrap_last": amrap,
        "note": note,
    }


def advance_program_lift(
    state: dict,
    min_working_reps: int | None,
    amrap_reps: int | None = None,
    on_date: str | None = None,
) -> dict:
    """Advance a program lift's stored state after a completed session.

    Pure state machine — returns a NEW state dict, never mutates the
    input. The caller (patch_workout completion hook) passes:
      - min_working_reps: the MINIMUM reps completed across the fixed
        working sets (None = nothing logged → no advance).
      - amrap_reps: the Greyskull AMRAP set's reps (ignored otherwise).
      - on_date: ISO date to stamp last_advanced_on (double-advance guard).

    Schemes:
      linear    — all sets hit reps_low → +increment; else fail streak,
                  deload deload_pct after fails_before_deload misses.
      greyskull — AMRAP ≥ reps_low → +increment (double at 2×reps_low);
                  a miss deloads immediately (fails_before_deload=1).
      double    — min reps ≥ reps_high → +increment (reset to reps_low);
                  reps_low ≤ min < reps_high → hold (rep progress, not a
                  fail); below reps_low → fail streak → deload.
    Bodyweight lifts (current_weight_lb is None) never move weight; they
    just stamp the date so the generator's rep progression carries them.
    """
    out = dict(state)
    if min_working_reps is None:
        # Nothing logged this session — hold everything AND do NOT stamp
        # last_advanced_on. Stamping here would burn the per-date
        # idempotency guard: an empty completion (finished with no logged
        # sets) would consume the date, and a later real completion for the
        # same date would be skipped, stalling the lift forever.
        return out
    if on_date is not None:
        out["last_advanced_on"] = on_date

    scheme = state.get("scheme", "linear")
    w = state.get("current_weight_lb")
    if w is None:
        return out  # bodyweight lift — no weight to progress

    w = float(w)
    inc = float(state.get("increment_lb", 5.0))
    lo = int(state.get("reps_low", 5))
    hi = max(int(state.get("reps_high", lo)), lo)
    fails = int(state.get("consecutive_fails", 0))
    fbd = int(state.get("fails_before_deload", 3))
    dpct = float(state.get("deload_pct", 0.10))

    if scheme == "greyskull":
        top = amrap_reps if amrap_reps is not None else min_working_reps
        if top >= lo:
            jump = inc * (2 if top >= lo * 2 else 1)
            out["current_weight_lb"] = round(w + jump, 1)
            out["consecutive_fails"] = 0
        else:
            out["current_weight_lb"] = round(w * (1.0 - dpct), 1)
            out["consecutive_fails"] = 0
        return out

    if scheme == "double":
        if min_working_reps >= hi:
            out["current_weight_lb"] = round(w + inc, 1)
            out["consecutive_fails"] = 0
        elif min_working_reps >= lo:
            out["consecutive_fails"] = 0  # rep progress in-range — hold weight
        else:
            fails += 1
            if fails >= fbd:
                out["current_weight_lb"] = round(w * (1.0 - dpct), 1)
                fails = 0
            out["consecutive_fails"] = fails
        return out

    # linear (default)
    if min_working_reps >= lo:
        out["current_weight_lb"] = round(w + inc, 1)
        out["consecutive_fails"] = 0
    else:
        fails += 1
        if fails >= fbd:
            out["current_weight_lb"] = round(w * (1.0 - dpct), 1)
            fails = 0
        out["consecutive_fails"] = fails
    return out


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
    # BAR-2 — "Hang from a pull-up bar using a pronated grip", tagged
    # equipment=['bodyweight'] upstream, so it was reaching a dumbbell-only
    # gym as an isolation_core slot. Landed in a real generated plan.
    "Wind_Sprints",
})

# Same catalog quirk, different gate: these need a *waist-height* bar to
# pull under (barbell in a rack, Smith, or rings/suspension), NOT an
# overhead pull-up bar. free-exercise-db tags them equipment=['bodyweight']
# so they'd otherwise leak into a dumbbell-only home gym (e.g. Inverted_Row
# showing up as the pull-day main compound for someone with no bar at all).
# Gated on barbell OR squat_rack OR pull_up_bar — any of which can rig a low
# bar / rings — rather than pull_up_bar alone (a doorway bar is too high).
_LOW_BAR_REQUIRED_EXERCISES: frozenset[str] = frozenset({
    "Inverted_Row",
    # BAR-2 — "Position a bar in a rack at chest height." Needs a fixed bar,
    # not just a body.
    "Body_Tricep_Press",
    # BAR-2 — parallel dip bars ("arms nearly locked above the bars"). The
    # equipment schema has no dip-station flag, and this is the closest
    # honest gate: a squat rack or a power-tower-style pull-up bar can be
    # dipped on, a pair of dumbbells cannot. Bench dips are a separate
    # catalog entry and stay available.
    "Dips_-_Triceps_Version",
})

# Exercises that genuinely REQUIRE a second person to perform — a partner
# applies the resistance or the movement is impossible solo. free-exercise-db
# tags them equipment=['bodyweight'], so without this gate they'd be
# prescribed to a solo home-gym user who literally can't do them. Dropped
# by id when equipment.training_partner is false. Kept deliberately narrow:
# exercises where a spotter is only *optional* (racking heavy DBs, holding
# feet on sit-ups, or a "brace your feet instead" alternative) are doable
# solo and stay in the catalog.
_PARTNER_REQUIRED_EXERCISES: frozenset[str] = frozenset({
    "Standing_Towel_Triceps_Extension",  # partner grips the towel to resist
    "Prone_Manual_Hamstring",            # "you will need a partner" — manual resistance
})

# WP-18 — qualifier words stripped when deriving an exercise's "movement
# family" (the core noun). Lets us tell that "Straight-Arm Dumbbell Pullover"
# and "Bent-Arm Dumbbell Pullover" are the SAME movement so the finisher
# doesn't add a second pullover when the pull slot already substituted one.
_FAMILY_QUALIFIERS: frozenset[str] = frozenset({
    "dumbbell", "barbell", "cable", "machine", "band", "bands",
    "incline", "decline", "flat", "seated", "standing", "lying", "kneeling",
    "alternate", "alternating", "single", "one", "two", "arm", "leg", "legs",
    "bent", "straight", "close", "wide", "neutral", "reverse", "overhead",
    "grip", "with", "a", "an", "the", "of", "on", "over", "to", "in", "out",
    "up", "down", "palms", "front", "rear", "side", "high", "low", "body",
    "weighted", "db", "and", "for", "head",
})


def _name_family(name: str) -> str:
    """Coarse movement family from an exercise name — the last non-qualifier
    word (e.g. 'pullover', 'twist', 'crunch'). Used to block near-duplicate
    variants from landing in the same day."""
    words = re.split(r"[\s_/+-]+", name.lower())
    core = [w for w in words if w and w not in _FAMILY_QUALIFIERS]
    return core[-1] if core else name.lower()


def selectable_catalog_ids(
    equipment: dict[str, Any],
    exercise_prefs: dict[str, str] | None = None,
) -> set[str]:
    """Ids the generator would actually consider, as a set.

    Three filters, matching what `select_exercises_for_split` applies:
    equipment the user owns, exercises they have not disabled, and the
    supersede list that keeps duplicate rows out of selection.

    Extracted so the AI surfaces can be gated on the same rule. The variety
    nudge used to receive the whole catalog and was free to suggest swapping
    in a barbell exercise for someone who owns dumbbells, or an exercise the
    user had explicitly turned off — which reads as the coach not having read
    the settings, and costs a call to produce advice that cannot be taken.
    """
    prefs = exercise_prefs or {}
    allowed = filter_catalog_for_equipment(CATALOG_SELECTABLE, equipment)
    return {
        e["id"] for e in allowed
        if prefs.get(e["id"]) != "disabled"
    }


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

    DEDUP-1 superseded ids are dropped here rather than at module load, so
    every generation path picks them up (they all funnel through this
    function) while CATALOG itself stays complete for history lookups.
    """
    catalog = [e for e in catalog if e["id"] not in SUPERSEDED_EXERCISE_IDS]
    return [e for e in catalog if can_do_exercise(e, equipment)]


def can_do_exercise(ex: dict[str, Any], equipment: dict[str, Any]) -> bool:
    """Can this one exercise be performed with the equipment owned?

    Extracted from `filter_catalog_for_equipment` (OG2-A6) so the same
    question can be asked about an exercise that is ALREADY in a plan, not
    only about candidates for a new one. Selling a bench does not un-write
    yesterday's prescription, and until this existed nothing could tell the
    user that a slot in front of them had become undoable.
    """
    bench_owned = (
        equipment.get("bench", {}).get("flat")
        or equipment.get("bench", {}).get("incline")
        or equipment.get("bench", {}).get("decline")
    )
    db_owned = equipment.get("dumbbells", {}).get("type", "none") != "none"
    bar_owned = bool(equipment.get("pull_up_bar"))
    partner_owned = bool(equipment.get("training_partner"))
    # A waist-height bar can be rigged from any of these; a doorway
    # pull-up bar alone (bar_owned) is too high for inverted rows.
    low_bar_owned = bool(
        equipment.get("barbell")
        or equipment.get("squat_rack")
        or equipment.get("pull_up_bar")
    )

    if not bar_owned and ex["id"] in _BAR_REQUIRED_EXERCISES:
        return False
    if not low_bar_owned and ex["id"] in _LOW_BAR_REQUIRED_EXERCISES:
        return False
    if not partner_owned and ex["id"] in _PARTNER_REQUIRED_EXERCISES:
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


# ------------------------------------------------------------------
# Pure: exercise selection for a given split focus
# ------------------------------------------------------------------

def _level_bucket(ex_level: str, target_level: str) -> int:
    """Level eligibility for slot ranking: 0 = in-band, 1 = deprioritised.

    Adjacent levels are in-band so a beginner still rotates through
    intermediate variety (WP-18). BUT advanced moves are skill-gated —
    a genuine advanced movement (one-arm / archer push-up, handstand
    push-up, pistol squat, etc.) is only in-band for an *advanced* user.
    An intermediate must not be prescribed 4×8 one-arm push-ups just
    because 'advanced' is one level up.

    This only changes intermediate users: beginners are already 2 levels
    from advanced (so it was deprioritised anyway), and advanced users
    still match advanced moves. Beginner↔intermediate reach is untouched.
    """
    lvl = LEVEL_INDEX.get(ex_level, 1)
    tgt = LEVEL_INDEX.get(target_level, 1)
    advanced = LEVEL_INDEX["advanced"]
    if lvl == advanced and tgt < advanced:
        return 1
    return 0 if abs(lvl - tgt) <= 1 else 1


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
        # WP-18 — SOFT level (adjacent levels in-band so a beginner still
        # rotates intermediate variants), but advanced moves are skill-
        # gated to advanced users only — see _level_bucket.
        level_score = _level_bucket(e["level"], level)
        return (compound_score, level_score, e["id"])

    return sorted(matches, key=rank_key)


# DEDUP-1 — near-duplicate co-selection guard.
#
# Beyond the handful of outright duplicates above, the catalog carries many
# legitimate close variants (palms-up vs palms-down wrist curl, one-arm vs
# two-arm extension). Those are good *across* sessions — that's rotation —
# but two of them in one workout reads as a bug and narrows the session.
#
# So they stay in the catalog and are instead deprioritised within a single
# workout: same primary muscle AND same movement pattern AND name-token
# Jaccard over the threshold. Name overlap alone is too blunt (every
# dumbbell exercise shares "dumbbell"), hence all three conditions.
_NEAR_DUP_JACCARD = 0.6
_NAME_STOPWORDS = frozenset({"the", "a", "with", "and", "on", "to", "in", "of"})


def _stem(tok: str) -> str:
    """Crude plural strip. The catalog mixes singular and plural freely —
    "Hammer Curls" vs "Alternate Hammer Curl", "Tricep" vs "Triceps" — and
    without this they tokenise as unrelated words, so twelve genuinely
    near-identical pairs scored 0 overlap. Correctness as English doesn't
    matter here, only that it's applied symmetrically to both names.
    """
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok


def _name_tokens(name: str) -> frozenset[str]:
    return frozenset(
        _stem(t) for t in re.split(r"[^a-z0-9]+", (name or "").lower())
        if t and t not in _NAME_STOPWORDS
    )


def is_near_duplicate(
    a: dict[str, Any], b: dict[str, Any], threshold: float = _NEAR_DUP_JACCARD,
) -> bool:
    """True when two catalog entries are effectively the same movement."""
    if a.get("primary_muscle") != b.get("primary_muscle"):
        return False
    if a.get("movement_pattern") != b.get("movement_pattern"):
        return False
    ta, tb = _name_tokens(a.get("name", "")), _name_tokens(b.get("name", ""))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


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

    # Auto-avoid: exercises the user keeps FAILING over the last few weeks
    # (14d avg ≤ AUTO_AVOID_THRESHOLD). Treated like a soft 'avoid' pref
    # unless explicitly favorited. Post WP-16 "Hard" (2) is a normal
    # productive rating, so the bar sits at the failing end — only a lift
    # you can't complete gets rotated out.
    auto_avoid = {
        eid for eid, avg in ratings.items()
        if avg is not None and avg <= AUTO_AVOID_THRESHOLD
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
        # DEDUP-1 — prefer candidates that aren't a near-duplicate of
        # something already in this session. Deliberately a preference and
        # not a filter: thin muscles leave almost no choice (lats has two
        # entries for this user's equipment, and they're a near-dup pair),
        # so starving the slot would be worse than a close variant.
        if chosen:
            distinct = [
                c for c in candidates
                if not any(is_near_duplicate(c, k) for k in chosen)
            ]
            if distinct:
                candidates = distinct
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
                # WP-18 — seeded jitter + soft level. Previously equally-fresh
                # candidates (all freq 0 on a new plan) resolved to the same
                # deterministic order, so the top-3 window served the same
                # alphabetically/level-first moves forever and never reached
                # the deep catalog (Russian Twist was ~#36 of 40 ab moves and
                # invisible). `jitter` randomises ties so any fresh candidate
                # can surface; `lvl_bucket` keeps a 2-level mismatch (e.g. an
                # advanced compound for a beginner) deprioritised while
                # treating adjacent levels as equal — so a beginner still sees
                # intermediate isolation variety. Frequency still dominates
                # (rotation pressure intact), so a heavily-used lift stays out
                # of the window while fresher options exist.
                jitter = {c["id"]: rng.random() for c in candidates}

                def _sort_key(e: dict[str, Any]) -> tuple:
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
                    lvl_bucket = _level_bucket(e["level"], level)
                    return (avoid_bucket, bal, freq.get(eid, 0),
                            lvl_bucket, jitter[eid])
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
        # Pick from the top 3 candidates (lets seeded RNG vary across regen
        # calls). The window stays narrow so rotation pressure holds — the
        # jitter in _sort_key, not a wider window, is what delivers variety,
        # so a heavily-used lift can't sneak back in while fresh ones exist.
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

# ── PR-1b: personal records for bodyweight and timed work ────────────
#
# `_detect_pr` used to return early whenever `actual_weight_lb` was None,
# and `/records` filtered those rows out entirely. In production that is
# 233 of 760 logged sets — 31% of everything the user has recorded — and
# 112 of the 275 catalog exercises are bodyweight-only. A push-up session
# could never set a record no matter how it went.
#
# Kinds, in the order they win when more than one fires:
#
#   weight      a heavier top set on a loaded lift
#   e1rm        a better estimated 1RM on a loaded lift
#   added_load  more external load on a bodyweight movement (weighted dips)
#   hold        a longer isometric hold (plank, side bridge)
#   reps        more reps at bodyweight
#
# Deliberately NOT a kind: "more reps at the same weight" on a loaded
# lift. That already fires as an e1rm PR, because more reps at equal
# weight raises the Epley estimate. Adding a separate rep kind would
# double-report the same achievement.
PR_PRECEDENCE: tuple[str, ...] = (
    "weight", "e1rm", "added_load", "hold", "reps",
)


@dataclass(frozen=True)
class PriorSet:
    """One previously logged set, for PR comparison.

    `same_workout` separates "the record before today" from "earlier in
    this session", which is what makes the badge fire once rather than on
    every ascending set.
    """

    weight_lb: float | None
    reps: int | None
    same_workout: bool


def pr_eligible(ex: dict[str, Any]) -> bool:
    """Whether an exercise can hold a personal record at all.

    Mobility is excluded, and this is not tidiness — it would actively
    produce false records. `adjust_mobility_target` raises the prescribed
    hold to the user's own `max_actual`, so the prescription chases the
    best-ever hold. Every time the tuner steps a target up, the next
    session beats the previous best *by construction* and a "record" fires
    for following instructions. Production has 19 mobility poses with
    enough history for that to happen.
    """
    from . import taxonomy
    return taxonomy.canonical_pattern(ex.get("movement_pattern")) != "mobility"


def _pr_metric(
    ex: dict[str, Any], kind: str, weight_lb: float | None, reps: int | None,
) -> float | None:
    """The comparable number for one PR kind, or None if inapplicable."""
    if reps is None or reps <= 0:
        return None
    bodyweight = _is_bodyweight_only(ex)
    timed = bool(ex.get("is_timed"))

    if kind == "weight":
        if bodyweight or weight_lb is None:
            return None
        return weight_lb
    if kind == "e1rm":
        # Gated on NOT bodyweight. Without that gate a weighted dip logged
        # at 25 lb produces an e1RM computed as though 25 lb were the
        # total load — a nonsense number that then becomes the sort key
        # for the whole Records card.
        if bodyweight or weight_lb is None:
            return None
        return estimate_1rm(weight_lb, reps)
    if kind == "added_load":
        if not bodyweight or weight_lb is None or weight_lb <= 0:
            return None
        return weight_lb
    if kind == "hold":
        if not timed or weight_lb is not None:
            return None
        return float(reps)  # seconds
    if kind == "reps":
        if not bodyweight or weight_lb is not None or timed:
            return None
        return float(reps)
    return None


def classify_pr(
    ex: dict[str, Any],
    prior: Sequence[PriorSet],
    weight_lb: float | None,
    reps: int | None,
) -> str | None:
    """Which kind of personal record this set sets, if any.

    Returns None when it sets none — including for the very first set of
    an exercise, which is a baseline rather than a record.

    Fires at most once per (exercise, kind) per workout: a set only counts
    if nothing *earlier in the same session* had already beaten the old
    best. Without that, a user working up 135 → 145 → 155 gets three
    "personal record!" toasts for one achievement, and the third is the
    only true one.
    """
    if reps is None or reps <= 0 or not pr_eligible(ex):
        return None

    earlier = [p for p in prior if not p.same_workout]
    session = [p for p in prior if p.same_workout]

    for kind in PR_PRECEDENCE:
        metric = _pr_metric(ex, kind, weight_lb, reps)
        if metric is None:
            continue

        prior_vals = [
            m for m in (
                _pr_metric(ex, kind, p.weight_lb, p.reps) for p in earlier
            ) if m is not None
        ]
        if not prior_vals:
            # No history for this kind — a baseline, not a record.
            continue
        best_before = max(prior_vals)
        if metric <= best_before:
            continue

        session_vals = [
            m for m in (
                _pr_metric(ex, kind, p.weight_lb, p.reps) for p in session
            ) if m is not None
        ]
        if session_vals and max(session_vals) > best_before:
            # Already broken earlier in this same workout — the badge has
            # been shown, so this set is an improvement on today, not news.
            continue
        return kind
    return None


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


async def days_since_muscle_trained(
    db: AsyncSession, target_date: date, lookback_days: int = 28,
) -> dict[str, float]:
    """Days since each muscle last took a working set.

    Credits primary and secondary movers alike — a muscle worked only as
    a secondary is still fatigued, and for "is it rested?" the distinction
    doesn't matter the way it does for volume counting.

    Muscles with no qualifying set in the window report `lookback_days`,
    which reads as "maximally rested" to the scorer. That's the intent:
    something untrained for a month should be a strong pick.
    """
    since = target_date - timedelta(days=lookback_days)
    rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id,
            func.max(models.StrengthWorkout.date),
        )
        .join(
            models.StrengthSet,
            models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkout.id == models.StrengthWorkoutExercise.workout_id,
        )
        .where(models.StrengthWorkout.date >= since)
        .where(models.StrengthWorkout.date < target_date)
        .where(models.StrengthWorkout.status.in_(("completed", "in_progress")))
        .where(models.StrengthWorkout.split_focus.notin_(["yoga", "cardio"]))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.set_type != "warmup")
        .group_by(models.StrengthWorkoutExercise.exercise_id)
    )).all()

    last_by_muscle: dict[str, date] = {}
    for ex_id, last_date in rows:
        info = CATALOG_BY_ID.get(ex_id)
        if info is None or last_date is None:
            continue
        touched = [info.get("primary_muscle")] + list(
            info.get("secondary_muscles") or []
        )
        for m in touched:
            if not m:
                continue
            prev = last_by_muscle.get(m)
            if prev is None or last_date > prev:
                last_by_muscle[m] = last_date

    out: dict[str, float] = {}
    for muscle in MUSCLE_VOLUME_TARGETS:
        last = last_by_muscle.get(muscle)
        out[muscle] = (
            float(lookback_days) if last is None
            else float((target_date - last).days)
        )
    return out


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
# MUSCLE_VOLUME_TARGETS moved to analytics/taxonomy.py in TD-1 so the
# landmarks and the vocabulary that feeds them cannot drift apart. It is
# re-exported at the top of this module for existing importers.


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
        .where(models.StrengthSet.set_type != "warmup")  # SETTYPE-1
        .group_by(models.StrengthWorkoutExercise.exercise_id)
    )).all()

    # WP-5 (SCS-9 A): credit primary mover at 1.0× and each catalog-tagged
    # secondary mover at 0.5× — Helms/Wolf "fractional sets" convention.
    # Without this, a back squat with `primary=quadriceps` left glutes/
    # hamstrings/lower-back at 0 despite obvious training stress.
    SECONDARY_WEIGHT = 0.5
    sets_by_muscle: dict[str, float] = {}
    # TD-1 — every token folds through taxonomy.credits_volume rather than
    # being used as a dict key raw. The catalog is already normalised at
    # import, so for bundled exercises this is a no-op; it matters for rows
    # logged against ids that never went through that path, such as the
    # `import_*` slugs the Strong / Hevy CSV importer mints.
    unmatched_ids: list[str] = []
    unmatched_sets = 0
    for ex_id, n_sets in rows:
        info = CATALOG_BY_ID.get(ex_id)
        n = int(n_sets)
        if info is None:
            unmatched_ids.append(ex_id)
            unmatched_sets += n
            continue
        primary = taxonomy.credits_volume(info.get("primary_muscle"))
        if primary:
            sets_by_muscle[primary] = sets_by_muscle.get(primary, 0.0) + n
        for sec in info.get("secondary_muscles") or []:
            canon = taxonomy.credits_volume(sec)
            if canon and canon != primary:
                sets_by_muscle[canon] = sets_by_muscle.get(canon, 0.0) + n * SECONDARY_WEIGHT
    if unmatched_ids:
        # Not silent: an exercise the catalog cannot resolve contributes
        # nothing to the app's flagship strength analytic, and the user has
        # no other way to discover that their imported history is missing.
        log.warning(
            "weekly_muscle_volume: %d set(s) across %d unmatched exercise id(s) "
            "credited no muscle volume: %s",
            unmatched_sets, len(unmatched_ids), ", ".join(sorted(unmatched_ids)[:10]),
        )

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
        .where(models.StrengthSet.set_type != "warmup")  # SETTYPE-1
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


def select_mobility_poses(
    catalog: list[dict],
    seed: str,
    *,
    exercise_prefs: dict[str, str] | None = None,
    recent_frequency: dict[str, int] | None = None,
    count: int = 2,
) -> list[dict]:
    """Pick the poses for the cool-down block appended to a strength day.

    Two fixes over the original inline picker, which was a bare
    `rng.sample` over every mobility entry in the catalog:

    - `exercise_prefs` is honoured. Disabling a pose used to work for
      strength slots (select_exercises_for_split filters on it) but was
      silently ignored here, so a pose the user had explicitly turned off
      kept getting appended to every workout.
    - Rotation pressure, matching the main slots and the finishers:
      least-used-in-the-last-4-weeks wins, with seeded jitter breaking
      ties. Uniform sampling kept landing on the same couple of poses.
    """
    prefs = exercise_prefs or {}
    freq = recent_frequency or {}
    pool = [
        e for e in catalog
        if e.get("movement_pattern") == "mobility"
        and "bodyweight" in (e.get("equipment") or [])
        and prefs.get(e["id"]) != "disabled"
    ]
    if not pool:
        return []
    rng = random.Random(seed + "::mobility")
    jitter = {e["id"]: rng.random() for e in pool}
    ranked = sorted(pool, key=lambda e: (freq.get(e["id"], 0), jitter[e["id"]]))
    return ranked[:min(count, len(ranked))]


async def read_recent_sessions(
    db: AsyncSession, exercise_id: str, limit: int = 8,
) -> list[SessionRead]:
    """The last `limit` completed sessions of one exercise, newest first.

    The query half of OG2-B1; `read_session` is the judgement half and has no
    database in it.

    Two changes from the single-session lookup this replaces. It reads more
    than one session, without which a stall cannot be seen at all. And it
    keeps only sessions that actually carry qualifying sets — the old version
    took the newest completed slot whatever it held, so a single DECLINED
    slot (SKIP-1) in the most recent session made the reducer report no
    history and fall through to `starting_weight_lb`, a table indexed by
    declared experience level. That is the same shape as the OG2-A2 defect:
    real history discarded in favour of a beginner's default.
    """
    rows = (await db.execute(
        select(models.StrengthWorkoutExercise, models.StrengthWorkout.completed_at)
        .join(
            models.StrengthWorkout,
            models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id,
        )
        .where(models.StrengthWorkoutExercise.exercise_id == exercise_id)
        .where(models.StrengthWorkout.status == "completed")
        .order_by(models.StrengthWorkout.completed_at.desc())
        .limit(max(1, limit) * 3)
    )).all()
    if not rows:
        return []

    wex_by_id = {r[0].id: r[0] for r in rows}
    sets_by_wex: dict[int, list[models.StrengthSet]] = {}
    if wex_by_id:
        for s in (await db.execute(
            select(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(list(wex_by_id)))
        )).scalars().all():
            sets_by_wex.setdefault(s.workout_exercise_id, []).append(s)

    out: list[SessionRead] = []
    for wex, _completed_at in rows:
        read = read_session(
            target_sets=wex.target_sets,
            slot_declined=bool(wex.skipped),
            sets=[
                SetFacts(
                    skipped=bool(s.skipped),
                    actual_reps=s.actual_reps,
                    set_type=s.set_type,
                    actual_weight_lb=s.actual_weight_lb,
                    rating=s.rating,
                )
                for s in sets_by_wex.get(wex.id, [])
            ],
        )
        # A slot with nothing logged is not a session. Including it would
        # make every declined or forgotten slot read as a stall.
        if read.has_history:
            out.append(read)
        if len(out) >= limit:
            break
    return out


async def last_target_weight_for_exercise(
    db: AsyncSession, exercise_id: str
) -> tuple[float | None, float | None, float | None, bool]:
    """The most recent real session of an exercise, as
    (avg_rating, avg_weight_lb, avg_reps, enough).

    Used to compute the next prescription: crush 25 lb x 8 last session and
    this session should prescribe ~30 lb.

    `enough` is the OG2-B1 addition and it gates the ADVANCE only — see
    `weight_from_history`. Filters `PROGRESSION_EXCLUDED_SET_TYPES`
    (OG2-A1); reachable through the web set-type picker and through imported
    Strong/Hevy history.
    """
    sessions = await read_recent_sessions(db, exercise_id, limit=1)
    if not sessions:
        return None, None, None, True
    s = sessions[0]
    return s.avg_rating, s.avg_weight_lb, s.avg_reps, s.enough


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
    force_full_weight: bool = False,
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
    # WP-17 — target working-exercise count. None = auto (split template
    # size + up to 2 adaptive finishers). When set, clamp to a sane band.
    _epw = training.get("exercises_per_workout")
    target_exercises = (
        max(3, min(9, int(_epw))) if _epw not in (None, 0) else None
    )

    # PROG-1 — opt-in program mode. When enabled, the chosen core lifts
    # follow a fixed linear-progression scheme (see prescribe_program_lift)
    # instead of the recovery/rating oracle. `program_lifts` is empty when
    # disabled, so every hook below is a no-op and the default generator
    # runs byte-for-byte unchanged.
    _program = (training.get("program") or {}) if isinstance(training, dict) else {}
    program_lifts: dict[str, dict] = {}
    if _program.get("enabled"):
        for _pl in _program.get("lifts") or []:
            if isinstance(_pl, dict) and _pl.get("exercise_id"):
                program_lifts[_pl["exercise_id"]] = _pl

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
    #
    # ADAPT-1: under adaptive the carry-over must NOT pin the focus. Its
    # rationale is "don't lose the rotation slot", and adaptive has no slot
    # to lose — it re-decides from volume every day. Pinning here would
    # re-serve the very session the user skipped, which is the exact
    # behaviour adaptive exists to remove, just arriving through a second
    # door. What we DO keep is the useful half: bypass the cardio/yoga
    # day-type dispatch so a missed session still becomes a strength day.
    carryover_note: str | None = None
    carry_bypass_day_type = False
    if not override_split:
        carry = await missed_strength_carryover(db, target_date)
        if carry is not None:
            if split_pref == "adaptive":
                carry_bypass_day_type = True
                carryover_note = (
                    f"You missed {carry[1].isoformat()}'s {carry[0]} session, "
                    "so today is a strength day rather than rest/cardio/yoga "
                    "— focus chosen by need, not by what was missed."
                )
            else:
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
    if not override_split and not carry_bypass_day_type:
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
    # ADAPT-1 — need-based selection. Opt-in via split_preference="adaptive";
    # every other value keeps the completion-advanced rotation untouched.
    adaptive_note: str | None = None
    if override_split:
        focus = override_split
    elif split_pref == "adaptive":
        vol = await weekly_muscle_volume(db, days=7)
        rested = await days_since_muscle_trained(db, target_date)
        focus, _scores = select_split_adaptive(
            days_per_week, split_pref, vol, rested, last_split,
        )
        # Name the muscles that drove the pick, so the choice is legible
        # rather than the plan silently changing shape day to day.
        drivers = sorted(
            (
                (m, vol.get(m, {}).get("sets", 0), rested.get(m, 0.0))
                for m in muscles_for_focus(focus)
                if vol.get(m, {}).get("status") in ("under", "untrained", "in_range")
            ),
            key=lambda t: (t[1], -t[2]),
        )[:3]
        if drivers:
            adaptive_note = (
                "Adaptive split picked "
                + focus.replace("_", " ")
                + " — most-needed: "
                + ", ".join(
                    f"{m.replace('_', ' ')} ({int(s)} sets, {int(d)}d rest)"
                    for m, s, d in drivers
                )
                + "."
            )
    else:
        focus = select_split(days_per_week, split_pref, last_split)

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

    # PROG-1 Hook A — pin program lifts into today's plan. For each
    # enabled program lift that is equipment-available AND shares a
    # movement pattern with a slot the generator already picked,
    # substitute it into that slot (same index → same role + superset
    # shape, which pair_supersets recomputes just below). A program lift
    # whose pattern isn't trained today simply doesn't appear; it
    # surfaces on its natural day. Off by default → this block is skipped.
    if program_lifts:
        avail_ids = {e["id"] for e in catalog}
        already = {c["id"] for c in chosen}
        for prog_id, pstate in program_lifts.items():
            pex = CATALOG_BY_ID.get(prog_id)
            if pex is None or prog_id not in avail_ids or prog_id in already:
                continue  # unknown, equipment-filtered, or already chosen
            pat = pex.get("movement_pattern")
            for idx, c in enumerate(chosen):
                if c.get("movement_pattern") == pat and c["id"] not in program_lifts:
                    chosen[idx] = pex
                    already.add(prog_id)
                    break
        # NB: substitution is IN PLACE (same index) so chosen_slots stays
        # aligned and the positional slot_role of the surrounding non-
        # program exercises is preserved. Pinned lifts are protected from
        # the WP-17 trim below by a program-aware trim, NOT by reordering
        # (an earlier "front the pinned lifts" reorder demoted real
        # compounds to isolation slot_roles — reverted).

    if adaptive_note:
        notes.append(adaptive_note)
    if freq_advisory_note:
        notes.append(freq_advisory_note)
    if carryover_note:
        notes.append(carryover_note)
    auto_avoid_count = sum(
        1 for r in recent_ratings.values()
        if r is not None and r <= AUTO_AVOID_THRESHOLD
    )
    if auto_avoid_count:
        notes.append(
            f"{auto_avoid_count} exercise(s) auto-avoided — you kept failing "
            f"them over the last 14 days. Override by marking them "
            f"'favorite' in the catalog if you want them back."
        )

    superset_map = pair_supersets(chosen, chosen_slots)

    # Compute target weights for each exercise, applying history + deload.
    # `recovery_deload` is the automatic recovery/readiness factor we surface
    # to the user (WorkoutOut.deload_factor) and that force_full_weight
    # overrides. Difficulty is a separate, user-chosen knob layered on top for
    # the weight math only (not something to "confirm").
    recovery_deload = (
        recovery.deload_factor() if (recovery and not force_full_weight) else 1.0
    )
    deload = recovery_deload
    # Ad-hoc difficulty knob: easy -10% on top of deload, hard +5%.
    if difficulty == "easy":
        deload *= 0.90
    elif difficulty == "hard":
        deload *= 1.05
    if recovery_deload < 1.0:
        notes.append(
            f"Targets eased ~{round((1 - recovery_deload) * 100)}% for today's "
            f"recovery / readiness. Tap “Use full weight” to override, "
            f"or turn recovery-aware off in Settings."
        )
    if difficulty and difficulty != "normal":
        notes.append(f"Ad-hoc session — difficulty: {difficulty}.")
    # WP-17 — target working-exercise count. The ad-hoc custom-workout
    # path passes duration_minutes (≈8 min/exercise); the daily path uses
    # the user's exercises_per_workout preference. Trim here when over the
    # target; the accessory filler below tops up when under.
    target_count: int | None = None
    if duration_minutes is not None:
        target_count = max(3, min(10, duration_minutes // 8))
    elif target_exercises is not None:
        target_count = target_exercises
    if target_count is not None and len(chosen) > target_count:
        if program_lifts:
            # PROG-1: never trim away a pinned program lift, wherever it
            # sits. Keep ALL program lifts + fill the remaining budget with
            # non-program exercises in their ORIGINAL order (no reorder →
            # positional slot_role stays correct for the survivors). When
            # program lifts alone exceed target_count, keep them all.
            keep_nonprog = target_count - sum(
                1 for c in chosen if c["id"] in program_lifts)
            new_chosen: list[dict[str, Any]] = []
            new_slots: list = []
            np_kept = 0
            for c, s in zip(chosen, chosen_slots):
                if c["id"] in program_lifts:
                    new_chosen.append(c); new_slots.append(s)
                elif np_kept < keep_nonprog:
                    new_chosen.append(c); new_slots.append(s); np_kept += 1
            chosen, chosen_slots = new_chosen, new_slots
        else:
            chosen = chosen[:target_count]
            chosen_slots = chosen_slots[:target_count]
        notes.append(
            f"Trimmed to {target_count} exercises per your preference."
        )

    plan_exs: list[ExerciseInPlan] = []
    pairs_lb = (equipment.get("dumbbells") or {}).get("pairs_lb") or []
    wrist = equipment.get("wrist_weights_lb") or []
    # (exercise name, advisory) — the advisory text now differs per
    # case (coarse forced jump vs genuinely the top of the rack), so
    # carry it through instead of collapsing to one generic sentence.
    dp_advisories: list[tuple[str, str]] = []

    for i, ex in enumerate(chosen):
        # PROG-1 Hook B — program lift: fixed scheme, bypass the
        # recovery/rating/history oracle AND the recovery deload (weight
        # is scheme-owned and advances only on completion). FAST-18
        # fasted volume modulation and slot-role logic below are skipped
        # too — the program dictates sets/reps/rest deterministically.
        pstate = program_lifts.get(ex["id"])
        if pstate is not None:
            pp = prescribe_program_lift(pstate, pairs_lb, wrist)
            plan_exs.append(ExerciseInPlan(
                exercise_id=ex["id"],
                order_index=i,
                superset_id=superset_map.get(ex["id"]),
                target_sets=pp["sets"],
                target_reps_low=pp["reps_lo"],
                target_reps_high=pp["reps_hi"],
                target_weight_lb=pp["weight_lb"],
                target_rest_s=(
                    DEFAULT_REST_S_SUPERSET_AFTER
                    if ex["id"] in superset_map else pp["rest_s"]
                ),
            ))
            continue
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
        avg_rating, avg_weight, avg_reps, enough = await last_target_weight_for_exercise(
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
                deload=deload, session_complete=enough,
            )
            if advisory:
                dp_advisories.append((ex["name"], advisory))
        else:
            # Weight-only policy: non-dumbbell but rated (a timed hold
            # carrying a load), and the unrated case that used to fall
            # through to the starting table with a known weight in scope.
            # reps/seconds are handled elsewhere.
            target, _why = weight_from_history(
                avg_weight, avg_rating, ex["is_compound"], goal=goal,
                enough=enough,
            )
            if target is None:
                target = starting_weight_lb(ex["movement_pattern"], level)
            if target is not None:
                target = deload_round(target, deload, pairs_lb, wrist)

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

    for _name, _adv in dp_advisories[:3]:
        notes.append(f"{_name} — {_adv}")

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
        # WP-17 — how many accessory slots to add, and how strict to be.
        # Auto (no target): up to 2 finishers, only for real gaps (≥3).
        # Target set: top up to exactly the requested count, relaxing the
        # gap floor to 1 and, if still short, padding with core (favored).
        if target_count is not None:
            max_accessory = max(0, min(target_count - len(chosen), 9 - len(chosen)))
            gap_floor = 1
        else:
            max_accessory = 2
            gap_floor = 3

        gaps: list[tuple[float, float, str]] = []
        for muscle, payload in current_volume.items():
            mev = payload["mev"]
            sets_now = projected.get(muscle, 0)
            gap = mev - sets_now
            if gap >= gap_floor and muscle in FINISHER_PATTERNS:
                # Core is the preferred filler — nudge abdominals up so
                # close gaps default to core (WP-17 user choice).
                rank = gap + (1.5 if muscle == "abdominals" else 0.0)
                gaps.append((rank, gap, muscle))
        gaps.sort(reverse=True)  # widest (core-weighted) gap first
        fill_order = [m for _r, _g, m in gaps]
        # Target-driven and still short on under-MEV muscles? Pad with core
        # so the slider always delivers real, sensible volume.
        if target_count is not None:
            while len(fill_order) < max_accessory:
                fill_order.append("abdominals")

        finishers_added: list[str] = []
        already_chosen_ids = {e["id"] for e in chosen}
        # WP-18 — track movement families already in the plan so a finisher
        # can't add a near-duplicate (the classic bug: pull slot substitutes
        # Straight-Arm Pullover, then the lats finisher adds Bent-Arm Pullover
        # — two pullovers in one day). Family-block only the finisher; the
        # regular slots' twin-isolation design (e.g. two biceps slots) stays.
        chosen_families = {_name_family(e.get("name", e["id"])) for e in chosen}
        finisher_seed_rng = random.Random(seed + "::finishers")
        for muscle in fill_order:
            if len(finishers_added) >= max_accessory:
                break
            pattern = FINISHER_PATTERNS[muscle]
            candidates = _exercises_for_pattern(catalog, pattern, level, [muscle])
            candidates = [
                c for c in candidates
                if c["id"] not in already_chosen_ids
                and _name_family(c["name"]) not in chosen_families
            ]
            if not candidates:
                continue
            # Rotation pressure (low 4-week frequency wins) + WP-18 seeded
            # jitter so equally-fresh finishers don't always resolve to the
            # same alphabetical pick — same fix as the main slots.
            fin_jitter = {c["id"]: finisher_seed_rng.random() for c in candidates}
            candidates = sorted(
                candidates,
                key=lambda e: (recent_frequency.get(e["id"], 0), fin_jitter[e["id"]]),
            )
            pick = finisher_seed_rng.choice(candidates[:min(3, len(candidates))])
            already_chosen_ids.add(pick["id"])
            chosen_families.add(_name_family(pick["name"]))
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
            # Dedupe for the note — target padding can repeat a muscle
            # (e.g. two core slots) but we only want to name it once.
            muscles_named = list(dict.fromkeys(finishers_added))
            n = len(finishers_added)
            if target_count is not None:
                notes.append(
                    f"+{n} accessory slot{'s' if n > 1 else ''} added to hit "
                    f"your {target_count}-exercise target: "
                    f"{', '.join(muscles_named)}."
                )
            else:
                notes.append(
                    f"+{n} finisher slot{'s' if n > 1 else ''} added "
                    f"to chip away at weekly volume gap: {', '.join(muscles_named)}."
                )

    # Mobility / yoga block — append 2 poses tagged movement_pattern=mobility
    # to the end of the plan when the user has opted in. Reps are interpreted
    # as seconds-to-hold by the UI; sets=1, weight=null, rest=15.
    if include_mobility:
        mobility_history = await recent_mobility_history(db)
        picks = select_mobility_poses(
            CATALOG, seed,
            exercise_prefs=exercise_prefs,
            recent_frequency=recent_frequency,
        )
        if picks:
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
            # Count from the actual picks — disabling poses can shrink the
            # pool below the requested two.
            notes.append(
                f"Mobility block appended — {len(picks)} yoga "
                f"pose{'s' if len(picks) != 1 else ''}, ~30 s hold each."
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
        deload_factor=recovery_deload,
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
        deload_factor=plan.deload_factor,
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
