<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  value: number;
  max?: number;
  size?: number;
  color?: string;
  track?: string;
  thickness?: number;
  label?: string;
}>(), {
  max: 100, size: 140, color: "#22C55E", track: "#243042",
  thickness: 8, label: "Readiness",
});

const r = computed(() => (props.size - props.thickness) / 2);
const c = computed(() => 2 * Math.PI * r.value);
const pct = computed(() =>
  Math.max(0, Math.min(1, (props.value ?? 0) / props.max)),
);
const dash = computed(() => c.value * pct.value);
const gap = computed(() => c.value - dash.value);
const numSize = computed(() => Math.round(props.size * 0.32));
</script>

<template>
  <div class="gauge" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg :width="size" :height="size">
      <circle
        :cx="size / 2" :cy="size / 2" :r="r"
        :stroke="track" :stroke-width="thickness" fill="none" />
      <circle
        :cx="size / 2" :cy="size / 2" :r="r"
        :stroke="color" :stroke-width="thickness" fill="none"
        stroke-linecap="round"
        :stroke-dasharray="`${dash} ${gap}`"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"/>
    </svg>
    <div class="gauge-overlay">
      <span class="mono gauge-num"
            :style="{ fontSize: `${numSize}px` }">{{ Math.round(value ?? 0) }}</span>
      <span class="gauge-label">{{ label }}</span>
    </div>
  </div>
</template>

<style scoped>
.gauge { position: relative; flex: 0 0 auto; }
.gauge-overlay {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 4px;
}
.gauge-num { font-weight: 500; line-height: 1; letter-spacing: -0.5px; }
.gauge-label {
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--on-surface-2);
}
</style>
