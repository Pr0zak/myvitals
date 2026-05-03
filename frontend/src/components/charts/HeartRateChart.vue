<script setup lang="ts">
import { computed } from "vue";
import VChart from "vue-echarts";
import Card from "../Card.vue";
import type { HeartRateSeries } from "@/api/types";

const props = defineProps<{ series: HeartRateSeries | null }>();

const subtitle = computed(() => {
  if (!props.series || props.series.points.length === 0) return "";
  const a = props.series.avg, mn = props.series.min_bpm, mx = props.series.max_bpm;
  return `avg ${Math.round(a ?? 0)} · min ${Math.round(mn ?? 0)} · max ${Math.round(mx ?? 0)}`;
});

const option = computed(() => ({
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
    formatter: (params: any) => {
      const p = params[0];
      const d = new Date(p.value[0]);
      return `${d.toLocaleTimeString()}<br/><b>${Math.round(p.value[1])} bpm</b>`;
    },
  },
  series: [
    {
      type: "line",
      showSymbol: false,
      smooth: true,
      lineStyle: { color: "#ef4444", width: 1.5 },
      areaStyle: { color: "rgba(239, 68, 68, 0.15)" },
      data: (props.series?.points ?? []).map((p) => [p.time, p.value]),
    },
  ],
}));
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
.empty { color: #64748b; align-self: center; margin: auto; }
</style>
