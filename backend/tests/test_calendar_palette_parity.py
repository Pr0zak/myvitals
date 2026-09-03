"""Magenta meant strength on one device and yoga on the other — OG2-D-5.

Two shared palette modules already exist and already agree.
`frontend/src/utils/activityCategory.ts` maps strength to neon #ff3ad8
(magenta) and yoga to #6f7bff (periwinkle); `ui/common/ActivityCategory.kt`
maps STRENGTH to NeonMV.Magenta and YOGA to NeonMV.Periwinkle. Both
docstrings name StrengthHistory.vue as the source they were derived from.

Neither workout calendar imported either one.

`StrengthHistory.vue` wrote the hexes inline — the right values, but a second
copy. `StrengthHistoryScreen.kt` wrote a THIRD set, and that one was
inverted: strength drew as NeonMV.Lime, which the shared palette assigns to
RUN, and yoga drew as NeonMV.Magenta, which the shared palette assigns to
STRENGTH. So on the neon shell — the shell in use — the same completed
session was magenta on the desktop calendar and lime on the phone calendar,
and magenta on the phone meant a different thing entirely. That is CLAUDE.md's
"two clients showing different numbers for the same metric is always a bug",
in colour. The classic skin happened to agree, which is why it survived.

The fix deletes constants rather than adding them: both files now read the
module that already existed for this purpose. Cardio maps to the palette's
`ride`, matching `categoryForSplitFocus` on the phone and the bike icon the
activity feed already draws for a cardio day.

Two smaller things in the same pass, both in the same two files.

**The future weeks.** `range: y` drew all 53 columns, so the current year's
strip was roughly a third empty future and every cell shrank to fit a year
that has not happened yet. `ActivityYearCalendar.vue` had already solved
exactly this and recorded why in a comment; it was never carried across.

**The cells are an index, not a picture.** 110 distinct days in 2026 carry a
completed workout, and the view a cell would open already exists on both
surfaces — `/workout/strength/day/:date` on web, the detail sheet a list row
opens on the phone. Leaving them inert made the densest navigation surface on
the screen the one thing that could not be touched. Only a day that HAS a
workout navigates: opening an empty day lands on a sheet with nothing in it,
which reads as a failure rather than as an empty day.

Explicitly NOT done: OG2-D6's headline, shading the strip by minutes. That
reverts a shipped decision — v0.7.361 deliberately replaced the
minutes-intensity ramp with the per-category calendar and recorded the reason
in the component docstring — and this user's 2026 mix is 48 ebike rides to 13
walks, so category is the load-bearing channel.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB_CAL = REPO / "frontend" / "src" / "views" / "workout" / "StrengthHistory.vue"
WEB_PALETTE = REPO / "frontend" / "src" / "utils" / "activityCategory.ts"
PHONE_CAL = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthHistoryScreen.kt"
)
PHONE_PALETTE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "common" / "ActivityCategory.kt"
)


def _code_only(src: str) -> str:
    """Strip // and /* */ comments.

    Every absence check below has to read code rather than prose, or it
    matches the paragraph explaining why the thing is absent.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _web_script(path: pathlib.Path) -> str:
    """The <script> block only.

    A .vue file's <style> legitimately holds hexes that have nothing to do
    with the activity palette — a rating chip's red, the neon custom-property
    block — and a check that swept those in would be forbidding unrelated
    colour rather than a duplicated palette.
    """
    src = path.read_text()
    end = src.index("</script>")
    return _code_only(src[:end])


def _phone_calendar(path: pathlib.Path) -> str:
    """The calendar composables only.

    `NeonMV.Lime` appears elsewhere in this file for the muscle-volume
    `in_range` band and for a `completed` status pill. Those are different
    semantic axes that happen to share a hue, and forbidding the constant
    file-wide would be asserting something untrue about them.
    """
    src = _code_only(path.read_text())
    start = src.index("private fun WorkoutCalendar(")
    end = src.index("private fun ", src.index("private fun YearStrip(") + 10)
    return src[start:end]


class TestTheTwoPalettesStillAgree:
    """They did agree; nothing read them. Pinning it so the fix has a base."""

    def test_strength_is_magenta_on_both(self):
        assert "#ff3ad8" in WEB_PALETTE.read_text().lower()
        assert "NeonMV.Magenta" in PHONE_PALETTE.read_text()
        web = WEB_PALETTE.read_text()
        line = next(l for l in web.splitlines() if l.strip().startswith("strength:"))
        assert "#ff3ad8" in line.lower()
        kt = next(l for l in PHONE_PALETTE.read_text().splitlines()
                  if l.strip().startswith("STRENGTH("))
        assert "NeonMV.Magenta" in kt

    def test_yoga_is_periwinkle_on_both(self):
        web = WEB_PALETTE.read_text()
        line = next(l for l in web.splitlines() if l.strip().startswith("yoga:"))
        assert "#6f7bff" in line.lower()
        kt = next(l for l in PHONE_PALETTE.read_text().splitlines()
                  if l.strip().startswith("YOGA("))
        assert "NeonMV.Periwinkle" in kt


class TestBothCalendarsReadTheSharedPalette:
    def test_the_web_imports_it(self):
        assert "activityCategory" in WEB_CAL.read_text()

    def test_the_phone_imports_it(self):
        assert "categoryForSplitFocus" in PHONE_CAL.read_text()

    def test_the_phone_no_longer_paints_strength_with_the_run_colour(self):
        """The inversion, in one assertion. NeonMV.Lime is RUN in the shared
        palette and was this file's STRENGTH."""
        assert "NeonMV.Lime" not in _phone_calendar(PHONE_CAL)

    def test_neither_calendar_writes_a_category_hex_inline(self):
        """The fix deletes constants rather than adding them. A file that
        names a palette hex has started a fourth copy."""
        web = _web_script(WEB_CAL).lower()
        for hexcode in ("#ff3ad8", "#6f7bff", "#a78bfa", "#ef4444", "#38bdf8"):
            assert hexcode not in web, f"StrengthHistory.vue inlines {hexcode}"
        phone = _phone_calendar(PHONE_CAL).lower()
        for kt in ("0xffa78bfa", "0xffef4444", "0xff38bdf8"):
            assert kt not in phone, f"StrengthHistoryScreen.kt inlines {kt}"

    def test_cardio_maps_to_ride_on_both(self):
        """Matching the bike icon the activity feed already draws for it,
        rather than painting a cardio day in the strength colour."""
        assert '"ride"' in _web_script(WEB_CAL)
        assert "ActivityCategory.RIDE" in PHONE_PALETTE.read_text()


class TestTheCurrentYearStopsAtToday:
    def test_the_web_clamps_the_range(self):
        src = _web_script(WEB_CAL)
        assert "toLocalISO" in src
        assert re.search(r"range:\s*y\s*===", src), "range is still a bare year"

    def test_it_reuses_the_projects_own_local_date_helper(self):
        """`dates.ts` exists because `toISOString().slice(0,10)` on a locally
        built Date is off by a day for half of every day in this timezone."""
        src = _web_script(WEB_CAL)
        assert "toISOString" not in src


class TestTheCellsOpenTheDay:
    def test_the_web_cell_navigates(self):
        src = _web_script(WEB_CAL)
        assert "/workout/strength/day/" in src

    def test_the_web_route_it_uses_exists(self):
        """A cell pushing a route that is not registered is a dead click
        that looks like a hang."""
        main = (REPO / "frontend" / "src" / "main.ts").read_text()
        assert "/workout/strength/day/:date" in main

    def test_the_phone_cell_takes_a_tap(self):
        """The first pointer gesture on any chart under ui/strength."""
        src = PHONE_CAL.read_text()
        assert "detectTapGestures" in src
        assert "pointerInput" in src

    def test_the_phone_inverts_the_layout_rather_than_keeping_hit_boxes(self):
        """Two descriptions of one layout drift the moment either cell size
        changes, and the size here is computed from available width."""
        src = _phone_calendar(PHONE_CAL)
        assert "cellPxOut" in src and "startDowOut" in src

    def test_an_empty_day_does_not_navigate(self):
        """It would land on a detail sheet with nothing in it, which reads
        as a failure rather than as a day with no workout."""
        assert "byDate.containsKey(iso)" in PHONE_CAL.read_text()


class TestTheShadingDecisionIsNotReverted:
    def test_no_minutes_intensity_ramp_returned(self):
        """v0.7.361 deliberately replaced one with the per-category calendar.
        This user's 2026 mix is 48 ebike rides to 13 walks, so category is
        the load-bearing channel and duration would fight it for the same
        hue."""
        assert "minutes" not in _web_script(WEB_CAL).lower()
        assert "minutes" not in _phone_calendar(PHONE_CAL).lower()
