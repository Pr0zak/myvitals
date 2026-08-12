"""/query/sleep/range must label naps, and must actually manage to do it.

Clients counted every session as a night, so an afternoon doze became a
"night" in the stage-breakdown title and dragged the nightly average down.
The classification already existed for narrative cards; this exposes it.

The second test exists because the helper swallows exceptions and degrades to
"sleep" — a missing import would have made it return "sleep" for everything,
silently, which is indistinguishable from the bug it was meant to fix.
"""
from datetime import datetime, timezone

from myvitals.api import query as q


def test_helper_classifies_a_nap_and_a_night():
    # 1pm start, 45 minutes -> nap.
    nap = q._classify(datetime(2026, 8, 11, 13, 0, tzinfo=timezone.utc), 45 * 60)
    # 10pm start, 8 hours -> night.
    night = q._classify(datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc), 8 * 3600)
    assert nap == "nap", f"expected nap, got {nap}"
    assert night == "sleep", f"expected sleep, got {night}"


def test_helper_is_not_silently_degrading():
    """It must not return the fallback for EVERY input."""
    results = {
        q._classify(datetime(2026, 8, 11, h, 0, tzinfo=timezone.utc), secs)
        for h, secs in ((13, 45 * 60), (22, 8 * 3600), (14, 30 * 60))
    }
    assert len(results) > 1, (
        "_classify returned the same label for a nap and a full night — the "
        "fallback is swallowing a real error (a missing import, most likely)"
    )
