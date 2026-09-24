"""UI-3 — the two server facts Body's redesign renders.

`cadence` decides whether a tile is drawn as a daily 2-up chart card or as a
compact "as of <date>" row with a dot strip. It lives on the server so the
phone and the web cannot keep two different lists of which metrics are
measured by hand — they already disagreed once about skin temp, when each
kept its own copy of the tile-order table.

`last_sync` on `/summary/tiles` is the "synced Xm ago" beside the in-range
count. It must come from the same resolver `/summary/today` uses; a second
query written inline would be one filter short of the SA-O2 fix, which is
exactly how that ghost heartbeat reached the home screen the first time.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from myvitals.analytics import tiles
from myvitals.api import summary

TILES_SRC = Path(tiles.__file__).read_text()


def _added_keys() -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(ast.parse(TILES_SRC)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "add":
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    keys.add(kw.value.value)
    return keys


def test_every_tile_the_builder_emits_has_a_declared_cadence():
    missing = _added_keys() - set(tiles.TILE_CADENCE)
    assert not missing, f"tiles with no cadence: {sorted(missing)}"


def test_cadence_vocabulary_is_two_words():
    assert set(tiles.TILE_CADENCE.values()) == {"daily", "intermittent"}


def test_hand_measured_metrics_are_intermittent():
    for key in ("weight", "blood_pressure"):
        assert tiles.TILE_CADENCE[key] == "intermittent"
    for key in ("steps", "sleep_duration", "hrv", "resting_hr", "recovery"):
        assert tiles.TILE_CADENCE[key] == "daily"


def test_add_stamps_cadence_on_every_tile():
    """The field is set in `add()`, not per call, so a new tile cannot ship
    without one and fall through to whichever tier a client guesses."""
    src = inspect.getsource(tiles.tile_stats)
    assert 'kw.setdefault("cadence", TILE_CADENCE.get(' in src


def test_tiles_last_sync_uses_the_shared_resolver():
    src = inspect.getsource(summary.summary_tiles)
    assert "current_last_sync(db)" in src
    assert '"last_sync"' in src
    # And /summary/today reads the same helper rather than its own copy.
    today_src = inspect.getsource(summary.today)
    assert "_sync_signals(db)" in today_src
    assert "SyncHeartbeat" not in today_src


def test_shared_resolver_keeps_the_real_install_filter():
    src = inspect.getsource(summary._sync_signals)
    assert "real_install_heartbeat_filter()" in src
