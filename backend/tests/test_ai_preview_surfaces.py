"""SA-O1: the AI "Preview payload" button must be able to show every
payload the app actually sends, not just the weekly summary.

Before this, `/ai/preview-payload` only ever ran `build_summary_payload`
for "week" — the web button hard-coded that call and forwarded nothing
else, so the "see exactly what gets sent" claim in Settings covered 1 of
the 15 payload builders in `claude.py`. `ai_summaries` in production shows
14 of 24 cached real results came from the other 14 range kinds, so the
un-previewable builders are the majority of actual use, not a
theoretical tail.

Two things this file locks down:

1. A drift guard — parses `claude.py` for every `build_*_payload`
   function and asserts `ai.PREVIEW_SURFACES` has a key for each one, by
   the same mechanical name rule the dispatcher uses. This is the actual
   generalizable lesson: a sixteenth builder that ships with no preview
   entry is exactly how this regressed once already (there were 2
   reachable of 15, not by design — nobody built the picker, the
   hard-coded "week" call just happened to exist).
2. Dispatch-correctness — the fix's whole point is that the preview must
   render the REAL payload the builder produces, not a reconstruction
   that could drift from it. Each surface's stub-returned sentinel is
   asserted to come back unchanged from `preview_payload`, which proves
   delegation rather than restating the shape.

No real DB: builders are monkeypatched to sentinel stubs so this tests
the endpoint's own dispatch, not the builders themselves (those get their
own tests elsewhere, e.g. test_ai_privacy.py, test_ai_nudge_gating.py).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from myvitals.api import ai

CLAUDE_PY = (
    Path(__file__).resolve().parents[1]
    / "src" / "myvitals" / "integrations" / "claude.py"
)

BUILDER_RE = re.compile(r"^async def (build_\w+_payload)\(", re.MULTILINE)


def _expected_surface_names() -> set[str]:
    source = CLAUDE_PY.read_text()
    names = BUILDER_RE.findall(source)
    assert names, "regex found no build_*_payload functions — did claude.py move?"
    return {n[len("build_"):-len("_payload")] for n in names}


def test_the_source_this_guard_reads_still_exists():
    """A guard whose input silently moved would pass on an empty read."""
    assert CLAUDE_PY.is_file(), f"missing {CLAUDE_PY}"


def test_every_payload_builder_has_a_preview_surface():
    """Fails the moment a 16th build_*_payload ships with no preview key —
    the exact shape of the SA-O1 regression."""
    expected = _expected_surface_names()
    missing = expected - set(ai.PREVIEW_SURFACES)
    assert not missing, (
        f"claude.py defines build_*_payload builders with no preview "
        f"surface: {sorted(missing)} — add a PREVIEW_SURFACES entry (and "
        f"wire it in preview_payload) so the privacy-preview button can "
        f"still show 'exactly what gets sent'."
    )


def test_preview_surfaces_names_only_real_builders_or_named_photo_endpoints():
    """The inverse direction: a stale key naming a builder that no longer
    exists would silently preview nothing (a 400 the user can't explain)."""
    expected = _expected_surface_names()
    photo_only = {"meals_identify", "meals_read_label"}
    extra = set(ai.PREVIEW_SURFACES) - expected - photo_only
    assert not extra, f"PREVIEW_SURFACES has stale/unknown keys: {sorted(extra)}"


def test_photo_surfaces_are_named_and_explained():
    """The two upload endpoints are not payload builders and cannot be
    dispatched — they must still appear, described as photo uploads."""
    for key in ("meals_identify", "meals_read_label"):
        assert key in ai.PREVIEW_SURFACES


# ─────────────── Dispatch correctness ───────────────

class _Result:
    def __init__(self, one=None):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _FakeDB:
    """Raises if queried — the surfaces under test here should never touch
    the DB directly; they delegate to a monkeypatched builder stub."""

    async def execute(self, *a, **k):
        raise AssertionError("preview_payload queried the DB directly for this surface")


SENTINEL = object()


async def _stub_builder(*_a, **_k):
    return SENTINEL


@pytest.mark.parametrize("surface,kwargs", [
    ("summary", {"range": "week"}),
    ("summary", {"range": "month"}),
    ("topic", {"topic": "sleep"}),
    ("topic", {"topic": "recovery"}),
    ("topic", {"topic": "sober"}),
    ("topic", {"topic": "anomaly"}),
    ("verdict", {}),
    ("ask", {}),
    ("ask", {"question": "how am I doing?"}),
    ("deload", {}),
    ("cardio_coach", {}),
    ("sleep_coach", {}),
    ("recovery_coach", {}),
    ("fasting_coach", {}),
    ("workout_coach", {}),
    ("meal_suggestion", {}),
    ("prep_plan", {}),
    ("strength_review", {"workout_id": 7}),
])
async def test_surface_delegates_to_the_real_builder(monkeypatch, surface, kwargs):
    """Every builder-backed surface must return exactly what the builder
    produced — proving delegation, not a hand-rolled reconstruction that
    could drift from the real payload."""
    builder_name = f"build_{surface}_payload"
    monkeypatch.setattr(ai, builder_name, _stub_builder)
    out = await ai.preview_payload(surface=surface, db=_FakeDB(), **kwargs)
    assert out is SENTINEL


async def test_focus_cue_and_nudge_delegate_given_an_explicit_workout_id(monkeypatch):
    """These two also consult the equipment/catalog context before calling
    the builder — patched out here so this stays a dispatch test, not a
    retest of selectable_catalog_ids (covered in test_ai_nudge_gating.py)."""
    from myvitals.analytics import strength as strength_algo
    from myvitals.api.workout import strength as strength_api

    async def _fake_equipment(_db):
        return {"exercise_prefs": {}}

    monkeypatch.setattr(strength_api, "_equipment_payload", _fake_equipment)
    monkeypatch.setattr(strength_algo, "selectable_catalog_ids", lambda *a, **k: set())
    monkeypatch.setattr(ai, "build_focus_cue_payload", _stub_builder)
    monkeypatch.setattr(ai, "build_strength_nudge_payload", _stub_builder)

    out = await ai.preview_payload(surface="focus_cue", workout_id=7, db=_FakeDB())
    assert out is SENTINEL

    out = await ai.preview_payload(surface="strength_nudge", workout_id=7, db=_FakeDB())
    assert out is SENTINEL


async def test_workout_surface_defaults_to_the_latest_workout(monkeypatch):
    """No workout_id given → looks up the most recent one rather than
    forcing the user to go find and paste an id."""
    captured = {}

    async def _capture(db, wid):
        captured["wid"] = wid
        return SENTINEL

    async def _fake_latest(_db):
        return 42

    monkeypatch.setattr(ai, "build_strength_review_payload", _capture)
    monkeypatch.setattr(ai, "_latest_workout_id", _fake_latest)

    out = await ai.preview_payload(surface="strength_review", db=_FakeDB())
    assert out is SENTINEL
    assert captured["wid"] == 42


async def test_workout_surface_with_no_workouts_returns_a_note_not_an_error(monkeypatch):
    """A brand-new install with zero workouts must not 500 or 400 the
    whole Settings page — it should say why there's nothing to show."""
    async def _fake_latest(_db):
        return None

    monkeypatch.setattr(ai, "_latest_workout_id", _fake_latest)

    out = await ai.preview_payload(surface="strength_review", db=_FakeDB())
    assert out["is_payload"] is False
    assert "no strength workouts" in out["note"].lower()


async def test_photo_surfaces_return_a_note_and_touch_no_builder():
    for surface in ("meals_identify", "meals_read_label"):
        out = await ai.preview_payload(surface=surface, db=_FakeDB())
        assert out["is_payload"] is False
        assert "photo" in out["note"].lower()
        assert "never stored" in out["note"].lower()


async def test_unknown_surface_is_a_400_naming_the_valid_choices():
    with pytest.raises(HTTPException) as exc_info:
        await ai.preview_payload(surface="not-a-real-surface", db=_FakeDB())
    assert exc_info.value.status_code == 400
    assert "summary" in exc_info.value.detail


async def test_bad_range_and_topic_still_400_as_before():
    with pytest.raises(HTTPException) as exc_info:
        await ai.preview_payload(surface="summary", range="year", db=_FakeDB())
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await ai.preview_payload(surface="topic", topic="not-a-topic", db=_FakeDB())
    assert exc_info.value.status_code == 400


async def test_default_call_shape_is_unchanged():
    """Nothing passes `surface` yet outside this fix, so the bare call
    (as the old endpoint signature was always invoked) must still resolve
    to the old behaviour: summary/week."""
    monkeypatch_target = "build_summary_payload"
    calls = []

    async def _capture(db, range_kind):
        calls.append(range_kind)
        return SENTINEL

    orig = getattr(ai, monkeypatch_target)
    setattr(ai, monkeypatch_target, _capture)
    try:
        out = await ai.preview_payload(db=_FakeDB())
    finally:
        setattr(ai, monkeypatch_target, orig)
    assert out is SENTINEL
    assert calls == ["week"]
