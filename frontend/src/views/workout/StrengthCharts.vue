<script setup lang="ts">
/**
 * Strength workout charts — daily volume, per-muscle volume,
 * weight progression. Reads /workout/strength/stats.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import { chartTheme } from "@/theme";

const days = ref<number>(90);
const loading = ref(true);
const error = ref<string | null>(null);

interface Stats {
  since: string; days: number; n_workouts: number; n_sets: number;
  total_volume_lb: number; rpe_avg: number | null;
  daily: Array<{ date: string; volume_lb: number; sets: number }>;
  per_muscle: Array<{ muscle: string; volume_lb: number }>;
  progression: Record<string, Array<{ date: string; top_weight_lb: number }>>;
  progression_names: Record<string, string>;
}
const stats = ref<Stats | null>(null);

async function load() {
  loading.value = true; error.value = null;
  try {
    stats.value = await api.strengthStats(days.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally { loading.value = false; }
}
onMounted(load);
watch(days, load);

// Selected exercise for the progression chart
const selectedExercise = ref<string>("");
watch(stats, (s) => {
  if (s && !selectedExercise.value) {
    selectedExercise.value = Object.keys(s.progression)[0] ?? "";
  } else if (s && !(selectedExercise.value in s.progression)) {
    selectedExercise.value = Object.keys(s.progression)[0] ?? "";
  }
});

// Match the existing dashboard's volume colour
const VOLUME_COLOR = "#a855f7";

const dailyOption = computed(() => {
  const t = chartTheme.value;
  const s = stats.value;
  if (!s || s.daily.length < 2) return null;
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
      lineStyle: { color: VOLUME_COLOR, width: 2 },
      itemStyle: { color: VOLUME_COLOR },
      areaStyle: { color: VOLUME_COLOR, opacity: 0.18 },
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
function muscleColor(m: string): string {
  return MUSCLE_COLOURS[m.toLowerCase()] ?? "#64748b";
}

const muscleOption = computed(() => {
  const t = chartTheme.value;
  const s = stats.value;
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
  if (!s || !selectedExercise.value) return null;
  const pts = s.progression[selectedExercise.value] ?? [];
  if (pts.length < 2) return null;
  return {
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    tooltip: { trigger: "axis", ...t.tooltip,
               valueFormatter: (v: number) => `${v} lb` },
    xAxis: {
      type: "category", data: pts.map((p) => p.date),
      axisLabel: { ...t.axisLabel, formatter: (v: string) => v.slice(5) },
    },
    yAxis: { type: "value", name: "lb", axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      name: "Top weight", type: "line",
      smooth: false, symbol: "circle", symbolSize: 6,
      data: pts.map((p) => p.top_weight_lb),
      lineStyle: { color: "#ef4444", width: 2 },
      itemStyle: { color: "#ef4444" },
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
.picker { margin-bottom: 0.6rem; }
.picker select { background: var(--bg-2); color: var(--text);
                 border: 1px solid var(--line);
                 padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }
</style>
