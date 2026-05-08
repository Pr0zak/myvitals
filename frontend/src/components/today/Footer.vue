<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  version: string;
  lastSyncIso: string | null;
}>();

const syncLabel = computed(() => {
  if (!props.lastSyncIso) return "never synced";
  const ageMs = Date.now() - new Date(props.lastSyncIso).getTime();
  const min = Math.round(ageMs / 60000);
  if (min < 1) return "synced just now";
  if (min < 60) return `synced ${min} min ago`;
  const h = Math.floor(min / 60);
  return `synced ${h}h ago`;
});
const syncTone = computed(() => {
  if (!props.lastSyncIso) return "neutral";
  const ageMs = Date.now() - new Date(props.lastSyncIso).getTime();
  return ageMs < 30 * 60_000 ? "good" : "warn";
});
</script>

<template>
  <div class="foot">
    <div class="mono">myvitals · v{{ version }}</div>
    <div class="sync">
      <span :class="['dot', `dot-${syncTone}`]"/>
      <span class="mono">{{ syncLabel }}</span>
    </div>
    <RouterLink to="/logs" class="diag">Diagnostics</RouterLink>
  </div>
</template>

<style scoped>
.foot {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; color: var(--dim); padding: 8px 4px;
}
.sync { display: flex; align-items: center; gap: 6px; }
.diag {
  color: var(--on-surface-2); text-decoration: none;
  border-bottom: 1px dashed var(--outline-strong);
}
</style>
