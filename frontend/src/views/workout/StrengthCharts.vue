<script setup lang="ts">
/**
 * Strength workout charts — daily volume, per-muscle volume,
 * weight progression. Reads /workout/strength/stats.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import BodyMap from "@/components/BodyMap.vue";
import ConsistencyCard from "@/components/ConsistencyCard.vue";
import { api } from "@/api/client";
import { chartTheme, isNeon } from "@/theme";
import type { TrainingConsistency } from "@/api/types";

const days = ref<number>(90);
const loading = ref(true);
const error = ref<string | null>(null);

interface Stats {
  since: string; days: number; n_workouts: number; n_sets: number;
  total_volume_lb: number; rpe_avg: number | null;
  daily: Array<{ date: string; volume_lb: number; sets: number }>;
  per_muscle: Array<{ muscle: string; volume_lb: number }>;
  progression: Record<string, Array<{ date: string; top_weight_lb: number; e1rm?: number }>>;
  progression_names: Record<string, string>;
  /** CONS-1: full-history streaks + frequency; independent of `days`. */
  consistency?: TrainingConsistency | null;
}
const stats = ref<Stats | null>(null);

// PR-1: all-time per-exercise records — independent of the range picker,
// fetched once on mount.
type StrengthRecord = Awaited<ReturnType<typeof api.strengthRecords>>["records"][number];
const records = ref<StrengthRecord[]>([]);

async function load() {
  loading.value = true; error.value = null;
  try {
    stats.value = await api.strengthStats(days.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally { loading.value = false; }
}
async function loadRecords() {
  try {
    records.value = (await api.strengthRecords()).records;
  } catch { /* records are non-critical; leave empty on failure */ }
}
// MMAP-1: 7-day muscle-volume status for the body map (fixed weekly window,
// independent of the range picker — the map is a "this week's balance" audit).
type MuscleVol = Awaited<ReturnType<typeof api.strengthMuscleVolume>>["muscles"];
const muscleVol = ref<MuscleVol>({});
async function loadMuscleVol() {
  try {
    muscleVol.value = (await api.strengthMuscleVolume(7)).muscles;
  } catch { /* map is non-critical; leave empty (all untrained) on failure */ }
}
// VOLT-1: weekly volume over a fixed 16-week mesocycle window (independent of
// the range picker), fetched once on mount.
type VolumeTrend = Awaited<ReturnType<typeof api.strengthVolumeTrend>>["trend"];
const volumeTrend = ref<VolumeTrend>([]);
async function loadVolumeTrend() {
  try {
    volumeTrend.value = (await api.strengthVolumeTrend(16)).trend;
  } catch { /* non-critical; leave empty on failure */ }
}
onMounted(() => { load(); loadRecords(); loadMuscleVol(); loadVolumeTrend(); });
watch(days, load);

function fmtRecDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}

// Selected exercise for the progression chart
const selectedExercise = ref<string>("");
watch(stats, (s) => {
  if (s && !selectedExercise.value) {
    selectedExercise.value = Object.keys(s.progression)[0] ?? "";
  } else if (s && !(selectedExercise.value in s.progression)) {
    selectedExercise.value = Object.keys(s.progression)[0] ?? "";
  }
});

// Match the existing dashboard's volume colour (neon → magenta).
const VOLUME_COLOR = computed(() => (isNeon.value ? "#ff3ad8" : "#a855f7"));

const dailyOption = computed(() => {
  const t = chartTheme.value;
  const s = stats.value;
  void isNeon.value;
  if (!s || s.daily.length < 2) return null;
  const vol = VOLUME_COLOR.value;
  return {
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: {
      type: "category",
      data: s.daily.map((d) => d.date),
      axisLabel: { ...t.axisLabel,
        formatter: (v: string) => v.slice(5) },
    },
    yAxis: { type: "value", name: "lb",
             axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      name: "Volume", type: "line",
      smooth: true, symbol: "circle", symbolSize: 4,
      data: s.daily.map((d) => d.volume_lb),
      lineStyle: { color: vol, width: 2 },
      itemStyle: { color: vol },
      areaStyle: { color: vol, opacity: 0.18 },
    }],
  };
});

// VOLT-1: weekly mesocycle volume bars (fixed 16-week window).
const weeklyOption = computed(() => {
  const t = chartTheme.value;
  const tr = volumeTrend.value;
  void isNeon.value;
  // Backend zero-fills the full 16-week spine, so length is always 16 — only
  // chart when at least 2 weeks actually have training (else empty/1-bar).
  if (!tr || tr.filter((r) => r.volume_lb > 0).length < 2) return null;
  const vol = VOLUME_COLOR.value;
  return {
    grid: { left: 56, right: 16, top: 24, bottom: 40 },
    tooltip: {
      trigger: "axis", ...t.tooltip,
      formatter: (ps: { name: string; value: number }[]) => {
        const p = ps[0];
        const row = tr.find((r) => r.week_start === p.name);
        return `Week of ${p.name}<br/>${Math.round(p.value).toLocaleString()} lb`
          + (row ? ` · ${row.sets} sets · ${row.workouts} workouts` : "");
      },
    },
    xAxis: {
      type: "category",
      data: tr.map((r) => r.week_start),
      axisLabel: { ...t.axisLabel, formatter: (v: string) => v.slice(5) },
    },
    yAxis: { type: "value", name: "lb",
             axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      name: "Weekly volume", type: "bar",
      data: tr.map((r) => r.volume_lb),
      itemStyle: { color: vol, borderRadius: [3, 3, 0, 0] },
    }],
  };
});

const MUSCLE_COLOURS: Record<string, string> = {
  chest: "#ef4444", back: "#3b82f6", shoulders: "#f59e0b",
  biceps: "#a855f7", triceps: "#ec4899",
  quadriceps: "#22c55e", hamstrings: "#10b981", glutes: "#14b8a6",
  calves: "#84cc16", abdominals: "#fbbf24",
  forearms: "#94a3b8", lats: "#3b82f6", traps: "#3b82f6",
};
const MUSCLE_COLOURS_NEON: Record<string, string> = {
  chest: "#ff5d7a", back: "#28e6ff", shoulders: "#ffb52e",
  biceps: "#ff3ad8", triceps: "#6f7bff",
  quadriceps: "#5dff3b", hamstrings: "#28e6ff", glutes: "#ff3ad8",
  calves: "#5dff3b", abdominals: "#ffb52e",
  forearms: "#9b9bb0", lats: "#28e6ff", traps: "#28e6ff",
};
function muscleColor(m: string): string {
  const map = isNeon.value ? MUSCLE_COLOURS_NEON : MUSCLE_COLOURS;
  return map[m.toLowerCase()] ?? (isNeon.value ? "#6f7bff" : "#64748b");
}

const muscleOption = computed(() => {
  const t = chartTheme.value;
  const s = stats.value;
  void isNeon.value;
  if (!s || !s.per_muscle.length) return null;
  return {
    grid: { left: 100, right: 24, top: 8, bottom: 24 },
    tooltip: { trigger: "axis", ...t.tooltip,
               valueFormatter: (v: number) => `${Math.round(v).toLocaleString()} lb` },
    xAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: {
      type: "category",
      data: s.per_muscle.map((m) => m.muscle),
      axisLabel: { ...t.axisLabel,
                   formatter: (v: string) => v.charAt(0).toUpperCase() + v.slice(1) },
    },
    series: [{
      type: "bar",
      data: s.per_muscle.map((m) => ({
        value: m.volume_lb,
        itemStyle: { color: muscleColor(m.muscle) },
      })),
    }],
  };
});

const progressionOption = computed(() => {
  const t = chartTheme.value;
  const s = stats.value;
  void isNeon.value;
  if (!s || !selectedExercise.value) return null;
  const pts = s.progression[selectedExercise.value] ?? [];
  if (pts.length < 2) return null;
  const prog = isNeon.value ? "#ff5d7a" : "#ef4444";
  const e1c = isNeon.value ? "#22d3ee" : "#0ea5e9";
  return {
    grid: { left: 56, right: 16, top: 34, bottom: 32 },
    legend: { data: ["Top weight", "e1RM"], top: 2, textStyle: t.axisLabel },
    tooltip: { trigger: "axis", ...t.tooltip,
               valueFormatter: (v: number | null) => (v == null ? "—" : `${v} lb`) },
    xAxis: {
      type: "category", data: pts.map((p) => p.date),
      axisLabel: { ...t.axisLabel, formatter: (v: string) => v.slice(5) },
    },
    yAxis: { type: "value", name: "lb", axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      name: "Top weight", type: "line",
      smooth: false, symbol: "circle", symbolSize: 6,
      data: pts.map((p) => p.top_weight_lb),
      lineStyle: { color: prog, width: 2 },
      itemStyle: { color: prog },
    }, {
      // e1RM-1: estimated 1-rep-max trend (Epley) — the canonical strength signal.
      name: "e1RM", type: "line",
      smooth: false, symbol: "circle", symbolSize: 5,
      data: pts.map((p) => p.e1rm ?? null),
      lineStyle: { color: e1c, width: 2, type: "dashed" },
      itemStyle: { color: e1c },
    }],
  };
});
</script>

<template>
  <section class="charts">
    <header>
      <h1>Workout charts</h1>
      <div class="ranges">
        <button v-for="d in [7, 30, 90, 365]" :key="d"
                class="range" :class="{ on: days === d }"
                @click="days = d">
          {{ d >= 365 ? "1y" : `${d}d` }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <template v-else-if="stats">
      <!-- CONS-1: sits above the range-bounded cards on purpose. Everything
           below reflects the selected window; these numbers deliberately do
           not, so putting them next to a "90d" toggle without saying so
           would imply they did. -->
      <ConsistencyCard :data="stats.consistency" noun="sessions" :show-muscles="true"/>

      <Card :flat="true" class="overview">
        <div class="stats-row">
          <div><div class="lbl">Workouts</div><div class="val">{{ stats.n_workouts }}</div></div>
          <div><div class="lbl">Sets</div><div class="val">{{ stats.n_sets }}</div></div>
          <div><div class="lbl">Volume</div>
               <div class="val">{{ Math.round(stats.total_volume_lb).toLocaleString() }} lb</div></div>
          <div v-if="stats.rpe_avg !== null">
            <div class="lbl">Avg RPE</div>
            <div class="val">{{ stats.rpe_avg.toFixed(1) }}</div>
          </div>
        </div>
      </Card>

      <Card v-if="dailyOption" title="Daily volume">
        <div class="chart"><VChart :option="dailyOption" autoresize /></div>
      </Card>
      <p v-else-if="stats.daily.length < 2" class="muted small">
        Need at least 2 sessions in this window for a daily-volume chart.
      </p>

      <Card v-if="weeklyOption" title="Weekly volume · 16-week mesocycle">
        <div class="chart"><VChart :option="weeklyOption" autoresize /></div>
      </Card>

      <Card title="Muscle balance · 7-day">
        <BodyMap :muscles="muscleVol" />
      </Card>

      <Card v-if="muscleOption" title="Volume by muscle">
        <div class="chart" style="height: 280px;"><VChart :option="muscleOption" autoresize /></div>
      </Card>

      <Card v-if="Object.keys(stats.progression).length" title="Weight progression">
        <div class="picker">
          <select v-model="selectedExercise">
            <option v-for="(name, id) in stats.progression_names" :key="id" :value="id">
              {{ name }}
            </option>
          </select>
        </div>
        <div v-if="progressionOption" class="chart">
          <VChart :option="progressionOption" autoresize />
        </div>
        <p v-else class="muted small">
          Need at least 2 sessions of this exercise to chart progression.
        </p>
      </Card>

      <Card v-if="records.length" title="Personal records">
        <table class="records">
          <thead>
            <tr><th>Exercise</th><th>Best set</th><th>Best e1RM</th><th>Last</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in records" :key="r.exercise_id">
              <td class="rec-name">{{ r.name }}</td>
              <td class="rec-num">
                {{ r.best_weight_lb }} lb
                <span class="rec-date">{{ fmtRecDate(r.best_weight_date) }}</span>
              </td>
              <td class="rec-num">
                {{ r.best_e1rm }} lb
                <span class="rec-date">{{ fmtRecDate(r.best_e1rm_date) }}</span>
              </td>
              <td class="rec-date">{{ fmtRecDate(r.last_performed_date) }}</td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </section>
</template>

<style scoped>
.charts { max-width: 880px; margin: 0 auto; padding: 1rem; }
header { display: flex; align-items: center; justify-content: space-between;
         margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem; }
header h1 { margin: 0; font-size: 1.25rem; }
.ranges { display: flex; gap: 0.3rem; }
.range { padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.8rem;
         border: 1px solid var(--line); background: var(--bg-2);
         color: var(--muted); cursor: pointer; }
.range.on { background: var(--accent, #ef4444); color: #fff;
            border-color: var(--accent, #ef4444); }
.muted { color: var(--muted); }
.err { color: var(--accent, #ef4444); }
.small { font-size: 0.85rem; }
.overview { padding: 1rem; margin-bottom: 0.6rem; }
.stats-row { display: flex; gap: 2rem; flex-wrap: wrap; }
.lbl { font-size: 0.7rem; letter-spacing: 0.06em; color: var(--muted);
       font-weight: 700; text-transform: uppercase; }
.val { font-size: 1.3rem; font-weight: 600;
       font-family: 'Geist Mono', ui-monospace, monospace; }
.chart { width: 100%; height: 320px; }
.chart > * { width: 100%; height: 100%; }
.records { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.records th { text-align: left; font-size: 0.68rem; letter-spacing: 0.05em;
  text-transform: uppercase; color: var(--muted); font-weight: 700;
  padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--line); }
.records td { padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--line); }
.records tr:last-child td { border-bottom: none; }
.rec-name { font-weight: 600; }
.rec-num { font-family: 'Geist Mono', ui-monospace, monospace; }
.rec-date { color: var(--muted); font-size: 0.72rem; }
.rec-num .rec-date { margin-left: 0.35rem; }
.picker { margin-bottom: 0.6rem; }
.picker select { background: var(--bg-2); color: var(--text);
                 border: 1px solid var(--line);
                 padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }

/* ---- Vitality Neon (neon-only; classic themes untouched) ---- */
html[data-theme="neon"] .charts {
  --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-track: #272a3b;
  min-height: 100vh; max-width: 880px; margin: -1.25rem auto 0;
  padding: 1.5rem 1.5rem 2rem;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink);
  font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}
html[data-theme="neon"] .charts header h1 {
  font-weight: 800; letter-spacing: -0.5px; color: var(--rn-ink);
}
html[data-theme="neon"] .charts .range {
  border: 1px solid #ffffff14; background: #ffffff08; color: var(--rn-mut);
  border-radius: 999px;
}
html[data-theme="neon"] .charts .range.on {
  background: rgba(255, 58, 216, 0.16); color: var(--rn-mag);
  border-color: rgba(255, 58, 216, 0.45);
  box-shadow: 0 0 12px rgba(255, 58, 216, 0.28);
}
html[data-theme="neon"] .charts .muted,
html[data-theme="neon"] .charts .lbl { color: var(--rn-mut); }
html[data-theme="neon"] .charts .err { color: #ff5d7a; }
html[data-theme="neon"] .charts .val {
  font-family: 'Space Grotesk', 'Geist Mono', ui-monospace, monospace;
  letter-spacing: -0.5px; color: var(--rn-ink);
}
html[data-theme="neon"] .charts .picker select {
  background: #ffffff08; color: var(--rn-ink);
  border: 1px solid #ffffff14; border-radius: 10px;
}
html[data-theme="neon"] .charts .records th,
html[data-theme="neon"] .charts .records .rec-date { color: var(--rn-mut); }
html[data-theme="neon"] .charts .records th,
html[data-theme="neon"] .charts .records td { border-color: #ffffff14; }
html[data-theme="neon"] .charts .rec-num { color: var(--rn-ink); }
</style>
