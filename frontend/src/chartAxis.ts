/**
 * Axis helpers shared by the ECharts views.
 *
 * Web twin of the Kotlin `ChartFrame.kt` reasoning: ECharts will not widen an
 * axis to contain a `markLine` or `markArea`, so a goal / target / normal band
 * that falls outside the data's own extent is silently not drawn — and that is
 * precisely the case you most want to see (every day short of the goal, every
 * night short of the target).
 *
 * Forcing `max` fixes the invisibility but introduces a second problem if you
 * force it to an arbitrary number: ECharts then labels the axis with whatever
 * the raw bound was, which renders as a long unrounded string that overflows
 * the grid's left gutter. Always round the bound out to a readable tick.
 */

/** 1 / 2 / 2.5 / 5 × 10^n — the same ladder the Kotlin side uses. */
function niceStep(rough: number): number {
  if (!(rough > 0) || !Number.isFinite(rough)) return 1;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const n = rough / mag;
  const mult = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return mult * mag;
}

/**
 * A zero-anchored `{ min, max }` that contains every value in [values] plus
 * [mustInclude] (a goal or target line), rounded up to a readable tick.
 *
 * Returns `{}` when there is nothing to bound, so callers can spread it into
 * an axis config and leave ECharts' own behaviour untouched.
 */
export function zeroAxisIncluding(
  values: Array<number | null | undefined>,
  mustInclude?: number | null,
  targetTicks = 5,
): { min?: number; max?: number } {
  const nums = values.filter((v): v is number => v != null && Number.isFinite(v));
  const hi = Math.max(
    ...nums,
    mustInclude != null && Number.isFinite(mustInclude) ? mustInclude : -Infinity,
  );
  if (!Number.isFinite(hi) || hi <= 0) return {};
  // Headroom first, then round out — so a goal exactly equal to the max is not
  // drawn flush against the top of the plot.
  const step = niceStep((hi * 1.08) / targetTicks);
  return { min: 0, max: Math.ceil((hi * 1.08) / step) * step };
}
