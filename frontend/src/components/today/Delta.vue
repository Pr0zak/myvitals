<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  value: number | null;
  invert?: boolean;     // if true, negative is "good" (resting HR)
  /**
   * OG2-A5: an explicit verdict, for metrics where the sign alone cannot
   * settle it. `invert` answers "is down good" and bodyweight has no such
   * answer — it depends on the user's goal, which is why
   * `analytics/compare.py` classes it better="context". Callers that can
   * work the direction out pass it; `"neutral"` renders an uncoloured
   * figure rather than guessing.
   */
  tone?: "positive" | "caution" | "neutral" | null;
  suffix?: string;
  size?: number;
}>(), { invert: false, tone: null, suffix: "", size: 11 });

const arrow = computed(() => {
  if (props.value == null || props.value === 0) return "·";
  return props.value > 0 ? "▲" : "▼";
});
const cls = computed(() => {
  if (props.value == null || props.value === 0) return "delta-flat";
  // An explicit tone wins: it was worked out from something the sign does
  // not carry, so it must not be second-guessed here.
  if (props.tone) {
    return props.tone === "positive" ? "delta-up"
      : props.tone === "caution" ? "delta-down" : "delta-flat";
  }
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
