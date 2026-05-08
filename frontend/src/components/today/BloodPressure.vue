<script setup lang="ts">
/**
 * BP card with sys/dia + 30-day dual-line. "Log BP" opens the existing
 * BP form modal in the parent — the slide-over from the design is left
 * for a future polish pass; we emit a "log" event so the parent can
 * show its existing inline form (or convert it to a slide-over later).
 */
import { Plus } from "lucide-vue-next";
import DualLine from "./DualLine.vue";

defineProps<{
  latest: { systolic: number; diastolic: number; time: string } | null;
  sys: number[];  // 30-day series
  dia: number[];
  asOfLabel?: string | null;
}>();

const emit = defineEmits<{ (e: "log"): void }>();

function bpCategory(s: number, d: number): { label: string; tone: "good" | "warn" | "bad" } {
  if (s >= 140 || d >= 90) return { label: "stage 2", tone: "bad" };
  if (s >= 130 || d >= 80) return { label: "elevated", tone: "warn" };
  return { label: "normal", tone: "good" };
}
</script>

<template>
  <div class="card">
    <div class="card-title">
      <span>Blood pressure</span>
      <button class="btn btn-tiny" @click="emit('log')">
        <Plus :size="11"/> Log BP
      </button>
    </div>
    <div class="hl-row" v-if="latest">
      <span class="mono num-xl">{{ latest.systolic }}</span>
      <span class="dim mono num-l slash">/</span>
      <span class="mono num-xl"
            :style="{ color: latest.diastolic >= 80 ? 'var(--warn)' : 'inherit' }">
        {{ latest.diastolic }}
      </span>
      <span class="unit">mmHg</span>
      <span :class="['chip', 'tone', `tone-${bpCategory(latest.systolic, latest.diastolic).tone}`]">
        <span :class="['dot', `dot-${bpCategory(latest.systolic, latest.diastolic).tone}`]"/>
        {{ bpCategory(latest.systolic, latest.diastolic).label }}
      </span>
    </div>
    <div v-else class="dim sub">No readings logged yet.</div>
    <div class="dim sub" v-if="asOfLabel">logged · {{ asOfLabel }}</div>
    <div class="chart" v-if="sys.length && dia.length">
      <DualLine :sys="sys" :dia="dia" :height="64" :pad-top="6"/>
    </div>
    <div class="legend">
      <span class="leg-item">
        <span class="leg-dash" style="background: #EF4444"/> systolic
      </span>
      <span class="leg-item">
        <span class="leg-dash" style="background: #EAB308"/> diastolic
      </span>
    </div>
  </div>
</template>

<style scoped>
.hl-row { display: flex; align-items: baseline; gap: 6px; margin-bottom: 6px; }
.slash { font-size: 22px; }
.sub { font-size: 11px; margin-bottom: 12px; }
.chart { height: 64px; margin-top: 16px; }
.chip { height: 22px; font-size: 11px; padding: 0 8px; margin-left: auto; }
.chip.tone.tone-good { color: var(--good); border-color: rgba(34,197,94,0.3); }
.chip.tone.tone-warn { color: var(--warn); border-color: rgba(234,179,8,0.3); }
.chip.tone.tone-bad  { color: var(--bad);  border-color: rgba(239,68,68,0.3); }
.legend {
  display: flex; gap: 14px; font-size: 10px; margin-top: 6px;
  color: var(--on-surface-2);
}
.leg-item { display: inline-flex; align-items: center; gap: 4px; }
.leg-dash { width: 8px; height: 2px; border-radius: 1px; }
.dim { color: var(--on-surface-2); }
.btn-tiny { text-transform: none; letter-spacing: 0; }
</style>
