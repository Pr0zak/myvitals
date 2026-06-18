<script setup lang="ts">
/**
 * Skin temperature delta detail view (VITALS-1). The reading is a
 * delta from the user's overnight baseline — a sustained positive
 * delta of ~0.4°C or more is one of the earliest illness signals
 * (the anomaly scanner already alerts on `skin_temp_anomaly`).
 *
 * Layout matches Hrv.vue: 24h trace + daily-bar with rolling mean +
 * weekday-pattern average + 4-stat header. Y-axis is centred on
 * zero so positive (warmer) vs negative (cooler) reads at a glance.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import PageHeader from "@/components/PageHeader.vue";
import RangeTabs from "@/components/RangeTabs.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme, isNeon } from "@/theme";
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

const live = ref<Array<{ time: string; value: number }>>([]);
const dailyRows = ref<TodaySummary[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function loadLive() {
  try {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const r = await api.skinTemp({ since });
    live.value = r.points ?? [];
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

const traceOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  if (live.value.length === 0) return null;
  return {
    grid: { left: 48, right: 12, top: 12, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, name: "Δ °C", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (p: any) => {
        const x = Array.isArray(p) ? p[0] : p;
        return `${new Date(x.data[0]).toLocaleTimeString()}: ${x.data[1].toFixed(2)} °C`;
      },
    },
    series: [{
      type: "scatter", symbolSize: 6,
      itemStyle: { color: isNeon.value ? "#ffb52e" : t.palette.recovery, opacity: 0.85 },
      data: live.value.map((p) => [p.time, p.value]),
    }],
  };
});

const dailyOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const data = dailyRows.value
    .filter((r) => r.skin_temp_delta_avg != null)
    .map((r) => [r.date, r.skin_temp_delta_avg]);
  if (data.length === 0) return null;
  // 3-day rolling mean — short window because skin-temp deltas are
  // small and we want to see the noise reduction without erasing
  // genuine multi-day excursions (which are the illness signal).
  const series3 = dailyRows.value.map((r, i) => {
    const window = dailyRows.value
      .slice(Math.max(0, i - 2), i + 1)
      .map((x) => x.skin_temp_delta_avg).filter((v): v is number => v != null);
    if (window.length === 0) return [r.date, null] as [string, number | null];
    const avg = window.reduce((a, b) => a + b, 0) / window.length;
    return [r.date, +avg.toFixed(2)] as [string, number];
  });
  const warmColor = isNeon.value ? "#ff5d7a" : "#ef4444";
  const coolColor = isNeon.value ? "#28e6ff" : "#60a5fa";
  const neutralColor = isNeon.value ? "#9b9bb0" : "#94a3b8";
  const avgColor = isNeon.value ? "#ffb52e" : t.palette.violet;
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: t.splitLine },
    yAxis: { type: "value", scale: true, name: "Δ °C", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (params: any[]) => {
        const lines = params.map((p) => `${p.seriesName}: ${(p.data[1] ?? 0).toFixed(2)} °C`);
        return `${params[0].data[0]}<br/>${lines.join("<br/>")}`;
      },
    },
    series: [
      {
        type: "bar", name: "Δ vs baseline",
        itemStyle: { color: (params: any) => {
          const v = params.value[1] as number;
          if (v > 0.3) return warmColor;
          if (v < -0.3) return coolColor;
          return neutralColor;
        } },
        data,
        markLine: {
          symbol: ["none", "none"], silent: true,
          lineStyle: { color: warmColor, type: "dashed" as const, opacity: 0.6 },
          label: { show: true, formatter: "anomaly threshold", color: warmColor, fontSize: 9 },
          data: [{ yAxis: 0.4 }],
        },
      },
      {
        type: "line", name: "3d avg", smooth: true, showSymbol: false,
        lineStyle: { color: avgColor, width: 2 },
        data: series3,
      },
    ],
  };
});

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const weekdayOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const buckets: Array<{ sum: number; count: number }> = Array.from({ length: 7 }, () => ({ sum: 0, count: 0 }));
  for (const r of dailyRows.value) {
    if (r.skin_temp_delta_avg == null) continue;
    const idx = new Date(r.date + "T00:00:00").getDay();
    buckets[idx].sum += r.skin_temp_delta_avg;
    buckets[idx].count += 1;
  }
  const data = buckets.map((b) => b.count > 0 ? +(b.sum / b.count).toFixed(2) : 0);
  if (data.every((v) => v === 0)) return null;
  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    xAxis: { type: "category", data: DOW, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "Δ °C", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "bar", name: "Avg Δ",
      itemStyle: { color: isNeon.value ? "#ffb52e" : t.palette.recovery },
      data,
    }],
  };
});

const stats = computed(() => {
  const vals = dailyRows.value
    .map((r) => r.skin_temp_delta_avg).filter((v): v is number => v != null);
  if (vals.length === 0) return null;
  const recent7 = dailyRows.value.slice(-7)
    .map((r) => r.skin_temp_delta_avg).filter((v): v is number => v != null);
  return {
    latest: vals[vals.length - 1],
    avg: +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2),
    last7: recent7.length > 0
      ? +(recent7.reduce((a, b) => a + b, 0) / recent7.length).toFixed(2)
      : null,
    max: Math.max(...vals),
  };
});
</script>

<template>
  <div class="skin-view">
    <PageHeader title="Skin temperature Δ">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Skin-temperature time range">
        <template #before>
          <PatternsLink metric="skin_temp_delta_avg" label="skin temp"/>
        </template>
      </RangeTabs>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="stats">
      <div class="stats-row">
        <div class="stat">
          <span class="lbl">Latest</span>
          <span class="val">{{ stats.latest.toFixed(2) }}<span class="unit">°C</span></span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} avg</span>
          <span class="val">{{ stats.avg }}<span class="unit">°C</span></span>
        </div>
        <div v-if="stats.last7 != null" class="stat">
          <span class="lbl">7d avg</span>
          <span class="val">{{ stats.last7 }}<span class="unit">°C</span></span>
        </div>
        <div class="stat">
          <span class="lbl">{{ cur.label }} peak</span>
          <span class="val" :class="{ warn: stats.max >= 0.4 }">
            {{ stats.max.toFixed(2) }}<span class="unit">°C</span>
          </span>
        </div>
      </div>
    </Card>

    <Card v-if="traceOption" title="Last 24h">
      <div class="chart"><VChart :option="traceOption" autoresize/></div>
      <p class="dim small">
        Wrist-sensor delta from your overnight baseline. Sample density
        is overnight-heavy by design — daytime is usually empty.
      </p>
    </Card>

    <Card v-if="dailyOption" :title="`Daily — ${cur.label}`">
      <div class="chart"><VChart :option="dailyOption" autoresize/></div>
      <p class="dim small">
        Sustained ≥ +0.4 °C for 2+ days fires the anomaly scanner —
        watch for clusters above the dashed threshold line.
      </p>
    </Card>

    <Card v-if="weekdayOption" title="Weekday pattern">
      <div class="chart"><VChart :option="weekdayOption" autoresize/></div>
    </Card>

    <p v-if="loading" class="dim">Loading…</p>
  </div>
</template>

<style scoped>
.skin-view { max-width: 1080px; margin: 0 auto; padding: 1rem 1.25rem 2rem; }
.err { color: #ef4444; }
.dim { color: var(--muted); font-size: 0.85rem; }
.small { font-size: 0.78rem; margin-top: 0.5rem; }

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
.stat .val.warn { color: #ef4444; }
.stat .unit { font-size: 0.75rem; color: var(--on-surface-2); margin-left: 4px; }

.chart { height: 220px; }

/* ── Vitality Neon (data-theme="neon") — scoped, neon-only overrides ── */
html[data-theme="neon"] .skin-view {
  min-height: 100vh;
  margin: -1.25rem -1.5rem;
  padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: #ececf5;
  font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}
html[data-theme="neon"] .err { color: #ff5d7a; }
html[data-theme="neon"] .dim { color: #9b9bb0; }
html[data-theme="neon"] .stat .lbl { color: #9b9bb0; }
html[data-theme="neon"] .stat .unit { color: #9b9bb0; }
html[data-theme="neon"] .stat .val {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  letter-spacing: -0.5px;
  color: #ececf5;
}
/* "Latest" is the headline readout — subtle amber (warmth) glow */
html[data-theme="neon"] .stat:first-child .val {
  color: #ffb52e;
  text-shadow: 0 0 8px rgba(255, 181, 46, 0.45);
}
html[data-theme="neon"] .stat .val.warn {
  color: #ff5d7a;
  text-shadow: 0 0 8px rgba(255, 93, 122, 0.45);
}
</style>
