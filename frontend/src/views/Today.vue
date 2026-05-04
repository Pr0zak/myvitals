<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import { api } from "@/api/client";
import type {
  Activity, Annotation, HeartRateSeries, HrvSeries,
  SleepNight, StepsSeries, TodaySummary,
} from "@/api/types";
import { chartTheme } from "@/theme";
import { annotationMarkPoint, baseTimeOption, meanMarkLine, workoutMarkArea } from "@/components/charts/chartHelpers";

import Card from "@/components/Card.vue";
import RecoveryCard from "@/components/RecoveryCard.vue";
import SleepCard from "@/components/SleepCard.vue";
import StepsCard from "@/components/StepsCard.vue";

type Range = "6h" | "24h" | "3d" | "7d";
const RANGES: { key: Range; hours: number; label: string }[] = [
  { key: "6h", hours: 6, label: "6h" },
  { key: "24h", hours: 24, label: "24h" },
  { key: "3d", hours: 72, label: "3d" },
  { key: "7d", hours: 168, label: "7d" },
];

const range = ref<Range>("24h");
const summary = ref<TodaySummary | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const hrv = ref<HrvSeries | null>(null);
const sleep = ref<SleepNight | null>(null);
const steps = ref<StepsSeries | null>(null);
const activities = ref<Activity[]>([]);
const annotations = ref<Annotation[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

// Chart toggles
const showWorkouts = ref(true);
const showAnnotations = ref(true);
const showHrv = ref(false);
const showMean = ref(true);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const hours = RANGES.find((r) => r.key === range.value)!.hours;
    const since = new Date(Date.now() - hours * 3600 * 1000);
    const [s, h, hv, sl, st, a, an] = await Promise.all([
      api.todaySummary(),
      api.heartRate({ since }),
      api.hrv({ since }),
      api.lastSleep(),
      api.steps({ since }),
      api.activities({ since, limit: 50 }),
      api.listAnnotations({ since, limit: 200 }),
    ]);
    summary.value = s;
    hr.value = h;
    hrv.value = hv;
    sleep.value = sl;
    steps.value = st;
    activities.value = a;
    annotations.value = an;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(range, load);

const hrSeriesOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const opt = baseTimeOption() as Record<string, any>;
  if (!hr.value) return opt;

  const hrPoints = hr.value.points.map((p) => [p.time, p.value]);
  const series: any[] = [
    {
      type: "line",
      name: "HR",
      showSymbol: false,
      smooth: true,
      lineStyle: { color: t.palette.hr, width: 1.5 },
      areaStyle: { color: `${t.palette.hr}22` },
      data: hrPoints,
      ...(showWorkouts.value && activities.value.length > 0
        ? { markArea: workoutMarkArea(activities.value) }
        : {}),
      ...(showMean.value && hr.value.avg !== null
        ? { markLine: meanMarkLine(hr.value.avg, "avg HR") }
        : {}),
      ...(showAnnotations.value && annotations.value.length > 0
        ? { markPoint: annotationMarkPoint(annotations.value, hr.value.max_bpm ?? 100) }
        : {}),
    },
  ];

  if (showHrv.value && hrv.value && hrv.value.points.length > 0) {
    series.push({
      type: "line",
      name: "HRV",
      yAxisIndex: 1,
      showSymbol: false,
      smooth: true,
      lineStyle: { color: t.palette.hrv, width: 1.2, type: "dashed" },
      data: hrv.value.points.map((p) => [p.time, p.value]),
    });
    opt.yAxis = [
      { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true,
        name: "bpm", nameTextStyle: t.axisLabel },
      { type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, scale: true,
        name: "ms", nameTextStyle: t.axisLabel, position: "right" },
    ];
  }

  opt.series = series;
  opt.legend = { show: showHrv.value, textStyle: t.axisLabel, top: 4 };
  return opt;
});

const stepsBarOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!steps.value || steps.value.points.length === 0) return null;
  return {
    grid: { left: 36, right: 12, top: 8, bottom: 24 },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "bar",
      data: steps.value.points.map((p) => [p.time, p.value]),
      itemStyle: { color: t.palette.steps },
    }],
  };
});

const subtitleHr = computed(() => {
  if (!hr.value || hr.value.points.length === 0) return "no data";
  const a = hr.value.avg, mn = hr.value.min_bpm, mx = hr.value.max_bpm;
  return `${hr.value.points.length} pts · avg ${Math.round(a ?? 0)} · min ${Math.round(mn ?? 0)} · max ${Math.round(mx ?? 0)}`;
});
</script>

<template>
  <div class="today">
    <header class="head">
      <h1>Today</h1>
      <div class="controls">
        <div class="range">
          <button v-for="r in RANGES" :key="r.key"
                  :class="{ active: range === r.key }" @click="range = r.key">
            {{ r.label }}
          </button>
        </div>
        <button class="ghost" @click="load" :disabled="loading">{{ loading ? "…" : "↻" }}</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>

    <div v-if="!loading">
      <!-- top stats row -->
      <div class="grid stats">
        <RecoveryCard
          :score="summary?.recovery_score ?? null"
          :rhr="summary?.resting_hr ?? null"
          :hrv="summary?.hrv_avg ?? null"
        />
        <StepsCard :total="summary?.steps_total ?? steps?.total ?? 0" />
        <SleepCard :sleep="sleep" />
      </div>

      <!-- HR chart with toggles -->
      <Card title="Heart rate" :subtitle="subtitleHr">
        <div class="toggle-row">
          <label v-if="activities.length > 0">
            <input type="checkbox" v-model="showWorkouts"/>
            <span>Workouts ({{ activities.length }})</span>
          </label>
          <label v-if="hrv && hrv.points.length > 0">
            <input type="checkbox" v-model="showHrv"/>
            <span>HRV overlay</span>
          </label>
          <label v-if="annotations.length > 0">
            <input type="checkbox" v-model="showAnnotations"/>
            <span>Annotations ({{ annotations.length }})</span>
          </label>
          <label>
            <input type="checkbox" v-model="showMean"/>
            <span>Mean line</span>
          </label>
        </div>
        <div class="chart-wrap">
          <VChart v-if="hr && hr.points.length > 0" :option="hrSeriesOption" autoresize />
          <div v-else class="empty">No HR data in this range</div>
        </div>
      </Card>

      <!-- steps bar chart -->
      <Card title="Steps" :subtitle="`${steps?.total ?? 0} total`">
        <div class="chart-wrap small">
          <VChart v-if="stepsBarOption" :option="stepsBarOption" autoresize />
          <div v-else class="empty">No step data</div>
        </div>
      </Card>
    </div>

    <div v-if="summary?.last_sync" class="footer">
      Last sync: {{ new Date(summary.last_sync).toLocaleString() }}
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }
h1 { margin: 0; }
.controls { display: flex; gap: 0.6rem; align-items: center; }
.range { display: flex; gap: 0.25rem; }
.range button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.8rem; }
.range button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.55rem; cursor: pointer; font-size: 0.9rem; }

.grid { display: grid; gap: 1rem; margin-bottom: 1rem; }
.stats { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }

.toggle-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.toggle-row label { display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none; }

.chart-wrap { flex: 1; min-height: 280px; display: flex; }
.chart-wrap.small { min-height: 140px; }
.chart-wrap > * { flex: 1; }
.empty { color: var(--muted-2); align-self: center; margin: auto; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
.footer { margin-top: 1.5rem; color: var(--muted-2); font-size: 0.8rem; text-align: right; }
</style>
