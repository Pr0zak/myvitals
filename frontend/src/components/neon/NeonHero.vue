<script setup lang="ts">
/** The focal block a screen leads with — phone `NeonHeroCard`.
 *  It sits on the page ground with no surface, border or glow, matching the
 *  Today brief: the hero is the one unboxed thing on the screen. `accent`
 *  is kept for API compatibility and exposed as --acc for slot content. */
defineProps<{ accent: string }>();
</script>

<template>
  <section class="neon-hero" :style="{ '--acc': accent }"><slot /></section>
</template>

<style scoped>
.neon-hero {
  padding: 4px 0 0;
  margin-bottom: 20px;
}
</style>
