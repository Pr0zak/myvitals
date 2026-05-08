<script setup lang="ts">
/**
 * Horizontal scroll of annotation chips. Caller passes the last N
 * annotation rows mapped to a chip-friendly shape; this component is
 * purely presentational.
 */
import { computed } from "vue";
import {
  Plus, Coffee, Wine, Utensils, Smile, Pill, FileText, Activity,
} from "lucide-vue-next";

type Chip = {
  id: number;
  kind: string;
  label: string;
  whenLabel: string;
};

const props = defineProps<{ chips: Chip[] }>();
const emit = defineEmits<{ (e: "log"): void }>();

function iconFor(kind: string) {
  if (kind === "caffeine") return Coffee;
  if (kind === "alcohol") return Wine;
  if (kind === "food") return Utensils;
  if (kind === "mood") return Smile;
  if (kind === "meds") return Pill;
  if (kind === "note") return FileText;
  return Activity;
}

const visible = computed(() => props.chips.slice(0, 12));
</script>

<template>
  <div class="card log-card">
    <div class="head-row">
      <span class="card-title">Log</span>
      <button class="btn btn-tiny" @click="emit('log')">
        <Plus :size="11"/> Log
      </button>
    </div>
    <div class="no-scrollbar chips">
      <div v-for="c in visible" :key="c.id" class="chip">
        <component :is="iconFor(c.kind)" :size="12" class="chip-icon"/>
        <span class="chip-label">{{ c.label }}</span>
        <span class="mono dim chip-when">{{ c.whenLabel }}</span>
      </div>
      <div v-if="visible.length === 0" class="dim empty">
        No annotations yet — tap "Log" to add one.
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-card { padding: 14px 16px; }
.head-row {
  display: flex; align-items: center; gap: 12px;
  justify-content: space-between; margin-bottom: 12px;
}
.head-row .card-title { margin: 0; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
.chip { flex: 0 0 auto; height: 30px; padding: 0 12px; }
.chip-icon { color: var(--on-surface-2); }
.chip-label { color: var(--on-surface); font-size: 12px; }
.chip-when { font-size: 11px; margin-left: 4px; }
.dim { color: var(--on-surface-2); }
.empty { font-size: 12px; padding: 4px 0; }
.btn-tiny { text-transform: none; letter-spacing: 0; }
</style>
