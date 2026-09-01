"""The rest timer stops when the session does — OG2-A7.

Both surfaces guarded a rest on `if (!skipped)` alone, so finishing a workout
started a countdown while the user racked the weights. There is exactly one
set with nothing left to time — the last set of the SESSION — and neither
client knew about it.

openGym found the same thing from the other direction and its changelog
records the rule: a rest belongs after every completed set, the last set of
an *exercise* included, because another exercise follows and you rest before
that one too. Its bug was the mirror image of this one — it finished
exercises quietly, so a two-set exercise timed one rest instead of two.

Two other faults travelled with it.

**The 35-second within-round superset rest was hard-coded twice**, in Vue and
again in Kotlin, so the two surfaces could disagree about how long a rest was
and a change had to be made in two places.

**The web decremented a counter once per tick.** That is only correct if
every tick fires, and a background tab is throttled to roughly one a minute,
so leaving the page and returning showed a rest far longer than the one
actually taken. The phone has anchored to a wall-clock deadline since it was
written, which is the same divergence again: two clients, two answers, one
number.

The decision is now made once, server-side, at the moment the set is written
— which is the only place that can see the whole session without a client
re-deriving state the server already holds.
"""

from __future__ import annotations

import inspect
import pathlib

from myvitals.analytics.strength import (
    DEFAULT_REST_S_SUPERSET_WITHIN,
    rest_after_set,
)
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)


class TestTheLastSetOfTheSession:
    def test_it_earns_no_rest(self):
        """The reported bug. Nothing follows, so there is nothing to time."""
        assert rest_after_set(
            is_last_set_of_session=True,
            superset_partner_owes_this_round=False,
            target_rest_s=90,
        ) == 0

    def test_the_session_being_over_beats_a_superset_mid_round(self):
        """Ordering matters, and this is the case that gets it wrong.

        If the final set of the day happens to be one half of a superset,
        asking about the partner first would return a 35-second rest for a
        workout that has ended.
        """
        assert rest_after_set(
            is_last_set_of_session=True,
            superset_partner_owes_this_round=True,
            target_rest_s=90,
        ) == 0

    def test_every_other_set_still_rests(self):
        """Including the last set of an EXERCISE.

        Another exercise follows and you rest before it too — openGym's bug
        was exactly this one inverted, and a two-set exercise timed one rest
        instead of two.
        """
        assert rest_after_set(
            is_last_set_of_session=False,
            superset_partner_owes_this_round=False,
            target_rest_s=90,
        ) == 90


class TestTheSupersetRound:
    def test_a_partner_still_owing_gets_the_short_rest(self):
        assert rest_after_set(
            is_last_set_of_session=False,
            superset_partner_owes_this_round=True,
            target_rest_s=180,
        ) == DEFAULT_REST_S_SUPERSET_WITHIN

    def test_a_completed_round_gets_the_full_rest(self):
        assert rest_after_set(
            is_last_set_of_session=False,
            superset_partner_owes_this_round=False,
            target_rest_s=180,
        ) == 180

    def test_the_within_round_value_is_the_shared_constant(self):
        """It was the literal 35, in Vue and in Kotlin.

        Two copies of a number that decides how long you stand still is how
        the two surfaces came to disagree about a rest.
        """
        assert DEFAULT_REST_S_SUPERSET_WITHIN == 35
        # Code only — the docstring names the literal while explaining what
        # was removed, which is the point of it being there.
        src = inspect.getsource(rest_after_set)
        code = src[src.rindex('"""') + 3:]
        assert "35" not in code, "the constant should be referenced, not inlined"


class TestOutstandingWorkIsCountedFromThePrescription:
    def test_it_counts_target_sets_not_rows_present(self):
        """Set rows are created lazily on log.

        So "no row" and "not done" are the same state, and only `target_sets`
        knows how many there should be. Counting rows would call every set
        the last one.
        """
        src = inspect.getsource(api._rest_after_s)
        assert "x.target_sets" in src

    def test_a_declined_slot_owes_nothing(self):
        """SKIP-1: a slot the user declined is accounted for, not pending.

        Without this the session could never register as finished, and the
        timer would run after the genuine last set of a workout whose tail
        was skipped.
        """
        src = inspect.getsource(api._rest_after_s)
        assert "x.skipped" in src

    def test_a_skipped_set_starts_no_rest(self):
        src = inspect.getsource(api._rest_after_s)
        assert "if s.skipped:" in src


class TestNeitherClientDecidesAnyMore:
    def test_the_web_reads_the_server_field(self):
        src = WEB.read_text()
        assert "res.rest_after_s" in src
        assert "rest = partnerDone ? wex.target_rest_s : 35" not in src

    def test_the_phone_reads_the_server_field(self):
        src = PHONE.read_text()
        assert "restAfterS" in src
        assert "35_000L" not in src, "the phone's hard-coded 35s is back"

    def test_zero_means_do_not_rest_on_both(self):
        """Zero rather than null, because the phone models this as a
        non-nullable Int and Moshi throws on a null for one."""
        assert "> 0" in WEB.read_text()
        assert "restMs > 0L" in PHONE.read_text()

        models = (
            REPO / "android" / "app" / "src" / "main" / "kotlin" / "app"
            / "myvitals" / "sync" / "Models.kt"
        ).read_text()
        assert "val restAfterS: Int = 0" in models


class TestTheWebCountdownIsAnchored:
    def test_it_uses_a_deadline_not_a_decrement(self):
        """A tick counter is right only if every tick fires.

        A background tab is throttled to roughly one a minute, so the number
        came back wrong from any excursion — and the phone, anchored since it
        was written, disagreed with it.
        """
        src = WEB.read_text()
        assert "restEndsAt" in src
        assert "restRemaining.value -= 1" not in src

    def test_visibility_change_re_reads_the_deadline(self):
        """Waiting for the next interval after refocus shows a stale number
        for up to a second, on the screen whose whole job is that number."""
        assert "visibilitychange" in WEB.read_text()

    def test_the_chime_cannot_repeat(self):
        """Re-evaluating an expired deadline must not re-fire the alert.

        The phone guards this with `lastNotifiedFor`; deriving remaining time
        from a clock means the zero-crossing is now evaluated on every tick
        AND every refocus, so the web needs the same guard it did not
        previously need.
        """
        assert "lastNotifiedFor" in WEB.read_text()
