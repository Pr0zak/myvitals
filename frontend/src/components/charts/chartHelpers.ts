import type { Activity, Annotation } from "@/api/types";
import { chartTheme } from "@/theme";
import { fmtTime, timeFormat } from "@/format";

/** A no-icon SVG path so markPoint can render dots without text. */
const DOT_SYMBOL = "circle";

/**
 * Smart time-axis label formatter. Renders intraday timestamps in the
 * user's preferred 12h/24h format and dates (midnight) as "MMM d".
 * Reading `timeFormat.value` here means callers must reference it in
 * their computed() to trigger a re-render when the user toggles.
 *
 * Exported so charts that build their own xAxis (HR component,
 * Activity detail, Today's steps) can apply it directly.
 */
export function timeAxisFormatter(v: number): string {
  const d = new Date(v);
  // Midnight tick → show date label instead of "12:00 AM" / "00:00"
  if (d.getHours() === 0 && d.getMinutes() === 0) {
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return fmtTime(d);
}

/** Drop-in `axisLabel` object for ECharts time axes that respects the
 *  user's 12h/24h preference. Use as: `axisLabel: { ...t.axisLabel, ...timeAxisLabel() }`. */
export function timeAxisLabel() {
  void timeFormat.value;  // re-render trigger
  return { formatter: timeAxisFormatter };
}

/** Common ECharts options every time-series chart starts from. */
export function baseTimeOption() {
  const t = chartTheme.value;
  void timeFormat.value;  // re-render charts when the user flips 12h/24h
  return {
    grid: { left: 40, right: 12, top: 8, bottom: 28 },
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
      scale: true,
    },
    tooltip: {
      trigger: "axis",
      ...t.tooltip,
    },
    dataZoom: [
      { type: "inside", throttle: 50 },
      {
        type: "slider",
        height: 18,
        bottom: 4,
        backgroundColor: "transparent",
        borderColor: t.splitLine.lineStyle.color,
        fillerColor: t.tooltip.backgroundColor + "40",
        handleStyle: { color: t.palette.accent ?? t.palette.steps },
        textStyle: t.axisLabel,
      },
    ],
  };
}

/**
 * Convert a list of activities to a markArea series component.
 * Use as: { ...lineSeries, markArea: workoutMarkArea(activities) }.
 * Strength sessions (type === "strength") are tinted with the workout
 * palette colour so they're visually distinct from cardio activities.
 */
export function workoutMarkArea(activities: Activity[]) {
  const t = chartTheme.value;
  const strengthColor = t.palette.workout ?? t.palette.activity;
  return {
    silent: false,
    itemStyle: { color: t.palette.activity, borderColor: t.palette.activity },
    // Pin the label *inside* the band near the top so it doesn't get
    // clipped by the chart's top edge. ECharts' default position puts
    // the label above the band where the chart container truncates it.
    label: {
      show: true,
      position: "insideTop",
      distance: 4,
      color: t.axisLabel.color,
      fontSize: 10,
      fontWeight: 600,
      overflow: "truncate",
      width: 120,
    },
    data: activities.map((a) => {
      const color = a.type === "strength" ? strengthColor : t.palette.activity;
      return [
        {
          xAxis: a.start_at,
          name: a.name ?? a.type,
          itemStyle: { color },
        },
        {
          xAxis: new Date(new Date(a.start_at).getTime() + a.duration_s * 1000).toISOString(),
        },
      ];
    }),
  };
}

const ANNOTATION_EMOJI: Record<string, string> = {
  caffeine: "☕",
  alcohol: "🍺",
  mood: "🙂",
  food: "🍽️",
  meds: "💊",
  note: "📝",
};

/**
 * Markpoint series component that drops icons at annotation timestamps.
 * Pass the y-position you want markers stacked at (e.g. the chart's max).
 */
export function annotationMarkPoint(annotations: Annotation[], yValue: number) {
  return {
    symbol: DOT_SYMBOL,
    symbolSize: 18,
    label: {
      show: true,
      formatter: (p: { data: { value: string } }) => p.data.value,
      fontSize: 14,
    },
    itemStyle: { color: "transparent" },
    data: annotations.map((a) => ({
      coord: [a.ts, yValue],
      value: ANNOTATION_EMOJI[a.type] ?? "•",
      tooltipName: `${a.type} ${JSON.stringify(a.payload)}`,
    })),
  };
}

/**
 * Vertical dashed lines at each sobriety reset, with a 🔄 label at the top.
 * Pass the streaks list (the start_at of each row is the reset event — the
 * moment the streak began, equivalent to when the previous one ended).
 */
export function soberResetMarkLine(
  resets: Array<{ start_at: string }>,
  color = "#a78bfa",
) {
  if (!resets.length) return undefined;
  return {
    silent: false,
    symbol: ["none", "none"],
    lineStyle: { color, width: 1, type: "dashed" as const, opacity: 0.55 },
    label: {
      show: true,
      formatter: "🔄",
      position: "insideEndTop" as const,
      fontSize: 12,
      color,
    },
    data: resets.map((r) => ({ xAxis: r.start_at, name: "reset" })),
  };
}

/**
 * Convert a sleep night into a markArea series component representing
 * the in-bed window. Pass the result as the markArea of a (possibly
 * empty) series to render a translucent band on a time-axis chart.
 */
export function sleepMarkArea(
  sleep: { start?: string | null; end?: string | null } | null,
  windowMinMs: number,
  windowMaxMs: number,
) {
  if (!sleep || !sleep.start || !sleep.end) return undefined;
  const start = new Date(sleep.start).getTime();
  const end = new Date(sleep.end).getTime();
  if (!isFinite(start) || !isFinite(end) || end <= start) return undefined;
  // Clamp to the chart's visible window so the band doesn't drag the
  // chart off-axis when it precedes the window.
  const lo = Math.max(start, windowMinMs);
  const hi = Math.min(end, windowMaxMs);
  if (hi <= lo) return undefined;
  return {
    silent: true,
    itemStyle: {
      color: "rgba(167, 139, 250, 0.13)",   // violet — same family as sleep palette
      borderColor: "rgba(167, 139, 250, 0.35)",
      borderWidth: 1,
    },
    label: {
      show: true,
      formatter: "💤 sleep",
      position: "insideTop" as const,
      color: "#a78bfa",
      fontSize: 10,
      fontWeight: 600,
      distance: 4,
    },
    data: [[
      { xAxis: new Date(lo).toISOString(), name: "sleep" },
      { xAxis: new Date(hi).toISOString() },
    ]],
  };
}

/** A horizontal "mean" line for any axis. */
export function meanMarkLine(value: number | null, label = "avg") {
  if (value === null) return undefined;
  const t = chartTheme.value;
  return {
    silent: true,
    symbol: "none",
    lineStyle: { color: t.palette.steps, type: "dashed" as const, opacity: 0.6 },
    label: { show: true, formatter: `${label} ${value.toFixed(0)}`, color: t.axisLabel.color, fontSize: 9 },
    data: [{ yAxis: value }],
  };
}

/**
 * The shaded "your normal" band, as a y-axis markArea.
 *
 * Bounds come from `/summary/tiles` (band_low / band_high) — the rule that
 * produces them is a health judgement and lives in analytics/tiles.py, so
 * the detail chart, the metric card and the phone all shade the same zone.
 *
 * markArea is ONE PER SERIES, and several views already spend that slot on
 * time-based bands (workout windows, the sleep block). Pair this with
 * `bandHostSeries` in those cases rather than overwriting theirs.
 */
export function normalBandMarkArea(
  low: number | null | undefined,
  high: number | null | undefined,
  color?: string,
) {
  if (low == null || high == null) return undefined;
  const t = chartTheme.value;
  const tone = color ?? t.palette.hrv ?? "#7ee2a8";
  return {
    silent: true,
    itemStyle: { color: tone, opacity: 0.1 },
    label: {
      show: true,
      position: "insideTopRight" as const,
      formatter: "Your normal",
      color: t.axisLabel.color,
      fontSize: 9,
      opacity: 0.8,
    },
    data: [[{ yAxis: low }, { yAxis: high }]],
  };
}

/**
 * An empty series that exists only to carry a markArea.
 *
 * The escape hatch for charts whose real series already uses its one
 * markArea slot — the pattern HeartRate.vue already uses for its sleep
 * band.
 */
export function bandHostSeries(markArea: unknown, name = "Your normal") {
  return {
    type: "line" as const,
    name,
    data: [] as number[],
    showSymbol: false,
    silent: true,
    markArea,
  };
}

/**
 * A single markLine DATA ENTRY for a target/threshold, not a whole
 * markLine object — markLine is one-per-series but its `data` is a list,
 * so appending composes with existing lines instead of replacing them.
 */
export function targetMarkLineItem(value: number, label: string) {
  const t = chartTheme.value;
  return {
    yAxis: value,
    lineStyle: { color: t.palette.steps, type: "dashed" as const, opacity: 0.55 },
    label: { show: true, formatter: label, color: t.axisLabel.color, fontSize: 9 },
  };
}

// ---------------------------------------------------------------------------
// Window coverage — the axis shows the range you asked for, and says where
// it has nothing.
// ---------------------------------------------------------------------------

/**
 * X-axis `min`/`max` pinned to the SELECTED window rather than to the data.
 *
 * ECharts fits a time axis to the points it is given, so picking 90d on a
 * stream holding three readings from the last two days drew a two-day chart
 * captioned 90d. Every range above 7d rendered identically and the picker
 * looked broken — it was reported as exactly that. The axis is a statement
 * about the question asked, not about the answer that came back.
 *
 * Returns `{}` for an open-ended range ("all"), where there is no window to
 * pin to and the data genuinely is the extent.
 */
export function windowExtent(
  sinceMs: number | null | undefined,
  untilMs: number = Date.now(),
): { min?: number; max?: number } {
  if (sinceMs == null) return {};
  return { min: sinceMs, max: untilMs };
}

/** Smallest slice of the window worth drawing as a gap, as a fraction. Below
 *  this a gap is a rendering artefact of the last sample's timing, not an
 *  absence worth pointing at. */
const GAP_MIN_FRACTION = 0.03;

/**
 * A faint dashed line across the stretches of the window that hold no data.
 *
 * Held FLAT at the nearest real reading's value, deliberately. The line has
 * to sit at some height, and any slope would assert a direction of travel
 * across days that were never measured — the one thing the chart must not
 * invent. Flat asserts less: it reads as "nothing was recorded here" rather
 * than as a trend. It is still a drawn line where no measurement exists, so
 * it is dashed, faint, excluded from the tooltip, and named "No data" in the
 * legend; the stats card counts only real readings, and no moving average or
 * regression may consume these points.
 *
 * Covers both ends. The trailing gap matters more than it looks: a stream
 * that stopped days ago currently draws a line that ends wherever it ends,
 * which is indistinguishable from a stream that is up to date.
 */
export function noDataSpans(
  points: Array<[number, number]>,
  sinceMs: number | null | undefined,
  untilMs: number = Date.now(),
  color = "#94a3b8",
): Array<Record<string, unknown>> {
  if (sinceMs == null || !points.length) return [];
  const span = untilMs - sinceMs;
  if (span <= 0) return [];
  const min = GAP_MIN_FRACTION * span;

  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const data: Array<[number, number] | null> = [];

  if (first[0] - sinceMs > min) {
    data.push([sinceMs, first[1]], [first[0], first[1]], null);
  }
  if (untilMs - last[0] > min) {
    data.push([last[0], last[1]], [untilMs, last[1]]);
  }
  if (!data.length) return [];

  return [{
    name: "No data",
    type: "line",
    data,
    symbol: "none",
    connectNulls: false,
    silent: true,
    tooltip: { show: false },
    z: 1,
    lineStyle: { width: 1.5, color, type: "dashed" as const, opacity: 0.45 },
  }];
}

/** `[[ms, value], ...]` from a daily series keyed by date string, dropping
 *  the null days. The daily charts carry `[date, value | null]` so that
 *  `gapBridgeSeries` can dash the interior holes; the window helpers want
 *  only the readings that exist. */
export function daysToPoints(
  rows: Array<[string, number | null]>,
): Array<[number, number]> {
  return rows
    .filter((r): r is [string, number] => r[1] != null)
    .map((r) => [new Date(r[0]).getTime(), r[1]]);
}

/**
 * One line describing what the window actually contains, for the stats card.
 *
 * The chart can show an empty stretch; it cannot say how many readings the
 * numbers beside it were computed from, which is the part that makes three
 * identical windows legible instead of suspicious. Returns null when the
 * data fills the window, so the note appears only when it is telling the
 * user something.
 */
export function coverageNote(
  points: Array<[number, number]>,
  sinceMs: number | null | undefined,
  untilMs: number = Date.now(),
): string | null {
  if (!points.length) return null;
  const n = points.length;
  const reading = n === 1 ? "reading" : "readings";
  if (sinceMs == null) return null;
  const span = untilMs - sinceMs;
  if (span <= 0) return null;
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  const oldest = new Date(sorted[0][0]);
  const newest = new Date(sorted[sorted.length - 1][0]);
  const lead = sorted[0][0] - sinceMs;
  const trail = untilMs - sorted[sorted.length - 1][0];
  if (lead <= GAP_MIN_FRACTION * span && trail <= GAP_MIN_FRACTION * span) return null;
  const d = (x: Date) => x.toLocaleDateString([], { month: "numeric", day: "numeric" });
  if (n === 1) return `1 reading, ${d(oldest)} — nothing else in this range`;
  return `${n} ${reading}, ${d(oldest)} – ${d(newest)} — nothing outside that in this range`;
}
