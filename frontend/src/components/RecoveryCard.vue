<script setup lang="ts">
import { computed } from "vue";
import Card from "./Card.vue";

const props = defineProps<{
  score: number | null;
  rhr: number | null;
  hrv: number | null;
}>();

const color = computed(() => {
  if (props.score === null) return "#64748b";
  if (props.score >= 70) return "#22c55e";
  if (props.score >= 40) return "#eab308";
  return "#ef4444";
});

const label = computed(() => {
  if (props.score === null) return "—";
  return Math.round(props.score).toString();
});
</script>

<template>
  <Card title="Recovery">
    <div class="big" :style="{ color }">{{ label }}</div>
    <dl class="stats">
      <div><dt>Resting HR</dt><dd>{{ rhr !== null ? Math.round(rhr) + " bpm" : "—" }}</dd></div>
      <div><dt>HRV</dt><dd>{{ hrv !== null ? Math.round(hrv) + " ms" : "—" }}</dd></div>
    </dl>
  </Card>
</template>

<style scoped>
.big { font-size: 3.5rem; font-weight: 300; line-height: 1; margin: 0.5rem 0; }
.stats { display: flex; gap: 1.5rem; margin: 0; padding: 0; font-size: 0.85rem; }
.stats > div { display: flex; flex-direction: column; }
dt { color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
dd { margin: 0.2rem 0 0; color: #e2e8f0; font-weight: 500; }
</style>
