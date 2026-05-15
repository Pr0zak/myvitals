<script setup lang="ts">
/**
 * HRV detail view (VITALS-1). Three panels mirroring Steps.vue's
 * structure but tuned to HRV: a 24h trace, a daily-bar chart with
 * 7-day rolling mean, and a weekday-pattern average.
 *
 * HRV is overnight-dominated (most samples are 2-5am during deep
 * sleep) so the 24h trace is sparse outside that window — expected
 * behaviour, not a sync issue.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { HrvSeries, TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import { timeAxisFormatter } from "@/components/charts/chartHelpers";
import PatternsLink from "@/components/PatternsLink.vue";

type RangeKey = "7d" | "30d" | "90d" | "1y";
const RANGES: Array<{ key: RangeKey; label: string; days: number }> = [
  { key: "7d",  label: "7d",  days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "1y",  label: "1y",  days: 365 },
];
const range = ref<RangeKey>("30d");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);

const live = ref<HrvSeries | null>(null);
const dailyRows = ref<TodaySummary[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function loadLive() {
  try {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    live.value = await api.hrv({ since });
  } catch { /* trace is non-critical */ }
}

async function loadHistory() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date();
    since.setDate(since.getDate() - cur.value.days + 1);
    dailyRows.value = await api.summaryRange(since);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(() => { loadLive(); loadHistory(); });
watch(range, loadHistory);

// ── 24h trace ──
const traceOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!live.value || live.value.points.length === 0) return null;
  return {
    grid: { left: 40, right: 12, top: 12, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, name: "ms", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "scatter", name: "HRV (ms)", symbolSize: 6,
      itemStyle: { color: t.palette.hrv, opacity: 0.85 },
      data: live.value.points.map((p) => [p.time, p.value]),
    }],
  };
});

// ── Daily HRV with 7d rolling mean ──
const dailyOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const data = dailyRows.value
    .filter((r) => r.hrv_avg != null)
    .map((r) => [r.date, r.hrv_avg]);
  if (data.length === 0) return null;
  const series7 = dailyRows.value.map((r, i) => {
    const window = dailyRows.value
      .slice(Math.max(0, i - 6), i + 1)
      .map((x) => x.hrv_avg).filter((v): v is number => v != null);
    if (window.length === 0) return [r.date, null] as [string, number | null];
    const avg = window.reduce((a, b) => a + b, 0) / window.length;
    return [r.date, +avg.toFixed(1)] as [string, number];
  });
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: t.splitLine },
    yAxis: { type: "value", scale: true, name: "ms", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      {
        type: "bar", name: "Nightly avg",
        itemStyle: { color: `${t.palette.hrv}aa` },
        data,
      },
      {
        type: "line", name: "7d avg", smooth: true, showSymbol: false,
        lineStyle: { color: t.palette.violet, width: 2 },
        data: series7,
      },
    ],
  };
});

// ── Weekday avg ──
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const weekdayOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const buckets: Array<{ sum: number; count: number }> = Array.from({ length: 7 }, () => ({ sum: 0, count: 0 }));
  for (const r of dailyRows.value) {
    if (r.hrv_avg == null) continue;
    const idx = new Date(r.date + "T00:00:00").getDay();
    buckets[idx].sum += r.hrv_avg;
    buckets[idx].count += 1;
  }
  const data = buckets.map((b) => b.count > 0 ? +(b.sum / b.count).toFixed(1) : 0);
  if (data.every((v) => v === 0)) return null;
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "category", data: DOW, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "ms", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (p: any) => {
        const x = Array.isArray(p) ? p[0] : p;
        return `${x.name}: ${x.value} ms`;
      },
    },
    series: [{
      type: "bar", name: "HRV avg",
      itemStyle: { color: t.palette.hrv },
      data,
    }],
  };
});

const stats = computed(() => {
  const vals = dailyRows.value.map((r) => r.hrv_avg).filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  return {
    latest: vals[vals.length - 1],
    avg: +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1),
    min: Math.min(...vals),
    max: Math.max(...vals),
  };
});
</script>

<template>
  <div class="hrv-view">
    <header class="hdr">
      <h1>HRV</h1>
      <div class="hdr-actions">
        <PatternsLink metric="hrv_avg" label="HRV"/>
        <div class="seg-toggle">
          <button v-for="r in RANGES" :key="r.key"
                  :class="{ active: range === r.key }"
                  @click="range = r.key">{{ r.label }}</button>
        </div>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="stats">
      <div class="stats-row">
        <div class="stat">
          <span class="lbl">Latest</span>
          <span class="val">{{ stats.latest.toFixed(0) }}<span class="unit">ms</span></span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} avg</span>
          <span class="val">{{ stats.avg }}<span class="unit">ms</span></span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} min</span>
          <span class="val">{{ stats.min.toFixed(0) }}<span class="unit">ms</span></span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} max</span>
          <span class="val">{{ stats.max.toFixed(0) }}<span class="unit">ms</span></span>
        </div>
      </div>
    </Card>

    <Card v-if="traceOption" title="Last 24h">
      <div class="chart"><VChart :option="traceOption" autoresize/></div>
      <p class="dim small">
        HRV is overnight-dominated — sparse outside the deep-sleep window
        is expected, not a sync issue.
      </p>
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
.hrv-view { max-width: 1080px; margin: 0 auto; padding: 1rem 1.25rem 2rem; }
.hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; gap: 12px; }
.hdr-actions { display: flex; align-items: center; gap: 10px; }
h1 { margin: 0; }
.err { color: #ef4444; }
.dim { color: var(--muted); font-size: 0.85rem; }
.small { font-size: 0.78rem; margin-top: 0.5rem; }

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

.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
@media (max-width: 720px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
.stat { display: flex; flex-direction: column; }
.stat .lbl {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--on-surface-2);
}
.stat .val { font-size: 1.25rem; font-weight: 600; color: var(--on-surface); }
.stat .unit { font-size: 0.75rem; color: var(--on-surface-2); margin-left: 4px; }

.chart { height: 220px; }
</style>
