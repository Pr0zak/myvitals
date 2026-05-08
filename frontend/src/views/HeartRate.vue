<script setup lang="ts">
/**
 * Heart Rate detail view — live 24h trace + history + zones +
 * comparison + four extra surfaces (distribution histogram, weekday
 * pattern, activity-HR correlation, year-over-year overlay).
 *
 * Performance rule: live HR samples only ever come back for the most
 * recent 24h. Longer ranges (7d / 30d / 90d / 1y) lean on daily
 * aggregates from /summary/range, which is small no matter the span.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type {
  Activity, HeartRateSeries, HrvSeries, TodaySummary,
} from "@/api/types";
import { chartTheme } from "@/theme";
import {
  meanMarkLine, sleepMarkArea, soberResetMarkLine, timeAxisFormatter,
  workoutMarkArea,
} from "@/components/charts/chartHelpers";
import type { SleepNight } from "@/api/types";

type RangeKey = "24h" | "7d" | "30d" | "90d" | "1y";
const RANGES: Array<{ key: RangeKey; label: string; days: number }> = [
  { key: "24h", label: "24h", days: 1 },
  { key: "7d",  label: "7d",  days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "1y",  label: "1 yr", days: 365 },
];
const range = ref<RangeKey>("7d");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);

const hr24 = ref<HeartRateSeries | null>(null);
const hrv24 = ref<HrvSeries | null>(null);
const dailyRows = ref<TodaySummary[]>([]);
const priorRows = ref<TodaySummary[]>([]);
const yearAgoRows = ref<TodaySummary[]>([]);
const activities = ref<Activity[]>([]);
// 24h overlays: activities (cardio + strength), sober resets, last sleep
const activities24 = ref<Activity[]>([]);
const soberResets24 = ref<Array<{ start_at: string }>>([]);
const lastSleep = ref<SleepNight | null>(null);
const profile = ref<{
  max_hr_estimated?: number | null;
  resting_hr_baseline?: number | null;
} | null>(null);
const loading = ref(true);
const traceLoaded = ref(false);  // 24h trace only loads once
const error = ref<string | null>(null);

async function loadTrace() {
  if (traceLoaded.value) return;
  try {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const sinceMs = since.getTime();
    const [liveHr, liveHrv, acts, sleep, swo, sbHist] = await Promise.all([
      api.heartRate({ since }),
      api.hrv({ since }),
      api.activities({ since, limit: 30 }),
      api.lastSleep().catch(() => null),
      api.strengthWorkouts({ limit: 5 }).catch(() => ({ count: 0, workouts: [] })),
      api.soberHistory(50).catch(() => []),
    ]);
    hr24.value = liveHr;
    hrv24.value = liveHrv;

    // Merge strength workouts that overlap the 24h window into the
    // activity list as Activity-shaped rows, so workoutMarkArea can
    // render them as bands alongside cardio activities.
    const strengthAsActivity: Activity[] = (swo.workouts ?? [])
      .filter((w) => w.started_at && w.completed_at)
      .map((w) => {
        const start = new Date(w.started_at!).getTime();
        const end = new Date(w.completed_at!).getTime();
        return {
          source: "strength", source_id: String(w.id),
          type: "strength",
          name: `${w.split_focus.replace(/_/g, " ")} workout`,
          start_at: w.started_at!,
          duration_s: Math.max(0, Math.round((end - start) / 1000)),
          distance_m: null, elevation_gain_m: null,
          avg_hr: w.avg_hr ?? null, max_hr: w.max_hr ?? null,
          avg_power_w: null, max_power_w: null, kcal: null,
          suffer_score: null, polyline: null,
        } as Activity;
      })
      .filter((a) => new Date(a.start_at).getTime() >= sinceMs);
    activities24.value = [...acts, ...strengthAsActivity]
      .filter((a) => new Date(a.start_at).getTime() >= sinceMs);

    // Sober resets in window — same 1st-row drop convention as Today.vue
    // (the chronological first row is the start-of-tracking, not a reset).
    if (Array.isArray(sbHist) && sbHist.length > 0) {
      const sortedAsc = [...sbHist].sort(
        (a, b) => a.start_at.localeCompare(b.start_at),
      );
      soberResets24.value = sortedAsc.slice(1)
        .filter((r) => new Date(r.start_at).getTime() >= sinceMs)
        .map((r) => ({ start_at: r.start_at }));
    } else {
      soberResets24.value = [];
    }

    lastSleep.value = sleep;
    traceLoaded.value = true;
  } catch {
    /* trace is non-critical; aggregates still render */
  }
}

async function loadHistory() {
  loading.value = true;
  error.value = null;
  try {
    const dailySince = new Date();
    dailySince.setHours(0, 0, 0, 0);
    dailySince.setDate(dailySince.getDate() - cur.value.days + 1);

    const priorSince = new Date(dailySince);
    priorSince.setDate(priorSince.getDate() - cur.value.days);
    const priorUntil = new Date(dailySince);

    const yearAgoSince = new Date(dailySince);
    yearAgoSince.setFullYear(yearAgoSince.getFullYear() - 1);
    const yearAgoUntil = new Date();
    yearAgoUntil.setFullYear(yearAgoUntil.getFullYear() - 1);

    const [daily, prior, yearAgo, acts, p] = await Promise.all([
      api.summaryRange(dailySince),
      api.summaryRange(priorSince, priorUntil),
      api.summaryRange(yearAgoSince, yearAgoUntil),
      api.activities({ since: dailySince, limit: 200 }),
      api.getProfile().catch(() => null),
    ]);
    dailyRows.value = daily;
    priorRows.value = prior;
    yearAgoRows.value = yearAgo;
    activities.value = acts;
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

onMounted(() => {
  loadHistory();
  loadTrace();
});
watch(range, loadHistory);

const dayMs = 24 * 3600 * 1000;
const xWindow24 = computed(() => ({ min: Date.now() - dayMs, max: Date.now() }));

// ── Headline cards ──
function avg(xs: number[]): number | null {
  if (!xs.length) return null;
  return xs.reduce((s, v) => s + v, 0) / xs.length;
}
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

// ── Live 24h trace ──
const traceOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr24.value || hr24.value.points.length === 0) return null;

  // Stack the mean line + sober-reset verticals into a single markLine
  // (ECharts allows only one markLine per series). Workout bands and
  // sleep band are separate markAreas — we use one host series each
  // since markArea is also one-per-series.
  const markLineData: any[] = [];
  let markLineConfig: any = null;
  if (hr24.value.avg != null) {
    markLineData.push({
      yAxis: hr24.value.avg,
      lineStyle: { color: t.palette.steps, type: "dashed" as const, opacity: 0.6 },
      label: { show: true, formatter: `avg ${hr24.value.avg.toFixed(0)}`,
               color: t.axisLabel.color, fontSize: 9 },
    });
    markLineConfig = { silent: true, symbol: "none" };
  }
  const resetLine = soberResetMarkLine(soberResets24.value);
  if (resetLine) {
    for (const d of (resetLine.data as any[])) markLineData.push(d);
    markLineConfig = markLineConfig ?? { symbol: ["none", "none"] };
  }

  const series: any[] = [
    {
      type: "line", name: "HR", showSymbol: false, smooth: true,
      lineStyle: { color: t.palette.hr, width: 1.5 },
      areaStyle: { color: `${t.palette.hr}22` },
      data: hr24.value.points.map((p) => [p.time, p.value]),
      ...(markLineConfig
        ? { markLine: { ...markLineConfig, data: markLineData } } : {}),
      ...(activities24.value.length > 0
        ? { markArea: workoutMarkArea(activities24.value) } : {}),
    },
  ];

  // Second host series for the sleep band (markArea is one-per-series).
  const sleepArea = sleepMarkArea(
    lastSleep.value, xWindow24.value.min, xWindow24.value.max,
  );
  if (sleepArea) {
    series.push({
      type: "line", name: "Sleep window",
      data: [], showSymbol: false, silent: true,
      markArea: sleepArea,
    });
  }

  return {
    grid: { left: 40, right: 12, top: 12, bottom: 28 },
    xAxis: {
      type: "time",
      min: xWindow24.value.min,
      max: xWindow24.value.max,
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", scale: true,
      axisLabel: t.axisLabel, splitLine: t.splitLine,
    },
    tooltip: { trigger: "axis", ...t.tooltip },
    series,
  };
});

// ── Daily resting HR over the selected range ──
function dailyLineOption(rows: TodaySummary[], color: string) {
  void chartTheme.value;
  const t = chartTheme.value;
  const data = rows
    .filter((r) => r.resting_hr != null)
    .map((r) => [r.date, r.resting_hr]);
  if (data.length === 0) return null;
  return {
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
             splitLine: t.splitLine },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis" },
    series: [{
      type: "line", name: "Resting HR",
      showSymbol: data.length < 90, smooth: true,
      lineStyle: { color, width: 1.8 },
      itemStyle: { color },
      areaStyle: { color: `${color}1f` },
      data,
      markLine: profile.value?.resting_hr_baseline
        ? meanMarkLine(profile.value.resting_hr_baseline, "baseline")
        : undefined,
    }],
  };
}
const restingOption = computed(() =>
  dailyLineOption(dailyRows.value, chartTheme.value.palette.hr),
);

// ── Daily HRV ──
const hrvOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const data = dailyRows.value
    .filter((r) => r.hrv_avg != null)
    .map((r) => [r.date, r.hrv_avg]);
  if (data.length === 0) return null;
  return {
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
             splitLine: t.splitLine },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis" },
    series: [{
      type: "line", name: "HRV (ms)", showSymbol: data.length < 90, smooth: true,
      lineStyle: { color: t.palette.hrv, width: 1.8 },
      itemStyle: { color: t.palette.hrv },
      areaStyle: { color: `${t.palette.hrv}1f` }, data,
    }],
  };
});

// ── Time in zone (from 24h trace) ──
const ZONE_DEFS = [
  { name: "Z1 · easy",      min: 0.50, color: "#38bdf8" },
  { name: "Z2 · aerobic",   min: 0.60, color: "#22c55e" },
  { name: "Z3 · tempo",     min: 0.70, color: "#eab308" },
  { name: "Z4 · threshold", min: 0.80, color: "#f97316" },
  { name: "Z5 · max",       min: 0.90, color: "#ef4444" },
];
const zonesOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr24.value || hr24.value.points.length === 0) return null;
  const maxHr = profile.value?.max_hr_estimated ?? 187;
  const buckets = ZONE_DEFS.map(() => 0);
  const pts = hr24.value.points;
  for (let i = 1; i < pts.length; i++) {
    const dt = (new Date(pts[i].time).getTime() - new Date(pts[i - 1].time).getTime()) / 1000;
    if (dt <= 0 || dt > 600) continue;
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
    series: [{
      type: "bar", data, barWidth: 16,
      label: { show: true, position: "right", color: t.axisLabel.color, fontSize: 10,
               formatter: (p: any) => total > 0
                 ? `${((p.data.value * 60 / total) * 100).toFixed(0)}%` : "" },
    }],
  };
});

// ── HR distribution histogram (5-bpm bins, from 24h trace) ──
const histogramOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr24.value || hr24.value.points.length === 0) return null;
  const BIN = 5;
  const counts = new Map<number, number>();
  let lo = Infinity, hi = -Infinity;
  for (const p of hr24.value.points) {
    const bin = Math.floor(p.value / BIN) * BIN;
    counts.set(bin, (counts.get(bin) ?? 0) + 1);
    lo = Math.min(lo, bin); hi = Math.max(hi, bin);
  }
  if (!isFinite(lo) || !isFinite(hi)) return null;
  const bins: number[] = [];
  for (let b = lo; b <= hi; b += BIN) bins.push(b);
  return {
    grid: { left: 40, right: 16, top: 12, bottom: 36 },
    xAxis: {
      type: "category",
      data: bins.map((b) => `${b}`),
      name: "bpm", nameLocation: "middle", nameGap: 22,
      nameTextStyle: t.axisLabel,
      axisLabel: t.axisLabel,
    },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
    series: [{
      type: "bar",
      data: bins.map((b) => counts.get(b) ?? 0),
      itemStyle: { color: t.palette.hr },
      barWidth: "85%",
    }],
  };
});

// ── Weekday-of-week pattern (avg resting HR by DOW from selected range) ──
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const weekdayOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const sums = Array(7).fill(0);
  const cnts = Array(7).fill(0);
  for (const r of dailyRows.value) {
    if (r.resting_hr == null) continue;
    const d = new Date(r.date + "T00:00:00").getDay();
    sums[d] += r.resting_hr;
    cnts[d] += 1;
  }
  const data = sums.map((s, i) => cnts[i] > 0 ? +(s / cnts[i]).toFixed(1) : null);
  if (data.every((v) => v == null)) return null;
  return {
    grid: { left: 40, right: 16, top: 12, bottom: 28 },
    xAxis: { type: "category", data: DOW, axisLabel: t.axisLabel },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
               formatter: (p: any) => `${p[0].name}: ${p[0].value ?? "—"} bpm` },
    series: [{
      type: "bar",
      data: data.map((v) => ({ value: v, itemStyle: { color: t.palette.hr } })),
      barWidth: "55%",
      label: { show: true, position: "top", color: t.axisLabel.color, fontSize: 10,
               formatter: (p: any) => p.value != null ? `${Math.round(p.value)}` : "" },
    }],
  };
});

// ── Exercise (activity-type) HR correlation ──
const activityHrOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const grouped = new Map<string, number[]>();
  for (const a of activities.value) {
    if (a.avg_hr == null) continue;
    const arr = grouped.get(a.type) ?? [];
    arr.push(a.avg_hr);
    grouped.set(a.type, arr);
  }
  if (grouped.size === 0) return null;
  const types = Array.from(grouped.keys()).sort();
  const avgs = types.map((tp) => {
    const arr = grouped.get(tp)!;
    return +(arr.reduce((s, v) => s + v, 0) / arr.length).toFixed(0);
  });
  const counts = types.map((tp) => grouped.get(tp)!.length);
  return {
    grid: { left: 110, right: 30, top: 12, bottom: 28 },
    xAxis: { type: "value", axisLabel: { ...t.axisLabel, formatter: "{value} bpm" },
             splitLine: t.splitLine },
    yAxis: { type: "category", data: types, axisLabel: { ...t.axisLabel, fontSize: 11 } },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
               formatter: (p: any) => {
                 const i = types.indexOf(p[0].name);
                 return `${p[0].name}: ${p[0].value} bpm avg<br/>${counts[i]} session(s)`;
               } },
    series: [{
      type: "bar",
      data: avgs.map((v, i) => ({
        value: v,
        itemStyle: {
          color: types[i] === "strength" ? t.palette.workout
                : types[i] === "rower" ? t.palette.violet
                : t.palette.hr,
        },
      })),
      barWidth: 14,
      label: { show: true, position: "right", color: t.axisLabel.color, fontSize: 10,
               formatter: (p: any) => {
                 const i = types.indexOf(p.name);
                 return `${p.value} · n=${counts[i]}`;
               } },
    }],
  };
});

// ── Year-over-year overlay ──
const yoyOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const cur = dailyRows.value
    .filter((r) => r.resting_hr != null)
    .map((r) => [new Date(r.date + "T00:00:00").getTime(), r.resting_hr]);
  // Year-ago series gets shifted forward by 1 year so both lines share an x-axis.
  const yoy = yearAgoRows.value
    .filter((r) => r.resting_hr != null)
    .map((r) => {
      const d = new Date(r.date + "T00:00:00");
      d.setFullYear(d.getFullYear() + 1);
      return [d.getTime(), r.resting_hr];
    });
  if (cur.length === 0 && yoy.length === 0) return null;
  return {
    legend: { textStyle: t.axisLabel, top: 0 },
    grid: { left: 40, right: 16, top: 30, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
             splitLine: t.splitLine },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { ...t.tooltip, trigger: "axis" },
    series: [
      {
        type: "line", name: "This period", smooth: true, showSymbol: cur.length < 90,
        lineStyle: { color: t.palette.hr, width: 1.8 },
        itemStyle: { color: t.palette.hr },
        data: cur,
      },
      {
        type: "line", name: "Same period last year", smooth: true, showSymbol: false,
        lineStyle: { color: t.palette.steps, width: 1.4, type: "dashed" },
        itemStyle: { color: t.palette.steps },
        data: yoy,
      },
    ],
  };
});

const maxHrInWindow = computed(() => hr24.value?.max_bpm ?? null);
const minHrInWindow = computed(() => hr24.value?.min_bpm ?? null);
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

    <!-- Headline cards always render once history is loaded -->
    <div v-if="!loading" class="cards">
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

      <Card title="Max HR (24h)" :flat="true">
        <div class="big">
          {{ maxHrInWindow != null ? Math.round(maxHrInWindow) : "—" }}
          <span class="unit">bpm</span>
        </div>
        <div class="muted-sm" v-if="profile?.max_hr_estimated">
          est max {{ profile.max_hr_estimated }}
        </div>
      </Card>

      <Card title="Min HR (24h)" :flat="true">
        <div class="big">
          {{ minHrInWindow != null ? Math.round(minHrInWindow) : "—" }}
          <span class="unit">bpm</span>
        </div>
      </Card>
    </div>

    <p v-if="loading" class="muted">Loading…</p>

    <template v-if="!loading">
      <!-- 24h trace -->
      <Card v-if="traceOption" title="HR trace · last 24h" :flat="true">
        <div class="chart"><VChart :option="traceOption" autoresize/></div>
      </Card>

      <!-- Time in zone (24h) -->
      <Card v-if="zonesOption" title="Time in zone · last 24h" :flat="true">
        <div class="chart-sm"><VChart :option="zonesOption" autoresize/></div>
        <p class="hint" v-if="profile?.max_hr_estimated">Max HR: {{ profile.max_hr_estimated }} bpm.</p>
      </Card>

      <!-- HR distribution histogram (24h) -->
      <Card v-if="histogramOption" title="HR distribution · last 24h" :flat="true">
        <div class="chart-sm"><VChart :option="histogramOption" autoresize/></div>
        <p class="hint">5-bpm bins. Sample count per bin.</p>
      </Card>

      <!-- Daily resting HR history -->
      <Card v-if="restingOption" :title="`Daily resting HR · ${cur.label}`" :flat="true">
        <div class="chart"><VChart :option="restingOption" autoresize/></div>
      </Card>

      <!-- YoY overlay -->
      <Card v-if="yoyOption" :title="`Year-over-year resting HR · ${cur.label}`" :flat="true">
        <div class="chart"><VChart :option="yoyOption" autoresize/></div>
      </Card>

      <!-- Weekday pattern -->
      <Card v-if="weekdayOption" :title="`Resting HR by weekday · ${cur.label}`" :flat="true">
        <div class="chart-sm"><VChart :option="weekdayOption" autoresize/></div>
      </Card>

      <!-- Activity HR correlation -->
      <Card v-if="activityHrOption" :title="`Avg HR by activity type · ${cur.label}`" :flat="true">
        <div class="chart-sm"><VChart :option="activityHrOption" autoresize/></div>
        <p class="hint">Average HR per session, grouped by activity type. Strength = red, Concept2 = violet, cardio = HR red.</p>
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
