<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { apiBase, queryToken } from "@/config";
import { chartTheme } from "@/theme";

const METRICS = [
  { key: "hrv_avg", label: "HRV (RMSSD ms)" },
  { key: "resting_hr", label: "Resting HR (bpm)" },
  { key: "recovery_score", label: "Recovery score" },
  { key: "sleep_score", label: "Sleep score" },
  { key: "sleep_duration_s", label: "Sleep duration (s)" },
  { key: "steps_total", label: "Steps total" },
  { key: "activity_duration_s", label: "Activity duration (s)" },
  { key: "alcohol_count", label: "Alcohol drinks (count)" },
  { key: "caffeine_mg", label: "Caffeine (mg)" },
  { key: "mood_score", label: "Mood score" },
];

const x = ref("alcohol_count");
const y = ref("hrv_avg");
const lag = ref(1);
const days = ref(90);

interface Result {
  x_metric: string;
  y_metric: string;
  lag_days: number;
  n: number;
  pearson_r: number | null;
  points: { date: string; x: number; y: number }[];
}

const result = ref<Result | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

async function fetchData() {
  if (!queryToken.value) {
    error.value = "Set QUERY_TOKEN in Settings first.";
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const r = await axios.get<Result>(`${base}/analytics/correlate`, {
      headers: { Authorization: `Bearer ${queryToken.value}` },
      params: { x: x.value, y: y.value, lag: lag.value, days: days.value },
    });
    result.value = r.data;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(fetchData);
watch([x, y, lag, days], fetchData);

const scatterOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!result.value) return null;
  const points = result.value.points;
  if (points.length === 0) return null;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);

  const n = points.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0; let den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = my - slope * mx;
  const xMin = Math.min(...xs); const xMax = Math.max(...xs);
  const fitLine = den === 0 ? [] : [[xMin, slope * xMin + intercept], [xMax, slope * xMax + intercept]];

  return {
    grid: { left: 50, right: 12, top: 30, bottom: 36 },
    xAxis: { type: "value", name: result.value.x_metric, nameTextStyle: t.axisLabel, axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true },
    yAxis: { type: "value", name: result.value.y_metric, nameTextStyle: t.axisLabel, axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true },
    tooltip: {
      ...t.tooltip,
      trigger: "item",
      formatter: (p: any) => {
        const d = points[p.dataIndex];
        return `<b>${d.date}</b><br/>${result.value!.x_metric}: ${d.x.toFixed(2)}<br/>${result.value!.y_metric}: ${d.y.toFixed(2)}`;
      },
    },
    series: [
      {
        type: "scatter", symbolSize: 8,
        itemStyle: { color: t.palette.steps, opacity: 0.7 },
        data: points.map((p) => [p.x, p.y]),
      },
      ...(fitLine.length > 0 ? [{
        type: "line" as const, showSymbol: false, smooth: false, silent: true,
        lineStyle: { color: t.palette.recovery, width: 2, type: "dashed" as const },
        data: fitLine,
      }] : []),
    ],
  };
});

interface Preset { x: string; y: string; lag: number; label: string }
const PRESETS: Preset[] = [
  { x: "alcohol_count", y: "hrv_avg", lag: 1, label: "Alcohol → next-day HRV" },
  { x: "alcohol_count", y: "resting_hr", lag: 1, label: "Alcohol → next-day RHR" },
  { x: "alcohol_count", y: "sleep_score", lag: 0, label: "Alcohol → same-night sleep" },
  { x: "caffeine_mg", y: "sleep_score", lag: 0, label: "Caffeine → same-night sleep" },
  { x: "activity_duration_s", y: "hrv_avg", lag: 1, label: "Workout → next-day HRV" },
  { x: "activity_duration_s", y: "resting_hr", lag: 1, label: "Workout → next-day RHR" },
  { x: "sleep_duration_s", y: "recovery_score", lag: 0, label: "Sleep duration → recovery" },
  { x: "steps_total", y: "sleep_score", lag: 0, label: "Steps → that night's sleep" },
];

function applyPreset(p: Preset) { x.value = p.x; y.value = p.y; lag.value = p.lag; }

const rLabel = computed(() => {
  const r = result.value?.pearson_r;
  if (r === null || r === undefined) return "—";
  const abs = Math.abs(r);
  const strength = abs < 0.1 ? "no" : abs < 0.3 ? "weak" : abs < 0.5 ? "moderate" : abs < 0.7 ? "strong" : "very strong";
  const dir = r > 0 ? "positive" : "negative";
  return `${r.toFixed(3)}  (${strength} ${dir})`;
});
</script>

<template>
  <div class="insights">
    <h1>Insights</h1>
    <p class="hint">
      Pearson r between any two daily metrics. Negative lag means X precedes Y by N days.
      Need ≥ 3 days where both metrics exist for any signal to surface.
    </p>

    <Card title="Presets">
      <div class="presets">
        <button v-for="p in PRESETS" :key="p.label" class="preset" @click="applyPreset(p)">
          {{ p.label }}
        </button>
      </div>
    </Card>

    <Card title="Configure">
      <div class="cfg">
        <label>
          <span>X (independent)</span>
          <select v-model="x">
            <option v-for="m in METRICS" :key="m.key" :value="m.key">{{ m.label }}</option>
          </select>
        </label>
        <label>
          <span>Y (dependent)</span>
          <select v-model="y">
            <option v-for="m in METRICS" :key="m.key" :value="m.key">{{ m.label }}</option>
          </select>
        </label>
        <label>
          <span>Lag (days)</span>
          <input type="number" v-model.number="lag" min="-7" max="7"/>
        </label>
        <label>
          <span>Window (days)</span>
          <input type="number" v-model.number="days" min="14" max="365" step="7"/>
        </label>
      </div>
    </Card>

    <div v-if="error" class="err">{{ error }}</div>

    <Card v-if="result"
          :title="`${result.x_metric} → ${result.y_metric}  (lag ${result.lag_days}d)`"
          :subtitle="`n=${result.n}  ·  r=${rLabel}`">
      <div class="chart">
        <VChart v-if="scatterOption" :option="scatterOption" autoresize/>
        <div v-else class="empty">Not enough overlapping data points to plot. Try widening the window or picking different metrics.</div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 1.2rem; }

.presets { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.preset {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.4rem 0.7rem; cursor: pointer; font-size: 0.8rem; font-family: inherit;
}
.preset:hover { border-color: var(--accent); color: var(--accent); }

.cfg { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.8rem; }
.cfg label { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.8rem; color: var(--muted); }
.cfg input, .cfg select {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.4rem 0.6rem; font-size: 0.95rem; font-family: inherit;
}

.chart { flex: 1; min-height: 320px; display: flex; }
.chart > * { flex: 1; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; align-self: center; margin: auto; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
