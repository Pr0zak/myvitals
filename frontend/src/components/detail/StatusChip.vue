<script setup lang="ts">
/**
 * UI-4 — the server's verdict for a metric, in the server's words. Phone
 * twin: `DetailStatusChip`. good/positive = lime, watch/caution = amber,
 * anything else muted. Never rose: an ordinary metric is not a crisis.
 */
import { computed } from "vue";
const props = defineProps<{ status?: string | null; text?: string | null }>();
const color = computed(() => {
  switch (props.status) {
    case "good": case "positive": return "#5dff3b";
    case "watch": case "caution": return "#ffb52e";
    default: return "#9b9bb0";
  }
});
</script>

<template>
  <span v-if="text" class="dchip" :style="{ '--c': color }"><i></i>{{ text }}</span>
</template>

<style scoped>
.dchip { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; color: var(--c);
  padding: 4px 10px; border-radius: 999px; background: color-mix(in srgb, var(--c) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--c) 35%, transparent); white-space: nowrap; max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; align-self: flex-start; }
.dchip i { width: 6px; height: 6px; border-radius: 50%; background: var(--c); flex: 0 0 auto; }
</style>
