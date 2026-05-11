<script setup lang="ts">
/**
 * Weekly muscle-group volume audit (#WP-4).
 * Shows direct working sets per primary muscle over the last 7 days
 * against research-backed MEV / MAV ranges. Surfaces under-trained
 * and over-trained groups so the user can see imbalance at a glance.
 */
import { onMounted, ref } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";

type Status = "untrained" | "under" | "in_range" | "over";
type Row = {
  muscle: string;
  sets: number;
  mev: number;
  mav: number;
  status: Status;
};

const rows = ref<Row[]>([]);
const windowDays = ref(7);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const r = await api.strengthMuscleVolume(7);
    windowDays.value = r.window_days;
    rows.value = Object.entries(r.muscles)
      .map(([m, v]) => ({ muscle: m, ...v }))
      // Show muscles with any recent volume first (most-stimulated
      // top); zero-volume groups at the bottom in alphabetical order.
      .sort((a, b) => {
        if (a.sets === 0 && b.sets === 0) return a.muscle.localeCompare(b.muscle);
        if (a.sets === 0) return 1;
        if (b.sets === 0) return -1;
        return b.sets - a.sets;
      });
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function barPct(row: Row): number {
  // Fill bar against MAV (100% = at MAV). Over-MAV clamps to 100%
  // but the row gets coloured red so the user sees the overage.
  if (row.mav === 0) return 0;
  return Math.min(100, (row.sets / row.mav) * 100);
}
function mevPct(row: Row): number {
  // The MEV tick position on the bar (0-100% of MAV).
  return (row.mev / row.mav) * 100;
}
function statusClass(s: Status): string {
  return `st-${s}`;
}
function muscleLabel(m: string): string {
  return m.replace(/_/g, " ");
}
</script>

<template>
  <Card title="Weekly muscle volume" :subtitle="`Last ${windowDays} days vs research-backed MEV / MAV ranges`">
    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="muted small">{{ error }}</p>
    <p v-else-if="rows.length === 0" class="muted small">No data.</p>
    <ul v-else class="mv-list">
      <li v-for="r in rows" :key="r.muscle"
          :class="['mv-row', statusClass(r.status)]">
        <div class="mv-head">
          <span class="mv-name">{{ muscleLabel(r.muscle) }}</span>
          <span class="mv-stat">{{ r.sets }} / {{ r.mev }}–{{ r.mav }}</span>
        </div>
        <div class="mv-bar">
          <div class="mv-fill" :style="{ width: barPct(r) + '%' }"></div>
          <div class="mv-mev-tick" :style="{ left: mevPct(r) + '%' }"></div>
        </div>
        <div class="mv-tag">{{ r.status.replace("_", " ") }}</div>
      </li>
    </ul>
  </Card>
</template>

<style scoped>
.mv-list { list-style: none; padding: 0; margin: 0; display: flex;
           flex-direction: column; gap: 0.4rem; }
.mv-row { padding: 0.5rem 0.6rem; border-radius: 8px;
          background: var(--bg-1); border: 1px solid var(--line); }
.mv-head { display: flex; align-items: center; justify-content: space-between;
           font-size: 0.85rem; margin-bottom: 0.25rem; }
.mv-name { text-transform: capitalize; font-weight: 600; color: var(--text); }
.mv-stat { font-family: 'Geist Mono', ui-monospace, monospace;
           font-size: 0.78rem; color: var(--muted); }
.mv-bar { position: relative; height: 6px; background: var(--bg-2);
          border-radius: 3px; overflow: visible; }
.mv-fill { position: absolute; left: 0; top: 0; height: 100%;
           border-radius: 3px; background: currentColor;
           transition: width 0.2s; }
.mv-mev-tick { position: absolute; top: -2px; width: 1px; height: 10px;
               background: var(--muted); opacity: 0.45; }
.mv-tag { margin-top: 0.25rem; font-size: 0.7rem; text-transform: uppercase;
          letter-spacing: 0.06em; opacity: 0.75; }
.st-untrained { color: #64748b; }
.st-under     { color: #facc15; border-left: 3px solid #facc15; }
.st-in_range  { color: #22c55e; }
.st-over      { color: #ef4444; border-left: 3px solid #ef4444; }
.muted { color: var(--muted); }
.muted.small { font-size: 0.85rem; }
</style>
