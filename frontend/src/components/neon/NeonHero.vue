<script setup lang="ts">
/** The one focal card a screen leads with — phone `NeonHeroCard`. */
defineProps<{ accent: string }>();
</script>

<template>
  <section class="neon-hero" :style="{ '--acc': accent }"><slot /></section>
</template>

<style scoped>
.neon-hero {
  background: #1e2230;
  border: 1px solid color-mix(in srgb, var(--acc) 40%, transparent);
  border-radius: 22px;
  padding: 16px;
  margin-bottom: 14px;
  box-shadow: 0 0 32px color-mix(in srgb, var(--acc) 14%, transparent);
}
</style>
