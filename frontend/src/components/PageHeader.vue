<script setup lang="ts">
/**
 * Standard detail-view page header: an `<h1>` title on the left and an actions
 * area (range tabs, links) on the right, wrapping on narrow screens. Replaces
 * the per-view `<header class="hdr|head|page-head">` + `.page-head h1` CSS that
 * every detail view re-declared with slightly different numbers.
 *
 * Usage:
 *   <PageHeader title="Heart rate">
 *     <RangeTabs v-model="range" :options="RANGES" />
 *   </PageHeader>
 * Use the `title` slot instead of the prop when the heading needs markup.
 */
defineProps<{ title?: string }>();
</script>

<template>
  <header class="page-header">
    <h1><slot name="title">{{ title }}</slot></h1>
    <div v-if="$slots.default" class="page-header-actions">
      <slot />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem;
}
.page-header h1 { margin: 0; font-size: 1.4rem; }
.page-header-actions {
  display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;
}
</style>
