import polyline

from myvitals.analytics.geo import (
    primary_bounds,
    DEFAULT_MAX_POINTS,
    bounds_of,
    rdp,
    simplify_encoded,
)


def test_rdp_keeps_endpoints():
    pts = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
    out = rdp(pts, epsilon=1e-4)
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


def test_rdp_drops_collinear_interior_points():
    # A dead-straight line: every interior point is redundant.
    pts = [(0.0, i / 100.0) for i in range(50)]
    assert rdp(pts, epsilon=1e-4) == [pts[0], pts[-1]]


def test_rdp_keeps_a_real_corner():
    # Right-angle turn — the corner is far off the start-end chord and
    # must survive.
    pts = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    out = rdp(pts, epsilon=1e-4)
    assert (0.0, 1.0) in out


def test_rdp_short_tracks_pass_through():
    assert rdp([], 1e-4) == []
    assert rdp([(1.0, 2.0)], 1e-4) == [(1.0, 2.0)]
    two = [(1.0, 2.0), (3.0, 4.0)]
    assert rdp(two, 1e-4) == two


def test_rdp_handles_long_track_without_recursion_error():
    # Zig-zag that defeats simplification — the iterative implementation
    # must not blow the stack the recursive one would.
    pts = [(0.001 * (i % 2), i / 1000.0) for i in range(6000)]
    out = rdp(pts, epsilon=1e-9)
    assert len(out) > 1000


def test_simplify_encoded_round_trips_and_shrinks():
    pts = [(39.0 + i / 10000.0, -94.0) for i in range(500)]
    encoded = polyline.encode(pts)
    out, n_src, n_simp = simplify_encoded(encoded)
    assert n_src == 500
    # A straight line collapses hard.
    assert n_simp < 10
    assert len(polyline.decode(out)) == n_simp


def test_simplify_encoded_caps_at_max_points():
    pts = [(39.0 + (i % 2) * 0.01, -94.0 + i / 1000.0) for i in range(3000)]
    encoded = polyline.encode(pts)
    _, _, n_simp = simplify_encoded(encoded, epsilon=0.0)
    assert n_simp <= DEFAULT_MAX_POINTS


def test_simplify_encoded_tolerates_garbage():
    # One corrupt row must not take down the whole map response.
    assert simplify_encoded("") == ("", 0, 0)
    assert simplify_encoded("!!!not-a-polyline!!!")[2] <= 2


def test_bounds_of():
    assert bounds_of([]) is None
    assert bounds_of([(1.0, 2.0), (3.0, -4.0)]) == [1.0, -4.0, 3.0, 2.0]


# ── primary_bounds ────────────────────────────────────────────────────

# Three rides around one metro plus one holiday ride far away — the case
# that made the real map open zoomed out to the whole continent.
LOCAL = [
    [(39.10, -94.60), (39.12, -94.58)],
    [(39.05, -94.65), (39.07, -94.63)],
    [(39.15, -94.55), (39.17, -94.52)],
]
FARAWAY = [[(34.05, -118.24), (34.07, -118.22)]]


def test_primary_bounds_excludes_the_outlier_with_home():
    b = primary_bounds(LOCAL + FARAWAY, home=(39.1, -94.6))
    assert b is not None
    # Never reaches Los Angeles.
    assert b[1] > -95.0
    assert b[3] < -94.0


def test_primary_bounds_excludes_the_outlier_without_home():
    # Densest-cell fallback must reach the same conclusion unaided.
    b = primary_bounds(LOCAL + FARAWAY)
    assert b is not None
    assert b[1] > -95.0
    assert b[3] < -94.0


def test_primary_bounds_falls_back_to_full_extent_when_home_is_remote():
    # Home nowhere near any track: better to show everything than nothing.
    b = primary_bounds(LOCAL, home=(-33.87, 151.21))
    assert b == bounds_of([p for t in LOCAL for p in t])


def test_primary_bounds_empty():
    assert primary_bounds([]) is None


def test_primary_bounds_single_track():
    b = primary_bounds([LOCAL[0]])
    assert b == bounds_of(LOCAL[0])
