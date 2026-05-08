<script setup lang="ts">
/**
 * Heart Rate detail view — live trace + history + zones + period
 * comparison. Uses existing /query/heartrate, /summary/range, /query/hrv
 * endpoints; no backend changes required.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { HeartRateSeries, HrvSeries, TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import {
  baseTimeOption, meanMarkLine, timeAxisFormatter,
} from "@/components/charts/chartHelpers";

type RangeKey = "24h" | "7d" | "30d" | "90d" | "1y";
const RANGES: Array<{ key: RangeKey; label: string; hours: number; days: number }> = [
  { key: "24h", label: "24h",  hours: 24,         days: 1 },
  { key: "7d",  label: "7d",   hours: 24 * 7,     days: 7 },
  { key: "30d", label: "30d",  hours: 24 * 30,    days: 30 },
  { key: "90d", label: "90d",  hours: 24 * 90,    days: 90 },
  { key: "1y",  label: "1 yr", hours: 24 * 365,   days: 365 },
];
const range = ref<RangeKey>("24h");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);

const hr = ref<HeartRateSeries | null>(null);
const hrv = ref<HrvSeries | null>(null);
const dailyRows = ref<TodaySummary[]>([]);    // for the selected window
const priorRows = ref<TodaySummary[]>([]);    // matching prior window for delta
const profile = ref<{ max_hr_estimated?: number | null; resting_hr_baseline?: number | null } | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date(Date.now() - cur.value.hours * 3600 * 1000);
    // Live trace caps at 30d to keep payloads reasonable; longer ranges
    // skip the trace and lean on daily aggregates only.
    const liveCap = Math.min(cur.value.hours, 24 * 30);
    const liveSince = new Date(Date.now() - liveCap * 3600 * 1000);

    const dailySince = new Date();
    dailySince.setHours(0, 0, 0, 0);
    dailySince.setDate(dailySince.getDate() - cur.value.days + 1);
    const priorSince = new Date(dailySince);
    priorSince.setDate(priorSince.getDate() - cur.value.days);
    const priorUntil = new Date(dailySince);

    const [liveHr, liveHrv, daily, prior, p] = await Promise.all([
      api.heartRate({ since: liveSince }),
      api.hrv({ since: liveSince }),
      api.summaryRange(dailySince),
      api.summaryRange(priorSince, priorUntil),
      api.getProfile().catch(() => null),
    ]);
    hr.value = liveHr;
    hrv.value = liveHrv;
    dailyRows.value = daily;
    priorRows.value = prior;
    profile.value = p ? {
      max_hr_estimated: p.derived?.max_hr_estimated ?? null,
      resting_hr_baseline: p.resting_hr_baseline ?? null,
    } : null;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const xWindow = computed(() => {
  const max = Date.now();
  const span = Math.min(cur.value.hours, 24 * 30) * 3600 * 1000;
  return { min: max - span, max };
});

// ── Headline cards ──
const periodAvgRhr = computed(() =>
  avg(dailyRows.value.map((r) => r.resting_hr).filter((v): v is number => v != null)),
);
const priorAvgRhr = computed(() =>
  avg(priorRows.value.map((r) => r.resting_hr).filter((v): v is number => v != null)),
);
const rhrDelta = computed(() => {
  if (periodAvgRhr.value == null || priorAvgRhr.value == null) return null;
  return periodAvgRhr.value - priorAvgRhr.value;
});

const periodAvgHrv = computed(() =>
  avg(dailyRows.value.map((r) => r.hrv_avg).filter((v): v is number => v != null)),
);
const priorAvgHrv = computed(() =>
  avg(priorRows.value.map((r) => r.hrv_avg).filter((v): v is number => v != null)),
);
const hrvDelta = computed(() => {
  if (periodAvgHrv.value == null || priorAvgHrv.value == null) return null;
  return periodAvgHrv.value - priorAvgHrv.value;
});

const maxHrInWindow = computed(() => {
  if (!hr.value) return null;
  return hr.value.max_bpm;
});
const minHrInWindow = computed(() => {
  if (!hr.value) return null;
  return hr.value.min_bpm;
});

function avg(xs: number[]): number | null {
  if (!xs.length) return null;
  return xs.reduce((s, v) => s + v, 0) / xs.length;
}

// ── Live trace ──
const traceOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const opt = baseTimeOption() as Record<string, any>;
  opt.xAxis = { ...(opt.xAxis as object), min: xWindow.value.min, max: xWindow.value.max };
  if (!hr.value || hr.value.points.length === 0) return null;
  const series: any[] = [
    {
      type: "line",
      name: "HR",
      showSymbol: false,
      smooth: true,
      lineStyle: { color: t.palette.hr, width: 1.5 },
      areaStyle: { color: `${t.palette.hr}22` },
      data: hr.value.points.map((p) => [p.time, p.value]),
      ...(meanMarkLine(hr.value.avg ?? null, "avg") ?? {}),
    },
  ];
  return { ...opt, series, tooltip: { ...t.tooltip, trigger: "axis" } };
});

// ── Daily resting HR over time ──
const restingOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (dailyRows.value.length === 0) return null;
  const data = dailyRows.value
    .filter((r) => r.resting_hr != null)
    .map((r) => [r.date, r.resting_hr]);
  if (data.length === 0) return null;
  return {
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: t.splitLine,
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
    },
    tooltip: { ...t.tooltip, trigger: "axis" },
    series: [
      {
        type: "line",
        name: "Resting HR",
        showSymbol: data.length < 90,
        smooth: true,
        lineStyle: { color: t.palette.hr, width: 1.8 },
        itemStyle: { color: t.palette.hr },
        areaStyle: { color: `${t.palette.hr}1f` },
        data,
        ...(profile.value?.resting_hr_baseline
          ? (meanMarkLine(profile.value.resting_hr_baseline, "baseline") ?? {})
          : {}),
      },
    ],
  };
});

// ── Daily HRV alongside ──
const hrvOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (dailyRows.value.length === 0) return null;
  const data = dailyRows.value
    .filter((r) => r.hrv_avg != null)
    .map((r) => [r.date, r.hrv_avg]);
  if (data.length === 0) return null;
  return {
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: t.splitLine,
    },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis" },
    series: [
      {
        type: "line",
        name: "HRV (RMSSD ms)",
        showSymbol: data.length < 90,
        smooth: true,
        lineStyle: { color: t.palette.hrv, width: 1.8 },
        itemStyle: { color: t.palette.hrv },
        areaStyle: { color: `${t.palette.hrv}1f` },
        data,
      },
    ],
  };
});

// ── Time in zone (computed from live trace; only meaningful for ≤ 30d) ──
const ZONE_DEFS = [
  { name: "Z1 · easy",     min: 0.50, color: "#38bdf8" },
  { name: "Z2 · aerobic",  min: 0.60, color: "#22c55e" },
  { name: "Z3 · tempo",    min: 0.70, color: "#eab308" },
  { name: "Z4 · threshold",min: 0.80, color: "#f97316" },
  { name: "Z5 · max",      min: 0.90, color: "#ef4444" },
];
const zonesOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr.value || hr.value.points.length === 0) return null;
  const maxHr = profile.value?.max_hr_estimated ?? 187;
  const buckets = ZONE_DEFS.map(() => 0);
  // Each consecutive pair of points is a segment; weight time-in-zone
  // by segment duration (samples are non-uniform).
  const pts = hr.value.points;
  for (let i = 1; i < pts.length; i++) {
    const dt = (new Date(pts[i].time).getTime() - new Date(pts[i - 1].time).getTime()) / 1000;
    if (dt <= 0 || dt > 600) continue;  // skip > 10-min gaps
    const v = pts[i].value;
    const pct = v / maxHr;
    let z = 0;
    for (let k = ZONE_DEFS.length - 1; k >= 0; k--) {
      if (pct >= ZONE_DEFS[k].min) { z = k; break; }
    }
    buckets[z] += dt;
  }
  const total = buckets.reduce((s, v) => s + v, 0);
  if (total === 0) return null;
  const data = buckets.map((s, i) => ({
    value: +(s / 60).toFixed(0),
    itemStyle: { color: ZONE_DEFS[i].color },
  }));
  return {
    grid: { left: 90, right: 30, top: 12, bottom: 28 },
    xAxis: { type: "value", axisLabel: { ...t.axisLabel, formatter: "{value} min" },
             splitLine: t.splitLine },
    yAxis: { type: "category", data: ZONE_DEFS.map((z) => z.name),
             axisLabel: { ...t.axisLabel, fontSize: 11 } },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
               formatter: (p: any) => `${p[0].name}: ${p[0].value} min` },
    series: [{ type: "bar", data, barWidth: 16,
               label: { show: true, position: "right", color: t.axisLabel.color, fontSize: 10,
                        formatter: (p: any) =>
                          total > 0 ? `${((p.data.value * 60 / total) * 100).toFixed(0)}%` : "" } }],
  };
});
</script>

<template>
  <section class="hr">
    <header class="page-head">
      <h1>Heart rate</h1>
      <div class="ranges">
        <button v-for="r in RANGES" :key="r.key"
                :class="{ pill: true, active: range === r.key }"
                @click="range = r.key">{{ r.label }}</button>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="loading" class="muted">Loading…</p>

    <template v-else>
      <!-- Headline summary cards -->
      <div class="cards">
        <Card title="Resting HR" :flat="true">
          <div class="big">
            {{ periodAvgRhr != null ? Math.round(periodAvgRhr) : "—" }}
            <span class="unit">bpm</span>
          </div>
          <div class="delta" :class="rhrDelta != null && rhrDelta < 0 ? 'good' : (rhrDelta != null && rhrDelta > 0 ? 'bad' : '')">
            <template v-if="rhrDelta != null">
              {{ rhrDelta < 0 ? "▼" : "▲" }} {{ Math.abs(rhrDelta).toFixed(1) }} vs prior
            </template>
            <template v-else>—</template>
          </div>
        </Card>

        <Card title="HRV (RMSSD)" :flat="true">
          <div class="big">
            {{ periodAvgHrv != null ? Math.round(periodAvgHrv) : "—" }}
            <span class="unit">ms</span>
          </div>
          <div class="delta" :class="hrvDelta != null && hrvDelta > 0 ? 'good' : (hrvDelta != null && hrvDelta < 0 ? 'bad' : '')">
            <template v-if="hrvDelta != null">
              {{ hrvDelta > 0 ? "▲" : "▼" }} {{ Math.abs(hrvDelta).toFixed(1) }} vs prior
            </template>
            <template v-else>—</template>
          </div>
        </Card>

        <Card title="Max HR (window)" :flat="true">
          <div class="big">
            {{ maxHrInWindow != null ? Math.round(maxHrInWindow) : "—" }}
            <span class="unit">bpm</span>
          </div>
          <div class="muted-sm" v-if="profile?.max_hr_estimated">
            est max {{ profile.max_hr_estimated }}
          </div>
        </Card>

        <Card title="Min HR (window)" :flat="true">
          <div class="big">
            {{ minHrInWindow != null ? Math.round(minHrInWindow) : "—" }}
            <span class="unit">bpm</span>
          </div>
        </Card>
      </div>

      <!-- Live trace -->
      <Card v-if="traceOption" :title="`HR trace · ${cur.label === '1 yr' ? 'last 30d' : cur.label}`" :flat="true">
        <div class="chart"><VChart :option="traceOption" autoresize/></div>
      </Card>

      <!-- Time in zone -->
      <Card v-if="zonesOption" title="Time in zone" :flat="true">
        <div class="chart-sm"><VChart :option="zonesOption" autoresize/></div>
        <p class="hint">
          Bucketed from the live trace ({{ cur.label === "1 yr" ? "last 30d capped" : cur.label }})
          using profile max HR.
          <span v-if="profile?.max_hr_estimated">Max HR: {{ profile.max_hr_estimated }}.</span>
        </p>
      </Card>

      <!-- Daily resting HR -->
      <Card v-if="restingOption" :title="`Daily resting HR · ${cur.label}`" :flat="true">
        <div class="chart"><VChart :option="restingOption" autoresize/></div>
      </Card>

      <!-- Daily HRV -->
      <Card v-if="hrvOption" :title="`Daily HRV · ${cur.label}`" :flat="true">
        <div class="chart"><VChart :option="hrvOption" autoresize/></div>
      </Card>
    </template>
  </section>
</template>

<style scoped>
.hr { max-width: 1100px; margin: 0 auto; padding: 1rem; }
.page-head { display: flex; align-items: center; justify-content: space-between;
             margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem; }
.page-head h1 { margin: 0; font-size: 1.4rem; }
.ranges { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.pill { background: var(--surface); color: var(--muted); border: 1px solid var(--border);
        border-radius: 999px; padding: 0.3rem 0.85rem; cursor: pointer; font-size: 0.8rem; }
.pill.active { background: var(--accent); color: var(--surface); border-color: var(--accent); }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
         gap: 0.6rem; margin-bottom: 0.8rem; }
.big { font-size: 1.7rem; font-weight: 600; font-feature-settings: "tnum"; line-height: 1.1; }
.unit { font-size: 0.8rem; color: var(--muted); font-weight: 500; margin-left: 0.2rem; }
.delta { font-size: 0.78rem; color: var(--muted); margin-top: 0.2rem; font-feature-settings: "tnum"; }
.delta.good { color: #22c55e; }
.delta.bad  { color: #ef4444; }
.muted-sm { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; }

.chart    { width: 100%; height: 260px; }
.chart-sm { width: 100%; height: 220px; }
.chart > *, .chart-sm > * { width: 100%; height: 100%; }

.muted { color: var(--muted); }
.err { color: #ef4444; }
.hint { color: var(--muted); font-size: 0.78rem; margin-top: 0.4rem; }
</style>
