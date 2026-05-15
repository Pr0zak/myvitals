<script setup lang="ts">
/**
 * Today — redesigned dashboard. Stack after TODAY-1 + TODAY-2:
 *   PageHeader · Hero · LiveVitals · WatchStatus ·
 *   (BodyMetrics / BloodPressure) · ActivityRow · CoachHint ·
 *   AnnotationLog · LifestyleStrip · GoalsTile · Footer
 *
 * AIInsights (the topic explorer) is gone — full Coach lives at
 * /analytics?tab=coach and gets a single-line link below the
 * activity row. The Hero verdict is the only AI surface inline.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import type {
  Activity, Annotation, HeartRateSeries, HrvSeries,
  SleepNight, StepsSeries, TodaySummary,
} from "@/api/types";
import "@/styles/today-tokens.css";

import PageHeader from "@/components/today/PageHeader.vue";
import Hero from "@/components/today/Hero.vue";
import LiveVitals from "@/components/today/LiveVitals.vue";
import WatchStatus from "@/components/today/WatchStatus.vue";
import ActivityRow from "@/components/today/ActivityRow.vue";
import BodyMetrics from "@/components/today/BodyMetrics.vue";
import BloodPressure from "@/components/today/BloodPressure.vue";
import AnnotationLog from "@/components/today/AnnotationLog.vue";
import GoalsTile from "@/components/today/GoalsTile.vue";
import LifestyleStrip from "@/components/today/LifestyleStrip.vue";
import Footer from "@/components/today/Footer.vue";

const loading = ref(true);
const error = ref<string | null>(null);

// ── Data ──
const summary = ref<TodaySummary | null>(null);
const summary7d = ref<TodaySummary[]>([]);     // last 7 daily rows for sparks/baseline
const hr24 = ref<HeartRateSeries | null>(null);
const hrv24 = ref<HrvSeries | null>(null);
const sleep = ref<SleepNight | null>(null);
const steps24 = ref<StepsSeries | null>(null);
const activities = ref<Activity[]>([]);
const strengthWorkouts = ref<Awaited<ReturnType<typeof api.strengthWorkouts>>["workouts"]>([]);
const annotations = ref<Annotation[]>([]);
const goals = ref<Array<{
  id: number; kind: string; title: string;
  target_value: number | null; target_unit: string | null;
  current_value: number | null; progress_pct: number | null;
}>>([]);
const soberCurrent = ref<{ days: number | null; hours: number | null } | null>(null);
const fastingCurrent = ref<{
  isActive: boolean; startedAt: string;
  targetHours: number | null; currentStage: string;
} | null>(null);
const lastSync = ref<string | null>(null);
const version = ref<string>("0.0.0");

// Body / BP
const profile = ref<Awaited<ReturnType<typeof api.getProfile>> | null>(null);
const weightSeries = ref<Array<{ date: string; weight_kg: number }>>([]);
const bpSeries = ref<{
  latest: { systolic: number; diastolic: number; time: string } | null;
  points: Array<{ time: string; systolic: number; diastolic: number }>;
} | null>(null);

// AI
const aiCfg = ref<Awaited<ReturnType<typeof api.aiConfig>> | null>(null);
const aiVerdict = ref<{ content: string; generated_at: string; model: string } | null>(null);
const aiVerdictBusy = ref(false);

async function loadCore() {
  loading.value = true;
  error.value = null;
  try {
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 6);
    sevenDaysAgo.setHours(0, 0, 0, 0);
    const dayAgo = new Date(Date.now() - 24 * 3600 * 1000);
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    // TODAY-4: try the bundled snapshot endpoint first. When present
    // (v0.7.221+), it collapses 13 of the 16 round-trips into one.
    // The remaining three — version, activities, strengthWorkouts —
    // stay parallel since the snapshot doesn't carry them yet.
    const snap = await api.todaySnapshot().catch(() => null);

    if (snap) {
      const [a, sw, ver] = await Promise.all([
        api.activities({ since: thirtyDaysAgo, limit: 30 }).catch(() => []),
        api.strengthWorkouts({ limit: 5 }).catch(() => ({ count: 0, workouts: [] })),
        api.version().catch(() => ({ version: "?", git_sha: "?", build_time: "?" })),
      ]);
      summary.value = snap.today as TodaySummary;
      summary7d.value = (snap.summary7d as TodaySummary[]) ?? [];
      hr24.value = snap.hr24 as HeartRateSeries | null;
      hrv24.value = snap.hrv24 as HrvSeries | null;
      sleep.value = snap.sleep_last as SleepNight | null;
      steps24.value = snap.steps24 as StepsSeries | null;
      activities.value = a;
      strengthWorkouts.value = sw.workouts ?? [];
      annotations.value = (snap.annotations1d as Annotation[]) ?? [];
      version.value = ver.version;
      lastSync.value = (snap.today as TodaySummary | null)?.last_sync ?? null;
      profile.value = snap.profile as any;
      weightSeries.value = (snap.weight30 as any)?.points ?? [];
      bpSeries.value = snap.bp30 as any;
      goals.value = (snap.goals as any) ?? [];
      const sob = snap.sober as { active?: unknown; days?: number; hours?: number } | null;
      soberCurrent.value = sob && sob.active
        ? { days: sob.days ?? null, hours: sob.hours ?? null }
        : null;
      const fst = snap.fasting as { is_active?: boolean; started_at?: string;
        target_hours?: number; current_stage?: string } | null;
      fastingCurrent.value = fst
        ? {
            isActive: fst.is_active ?? true,
            startedAt: fst.started_at ?? "",
            targetHours: fst.target_hours ?? null,
            currentStage: fst.current_stage ?? "",
          }
        : null;
      loading.value = false;
      return;
    }

    // Fallback: original per-call fan-out for pre-v0.7.221 servers.
    const [s, s7, h, hv, sl, st, a, sw, an, ver, prof, ws, bps, gs, sob, fst] = await Promise.all([
      api.todaySummary(),
      api.summaryRange(sevenDaysAgo).catch(() => []),
      api.heartRate({ since: dayAgo }).catch(() => null),
      api.hrv({ since: dayAgo }).catch(() => null),
      api.lastSleep().catch(() => null),
      api.steps({ since: dayAgo }).catch(() => null),
      api.activities({ since: thirtyDaysAgo, limit: 30 }).catch(() => []),
      api.strengthWorkouts({ limit: 5 }).catch(() => ({ count: 0, workouts: [] })),
      api.listAnnotations({ since: dayAgo, limit: 50 }).catch(() => []),
      api.version().catch(() => ({ version: "?", git_sha: "?", build_time: "?" })),
      api.getProfile().catch(() => null),
      api.weight({ since: thirtyDaysAgo }).catch(() => ({ points: [] as any })),
      api.bloodPressure({ since: thirtyDaysAgo }).catch(() => null),
      api.aiGoals(true).catch(() => []),
      api.soberCurrent().catch(() => null),
      api.fastingCurrent().catch(() => null),
    ]);
    summary.value = s;
    summary7d.value = s7;
    hr24.value = h;
    hrv24.value = hv;
    sleep.value = sl;
    steps24.value = st;
    activities.value = a;
    strengthWorkouts.value = sw.workouts ?? [];
    annotations.value = an;
    version.value = ver.version;
    lastSync.value = s?.last_sync ?? null;
    profile.value = prof as any;
    weightSeries.value = (ws as any)?.points ?? [];
    bpSeries.value = bps as any;
    goals.value = gs as any;
    soberCurrent.value = sob && sob.active
      ? { days: sob.days ?? null, hours: sob.hours ?? null }
      : null;
    fastingCurrent.value = fst
      ? {
          isActive: (fst as any).is_active ?? true,
          startedAt: (fst as any).started_at,
          targetHours: (fst as any).target_hours ?? null,
          currentStage: (fst as any).current_stage ?? "",
        }
      : null;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

async function loadAi() {
  try { aiCfg.value = await api.aiConfig(); } catch { return; }
  if (!aiCfg.value?.enabled) return;
  try { aiVerdict.value = await api.aiVerdictLatest(); } catch { /* ignore */ }
}

async function refreshVerdict() {
  if (!aiCfg.value?.enabled) return;
  aiVerdictBusy.value = true;
  try { aiVerdict.value = await api.aiVerdict(); }
  catch { /* ignore */ }
  finally { aiVerdictBusy.value = false; }
}

// AIInsights / topic explorer removed from Today in TODAY-2.
// The full multi-card Coach experience lives on /coach (or
// /analytics?tab=coach). Today keeps only the Hero verdict for
// a single-glance read.

// Live polling — every 30s while the tab is visible, refresh just the
// rapidly-changing data (HR, HRV, steps, summary). Heavy queries
// (activities, BP/weight 30d, annotations) stay on the loadCore path
// — they don't change minute-to-minute. Pause when tab is hidden so
// background tabs don't burn requests.
let liveTickHandle: number | null = null;
async function loadLive() {
  if (document.visibilityState !== "visible") return;
  const dayAgo = new Date(Date.now() - 24 * 3600 * 1000);
  const [s, h, hv, st] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.heartRate({ since: dayAgo }).catch(() => null),
    api.hrv({ since: dayAgo }).catch(() => null),
    api.steps({ since: dayAgo }).catch(() => null),
  ]);
  if (s) { summary.value = s; lastSync.value = s.last_sync ?? null; }
  if (h) hr24.value = h;
  if (hv) hrv24.value = hv;
  if (st) steps24.value = st;
}

onMounted(() => {
  loadCore(); loadAi();
  liveTickHandle = window.setInterval(loadLive, 30_000);
});
onBeforeUnmount(() => { if (liveTickHandle) clearInterval(liveTickHandle); });
useVisibilityRefresh(() => { loadCore(); loadAi(); });

// ── Derived: hero anchors ──
const headerDate = computed(() => {
  return new Date().toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
});

function fmtSleepHM(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

function avg(xs: number[]): number | null {
  if (!xs.length) return null;
  return xs.reduce((s, v) => s + v, 0) / xs.length;
}

const baseline7d = computed(() => {
  const rows = summary7d.value.slice(0, -1);  // exclude today
  return {
    rhr: avg(rows.map((r) => r.resting_hr).filter((v): v is number => v != null)),
    hrv: avg(rows.map((r) => r.hrv_avg).filter((v): v is number => v != null)),
    sleep: avg(rows.map((r) => r.sleep_duration_s).filter((v): v is number => v != null)),
    steps: avg(rows.map((r) => r.steps_total).filter((v): v is number => v != null)),
  };
});

const stepsGoal = computed(() => {
  const extra = (profile.value as any)?.extra ?? {};
  return Math.max(1, (extra.steps_goal as number) ?? 10_000);
});
const sleepGoalH = computed(() => {
  const extra = (profile.value as any)?.extra ?? {};
  return (extra.sleep_goal_h as number) ?? 8;
});

const heroAnchors = computed(() => {
  const s = summary.value;
  if (!s) return [];
  const sleepDelta = (s.sleep_duration_s != null && baseline7d.value.sleep != null)
    ? Math.round((s.sleep_duration_s - baseline7d.value.sleep) / 60) : null;
  const rhrDelta = (s.resting_hr != null && baseline7d.value.rhr != null)
    ? Math.round(s.resting_hr - baseline7d.value.rhr) : null;
  const hrvDelta = (s.hrv_avg != null && baseline7d.value.hrv != null)
    ? Math.round(s.hrv_avg - baseline7d.value.hrv) : null;
  const stepsPct = s.steps_total != null
    ? Math.round((s.steps_total / stepsGoal.value) * 100) : null;
  const stepsBaselinePct = baseline7d.value.steps != null
    ? Math.round((baseline7d.value.steps / stepsGoal.value) * 100) : null;
  const stepsDelta = stepsPct != null && stepsBaselinePct != null
    ? stepsPct - stepsBaselinePct : null;
  return [
    {
      label: "Sleep",
      value: fmtSleepHM(s.sleep_duration_s),
      sub: s.sleep_score != null ? `· ${Math.round(s.sleep_score)}` : null,
      delta: sleepDelta, invert: false, suffix: "m",
    },
    {
      label: "Resting HR",
      value: s.resting_hr != null ? `${Math.round(s.resting_hr)}` : "—",
      unit: "bpm", delta: rhrDelta, invert: true, suffix: "",
    },
    {
      label: "HRV",
      value: s.hrv_avg != null ? `${Math.round(s.hrv_avg)}` : "—",
      unit: "ms", delta: hrvDelta, invert: false, suffix: "",
    },
    {
      label: "Steps",
      value: s.steps_total != null ? s.steps_total.toLocaleString() : "—",
      unit: `/ ${(stepsGoal.value / 1000).toFixed(0)}k`,
      delta: stepsDelta, invert: false, suffix: "%",
    },
  ];
});

function tone(score: number | null, lo = 50, hi = 70): "good" | "warn" | "bad" {
  if (score == null) return "warn";
  if (score < lo) return "bad";
  if (score < hi) return "warn";
  return "good";
}

const heroScores = computed(() => {
  const s = summary.value;
  if (!s) return [];
  // 7d sparks per metric
  const recoverySpark = summary7d.value
    .map((r) => r.recovery_score).filter((v): v is number => v != null);
  const readinessSpark = summary7d.value
    .map((r) => r.readiness_score).filter((v): v is number => v != null);
  const sleepSparkScore = summary7d.value
    .map((r) => r.sleep_score).filter((v): v is number => v != null);
  const tsbSpark = summary7d.value
    .map((r) => r.tsb).filter((v): v is number => v != null);
  return [
    {
      label: "Recovery", value: s.recovery_score != null ? Math.round(s.recovery_score) : null,
      tone: tone(s.recovery_score) as any, spark: recoverySpark, mode: "line" as const,
    },
    {
      label: "Readiness", value: s.readiness_score != null ? Math.round(s.readiness_score) : null,
      tone: tone(s.readiness_score) as any, spark: readinessSpark, mode: "line" as const,
    },
    {
      // Each value is a discrete per-night score — bars communicate
      // that better than a smoothed line.
      label: "Sleep", value: s.sleep_score != null ? Math.round(s.sleep_score) : null,
      tone: tone(s.sleep_score) as any, spark: sleepSparkScore, mode: "bar" as const,
    },
    {
      label: "TSB", value: s.tsb != null ? Math.round(s.tsb) : null,
      tone: (s.tsb != null && s.tsb < -10 ? "warn" : "good") as any,
      spark: tsbSpark, mode: "line" as const,
    },
  ];
});

const heroReadiness = computed(() => Math.round(summary.value?.readiness_score ?? 0));
const heroReadinessTone = computed(() => tone(summary.value?.readiness_score ?? null));

// Downsample 24h points into N equal-width buckets. Empty buckets
// are emitted as nulls so the sparkline draws genuine gaps rather
// than carrying the previous value forward.
function downsample(
  points: Array<{ time: string; value: number }>, buckets: number,
): Array<number | null> {
  if (points.length === 0) return [];
  const start = Date.now() - 24 * 3600_000;
  const span = 24 * 3600_000;
  const sums = new Array(buckets).fill(0);
  const counts = new Array(buckets).fill(0);
  for (const p of points) {
    const t = new Date(p.time).getTime();
    if (t < start) continue;
    const idx = Math.min(buckets - 1, Math.floor(((t - start) / span) * buckets));
    sums[idx] += p.value;
    counts[idx] += 1;
  }
  const out: Array<number | null> = [];
  for (let i = 0; i < buckets; i++) {
    out.push(counts[i] > 0 ? sums[i] / counts[i] : null);
  }
  return out;
}
function bucketSumByHour(points: Array<{ time: string; value: number }>): number[] {
  const buckets: number[] = Array(24).fill(0);
  const now = Date.now();
  for (const p of points) {
    const ageH = Math.floor((now - new Date(p.time).getTime()) / 3600_000);
    if (ageH < 0 || ageH >= 24) continue;
    buckets[23 - ageH] += p.value;
  }
  return buckets;
}

const liveHr = computed(() => {
  const pts = hr24.value?.points ?? [];
  const series = downsample(pts, 96);   // 24h ÷ 15-min buckets = 96 points
  const last = pts[pts.length - 1] ?? null;
  const ageMs = last ? Date.now() - new Date(last.time).getTime() : null;
  const ageLabel = ageMs == null ? null
    : ageMs < 90_000 ? "live"
    : ageMs < 60 * 60_000 ? `${Math.floor(ageMs / 60_000)} min ago`
    : `${Math.floor(ageMs / 3_600_000)}h ago`;
  return {
    latest: last?.value ?? null,
    rest: summary.value?.resting_hr ?? null,
    ageLabel,
    series,
    mean: hr24.value?.avg ?? null,
    min: hr24.value?.min_bpm ?? null,
    max: hr24.value?.max_bpm ?? null,
  };
});

const liveHrv = computed(() => {
  const pts = hrv24.value?.points ?? [];
  const series = downsample(pts, 48);   // HRV is noisier; 48 buckets is plenty
  const last = pts[pts.length - 1] ?? null;
  const baseline = baseline7d.value.hrv;
  const delta = (last && baseline != null)
    ? Math.round(last.value - baseline) : null;
  const vals = pts.map((p) => p.value);
  const min = vals.length ? Math.min(...vals) : null;
  const max = vals.length ? Math.max(...vals) : null;
  return {
    latest: last?.value ?? null,
    series,
    mean: baseline,
    deltaVsBaseline: delta,
    min, max,
  };
});

const liveSteps = computed(() => {
  const pts = steps24.value?.points ?? [];
  return {
    total: steps24.value?.total ?? summary.value?.steps_total ?? 0,
    goal: stepsGoal.value,
    hourly: bucketSumByHour(pts),
    currentHour: new Date().getHours(),
  };
});

// ── Activity row ──
const cardioCell = computed(() => {
  // Latest non-strength, non-rower activity in the last 24-48h.
  const cardio = activities.value.find(
    (a) => !["strength", "rower", "rowerg", "skierg", "bikeerg"].includes(a.type),
  );
  if (!cardio) return null;
  const start = new Date(cardio.start_at);
  const ageMs = Date.now() - start.getTime();
  const whenLabel = ageMs < 24 * 3_600_000
    ? `Today · ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : start.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  const miles = cardio.distance_m != null
    ? (cardio.distance_m / 1609.34).toFixed(2) : null;
  const dur = cardio.duration_s
    ? `${Math.floor(cardio.duration_s / 60)}:${String(cardio.duration_s % 60).padStart(2, "0")}`
    : null;
  return {
    title: cardio.name ?? cardio.type,
    whenLabel,
    miles,
    duration: dur,
    avgHr: cardio.avg_hr,
    source: cardio.source,
    sourceId: cardio.source_id,
  };
});

const strengthCell = computed(() => {
  const w = strengthWorkouts.value.find((x) => x.status !== "regenerated");
  if (!w) return null;
  const start = w.started_at ? new Date(w.started_at) : new Date(w.date + "T00:00:00");
  const ageMs = Date.now() - start.getTime();
  const whenLabel = ageMs < 24 * 3_600_000
    ? `Today · ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : start.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return {
    title: w.split_focus === "yoga"
      ? "Yoga flow"
      : `${w.split_focus.replace(/_/g, " ")}${w.split_focus !== "rest" ? " · session" : ""}`,
    whenLabel,
    setCount: (w as any).set_count ?? null,
    avgRpe: (w as any).rpe_avg ?? null,
    status: w.status,
    workoutDate: w.date,
  };
});

const ergCell = computed(() => {
  const erg = activities.value.find((a) =>
    ["rower", "rowerg", "skierg", "bikeerg"].includes(a.type));
  if (!erg) return null;
  const start = new Date(erg.start_at);
  const ageMs = Date.now() - start.getTime();
  const whenLabel = ageMs < 24 * 3_600_000
    ? `Today · ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : start.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  let pace500: string | null = null;
  if (erg.distance_m && erg.duration_s) {
    const splitS = erg.duration_s * 500 / erg.distance_m;
    const m = Math.floor(splitS / 60);
    const s = (splitS - m * 60).toFixed(1);
    pace500 = `${m}:${s.padStart(4, "0")}`;
  }
  return {
    title: erg.name ?? `${erg.type} session`,
    whenLabel,
    meters: erg.distance_m != null ? Math.round(erg.distance_m).toLocaleString() : null,
    pace500,
    avgWatts: erg.avg_power_w != null ? Math.round(erg.avg_power_w) : null,
    source: erg.source,
    sourceId: erg.source_id,
  };
});

// ── Body / BP ──
const KG_TO_LB = 2.20462;
const weightLbSeries = computed(() =>
  weightSeries.value.map((p) => +(p.weight_kg * KG_TO_LB).toFixed(1)),
);
const latestLb = computed(() =>
  weightLbSeries.value.length ? weightLbSeries.value[weightLbSeries.value.length - 1] : null,
);
const goalLb = computed(() => {
  const kg = profile.value?.weight_goal_kg;
  return kg != null ? +(kg * KG_TO_LB).toFixed(1) : null;
});
const delta30Lb = computed(() => {
  if (weightLbSeries.value.length < 2) return null;
  return weightLbSeries.value[weightLbSeries.value.length - 1] - weightLbSeries.value[0];
});
const weightFromLabel = computed(() => {
  if (!weightSeries.value.length) return "—";
  return new Date(weightSeries.value[0].date).toLocaleDateString([], { month: "short", day: "numeric" });
});
const weightToLabel = computed(() =>
  new Date().toLocaleDateString([], { month: "short", day: "numeric" }),
);
const weightAsOfLabel = computed(() => {
  const last = weightSeries.value[weightSeries.value.length - 1];
  if (!last) return null;
  return new Date(last.date).toLocaleString([], {
    weekday: "short", hour: "2-digit", minute: "2-digit",
  });
});

const bpSysSeries = computed(() =>
  (bpSeries.value?.points ?? []).map((p) => p.systolic),
);
const bpDiaSeries = computed(() =>
  (bpSeries.value?.points ?? []).map((p) => p.diastolic),
);
const bpAsOfLabel = computed(() => {
  const t = bpSeries.value?.latest?.time;
  return t ? new Date(t).toLocaleString([], {
    weekday: "short", hour: "2-digit", minute: "2-digit",
  }) : null;
});

// ── Annotation log chips ──
const annotationChips = computed(() =>
  annotations.value.slice(0, 12).map((a) => {
    const t = new Date(a.ts);
    const ageMs = Date.now() - t.getTime();
    const when = ageMs < 24 * 3_600_000
      ? t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : t.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
    const payload = (a.payload ?? {}) as Record<string, any>;
    let label = a.type;
    if (payload.amount && payload.unit) label = `${payload.amount}${payload.unit}`;
    if (payload.label) label = payload.label;
    if (payload.note) label = String(payload.note).slice(0, 32);
    return { id: a.id, kind: a.type, label, whenLabel: when };
  }),
);

// ── BP slide-over (deferred — for now a route to /blood-pressure form) ──
import { RouterLink, useRouter } from "vue-router";
const router = useRouter();
function openBp() { router.push("/blood-pressure"); }
function openLog() { router.push("/journal"); }

async function refreshAnnotations() {
  const dayAgo = new Date(Date.now() - 24 * 3600 * 1000);
  try {
    annotations.value = await api.listAnnotations({ since: dayAgo, limit: 50 });
  } catch { /* non-fatal — chip strip will refresh next loadCore */ }
}
</script>

<template>
  <div class="today-redesign today">
    <PageHeader :date="headerDate" :loading="loading" :last-sync-iso="lastSync"
                @refresh="loadCore"/>

    <p v-if="error" class="err">{{ error }}</p>

    <Hero
      v-if="summary"
      :readiness="heroReadiness"
      :readiness-tone="heroReadinessTone"
      :verdict="aiVerdict?.content ?? null"
      :ai-enabled="!!aiCfg?.enabled"
      :anchors="heroAnchors"
      :scores="heroScores"
      :on-verdict-refresh="refreshVerdict"
    />

    <LiveVitals
      :hr="liveHr"
      :hrv="liveHrv"
      :steps="liveSteps"
    />

    <WatchStatus/>

    <div class="two-col body-row">
      <BodyMetrics
        :latest-lb="latestLb"
        :goal-lb="goalLb"
        :series="weightLbSeries"
        :delta30-lb="delta30Lb"
        :from-label="weightFromLabel"
        :to-label="weightToLabel"
        :as-of-label="weightAsOfLabel"
      />
      <BloodPressure
        :latest="bpSeries?.latest ?? null"
        :sys="bpSysSeries"
        :dia="bpDiaSeries"
        :as-of-label="bpAsOfLabel"
        @log="openBp"
      />
    </div>

    <ActivityRow
      :cardio="cardioCell"
      :strength="strengthCell"
      :erg="ergCell"
    />

    <p v-if="aiCfg?.enabled" class="coach-hint">
      Want deeper synthesis?
      <RouterLink to="/analytics?tab=coach">Open Coach →</RouterLink>
    </p>

    <AnnotationLog
      :chips="annotationChips"
      @log="openLog"
      @added="refreshAnnotations"
    />

    <LifestyleStrip :sober="soberCurrent" :fasting="fastingCurrent"/>

    <GoalsTile :goals="goals"/>

    <Footer :version="version"/>
  </div>
</template>

<style scoped>
.today {
  padding: 20px 32px 16px;
  display: flex; flex-direction: column; gap: 16px;
  font-family: var(--sans);
  min-height: 100vh;
}
.two-col { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; }
.body-row { grid-template-columns: 1fr 1fr; }
.coach-hint { font-size: 0.85rem; color: var(--on-surface-2); margin: 4px 0; }
.coach-hint a { color: #38bdf8; text-decoration: none; }
.coach-hint a:hover { text-decoration: underline; }
.err { color: var(--bad); }
@media (max-width: 720px) {
  .today { padding: 16px; gap: 12px; }
  .two-col { grid-template-columns: 1fr; }
}
</style>
