"""Mobility cool-down pose selection.

The block used to be a bare rng.sample over every mobility entry in the
catalog, which meant two things went wrong: a pose the user had explicitly
disabled kept being appended (the pref was honoured for strength slots but
not here), and uniform sampling kept landing on the same couple of poses
because nothing pushed toward the ones that hadn't come up recently.
"""
from __future__ import annotations

from myvitals.analytics.strength import select_mobility_poses


def _pose(pose_id: str, *, equipment: list[str] | None = None,
          pattern: str = "mobility") -> dict:
    return {
        "id": pose_id,
        "name": pose_id.replace("_", " "),
        "movement_pattern": pattern,
        "equipment": ["bodyweight"] if equipment is None else equipment,
    }


POOL = [_pose(f"Pose_{i}") for i in range(6)]


class TestPoolFiltering:
    def test_only_mobility_patterns_qualify(self):
        catalog = POOL + [_pose("Bench_Press", pattern="horizontal_push")]
        picks = select_mobility_poses(catalog, "seed", count=6)
        assert all(p["movement_pattern"] == "mobility" for p in picks)

    def test_only_bodyweight_poses_qualify(self):
        catalog = [_pose("Machine_Stretch", equipment=["machine"])] + POOL
        ids = {p["id"] for p in select_mobility_poses(catalog, "seed", count=6)}
        assert "Machine_Stretch" not in ids

    def test_disabled_poses_are_excluded(self):
        # The bug: this pref was honoured for strength slots and silently
        # ignored for the mobility block, so a disabled pose kept coming back.
        prefs = {"Pose_0": "disabled", "Pose_1": "disabled"}
        ids = {
            p["id"] for p in
            select_mobility_poses(POOL, "seed", exercise_prefs=prefs, count=6)
        }
        assert ids.isdisjoint({"Pose_0", "Pose_1"})
        assert len(ids) == 4

    def test_non_disabled_prefs_do_not_exclude(self):
        prefs = {"Pose_0": "favourite", "Pose_1": "avoid"}
        ids = {
            p["id"] for p in
            select_mobility_poses(POOL, "seed", exercise_prefs=prefs, count=6)
        }
        assert ids == {p["id"] for p in POOL}

    def test_empty_pool_returns_empty(self):
        assert select_mobility_poses([], "seed") == []

    def test_all_disabled_returns_empty(self):
        prefs = {p["id"]: "disabled" for p in POOL}
        assert select_mobility_poses(POOL, "seed", exercise_prefs=prefs) == []

    def test_pool_smaller_than_count_returns_what_exists(self):
        assert len(select_mobility_poses(POOL[:1], "seed", count=2)) == 1


class TestRotationPressure:
    def test_least_recently_used_poses_win(self):
        freq = {"Pose_0": 9, "Pose_1": 9, "Pose_2": 9,
                "Pose_3": 9, "Pose_4": 0, "Pose_5": 0}
        ids = {
            p["id"] for p in
            select_mobility_poses(POOL, "seed", recent_frequency=freq)
        }
        assert ids == {"Pose_4", "Pose_5"}

    def test_unseen_poses_beat_seen_ones(self):
        # A pose absent from the frequency map has never been logged.
        freq = {p["id"]: 5 for p in POOL if p["id"] != "Pose_3"}
        ids = {
            p["id"] for p in
            select_mobility_poses(POOL, "seed", recent_frequency=freq, count=1)
        }
        assert ids == {"Pose_3"}

    def test_ties_break_by_seed_not_catalog_order(self):
        # With no frequency signal every pose ties, so the seed alone decides.
        # Different seeds must be able to produce different pairs, or the
        # block grinds the same poses forever.
        seen = {
            tuple(p["id"] for p in select_mobility_poses(POOL, f"seed-{i}"))
            for i in range(12)
        }
        assert len(seen) > 1

    def test_same_seed_is_deterministic(self):
        a = select_mobility_poses(POOL, "fixed", recent_frequency={})
        b = select_mobility_poses(POOL, "fixed", recent_frequency={})
        assert [p["id"] for p in a] == [p["id"] for p in b]

    def test_frequency_outranks_jitter(self):
        # Whatever the seed, a never-used pose must beat a heavily-used one.
        freq = {"Pose_0": 40, "Pose_1": 40, "Pose_2": 40,
                "Pose_3": 40, "Pose_4": 40, "Pose_5": 1}
        for i in range(12):
            picks = select_mobility_poses(
                POOL, f"seed-{i}", recent_frequency=freq, count=1)
            assert picks[0]["id"] == "Pose_5"
