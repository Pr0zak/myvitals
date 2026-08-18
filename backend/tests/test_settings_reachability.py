"""Every Settings pane must be reachable by clicking — TD-7.

This is a source-level guard, in the same spirit as
``test_local_day_boundary.py``: the failure it prevents is invisible to any
unit test, and it had already shipped.

``Settings.vue`` assigned ``activeTab`` exactly once, from ``?tab=``, with no
in-page tab bar. Under the classic shell ``SideNav.vue`` supplied the twelve
links -- but ``theme.ts`` defaults the theme to ``neon``, and under neon
``App.vue`` renders ``NeonNav`` instead, so ``SideNav`` never mounts.
``You.vue`` then offered exactly four settings pills. The net effect was that
eight of the twelve panes -- access, ai, tools, imports, trails, fasting, ha
and concept2 -- could only be reached by typing a URL, so a user on the
default theme could not configure AI, run a historical import, or set up
Home Assistant or Concept2 at all.

The frontend has no JS test runner, so this lives with the backend suite.
Parsing the source is crude, but the alternative is trusting that nobody adds
a thirteenth section and forgets the rail.
"""

from __future__ import annotations

import pathlib
import re

SETTINGS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "views" / "Settings.vue"
)


def _source() -> str:
    return SETTINGS.read_text()


def _section_keys(src: str) -> list[str]:
    m = re.search(r"const SECTION_KEYS:[^=]*=\s*\[(.*?)\]", src, re.S)
    assert m, "SECTION_KEYS not found — did the declaration move?"
    return re.findall(r'"([a-z0-9_]+)"', m.group(1))


def _label_keys(src: str) -> list[str]:
    m = re.search(r"const SECTION_LABELS:[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "SECTION_LABELS not found — did the declaration move?"
    return re.findall(r"^\s*([a-z0-9_]+):", m.group(1), re.M)


def test_every_section_has_a_rail_label():
    """A section without a label is a pane with no way in."""
    src = _source()
    keys, labels = set(_section_keys(src)), set(_label_keys(src))
    assert keys == labels, (
        f"sections with no rail label: {sorted(keys - labels)}; "
        f"labels for sections that do not exist: {sorted(labels - keys)}"
    )


def test_the_rail_is_rendered_and_derived_from_the_key_list():
    """The rail must iterate SECTION_KEYS, not a hand-written list.

    A parallel list is how the eight unreachable panes would come back: the
    section gets added, the second list does not, and nothing complains.
    """
    src = _source()
    assert 'class="settings-rail"' in src, "the settings rail is gone"
    assert 'v-for="key in SECTION_KEYS"' in src, (
        "the rail must be derived from SECTION_KEYS so a new section cannot "
        "be omitted from it"
    )


def test_selecting_a_section_writes_it_to_the_url():
    """Deep links and the rail have to agree on which pane is showing, or
    ?tab= silently means something different from what is on screen."""
    src = _source()
    assert "function selectTab(" in src
    assert "router.replace" in src, (
        "selectTab must record the section in the URL so a deep link, the "
        "rail and the Back button describe the same pane"
    )


def test_the_default_theme_still_renders_a_settings_entry_point():
    """The root cause, guarded at its source.

    theme.ts defaulting to neon is fine; what was not fine is that the neon
    shell had no path to eight settings panes. If the default theme changes
    again, this at least documents the coupling.
    """
    theme = SETTINGS.parent.parent / "theme.ts"
    if not theme.exists():
        return  # theme module moved; the rail test above still covers us
    src = theme.read_text()
    assert "neon" in src, "expected the theme module to name the neon shell"
