<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import { weightVal, weightUnit, fmtWeight, weightToKg, isImperial, tempUnit } from "@/units";

const _C_TO_F = 1.8;  // ΔF = ΔC × 9/5

type Range = "7d" | "30d" | "90d" | "365d";
const RANGES: { key: Range; label: string; days: number }[] = [
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "90 days", days: 90 },
  { key: "365d", label: "1 year", days: 365 },
];

type ChartType = "line" | "bar" | "area";

const range = ref<Range>("30d");
const data = ref<TodaySummary[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const overlayMetrics = ref({ rhr: true, hrv: true, recovery: true, sleep: false });
const stepsType = ref<ChartType>("bar");
const stepsGoal = ref(8000);

type WeightPoint = { time: string; weight_kg: number | null; body_fat_pct: number | null; bmi: number | null; lean_mass_kg: number | null; source: string };
const weightSeries = ref<WeightPoint[]>([]);
const weightStats = ref<{ latest_kg: number | null; min_kg: number | null; max_kg: number | null; avg_kg: number | null }>({ latest_kg: null, min_kg: null, max_kg: null, avg_kg: null });

// Goal tracker — persisted to localStorage (single-user app, no profile yet)
const heightCm = ref<number>(parseFloat(localStorage.getItem("myvitals.height_cm") ?? "178"));
const targetKg = ref<number | null>(
  localStorage.getItem("myvitals.target_kg")
    ? parseFloat(localStorage.getItem("myvitals.target_kg")!) : null,
);
const targetDateStr = ref<string>(localStorage.getItem("myvitals.target_date") ?? "");
watch(heightCm, (v) => localStorage.setItem("myvitals.height_cm", String(v)));
watch(targetKg, (v) => v == null ? localStorage.removeItem("myvitals.target_kg")
                                  : localStorage.setItem("myvitals.target_kg", String(v)));
watch(targetDateStr, (v) => v ? localStorage.setItem("myvitals.target_date", v)
                              : localStorage.removeItem("myvitals.target_date"));

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const since = new Date();
    since.setDate(since.getDate() - days);
    const [summary, weight] = await Promise.all([
      api.summaryRange(since),
      api.weight({ since }).catch(() => ({ points: [], latest_kg: null, min_kg: null, max_kg: null, avg_kg: null })),
    ]);
    data.value = summary;
    weightSeries.value = weight.points;
    weightStats.value = { latest_kg: weight.latest_kg, min_kg: weight.min_kg, max_kg: weight.max_kg, avg_kg: weight.avg_kg };
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
  const heightM = (heightCm.value || 178) / 100;

  if (pts.length) {
    series.push({
      name: "Daily weight", type: "line", data: pts,
      symbol: "circle", symbolSize: 3, connectNulls: false,
      lineStyle: { width: 1, color: t.palette.accent, opacity: 0.45 },
      itemStyle: { color: t.palette.accent }, yAxisIndex: 0,
      // Render BMI bands behind the daily line (only attached once).
      markArea: {
        silent: true,
        data: bmiBands(heightM),
      },
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
  if (targetKg.value != null && targetDateStr.value && pts.length) {
    const start = pts[0];
    const targetTs = new Date(targetDateStr.value).getTime();
    const targetDisplay = weightVal(targetKg.value);
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

// Goal arrival projection: linear regression on last 28d of 7d MA.
const goalProjection = computed(() => {
  if (targetKg.value == null) return null;
  const raw = weightSeries.value
    .filter((p) => p.weight_kg != null)
    .map((p) => ({ t: new Date(p.time).getTime(), v: p.weight_kg as number }))
    .sort((a, b) => a.t - b.t);
  const ma = rolling7Avg(raw);
  if (ma.length < 7) return null;
  const cutoff = ma[ma.length - 1].t - 28 * 86400 * 1000;
  const recent = ma.filter((p) => p.t >= cutoff);
  if (recent.length < 5) return null;
  // Simple OLS: v = a*t + b (t in days from first point)
  const t0 = recent[0].t;
  const xs = recent.map((p) => (p.t - t0) / 86400_000);
  const ys = recent.map((p) => p.v);
  const n = xs.length;
  const mx = xs.reduce((s, x) => s + x, 0) / n;
  const my = ys.reduce((s, y) => s + y, 0) / n;
  let num = 0; let den = 0;
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (ys[i] - my); den += (xs[i] - mx) ** 2; }
  if (den === 0) return null;
  const a = num / den;  // kg per day
  if (Math.abs(a) < 0.001) return { etaDate: null, perDay: a, headed: "flat" as const };
  const last = recent[recent.length - 1];
  const headingTowards = (targetKg.value < last.v) === (a < 0);
  if (!headingTowards) return { etaDate: null, perDay: a, headed: "wrong" as const };
  const daysToGoal = (targetKg.value - last.v) / a;
  const etaDate = new Date(last.t + daysToGoal * 86400_000);
  return { etaDate, perDay: a, headed: "right" as const };
});

onMounted(load);
watch(range, load);

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
    <header class="head">
      <h1>Trends</h1>
      <div class="picker">
        <button v-for="r in RANGES" :key="r.key"
                :class="{ active: range === r.key }" @click="range = r.key">{{ r.label }}</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="!hasData" class="empty">
      No daily summaries yet for this range. The analytics job runs at 03:00 local each night.
    </div>

    <div v-else class="grid">
      <Card title="Combined trend">
        <div class="toggle-row">
          <label><input type="checkbox" v-model="overlayMetrics.rhr"/><span>RHR</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.hrv"/><span>HRV</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.recovery"/><span>Recovery</span></label>
          <label><input type="checkbox" v-model="overlayMetrics.sleep"/><span>Sleep h</span></label>
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
        <div v-if="!hasWeight" class="empty-mini">
          No weight data yet. Import a Fitbit/Garmin ZIP from Settings, or POST to /ingest/batch.
        </div>
        <template v-else>
          <div class="weight-stats">
            <span><strong>{{ fmtWeight(weightStats.latest_kg) }}</strong> latest</span>
            <span class="muted">range: {{ fmtWeight(weightStats.min_kg) }} – {{ fmtWeight(weightStats.max_kg) }}</span>
            <span class="muted">avg: {{ fmtWeight(weightStats.avg_kg) }}</span>
          </div>
          <div class="goal-row">
            <span class="muted">Height ({{ isImperial ? 'in' : 'cm' }}):</span>
            <input :value="isImperial ? (heightCm / 2.54).toFixed(1) : heightCm"
                   @change="heightCm = isImperial
                     ? parseFloat(($event.target as HTMLInputElement).value) * 2.54
                     : parseFloat(($event.target as HTMLInputElement).value)"
                   type="number" class="goal-input"
                   :min="isImperial ? 20 : 50" :max="isImperial ? 100 : 250"
                   step="0.1"/>
            <span class="muted" style="margin-left: 0.6rem;">Goal ({{ weightUnit }}):</span>
            <input :value="targetKg != null ? weightVal(targetKg)?.toFixed(1) : ''"
                   @change="targetKg = ($event.target as HTMLInputElement).value ? weightToKg(parseFloat(($event.target as HTMLInputElement).value)) : null"
                   type="number" class="goal-input" min="20" max="660" step="0.1" :placeholder="weightUnit"/>
            <input v-model="targetDateStr" type="date" class="goal-input" style="width: 140px;"/>
            <span v-if="goalProjection" class="muted" style="margin-left: 0.6rem;">
              <template v-if="goalProjection.etaDate">
                ETA: {{ goalProjection.etaDate.toISOString().slice(0,10) }}
                ({{ ((weightVal(goalProjection.perDay * 7) ?? 0)).toFixed(2) }} {{ weightUnit }}/wk)
              </template>
              <template v-else-if="goalProjection.headed === 'wrong'">
                <span style="color: var(--bad);">⚠</span> trending away from goal
              </template>
              <template v-else>flat trend — no ETA</template>
            </span>
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

      <Card v-if="hasSkinTemp" title="Skin temperature (Δ from baseline)">
        <div class="chart"><VChart :option="skinTempOption" autoresize/></div>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; }
h1 { margin: 0; }
.picker { display: flex; gap: 0.4rem; }
.picker button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.85rem; }
.picker button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }

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

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.empty-mini { color: var(--muted-2); padding: 1.2rem 0; text-align: center; font-size: 0.85rem; }
.weight-stats { display: flex; gap: 1rem; align-items: baseline; margin-bottom: 0.5rem; font-size: 0.95rem; }
.weight-stats .muted { color: var(--muted); font-size: 0.8rem; }
.goal-row { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.8rem; }
.goal-row .muted { color: var(--muted); }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
