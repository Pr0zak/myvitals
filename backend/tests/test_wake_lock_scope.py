"""The screen stays on for a workout, not for a screen — OG2-A8.

Two faults, one on each surface, and they point in opposite directions.

**The web had no wake lock at all.** A grep for `wakeLock` across
`frontend/src` returned nothing, so the browser slept between sets and the
phone had to be unlocked to log the next one. The Compose app has held the
screen since it shipped, which made this a parity gap nobody had written
down: the same session behaved differently depending on which surface it ran
on.

**The phone held it too eagerly.** The comment said "during the active
workout" and the code said `DisposableEffect(Unit)` — keyed to the
composable, not to the workout — so the flag went up whenever that screen was
on top. Reading a rest-day plan, or a session finished an hour ago, pinned
the display awake for no session at all.

openGym documents the browser half, and it is the part that looks like it
works and does not: **the browser releases the lock on its own whenever the
document stops being visible.** A one-shot `request()` therefore succeeds
once and then dies silently, which is indistinguishable from never having
worked. The intent has to be held separately and the lock re-acquired on
every `visibilitychange`.

Both surfaces now release on `paused`. WP-14 pause means the user has stepped
away, which is the one moment during a session when the screen should be
allowed to sleep.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
HELPER = REPO / "frontend" / "src" / "wakeLock.ts"
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)


class TestTheWebHoldsTheScreen:
    def test_the_helper_exists(self):
        assert HELPER.exists(), "the web wake lock is gone again"

    def test_it_re_acquires_on_visibility_change(self):
        """The whole reason this is a module and not four lines inline.

        The browser drops the lock every time the document hides, so a
        one-shot request works exactly once and then fails silently.
        """
        src = HELPER.read_text()
        assert "visibilitychange" in src
        assert "wanted" in src, "the intent must outlive the lock itself"

    def test_it_does_not_ask_while_hidden(self):
        """`request()` rejects outright on a hidden document."""
        assert 'document.visibilityState !== "visible"' in HELPER.read_text()

    def test_concurrent_requests_cannot_stack_two_locks(self):
        """Two quick calls would take two locks and one release would leave
        the screen pinned on with nothing holding a handle to it."""
        assert "pending" in HELPER.read_text()

    def test_a_release_during_an_in_flight_request_is_honoured(self):
        """The await window is real: a workout can finish inside it, and the
        lock that arrives afterwards has nothing left to release it."""
        src = HELPER.read_text()
        acquired = src[src.index("navigator.wakeLock.request"):]
        assert "if (!wanted)" in acquired

    def test_refusals_are_swallowed(self):
        """iOS declines in Low Power Mode and some browsers decline on a low
        battery. There is nothing the user could act on, so it stays quiet
        and tries again next time the document becomes visible.
        """
        assert "catch {" in HELPER.read_text()


class TestBothSurfacesKeyOnTheWorkout:
    def test_the_web_keys_on_the_running_status(self):
        src = WEB.read_text()
        assert "workoutRunning" in src
        assert 'workout.value?.status === "in_progress"' in src

    def test_the_web_releases_on_unmount(self):
        """Leaving the screen with the intent still set would hold the lock
        with nothing left to clear it."""
        assert "onUnmounted(releaseWakeLock)" in WEB.read_text()

    def test_the_phone_no_longer_keys_on_the_composable(self):
        """`DisposableEffect(Unit)` is the bug, stated exactly.

        Mounted is the easy key and the wrong one: it pins the display awake
        while the user reads a plan for a day they are not training.
        """
        src = PHONE.read_text()
        assert not re.search(
            r"DisposableEffect\(Unit\)\s*\{\s*val activity", src,
        ), "the phone wake lock is keyed to the composable again"
        assert "DisposableEffect(workout?.status)" in src

    def test_the_phone_checks_the_status_before_setting_the_flag(self):
        """Re-keying alone is not enough — the effect still runs for every
        status, so the body has to ask."""
        src = PHONE.read_text()
        assert 'val running = workout?.status == "in_progress"' in src
        assert "if (running)" in src

    def test_neither_surface_holds_it_while_paused(self):
        """WP-14 pause is the user stepping away. Both surfaces test for
        `in_progress` specifically rather than for "not completed", so
        `paused` releases without either needing a separate branch.
        """
        web = WEB.read_text()
        web_block = web[web.index("const workoutRunning"):]
        web_block = web_block[:web_block.index("onUnmounted(releaseWakeLock)")]
        assert '"in_progress"' in web_block
        assert "completed" not in web_block

        phone = PHONE.read_text()
        phone_block = phone[phone.index("DisposableEffect(workout?.status)"):]
        phone_block = phone_block[:phone_block.index("FLAG_KEEP_SCREEN_ON")]
        assert '"in_progress"' in phone_block
        assert "completed" not in phone_block


class TestTheRemainingLeakIsRecorded:
    def test_the_navigate_away_case_is_documented_not_silently_left(self):
        """Navigating to Charts mid-session disposes the effect.

        Holding the flag past dispose is worse — a user who navigates away
        and never returns leaves the display pinned on. Fixing it properly
        means owning the flag above the NavHost. The comment says so, because
        an undocumented known gap reads as an oversight to the next person.
        """
        src = PHONE.read_text()
        assert "Known and not fixed here" in src
        assert "NavHost" in src
