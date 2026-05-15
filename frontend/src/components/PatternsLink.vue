<script setup lang="ts">
/**
 * ANALYTICS-3 helper: a small "Explore patterns ↗" link that
 * drops into any vital detail view header. Routes to
 * /analytics?tab=patterns&metric=<key>, where Insights.vue reads
 * the metric query param on mount and seeds its y selector.
 */
import { RouterLink } from "vue-router";

defineProps<{
  /** Insights metric key, e.g. "hrv_avg", "steps_total", "weight_kg" */
  metric: string;
  /** Short label of the metric, shown in the link copy */
  label?: string;
}>();
</script>

<template>
  <RouterLink
    :to="`/analytics?tab=patterns&metric=${metric}`"
    class="patterns-link"
    :title="`Explore ${label ?? metric} patterns (correlations, day-of-week, lag)`"
  >
    Explore patterns ↗
  </RouterLink>
</template>

<style scoped>
.patterns-link {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  font-size: 0.75rem; font-weight: 500;
  color: #38bdf8; text-decoration: none;
  background: rgba(56, 189, 248, 0.10);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 999px;
  transition: background-color 120ms ease;
}
.patterns-link:hover {
  background: rgba(56, 189, 248, 0.20);
}
</style>
