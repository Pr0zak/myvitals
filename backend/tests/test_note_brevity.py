"""Notes are rows of one clause, not paragraphs — OG2-D-7.

Reported twice from live use, with screenshots. Two separate note systems had
the same fault: the server composed a full explanatory sentence and the client
printed it raw.

THE PLAN NOTES. `generate_plan` appends one note per decision it made and the
list is joined with newlines at `persist_plan`. Each note was a
paragraph-length sentence that justified itself inline, so four of them read
as a wall. They are now one clause each, and both clients render one ROW per
note instead of printing the join — the list already existed and was being
thrown away at the last moment.

THE PER-SLOT REASONS. OG2-B3's `why` is worse, because it repeats per
exercise: eight slots of "No recent history for Arnold Dumbbell Press, so this
is a starting weight for your level — rate the sets and it will tune from
there" is 24 lines of oblique 11sp text inside the cards you are trying to log
into. It also opened by naming the exercise, which is the card's own title two
lines above. Now: "Starting weight for your level — no recent history."

WHAT WAS CUT, AND WHAT WAS NOT. The clause that justifies the decision goes —
the note's existence already says the decision was made, and "focus chosen by
need, not by what was missed" is the generator explaining itself to itself.
Every NUMBER, every DATE, every muscle name and every NEGATION stays: this
codebase's rule is that brevity must never cost correctness, and a target that
loses its poundage is worse than a long one.

Two instructions were also cut, because they told the user to tap something
already on screen. The deload note said "Tap Use full weight to override"
beside a deload banner carrying that exact button.

The italic went with the length. Oblique text at 11px is the least legible
thing on the card, and it sat directly under the numbers the card exists to
show. One short line does not need it; the muted colour already marks it
secondary.

Deliberately NOT changed: the cadence advisory's copy. Its directional verb
is load-bearing — `test_frequency_advisory.py` exists because the verb was
backwards once — and shortening it would have meant rewriting nine assertions
that protect a real past bug for a note that has never yet fired.
"""

from __future__ import annotations

import pathlib
import re

from myvitals.analytics.strength import (
    bodyweight_progression,
    next_prescription,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)

DUMBBELL = {
    "id": "Arnold_Dumbbell_Press", "name": "Arnold Dumbbell Press",
    "equipment": ["dumbbell"], "is_compound": True,
    "movement_pattern": "vertical_push",
}
BODYWEIGHT = {
    "id": "Pushups", "name": "Pushups", "equipment": ["bodyweight"],
    "is_compound": True, "movement_pattern": "horizontal_push",
}
BASE = dict(reps_lo=8, reps_hi=12, level="intermediate", goal="hypertrophy",
            pairs_lb=[10, 15, 20, 25, 30], wrist_weights_lb=[])

CASES = [
    dict(exercise=DUMBBELL, avg_rating=None, avg_weight_lb=None,
         avg_reps=None, enough=True),
    dict(exercise=DUMBBELL, avg_rating=5.0, avg_weight_lb=25.0,
         avg_reps=12.0, enough=True),
    dict(exercise=DUMBBELL, avg_rating=1.0, avg_weight_lb=25.0,
         avg_reps=8.0, enough=True),
    dict(exercise=DUMBBELL, avg_rating=4.0, avg_weight_lb=25.0,
         avg_reps=9.0, enough=True),
    dict(exercise=DUMBBELL, avg_rating=5.0, avg_weight_lb=25.0,
         avg_reps=12.0, enough=False),
    dict(exercise=DUMBBELL, avg_rating=None, avg_weight_lb=25.0,
         avg_reps=10.0, enough=True),
    dict(exercise=BODYWEIGHT, avg_rating=5.0, avg_weight_lb=None,
         avg_reps=12.0, enough=True),
]


def _why(**kw) -> str:
    return next_prescription(**{**BASE, **kw}).why


class TestEveryReasonFitsOnALine:
    def test_none_exceeds_sixty_characters(self):
        """The card is about 320dp wide at 11sp, so roughly sixty characters
        is one line. Three of these used to run to three."""
        for kw in CASES:
            why = _why(**kw)
            assert len(why) <= 60, f"{len(why)} chars: {why}"

    def test_none_has_two_sentences(self):
        """A second sentence is the justifying clause coming back."""
        for kw in CASES:
            why = _why(**kw)
            assert why.count(".") <= 1, why

    def test_none_repeats_the_exercise_name(self):
        """It is the card's own title, two lines above the reason."""
        for kw in CASES:
            assert kw["exercise"]["name"] not in _why(**kw)

    def test_every_bodyweight_rung_fits_too(self):
        for kw in (
            dict(avg_rating=5.0, avg_reps=9.0),
            dict(avg_rating=1.0, avg_reps=6.0),
            dict(avg_rating=None, avg_reps=9.0),
            dict(avg_rating=4.0, avg_reps=12.0),
            dict(avg_rating=4.0, avg_reps=9.0),
        ):
            _lo, _hi, _r, why, _a = bodyweight_progression(
                base_reps_lo=9, base_reps_hi=11, is_timed=False,
                session_complete=True, **kw)
            assert len(why) <= 60, f"{len(why)} chars: {why}"


class TestBrevityDidNotCostCorrectness:
    def test_the_weight_survives_every_reason_that_holds_one(self):
        """A target that loses its poundage is worse than a long one."""
        for kw in CASES:
            if kw["avg_weight_lb"] is None:
                continue
            assert "25" in _why(**kw), _why(**kw)

    def test_the_rep_target_survives(self):
        why = _why(exercise=DUMBBELL, avg_rating=4.0, avg_weight_lb=25.0,
                   avg_reps=9.0, enough=True)
        assert re.search(r"\d+ reps", why), why

    def test_the_beaten_number_survives(self):
        _lo, _hi, _r, why, _a = bodyweight_progression(
            base_reps_lo=9, base_reps_hi=11, is_timed=False,
            session_complete=True, avg_rating=4.0, avg_reps=12.0)
        assert "11" in why, why

    def test_direction_is_still_unambiguous(self):
        """Up, down and hold must never be inferable only from context."""
        up = _why(exercise=DUMBBELL, avg_rating=5.0, avg_weight_lb=25.0,
                  avg_reps=12.0, enough=True)
        down = _why(exercise=DUMBBELL, avg_rating=1.0, avg_weight_lb=25.0,
                    avg_reps=8.0, enough=True)
        hold = _why(exercise=DUMBBELL, avg_rating=4.0, avg_weight_lb=25.0,
                    avg_reps=9.0, enough=True)
        assert up.startswith("Up ")
        assert down.startswith("Down ")
        assert hold.startswith("Hold ")


class TestBothSurfacesRenderRowsNotAParagraph:
    def test_the_web_iterates_the_notes(self):
        src = WEB.read_text()
        assert 'v-for="(n, i) in planNotes"' in src

    def test_the_web_no_longer_prints_the_join(self):
        """`white-space: pre-line` over the raw string was the paragraph."""
        src = WEB.read_text()
        assert "pn-body" not in src

    def test_the_phone_iterates_the_notes(self):
        src = PHONE.read_text()
        block = src[src.index('"Why this plan"'):][:2500]
        assert "for (line in lines)" in block

    def test_neither_reason_is_italic_any_more(self):
        assert "font-style: italic" not in WEB.read_text()[
            WEB.read_text().index(".why-target {"):][:300]
        block = PHONE.read_text()
        i = block.index("wex.notes?.takeIf")
        assert "Italic" not in block[i:i + 600]


class TestTheCardioDayIsNotDoubleRendered:
    def test_the_web_disclosure_requires_exercises(self):
        """A cardio day comes back with exercises=[] and the prescription in
        `notes`, and `.cardio-card` already renders it. Without this gate the
        same string appeared twice on one screen — once as the session's
        content and once as an explanation of it."""
        src = WEB.read_text()
        assert 'v-if="planNotes.length && workout?.exercises?.length"' in src

    def test_the_phone_already_required_it(self):
        assert "plan.exercises.isNotEmpty() && !plan.notes.isNullOrBlank()" \
            in PHONE.read_text()


class TestTheNeonShellGetsMutedText:
    def test_the_disclosure_classes_have_a_neon_rule(self):
        """They set no colour, so under the neon shell they inherited
        --rn-ink and read brighter than the exercise names above them."""
        src = WEB.read_text()
        assert 'html[data-theme="neon"] .pn-item' in src
        assert "--rn-mut" in src[src.index('html[data-theme="neon"] .pn-item'):][:200]
