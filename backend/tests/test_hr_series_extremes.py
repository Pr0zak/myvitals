"""Bucketed HR series must report RAW extremes, not bucket-average extremes.

A short sprint inside a bucket disappears into that bucket's mean, so taking
min/max from the returned points understates the peak — which made the HR
detail card disagree with the Activities feed's per-activity max_hr for the
same session.
"""
import ast
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "src" / "myvitals" / "api" / "query.py")


def _hr_func() -> ast.AST:
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "heart" in node.name.lower() and "rate" in node.name.lower():
                return node
    raise AssertionError("heart-rate series endpoint not found in query.py")


def test_bucketed_branch_aggregates_raw_rows():
    """The bucketed path must run its own aggregate over vitals_heartrate."""
    fn = _hr_func()
    src = ast.get_source_segment(SRC.read_text(), fn) or ""
    assert "min(bpm)" in src and "max(bpm)" in src, (
        "bucketed HR series still derives min/max from the bucketed points; "
        "those are per-bucket averages and understate the real peak"
    )


def test_extremes_not_taken_from_points_unconditionally():
    """`min(values)`/`max(values)` must not be the final answer when bucketing."""
    fn = _hr_func()
    src = ast.get_source_segment(SRC.read_text(), fn) or ""
    # The response must be built from the stats variables, not straight from
    # the point list.
    assert "min_bpm=min(values)" not in src.replace(" ", ""), (
        "HeartRateSeries.min_bpm is wired straight to the bucketed points"
    )
    assert "max_bpm=max(values)" not in src.replace(" ", ""), (
        "HeartRateSeries.max_bpm is wired straight to the bucketed points"
    )
