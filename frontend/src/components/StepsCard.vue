<script setup lang="ts">
import { computed } from "vue";
import Card from "./Card.vue";

const props = defineProps<{ total: number; goal?: number }>();

const goal = computed(() => props.goal ?? 8000);
const pct = computed(() => Math.min(100, (props.total / goal.value) * 100));
</script>

<template>
  <Card title="Steps">
    <div class="big">{{ total.toLocaleString() }}</div>
    <div class="bar"><div class="fill" :style="{ width: pct + '%' }" /></div>
    <div class="goal">{{ Math.round(pct) }}% of {{ goal.toLocaleString() }} goal</div>
  </Card>
</template>

<style scoped>
.big { font-size: 2.5rem; font-weight: 300; color: #38bdf8; line-height: 1; margin: 0.5rem 0; }
.bar { height: 8px; background: #0f172a; border-radius: 4px; overflow: hidden; margin-top: 0.5rem; }
.fill { height: 100%; background: linear-gradient(90deg, #38bdf8, #22d3ee); transition: width 0.3s; }
.goal { font-size: 0.8rem; color: #64748b; margin-top: 0.4rem; }
</style>
