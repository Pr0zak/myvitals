<script setup lang="ts">
import { computed } from "vue";
import VChart from "@/echarts";
import Card from "../Card.vue";
import type { HeartRateSeries } from "@/api/types";
import { fmtTime } from "@/format";
import { timeAxisFormatter } from "@/components/charts/chartHelpers";
import { chartTheme } from "@/theme";

const props = defineProps<{ series: HeartRateSeries | null }>();

const subtitle = computed(() => {
  if (!props.series || props.series.points.length === 0) return "";
  const a = props.series.avg, mn = props.series.min_bpm, mx = props.series.max_bpm;
  return `avg ${Math.round(a ?? 0)} · min ${Math.round(mn ?? 0)} · max ${Math.round(mx ?? 0)}`;
});

const option = computed(() => {
  // Route through the shared chartTheme so this chart follows light/dark like
  // the rest of the app. It used to hardcode dark hexes → illegible in light mode.
  const t = chartTheme.value;
  const hr = t.palette.hr;
  return {
    grid: { left: 36, right: 12, top: 8, bottom: 24 },
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
      scale: true,
    },
    tooltip: {
      trigger: "axis",
      ...t.tooltip,
      formatter: (params: any) => {
        const p = params[0];
        const d = new Date(p.value[0]);
        return `${fmtTime(d)}<br/><b>${Math.round(p.value[1])} bpm</b>`;
      },
    },
    series: [
      {
        type: "line",
        showSymbol: false,
        smooth: true,
        lineStyle: { color: hr, width: 1.5 },
        areaStyle: { color: t.palette.workout },
        data: (props.series?.points ?? []).map((p) => [p.time, p.value]),
      },
    ],
  };
});
</script>

<template>
  <Card title="Heart rate (24h)" :subtitle="subtitle">
    <div class="chart-wrap">
      <VChart v-if="series && series.points.length > 0" :option="option" autoresize />
      <div v-else class="empty">No HR data in the last 24h</div>
    </div>
  </Card>
</template>

<style scoped>
.chart-wrap { flex: 1; min-height: 160px; display: flex; }
.chart-wrap > * { flex: 1; }
.empty { color: var(--muted-2); align-self: center; margin: auto; }
</style>
