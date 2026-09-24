<script setup lang="ts">
/** UI-4 — a secondary (non-hero) chart card. Phone twin: `DetailCard`. */
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
defineProps<{ title: string; subtitle?: string | null }>();
</script>

<template>
  <NeonEyebrow>{{ title }}</NeonEyebrow>
  <section class="dcard">
    <p v-if="subtitle" class="dsub">{{ subtitle }}</p>
    <slot />
  </section>
</template>

<style scoped>
.dcard { background: #181b27; border: 1px solid #23263a; border-radius: 18px; padding: 14px; }
.dsub { margin: 0 0 8px; color: #9b9bb0; font-size: 12px; }
</style>
