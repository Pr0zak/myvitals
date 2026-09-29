"""Suggested trails for the link picker: nearest approach of the route."""
from types import SimpleNamespace

import polyline

from myvitals.api.trails import _activity_track, rank_trails_near_track


def _trail(id_, lat, lon):
    return SimpleNamespace(id=id_, name=f"t{id_}", latitude=lat, longitude=lon)


def test_nearest_first_and_capped():
    track = [(35.0, -97.0), (35.01, -97.0)]
    trails = [_trail(1, 35.05, -97.0), _trail(2, 35.011, -97.0),
              _trail(3, 35.03, -97.0), _trail(4, 35.02, -97.0)]
    ranked = rank_trails_near_track(track, trails, limit=3)
    assert [t.id for t, _ in ranked] == [2, 4, 3]


def test_closest_approach_not_start_point():
    # Starts ~11 km away (home), ends at the trail: still suggested.
    track = [(35.1, -97.0), (35.05, -97.0), (35.0005, -97.0)]
    ranked = rank_trails_near_track(track, [_trail(1, 35.0, -97.0)])
    assert ranked and ranked[0][1] < 0.1


def test_far_or_unpinned_trails_excluded():
    track = [(35.0, -97.0)]
    trails = [_trail(1, 36.0, -97.0), _trail(2, None, None)]
    assert rank_trails_near_track(track, trails) == []


def test_no_gps_is_empty_not_error():
    act = SimpleNamespace(polyline=None, polyline_simple=None)
    assert _activity_track(act) == []
    assert rank_trails_near_track([], [_trail(1, 35.0, -97.0)]) == []


def test_track_falls_back_to_simplified_polyline():
    act = SimpleNamespace(polyline=None, polyline_simple=polyline.encode([(35.0, -97.0)]))
    assert _activity_track(act) == [(35.0, -97.0)]
