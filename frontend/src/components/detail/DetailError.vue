<script setup lang="ts">
/**
 * UI-4 — failure banner. With `cached` it sits ABOVE the last good render
 * ("Showing the last copy loaded"), never in place of it: a failed refresh
 * must not hide points that were already on screen.
 */
defineProps<{ error: string; cached?: boolean }>();
defineEmits<{ (e: "retry"): void }>();
</script>

<template>
  <button class="derr" type="button" @click="$emit('retry')">
    <b>{{ cached ? "Couldn't refresh" : "Couldn't load" }}</b>
    <span>{{ cached ? `Showing the last copy loaded. ${error}` : error }}</span>
    <em>Tap to retry</em>
  </button>
</template>

<style scoped>
.derr { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 93, 122, .10); border: 1px solid rgba(255, 93, 122, .28); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: inherit; font: inherit; }
.derr b { color: #ff5d7a; font-size: 13px; }
.derr span { color: #9b9bb0; font-size: 12px; }
.derr em { color: #28e6ff; font-size: 12px; font-style: normal; font-weight: 600; }
</style>
