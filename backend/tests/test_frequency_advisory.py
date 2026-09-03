"""The cadence advisory was switched off for the user it describes — OG2-D-2.

#WP-8 exists to say one thing: "your setting is N sessions a week, you are
completing M". On this database it has never once been able to say it, and
neither reason was a tuning question.

**Gate one excluded `adaptive`.** The condition was `split_pref == "auto"`,
and the live preference is `"adaptive"`. ADAPT-1 chooses which focus to run,
not how many days are scheduled — `days_per_week` still drives
`_STRENGTH_WEEKDAYS_BY_COUNT` and still selects the candidate family — so the
declared-versus-actual mismatch under adaptive is the identical mismatch. An
EXPLICIT family stays excluded, and that is a different case rather than an
oversight: there the user named a split, and suggesting another one argues
with a decision instead of reporting a fact.

**Gate two was `actual_14d >= 4`.** An advisory whose whole job is to flag a
gap between declared and actual cadence was disabled whenever actual cadence
was LOW — which is the direction that most needs saying, since someone
declaring 6 and completing 2 is precisely who it is for. A floor is still
right: 0 or 1 sessions cannot distinguish "this is my cadence" from a
fortnight away. It belongs just above that, not above the middle of the
user's own distribution. Measured over 105 days of history, trailing-14-day
completed strength sessions land on 2 (11 days), 3 (44), 4 (18), 5 (22) and 6
(10), so the old floor sat above the mode and silenced the note on 55 of 105
days — all of them days when the gap was at its widest. This is HEALTH-1's
rule applied in the direction it is usually not: a threshold can be wrong by
never firing as easily as by always firing.

A 28-day window was measured as an alternative basis for the suggestion and
rejected: the two windows agree on 62 of 77 days and disagree by ±1 on the
rest, which does not justify a second constant.

**The copy only ever handled one direction.** The caller's comment described
both ("declared 4 but actually does 2/wk, or declared 2 but actually does
5/wk") while the sentence said "Consider bumping" unconditionally. For this
user the suggestion is to schedule FEWER days, and getting the verb backwards
on the one sentence meant to explain the schedule undoes the explaining.

It is extracted to a pure function so the thresholds and the copy are
testable without a database, the house style of `next_prescription` and
`analytics/targets.py`.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    FREQ_ADVISORY_MIN_SESSIONS,
    frequency_advisory,
)


class TestItSpeaksWhenDeclaredAndActualDiverge:
    def test_the_live_case_produces_a_note(self):
        """2 completed strength sessions in 14 days against a declared 6 —
        the reading on 2026-09-02, which both old gates silenced."""
        note = frequency_advisory(actual_14d=2, days_per_week=6, focus="pull")
        assert note is not None
        assert "2 strength sessions" in note
        assert "6/week" in note

    def test_it_reports_the_evidence_it_judged_on(self):
        """The user has to be able to tell whether the fortnight was typical,
        so the count and the rate are in the sentence, not just the verdict."""
        note = frequency_advisory(actual_14d=5, days_per_week=6, focus="ppl")
        assert "5 strength sessions" in note
        assert "2.5/week" in note

    def test_a_half_session_tie_rounds_down(self):
        """Python's round() is banker's, so 2.5/week suggests 2 rather than
        3. That is the right way for this advisory to break a tie: the
        symptom it exists to explain is days the schedule generates and the
        user does not train, and rounding up would add one back."""
        note = frequency_advisory(actual_14d=5, days_per_week=6, focus="ppl")
        assert "days_per_week to 2" in note

    def test_a_declared_figure_close_to_actual_says_nothing(self):
        assert frequency_advisory(
            actual_14d=6, days_per_week=3, focus="ppl") is None

    def test_it_names_the_split_the_suggestion_implies(self):
        note = frequency_advisory(actual_14d=10, days_per_week=2, focus="full_body")
        assert "ppl" in note


class TestTheDirectionIsRead:
    def test_scheduling_fewer_days_is_not_called_bumping(self):
        note = frequency_advisory(actual_14d=2, days_per_week=6, focus="pull")
        assert "dropping days_per_week to 1" in note
        assert "bumping" not in note

    def test_scheduling_more_days_still_is(self):
        note = frequency_advisory(actual_14d=10, days_per_week=2, focus="full_body")
        assert "bumping days_per_week to 5" in note
        assert "dropping" not in note

    def test_only_the_over_declared_case_names_the_skipped_pile_up(self):
        """The consequence is real in one direction only. Declaring FEWER
        days than you train does not generate days you never trained, so
        claiming it would be describing something that cannot happen."""
        over = frequency_advisory(actual_14d=2, days_per_week=6, focus="pull")
        under = frequency_advisory(actual_14d=10, days_per_week=2, focus="full_body")
        assert "skipped sessions" in over
        assert "skipped sessions" not in under


class TestTheFloor:
    def test_it_is_two_not_four(self):
        """Four sat above the mode of the user's own distribution — the note
        went quiet exactly where the gap was widest."""
        assert FREQ_ADVISORY_MIN_SESSIONS == 2

    def test_a_single_session_is_not_a_cadence(self):
        """One session in a fortnight cannot be told apart from a fortnight
        away, and "set it to 1/week" off that would be a guess."""
        assert frequency_advisory(
            actual_14d=1, days_per_week=6, focus="pull") is None
        assert frequency_advisory(
            actual_14d=0, days_per_week=6, focus="pull") is None

    def test_the_floor_no_longer_hides_the_middle_of_the_distribution(self):
        """3 sessions per 14 days is this user's modal reading, on 44 of 105
        measured days, and the old floor silenced every one of them."""
        assert frequency_advisory(
            actual_14d=3, days_per_week=6, focus="legs") is not None


class TestWhichPreferencesAsk:
    def test_adaptive_is_included(self):
        """The live value, and the reason gate one never fired. Adaptive
        changes which focus is chosen, not how many days are scheduled."""
        src = inspect.getsource(algo.generate_plan)
        assert 'split_pref in ("auto", "adaptive")' in src

    def test_an_explicit_family_is_still_excluded(self):
        """Not an oversight — there the user named a split, and suggesting a
        different one argues with a decision rather than reporting a fact."""
        src = inspect.getsource(algo.generate_plan)
        assert '"ppl"' not in src[src.index("#WP-8"):src.index("#WP-8") + 1800]

    def test_an_override_still_suppresses_it(self):
        src = inspect.getsource(algo.generate_plan)
        assert "not override_split" in src[src.index("#WP-8"):]


class TestItIsPure:
    def test_no_database(self):
        sig = inspect.signature(frequency_advisory)
        assert "db" not in sig.parameters
        assert not inspect.iscoroutinefunction(frequency_advisory)

    def test_the_caller_does_not_rebuild_the_sentence(self):
        """One copy, so the thresholds and the wording cannot drift apart —
        which is how the verb came to disagree with its own comment."""
        src = inspect.getsource(algo.generate_plan)
        assert "You've completed" not in src
