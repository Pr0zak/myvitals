<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts/core";

const props = withDefaults(defineProps<{
  sys: number[];
  dia: number[];
  height?: number;
  padTop?: number;
}>(), { height: 64, padTop: 8 });

const root = ref<HTMLDivElement | null>(null);
let inst: echarts.ECharts | null = null;
let ro: ResizeObserver | null = null;

function render() {
  if (!root.value) return;
  if (!inst) inst = echarts.init(root.value, null, { renderer: "canvas" });
  const opt: any = {
    grid: { top: props.padTop, right: 0, bottom: 1, left: 0 },
    xAxis: {
      type: "category", show: false, boundaryGap: false,
      data: props.sys.map((_, i) => i),
    },
    yAxis: { type: "value", show: false, scale: true },
    series: [
      {
        type: "line", data: props.sys, smooth: true, showSymbol: false,
        lineStyle: { color: "#EF4444", width: 1.6 }, animation: false,
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(239,68,68,0.18)" },
              { offset: 1, color: "rgba(239,68,68,0)" },
            ],
          },
        },
      },
      {
        type: "line", data: props.dia, smooth: true, showSymbol: false,
        lineStyle: { color: "#EAB308", width: 1.6 }, animation: false,
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(234,179,8,0.12)" },
              { offset: 1, color: "rgba(234,179,8,0)" },
            ],
          },
        },
      },
    ],
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

watch(() => [props.sys, props.dia, props.height, props.padTop],
      () => render(), { deep: true });
</script>

<template>
  <div ref="root" :style="{ width: '100%', height: `${height}px` }" />
</template>
