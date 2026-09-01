/**
 * Which way is "good" for a body-weight change — OG2-A5.
 *
 * A body-weight delta has no intrinsic sign meaning. Two screens decided it
 * did, in opposite corners of the app and with the same wrong answer:
 * `Weight.vue` declared `deltaCls(kg, lowerIsBetter = true)` and called it
 * bare for the 7-day, 30-day and range figures, and `BodyMetrics.vue` passed
 * a hard-coded `invert` to `Delta.vue` on the Today screen. So a user gaining
 * toward a goal had their progress painted red on both.
 *
 * The server already had a position on this and neither screen asked. The
 * `MetricSpec` for bodyweight in `analytics/compare.py` is `better="context"`,
 * whose docstring says it outright: whether +2 lb is good depends entirely on
 * whether the user is cutting or bulking, "and the app does not get to
 * assume". `context` means render neutral, not "pick lower and hope".
 *
 * The only thing that can settle the direction is the user's own goal, which
 * is why this takes one. With no goal the answer is genuinely unknown and the
 * honest render is a plain figure — the same refusal `analytics/projection.py`
 * makes rather than projecting a trend it cannot support, and the same reason
 * MEAL-2 leaves the fat target null rather than inventing one.
 *
 * The tone vocabulary matches `goalState.ts` so the two read as one system,
 * and for the same stated reason: a client that infers direction from the
 * sign alone eventually paints something as a failure that was never one.
 */

/** Below this a change is scale noise, not a direction.
 *
 *  Mirrors `WEIGHT_NOISE_BAND_KG` in `api/ai.py`, where GOAL-STATE set it and
 *  recorded why: a card that fires on water weight is wrong most weeks, and
 *  one that is wrong most weeks is one you have stopped reading by the week
 *  it matters. It should be re-derived from this user's own within-week
 *  spread once there are enough weigh-ins; until then it errs toward saying
 *  nothing.
 */
export const WEIGHT_NOISE_BAND_KG = 1.0;

/** The same band in pounds. Two callers work in display units and one in
 *  storage units, and the closing instruction of the GOAL-STATE note is
 *  precisely this: when adding a field here, ask which unit it is in. Three
 *  bugs in that release were sign or unit errors of exactly this shape. */
export const WEIGHT_NOISE_BAND_LB = 2.2046226;

export type WeightTone = "positive" | "caution" | "neutral";

/** Unit-agnostic core. Every argument must be in the SAME unit as `band`. */
function toneIn(
  delta: number | null | undefined,
  current: number | null | undefined,
  goal: number | null | undefined,
  band: number,
): WeightTone {
  if (delta == null || current == null || goal == null) return "neutral";
  if (Math.abs(delta) < band) return "neutral";

  // Which way the goal lies from here. Sitting on it is not a direction, so
  // it stays neutral rather than arbitrarily rewarding one sign — a user at
  // their target has nowhere good left to move.
  const gap = goal - current;
  if (Math.abs(gap) < band) return "neutral";

  const movingTowardGoal = gap < 0 ? delta < 0 : delta > 0;
  return movingTowardGoal ? "positive" : "caution";
}

/** All three arguments in KILOGRAMS. */
export function weightDeltaTone(
  deltaKg: number | null | undefined,
  currentKg: number | null | undefined,
  goalKg: number | null | undefined,
): WeightTone {
  return toneIn(deltaKg, currentKg, goalKg, WEIGHT_NOISE_BAND_KG);
}

/** All three arguments in POUNDS. */
export function weightDeltaToneLb(
  deltaLb: number | null | undefined,
  currentLb: number | null | undefined,
  goalLb: number | null | undefined,
): WeightTone {
  return toneIn(deltaLb, currentLb, goalLb, WEIGHT_NOISE_BAND_LB);
}

/** The CSS class for a tone. `neutral` deliberately styles nothing, so an
 *  unjudgeable figure renders as an ordinary number rather than borrowing
 *  the reassurance of green or the alarm of amber. */
export function weightDeltaClass(tone: WeightTone): string {
  return tone === "positive" ? "delta-good" : tone === "caution" ? "delta-warn" : "";
}
