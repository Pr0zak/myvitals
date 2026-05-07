import type { Activity, Annotation } from "@/api/types";
import { chartTheme } from "@/theme";
import { fmtTime, timeFormat } from "@/format";
import { computed } from "vue";

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
 * Reactive that produces the chart-theme object as a ref so charts can
 * `:option="..."` and re-render on theme change automatically.
 */
export const reactiveChartTheme = computed(() => chartTheme.value);
