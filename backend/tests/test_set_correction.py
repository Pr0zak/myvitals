"""A mistyped set was permanent — OG2-A9.

The web disabled every input on a logged row and `DELETE /sets/{id}` had no
caller anywhere, so a fat-fingered 225 instead of 25 stayed in the log. It
does not merely sit there: it feeds `last_target_weight_for_exercise` which
picks next session's load, it can fire a PR that becomes the all-time best,
and it enters tonnage, the muscle-volume audit and the AI payloads. It also
compounds with OG2-A1 and OG2-A2, which had just made the prescription read
that history more carefully.

Two repairs, and they are not peers.

**Correction is primary, and is a re-POST on the natural key.** `log_set` is
already an idempotent upsert on `(workout_exercise_id, set_number)` — and the
pair is UNIQUE in the database (migration 0021), so it is a real constraint
rather than an application convention. Both clients derive `set_number` from
their own render loops, so the key exists offline, before any round trip. A
correction therefore rides the replay buffer that already exists: two upserts
on one key, drained in queue order, converge on the later one. No new
endpoint, no new Room table, no new discriminator.

**Delete is secondary and online-only.** It is addressed by `set_id`, a
server surrogate, and a set logged offline has no id on the client at all —
`logSet` returns null on the buffered path. Delete is inexpressible for
exactly the sets most likely to need it, which is *why* correction is the
offline repair. Buffering one would be worse than useless: buffered workout
writes drain AFTER buffered sets at every call site, so a queued delete could
replay before the insert it was meant to remove and the set would come back.

It is still needed. Correcting a set to zero reps leaves a row
`_accounted_sets` counts, so the session reads as further along than it is,
and "this set did not happen" has no other honest expression. Marking it
`skipped` is specifically forbidden: SKIP-1 records that
`recent_mobility_history` reads a skipped set as a FAILED one and
`adjust_mobility_target` lowers the next hold prescription after two.

Nothing is stored for any of this and no migration is needed. Every number a
correction touches — PRs, progress counters, tonnage, the muscle audit — is
derived on read, so fixing the row fixes the answer with nothing to unwind.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re

from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
MIGRATION = REPO / "backend" / "alembic" / "versions" / "0021_strength_tables.py"
MODELS = REPO / "backend" / "src" / "myvitals" / "db" / "models.py"
WEB = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)
PHONE_REPO = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "strength" / "StrengthRepository.kt"
)


class TestTheNaturalKeyIsRealNotAConvention:
    def test_the_pair_is_unique_in_the_database(self):
        """The whole correction design rests on this.

        If it were only an application convention, a lost SELECT-then-INSERT
        race would produce two rows for one set number and a correction would
        update an arbitrary one of them.
        """
        src = MIGRATION.read_text()
        idx = src[src.index("ix_strength_sets_workout_exercise"):]
        idx = idx[:idx.index(")")]
        assert '"workout_exercise_id", "set_number"' in idx
        assert "unique=True" in src[src.index("ix_strength_sets_workout_exercise"):][:400]

    def test_log_set_looks_up_by_that_pair(self):
        src = inspect.getsource(api.log_set)
        assert "StrengthSet.workout_exercise_id == body.workout_exercise_id" in src
        assert "StrengthSet.set_number == body.set_number" in src


class TestACorrectionIsInferredNotFlagged:
    def test_there_is_no_is_correction_field_on_the_request(self):
        """A client cannot reliably know it is correcting.

        An online POST whose response is lost buffers and replays, and that
        replay is a RETRY the user never saw, not an edit. `existing is not
        None` is the only thing that knows, and it knows on the server where
        the answer is the same for every caller.
        """
        assert "is_correction" not in api.SetIn.model_fields

    def test_the_update_branch_sets_the_flag(self):
        src = inspect.getsource(api.log_set)
        assert "is_correction = True" in src
        assert "is_correction = False" in src


class TestWhatACorrectionMustNotTouch:
    def test_it_does_not_rewrite_the_prescription(self):
        """`target_*` records what the generator PRESCRIBED at log time.

        `actual_*` is what was done. Letting a correction restate the target
        would quietly rewrite the prescription to match the performance and
        erase the comparison the pair exists to make.
        """
        src = inspect.getsource(api.log_set)
        update = src[src.index("is_correction = True"):]
        update = update[:update.index("# Auto-advance")]
        assert "s.target_weight_lb =" not in update
        assert "s.target_reps =" not in update

    def test_it_does_not_re_stamp_when_the_set_happened(self):
        """The set happened when it happened.

        Re-stamping would move it to the moment its typo was noticed.

        Nothing currently reads `logged_at` — the last-session lookup orders
        by `StrengthWorkout.completed_at` — so this preserves a fact rather
        than preventing a live bug, and this docstring says so because an
        earlier version of it claimed otherwise. It is still the right
        default: a timestamp that silently means "when this was last edited"
        is a trap for the first consumer that assumes otherwise.
        """
        src = inspect.getsource(api.log_set)
        update = src[src.index("is_correction = True"):]
        update = update[:update.index("# Auto-advance")]
        assert "s.logged_at =" not in update

    def test_it_earns_no_rest(self):
        """There is no rest to take after fixing a typo."""
        src = inspect.getsource(api.log_set)
        assert "0 if is_correction else await _rest_after_s" in src

    def test_it_cannot_re_fire_a_pr_badge(self):
        """`_detect_pr` excludes the row being written.

        So a corrected set is compared against every OTHER set and would
        happily re-award a badge it had already fired — or fire one for the
        first time on a set logged days ago.
        """
        src = inspect.getsource(api.log_set)
        assert "not is_correction" in src
        guard = src[src.index("if not s.skipped"):]
        assert "not is_correction" in guard[:120]

    def test_it_carries_the_sets_real_classification(self):
        """`_planned_sets` hard-coded "working" for every row.

        Harmless while a logged row could not be edited, because the value
        was never sent back. Now a correction re-POSTs the whole set, so
        seeding the wrong type would silently reclassify a warm-up as working
        the moment its weight was fixed — moving it into the volume audit and
        back into next session's prescription, undoing OG2-A1 for that row.
        """
        src = inspect.getsource(api._planned_sets)
        assert "set_type = prior.set_type or set_type" in src


class TestDeleteIsTheOtherRepair:
    def test_it_returns_the_rehydrated_workout(self):
        """Not 204. Its two siblings already do this, so the caller picks up
        the recomputed progress counters in one round trip rather than
        deriving them — the client-side re-derivation SKIP-1 removed."""
        src = inspect.getsource(api.delete_set)
        assert "_hydrate_workout" in src
        route = next(
            r for r in api.router.routes
            if getattr(r, "path", "") == "/workout/strength/sets/{set_id}"
            and "DELETE" in getattr(r, "methods", set())
        )
        assert route.response_model is api.WorkoutOut

    def test_removal_is_never_expressed_as_skipped(self):
        """SKIP-1's trap, and it is silent.

        `recent_mobility_history` counts a skipped set as a FAILED one and
        `adjust_mobility_target` lowers the next hold prescription after two,
        so marking a mistyped set skipped would quietly make every future
        cool-down easier.
        """
        for src in (WEB.read_text(), PHONE.read_text()):
            assert "skipped = true" not in src.lower().replace(" ", " ")
        src = inspect.getsource(api.delete_set)
        assert "db.delete(s)" in src

    def test_surviving_sets_are_not_renumbered(self):
        """The upsert key is (workout_exercise_id, set_number).

        Renumbering would invalidate any set still sitting in a client's
        replay buffer, so a hole is a valid state — the counters count rows,
        not the highest number.
        """
        src = inspect.getsource(api.delete_set)
        assert "set_number" not in src.replace("(workout_exercise_id, set_number)", "")

    def test_the_phone_refuses_to_buffer_a_delete(self):
        """Buffered workout writes drain AFTER buffered sets at every call
        site, so a queued delete could replay before the insert it was meant
        to remove and the set would come back."""
        src = PHONE_REPO.read_text()
        block = src[src.index("suspend fun deleteSet("):]
        block = block[:block.index("suspend fun swapExercise(")]
        assert "buffer" not in block.lower() or "NOT buffered" in block
        assert "bufferSet" not in block


class TestNothingNewIsStored:
    def test_no_migration_is_needed(self):
        """Every number a correction touches is derived on read.

        PRs, the progress counters, tonnage and the muscle audit all recompute
        from live rows, so fixing the row fixes the answer with nothing to
        unwind. A stored PR or an `edited` marker would each create a second
        thing to keep true.
        """
        heads = sorted(
            (REPO / "backend" / "alembic" / "versions").glob("00*.py"),
        )
        newest = heads[-1].name
        assert not re.search(r"correct|edited|pr_kind", newest)

    def test_the_set_table_gained_no_column(self):
        src = MODELS.read_text()
        table = src[src.index('__tablename__ = "strength_sets"'):]
        table = table[:table.index("class ", 10)]
        assert "edited" not in table
        assert "pr_kind" not in table


class TestBothSurfacesOfferIt:
    def test_the_web_re_enables_a_logged_row(self):
        src = WEB.read_text()
        assert "isEditing" in src
        assert ':disabled="isSetLogged(wex, n)"' not in src, (
            "the unconditional disable is back — a logged set is permanent again"
        )

    def test_the_web_confirms_before_deleting(self):
        """It destroys logged work and there is no undo.

        The ad-hoc exercise remove nearby does not confirm, but that only
        ever removes a slot the user added and has not touched.
        """
        src = WEB.read_text()
        block = src[src.index("async function removeSet("):]
        block = block[:block.index("async function logFailed(")]
        assert "confirm(" in block

    def test_the_phone_offers_an_edit_and_reuses_the_entry_form(self):
        """`SetEntryRow` already took `isCurrent` so a non-current set could
        render an entry form without stealing the NOW accent. A separate edit
        dialog would have been a second set-entry UI to keep in step."""
        src = PHONE.read_text()
        assert "onEditSet" in src
        assert "isCurrent = false" in src

    def test_the_phone_editing_state_is_hoisted(self):
        """State inside a LazyColumn item is dropped on slot churn, and every
        mutation here ends in reload(). That is the recorded CoachCard
        failure one screen over."""
        src = PHONE.read_text()
        i_state = src.index("var editingSetKey")
        # The real call, not the comment above the state that names it.
        i_items = src.index("items(orderedExercises, key =")
        assert i_state < i_items


class TestTheFixesTheReviewFound:
    """Four defects in the first cut of this task, found by an adversarial
    review of the committed code. Each is pinned because each was invisible
    to the tests that shipped with it.
    """

    def test_a_drop_set_does_not_crash_the_workout(self):
        """`_planned_sets` echoes a logged set's real type back.

        `PlannedSetOut.set_type` was `Literal["warmup", "working"]` — the two
        values the GENERATOR prescribes — so the moment it started echoing
        the four values a set can actually HOLD, loading any workout
        containing a set the web's picker had marked `drop` raised a
        ValidationError. A 500 on the main workout screen, shipped by a
        change whose whole point was to preserve that value.
        """
        field = api.PlannedSetOut.model_fields["set_type"]
        args = getattr(field.annotation, "__args__", ())
        assert set(args) == {"warmup", "working", "drop", "failure"}

    def test_every_loggable_set_type_survives_the_round_trip(self):
        """The validator, not the annotation — the real failure was runtime."""
        for kind in ("working", "warmup", "drop", "failure"):
            api.PlannedSetOut(
                set_number=1, set_type=kind, target_reps=8,
                rest_s=90, prefill_reps=8,
            )

    def test_the_web_can_correct_a_finished_exercise(self):
        """The common case, and the first cut did not cover it.

        A finished exercise collapses to chip summaries, and that branch
        precedes the input table — so a set could only be corrected while its
        siblings were still outstanding, which is precisely not when a typo
        gets noticed.
        """
        src = WEB.read_text()
        assert "reopenExercise" in src
        assert "isEditingExercise" in src
        chips = src.index('class="done-summary"')
        assert "isEditingExercise" in src[chips - 400:chips], (
            "the done-summary branch must yield while a correction is open"
        )

    def test_the_phone_gates_edit_on_the_session_not_the_slot(self):
        """`isSlotClosed` is true for a slot whose sets are all logged.

        Gating the correction affordance on it hid the affordance exactly
        when every set was done — the identical failure as the web's, on the
        other surface, and neither the design nor the first implementation
        noticed the phone had it too.
        """
        src = PHONE.read_text()
        assert "sessionWritable" in src
        assert "onEdit = if (sessionWritable)" in src
        assert "editingSetNum == n && sessionWritable" in src

    def test_the_phone_delete_is_not_wired_to_the_log_button(self):
        """The sharpest of the four.

        `SetEntryRow`'s single action button routes to `onFailed` whenever the
        rating is 1, and reads "Log set". Passing delete as `onFailed` meant
        correcting a set to Failed destroyed it — unconfirmed, from a button
        that said it would log.
        """
        src = PHONE.read_text()
        assert "onFailed = { onDeleteSet(" not in src, (
            "delete is wired to the log button's failed path again"
        )
        assert "Delete set" in src, "delete needs its own named control"

    def test_the_phone_correction_closes_itself(self):
        """Otherwise the row stays an entry form after Save, and its scratch
        input outlives it — the web already closed via cancelEdit()."""
        src = PHONE.read_text()
        assert "editingSetKey = null" in src
        assert "setInputs.clear()" in src
