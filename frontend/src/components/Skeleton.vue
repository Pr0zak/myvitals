<script setup lang="ts">
/**
 * Generic skeleton placeholder. A muted block with a sweeping
 * gradient that hints at the final layout while data loads.
 *
 * Replaces ad-hoc "Loading…" text. Pass width / height as CSS
 * dimensions, or pass `lines` to render a stack of lines (for text
 * blocks).
 */
withDefaults(defineProps<{
  /** CSS width — e.g. "120px", "100%", "8rem" */
  width?: string;
  /** CSS height — single bar height when `lines` is omitted */
  height?: string;
  /** Number of stacked lines (for text-shaped placeholders) */
  lines?: number;
  /** Round the corners more or less aggressively */
  radius?: string;
}>(), {
  width: "100%",
  height: "1rem",
  lines: 1,
  radius: "6px",
});
</script>

<template>
  <div v-if="lines === 1" class="skeleton"
       :style="{ width, height, borderRadius: radius }"/>
  <div v-else class="skeleton-stack">
    <div v-for="i in lines" :key="i" class="skeleton"
         :style="{ width: i === lines ? '60%' : width, height, borderRadius: radius }"/>
  </div>
</template>

<style scoped>
.skeleton {
  background:
    linear-gradient(
      90deg,
      var(--bg-2) 0%,
      var(--surface-2, rgba(255, 255, 255, 0.05)) 50%,
      var(--bg-2) 100%
    );
  background-size: 200% 100%;
  animation: skeleton-sweep 1.4s ease-in-out infinite;
}
.skeleton-stack {
  display: flex; flex-direction: column; gap: 0.4rem;
}
@keyframes skeleton-sweep {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
