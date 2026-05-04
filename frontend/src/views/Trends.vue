<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";

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

const weightOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const pts = weightSeries.value.filter((p) => p.weight_kg != null).map((p) => [p.time, p.weight_kg]);
  const fatPts = weightSeries.value.filter((p) => p.body_fat_pct != null).map((p) => [p.time, p.body_fat_pct]);
  const series: Array<Record<string, unknown>> = [];
  if (pts.length) series.push({
    name: "Weight (kg)", type: "line", data: pts, smooth: true,
    symbol: "circle", symbolSize: 5, connectNulls: true,
    lineStyle: { width: 2, color: t.palette.accent },
    itemStyle: { color: t.palette.accent }, yAxisIndex: 0,
  });
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
      { type: "value", name: "kg", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
      { type: "value", name: "%", scale: true, axisLabel: t.axisLabel, splitLine: { show: false } },
    ],
    series,
    dataZoom: [{ type: "inside" }],
  };
});
const hasWeight = computed(() => weightSeries.value.some((p) => p.weight_kg != null));

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
            <span><strong>{{ weightStats.latest_kg?.toFixed(1) }}</strong> kg latest</span>
            <span class="muted">range: {{ weightStats.min_kg?.toFixed(1) }} – {{ weightStats.max_kg?.toFixed(1) }}</span>
            <span class="muted">avg: {{ weightStats.avg_kg?.toFixed(1) }}</span>
          </div>
          <div class="chart"><VChart :option="weightOption" autoresize/></div>
        </template>
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
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
