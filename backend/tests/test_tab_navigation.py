"""Bottom-nav tab taps must land on the tab root — v0.8.2.

A source guard, in the same spirit as `test_settings_reachability.py`: the
Android module has no test runner, and the failure this prevents is one that
shipped and survived several releases because it only appears after a
specific navigation sequence.

`navigateTopTab` carried `saveState = true` / `restoreState = true`, which is
the pattern every bottom-nav sample shows. Those flags do not merely remember
a scroll position — they save and restore the tab's whole nested back stack.
So after drilling Body → Heart rate, tapping Body did not show Body; it
restored Heart rate.

Reproduced on an emulator against the pre-fix build, from a cold start:

    tap You      -> You        (correct)
    tap Journal  -> Journal    (correct)
    tap Today    -> Today      (correct)
    tap You      -> Journal    <-- restored the drill-down

Because the saved stacks live in the NavController rather than on disk,
force-quitting the app was the only reliable way to clear them, which is
exactly the workaround the bug report described.
"""

from __future__ import annotations

import pathlib
import re

SHELL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "neon" / "NeonAppShell.kt"
)


def _navigate_top_tab() -> str:
    src = SHELL.read_text()
    start = src.index("private fun NavHostController.navigateTopTab(")
    # Function body ends at the next top-level closing brace.
    end = src.index("\n}", start) + 2
    return src[start:end]


def test_the_helper_still_exists():
    assert SHELL.exists(), f"{SHELL} moved — update this guard"
    assert "navigateTopTab" in SHELL.read_text()


def test_tab_taps_do_not_save_or_restore_a_nested_back_stack():
    """The exact flags that resurrected detail screens.

    Restoring a nested stack is defensible for tabs that are independent
    workspaces. It is wrong here: these five tabs are views onto the same
    day, the leftmost is literally labelled "Today", and a tab bar whose
    destination depends on invisible history is not predictable.
    """
    body = _navigate_top_tab()
    offenders = [
        flag for flag in ("saveState = true", "restoreState = true")
        if re.search(rf"^\s*{re.escape(flag)}", body, re.M)
    ]
    assert not offenders, (
        f"navigateTopTab sets {offenders} again. Those flags restore the "
        "tab's whole nested back stack, so tapping a tab returns the user to "
        "the detail screen they were last on inside it instead of the tab "
        "root — see this module's docstring for the reproduced trace."
    )


def test_the_pop_is_inclusive_so_no_stale_entry_survives():
    body = _navigate_top_tab()
    assert "inclusive = true" in body, (
        "popping non-inclusively leaves the start destination on the stack; "
        "combined with a later restore that is how the old behaviour crept in"
    )


def test_re_tapping_the_current_tab_is_a_no_op():
    """Without this the tab pops and re-pushes itself, visibly reloading the
    screen under the user's finger."""
    body = _navigate_top_tab()
    assert "currentDestination?.route == route" in body
