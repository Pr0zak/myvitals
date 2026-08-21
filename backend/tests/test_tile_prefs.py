"""Key-metrics tile order reconciliation (TILE-1).

`vitals_order` / `vitals_hidden` had four readers and no writer for most
of this app's life. Now that it can be written, the reconciler is the
piece that has to survive the tile set changing underneath a saved
preference — which it will, every time a metric is added.
"""

from __future__ import annotations

import re
from pathlib import Path

from myvitals.analytics import tiles

TILES_SRC = Path(tiles.__file__).read_text()


class TestLabelsMatchTheRealTiles:
    def test_every_emitted_tile_has_a_label_entry(self):
        """TILE_LABELS is a second copy of names `build_tiles` sets inline.

        The editor reads it so it does not have to run the query-heavy tile
        build just to learn what a metric is called. A tile emitted by
        `build_tiles` but missing here would be invisible in the editor and
        unorderable — present in the grid, absent from the control.
        """
        emitted = set(re.findall(r'add\(key="([a-z_]+)"', TILES_SRC))
        assert emitted, "no add(key=...) calls found — did build_tiles move?"
        missing = emitted - set(tiles.TILE_LABELS)
        assert not missing, f"tiles with no TILE_LABELS entry: {sorted(missing)}"

    def test_no_label_entry_for_a_tile_that_no_longer_exists(self):
        emitted = set(re.findall(r'add\(key="([a-z_]+)"', TILES_SRC))
        stale = set(tiles.TILE_LABELS) - emitted
        assert not stale, f"TILE_LABELS names tiles build_tiles never emits: {sorted(stale)}"

    def test_every_tile_has_a_group(self):
        for key in tiles.TILE_LABELS:
            assert key in tiles.TILE_GROUPS, (
                f"{key} has no group, so the editor files it under 'Other'"
            )


class TestReconcile:
    def test_empty_preference_yields_the_default_order(self):
        order, hidden = tiles.reconcile_tile_prefs(None, None)
        assert order == list(tiles.DEFAULT_TILE_ORDER)
        assert hidden == []

    def test_legacy_vital_enum_names_are_translated(self):
        """Preferences saved by older builds used `Vital` enum names."""
        order, hidden = tiles.reconcile_tile_prefs(["HR", "SLEEP"], ["BP"])
        assert order[:2] == ["resting_hr", "sleep_duration"]
        assert hidden == ["blood_pressure"]

    def test_a_new_tile_appears_rather_than_being_demoted(self):
        """The bug this function exists to prevent.

        A saved order predates any newly added metric by definition. The
        old client-side sort gave unmentioned keys a rank of 1e9, so a new
        tile landed dead last forever — and silently, since nothing ever
        told the user a metric had been added.
        """
        partial = ["hrv", "steps"]
        order, _ = tiles.reconcile_tile_prefs(partial, [])
        assert set(order) == set(tiles.DEFAULT_TILE_ORDER), (
            "reconcile must return the complete current key set"
        )
        assert order[:2] == partial, "the user's explicit choices keep their positions"

    def test_a_removed_tile_is_dropped_from_the_order(self):
        order, _ = tiles.reconcile_tile_prefs(
            ["hrv", "a_metric_that_was_deleted", "steps"], [],
        )
        assert "a_metric_that_was_deleted" not in order

    def test_duplicates_collapse(self):
        order, hidden = tiles.reconcile_tile_prefs(
            ["hrv", "hrv", "steps"], ["weight", "weight"],
        )
        assert order.count("hrv") == 1
        assert hidden == ["weight"]

    def test_a_legacy_name_and_its_key_do_not_both_survive(self):
        """`HR` and `resting_hr` are the same tile spelled two ways."""
        order, _ = tiles.reconcile_tile_prefs(["HR", "resting_hr"], [])
        assert order.count("resting_hr") == 1

    def test_hidden_is_not_removed_from_order(self):
        """Hidden tiles stay IN the order, flagged rather than filtered.

        Three detail screens (HeartRate.vue, HrDetailScreen.kt,
        VitalsDetailScreen.kt) look a tile up by key to source their band
        and baseline. Dropping hidden keys server-side would blank those
        screens for anyone who had hidden the corresponding home tile.
        """
        order, hidden = tiles.reconcile_tile_prefs(None, ["weight"])
        assert "weight" in order
        assert "weight" in hidden

    def test_hidden_entries_that_are_not_real_tiles_are_dropped(self):
        _, hidden = tiles.reconcile_tile_prefs(None, ["weight", "nonsense"])
        assert hidden == ["weight"]

    def test_reconcile_is_idempotent(self):
        """Round-tripping a reconciled preference must not change it.

        The editor saves what the server returned, so a non-idempotent
        reconcile would let the order drift a little on every save.
        """
        once = tiles.reconcile_tile_prefs(["steps", "HR"], ["BP"])
        twice = tiles.reconcile_tile_prefs(*once)
        assert once == twice

    def test_skin_temp_is_reachable_through_a_legacy_name(self):
        """The gap that made this a real bug rather than a tidy-up.

        Neither client's private VITAL_TO_KEY table had a SKIN_TEMP entry,
        so no saved order could ever mention skin temp and it always sorted
        to the end of the grid behind everything the user had ranked.
        """
        assert "SKIN_TEMP" in tiles.LEGACY_VITAL_NAMES
        order, _ = tiles.reconcile_tile_prefs(["SKIN_TEMP", "HR"], [])
        assert order[0] == "skin_temp"
