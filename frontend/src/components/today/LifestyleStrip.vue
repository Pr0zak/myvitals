<script setup lang="ts">
/**
 * Sober + Fasting compact tiles on Today (TODAY-1). Each renders the
 * current state with a single click-through to the relevant detail
 * page. No-op visually when neither has data — the tile collapses so
 * users without either feature don't see a placeholder.
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { RotateCcw, Hourglass } from "lucide-vue-next";

const props = defineProps<{
  sober: { days: number | null; hours: number | null } | null;
  fasting: {
    isActive: boolean;
    startedAt: string;
    targetHours: number | null;
    currentStage: string;
  } | null;
}>();

const elapsedH = computed<number | null>(() => {
  if (!props.fasting?.isActive || !props.fasting.startedAt) return null;
  const start = new Date(props.fasting.startedAt).getTime();
  return (Date.now() - start) / 3_600_000;
});

const fastPct = computed<number | null>(() => {
  if (elapsedH.value == null || !props.fasting?.targetHours) return null;
  return Math.min(100, (elapsedH.value / props.fasting.targetHours) * 100);
});

const anyVisible = computed(() =>
  props.sober?.days != null || props.fasting?.isActive,
);
</script>

<template>
  <div v-if="anyVisible" class="strip">
    <RouterLink v-if="sober?.days != null" to="/sober" class="tile sober">
      <div class="tile-head">
        <RotateCcw :size="13"/>
        <span class="tile-title">Sober</span>
      </div>
      <div class="tile-value mono">
        {{ sober.days }}
        <span class="tile-unit">{{ sober.days === 1 ? 'day' : 'days' }}</span>
        <span v-if="sober.hours != null" class="dim tile-extra">
          · {{ sober.hours }}h
        </span>
      </div>
    </RouterLink>

    <RouterLink v-if="fasting?.isActive" to="/fasting" class="tile fasting">
      <div class="tile-head">
        <Hourglass :size="13"/>
        <span class="tile-title">Fasting</span>
      </div>
      <div class="tile-value mono">
        {{ elapsedH?.toFixed(1) }}<span class="tile-unit">h</span>
        <span v-if="fasting.targetHours" class="dim tile-extra">
          / {{ fasting.targetHours }}h
        </span>
      </div>
      <div v-if="fastPct != null" class="bar">
        <div class="bar-fill" :style="{ width: fastPct + '%' }"/>
      </div>
      <div class="dim stage">{{ fasting.currentStage.replace(/_/g, ' ') }}</div>
    </RouterLink>
  </div>
</template>

<style scoped>
.strip {
  display: grid;
  /* auto-fit so a lone tile (e.g. sober only, no active fast) fills the
     row instead of leaving a phantom half-width gap, and so the strip
     gracefully collapses when its parent is the narrow column of the
     Today bottom-row grid. */
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.tile {
  background: var(--surface);
  border: 1px solid var(--outline);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
  text-decoration: none;
  color: var(--on-surface);
  transition: border-color 120ms ease, background-color 120ms ease;
}
.tile:hover { border-color: var(--outline-strong); background: var(--surface-low); }
.tile-head {
  display: flex; align-items: center; gap: 6px;
  color: var(--on-surface-2);
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  font-weight: 600;
}
.tile-title { font-size: 11px; }
.tile-value { font-size: 22px; font-weight: 600; }
.tile-unit { font-size: 12px; color: var(--on-surface-2); margin-left: 4px; }
.tile-extra { font-size: 11px; margin-left: 6px; font-weight: 400; }
.bar {
  height: 4px; background: rgba(255, 255, 255, 0.06);
  border-radius: 2px; overflow: hidden;
  margin-top: 4px;
}
.bar-fill {
  height: 100%; background: #38bdf8;
  transition: width 320ms ease;
}
.stage { font-size: 10px; margin-top: 4px; text-transform: capitalize; }
.dim { color: var(--on-surface-2); }
</style>
