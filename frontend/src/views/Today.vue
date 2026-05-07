<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import VChart from "vue-echarts";
import { api } from "@/api/client";
import type {
  Activity, Annotation, HeartRateSeries, HrvSeries,
  SleepNight, StepsSeries, TodaySummary,
} from "@/api/types";
import { chartTheme } from "@/theme";
import { fmtDateTime } from "@/format";
import { tempUnit, isImperial } from "@/units";
import { TrendingUp, TrendingDown, Sparkles } from "lucide-vue-next";
import { annotationMarkPoint, baseTimeOption, meanMarkLine, soberResetMarkLine, timeAxisFormatter, workoutMarkArea } from "@/components/charts/chartHelpers";

import Card from "@/components/Card.vue";
import RecoveryCard from "@/components/RecoveryCard.vue";
import StrengthTodayCard from "@/components/StrengthTodayCard.vue";
import SleepCard from "@/components/SleepCard.vue";
import StepsCard from "@/components/StepsCard.vue";
import TrendBadges from "@/components/TrendBadges.vue";

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
// Separate "today only" HR series scoped to local midnight → now,
// independent of the range picker — used for the at-a-glance underlay.
const todayHr = ref<HeartRateSeries | null>(null);
// Local-day step count (UTC midnight rolled into "today" includes
// yesterday's evening for users west of UTC; this fetches since local
// midnight so the dashboard matches what the watch shows).
const todayStepsLocal = ref<number>(0);

// Auto-discovered correlations for the violet "Recent insights" ribbon
type Discovery = { x_metric: string; y_metric: string; n: number; pearson_r: number };
const discoveries = ref<Discovery[]>([]);
async function loadDiscoveries() {
  try { discoveries.value = await api.discoveries(90); } catch { /* ignore */ }
}
onMounted(loadDiscoveries);

// ── AI insights ─────────────────────────────────────────────
const aiCfg = ref<Awaited<ReturnType<typeof api.aiConfig>> | null>(null);
const aiTopicResult = ref<Awaited<ReturnType<typeof api.aiExplainTopic>> | null>(null);
const aiVerdict = ref<{ content: string; generated_at: string; model: string } | null>(null);
const aiVerdictBusy = ref(false);
const activeTopic = ref<string | null>(null);
const aiBusy = ref(false);
const aiError = ref<string | null>(null);

type Topic = "week" | "month" | "sleep" | "recovery" | "sober" | "anomaly";
const AI_TOPICS: { id: Topic; label: string }[] = [
  { id: "week",     label: "This week" },
  { id: "sleep",    label: "Sleep" },
  { id: "recovery", label: "Recovery" },
  { id: "sober",    label: "Sober" },
  { id: "anomaly",  label: "Anomalies" },
  { id: "month",    label: "Month" },
];

async function loadAi() {
  try { aiCfg.value = await api.aiConfig(); } catch { return; }
  if (!aiCfg.value?.enabled) return;
  // Pull cached verdict on mount — no API call unless user taps refresh.
  try { aiVerdict.value = await api.aiVerdictLatest(); } catch { /* ignore */ }
}

async function refreshVerdict() {
  if (!aiCfg.value?.enabled) return;
  aiVerdictBusy.value = true;
  try { aiVerdict.value = await api.aiVerdict(); }
  catch (e) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { data?: { detail?: string } } }).response;
      aiError.value = r?.data?.detail ?? "verdict failed";
    }
  }
  finally { aiVerdictBusy.value = false; }
}

const aiPreWorkout = ref<{ content: string; generated_at: string; model: string } | null>(null);
const aiPreWorkoutBusy = ref(false);
async function getPreWorkout() {
  if (!aiCfg.value?.enabled) return;
  aiPreWorkoutBusy.value = true;
  try { aiPreWorkout.value = await api.aiPreWorkout(); }
  catch (e) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { data?: { detail?: string } } }).response;
      aiError.value = r?.data?.detail ?? "pre-workout failed";
    }
  }
  finally { aiPreWorkoutBusy.value = false; }
}
async function askTopic(topic: Topic) {
  aiBusy.value = true; aiError.value = null; activeTopic.value = topic;
  try {
    aiTopicResult.value = await api.aiExplainTopic(topic);
    await loadAi();
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      aiError.value = r?.data?.detail ?? `HTTP ${r?.status ?? "?"}`;
    } else {
      aiError.value = e instanceof Error ? e.message : "AI request failed";
    }
  } finally { aiBusy.value = false; }
}

// Re-ask the current topic — useful when the cached response feels stale
// (server-side cache is keyed by payload hash, so a real refresh requires
// the data to have moved since last call. If hash unchanged we just see
// the same cached body again — that's expected, not a bug).
async function refreshTopic() {
  if (activeTopic.value) await askTopic(activeTopic.value as Topic);
}

// Click handler for trend badges → AI explain on the relevant topic.
// Maps badge.key → topic. Bad/warn badges nudge toward the topic that
// most likely explains them; good streaks open the matching topic too.
function onBadgeClicked(badgeKey: string) {
  if (!aiCfg.value?.enabled) return;
  const topic: Topic =
    badgeKey.startsWith("sleep") ? "sleep"
    : badgeKey === "sober" ? "sober"
    : badgeKey.includes("anomaly") ? "anomaly"
    : "recovery";
  askTopic(topic);
  // Scroll to the AI card if needed (it's at the top, but nice for confirmation)
  setTimeout(() => {
    document.querySelector(".ai-topics")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 50);
}

onMounted(loadAi);
const hrv = ref<HrvSeries | null>(null);
const sleep = ref<SleepNight | null>(null);
const steps = ref<StepsSeries | null>(null);
const activities = ref<Activity[]>([]);
const annotations = ref<Annotation[]>([]);
const sober = ref<Awaited<ReturnType<typeof api.soberCurrent>> | null>(null);
const loading = ref(true);

// SleepNight.total_s is the in-bed window (start→end). For "Sleep last
// night" the headline number people expect is time *asleep* — subtract
// the awake bucket. Same convention as SleepCard.vue.
const asleepSeconds = computed(() => {
  if (!sleep.value) return 0;
  const awake = sleep.value.stages.find((s) => s.stage === "awake")?.duration_s ?? 0;
  return Math.max(0, sleep.value.total_s - awake);
});
const error = ref<string | null>(null);

// Blood pressure
type BpPoint = { time: string; systolic: number; diastolic: number; pulse_bpm: number | null; source: string; notes: string | null };
const bp = ref<{ latest: BpPoint | null; avg_sys: number | null; avg_dia: number | null; points: BpPoint[] }>({ latest: null, avg_sys: null, avg_dia: null, points: [] });
const bpForm = ref({ systolic: "", diastolic: "", pulse: "", notes: "" });
const bpSaving = ref(false);
const bpError = ref<string | null>(null);
const bpFormVisible = ref(false);

async function loadBp() {
  try {
    const since = new Date();
    since.setDate(since.getDate() - 30);
    bp.value = await api.bloodPressure({ since });
  } catch (e) {
    bpError.value = e instanceof Error ? e.message : String(e);
  }
}

async function saveBp() {
  bpSaving.value = true;
  bpError.value = null;
  try {
    const sys = parseInt(bpForm.value.systolic, 10);
    const dia = parseInt(bpForm.value.diastolic, 10);
    if (!Number.isFinite(sys) || !Number.isFinite(dia)) throw new Error("Enter both systolic and diastolic");
    const pulse = bpForm.value.pulse ? parseInt(bpForm.value.pulse, 10) : null;
    await api.logBloodPressure({
      systolic: sys, diastolic: dia,
      pulse_bpm: Number.isFinite(pulse as number) ? pulse : null,
      notes: bpForm.value.notes || null,
    });
    bpForm.value = { systolic: "", diastolic: "", pulse: "", notes: "" };
    bpFormVisible.value = false;
    await loadBp();
  } catch (e) {
    bpError.value = e instanceof Error ? e.message : String(e);
  } finally {
    bpSaving.value = false;
  }
}

function hM(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function minutesAgo(iso: string): string {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}
function daysAgo(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 86400_000;
  if (d < 1) return "today";
  if (d < 2) return "yesterday";
  return `${Math.floor(d)}d ago`;
}
function readinessBlurb(s: number): string {
  if (s >= 80) return "Primed — go hard if you want.";
  if (s >= 65) return "Solid — moderate-to-hard training is fine.";
  if (s >= 50) return "Average — keep things easy or moderate.";
  if (s >= 35) return "Low — prioritise recovery today.";
  return "Very low — rest day.";
}

function readinessClass(s: number): string {
  if (s >= 75) return "good";
  if (s >= 50) return "";
  return "bad";
}
function formClass(tsb: number): string {
  if (tsb > 5) return "good";   // fresh, race-ready
  if (tsb < -20) return "bad";  // overreached
  return "";
}

// Watch wear-time inference: when the Pixel Watch is on charger or off-
// wrist, HR sampling pauses. Bucket today's HR into hour slots; a slot
// is "worn" if it has any samples. Returns wear % across hours that have
// elapsed today, plus the longest contiguous gap.
const watchState = computed(() => {
  const now = new Date();
  const todayMidnight = new Date();
  todayMidnight.setHours(0, 0, 0, 0);
  const hoursElapsed = Math.max(1, Math.ceil((now.getTime() - todayMidnight.getTime()) / 3600_000));
  const slots = new Array<boolean>(hoursElapsed).fill(false);
  if (todayHr.value) {
    for (const p of todayHr.value.points) {
      const h = Math.floor((new Date(p.time).getTime() - todayMidnight.getTime()) / 3600_000);
      if (h >= 0 && h < slots.length) slots[h] = true;
    }
  }
  const worn = slots.filter(Boolean).length;
  // Longest gap (consecutive empty slots).
  let longest = 0; let cur = 0;
  let gapStart = -1; let gapStartLongest = -1;
  for (let i = 0; i < slots.length; i++) {
    if (slots[i]) {
      cur = 0; gapStart = -1;
    } else {
      if (gapStart < 0) gapStart = i;
      cur += 1;
      if (cur > longest) { longest = cur; gapStartLongest = gapStart; }
    }
  }
  const pct = Math.round((worn / hoursElapsed) * 100);
  return {
    pct, worn, total: hoursElapsed, longestGapH: longest,
    gapStartHour: gapStartLongest, isLikelyCharging: longest >= 1,
  };
});

// HR sparkline path for the "Today at a glance" underlay. Pure SVG —
// no chart lib needed. The x-axis is anchored to the full local-day
// window (midnight → now), so if HR sync stalls the trailing portion
// renders as empty space — a visible "no data" gap against the fixed
// 00 / 06 / 12 / 18 / now axis labels.
const hrSparkPath = computed(() => {
  if (!todayHr.value || todayHr.value.points.length < 5) return null;
  const pts = todayHr.value.points;
  const xs = pts.map((p) => new Date(p.time).getTime());
  const ys = pts.map((p) => p.value);
  const now = new Date();
  const localMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const xMin = localMidnight;
  const xMax = now.getTime();
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const W = 1000;  // viewBox width
  const H = 100;
  const xR = xMax - xMin || 1;
  const yR = yMax - yMin || 1;
  const path = pts.map((p, i) => {
    const x = ((xs[i] - xMin) / xR) * W;
    const y = H - ((ys[i] - yMin) / yR) * H * 0.85 - H * 0.075;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const firstX = ((xs[0] - xMin) / xR) * W;
  const lastX = ((xs[xs.length - 1] - xMin) / xR) * W;
  // Close fill to the data extent only, not the full viewBox — keeps the
  // post-last-sample region truly empty so the gap is visible.
  const last = `L${lastX.toFixed(1)},${H} L${firstX.toFixed(1)},${H} Z`;
  // Gap-from-now in minutes; surface > 30 min as a stale flag.
  const gapMin = Math.round((xMax - xs[xs.length - 1]) / 60000);
  return { stroke: path, fill: path + last, yMin, yMax, n: pts.length, gapMin };
});

// Radar combining the day's normalised vitals.
const radarOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const s = summary.value;
  if (!s) return null;
  // Each axis is 0-100; readiness already is. HRV/Recovery/Sleep score are
  // already 0-100. Steps + RHR get normalised below.
  const stepsPct = Math.min(100, Math.round(((s.steps_total ?? 0) / 10000) * 100));
  // RHR: lower is better. 50bpm → 100, 80bpm → 0.
  const rhr = s.resting_hr;
  const rhrPct = rhr != null ? Math.max(0, Math.min(100, ((80 - rhr) / 30) * 100)) : null;
  // HRV: typical 20-100. 80+ → 100.
  const hrv = s.hrv_avg;
  const hrvPct = hrv != null ? Math.max(0, Math.min(100, (hrv / 80) * 100)) : null;

  const indicators = [
    { name: "Readiness", max: 100 },
    { name: "Recovery", max: 100 },
    { name: "Sleep", max: 100 },
    { name: "HRV", max: 100 },
    { name: "RHR", max: 100 },
    { name: "Steps", max: 100 },
  ];
  const data = [
    s.readiness_score ?? 0,
    s.recovery_score ?? 0,
    s.sleep_score ?? 0,
    hrvPct ?? 0,
    rhrPct ?? 0,
    stepsPct,
  ];
  return {
    tooltip: { ...t.tooltip },
    radar: {
      indicator: indicators,
      shape: "polygon",
      splitLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
      splitArea: { areaStyle: { color: ["rgba(56, 189, 248, 0.02)", "rgba(56, 189, 248, 0.04)"] } },
      axisName: { color: t.axisLabel.color, fontSize: 11 },
    },
    series: [{
      type: "radar",
      data: [{
        value: data,
        name: "Today",
        areaStyle: { color: "rgba(56, 189, 248, 0.25)" },
        lineStyle: { color: t.palette.accent, width: 2 },
        itemStyle: { color: t.palette.accent },
      }],
    }],
  };
});

function bpClass(sys: number, dia: number): string {
  if (sys >= 180 || dia >= 120) return "bp-crisis";
  if (sys >= 140 || dia >= 90) return "bp-stage2";
  if (sys >= 130 || dia >= 80) return "bp-stage1";
  if (sys >= 120) return "bp-elevated";
  return "bp-normal";
}
function bpLabel(sys: number, dia: number): string {
  if (sys >= 180 || dia >= 120) return "Hypertensive crisis";
  if (sys >= 140 || dia >= 90) return "Stage 2";
  if (sys >= 130 || dia >= 80) return "Stage 1";
  if (sys >= 120) return "Elevated";
  return "Normal";
}

// Chart toggles
const showWorkouts = ref(true);
const showAnnotations = ref(true);
const showHrv = ref(false);
const showMean = ref(true);
const showSoberResets = ref(true);
// Sober resets in the visible range. Computed from the streaks list — every
// row's start_at is a "this is when the previous streak ended and a new one
// began" marker, except the very first row (which is the start of tracking,
// not a reset). Filtered to the chart's xWindow so the markline stays light.
const soberResets = ref<Array<{ start_at: string }>>([]);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const hours = RANGES.find((r) => r.key === range.value)!.hours;
    const since = new Date(Date.now() - hours * 3600 * 1000);
    // Today's local midnight for the underlay sparkline + glance stats.
    const todayMidnight = new Date();
    todayMidnight.setHours(0, 0, 0, 0);
    const [s, h, hv, sl, st, a, an, hToday, sToday, sb, sbHist] = await Promise.all([
      api.todaySummary(),
      api.heartRate({ since }),
      api.hrv({ since }),
      api.lastSleep(),
      api.steps({ since }),
      api.activities({ since, limit: 50 }),
      api.listAnnotations({ since, limit: 200 }),
      api.heartRate({ since: todayMidnight }),
      api.steps({ since: todayMidnight }),
      api.soberCurrent().catch(() => null),
      api.soberHistory(500).catch(() => []),
    ]);
    summary.value = s;
    hr.value = h;
    hrv.value = hv;
    sleep.value = sl;
    steps.value = st;
    activities.value = a;
    annotations.value = an;
    todayHr.value = hToday;
    todayStepsLocal.value = sToday.total ?? 0;
    sober.value = sb;
    // Sober resets in the visible window. The first row chronologically is
    // the start-of-tracking, not a reset, so drop it.
    if (Array.isArray(sbHist) && sbHist.length > 0) {
      const sortedAsc = [...sbHist].sort((a, b) => a.start_at.localeCompare(b.start_at));
      const resets = sortedAsc.slice(1).filter((r) =>
        new Date(r.start_at).getTime() >= since.getTime()
      );
      soberResets.value = resets.map((r) => ({ start_at: r.start_at }));
    } else {
      soberResets.value = [];
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(() => { load(); loadBp(); });
watch(range, load);

// Anchor every time-series chart on this page to the same window — full
// range (since → now). When sync stalls, the right side is empty space
// rather than the chart silently truncating to the last data point.
const xWindow = computed(() => {
  const hours = RANGES.find((r) => r.key === range.value)!.hours;
  const max = Date.now();
  return { min: max - hours * 3600 * 1000, max };
});

const hrSeriesOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const opt = baseTimeOption() as Record<string, any>;
  // Anchor x-axis to the full range window so a stalled sync shows as a
  // visible gap on the right edge instead of a chart that just ends early.
  opt.xAxis = { ...(opt.xAxis as object), min: xWindow.value.min, max: xWindow.value.max };
  if (!hr.value) return opt;

  const hrPoints = hr.value.points.map((p) => [p.time, p.value]);
  // Stack mean line + sober resets into a single markLine (ECharts only
  // accepts one per series). Mean is a horizontal line at yAxis=avg, resets
  // are vertical lines at xAxis=reset_ts. ECharts is happy to mix.
  const markLineData: any[] = [];
  let markLineConfig: any = null;
  if (showMean.value && hr.value.avg !== null) {
    markLineData.push({
      yAxis: hr.value.avg, name: `avg ${hr.value.avg.toFixed(0)}`,
      lineStyle: { color: t.palette.steps, type: "dashed" as const, opacity: 0.6 },
      label: { show: true, formatter: `avg ${hr.value.avg.toFixed(0)}`, color: t.axisLabel.color, fontSize: 9 },
    });
    markLineConfig = { silent: true, symbol: "none" };
  }
  if (showSoberResets.value && soberResets.value.length > 0) {
    for (const r of soberResets.value) {
      markLineData.push({
        xAxis: r.start_at,
        name: "🔄 sober reset",
        lineStyle: { color: "#a78bfa", type: "dashed" as const, opacity: 0.55, width: 1 },
        label: { show: true, formatter: "🔄", position: "insideEndTop", fontSize: 13, color: "#a78bfa" },
      });
    }
    markLineConfig = markLineConfig ?? { symbol: ["none", "none"] };
  }
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
      ...(markLineConfig ? { markLine: { ...markLineConfig, data: markLineData } } : {}),
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
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: { show: false },
      min: xWindow.value.min, max: xWindow.value.max,
    },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "bar",
      data: steps.value.points.map((p) => [p.time, p.value]),
      itemStyle: { color: t.palette.steps },
      ...(showSoberResets.value && soberResets.value.length > 0 ? {
        markLine: {
          symbol: ["none", "none"],
          data: soberResets.value.map((r) => ({
            xAxis: r.start_at,
            lineStyle: { color: "#a78bfa", type: "dashed" as const, opacity: 0.55, width: 1 },
            label: { show: true, formatter: "🔄", position: "insideEndTop", fontSize: 13, color: "#a78bfa" },
          })),
        },
      } : {}),
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
      <!-- ════ AI verdict headline (one sentence above everything) ════ -->
      <div v-if="aiCfg?.enabled" class="verdict-strip">
        <span class="verdict-icon">✦</span>
        <span class="verdict-text" v-if="aiVerdict">{{ aiVerdict.content }}</span>
        <span class="verdict-text muted" v-else>Tap ↻ for today's read.</span>
        <button class="verdict-refresh" :disabled="aiVerdictBusy"
                :title="aiVerdict ? `${fmtDateTime(aiVerdict.generated_at)} · ${aiVerdict.model.replace(/-\\d{8}$/, '')}` : 'Generate'"
                @click="refreshVerdict">
          {{ aiVerdictBusy ? '…' : '↻' }}
        </button>
      </div>

      <!-- Pre-workout chip — small, opt-in via tap -->
      <div v-if="aiCfg?.enabled" class="prework-strip">
        <button class="prework-btn" :disabled="aiPreWorkoutBusy" @click="getPreWorkout">
          🏋  {{ aiPreWorkout ? "Refresh pre-workout" : "Pre-workout call" }}
        </button>
        <span v-if="aiPreWorkout" class="prework-text">{{ aiPreWorkout.content }}</span>
      </div>

      <!-- ════ AI + Trend badges at the top ══════════════════════ -->
      <!-- AI insights card (only if enabled in Settings) -->
      <Card v-if="aiCfg?.enabled" title="AI insights"
            :subtitle="aiCfg ? `${aiCfg.calls_today}/${aiCfg.daily_call_limit} today · ${aiCfg.model.replace(/-\\d{8}$/, '')}` : ''">
        <div class="ai-topics">
          <button v-for="t in AI_TOPICS" :key="t.id" class="ai-topic"
                  :class="{ active: activeTopic === t.id, primary: t.id === 'week' }"
                  :disabled="aiBusy" @click="askTopic(t.id)">
            {{ t.label }}
          </button>
        </div>
        <div v-if="aiError" class="err" style="margin-top:0.5rem;">{{ aiError }}</div>
        <div v-if="aiBusy" class="muted ai-thinking">Thinking…</div>
        <div v-else-if="aiTopicResult" class="ai-card" :class="`tone-${aiTopicResult.tone}`">
          <div class="ai-headline">{{ aiTopicResult.headline }}</div>
          <ul class="ai-evidence">
            <li v-for="(e, i) in aiTopicResult.evidence" :key="i">{{ e }}</li>
          </ul>
          <div v-if="aiTopicResult.suggestion" class="ai-suggestion">
            <strong>Try:</strong> {{ aiTopicResult.suggestion }}
          </div>
          <div class="ai-foot muted">
            {{ aiTopicResult.cached ? 'cached' : 'fresh' }}
            · {{ aiTopicResult.model.replace(/-\\d{8}$/, '') }}
            · {{ fmtDateTime(aiTopicResult.generated_at) }}
            <button v-if="aiTopicResult.cached && activeTopic" class="ai-refresh"
                    :disabled="aiBusy" @click="refreshTopic">↻ refresh</button>
          </div>
        </div>
        <div v-else class="muted" style="margin-top:0.4rem; font-size:0.85rem;">
          Pick a topic for a focused, structured read of your data.
        </div>
      </Card>

      <!-- Trend badges — pure stats, no LLM, always on -->
      <TrendBadges @badge-clicked="onBadgeClicked" :clickable="aiCfg?.enabled" />

      <!-- KPI headline strip — 4 trend badges above the hero -->
      <div v-if="summary" class="kpi-strip">
        <div class="kpi-badge"
             :style="{ '--kpi-c': (summary.recovery_score ?? 0) < 50 ? '#ef4444' : (summary.recovery_score ?? 0) < 70 ? '#fb923c' : '#22c55e' }">
          <div class="kpi-icon">
            <component :is="(summary.recovery_score ?? 60) < 60 ? TrendingDown : TrendingUp" :size="13"/>
          </div>
          <div class="kpi-content">
            <div class="kpi-l">Recovery</div>
            <div class="kpi-vrow">
              <span class="mono kpi-v">{{ summary.recovery_score?.toFixed(0) ?? '—' }}</span>
              <span class="kpi-s">/100</span>
            </div>
          </div>
        </div>
        <div class="kpi-badge" style="--kpi-c: #a78bfa;">
          <div class="kpi-icon"><component :is="TrendingUp" :size="13"/></div>
          <div class="kpi-content">
            <div class="kpi-l">Sleep</div>
            <div class="kpi-vrow">
              <span class="mono kpi-v">{{ hM(summary.sleep_duration_s) }}</span>
              <span class="kpi-s">{{ summary.sleep_score?.toFixed(0) ?? '—' }} sc</span>
            </div>
          </div>
        </div>
        <div class="kpi-badge" style="--kpi-c: #ef4444;">
          <div class="kpi-icon"><component :is="TrendingUp" :size="13"/></div>
          <div class="kpi-content">
            <div class="kpi-l">RHR</div>
            <div class="kpi-vrow">
              <span class="mono kpi-v">{{ summary.resting_hr ? Math.round(summary.resting_hr) : '—' }}</span>
              <span class="kpi-s">bpm</span>
            </div>
          </div>
        </div>
        <div class="kpi-badge" :style="{ '--kpi-c': (summary.hrv_avg ?? 50) < 30 ? '#fb923c' : '#a78bfa' }">
          <div class="kpi-icon">
            <component :is="(summary.hrv_avg ?? 50) < 30 ? TrendingDown : TrendingUp" :size="13"/>
          </div>
          <div class="kpi-content">
            <div class="kpi-l">HRV</div>
            <div class="kpi-vrow">
              <span class="mono kpi-v">{{ summary.hrv_avg ? summary.hrv_avg.toFixed(1) : '—' }}</span>
              <span class="kpi-s">ms</span>
            </div>
          </div>
        </div>
      </div>

      <Card title="Today at a glance">
       <div class="glance-wrap">
        <!-- Hero: readiness gauge -->
        <div class="hero">
          <div class="ring" :class="readinessClass(summary?.readiness_score ?? 0)"
               :style="{ '--pct': `${(summary?.readiness_score ?? 0) * 3.6}deg` }">
            <div class="ring-inner">
              <div class="ring-num">{{ summary?.readiness_score?.toFixed(0) ?? '—' }}</div>
              <div class="ring-lbl">Readiness</div>
            </div>
          </div>
          <div class="hero-blurb">
            <div class="hero-line" v-if="summary?.readiness_score != null">
              {{ readinessBlurb(summary.readiness_score) }}
            </div>
            <div class="hero-line">
              <span v-if="summary?.tsb != null">
                Form
                <strong :class="formClass(summary.tsb)">{{ summary.tsb > 0 ? '+' : '' }}{{ summary.tsb.toFixed(0) }}</strong>
                <span class="muted">(CTL {{ summary.ctl?.toFixed(0) }} · ATL {{ summary.atl?.toFixed(0) }})</span>
              </span>
            </div>
            <div class="hero-line muted" v-if="summary?.sleep_debt_h != null">
              7-day sleep debt:
              <strong :class="summary.sleep_debt_h > 5 ? 'bad' : summary.sleep_debt_h < -3 ? 'good' : ''">
                {{ summary.sleep_debt_h > 0 ? '+' : '' }}{{ summary.sleep_debt_h.toFixed(1) }}h
              </strong>
            </div>
          </div>
        </div>

        <!-- Compact KPI grid -->
        <div class="kpi-grid">
          <div class="kpi-tile">
            <div class="kpi-lbl">HR today</div>
            <div class="kpi-num" :style="{ color: '#ef4444' }">
              <strong>{{ todayHr?.avg ? Math.round(todayHr.avg) : '—' }}</strong> bpm
            </div>
            <div class="kpi-sub muted">
              <template v-if="todayHr?.min_bpm != null && todayHr?.max_bpm != null">
                {{ Math.round(todayHr.min_bpm) }}–{{ Math.round(todayHr.max_bpm) }} · {{ todayHr.points.length }} pts
              </template>
              <template v-else>no data yet</template>
            </div>
          </div>

          <div class="kpi-tile">
            <div class="kpi-lbl">BP latest</div>
            <div class="kpi-num" :class="bp.latest ? bpClass(bp.latest.systolic, bp.latest.diastolic) : ''">
              <strong>
                {{ bp.latest ? `${bp.latest.systolic}/${bp.latest.diastolic}` : '—' }}
              </strong>
              <span v-if="bp.latest" class="kpi-unit">mmHg</span>
            </div>
            <div class="kpi-sub muted">
              <template v-if="bp.latest">{{ bpLabel(bp.latest.systolic, bp.latest.diastolic) }} · {{ daysAgo(bp.latest.time) }}</template>
              <template v-else>no readings</template>
            </div>
          </div>

          <div class="kpi-tile">
            <div class="kpi-lbl">Sleep last night</div>
            <div class="kpi-num" :style="{ color: '#a78bfa' }">
              <strong>{{ sleep ? hM(asleepSeconds) : '—' }}</strong>
            </div>
            <div class="kpi-sub muted">
              <template v-if="summary?.sleep_score != null">
                Score {{ summary.sleep_score.toFixed(0) }} · cons. {{ summary?.sleep_consistency_score?.toFixed(0) ?? '—' }}
              </template>
            </div>
          </div>

          <div class="kpi-tile">
            <div class="kpi-lbl">Recovery</div>
            <div class="kpi-num" :style="{ color: '#22c55e' }">
              <strong>{{ summary?.recovery_score?.toFixed(0) ?? '—' }}</strong>
              <span v-if="summary?.recovery_score" class="kpi-unit">/100</span>
            </div>
            <div class="kpi-sub muted">
              RHR {{ summary?.resting_hr ? Math.round(summary.resting_hr) : '—' }} · HRV {{ summary?.hrv_avg ? Math.round(summary.hrv_avg) : '—' }} ms
            </div>
          </div>

          <div class="kpi-tile">
            <div class="kpi-lbl">Steps today</div>
            <div class="kpi-num" :style="{ color: '#38bdf8' }">
              <strong>{{ todayStepsLocal.toLocaleString() }}</strong>
            </div>
            <div class="kpi-sub muted">
              {{ Math.round(todayStepsLocal / 8000 * 100) }}% of 8k ·
              <template v-if="summary?.last_sync">last HC sync {{ minutesAgo(summary.last_sync) }}</template>
              <template v-else>local midnight</template>
            </div>
          </div>

          <div class="kpi-tile">
            <div class="kpi-lbl">Watch wear today</div>
            <div class="kpi-num"
                 :style="{ color: watchState.pct >= 80 ? '#22c55e' : watchState.pct >= 50 ? '#eab308' : '#ef4444' }">
              <strong>{{ watchState.pct }}%</strong>
              <span class="kpi-unit">{{ watchState.worn }}/{{ watchState.total }}h</span>
            </div>
            <div class="kpi-sub muted">
              <template v-if="watchState.longestGapH >= 1">
                {{ watchState.longestGapH }}h gap from
                {{ String(watchState.gapStartHour).padStart(2, '0') }}:00
                {{ watchState.longestGapH >= 3 ? '· likely charging' : '· off-wrist?' }}
              </template>
              <template v-else>continuous · worn all day</template>
            </div>
          </div>

          <RouterLink to="/sober" class="kpi-tile sober-tile" v-if="sober?.active">
            <div class="kpi-lbl">Sober time</div>
            <div class="kpi-num" style="color: #22c55e;">
              <strong>{{ sober.days ?? 0 }}d {{ sober.hours ?? 0 }}h</strong>
            </div>
            <div class="kpi-sub muted">
              since {{ new Date(sober.active.start_at).toLocaleDateString() }}
            </div>
          </RouterLink>
        </div>

        <!-- HR sparkline ribbon along the bottom for visual context -->
        <div v-if="hrSparkPath" class="ribbon-wrap">
          <svg class="hr-ribbon" viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="hr-rib" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#ef4444" stop-opacity="0.4"/>
                <stop offset="100%" stop-color="#ef4444" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <path :d="hrSparkPath.fill" fill="url(#hr-rib)"/>
            <path :d="hrSparkPath.stroke" stroke="#ef4444" stroke-width="1.6" fill="none" stroke-opacity="0.85"/>
          </svg>
          <div class="ribbon-axis muted">
            <span>00</span><span>06</span><span>12</span><span>18</span><span>now</span>
          </div>
        </div>
       </div>
      </Card>

      <!-- top stats row -->
      <div class="grid stats">
        <RecoveryCard
          :score="summary?.recovery_score ?? null"
          :rhr="summary?.resting_hr ?? null"
          :hrv="summary?.hrv_avg ?? null"
        />
        <StepsCard :total="todayStepsLocal" />
        <SleepCard :sleep="sleep" />
        <StrengthTodayCard />
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
          <label v-if="soberResets.length > 0">
            <input type="checkbox" v-model="showSoberResets"/>
            <span>🔄 Sober resets ({{ soberResets.length }})</span>
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

      <!-- Blood pressure -->
      <Card title="Blood pressure" :subtitle="bp.latest ? fmtDateTime(bp.latest.time) : 'No readings yet'">
        <div v-if="bp.latest" class="bp-latest">
          <div class="bp-big" :class="bpClass(bp.latest.systolic, bp.latest.diastolic)">
            <span class="sys">{{ bp.latest.systolic }}</span>
            <span class="slash">/</span>
            <span class="dia">{{ bp.latest.diastolic }}</span>
            <span class="unit">mmHg</span>
          </div>
          <div class="bp-meta">
            <span class="bp-tag" :class="bpClass(bp.latest.systolic, bp.latest.diastolic)">{{ bpLabel(bp.latest.systolic, bp.latest.diastolic) }}</span>
            <span v-if="bp.latest.pulse_bpm" class="muted">Pulse: {{ bp.latest.pulse_bpm }} bpm</span>
            <span class="muted">via {{ bp.latest.source }}</span>
          </div>
          <div v-if="bp.avg_sys && bp.avg_dia" class="bp-avg">
            30-day avg: {{ bp.avg_sys.toFixed(0) }}/{{ bp.avg_dia.toFixed(0) }}
          </div>
        </div>
        <div v-else class="empty">
          Pair OMRON Connect with Health Connect, or log a reading manually.
        </div>

        <div class="bp-actions">
          <button class="ghost" @click="bpFormVisible = !bpFormVisible">
            {{ bpFormVisible ? 'Cancel' : '+ Log a reading' }}
          </button>
        </div>
        <div v-if="bpFormVisible" class="bp-form">
          <input v-model="bpForm.systolic" type="number" placeholder="Sys" min="40" max="260"/>
          <span>/</span>
          <input v-model="bpForm.diastolic" type="number" placeholder="Dia" min="20" max="180"/>
          <input v-model="bpForm.pulse" type="number" placeholder="Pulse (opt)" min="20" max="250"/>
          <input v-model="bpForm.notes" type="text" placeholder="Notes (optional)" class="bp-notes"/>
          <button class="primary" :disabled="bpSaving" @click="saveBp">
            {{ bpSaving ? 'Saving…' : 'Save' }}
          </button>
        </div>
        <div v-if="bpError" class="err"><small>{{ bpError }}</small></div>
      </Card>
    </div>


    <!-- Recent insights — violet ribbon (auto-discovered correlations) -->
    <div v-if="discoveries.length" class="insights-ribbon">
      <div class="ir-head">
        <Sparkles :size="13" class="ir-icon"/>
        <span class="label" style="color: #c4b5fd;">Recent insights</span>
        <span class="ir-meta mono">|r| ≥ 0.4 · 90d window</span>
      </div>
      <div class="ir-grid">
        <div v-for="d in discoveries.slice(0, 6)" :key="`${d.x_metric}-${d.y_metric}`"
             class="ir-row">
          <span class="ir-r mono"
                :style="{ color: d.pearson_r > 0 ? '#22c55e' : '#ef4444',
                          background: (d.pearson_r > 0 ? '#22c55e' : '#ef4444') + '15',
                          borderColor: (d.pearson_r > 0 ? '#22c55e' : '#ef4444') + '40' }">
            r={{ d.pearson_r > 0 ? '+' : '' }}{{ d.pearson_r.toFixed(2) }}
          </span>
          <div class="ir-pair">
            <span class="ir-x">{{ d.x_metric }}</span>
            <span class="ir-arr">↔</span>
            <span class="ir-y">{{ d.y_metric }}</span>
          </div>
          <span class="ir-n mono">n={{ d.n }}</span>
        </div>
      </div>
    </div>

    <div v-if="summary?.last_sync" class="footer">
      Last sync: {{ fmtDateTime(summary.last_sync) }}
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

.grid { display: grid; gap: 1rem; margin-bottom: 1rem; margin-top: 1rem; }
.stats { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }

.toggle-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.toggle-row label { display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none; }

/* ECharts needs an explicitly-sized parent — flex grow leaves it 0×0. */
.chart-wrap { width: 100%; height: 320px; }
.chart-wrap.small { height: 160px; }
.chart-wrap > * { width: 100%; height: 100%; }
.empty { color: var(--muted-2); align-self: center; margin: auto; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
.footer { margin-top: 1.5rem; color: var(--muted-2); font-size: 0.8rem; text-align: right; }

.glance-wrap { display: flex; flex-direction: column; gap: 0.9rem; }

/* KPI badge strip floating above hero */
.kpi-strip {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem; margin-bottom: 0.85rem;
}
@media (max-width: 700px) { .kpi-strip { grid-template-columns: 1fr 1fr; } }
.kpi-badge {
  display: flex; align-items: center; gap: 0.7rem;
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.6rem 0.75rem;
}
.kpi-icon {
  width: 30px; height: 30px; border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  background: color-mix(in srgb, var(--kpi-c) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--kpi-c) 35%, transparent);
  color: var(--kpi-c);
  flex-shrink: 0;
}
.kpi-content { flex: 1; min-width: 0; }
.kpi-l {
  font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted-2); font-weight: 600;
}
.kpi-vrow { display: flex; align-items: baseline; gap: 0.25rem; margin-top: 0.15rem; }
.kpi-v {
  font-size: 18px; font-weight: 600; line-height: 1;
  letter-spacing: -0.02em; font-variant-numeric: tabular-nums;
}
.kpi-s { font-size: 10px; color: var(--muted-2); }
.kpi-delta {
  font-size: 10.5px; font-weight: 600;
  color: var(--kpi-c); font-variant-numeric: tabular-nums;
}

/* AI verdict — one-line headline above the page */
.verdict-strip {
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.7rem 1rem; margin: 0.6rem 0 1rem;
  background: linear-gradient(90deg, rgba(167, 139, 250, 0.08), rgba(56, 189, 248, 0.04));
  border: 1px solid rgba(167, 139, 250, 0.2);
  border-radius: 12px;
  font-size: 0.95rem; line-height: 1.4;
  color: var(--text);
}
.verdict-icon { color: var(--violet); font-size: 1.05rem; flex-shrink: 0; }
.verdict-text { flex: 1; }
.verdict-text.muted { color: var(--muted); font-style: italic; }
.verdict-refresh {
  background: transparent; border: 1px solid var(--border);
  color: var(--muted); border-radius: 6px;
  width: 28px; height: 28px; padding: 0;
  cursor: pointer; font-family: inherit; flex-shrink: 0;
}
.verdict-refresh:hover { color: var(--violet); border-color: var(--violet); }
.verdict-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.prework-strip {
  display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap;
  padding: 0.5rem 1rem; margin: 0 0 0.8rem;
  font-size: 0.88rem; color: var(--text-soft);
}
.prework-btn {
  background: rgba(56, 189, 248, 0.08); color: var(--accent);
  border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 100px;
  padding: 0.35rem 0.85rem; font-size: 0.78rem; font-weight: 600;
  cursor: pointer; font-family: inherit; flex-shrink: 0;
}
.prework-btn:hover { background: rgba(56, 189, 248, 0.15); }
.prework-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.prework-text { flex: 1; }

/* AI insights card */
.ai-topics { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.4rem; }
.ai-topic {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 100px; padding: 0.4rem 0.85rem; cursor: pointer; font-family: inherit;
  font-size: 0.82rem;
}
.ai-topic:hover { border-color: var(--accent); color: var(--accent); }
.ai-topic.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.ai-topic.primary { background: var(--surface-2); color: var(--text); border-color: rgba(56, 189, 248, 0.4); }
.ai-topic.primary.active, .ai-topic.primary:hover {
  background: var(--accent); color: var(--accent-text); border-color: var(--accent);
}
.ai-topic:disabled { opacity: 0.5; cursor: not-allowed; }

.ai-thinking { margin-top: 0.6rem; font-size: 0.85rem; color: var(--muted); }

.ai-card {
  margin-top: 0.6rem; padding: 0.85rem 1rem;
  background: rgba(148, 163, 184, 0.04);
  border-left: 3px solid var(--muted-2);
  border-radius: 6px;
}
.ai-card.tone-good { border-left-color: var(--good); background: rgba(34, 197, 94, 0.05); }
.ai-card.tone-warn { border-left-color: var(--warn); background: rgba(234, 179, 8, 0.05); }
.ai-card.tone-bad  { border-left-color: var(--bad);  background: rgba(239, 68, 68, 0.05); }

.ai-headline {
  font-size: 1rem; font-weight: 600; color: var(--text);
  letter-spacing: -0.01em; margin-bottom: 0.6rem; line-height: 1.35;
}
.ai-evidence { margin: 0.3rem 0 0.7rem; padding-left: 1.1rem; }
.ai-evidence li {
  color: var(--text-soft); font-size: 0.88rem; line-height: 1.5;
  margin-bottom: 0.25rem;
}
.ai-suggestion {
  margin-top: 0.5rem; padding-top: 0.5rem;
  border-top: 1px solid var(--line);
  color: var(--text-soft); font-size: 0.88rem;
}
.ai-suggestion strong { color: var(--accent); margin-right: 0.3rem; }
.ai-foot {
  margin-top: 0.5rem; font-size: 0.7rem; font-family: 'Geist Mono', monospace;
  color: var(--muted-2); letter-spacing: 0.02em;
  display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;
}
.ai-refresh {
  background: transparent; border: 1px solid var(--border);
  color: var(--muted); border-radius: 4px;
  font-size: 0.7rem; padding: 0.15rem 0.5rem; cursor: pointer;
  font-family: inherit; margin-left: auto;
}
.ai-refresh:hover { color: var(--accent); border-color: var(--accent); }
.ai-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* Violet "Recent insights" ribbon */
.insights-ribbon {
  margin-top: 1rem;
  padding: 0.85rem 1rem;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(167, 139, 250, 0.05), rgba(167, 139, 250, 0));
  border: 1px solid rgba(167, 139, 250, 0.20);
}
.ir-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; }
.ir-icon { color: #a78bfa; }
.ir-meta { margin-left: auto; font-size: 10px; color: var(--muted-2); }
.ir-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.4rem 0.8rem;
}
.ir-row { display: flex; align-items: center; gap: 0.5rem; }
.ir-r {
  font-size: 10px; font-weight: 600; padding: 0.05rem 0.35rem;
  border-radius: 3px; border: 1px solid; flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.ir-pair { flex: 1; min-width: 0; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ir-x { color: #38bdf8; }
.ir-y { color: #22c55e; }
.ir-arr { color: var(--muted-2); margin: 0 0.3rem; }
.ir-n { font-size: 10px; color: var(--muted-2); }

.hero { display: flex; align-items: center; gap: 1.4rem; }
.ring {
  --pct: 0deg;
  width: 130px; height: 130px; border-radius: 50%; flex-shrink: 0;
  background:
    conic-gradient(currentColor var(--pct), var(--surface-2) 0deg) padding-box,
    var(--surface);
  display: flex; align-items: center; justify-content: center;
  color: #38bdf8;
}
.ring.good { color: #22c55e; }
.ring.bad { color: #ef4444; }
.ring-inner {
  width: 100px; height: 100px; border-radius: 50%; background: var(--surface);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.ring-num { font-size: 2.2rem; font-weight: 700; font-family: ui-monospace, monospace; line-height: 1; color: var(--text); }
.ring-lbl { font-size: 0.7rem; color: var(--muted-2); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.2rem; }
.hero-blurb { display: flex; flex-direction: column; gap: 0.35rem; }
.hero-line { font-size: 0.95rem; color: var(--text); }
.hero-line:first-child { font-size: 1.05rem; font-weight: 500; }
.hero-line .muted { color: var(--muted); font-size: 0.85rem; }
.hero-line strong.good { color: #22c55e; }
.hero-line strong.bad { color: #ef4444; }

.kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 0.5rem;
}
.kpi-tile {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.65rem 0.85rem;
  text-decoration: none; color: inherit;
}
.kpi-tile.sober-tile { border-color: rgba(34, 197, 94, 0.25); cursor: pointer; }
.kpi-tile.sober-tile:hover { border-color: rgba(34, 197, 94, 0.6); background: rgba(34, 197, 94, 0.04); }
.kpi-lbl { font-size: 0.7rem; color: var(--muted-2); text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-num { font-size: 1.45rem; font-family: ui-monospace, monospace; line-height: 1.2; margin: 0.2rem 0 0.15rem; }
.kpi-num strong { font-weight: 600; }
.kpi-num .kpi-unit { font-size: 0.7rem; color: var(--muted); margin-left: 0.2rem; font-family: inherit; }
.kpi-num.bp-elevated strong { color: #eab308; }
.kpi-num.bp-stage1 strong { color: #f97316; }
.kpi-num.bp-stage2 strong { color: #ef4444; }
.kpi-num.bp-crisis strong { color: #b91c1c; }
.kpi-num.bp-normal strong { color: #22c55e; }
.kpi-sub { font-size: 0.75rem; }
.kpi-sub.muted { color: var(--muted); }

.ribbon-wrap { position: relative; margin-top: 0.4rem; }
.hr-ribbon { width: 100%; height: 60px; display: block; }
.ribbon-axis {
  display: flex; justify-content: space-between; font-size: 0.65rem;
  color: var(--muted-2); margin-top: 0.1rem; font-family: ui-monospace, monospace;
}

.hr-underlay {
  position: absolute; left: 0; right: 0; bottom: 0;
  width: 100%; height: 100px; pointer-events: none; z-index: 0;
}
.hr-stats-row {
  display: flex; gap: 0.8rem; align-items: baseline; font-size: 0.85rem;
  margin-bottom: 0.6rem; position: relative; z-index: 1;
}
.hr-stats-row strong { font-family: ui-monospace, monospace; font-size: 1.05rem; color: #ef4444; }
.hr-stats-row .muted { color: var(--muted); font-size: 0.75rem; font-family: ui-monospace, monospace; }

.radar-row { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(220px, 1fr); gap: 1rem; align-items: center; position: relative; z-index: 1; }
@media (max-width: 700px) { .radar-row { grid-template-columns: 1fr; } }
.radar-chart { height: 280px; }
.radar-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.rad-stat { background: var(--surface-2); border-radius: 6px; padding: 0.5rem 0.7rem; }
.rad-stat .lbl { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.rad-stat .val { font-size: 1.4rem; font-weight: 600; font-family: ui-monospace, monospace; margin: 0.1rem 0; }
.rad-stat .sub { color: var(--muted); font-size: 0.75rem; }
.rad-stat .good, .val.good { color: #22c55e; }
.rad-stat .bad, .val.bad { color: #ef4444; }

.bp-latest { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.4rem 0; }
.bp-big { display: flex; align-items: baseline; gap: 0.3rem; font-family: ui-monospace, monospace; font-weight: 600; }
.bp-big .sys, .bp-big .dia { font-size: 2rem; }
.bp-big .slash { font-size: 1.5rem; color: var(--muted-2); }
.bp-big .unit { font-size: 0.75rem; color: var(--muted); margin-left: 0.4rem; }
.bp-meta { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; font-size: 0.85rem; }
.bp-meta .muted { color: var(--muted); }
.bp-tag { padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 500; }
.bp-normal { color: #22c55e; } .bp-normal.bp-tag { background: rgba(34, 197, 94, 0.15); }
.bp-elevated { color: #eab308; } .bp-elevated.bp-tag { background: rgba(234, 179, 8, 0.15); }
.bp-stage1 { color: #f97316; } .bp-stage1.bp-tag { background: rgba(249, 115, 22, 0.15); }
.bp-stage2 { color: #ef4444; } .bp-stage2.bp-tag { background: rgba(239, 68, 68, 0.15); }
.bp-crisis { color: #b91c1c; } .bp-crisis.bp-tag { background: rgba(185, 28, 28, 0.2); font-weight: 700; }
.bp-avg { font-size: 0.8rem; color: var(--muted); }
.bp-actions { margin: 0.6rem 0 0; }
.bp-form { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-top: 0.6rem; }
.bp-form input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.35rem 0.5rem; width: 80px; font-size: 0.9rem; font-family: inherit; }
.bp-form .bp-notes { width: 100%; }
.bp-form .primary { background: var(--accent); color: var(--accent-text); border: 1px solid var(--accent); border-radius: 4px; padding: 0.4rem 0.9rem; cursor: pointer; }
.bp-form .primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
