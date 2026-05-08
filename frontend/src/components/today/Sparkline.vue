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
}>(), {
  color: "#22C55E", mean: null, height: 40, areaOpacity: 0.18,
  smooth: true, strokeWidth: 1.6, dashedMean: true, padTop: 4,
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
  const opt: any = {
    grid: { top: props.padTop, right: 0, bottom: 1, left: 0, containLabel: false },
    xAxis: {
      type: "category", show: false, boundaryGap: false,
      data: props.data.map((_, i) => i),
    },
    yAxis: { type: "value", show: false, scale: true },
    series: [{
      type: "line",
      data: props.data,
      smooth: props.smooth,
      showSymbol: false,
      lineStyle: { color: props.color, width: props.strokeWidth },
      areaStyle: props.areaOpacity > 0 ? {
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
], () => render(), { deep: true });
</script>

<template>
  <div ref="root" :style="{ width: '100%', height: `${height}px` }" />
</template>
