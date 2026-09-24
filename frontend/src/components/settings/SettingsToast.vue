<script setup lang="ts">
/** The visible half of `useToast`. Always mounted so screen readers
 *  announce the change through the live region. */
defineProps<{ message: string | null }>();
</script>

<template>
  <div class="stoast-wrap" role="status" aria-live="polite">
    <div v-if="message" class="stoast">{{ message }}</div>
  </div>
</template>

<style scoped>
.stoast-wrap { position: fixed; left: 0; right: 0; bottom: calc(20px + var(--neon-bar-h, 0px));
  display: flex; justify-content: center; pointer-events: none; z-index: 60; }
.stoast { background: #1e2230; color: #5dff3b; border: 1px solid rgba(93, 255, 59, .4); border-radius: 999px;
  padding: 10px 18px; font-size: 14px; font-weight: 700; box-shadow: 0 8px 24px rgba(0, 0, 0, .5); }
</style>
