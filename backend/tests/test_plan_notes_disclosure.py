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
_STRENGTH = REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals" / "ui" / "strength"


class _Surface:
    """UI-2 split the phone screen across three files; read them as one."""

    def __init__(self, *paths: pathlib.Path) -> None:
        self.paths = paths

    def read_text(self) -> str:
        return "\n".join(p.read_text() for p in self.paths)


PHONE = _Surface(
    _STRENGTH / "StrengthTodayScreen.kt",
    _STRENGTH / "NowHero.kt",
    _STRENGTH / "WorkoutSlots.kt",
)


# UI-2 moved the disclosure from an inline header into a chip on the banner
# strip (phone: a bottom sheet; web: an expander under the strip). The
# invariants are unchanged — collapsed by default, a count not a preview, one
# row per note — and are asserted against the new markup.


class TestItIsCollapsedByDefault:
    def test_the_phone_starts_closed(self):
        src = PHONE.read_text()
        assert "var openSheet by mutableStateOf<String?>(null)" in src

    def test_the_web_starts_closed(self):
        assert "const openChip = ref<ChipKey | null>(null);" in WEB.read_text()

    def test_the_phone_header_is_tappable(self):
        src = PHONE.read_text()
        assert ".clickable { onOpen(c.key) }" in src
        assert 'BannerChip("why", "Why this plan · $n"' in src

    def test_the_web_header_is_a_button(self):
        assert "@click=\"toggleChip('why')\"" in WEB.read_text()


class TestTheSummaryIsACountNotAPreview:
    def test_both_surfaces_derive_the_count_from_the_lines(self):
        """Counted, not hard-coded — the number of notes varies per plan."""
        phone = PHONE.read_text()
        assert "plan.notes.trim().lines().count { it.isNotBlank() }" in phone
        web = WEB.read_text()
        assert "planNotes.length" in web
        assert 'split("\\n")' in web

    def test_neither_truncates_the_text(self):
        """A note cut mid-sentence is less useful than a number and reads as
        a rendering fault rather than a deliberate summary."""
        phone = PHONE.read_text()
        block = phone[phone.index('"why" -> {'):][:1200]
        assert ".take(" not in block
        assert "ellipsis" not in block.lower()
        web = WEB.read_text()
        assert "slice(" not in web[web.index('class="pn-list"'):][:300]
        assert "text-overflow" not in web[web.index(".pn-list {"):][:200]

    def test_both_label_it_the_same(self):
        """Both chips read "Why this plan · N"."""
        assert ('Why this plan<template v-if="planNotes.length"> · '
                '{{ planNotes.length }}') in WEB.read_text()
        assert '"Why this plan · $n"' in PHONE.read_text()


class TestTheContentIsStillReachable:
    def test_the_phone_renders_every_note_when_open(self):
        """OG2-D-7 changed HOW, not WHETHER: opening the disclosure reaches
        every note, by iterating the same lines the count came from."""
        src = PHONE.read_text()
        block = src[src.index('"why" -> {'):][:1200]
        assert "for (line in lines)" in block

    def test_the_web_renders_every_note_when_open(self):
        src = WEB.read_text()
        assert "v-if=\"openChip === 'why' && whyVisible\"" in src
        assert 'v-for="(n, i) in planNotes"' in src

    def test_the_notes_cannot_run_together_into_one_sentence(self):
        """One element per note cannot merge them, so the rule is enforced by
        the markup rather than by a `white-space: pre-line` a later edit could
        drop without anything failing."""
        src = WEB.read_text()
        assert '<li v-for="(n, i) in planNotes"' in src
        assert "white-space: pre-line" not in src

    def test_the_cardio_day_card_is_untouched(self):
        """A cardio day comes back with exercises=[] and the prescription
        itself in `notes`. There it IS the content of the screen, so it is
        the hero, not a disclosure."""
        assert "plan.exercises.isEmpty() -> PrescriptionHero(" in PHONE.read_text()
