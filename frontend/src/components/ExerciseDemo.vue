<script setup lang="ts">
// ANIM-1: pseudo-animate an exercise by slowly crossfading its two catalog
// frames (0.jpg start position, 1.jpg end/contracted position). The front
// frame stays in normal flow and sizes the box at its natural aspect; the back
// frame is absolutely overlaid and its opacity loops. Falls back to a single
// static frame when there's no side image (Noun-Project icons) or the user
// prefers reduced motion.
defineProps<{ front: string | null; side?: string | null; alt?: string }>();
</script>

<template>
  <span class="exercise-demo">
    <img :src="front || ''" :alt="alt || ''" class="ex-front" />
    <img v-if="side" :src="side" alt="" aria-hidden="true" class="ex-back" />
  </span>
</template>

<style scoped>
.exercise-demo { position: relative; display: block; width: 100%; line-height: 0; }
/* Front frame is in flow → it sizes the wrapper at the photo's natural aspect. */
.ex-front { display: block; width: 100%; height: auto; }
/* Back frame overlays the front's exact box (same image dims → cover == fit). */
.ex-back {
  position: absolute; inset: 0; width: 100%; height: 100%;
  object-fit: cover; opacity: 0;
  /* 5s loop = ~2.5s dwell on each position with gentle eased transitions. */
  animation: exdemo-fade 5s ease-in-out infinite;
}
@keyframes exdemo-fade {
  0%, 8% { opacity: 0; }
  42%, 58% { opacity: 1; }
  92%, 100% { opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .ex-back { animation: none; opacity: 0; }
}
</style>
