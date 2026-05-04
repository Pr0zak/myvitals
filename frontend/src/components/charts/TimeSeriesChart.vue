<script setup lang="ts">
import VChart from "vue-echarts";
import { computed } from "vue";
import { baseTimeOption } from "./chartHelpers";
import { chartTheme } from "@/theme";

const props = defineProps<{
  /** Series objects merged onto the base option. ECharts series shape. */
  series: Record<string, unknown>[];
  /** Override grid bottom (e.g. taller for the dataZoom slider). */
  height?: number;
  /** Disable the slider zoom (keeps inside zoom). */
  noSlider?: boolean;
  /** Custom yAxis override (for multi-axis charts). */
  yAxis?: object | object[];
  /** Force a min/max y. */
  yMin?: number;
  yMax?: number;
}>();

const option = computed(() => {
  // touch chartTheme so this re-renders when theme flips
  void chartTheme.value;
  const opt = baseTimeOption() as Record<string, any>;
  if (props.noSlider) {
    opt.dataZoom = [opt.dataZoom[0]];
  }
  if (props.yAxis) {
    opt.yAxis = props.yAxis;
  } else if (props.yMin !== undefined || props.yMax !== undefined) {
    opt.yAxis = { ...opt.yAxis, min: props.yMin, max: props.yMax };
  }
  opt.series = props.series;
  return opt;
});
</script>

<template>
  <div class="ts-wrap" :style="{ height: (height ?? 220) + 'px' }">
    <VChart :option="option" autoresize />
  </div>
</template>

<style scoped>
.ts-wrap { width: 100%; }
.ts-wrap > * { width: 100%; height: 100%; }
</style>
