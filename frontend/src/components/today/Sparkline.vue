<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts/core";

const props = withDefaults(defineProps<{
  data: number[];
  color?: string;
  mean?: number | null;
  height?: number;
  areaOpacity?: number;
  smooth?: boolean;
  strokeWidth?: number;
  dashedMean?: boolean;
  padTop?: number;
  mode?: "line" | "bar";
  showSymbol?: boolean;
  symbolSize?: number;
}>(), {
  color: "#22C55E", mean: null, height: 40, areaOpacity: 0.18,
  smooth: true, strokeWidth: 1.6, dashedMean: true, padTop: 4,
  mode: "line", showSymbol: false, symbolSize: 3,
});

function hexA(hex: string, a: number) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

const root = ref<HTMLDivElement | null>(null);
let inst: echarts.ECharts | null = null;
let ro: ResizeObserver | null = null;

function render() {
  if (!root.value) return;
  if (!inst) inst = echarts.init(root.value, null, { renderer: "canvas" });
  const isBar = props.mode === "bar";
  const opt: any = {
    grid: { top: props.padTop, right: 0, bottom: 1, left: 0, containLabel: false },
    xAxis: {
      type: "category", show: false,
      boundaryGap: isBar,
      data: props.data.map((_, i) => i),
    },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: isBar ? "shadow" : "line",
                     lineStyle: { color: "#94A3B8", opacity: 0.4 } },
      backgroundColor: "rgba(27, 35, 49, 0.95)",
      borderColor: "#243042", borderWidth: 1,
      textStyle: { color: "#E5E7EB", fontSize: 11 },
      formatter: (p: any) => {
        const v = Array.isArray(p) ? p[0] : p;
        const num = typeof v.value === "number" ? v.value.toFixed(0) : v.value;
        return `<span style="font-family: var(--mono, monospace)">${num}</span>`;
      },
      padding: [4, 8],
    },
    series: [{
      type: isBar ? "bar" : "line",
      data: props.data,
      smooth: props.smooth && !isBar,
      showSymbol: props.showSymbol,
      symbolSize: props.symbolSize,
      barWidth: isBar ? "62%" : undefined,
      itemStyle: isBar
        ? { color: props.color, borderRadius: [2, 2, 0, 0] }
        : { color: props.color },
      lineStyle: isBar ? undefined : { color: props.color, width: props.strokeWidth },
      areaStyle: !isBar && props.areaOpacity > 0 ? {
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: hexA(props.color, props.areaOpacity) },
            { offset: 1, color: hexA(props.color, 0) },
          ],
        },
      } : null,
      markLine: (props.mean != null && props.dashedMean) ? {
        symbol: "none", silent: true,
        lineStyle: { type: "dashed", color: "#94A3B8", width: 1, opacity: 0.5 },
        label: { show: false },
        data: [{ yAxis: props.mean }],
      } : undefined,
      animation: false,
    }],
  };
  inst.setOption(opt, true);
}

onMounted(() => {
  render();
  if (root.value) {
    ro = new ResizeObserver(() => inst?.resize());
    ro.observe(root.value);
  }
});

onBeforeUnmount(() => {
  ro?.disconnect();
  inst?.dispose();
  inst = null;
});

watch(() => [
  props.data, props.color, props.mean, props.areaOpacity,
  props.smooth, props.strokeWidth, props.dashedMean, props.padTop,
  props.mode, props.showSymbol, props.symbolSize,
], () => render(), { deep: true });
</script>

<template>
  <div ref="root" :style="{ width: '100%', height: `${height}px` }" />
</template>
