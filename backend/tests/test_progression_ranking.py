"""The strength progression chart was ranking stretches — OG2-D-3.

`progression_by_count` keeps the eight most-performed exercises for chart
UX and had no mobility predicate, while OG2-C1 had already taught
`is_mobility` to exclude cool-down poses from BOTH muscle readers, for the
reason that a pose is not the training being measured.

The chart is where that omission is most visible, because the eight slots are
scarce and the competition is on session count — which the generator drives
up by appending the same two-pose cool-down to every strength day. Measured
on this database over 90 days: Bridge Pose ranked 4th and Downward-Facing Dog
6th, with Child's Pose and Happy Baby immediately behind. A quarter of a
chart titled for strength progression described stretching, and the appended
cool-down keeps feeding more in.

Two decisions inside the fix.

**It is a ranking fix, not a data fix.** The points are still built for every
performed set, so a mobility surface can read them later without re-deriving
anything. Only the strength chart's shortlist declines to spend a slot on
one. Dropping the points outright would have been the larger change and would
have thrown away the one history a hold time actually progresses along.

**The predicate is `is_mobility`, not a name match.** "Butt Lift (Bridge)" is
a bodyweight strength exercise and "Bridge Pose" is a yoga pose; they differ
by `movement_pattern`, not by anything in the name. A name heuristic would
have deleted a real lift from the user's own chart — the first exercise now
sitting in the freed slots.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import is_mobility
from myvitals.api.workout import strength as api


class TestTheRankerExcludesMobility:
    def test_the_rank_site_applies_the_predicate(self):
        src = inspect.getsource(api.strength_stats)
        block = src[src.index("progression_by_count = sorted("):]
        assert "is_mobility" in block[:400]

    def test_it_reuses_c1s_helper_rather_than_a_second_copy(self):
        """Two copies of "is this a stretch" is how the two muscle readers
        would have drifted, which is the fault the C1 pass ended."""
        src = inspect.getsource(api.strength_stats)
        block = src[src.index("progression_by_count = sorted("):]
        assert "movement_pattern" not in block[:400]

    def test_the_shortlist_is_still_capped_at_eight(self):
        src = inspect.getsource(api.strength_stats)
        block = src[src.index("progression_by_count = sorted("):]
        assert "[:8]" in block[:600]


class TestThePredicateSeparatesTheLookalikes:
    """The concrete reason a name match would have been wrong."""

    def test_the_yoga_pose_is_mobility(self):
        assert is_mobility("Bridge_Pose") is True

    def test_the_bodyweight_lift_of_almost_the_same_name_is_not(self):
        """It ranks 6th on the corrected chart — a name heuristic would have
        deleted a real lift from one of the slots it just freed."""
        assert is_mobility("Butt_Lift_Bridge") is False

    def test_they_differ_by_movement_pattern_not_by_name(self):
        pose = algo.CATALOG_BY_ID["Bridge_Pose"]
        lift = algo.CATALOG_BY_ID["Butt_Lift_Bridge"]
        assert (pose.get("movement_pattern") or "") == "mobility"
        assert (lift.get("movement_pattern") or "") != "mobility"
        assert "Bridge" in pose["name"] and "Bridge" in lift["name"]


class TestThePointsSurvive:
    def test_the_series_is_still_built_for_every_performed_set(self):
        """OG2-C3's ordering, unchanged: the point is built before the
        unweighted branch so a bodyweight lift can have a series at all. The
        exclusion happens at the shortlist, downstream of that."""
        src = inspect.getsource(api.strength_stats)
        assert src.index("progression.setdefault") < src.index("SET_UNWEIGHTED")
        assert src.index("progression.setdefault") < src.index(
            "progression_by_count = sorted(")
