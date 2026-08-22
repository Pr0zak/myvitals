"""PUT /profile must not erase keys the caller does not model.

`put_profile` assigned `p.extra = body.extra` wholesale. The phone's
`ProfileExtra` data class models six keys, so toggling the workout
reminder there deleted every other key in `extra` — including the
`display` block (units / time format / theme) added in v0.11.1 and
`fasting_prefs`.

The phone's `saveReminderPrefs` already re-copies `steps_goal`,
`sleep_goal_h`, `vitals_order` and `vitals_hidden` by hand, which is a
client-side workaround for a server bug rather than a fix — and it only
covers the four keys that existed when it was written.
"""

from __future__ import annotations

import inspect

from myvitals.api import profile as prof


class TestMergeSemantics:
    @staticmethod
    def _code_only(src: str) -> str:
        """Source with comment lines stripped.

        The docstring and comments in put_profile quote the old
        `p.extra = body.extra` line to explain why it changed, so a naive
        substring search matches the prose rather than the code.
        """
        return "\n".join(
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        )

    def test_extra_is_merged_not_replaced(self):
        code = self._code_only(inspect.getsource(prof.put_profile))
        assert "p.extra = body.extra" not in code, (
            "wholesale replace lets any client erase keys it does not model"
        )
        assert "merged.update(body.extra)" in code

    def test_the_stored_value_is_the_base_and_incoming_wins(self):
        """Order matters: incoming keys must override stored ones, not the
        reverse, or a client could never change anything."""
        src = inspect.getsource(prof.put_profile)
        base = src.index("merged = dict(p.extra or {})")
        upd = src.index("merged.update(body.extra)")
        assert base < upd

    def test_a_null_extra_leaves_the_stored_block_alone(self):
        """Sending no `extra` at all must not wipe it.

        A client updating only `height_cm` has no reason to send the
        preference block, and should not have to.
        """
        src = inspect.getsource(prof.put_profile)
        assert "if body.extra is not None:" in src

    def test_reassignment_not_in_place_mutation(self):
        """SQLAlchemy does not track in-place mutation of a JSON column, so
        mutating `p.extra` directly would commit nothing."""
        src = inspect.getsource(prof.put_profile)
        assert "p.extra = merged" in src


class TestClearingStillWorks:
    def test_nulls_are_written_through_rather_than_skipped(self):
        """Under a merge, absence means keep — so clearing needs a null.

        If nulls were filtered out of the patch, clearing a goal would
        become impossible and the field would be write-once.
        """
        src = inspect.getsource(prof.put_profile)
        # A skip would look like a comprehension filtering None out of
        # body.extra before the update. There must not be one.
        assert "if v is not None" not in src.split("merged = dict")[1].split("p.extra = merged")[0]

    def test_the_web_sends_an_explicit_null_to_clear(self):
        """Settings.vue used `delete extra.steps_goal`.

        An absent key and a "full object minus one key" are
        indistinguishable on the wire, so under a merge the delete would
        silently stop clearing. The web now sends null.
        """
        from pathlib import Path
        settings_vue = (
            Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "views" / "Settings.vue"
        ).read_text()
        assert "delete extra.steps_goal" not in settings_vue
        assert "delete extra.sleep_goal_h" not in settings_vue
        assert "extra.steps_goal =" in settings_vue

    def test_goal_sync_reads_a_null_as_cleared(self):
        """`_profile_set_target_for_kind` and the AiGoal sync read these
        with `.get(...)`, so a stored null and an absent key are the same
        downstream — which is what makes writing nulls through safe."""
        src = inspect.getsource(prof.put_profile)
        assert '(body.extra or {}).get("steps_goal")' in src
