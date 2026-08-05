"""ADAPT-1 — need-based split selection."""
from myvitals.analytics.strength import (
    MUSCLE_VOLUME_TARGETS,
    muscle_need,
    muscles_for_focus,
    score_focus,
    select_split,
    select_split_adaptive,
)


def _vol(**sets: float) -> dict[str, dict]:
    """Volume map with every muscle at MEV unless overridden."""
    out = {}
    for m, (mev, mav) in MUSCLE_VOLUME_TARGETS.items():
        out[m] = {"sets": sets.get(m, mev), "mev": mev, "mav": mav}
    return out


def _rest(default: float = 3.0, **days: float) -> dict[str, float]:
    return {m: days.get(m, default) for m in MUSCLE_VOLUME_TARGETS}


# ── muscle_need ───────────────────────────────────────────────────────

def test_muscle_need_is_continuous_at_the_landmarks():
    # 1.0 at MEV, 0.0 at MAV — no cliff for the pick to jitter across.
    assert muscle_need(10, 10, 20) == 1.0
    assert muscle_need(20, 10, 20) == 0.0


def test_muscle_need_rises_below_mev_and_goes_negative_above_mav():
    assert muscle_need(5, 10, 20) > 1.0
    assert muscle_need(0, 10, 20) > muscle_need(5, 10, 20)
    assert muscle_need(30, 10, 20) < 0
    assert muscle_need(40, 10, 20) < muscle_need(30, 10, 20)


def test_muscle_need_is_monotonic():
    prev = muscle_need(0, 10, 20)
    for s in range(1, 40):
        cur = muscle_need(s, 10, 20)
        assert cur <= prev
        prev = cur


def test_muscle_need_handles_degenerate_targets():
    assert muscle_need(5, 0, 0) == 0.0
    assert muscle_need(5, 10, 10) == 0.0


# ── muscles_for_focus ─────────────────────────────────────────────────

def test_muscles_for_focus_derives_from_split_slots():
    assert "chest" in muscles_for_focus("push")
    assert "lats" in muscles_for_focus("pull")
    assert "quadriceps" in muscles_for_focus("legs")
    # Push must not claim leg muscles, or the scorer is meaningless.
    assert not muscles_for_focus("push") & {"quadriceps", "hamstrings", "calves"}


def test_muscles_for_focus_unknown_is_empty():
    assert muscles_for_focus("nonsense") == set()


# ── the real-world case that motivated this ───────────────────────────

def test_over_mav_push_loses_to_rested_legs():
    """The exact failure this replaces: shoulders/chest/triceps far above
    MAV while the rotation kept prescribing push."""
    volume = _vol(shoulders=41, chest=26, triceps=23, biceps=20,
                  quadriceps=4, hamstrings=4, glutes=4, calves=2)
    rest = _rest(default=1.0, quadriceps=12, hamstrings=12,
                 glutes=12, calves=12, abdominals=12)
    focus, scores = select_split_adaptive(6, "adaptive", volume, rest, None)
    assert focus == "legs"
    assert scores["legs"] > scores["push"]


def test_skipping_does_not_lock_the_schedule():
    """Rotation state is irrelevant — only need matters. Repeatedly
    skipping push can no longer park the plan on push."""
    volume = _vol(shoulders=41, chest=26, triceps=23,
                  quadriceps=4, hamstrings=4, glutes=4)
    rest = _rest(default=1.0, quadriceps=10, hamstrings=10, glutes=10)
    for last in (None, "push", "pull", "legs"):
        focus, _ = select_split_adaptive(6, "adaptive", volume, rest, last)
        assert focus != "push"


def test_never_repeats_the_previous_focus():
    # One session barely moves a 7-day total, so without this guard the
    # deepest deficit would win several days running.
    volume = _vol(quadriceps=0, hamstrings=0, glutes=0, calves=0)
    rest = _rest(default=9.0)
    focus, _ = select_split_adaptive(6, "adaptive", volume, rest, "legs")
    assert focus != "legs"


def test_untrained_muscles_win_over_merely_rested_ones():
    volume = _vol(back=0, lats=0, biceps=0)
    rest = _rest(default=2.0, back=20, lats=20, biceps=20)
    focus, _ = select_split_adaptive(6, "adaptive", volume, rest, None)
    assert focus == "pull"


def test_recency_breaks_a_volume_tie():
    # All muscles identically at MEV → only rest days differ.
    volume = _vol()
    rest = _rest(default=1.0, quadriceps=7, hamstrings=7, glutes=7,
                 calves=7, abdominals=7, lower_back=7)
    focus, _ = select_split_adaptive(6, "adaptive", volume, rest, None)
    assert focus == "legs"


# ── candidate family resolution ───────────────────────────────────────

def test_adaptive_respects_the_days_per_week_family():
    volume, rest = _vol(), _rest()
    assert select_split_adaptive(3, "adaptive", volume, rest, None)[0] == "full_body"
    assert select_split_adaptive(4, "adaptive", volume, rest, None)[1].keys() == {
        "upper", "lower",
    }
    assert select_split_adaptive(6, "adaptive", volume, rest, None)[1].keys() == {
        "push", "pull", "legs",
    }


def test_explicit_family_is_not_overridden():
    _, scores = select_split_adaptive(6, "upper_lower", _vol(), _rest(), None)
    assert scores.keys() == {"upper", "lower"}


def test_select_split_still_rotates_for_adaptive_callers():
    # The week-ahead strip can only project; it must get the right family
    # rather than collapsing to full_body.
    assert select_split(6, "adaptive", "push") == "pull"
    assert select_split(6, "adaptive", "pull") == "legs"
    assert select_split(6, "adaptive", "legs") == "push"


def test_rotation_modes_are_untouched():
    # Default-off guarantee: nothing about the existing behaviour moves.
    assert select_split(6, "ppl", "push") == "pull"
    assert select_split(6, "auto", None) == "push"
    assert select_split(2, "auto", "full_body") == "full_body"


def test_score_focus_unknown_focus_is_zero():
    assert score_focus("nonsense", _vol(), _rest()) == 0.0
