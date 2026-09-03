"""The generator's notes are a disclosure, not a paragraph — OG2-D-7.

Reported from live use with a screenshot, and the fault was mine: OG2-D-2
added workout-level notes to the phone so the #WP-8 cadence advisory would be
visible there, and rendered the raw string.

`generate_plan` appends one note per decision it made — which split it chose
and why, a missed session, accessory slots added to hit a target count, the
mobility block, and the cadence advisory when it fires. A normal strength day
therefore carries four, joined by newlines, and printed raw that is nine
lines of prose between the header and set 1 on the page whose entire job is
logging set 1.

The content is worth keeping. It is the only place the app explains WHY
today's plan looks like this, and OG2-D-2 exists precisely because that
explanation was web-only. It is simply not worth reading before every set,
so it goes behind a header the way the Coach card sitting directly above it
has since v0.7.169.

Summarised by COUNT, not by a truncated preview. A note cut mid-sentence is
less useful than a number and reads as a rendering fault rather than as a
deliberate summary.

Both surfaces, because both printed it unconditionally under the header —
the phone since OG2-D-2 and the web since long before.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)


class TestItIsCollapsedByDefault:
    def test_the_phone_starts_closed(self):
        src = PHONE.read_text()
        assert "var open by remember(plan.id) { mutableStateOf(false) }" in src

    def test_the_web_starts_closed(self):
        assert "const notesOpen = ref(false);" in WEB.read_text()

    def test_the_phone_header_is_tappable(self):
        src = PHONE.read_text()
        block = src[src.index('"Why this plan"') - 1200:]
        assert "clickable { open = !open }" in block[:1200]

    def test_the_web_header_is_a_button(self):
        src = WEB.read_text()
        assert 'class="pn-head"' in src
        assert "notesOpen = !notesOpen" in src


class TestTheSummaryIsACountNotAPreview:
    def test_both_surfaces_derive_the_count_from_the_lines(self):
        """Counted, not hard-coded — the number of notes varies per plan."""
        phone = PHONE.read_text()
        block = phone[phone.index('"Why this plan"') - 900:]
        assert "lines.size" in block[:1800]
        assert "plan.notes!!.trim().lines()" in phone
        web = WEB.read_text()
        assert "planNotes.length" in web
        assert 'split("\\n")' in web

    def test_neither_truncates_the_text(self):
        """A note cut mid-sentence is less useful than a number and reads as
        a rendering fault rather than a deliberate summary."""
        phone = PHONE.read_text()
        block = phone[phone.index('"Why this plan"'):][:1800]
        assert ".take(" not in block
        assert "ellipsis" not in block.lower()
        web = WEB.read_text()
        wblock = web[web.index("plan-notes"):][:1200]
        assert "slice(" not in wblock
        assert "text-overflow" not in wblock

    def test_both_label_it_the_same(self):
        assert "Why this plan" in WEB.read_text()
        assert "Why this plan" in PHONE.read_text()

    def test_singular_and_plural_are_both_handled(self):
        assert '"1 note"' in PHONE.read_text()
        assert "'note' : 'notes'" in WEB.read_text()


class TestTheContentIsStillReachable:
    def test_the_phone_renders_the_full_string_when_open(self):
        src = PHONE.read_text()
        block = src[src.index('"Why this plan"'):]
        assert "if (open) {" in block[:1500]
        assert "plan.notes!!" in block[:1500]

    def test_the_web_renders_the_full_string_when_open(self):
        src = WEB.read_text()
        assert 'v-if="notesOpen"' in src
        assert "workout?.notes" in src

    def test_the_web_preserves_the_line_breaks(self):
        """The notes are newline-joined, so collapsing whitespace would run
        four separate statements into one sentence."""
        assert "white-space: pre-line" in WEB.read_text()

    def test_the_cardio_day_card_is_untouched(self):
        """A cardio day comes back with exercises=[] and the prescription
        itself in `notes`. There it IS the content of the screen, not an
        explanation of it, so it stays a plain card."""
        src = PHONE.read_text()
        assert "plan.exercises.isEmpty() && !plan.notes.isNullOrBlank()" in src
