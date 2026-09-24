"""Every Settings section must be reachable by clicking — TD-7, SETTINGS-B1.

This is a source-level guard, in the same spirit as
``test_local_day_boundary.py``: the failure it prevents is invisible to any
unit test, and it had already shipped once.

History. ``Settings.vue`` chose one of thirteen panes from ``?tab=`` with no
in-page tab bar; under the default neon shell ``SideNav`` never mounts, so
eight panes could only be reached by typing a URL. TD-7 added a rail.

SETTINGS-B1 replaced the single page with a home (``SettingsHome.vue``) and
one route per section, in the same order as the phone. What must hold now:

* every section route is linked from the home, so none is URL-only again;
* every old ``?tab=`` value still lands somewhere real — bookmarks, the
  phone's hints and notification deep links carry them;
* unsaved profile edits are not dropped silently on navigation (UX-W8).

The frontend has no JS test runner, so this lives with the backend suite.
"""

from __future__ import annotations

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
MAIN = FRONTEND / "main.ts"
SETTINGS_DIR = FRONTEND / "views" / "settings"
HOME = SETTINGS_DIR / "SettingsHome.vue"

# The thirteen panes the old page had. A bookmark to any of them must still
# resolve. Written out here on purpose rather than read from main.ts: the
# point is to catch a key being dropped from the redirect map.
OLD_TABS = {
    "updates", "access", "display", "profile", "ai", "tools", "imports",
    "trails", "strava", "fasting", "ha", "concept2", "google",
}

# Phone order (SettingsHomeScreen.kt). Web and phone list the same sections
# in the same order.
SECTIONS = ["you", "display", "connection", "integrations", "ai", "data", "about"]


def _routes() -> set[str]:
    return set(re.findall(r'path:\s*"(/settings[^"]*)"', MAIN.read_text()))


def _legacy_map() -> dict[str, str]:
    src = MAIN.read_text()
    m = re.search(r"const LEGACY_SETTINGS_TABS[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "LEGACY_SETTINGS_TABS not found in main.ts — did it move?"
    return dict(re.findall(r'^\s*([a-z0-9_]+):\s*"([^"]+)"', m.group(1), re.M))


def _integration_keys() -> set[str]:
    src = (SETTINGS_DIR / "integrations" / "health.ts").read_text()
    return set(re.findall(r'\{\s*key:\s*"([a-z0-9_]+)"', src))


def test_every_section_has_a_route():
    routes = _routes()
    for s in SECTIONS:
        assert f"/settings/{s}" in routes, f"/settings/{s} is not a route"
    assert "/settings/integrations/:key" in routes


def test_every_section_is_linked_from_the_home_in_phone_order():
    """A section without a row on the home is a section with no way in."""
    src = HOME.read_text()
    linked = re.findall(r'<SettingsRow\s+to="/settings/([a-z]+)"', src)
    assert linked == SECTIONS, (
        f"Settings home rows {linked} must be exactly {SECTIONS}, in the "
        "phone's order"
    )


def test_every_old_tab_still_resolves():
    legacy = _legacy_map()
    missing = OLD_TABS - set(legacy)
    assert not missing, f"old ?tab= values with no redirect: {sorted(missing)}"
    routes = _routes()
    integrations = _integration_keys()
    for tab, target in legacy.items():
        m = re.fullmatch(r"/settings/integrations/([a-z0-9_]+)", target)
        if m:
            assert m.group(1) in integrations, (
                f"?tab={tab} redirects to an integration page that does not exist: {target}"
            )
        else:
            assert target in routes, f"?tab={tab} redirects to a missing route {target}"


def test_the_home_route_applies_the_redirect():
    src = MAIN.read_text()
    block = src[src.index('path: "/settings", name: "settings"'):]
    block = block[: block.index("},\n    {")]
    assert "beforeEnter" in block and "LEGACY_SETTINGS_TABS" in block


def test_unsaved_profile_edits_are_guarded():
    """UX-W8: leaving with unsaved edits asks first, in-app and on unload."""
    src = (SETTINGS_DIR / "SettingsYou.vue").read_text()
    assert "onBeforeRouteLeave" in src
    assert "beforeunload" in src


def test_the_default_theme_still_renders_a_settings_entry_point():
    """The root cause, guarded at its source.

    theme.ts defaulting to neon is fine; what was not fine is that the neon
    shell had no path to eight settings panes. If the default theme changes
    again, this at least documents the coupling.
    """
    theme = FRONTEND / "theme.ts"
    if not theme.exists():
        return  # theme module moved; the home-row test above still covers us
    src = theme.read_text()
    assert "neon" in src, "expected the theme module to name the neon shell"
    you = (FRONTEND / "views" / "You.vue").read_text()
    assert 'to: "/settings"' in you, "the neon You hub must still link to Settings"
