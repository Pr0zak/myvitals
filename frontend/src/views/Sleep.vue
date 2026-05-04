<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { SleepNight } from "@/api/types";
import { chartTheme } from "@/theme";

const STAGE_COLORS: Record<string, string> = {
  awake: "#f97316",
  rem: "#a78bfa",
  light: "#60a5fa",
  deep: "#1e40af",
  out_of_bed: "#94a3b8",
  unknown: "#64748b",
};

// Order top-to-bottom in the hypnogram (REM is shallowest after awake)
const STAGE_ORDER = ["awake", "rem", "light", "deep"];

const nights = ref<SleepNight[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const range = ref<7 | 30 | 90>(30);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date();
    since.setDate(since.getDate() - range.value);
    nights.value = await api.sleepRange(since);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const lastNight = computed(() => nights.value[nights.value.length - 1] ?? null);

function fmtDur(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// === Hypnogram of the most recent night ===
// Need raw stage timeline; we have totals per stage, not the timeline.
// The /query/sleep/range groups by stage type — to draw a hypnogram we need
// the per-stage start/end. For now, render a stacked horizontal bar showing
// the proportion of each stage. (A real hypnogram requires raw stage rows;
// future v0.3.x can add /query/sleep/stages for that.)
const lastNightStackedOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const n = lastNight.value;
  if (!n) return null;
  const stages = STAGE_ORDER.filter((s) => n.stages.find((x) => x.stage === s));
  return {
    grid: { left: 60, right: 12, top: 8, bottom: 24 },
    xAxis: { type: "value", name: "minutes", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: t.axisLabel },
    yAxis: { type: "category", data: ["Stages"], axisLabel: { color: "transparent" } },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (params: any[]) => params.map((p) => `${p.seriesName}: ${p.value} min`).join("<br/>") },
    legend: { textStyle: t.axisLabel, top: 4 },
    series: stages.map((stage) => {
      const item = n.stages.find((x) => x.stage === stage)!;
      return {
        name: stage,
        type: "bar",
        stack: "stages",
        data: [Math.round(item.duration_s / 60)],
        itemStyle: { color: STAGE_COLORS[stage] ?? "#64748b" },
      };
    }),
  };
});

// === Last N nights stacked bar ===
const stackedNightsOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const dates = nights.value.map((n) => n.date);
  const allStages = Array.from(new Set(nights.value.flatMap((n) => n.stages.map((s) => s.stage))));
  const orderedStages = [...STAGE_ORDER, ...allStages.filter((s) => !STAGE_ORDER.includes(s))];

  const series = orderedStages.filter((s) => allStages.includes(s)).map((stage) => ({
    name: stage,
    type: "bar",
    stack: "sleep",
    data: nights.value.map((n) => {
      const s = n.stages.find((x) => x.stage === stage);
      return s ? +(s.duration_s / 60).toFixed(0) : 0;
    }),
    itemStyle: { color: STAGE_COLORS[stage] ?? "#64748b" },
  }));

  return {
    grid: { left: 50, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: dates, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "minutes", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: t.axisLabel },
    tooltip: { trigger: "axis", ...t.tooltip },
    series,
    dataZoom: [{ type: "inside" }],
  };
});

// === Bedtime / wake time consistency scatter ===
const consistencyOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  // Map each night to (date, fractional hour of bedtime) and (date, fractional hour of wake).
  // Bedtime can wrap past midnight; encode hours since 18:00 to keep them positive.
  const bedData: [string, number][] = [];
  const wakeData: [string, number][] = [];
  for (const n of nights.value) {
    const start = new Date(n.start);
    const end = new Date(n.end);
    const bedH = ((start.getHours() + start.getMinutes() / 60) - 18 + 24) % 24;
    const wakeH = (end.getHours() + end.getMinutes() / 60);
    bedData.push([n.date, +bedH.toFixed(2)]);
    wakeData.push([n.date, +wakeH.toFixed(2)]);
  }
  return {
    grid: { left: 50, right: 50, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: nights.value.map((n) => n.date), axisLabel: t.axisLabel },
    yAxis: [
      { type: "value", name: "bedtime (h after 6pm)", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: { color: t.palette.violet, fontSize: 9 } },
      { type: "value", name: "wake hour", axisLabel: t.axisLabel, splitLine: { show: false }, position: "right", nameTextStyle: { color: t.palette.steps, fontSize: 9 } },
    ],
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      { name: "Bedtime", type: "scatter", yAxisIndex: 0, symbolSize: 8, data: bedData, itemStyle: { color: t.palette.violet } },
      { name: "Wake", type: "scatter", yAxisIndex: 1, symbolSize: 8, data: wakeData, itemStyle: { color: t.palette.steps } },
    ],
  };
});

const stats = computed(() => {
  if (nights.value.length === 0) return null;
  const totals = nights.value.map((n) => n.total_s);
  const avg = totals.reduce((a, b) => a + b, 0) / totals.length;
  const min = Math.min(...totals);
  const max = Math.max(...totals);
  return { avg, min, max, count: nights.value.length };
});
</script>

<template>
  <div class="sleep">
    <header class="head">
      <h1>Sleep</h1>
      <div class="picker">
        <button v-for="r in [7, 30, 90]" :key="r"
                :class="{ active: range === r }" @click="range = r as 7 | 30 | 90; load()">
          {{ r }} days
        </button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="nights.length === 0" class="empty">
      No sleep sessions in this range. Make sure your watch is logging sleep + Fitbit is sharing it with Health Connect.
    </div>

    <div v-if="lastNight" class="last-banner">
      <span class="dot" :style="{ background: 'var(--violet)' }"></span>
      Last sleep logged: <strong>{{ new Date(lastNight.end).toLocaleString() }}</strong>
      <span class="rel">({{ relativeTime(lastNight.end) }})</span>
    </div>

    <div v-if="!loading && nights.length > 0" class="grid">
      <Card v-if="lastNight" title="Last night"
            :subtitle="`${fmtTime(new Date(lastNight.start))} → ${fmtTime(new Date(lastNight.end))}  ·  ${fmtDur(lastNight.total_s)}`">
        <div class="chart small"><VChart v-if="lastNightStackedOption" :option="lastNightStackedOption" autoresize/></div>
        <div class="legend">
          <span v-for="s in lastNight.stages" :key="s.stage" class="lg-item">
            <span class="dot" :style="{ background: STAGE_COLORS[s.stage] ?? '#64748b' }"></span>
            {{ s.stage }} {{ Math.round(s.duration_s / 60) }} min
          </span>
        </div>
      </Card>

      <Card v-if="stats" title="Range stats"
            :subtitle="`${stats.count} nights`">
        <div class="kv">
          <div><dt>Avg</dt><dd>{{ fmtDur(stats.avg) }}</dd></div>
          <div><dt>Min</dt><dd>{{ fmtDur(stats.min) }}</dd></div>
          <div><dt>Max</dt><dd>{{ fmtDur(stats.max) }}</dd></div>
        </div>
      </Card>

      <Card title="Per-night stage breakdown">
        <div class="chart"><VChart :option="stackedNightsOption" autoresize/></div>
      </Card>

      <Card title="Bedtime / wake-time consistency">
        <div class="chart"><VChart :option="consistencyOption" autoresize/></div>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
h1 { margin: 0; }
.picker { display: flex; gap: 0.4rem; }
.picker button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.85rem; }
.picker button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }

.grid { display: grid; gap: 1rem; margin-top: 1rem; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); }
.chart { width: 100%; height: 280px; }
.chart.small { height: 100px; }
.chart > * { width: 100%; height: 100%; }

.legend { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.lg-item { display: inline-flex; align-items: center; gap: 0.3rem; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }

.kv { display: flex; gap: 2rem; margin-top: 0.5rem; }
.kv > div { display: flex; flex-direction: column; }
.kv dt { color: var(--muted-2); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.kv dd { margin: 0.2rem 0 0; color: var(--text); font-weight: 500; font-size: 1.4rem; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }

.last-banner {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.6rem 0.9rem; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; margin: 0.5rem 0 1rem; font-size: 0.9rem; color: var(--muted);
}
.last-banner strong { color: var(--text); }
.last-banner .rel { color: var(--muted-2); font-size: 0.85rem; margin-left: auto; }
</style>
