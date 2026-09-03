"""One place chooses the weight, and it says why — OG2-B2 and OG2-B3.

**B2.** The branch that picks a weight lived at three call sites.
`generate_plan` chose between `double_progression` and `weight_from_history`
and then fell through to `starting_weight_lb`; `add_exercise` and
`swap_exercise` each carried a reduced copy. The copies had already drifted
twice — one never read `goal` at all, and after that was fixed the two still
defaulted it differently from the generator — and a comment at the ad-hoc
site read "Same weight chain as swap_exercise — one prescription policy"
while there were three. `next_prescription` is now the one entry point, and
it is pure, so the decision is testable without a database.

**B3.** A target now carries its own reason, and that reason is the one the
prescription actually produced.

`explain_workout` used to re-derive an explanation from a DIFFERENT query:
the heaviest set of any prior session, filtered only on `actual_weight_lb IS
NOT NULL` — no status, no skipped, no set_type, no reps predicate. So it
could cite a session the reducer never looked at and compare against a set
the weight was not computed from. Its fixed preamble was wrong independently:
it described "RPE ≤ 7" thresholds, but this app rates sets 1-5 where 5 is
Easy, so the copy named a scale the user has never seen.

The reason is stored on the slot's own `notes` column — which existed and was
NULL on all 1,430 rows — so it travels with the exercise it is about rather
than being flattened into the workout-level blob, where it was prefixed with
the exercise name and lost its subject. That also fixes a parity gap: the
workout-level notes render inline on web but only when `exercises.isEmpty()`
on the phone, so on a normal strength day everything the generator said about
why the numbers moved was web-only.

openGym states the reason for having one at all, in its progression engine's
header: "a suggestion you can't audit is one you stop trusting". The second
benefit is structural — every branch must be able to say what it did, which
stops a branch existing that nobody can explain.
"""

from __future__ import annotations

import inspect
import pathlib

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import next_prescription
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)

DUMBBELL = {
    "id": "Dumbbell_Bench_Press", "name": "Dumbbell Bench Press",
    "equipment": ["dumbbell", "bench"], "is_compound": True,
    "movement_pattern": "horizontal_push",
}
BODYWEIGHT = {
    "id": "Pullups", "name": "Pull-Ups", "equipment": ["bodyweight"],
    "is_compound": True, "movement_pattern": "vertical_pull",
}
RACK = dict(pairs_lb=[10, 15, 20, 25, 30, 35, 40], wrist_weights_lb=[])


def _rx(**kw):
    base = dict(
        exercise=DUMBBELL, reps_lo=8, reps_hi=12, level="intermediate",
        goal="hypertrophy", avg_rating=None, avg_weight_lb=None,
        avg_reps=None, enough=True, **RACK,
    )
    base.update(kw)
    return next_prescription(**base)


class TestOneEntryPoint:
    def test_the_generator_uses_it(self):
        assert "next_prescription" in inspect.getsource(algo.generate_plan)

    def test_both_api_sites_use_it(self):
        for fn in (api.add_exercise, api.swap_exercise):
            assert "next_prescription" in inspect.getsource(fn)

    def test_no_site_reaches_past_it(self):
        """A caller naming the inner helpers has rebuilt the branch.

        That is how the three copies came to disagree in the first place, so
        the check is on the entry point rather than on the outcome.
        """
        for fn in (api.add_exercise, api.swap_exercise):
            src = inspect.getsource(fn)
            assert "double_progression" not in src
            assert "weight_from_history" not in src

    def test_it_is_pure(self):
        """No database, so every branch is testable — the house style of
        analytics/targets.py and analytics/projection.py."""
        sig = inspect.signature(next_prescription)
        assert "db" not in sig.parameters
        assert not inspect.iscoroutinefunction(next_prescription)


class TestEveryBranchCanExplainItself:
    def test_no_history_says_it_is_a_starting_weight(self):
        rx = _rx()
        assert rx.reason == "no_history"
        assert "Starting weight" in rx.why
        # It no longer repeats the exercise NAME. That is the card's own
        # title two lines above the reason, so printing it again spent a
        # third of the sentence saying what the user was already looking at.
        assert DUMBBELL["name"] not in rx.why

    def test_an_advance_names_what_it_came_from(self):
        rx = _rx(avg_rating=5.0, avg_weight_lb=25.0, avg_reps=12.0)
        assert rx.reason == "advanced"
        assert "25" in rx.why

    def test_a_deload_says_the_session_failed(self):
        rx = _rx(avg_rating=1.0, avg_weight_lb=25.0, avg_reps=8.0)
        assert rx.reason == "deloaded"
        assert "failed" in rx.why.lower()

    def test_a_short_session_says_so(self):
        """The OG2-B1 gate, now visible to the user rather than silent."""
        rx = _rx(avg_rating=5.0, avg_weight_lb=25.0, avg_reps=12.0, enough=False)
        assert rx.reason == "held_incomplete"
        assert "short" in rx.why
        assert "25" in rx.why

    def test_an_unrated_session_says_so(self):
        """OG2-A2's case. It holds, and now it says why it held."""
        rx = _rx(exercise={**DUMBBELL, "equipment": ["barbell"]},
                 avg_rating=None, avg_weight_lb=25.0)
        assert rx.reason == "held_unrated"
        assert "unrated" in rx.why
        assert "25" in rx.why

    def test_the_rep_ladder_says_what_it_is_waiting_for(self):
        """Mid-range: the weight holds while the reps climb. Without a
        reason this reads as nothing having happened."""
        rx = _rx(avg_rating=4.0, avg_weight_lb=25.0, avg_reps=9.0)
        assert rx.reason == "rep_ladder"
        # The rep target it is waiting for, and the weight it is holding.
        assert "reps" in rx.why
        assert "25" in rx.why

    def test_every_branch_returns_a_non_empty_why(self):
        """The structural benefit: a branch that cannot say what it did
        should not exist."""
        cases = [
            {},
            dict(avg_rating=5.0, avg_weight_lb=25.0, avg_reps=12.0),
            dict(avg_rating=1.0, avg_weight_lb=25.0, avg_reps=8.0),
            dict(avg_rating=4.0, avg_weight_lb=25.0, avg_reps=9.0),
            dict(avg_rating=5.0, avg_weight_lb=25.0, avg_reps=12.0, enough=False),
            dict(avg_rating=None, avg_weight_lb=25.0),
        ]
        for kw in cases:
            assert _rx(**kw).why.strip()


class TestTheReasonTravelsWithTheExercise:
    def test_the_plan_carries_it(self):
        assert "why" in algo.ExerciseInPlan.__dataclass_fields__

    def test_it_is_persisted_on_the_slot(self):
        """Onto the slot's own column, not the workout-level notes blob.

        The blob prefixed the reason with the exercise name and lost its
        subject, and it renders on web only — the phone shows it just when
        `exercises.isEmpty()`, the cardio-day card.
        """
        assert "notes=ex.why" in inspect.getsource(algo.persist_plan)

    def test_a_bodyweight_lift_carries_no_weight_reason(self):
        """The weight is nulled for a lift that carries no load, so a reason
        describing a load would be describing something that is not there."""
        src = inspect.getsource(algo.generate_plan)
        assert "why_target = None" in src

    def test_a_swap_replaces_the_reason(self):
        """It belongs to the exercise now in the slot, not the one removed."""
        assert "wex.notes = why_target" in inspect.getsource(api.swap_exercise)


class TestTheExplanationIsTheOneThatWasComputed:
    def test_it_reads_the_stored_reason(self):
        src = inspect.getsource(api.explain_workout)
        assert "ex.notes" in src

    def test_it_no_longer_re_derives_from_a_different_query(self):
        """The heaviest set of any prior session, filtered only on a non-null
        weight — no status, skipped, set_type or reps predicate. It could
        cite a session the reducer never looked at."""
        src = inspect.getsource(api.explain_workout)
        assert "last_top_set" not in src
        assert "actual_weight_lb.is_not(None)" not in src

    def test_the_stale_rpe_copy_is_gone(self):
        """It described "RPE ≤ 7" thresholds. This app rates sets 1-5 where 5
        is Easy, so the sentence named a scale the user has never seen."""
        # Code only — the comment names the removed copy while explaining
        # why it went, which is the point of it being there.
        src = inspect.getsource(api.explain_workout)
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert "RPE" not in code

    def test_it_says_nothing_rather_than_inventing_a_reason(self):
        src = inspect.getsource(api.explain_workout)
        assert "enough history yet" in src


class TestBothSurfacesShowIt:
    def test_the_web_renders_the_slot_reason(self):
        assert "why-target" in WEB.read_text()

    def test_the_phone_renders_the_slot_reason(self):
        src = PHONE.read_text()
        assert "wex.notes?.takeIf" in src

    def test_neither_derives_it(self):
        """Server decides the sentence; clients render it verbatim. Same rule
        as GOAL-STATE's `state_tone`."""
        for path in (WEB, PHONE):
            src = path.read_text()
            assert "Up from" not in src
            assert "starting weight for" not in src
