"""OSM trails from the trailmap packs: parsing, clustering, ride matching."""
import io
import json
import zipfile

from myvitals.analytics.trail_match import match_trails
from myvitals.integrations.trailmap import parse_pack, primary_name, state_abbr, states_for


def _pack(files: dict[str, list[dict]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("meta.json", json.dumps({"schema": 2}))
        for name, els in files.items():
            z.writestr(name, json.dumps({"elements": els}))
    return buf.getvalue()


def _way(id_, name, pts, surface=None):
    tags = {"name": name}
    if surface:
        tags["surface"] = surface
    return {"type": "way", "id": id_, "tags": tags,
            "geometry": [{"lat": a, "lon": b} for a, b in pts]}


def test_primary_name_takes_first_alternative():
    assert primary_name("Gary L. Haller Trail;Mill Creek Trail") == "Gary L. Haller Trail"
    assert primary_name("  ") is None and primary_name(None) is None


def test_same_name_far_apart_is_two_trails_near_is_one():
    rows = parse_pack(_pack({"all/a.json": [
        _way(1, "Nature Trail", [(39.0, -94.8), (39.001, -94.8)]),
        _way(2, "Nature Trail", [(39.002, -94.8), (39.003, -94.8)]),      # ~100 m on
        _way(3, "Nature Trail", [(38.0, -97.0), (38.001, -97.0)]),         # 250 km away
    ]}))
    nature = sorted((r for r in rows if r["name"] == "Nature Trail"), key=lambda r: r["min_lat"])
    assert [len(r["paths"]) for r in nature] == [1, 2]
    assert len({r["key"] for r in nature}) == 2


def test_way_in_two_tiles_counted_once_and_mtb_wins_kind():
    w = _way(7, "Rock Loop", [(39.0, -94.8), (39.001, -94.8)], "dirt")
    rows = parse_pack(_pack({"mtb/a.json": [w], "all/b.json": [w],
                             "parks/c.json": [_way(9, "Some Park", [(39, -94), (39.1, -94)])]}))
    assert len(rows) == 1
    assert rows[0]["kind"] == "mtb" and rows[0]["surface"] == "dirt" and len(rows[0]["paths"]) == 1


def test_unnamed_and_degenerate_ways_dropped():
    rows = parse_pack(_pack({"all/a.json": [
        {"type": "way", "id": 1, "tags": {}, "geometry": [{"lat": 1, "lon": 1}, {"lat": 2, "lon": 2}]},
        _way(2, "Stub", [(39.0, -94.8)]),
    ]}))
    assert rows == []


def test_states_for_uses_bbox():
    idx = {"states": [{"slug": "kansas", "bbox": [-102.1, 36.9, -94.5, 40.1]},
                      {"slug": "texas", "bbox": [-106.7, 25.8, -93.5, 36.6]}]}
    assert [s["slug"] for s in states_for(idx, [(38.95, -94.75)])] == ["kansas"]
    assert state_abbr("kansas") == "KS" and state_abbr("new-york") == "NY"


# A straight north-south greenway, and a ride that follows it for ~1.1 km,
# then crosses a short east-west connector.
GREENWAY = [(39.000 + i * 0.001, -94.800) for i in range(20)]
CONNECTOR = [(39.0105, -94.8005), (39.0105, -94.7995)]


def test_ridden_trail_ranks_by_distance_along_it_not_closest_approach():
    ride = [(39.000 + i * 0.0005, -94.80008) for i in range(22)]  # ~7 m off, 1.17 km
    ms = match_trails(ride, [(1, [GREENWAY]), (2, [CONNECTOR])])
    assert [m.key for m in ms] == [1]           # connector crossed, not ridden
    assert 1000 < ms[0].on_trail_m < 1300
    assert ms[0].closest_m < 15


def test_parallel_street_a_block_away_is_not_the_trail():
    street = [(39.000 + i * 0.001, -94.8012) for i in range(20)]  # ~104 m east
    ride = [(39.000 + i * 0.0005, -94.8012) for i in range(30)]
    assert match_trails(ride, [(1, [GREENWAY])]) == []
    assert match_trails(ride, [(1, [street])])[0].key == 1


def test_sparse_vertices_still_match_via_segments():
    # A long straight segment with vertices 1.1 km apart: point-to-vertex
    # would miss the middle of the ride; point-to-segment must not.
    line = [(39.0, -94.8), (39.01, -94.8)]
    ride = [(39.002 + i * 0.0005, -94.8001) for i in range(10)]
    assert match_trails(ride, [(1, [line])])[0].on_trail_m > 400


def test_empty_inputs():
    assert match_trails([], [(1, [GREENWAY])]) == []
    assert match_trails([(39.0, -94.8), (39.01, -94.8)], []) == []
