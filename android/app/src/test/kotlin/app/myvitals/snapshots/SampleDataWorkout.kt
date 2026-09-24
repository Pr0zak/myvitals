package app.myvitals.snapshots

import app.myvitals.sync.FastingContext
import app.myvitals.sync.LastSet
import app.myvitals.sync.MuscleVolumeRow
import app.myvitals.sync.PlannedSet
import app.myvitals.sync.SessionSummary
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthSetRow
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutExerciseRow
import app.myvitals.sync.StrengthWorkoutSummary
import java.time.LocalDate

/**
 * Invented sample data for the active-workout screenshots (UI-2). Public
 * repo: every number here is made up. "Today" is Wednesday 2026-09-23,
 * mid-way through a push day.
 */
object SampleDataWorkout {
    val today: LocalDate = LocalDate.parse("2026-09-23")
    /** A fixed clock, so the rest ring reads the same on every run. */
    const val NOW_MS = 1_790_000_000_000L

    private fun info(id: String, name: String, muscle: String, pattern: String = "push",
                     timed: Boolean = false, bilateral: Boolean = false) =
        StrengthExerciseInfo(id = id, name = name, primaryMuscle = muscle,
            movementPattern = pattern, isTimed = timed, isBilateral = bilateral)

    val catalog: Map<String, StrengthExerciseInfo> = listOf(
        info("db_bench", "Dumbbell Bench Press", "chest"),
        info("db_shoulder_press", "Seated Dumbbell Shoulder Press", "shoulders"),
        info("incline_fly", "Incline Dumbbell Fly", "chest"),
        info("lateral_raise", "Lateral Raise", "shoulders"),
        info("oh_tri_ext", "Overhead Triceps Extension", "triceps"),
        info("pushup", "Push-Up", "chest"),
        info("childs_pose", "Child's Pose", "lower back", pattern = "mobility", timed = true),
        info("side_plank", "Side Plank", "abdominals", pattern = "core", timed = true, bilateral = true),
    ).associateBy { it.id }

    private fun planned(n: Int, w: Double?, reps: Int, prefillW: Double? = w, prefillReps: Int = reps) =
        PlannedSet(setNumber = n, targetWeightLb = w, targetReps = reps,
            prefillWeightLb = prefillW, prefillReps = prefillReps)

    private fun logged(id: Long, wexId: Long, n: Int, w: Double?, reps: Int, rating: Int) =
        StrengthSetRow(id = id, workoutExerciseId = wexId, setNumber = n, targetReps = reps,
            actualWeightLb = w, actualReps = reps, rating = rating)

    private fun slot(
        id: Long, exerciseId: String, order: Int, sets: Int, low: Int, high: Int, w: Double?,
        logged: List<StrengthSetRow> = emptyList(), superset: String? = null,
        skipped: Boolean = false, timed: Boolean = false, rest: Int = 90,
        last: List<LastSet> = emptyList(), notes: String? = null, loadHint: String? = null,
        ladder: List<Double>? = null,
    ) = StrengthWorkoutExerciseRow(
        id = id, workoutId = 7, exerciseId = exerciseId, orderIndex = order,
        supersetId = superset, targetSets = sets, targetRepsLow = low, targetRepsHigh = high,
        targetWeightLb = w, targetRestS = rest, isTimed = timed, skipped = skipped,
        lastSets = last, notes = notes, loadHint = loadHint,
        plannedSets = (1..sets).map { planned(it, w, low) },
        sets = logged,
        loadLadderLb = ladder,
    )

    private val exercises = listOf(
        slot(71, "db_bench", 0, 3, 8, 10, 50.0, logged = listOf(
            logged(1, 71, 1, 50.0, 10, 4), logged(2, 71, 2, 50.0, 9, 4), logged(3, 71, 3, 50.0, 8, 2),
        )),
        slot(72, "db_shoulder_press", 1, 3, 8, 10, 32.5,
            logged = listOf(logged(4, 72, 1, 32.5, 10, 4)),
            last = listOf(LastSet(1, 30.0, 10), LastSet(2, 30.0, 9), LastSet(3, 30.0, 8)),
            notes = "Up 2.5 lb: every set hit 10 last time.",
            loadHint = "30 lb DB + 2.5 lb wrist",
            // UI-F4: invented rack — the steppers walk these, not ±2.5.
            ladder = listOf(30.0, 31.0, 31.5, 32.5, 33.0, 34.0, 35.0)),
        slot(73, "incline_fly", 2, 3, 10, 12, 20.0),
        slot(74, "lateral_raise", 3, 3, 12, 15, 15.0, superset = "A", rest = 60),
        slot(75, "oh_tri_ext", 4, 3, 10, 12, 25.0, superset = "A", rest = 60),
        slot(76, "pushup", 5, 2, 12, 15, null, skipped = true),
        slot(77, "childs_pose", 6, 1, 45, 45, null, timed = true),
    )

    val workout = StrengthWorkoutDetail(
        id = 7, date = "2026-09-23", generatedAt = "2026-09-23T11:00:00Z",
        splitFocus = "push", status = "in_progress", seed = "sample",
        fastingContext = FastingContext(active = true, currentHours = 19.5,
            stage = "fat_burning", modulation = "volume_-20%"),
        deloadFactor = 0.92, deloadReason = "recovery 52",
        notes = "Push is next in your rotation.\n" +
            "Accessory work padded to fill 45 minutes.\n" +
            "Mobility cool-down appended.",
        exercisesDone = 2, exercisesTotal = 7, setsDone = 6, setsTotal = 18,
        exercises = exercises,
        projectedMuscleVolume = mapOf(
            "chest" to MuscleVolumeRow(sets = 9, mev = 10, mav = 20, status = "under",
                setsProjected = 12.0, statusProjected = "in_range"),
            "shoulders" to MuscleVolumeRow(sets = 6, mev = 8, mav = 16, status = "under",
                setsProjected = 12.0, statusProjected = "in_range"),
            "triceps" to MuscleVolumeRow(sets = 4, mev = 6, mav = 14, status = "under",
                setsProjected = 7.0, statusProjected = "in_range"),
        ),
    )

    /** Everything done and stamped. */
    val completed = workout.copy(
        status = "completed",
        exercises = exercises.map { e ->
            if (e.skipped || e.isTimed) e
            else e.copy(sets = (1..e.targetSets).map { n ->
                logged(100L + e.id * 10 + n, e.id, n, e.targetWeightLb, e.targetRepsLow, 4)
            })
        },
        exercisesDone = 7, exercisesTotal = 7, setsDone = 17, setsTotal = 18,
        sessionSummary = SessionSummary(netDurationS = 3120, workingSets = 15,
            totalReps = 158, totalVolumeLb = 4235.0, kcalMethod = "met", kcalEst = 210.0),
    )

    /** A mobility day whose NOW slot is a timed, bilateral hold. */
    val timedHold = StrengthWorkoutDetail(
        id = 8, date = "2026-09-23", generatedAt = "2026-09-23T11:00:00Z",
        splitFocus = "core", status = "in_progress", seed = "sample",
        exercisesDone = 0, exercisesTotal = 2, setsDone = 0, setsTotal = 3,
        exercises = listOf(
            slot(81, "side_plank", 0, 2, 40, 40, null, timed = true, rest = 30),
            slot(82, "childs_pose", 1, 1, 60, 60, null, timed = true),
        ),
    )

    val history = listOf(
        StrengthWorkoutSummary(id = 5, date = "2026-09-21", splitFocus = "pull",
            status = "completed", generatedAt = "2026-09-21T11:00:00Z"),
        StrengthWorkoutSummary(id = 6, date = "2026-09-22", splitFocus = "legs",
            status = "skipped", generatedAt = "2026-09-22T11:00:00Z"),
    )
    val projectedDates = setOf("2026-09-24", "2026-09-26")
}
