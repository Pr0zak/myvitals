<script setup lang="ts">
/** UI-4 — cold-load placeholder shaped like the hero + first chart, swept
 *  in the metric accent. Phone twin: `DetailSkeleton`. */
defineProps<{ accent: string; label?: string }>();
</script>

<template>
  <div class="dskel" aria-busy="true" :style="{ '--a': accent }">
    <div class="hero">
      <span v-if="label">{{ label }}</span>
      <div class="sk num"></div><div class="sk chip"></div><div class="sk chart"></div>
    </div>
    <div class="row"><div class="sk stat"></div><div class="sk stat"></div><div class="sk stat"></div></div>
    <div class="sk card"></div>
  </div>
</template>

<style scoped>
.dskel { display: flex; flex-direction: column; gap: 10px; }
.row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.sk { border-radius: 18px;
  background: linear-gradient(90deg, rgba(31,41,55,.5), color-mix(in srgb, var(--a) 22%, transparent), rgba(31,41,55,.5));
  background-size: 300% 100%; animation: sweep 1.4s linear infinite; }
.hero { padding: 16px; border-radius: 22px; background: #1e2230;
  border: 1px solid color-mix(in srgb, var(--a) 25%, transparent); display: flex; flex-direction: column; gap: 10px; }
.hero span { font-size: 12px; color: color-mix(in srgb, var(--a) 75%, transparent); }
.num { width: 170px; height: 48px; border-radius: 10px; }
.chip { width: 140px; height: 22px; border-radius: 999px; }
.chart { height: 150px; border-radius: 12px; }
.stat { height: 62px; }
.card { height: 190px; margin-top: 12px; }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
