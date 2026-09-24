"""The phone's route card must not hide behind a map drawn from a trail pin.

SA-P3 shipped the "Fetch route from Health Connect" button as the `else` of the
branch that renders the activity map. That branch is true when the activity has
a polyline OR when it is linked to a trail that has coordinates — and a trail
link gives the activity a PIN, not a track. The 2026-09-19 walk is linked to
trail 13, so the map rendered from the trail alone, the `else` never ran, and
the one affordance that could fetch the GPS track was unreachable on the only
surface that can request it. The user reported exactly that: no button.

The web half never had the bug, because `ActivityDetail.vue` gates its Route
card on `activity.polyline` alone and ignores `trail_id`. That asymmetry is why
this is worth a test rather than a comment: the two surfaces must agree on when
a route is missing, and only one of them was consulting trail state.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHONE = ROOT / "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivityDetailScreen.kt"
WEB = ROOT / "frontend/src/views/ActivityDetail.vue"


def test_the_route_card_is_not_an_else_of_the_map_branch():
    src = PHONE.read_text()
    assert "RouteMissingCard(" in src, "the route card is gone from the phone"
    # Find the guard immediately preceding the route card's call site. Since
    # UI-5 the stateless Content renders it through the `routeMissing` slot
    # (the wrapper binds that slot to RouteMissingCard).
    assert "RouteMissingCard(a = a" in src, "the route slot no longer draws RouteMissingCard"
    before = src[: src.index("routeMissing(a) }")]
    guard = before[before.rindex("if ("):]
    assert "else if" not in guard.split("\n")[0], (
        "the route card is gated by an `else if` again. It must be an "
        "independent `if`: the branch above renders a map from a trail pin as "
        "well as from a polyline, so an `else` hides the fetch button on any "
        "activity that happens to be linked to a trail."
    )
    assert "polyline.isNullOrBlank()" in guard, (
        "the route card's guard must test the polyline directly — a route is "
        "missing when there is no track, regardless of trail state"
    )
    assert "trailId" not in guard, (
        "the route card's guard must not consult trail state; a trail link is "
        "a pin, not a GPS track"
    )


def test_both_surfaces_decide_route_absence_the_same_way():
    """Neither surface may use trail state to decide a route is present."""
    web = WEB.read_text()
    # UI-5: the map is the hero, so the fallback is its own section.
    m = re.search(r'<section v-if="([^"]*healthconnect[^"]*)" class="card">', web)
    assert m, "the web Route fallback card is gone or its condition changed shape"
    assert "trail" not in m.group(1).lower(), (
        "the web Route card started consulting trail state, which is the "
        "phone's bug in the other direction"
    )
    assert "healthconnect" in m.group(1), (
        "the web fallback should still be scoped to the one source this app "
        "can go and ask"
    )
