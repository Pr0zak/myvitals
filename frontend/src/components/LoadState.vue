<script setup lang="ts">
/**
 * Shimmer loading placeholder that hints at the eventual layout, instead of a
 * bare "Loading…" line. Composes the existing Skeleton primitive (which already
 * carries the sweep animation + honours prefers-reduced-motion via the global
 * guard) into the two shapes the data views actually render:
 *
 *   variant="cards" (default) — a responsive row of stat-card blocks followed
 *     by one or more tall chart blocks. Matches the vitals detail / Trends view.
 *   variant="list" — a stack of row blocks. Matches Activities / Trails lists.
 *   variant="chart" — a single tall chart block.
 *
 * a11y: role="status" + aria-busy with a visually-hidden "Loading…" so screen
 * readers announce the load (the skeleton blocks themselves are decorative).
 *
 * Usage:  <LoadState v-if="loading" />            (cards)
 *         <LoadState v-if="loading" variant="list" :rows="6" />
 */
import Skeleton from "./Skeleton.vue";

withDefaults(defineProps<{
  variant?: "cards" | "list" | "chart";
  /** stat-card blocks in the cards variant */
  cards?: number;
  /** chart blocks in the cards variant */
  charts?: number;
  /** row blocks in the list variant */
  rows?: number;
}>(), { variant: "cards", cards: 4, charts: 2, rows: 5 });
</script>

<template>
  <div class="load-state" role="status" aria-busy="true">
    <template v-if="variant === 'cards'">
      <div class="ls-cards">
        <Skeleton v-for="i in cards" :key="`c${i}`" height="74px" radius="12px" />
      </div>
      <Skeleton v-for="i in charts" :key="`ch${i}`" height="240px" radius="12px" />
    </template>

    <template v-else-if="variant === 'list'">
      <Skeleton v-for="i in rows" :key="`r${i}`" height="58px" radius="10px" />
    </template>

    <Skeleton v-else height="260px" radius="12px" />

    <span class="sr-only">Loading…</span>
  </div>
</template>

<style scoped>
.load-state { display: flex; flex-direction: column; gap: 0.8rem; margin-top: 0.6rem; }
.ls-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.6rem;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
</style>
