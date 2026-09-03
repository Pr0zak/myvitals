/**
 * OG2-D-4 — how a session FELT, on the progression chart.
 *
 * The chart drew a flat line across four sessions of Straight-Arm Dumbbell
 * Pullover at 20 lb and said nothing about the ratings underneath it moving
 * 4, 4, 5, 5 before the jump to 25. The weight was the only channel, so the
 * sessions in which the lift got easier — the sessions that EARNED the jump —
 * were the ones the picture rendered as no progress at all.
 *
 * Two things do not happen here, deliberately.
 *
 * The BAND is not derived. `effort` arrives from the server, computed from
 * the same `EASY_THRESHOLD` / `FAIL_THRESHOLD` the progression policy acts
 * on, so a dot marked "easy" is exactly the dot where the weight went up.
 * This app rates sets 1-5 where 5 is EASY — the scale counts up with ease,
 * not with effort, and openGym's RIR counts the other way — so which end
 * means what is precisely the kind of inversion GOAL-STATE says one server
 * must own rather than two clients.
 *
 * The LABEL is not written here either. It comes from `effort_legend` in the
 * same response, so the words explaining a band and the thresholds defining
 * it cannot drift apart.
 *
 * What is left is colour, and it is an intensity ramp rather than a traffic
 * light. Effort is descriptive, not a verdict: a hard session is not a
 * failure and an easy one is not a win — an easy session usually means the
 * load is due to go up. Painting them green and red would be scoring the
 * user's training, which is the thing this codebase keeps declining to do.
 */

export type EffortBand = "easy" | "working" | "failed";

export interface Effortish {
  effort?: string | null;
  rating_avg?: number | null;
  rated_sets?: number | null;
}

/** Three bands and nothing else. An unrecognised value from a newer server
 *  must not become a lookup miss that renders an undefined colour. */
export function effortBand(p: Effortish): EffortBand | null {
  const e = p.effort;
  return e === "easy" || e === "working" || e === "failed" ? e : null;
}

/**
 * Deepening ink, not hue-coded judgement. `working` sits at the series
 * colour so the ordinary case reads as the line itself and only the two
 * ends stand out; an unrated day falls back to the series colour too,
 * because "nobody rated this" must not look like a reading.
 */
export function effortColor(
  band: EffortBand | null, seriesColor: string, neon: boolean,
): string {
  if (band === "easy") return neon ? "#5eead4" : "#14b8a6";
  if (band === "failed") return neon ? "#fbbf24" : "#d97706";
  return seriesColor;
}

/** Bigger dot for the two ends, so the ramp survives a colourblind reader
 *  and a greyscale print of the workout sheet. */
export function effortSymbolSize(band: EffortBand | null, base: number): number {
  return band === "easy" || band === "failed" ? base + 3 : base;
}

/**
 * The tooltip line. Returns null when nothing was rated — an absence, not a
 * zero, and never the middle band. `rated_sets` travels with the average
 * for OG2-C4's reason: a mean over two of five sets must not silently speak
 * for the other three.
 */
export function effortSummary(
  p: Effortish, legend: Record<string, string> | undefined,
): string | null {
  const band = effortBand(p);
  if (band === null || p.rating_avg == null) return null;
  const n = p.rated_sets ?? 0;
  const words = legend?.[band] ?? band;
  return `${p.rating_avg}/5 over ${n} rated set${n === 1 ? "" : "s"} — ${words}`;
}
