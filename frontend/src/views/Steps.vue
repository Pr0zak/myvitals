<script setup lang="ts">
/**
 * Steps detail view (VITALS-1). Three panels:
 *   1. 24h live trace (the StepsSeries already powering the LiveVitals chip)
 *   2. Last-N-day bars + goal markLine + 7-day moving average
 *   3. Day-of-week histogram
 *
 * Goal value pulls from `profile.extra.steps_goal` (synced bidirectionally
 * with AiGoal kind=steps by GOALS-1).
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { StepsSeries, TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import { timeAxisFormatter } from "@/components/charts/chartHelpers";

type RangeKey = "7d" | "30d" | "90d" | "1y";
const RANGES: Array<{ key: RangeKey; label: string; days: number }> = [
  { key: "7d",  label: "7d",  days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "1y",  label: "1y",  days: 365 },
];
const range = ref<RangeKey>("30d");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);

const live = ref<StepsSeries | null>(null);
const dailyRows = ref<TodaySummary[]>([]);
const stepsGoal = ref<number>(10_000);
const loading = ref(true);
const error = ref<string | null>(null);

async function loadLive() {
  try {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    live.value = await api.steps({ since });
  } catch { /* trace is non-critical */ }
}

async function loadHistory() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date();
    since.setDate(since.getDate() - cur.value.days + 1);
    const [rows, profile] = await Promise.all([
      api.summaryRange(since),
      api.getProfile().catch(() => null),
    ]);
    dailyRows.value = rows;
    const extra = profile?.extra as { steps_goal?: number } | undefined;
    if (extra?.steps_goal != null) stepsGoal.value = Math.round(extra.steps_goal);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(() => { loadLive(); loadHistory(); });
watch(range, loadHistory);

// ── 24h trace option ──
const traceOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!live.value || live.value.points.length === 0) return null;
  return {
    grid: { left: 40, right: 12, top: 12, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "line", smooth: true, showSymbol: false,
      lineStyle: { color: t.palette.steps, width: 2 },
      areaStyle: { color: `${t.palette.steps}22` },
      data: live.value.points.map((p) => [p.time, p.value]),
    }],
  };
});

// ── Daily-bar option ──
const dailyOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const data = dailyRows.value
    .filter((r) => r.steps_total != null)
    .map((r) => [r.date, r.steps_total]);
  if (data.length === 0) return null;
  // 7-day moving average as a smoothed overlay.
  const series7 = dailyRows.value.map((r, i) => {
    const window = dailyRows.value
      .slice(Math.max(0, i - 6), i + 1)
      .map((x) => x.steps_total).filter((v): v is number => v != null);
    if (window.length === 0) return [r.date, null] as [string, number | null];
    const avg = window.reduce((a, b) => a + b, 0) / window.length;
    return [r.date, Math.round(avg)] as [string, number];
  });
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: t.splitLine },
    yAxis: { type: "value", scale: false, axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      {
        type: "bar", name: "Steps",
        itemStyle: { color: t.palette.steps },
        data,
        markLine: stepsGoal.value > 0 ? {
          symbol: ["none", "none"], silent: true,
          lineStyle: { color: t.palette.recovery, type: "dashed" as const, opacity: 0.7 },
          label: { show: true, formatter: `goal ${stepsGoal.value.toLocaleString()}`, color: t.axisLabel.color, fontSize: 9 },
          data: [{ yAxis: stepsGoal.value }],
        } : undefined,
      },
      {
        type: "line", name: "7d avg", smooth: true, showSymbol: false,
        lineStyle: { color: t.palette.violet, width: 2 },
        data: series7,
      },
    ],
  };
});

// ── Day-of-week histogram ──
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const weekdayOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const buckets: Array<{ sum: number; count: number }> = Array.from({ length: 7 }, () => ({ sum: 0, count: 0 }));
  for (const r of dailyRows.value) {
    if (r.steps_total == null) continue;
    const d = new Date(r.date + "T00:00:00");
    const idx = d.getDay();
    buckets[idx].sum += r.steps_total;
    buckets[idx].count += 1;
  }
  const data = buckets.map((b) => b.count > 0 ? Math.round(b.sum / b.count) : 0);
  if (data.every((v) => v === 0)) return null;
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "category", data: DOW, axisLabel: t.axisLabel },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (p: any) => {
        const x = Array.isArray(p) ? p[0] : p;
        return `${x.name}: ${x.value.toLocaleString()}`;
      },
    },
    series: [{
      type: "bar", name: "Avg steps",
      itemStyle: { color: t.palette.steps },
      data,
    }],
  };
});

// ── Headline stats ──
const stats = computed(() => {
  if (dailyRows.value.length === 0) return null;
  const vals = dailyRows.value
    .map((r) => r.steps_total)
    .filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  return {
    todayCount: dailyRows.value[dailyRows.value.length - 1]?.steps_total ?? 0,
    avg: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length),
    max: Math.max(...vals),
    goalDays: vals.filter((v) => v >= stepsGoal.value).length,
    totalDays: vals.length,
  };
});
</script>

<template>
  <div class="steps-view">
    <header class="hdr">
      <h1>Steps</h1>
      <div class="seg-toggle">
        <button v-for="r in RANGES" :key="r.key"
                :class="{ active: range === r.key }"
                @click="range = r.key">{{ r.label }}</button>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="stats">
      <div class="stats-row">
        <div class="stat">
          <span class="lbl">Today</span>
          <span class="val">{{ stats.todayCount.toLocaleString() }}</span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} avg</span>
          <span class="val">{{ stats.avg.toLocaleString() }}</span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} max</span>
          <span class="val">{{ stats.max.toLocaleString() }}</span>
        </div>
        <div class="stat">
          <span class="lbl">Goal hit</span>
          <span class="val">{{ stats.goalDays }} / {{ stats.totalDays }}</span>
        </div>
      </div>
    </Card>

    <Card v-if="traceOption" title="Last 24h">
      <div class="chart"><VChart :option="traceOption" autoresize/></div>
    </Card>

    <Card v-if="dailyOption" :title="`Daily — ${cur.label}`">
      <div class="chart"><VChart :option="dailyOption" autoresize/></div>
    </Card>

    <Card v-if="weekdayOption" title="Weekday pattern">
      <div class="chart"><VChart :option="weekdayOption" autoresize/></div>
    </Card>

    <p v-if="loading" class="dim">Loading…</p>
  </div>
</template>

<style scoped>
.steps-view { max-width: 1080px; margin: 0 auto; padding: 1rem 1.25rem 2rem; }
.hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
h1 { margin: 0; }
.err { color: #ef4444; }
.dim { color: var(--muted); font-size: 0.85rem; }

.seg-toggle {
  display: inline-flex; border: 1px solid var(--outline); border-radius: 999px;
  overflow: hidden;
}
.seg-toggle button {
  appearance: none; border: 0; background: transparent;
  padding: 6px 14px; font-size: 12px; color: var(--on-surface-2);
  cursor: pointer;
}
.seg-toggle button.active {
  background: var(--surface); color: var(--on-surface);
}

.stats-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
}
@media (max-width: 720px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
.stat { display: flex; flex-direction: column; }
.stat .lbl {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--on-surface-2);
}
.stat .val { font-size: 1.25rem; font-weight: 600; color: var(--on-surface); }

.chart { height: 220px; }
</style>
