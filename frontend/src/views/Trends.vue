<script setup lang="ts">
import { normaliseRange } from "@/useDateRange";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import PageHeader from "@/components/PageHeader.vue";
import RangeTabs from "@/components/RangeTabs.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadState from "@/components/LoadState.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import { weightVal, weightUnit, fmtWeight, isImperial, tempUnit } from "@/units";

const route = useRoute();

const _C_TO_F = 1.8;  // ΔF = ΔC × 9/5

// RANGE-1: canonical vocabulary (was "365d" for the year).
type Range = "7d" | "30d" | "90d" | "1y";
const RANGES: { key: Range; label: string; days: number }[] = [
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "90 days", days: 90 },
  { key: "1y", label: "1 year", days: 365 },
];

type ChartType = "line" | "bar" | "area";

// ANALYTICS-2: range can be driven externally via the Analytics shell's
// shared selector (writes `?range=…` on the URL). Falls back to the
// per-page default when absent.
const VALID_RANGE = new Set(["7d", "30d", "90d", "1y"]);
function rangeFromRoute(): Range {
  const q = route.query.range;
  // Folds the legacy "365d" so bookmarks predating RANGE-1 still resolve.
  const v = normaliseRange(Array.isArray(q) ? q[0] : q);
  return (v && VALID_RANGE.has(v)) ? (v as Range) : "30d";
}
const range = ref<Range>(rangeFromRoute());
watch(() => route.query.range, () => {
  const next = rangeFromRoute();
  if (next !== range.value) range.value = next;
});
const data = ref<TodaySummary[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const overlayMetrics = ref({ rhr: true, hrv: true, recovery: true, sleep: false });
const stepsType = ref<ChartType>("bar");
const stepsGoal = ref(8000);

// Sober reset overlay state. The full streak history is loaded once; the
// computed `soberResetDates` filters down to dates within the data window
// so chart markLines stay light.
const showSoberResets = ref(true);
const soberStreaks = ref<Array<{ start_at: string }>>([]);

type WeightPoint = { time: string; weight_kg: number | null; body_fat_pct: number | null; bmi: number | null; lean_mass_kg: number | null; source: string };
const weightSeries = ref<WeightPoint[]>([]);
const weightStats = ref<{ latest_kg: number | null; min_kg: number | null; max_kg: number | null; avg_kg: number | null }>({ latest_kg: null, min_kg: null, max_kg: null, avg_kg: null });

// Goal, height and projection all come from the server (UX-D7).
//
// This card used to keep its OWN weight goal, goal date and height in
// localStorage — height defaulting to an invented 178 cm — and fitted its
// own regression for an ETA. So it was a second goal that could disagree
// with the one on You, BMI bands drawn for a height nobody entered, and an
// ETA that never refused: the server's projection declines to give a date
// when the trend is flat, noisy or too far out, and this one gave one
// anyway. Now it reads the profile and the weight goal's projection and
// edits nothing; the goal is set where every other surface reads it.
const heightCm = ref<number | null>(null);
const goalKg = ref<number | null>(null);
type GoalProjection = { per_week: number | null; eta_date: string | null; confidence: string | null; is_fallback: boolean; fallback_reason: string | null };
const weightGoal = ref<{ target_date: string | null; target_unit: string | null; projection: GoalProjection | null } | null>(null);

async function loadGoal() {
  try {
    const [p, goals] = await Promise.all([
      api.getProfile().catch(() => null),
      api.aiGoals(true).catch(() => []),
    ]);
    heightCm.value = p?.height_cm ?? null;
    goalKg.value = p?.weight_goal_kg ?? null;
    weightGoal.value = goals.find((g) => g.kind === "weight") ?? null;
  } catch { /* the chart still renders without a goal */ }
}

/** Same caption as the goal row on You, from the same projection. */
const goalCaption = computed<string | null>(() => {
  const p = weightGoal.value?.projection;
  if (!p) return null;
  if (p.is_fallback) return p.fallback_reason;
  const unit = weightGoal.value?.target_unit ?? "";
  const rate = p.per_week != null
    ? `${p.per_week > 0 ? "+" : ""}${p.per_week.toFixed(2)} ${unit}/wk`.replace("  ", " ")
    : null;
  if (p.eta_date) {
    const conf = p.confidence === "low" ? " (rough)" : "";
    return rate ? `${rate} · on track for ${p.eta_date}${conf}` : `On track for ${p.eta_date}${conf}`;
  }
  return rate;
});

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const since = new Date();
    since.setDate(since.getDate() - days);
    const [summary, weight, sober] = await Promise.all([
      api.summaryRange(since),
      api.weight({ since }).catch(() => ({ points: [], latest_kg: null, min_kg: null, max_kg: null, avg_kg: null })),
      api.soberHistory(500).catch(() => []),
    ]);
    data.value = summary;
    weightSeries.value = weight.points;
    weightStats.value = { latest_kg: weight.latest_kg, min_kg: weight.min_kg, max_kg: weight.max_kg, avg_kg: weight.avg_kg };
    soberStreaks.value = (sober as Array<{ start_at: string }>) ?? [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

function rolling7Avg(pts: { t: number; v: number }[]): { t: number; v: number }[] {
  // Simple centered window: average of all points within the trailing 7 days.
  if (pts.length === 0) return [];
  const sorted = [...pts].sort((a, b) => a.t - b.t);
  const out: { t: number; v: number }[] = [];
  const WINDOW_MS = 7 * 86400 * 1000;
  let i0 = 0;
  for (let i = 0; i < sorted.length; i++) {
    while (sorted[i].t - sorted[i0].t > WINDOW_MS) i0++;
    let sum = 0; let n = 0;
    for (let j = i0; j <= i; j++) { sum += sorted[j].v; n++; }
    out.push({ t: sorted[i].t, v: sum / n });
  }
  return out;
}

function bmiBands(heightM: number): unknown[] {
  // BMI thresholds in kg, then converted to display unit so the bands align
  // with the y-axis (which is in user units).
  const toUnit = (kg: number) => weightVal(kg) ?? kg;
  const u = toUnit(18.5 * heightM * heightM);
  const n = toUnit(25 * heightM * heightM);
  const o = toUnit(30 * heightM * heightM);
  return [
    [{ yAxis: 0, itemStyle: { color: "rgba(56, 189, 248, 0.07)" } }, { yAxis: u }],
    [{ yAxis: u, itemStyle: { color: "rgba(34, 197, 94, 0.07)" } }, { yAxis: n }],
    [{ yAxis: n, itemStyle: { color: "rgba(234, 179, 8, 0.07)" } }, { yAxis: o }],
    [{ yAxis: o, itemStyle: { color: "rgba(239, 68, 68, 0.10)" } }, { yAxis: 9999 }],
  ];
}

const weightOption = computed(() => {
  void chartTheme.value;
  void weightUnit.value;  // re-render on unit toggle
  const t = chartTheme.value;
  const raw = weightSeries.value
    .filter((p) => p.weight_kg != null)
    .map((p) => ({ t: new Date(p.time).getTime(), v: weightVal(p.weight_kg) as number }));
  const pts = raw.map((p) => [p.t, p.v]);
  const ma = rolling7Avg(raw).map((p) => [p.t, p.v]);
  const fatPts = weightSeries.value
    .filter((p) => p.body_fat_pct != null)
    .map((p) => [new Date(p.time).getTime(), p.body_fat_pct]);

  const series: Array<Record<string, unknown>> = [];
  if (pts.length) {
    series.push({
      name: "Daily weight", type: "line", data: pts,
      symbol: "circle", symbolSize: 3, connectNulls: false,
      lineStyle: { width: 1, color: t.palette.accent, opacity: 0.45 },
      itemStyle: { color: t.palette.accent }, yAxisIndex: 0,
      // BMI bands behind the daily line — only with a real height. Bands
      // drawn for a guessed height are a wrong answer that looks precise.
      ...(heightCm.value ? {
        markArea: { silent: true, data: bmiBands(heightCm.value / 100) },
      } : {}),
    });
  }
  if (ma.length) {
    series.push({
      name: "7-day avg", type: "line", data: ma, smooth: true,
      symbol: "none", lineStyle: { width: 2.5, color: t.palette.accent },
      yAxisIndex: 0,
    });
  }
  // Goal line: from earliest weight in window to target (in user units).
  const targetDate = weightGoal.value?.target_date;
  if (goalKg.value != null && targetDate && pts.length) {
    const start = pts[0];
    const targetTs = new Date(`${targetDate}T00:00:00`).getTime();
    const targetDisplay = weightVal(goalKg.value);
    if (Number.isFinite(targetTs) && targetDisplay != null) {
      series.push({
        name: "Goal", type: "line",
        data: [[start[0], start[1]], [targetTs, targetDisplay]],
        symbol: "none", smooth: false,
        lineStyle: { width: 1.5, color: t.palette.recovery, type: "dashed" as const, opacity: 0.7 },
        yAxisIndex: 0,
      });
    }
  }
  if (fatPts.length) series.push({
    name: "Body fat %", type: "line", data: fatPts, smooth: true,
    symbol: "circle", symbolSize: 4, connectNulls: true,
    lineStyle: { width: 1.5, color: t.palette.annotation, type: "dashed" as const },
    itemStyle: { color: t.palette.annotation }, yAxisIndex: 1,
  });
  return {
    grid: { left: 50, right: 50, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: [
      { type: "value", name: weightUnit.value, scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
      { type: "value", name: "%", scale: true, axisLabel: t.axisLabel, splitLine: { show: false } },
    ],
    series,
    dataZoom: [{ type: "inside" }],
  };
});

const hasWeight = computed(() => weightSeries.value.some((p) => p.weight_kg != null));

// Body composition (lean + fat mass, stacked area)
const bodyCompOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const lean: [number, number][] = [];
  const fat: [number, number][] = [];
  for (const p of weightSeries.value) {
    if (p.weight_kg == null) continue;
    const ts = new Date(p.time).getTime();
    if (p.lean_mass_kg != null) {
      lean.push([ts, weightVal(p.lean_mass_kg)!]);
    } else if (p.body_fat_pct != null) {
      const fatKg = p.weight_kg * (p.body_fat_pct / 100);
      lean.push([ts, weightVal(p.weight_kg - fatKg)!]);
      fat.push([ts, weightVal(fatKg)!]);
    }
  }
  return {
    grid: { left: 50, right: 12, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: weightUnit.value, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      { name: "Lean mass", type: "line", stack: "body", data: lean, smooth: true,
        symbol: "none", areaStyle: { color: t.palette.hrv, opacity: 0.4 },
        lineStyle: { width: 0 }, itemStyle: { color: t.palette.hrv } },
      { name: "Fat mass",  type: "line", stack: "body", data: fat,  smooth: true,
        symbol: "none", areaStyle: { color: t.palette.annotation, opacity: 0.4 },
        lineStyle: { width: 0 }, itemStyle: { color: t.palette.annotation } },
    ],
    dataZoom: [{ type: "inside" }],
  };
});
const hasBodyComp = computed(() =>
  weightSeries.value.some((p) => p.weight_kg != null && (p.body_fat_pct != null || p.lean_mass_kg != null)),
);

// BP card — uses daily_summary.bp_systolic_avg / bp_diastolic_avg
const bpOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const sys = data.value.filter((d) => d.bp_systolic_avg != null).map((d) => [d.date, d.bp_systolic_avg]);
  const dia = data.value.filter((d) => d.bp_diastolic_avg != null).map((d) => [d.date, d.bp_diastolic_avg]);
  return {
    grid: { left: 40, right: 12, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: data.value.map((d) => d.date), axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "mmHg", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine,
      // Reference bands: normal (<120/<80), elevated (120-129), stage1 (130/80), stage2 (140/90)
    },
    series: [
      { name: "Systolic", type: "line", data: sys, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 4,
        lineStyle: { width: 2, color: t.palette.hr }, itemStyle: { color: t.palette.hr },
        markLine: {
          silent: true, symbol: "none", lineStyle: { type: "dashed" as const },
          data: [
            { yAxis: 120, lineStyle: { color: "#eab308" }, label: { formatter: "elev", color: "#eab308" } },
            { yAxis: 130, lineStyle: { color: "#f97316" }, label: { formatter: "stage 1", color: "#f97316" } },
            { yAxis: 140, lineStyle: { color: "#ef4444" }, label: { formatter: "stage 2", color: "#ef4444" } },
          ],
        },
      },
      { name: "Diastolic", type: "line", data: dia, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 4,
        lineStyle: { width: 2, color: t.palette.recovery }, itemStyle: { color: t.palette.recovery },
      },
    ],
    dataZoom: [{ type: "inside" }],
  };
});
const hasBp = computed(() => data.value.some((d) => d.bp_systolic_avg != null));

// Skin-temp card — values are deltas, so unit conversion is just × 1.8.
const skinTempOption = computed(() => {
  void chartTheme.value;
  void tempUnit.value;
  const t = chartTheme.value;
  const factor = isImperial.value ? _C_TO_F : 1;
  const normalBand = 0.5 * factor;
  const alertLevel = 1 * factor;
  const pts = data.value
    .filter((d) => d.skin_temp_delta_avg != null)
    .map((d) => [d.date, (d.skin_temp_delta_avg as number) * factor]);
  return {
    grid: { left: 40, right: 12, top: 36, bottom: 28 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: data.value.map((d) => d.date), axisLabel: t.axisLabel },
    yAxis: { type: "value", name: tempUnit.value, scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      { name: `Skin Δ ${tempUnit.value}`, type: "line", data: pts, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 3,
        lineStyle: { width: 2, color: t.palette.violet }, itemStyle: { color: t.palette.violet },
        markArea: {
          silent: true,
          data: [
            [{ yAxis: -normalBand, itemStyle: { color: "rgba(34, 197, 94, 0.08)" } }, { yAxis: normalBand }],
          ],
        },
        markLine: {
          silent: true, symbol: "none", lineStyle: { type: "dashed" as const },
          data: [{
            yAxis: alertLevel,
            lineStyle: { color: "#ef4444" },
            label: { formatter: `+${alertLevel.toFixed(1)} ${tempUnit.value}`, color: "#ef4444" },
          }],
        },
      },
    ],
    dataZoom: [{ type: "inside" }],
  };
});
const hasSkinTemp = computed(() => data.value.some((d) => d.skin_temp_delta_avg != null));

onMounted(() => { load(); loadGoal(); });
watch(range, load);

// Sober resets that fall within the loaded date range. Drops the very first
// chronological entry (start-of-tracking, not a reset). For category-axis
// charts we map each reset to its YYYY-MM-DD bucket so ECharts can land it
// on the right column.
const soberResetDates = computed<string[]>(() => {
  if (!soberStreaks.value.length || !data.value.length) return [];
  const dateSet = new Set(data.value.map((d) => d.date));
  const sortedAsc = [...soberStreaks.value].sort((a, b) =>
    a.start_at.localeCompare(b.start_at)
  );
  // Drop start-of-tracking
  const resets = sortedAsc.slice(1);
  // Bucket each reset to YYYY-MM-DD; only keep dates the chart actually has
  return resets
    .map((r) => r.start_at.slice(0, 10))
    .filter((d) => dateSet.has(d));
});

function soberMarkLineForCategory() {
  if (!showSoberResets.value || soberResetDates.value.length === 0) return undefined;
  return {
    silent: false,
    symbol: ["none", "none"],
    data: soberResetDates.value.map((d) => ({
      xAxis: d,
      lineStyle: { color: "#a78bfa", type: "dashed" as const, opacity: 0.5, width: 1 },
      label: { show: true, formatter: "🔄", position: "insideEndTop", fontSize: 12, color: "#a78bfa" },
    })),
  };
}

// === Multi-overlay chart: RHR + HRV + Recovery + sleep duration on one chart ===
const overlayOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const dates = data.value.map((d) => d.date);
  const series: any[] = [];
  const yAxes: any[] = [];

  if (overlayMetrics.value.rhr) {
    yAxes.push({
      type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true,
      name: "RHR", nameTextStyle: { color: t.palette.hr, fontSize: 9 },
    });
    series.push({
      type: "line", name: "RHR", smooth: true,
      yAxisIndex: yAxes.length - 1,
      lineStyle: { color: t.palette.hr, width: 2 },
      itemStyle: { color: t.palette.hr },
      connectNulls: true,
      data: data.value.map((d) => [d.date, d.resting_hr]),
    });
  }
  if (overlayMetrics.value.hrv) {
    yAxes.push({
      type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, scale: true, position: "right",
      name: "HRV", nameTextStyle: { color: t.palette.hrv, fontSize: 9 },
    });
    series.push({
      type: "line", name: "HRV", smooth: true,
      yAxisIndex: yAxes.length - 1,
      lineStyle: { color: t.palette.hrv, width: 2 },
      itemStyle: { color: t.palette.hrv },
      connectNulls: true,
      data: data.value.map((d) => [d.date, d.hrv_avg]),
    });
  }
  if (overlayMetrics.value.recovery) {
    yAxes.push({
      type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, scale: true, position: "right",
      name: "Recovery", nameTextStyle: { color: t.palette.recovery, fontSize: 9 },
      offset: yAxes.filter((a) => a.position === "right").length * 40,
    });
    series.push({
      type: "line", name: "Recovery", smooth: true,
      yAxisIndex: yAxes.length - 1,
      lineStyle: { color: t.palette.recovery, width: 2 },
      itemStyle: { color: t.palette.recovery },
      connectNulls: true,
      data: data.value.map((d) => [d.date, d.recovery_score]),
    });
  }
  if (overlayMetrics.value.sleep) {
    yAxes.push({
      type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, scale: true, position: "right",
      name: "Sleep h", nameTextStyle: { color: t.palette.sleep, fontSize: 9 },
      offset: yAxes.filter((a) => a.position === "right").length * 40,
    });
    series.push({
      type: "line", name: "Sleep (h)", smooth: true,
      yAxisIndex: yAxes.length - 1,
      lineStyle: { color: t.palette.sleep, width: 2, type: "dashed" },
      itemStyle: { color: t.palette.sleep },
      connectNulls: true,
      data: data.value.map((d) => [d.date, d.sleep_duration_s ? d.sleep_duration_s / 3600 : null]),
    });
  }

  // Hang the sober-reset markLine off the first series — ECharts only honours
  // one markLine per series, but since the lines are vertical and reference
  // xAxis values they render the same regardless of which series carries them.
  const reset = soberMarkLineForCategory();
  if (reset && series.length > 0) {
    series[0] = { ...series[0], markLine: reset };
  }

  return {
    grid: { left: 40, right: 60 + (yAxes.filter((a) => a.position === "right").length * 40), top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: dates, axisLabel: t.axisLabel },
    yAxis: yAxes.length > 0 ? yAxes : { type: "value" },
    tooltip: { trigger: "axis", ...t.tooltip },
    series,
    dataZoom: [{ type: "inside" }],
  };
});

// === Steps chart with goal line ===
const stepsOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const baseSeries = {
    name: "Steps",
    data: data.value.map((d) => [d.date, d.steps_total ?? 0]),
    itemStyle: { color: t.palette.steps },
    markLine: stepsGoal.value > 0 ? {
      silent: true, symbol: "none",
      lineStyle: { color: t.palette.recovery, type: "dashed" as const },
      label: { show: true, formatter: `goal ${stepsGoal.value}`, color: t.axisLabel.color, fontSize: 9 },
      data: [{ yAxis: stepsGoal.value }],
    } : undefined,
  };
  const seriesByType = {
    bar: { ...baseSeries, type: "bar" as const },
    line: { ...baseSeries, type: "line" as const, smooth: true, lineStyle: { color: t.palette.steps, width: 2 } },
    area: { ...baseSeries, type: "line" as const, smooth: true, areaStyle: { color: `${t.palette.steps}33` }, lineStyle: { color: t.palette.steps, width: 2 } },
  };
  return {
    grid: { left: 50, right: 12, top: 8, bottom: 28 },
    xAxis: { type: "category", data: data.value.map((d) => d.date), axisLabel: t.axisLabel },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [seriesByType[stepsType.value]],
    dataZoom: [{ type: "inside" }],
  };
});

// === Sleep stage stacked chart ===
const sleepStackOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const dates = data.value.map((d) => d.date);
  return {
    grid: { left: 50, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: dates, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "hours", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: t.axisLabel },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      {
        type: "bar", stack: "sleep", name: "Total sleep",
        data: data.value.map((d) => d.sleep_duration_s ? +(d.sleep_duration_s / 3600).toFixed(2) : null),
        itemStyle: { color: t.palette.sleep },
      },
    ],
    dataZoom: [{ type: "inside" }],
  };
});

const hasData = computed(() => data.value.length > 0);
const hasSelected = computed(() => Object.values(overlayMetrics.value).some(Boolean));

function preset(p: "recovery" | "training" | "sleep" | "all") {
  if (p === "recovery") overlayMetrics.value = { rhr: true, hrv: true, recovery: true, sleep: false };
  else if (p === "training") overlayMetrics.value = { rhr: true, hrv: true, recovery: false, sleep: false };
  else if (p === "sleep") overlayMetrics.value = { rhr: false, hrv: false, recovery: false, sleep: true };
  else overlayMetrics.value = { rhr: true, hrv: true, recovery: true, sleep: true };
}
</script>

<template>
  <div class="trends">
    <PageHeader title="Trends">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Trends time range" />
    </PageHeader>

    <div v-if="error" class="err">{{ error }}</div>
    <LoadState v-if="loading" />
    <EmptyState v-else-if="!hasData">
      No daily summaries yet for this range. The analytics job runs at 03:00 local each night.
    </EmptyState>

    <div v-else class="grid">
      <div id="rhr"></div>
      <Card title="Combined trend">
        <div class="toggle-row">
          <label><input type="checkbox" v-model="overlayMetrics.rhr"/><span>RHR</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.hrv"/><span>HRV</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.recovery"/><span>Recovery</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.sleep"/><span>Sleep h</span></label>
          <label v-if="soberResetDates.length > 0">
            <input type="checkbox" v-model="showSoberResets"/>
            <span>🔄 Sober resets ({{ soberResetDates.length }})</span>
          </label>
          <span class="presets">presets:</span>
          <button class="preset" @click="preset('recovery')">recovery</button>
          <button class="preset" @click="preset('training')">training</button>
          <button class="preset" @click="preset('sleep')">sleep</button>
          <button class="preset" @click="preset('all')">all</button>
        </div>
        <div class="chart"><VChart v-if="hasSelected" :option="overlayOption" autoresize/></div>
      </Card>

      <Card title="Steps per day">
        <div class="toggle-row">
          <span>Type:</span>
          <button class="preset" :class="{ active: stepsType === 'bar' }" @click="stepsType = 'bar'">bar</button>
          <button class="preset" :class="{ active: stepsType === 'line' }" @click="stepsType = 'line'">line</button>
          <button class="preset" :class="{ active: stepsType === 'area' }" @click="stepsType = 'area'">area</button>
          <span style="margin-left: 1rem;">Goal:</span>
          <input class="goal-input" type="number" v-model.number="stepsGoal" min="0" step="500"/>
        </div>
        <div class="chart"><VChart :option="stepsOption" autoresize/></div>
      </Card>

      <Card title="Sleep duration">
        <div class="chart"><VChart :option="sleepStackOption" autoresize/></div>
      </Card>

      <Card title="Body weight">
        <EmptyState v-if="!hasWeight" mini>
          No weight data yet. Import a Fitbit/Garmin ZIP from Settings, or POST to /ingest/batch.
        </EmptyState>
        <template v-else>
          <div class="weight-stats">
            <span><strong>{{ fmtWeight(weightStats.latest_kg) }}</strong> latest</span>
            <span class="muted">range: {{ fmtWeight(weightStats.min_kg) }} – {{ fmtWeight(weightStats.max_kg) }}</span>
            <span class="muted">avg: {{ fmtWeight(weightStats.avg_kg) }}</span>
          </div>
          <div class="goal-row">
            <template v-if="goalKg != null">
              <span class="muted">Goal:</span> <strong>{{ fmtWeight(goalKg) }}</strong>
              <span v-if="goalCaption" class="muted" style="margin-left: 0.6rem;">{{ goalCaption }}</span>
            </template>
            <span v-else class="muted">No weight goal set.</span>
            <RouterLink to="/goals" class="muted" style="margin-left: 0.6rem;">Edit goal</RouterLink>
            <RouterLink v-if="!heightCm" to="/settings?tab=profile" class="muted" style="margin-left: 0.6rem;">Add height for BMI bands</RouterLink>
          </div>
          <div class="chart"><VChart :option="weightOption" autoresize/></div>
        </template>
      </Card>

      <Card v-if="hasBodyComp" title="Body composition (lean + fat mass)">
        <div class="chart"><VChart :option="bodyCompOption" autoresize/></div>
      </Card>

      <Card v-if="hasBp" title="Blood pressure">
        <div class="chart"><VChart :option="bpOption" autoresize/></div>
      </Card>

      <div id="skin-temp"></div>
      <Card v-if="hasSkinTemp" title="Skin temperature (Δ from baseline)">
        <div class="chart"><VChart :option="skinTempOption" autoresize/></div>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; gap: 1rem; margin-top: 1rem; }
.chart { width: 100%; height: 280px; }
.chart > * { width: 100%; height: 100%; }

.toggle-row { display: flex; gap: 0.8rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.toggle-row label { display: flex; align-items: center; gap: 0.3rem; cursor: pointer; }
.toggle-row .presets { color: var(--muted-2); margin-left: 0.5rem; }
.preset {
  background: transparent; color: var(--muted); border: 1px solid var(--border); border-radius: 4px;
  padding: 0.15rem 0.5rem; cursor: pointer; font-size: 0.75rem;
}
.preset:hover { color: var(--text); }
.preset.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.goal-input {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.15rem 0.4rem; width: 80px; font-family: inherit;
}

.weight-stats { display: flex; gap: 1rem; align-items: baseline; margin-bottom: 0.5rem; font-size: 0.95rem; }
.weight-stats .muted { color: var(--muted); font-size: 0.8rem; }
.goal-row { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.8rem; }
.goal-row .muted { color: var(--muted); }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
