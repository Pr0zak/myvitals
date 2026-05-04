<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";

const data = ref<TodaySummary[]>([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  // 9 weeks = 63 days
  const since = new Date();
  since.setDate(since.getDate() - 63);
  data.value = await api.summaryRange(since);
  loading.value = false;
}
onMounted(load);

function metricVal(d: TodaySummary, m: string): number | null {
  if (m === "sleep_hours") return d.sleep_duration_s ? d.sleep_duration_s / 3600 : null;
  return (d as any)[m];
}

function average(rows: TodaySummary[], metric: string): number | null {
  const vals = rows.map((r) => metricVal(r, metric)).filter((v): v is number => v !== null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

const buckets = computed(() => {
  if (data.value.length === 0) return null;
  const today = new Date();
  const day7 = new Date(today.getTime() - 7 * 86400 * 1000);
  const day14 = new Date(today.getTime() - 14 * 86400 * 1000);
  const day28 = new Date(today.getTime() - 28 * 86400 * 1000);
  const inRange = (s: Date, e: Date) =>
    data.value.filter((d) => {
      const x = new Date(d.date);
      return x >= s && x < e;
    });
  return {
    thisWeek: inRange(day7, today),
    lastWeek: inRange(day14, day7),
    fourWeekAvg: inRange(day28, today),
  };
});

const METRICS = [
  { key: "resting_hr", label: "Resting HR", suffix: "bpm" },
  { key: "hrv_avg", label: "HRV", suffix: "ms" },
  { key: "recovery_score", label: "Recovery", suffix: "" },
  { key: "sleep_hours", label: "Sleep", suffix: "h" },
  { key: "sleep_score", label: "Sleep score", suffix: "" },
  { key: "steps_total", label: "Steps", suffix: "" },
];

const rows = computed(() => {
  if (!buckets.value) return [];
  return METRICS.map((m) => ({
    metric: m,
    thisWeek: average(buckets.value!.thisWeek, m.key),
    lastWeek: average(buckets.value!.lastWeek, m.key),
    fourWeekAvg: average(buckets.value!.fourWeekAvg, m.key),
  }));
});

function fmt(v: number | null, suffix: string): string {
  if (v === null) return "—";
  if (suffix === "") return v.toFixed(1);
  if (suffix === "h") return v.toFixed(1) + " h";
  return Math.round(v).toString() + " " + suffix;
}

function delta(a: number | null, b: number | null): { pct: number; class: "up" | "down" | "same" } | null {
  if (a === null || b === null || b === 0) return null;
  const pct = ((a - b) / Math.abs(b)) * 100;
  return { pct, class: Math.abs(pct) < 1 ? "same" : pct > 0 ? "up" : "down" };
}

const trendOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (data.value.length === 0) return null;
  return {
    grid: { left: 50, right: 50, top: 40, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: data.value.map((d) => d.date), axisLabel: t.axisLabel },
    yAxis: [
      { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, name: "RHR/HRV", nameTextStyle: t.axisLabel },
      { type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, name: "Score", nameTextStyle: t.axisLabel, position: "right" },
    ],
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      { name: "RHR", type: "line", smooth: true, yAxisIndex: 0, lineStyle: { color: t.palette.hr, width: 2 }, itemStyle: { color: t.palette.hr },
        data: data.value.map((d) => [d.date, d.resting_hr]), connectNulls: true },
      { name: "HRV", type: "line", smooth: true, yAxisIndex: 0, lineStyle: { color: t.palette.hrv, width: 2 }, itemStyle: { color: t.palette.hrv },
        data: data.value.map((d) => [d.date, d.hrv_avg]), connectNulls: true },
      { name: "Recovery", type: "line", smooth: true, yAxisIndex: 1, lineStyle: { color: t.palette.recovery, width: 2 }, itemStyle: { color: t.palette.recovery },
        data: data.value.map((d) => [d.date, d.recovery_score]), connectNulls: true },
    ],
  };
});
</script>

<template>
  <div>
    <h1>Compare</h1>
    <p class="hint">This week (last 7 days) vs the prior week vs the rolling 4-week average.</p>

    <Card title="Week-over-week deltas">
      <div v-if="loading" class="empty">Loading…</div>
      <table v-else class="cmp">
        <thead>
          <tr>
            <th>Metric</th>
            <th>This week</th>
            <th>Last week</th>
            <th>Δ vs last</th>
            <th>4-wk avg</th>
            <th>Δ vs avg</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.metric.key">
            <td class="m">{{ r.metric.label }}</td>
            <td>{{ fmt(r.thisWeek, r.metric.suffix) }}</td>
            <td>{{ fmt(r.lastWeek, r.metric.suffix) }}</td>
            <td :class="delta(r.thisWeek, r.lastWeek)?.class ?? ''">
              <template v-if="delta(r.thisWeek, r.lastWeek)">
                {{ delta(r.thisWeek, r.lastWeek)!.pct > 0 ? "+" : "" }}{{ delta(r.thisWeek, r.lastWeek)!.pct.toFixed(1) }}%
              </template>
              <template v-else>—</template>
            </td>
            <td>{{ fmt(r.fourWeekAvg, r.metric.suffix) }}</td>
            <td :class="delta(r.thisWeek, r.fourWeekAvg)?.class ?? ''">
              <template v-if="delta(r.thisWeek, r.fourWeekAvg)">
                {{ delta(r.thisWeek, r.fourWeekAvg)!.pct > 0 ? "+" : "" }}{{ delta(r.thisWeek, r.fourWeekAvg)!.pct.toFixed(1) }}%
              </template>
              <template v-else>—</template>
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <Card title="Past 9 weeks at a glance">
      <div class="chart"><VChart v-if="trendOption" :option="trendOption" autoresize/></div>
    </Card>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 1.2rem; }

.cmp { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.cmp th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
.cmp td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--surface-2); color: var(--text); }
.cmp .m { color: var(--muted); }
.cmp .up { color: var(--good); font-weight: 500; }
.cmp .down { color: var(--bad); font-weight: 500; }
.cmp .same { color: var(--muted-2); }

.chart { width: 100%; height: 320px; }
.chart > * { width: 100%; height: 100%; }
.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
</style>
