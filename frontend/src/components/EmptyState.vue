<script setup lang="ts">
/**
 * Centred muted notice for the loading / empty / no-data branches that ~20
 * views each hand-rolled as `<div class="empty">…</div>` (identical 3-line CSS
 * copied everywhere). Pass the text via `message` or the default slot; `mini`
 * is the tighter variant some inline spots used (`.empty-mini`).
 *
 * Usage:
 *   <EmptyState v-if="loading" message="Loading…" />
 *   <EmptyState v-else-if="!hasData">No data yet for this range.</EmptyState>
 */
defineProps<{ message?: string; mini?: boolean }>();
</script>

<template>
  <div class="empty-state" :class="{ mini }">
    <slot>{{ message }}</slot>
  </div>
</template>

<style scoped>
.empty-state { color: var(--muted-2); padding: 2rem; text-align: center; }
.empty-state.mini { padding: 1.2rem 0; font-size: 0.85rem; }
</style>
