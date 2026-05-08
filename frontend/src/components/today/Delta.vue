<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  value: number | null;
  invert?: boolean;     // if true, negative is "good" (resting HR, weight)
  suffix?: string;
  size?: number;
}>(), { invert: false, suffix: "", size: 11 });

const arrow = computed(() => {
  if (props.value == null || props.value === 0) return "·";
  return props.value > 0 ? "▲" : "▼";
});
const cls = computed(() => {
  if (props.value == null || props.value === 0) return "delta-flat";
  const positive = props.value > 0;
  const good = props.invert ? !positive : positive;
  return good ? "delta-up" : "delta-down";
});
</script>

<template>
  <span :class="['delta', cls]" :style="{ fontSize: `${size}px` }">
    <template v-if="value == null">—</template>
    <template v-else>
      <span :style="{ fontSize: `${size - 2}px` }">{{ arrow }}</span>
      {{ Math.abs(value) }}{{ suffix }}
    </template>
  </span>
</template>
