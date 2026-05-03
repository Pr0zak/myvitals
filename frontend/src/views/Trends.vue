<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";

type Range = "7d" | "30d" | "90d";
const RANGES: { key: Range; label: string; days: number }[] = [
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
  { key: "90d", label: "90 days", days: 90 },
];

const range = ref<Range>("30d");
const data = ref<TodaySummary[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const since = new Date();
    since.setDate(since.getDate() - days);
    data.value = await api.summaryRange(since);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(range, load);

const baseChart = (color: string, name: string, accessor: (d: TodaySummary) => number | null) =>
  computed(() => ({
    grid: { left: 36, right: 12, top: 8, bottom: 24 },
    xAxis: {
      type: "time",
      axisLabel: { color: "#64748b", fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#64748b", fontSize: 10 },
      splitLine: { lineStyle: { color: "#334155", type: "dashed" } },
      scale: true,
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#1e293b",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0" },
    },
    series: [
      {
        type: "line",
        name,
        showSymbol: true,
        smooth: true,
        connectNulls: true,
        symbolSize: 4,
        lineStyle: { color, width: 1.8 },
        itemStyle: { color },
        areaStyle: { color: `${color}22` },
        data: data.value
          .map((d) => [d.date, accessor(d)])
          .filter((p) => p[1] !== null && p[1] !== undefined),
      },
    ],
  }));

const rhrOption = baseChart("#ef4444", "Resting HR (bpm)", (d) => d.resting_hr);
const hrvOption = baseChart("#22c55e", "HRV (ms)", (d) => d.hrv_avg);
const recoveryOption = baseChart("#a78bfa", "Recovery", (d) => d.recovery_score);
const stepsOption = computed(() => ({
  grid: { left: 36, right: 12, top: 8, bottom: 24 },
  xAxis: {
    type: "category",
    data: data.value.map((d) => d.date),
    axisLabel: { color: "#64748b", fontSize: 10 },
  },
  yAxis: {
    type: "value",
    axisLabel: { color: "#64748b", fontSize: 10 },
    splitLine: { lineStyle: { color: "#334155", type: "dashed" } },
  },
  tooltip: {
    trigger: "axis",
    backgroundColor: "#1e293b",
    borderColor: "#334155",
    textStyle: { color: "#e2e8f0" },
  },
  series: [
    {
      type: "bar",
      name: "Steps",
      itemStyle: { color: "#38bdf8" },
      data: data.value.map((d) => d.steps_total ?? 0),
    },
  ],
}));

const hasData = computed(() => data.value.length > 0);
</script>

<template>
  <div class="trends">
    <header class="head">
      <h1>Trends</h1>
      <div class="picker">
        <button
          v-for="r in RANGES" :key="r.key"
          :class="{ active: range === r.key }"
          @click="range = r.key"
        >{{ r.label }}</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="loading">Loading…</div>
    <div v-else-if="!hasData" class="empty">No daily summaries yet for this range — the analytics job runs at 03:00 local each night.</div>

    <div v-else class="grid">
      <Card title="Resting HR">
        <div class="chart"><VChart :option="rhrOption" autoresize /></div>
      </Card>
      <Card title="HRV (RMSSD)">
        <div class="chart"><VChart :option="hrvOption" autoresize /></div>
      </Card>
      <Card title="Recovery score">
        <div class="chart"><VChart :option="recoveryOption" autoresize /></div>
      </Card>
      <Card title="Steps per day">
        <div class="chart"><VChart :option="stepsOption" autoresize /></div>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; }
h1 { margin: 0; }
.picker { display: flex; gap: 0.4rem; }
.picker button { background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 6px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.85rem; }
.picker button.active { background: #38bdf8; color: #0f172a; border-color: #38bdf8; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1rem; margin-top: 1rem; }
.chart { flex: 1; min-height: 200px; display: flex; }
.chart > * { flex: 1; }
.empty, .loading { color: #64748b; padding: 2rem 0; text-align: center; }
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin: 0.6rem 0; }
</style>
