"""Every web view and phone screen must be visible to the parity gate.

`scripts/parity_check.py` is the release-time check for the enforced
web/phone parity rule (see CLAUDE.md), but its `PAIRS` map is hand-written
and nothing was checking that it stayed complete. SA-G2 found the drift:
eight web views and five phone screens had no row at all — not flagged as
web-only, just absent — so a release that moved only one half of Steps,
Hrv, SkinTemp, Measurements or the strength day-view still printed a clean
"all paired surfaces have matching changes", because the gate was never
looking at those files in the first place. `BloodPressure.vue` was worse:
it sat in `WEB_ONLY_OK` asserting there is no phone half while
`BpDetailScreen.kt` existed and had been edited seventeen times one-sided.

This mirrors `check_map_integrity()` already in the script, which catches a
PAIRS row pointing at a file that no longer exists. That check says nothing
about a file with no row at all, which is the shape of gap this test closes.
It imports the live module rather than re-deriving the glob logic, for the
same reason `pick_canonical_steps_source` and `_is_watch_source` are single
functions instead of two copies that can drift (see CLAUDE.md) — one set of
PAIRS/WEB_ONLY_OK data, read by both the release-time script and this gate.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "parity_check.py"


def _load_parity_check():
    spec = importlib.util.spec_from_file_location("parity_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_script_this_guard_reads_still_exists():
    """A guard that silently passes when its input moves is worthless."""
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_parity_map_has_no_stale_rows():
    """Same check the script runs itself — a PAIRS row naming a file that
    no longer exists silently checks nothing."""
    pc = _load_parity_check()
    stale = pc.check_map_integrity()
    assert not stale, f"parity map rows point at files that don't exist: {stale}"


def test_every_web_view_is_registered_or_opted_out():
    """Every `frontend/src/views/**.vue` must appear in PAIRS or WEB_ONLY_OK.

    An unregistered view is invisible to the release gate: nothing checks
    whether its phone counterpart moved with it. If this fails, either add
    a PAIRS row (after confirming a genuine phone counterpart exists and
    mirrors it) or add the view to WEB_ONLY_OK (after confirming it is
    genuinely web-only, not just currently missing a phone screen).
    """
    pc = _load_parity_check()
    web_gap, _phone_gap = pc.unregistered_surfaces()
    assert not web_gap, (
        "web views missing from PAIRS and WEB_ONLY_OK (invisible to the "
        f"parity gate): {web_gap}"
    )


def test_every_phone_screen_is_registered():
    """Every phone `*Screen.kt` under `ui/` must appear in PAIRS.

    There is no phone-only opt-out set today (WEB_ONLY_OK has no
    counterpart) because every current phone screen has a real web
    counterpart. If a genuinely phone-only screen is ever added, this test
    is the place to introduce that opt-out set — don't leave it silently
    unregistered instead.
    """
    pc = _load_parity_check()
    _web_gap, phone_gap = pc.unregistered_surfaces()
    assert not phone_gap, (
        f"phone screens missing from PAIRS (invisible to the parity gate): {phone_gap}"
    )
