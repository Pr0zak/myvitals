<script setup lang="ts">
/**
 * Slim hero — single-row strip (~84px) per the v2 design bundle:
 * tiny readiness ring + status pip · 4 inline anchor cells with
 * vertical dividers · inline AI verdict on the right.
 *
 * Score cards (Recovery / Readiness / Sleep / TSB) from the original
 * variant are dropped here — the design intentionally trades them for
 * a much shorter top of viewport. Re-add them in a separate module
 * downstream if you want them back.
 *
 * Props are preserved from the previous Hero so Today.vue's data
 * wiring works unchanged. `scores` is accepted but ignored.
 */
import { computed } from "vue";
import { Sparkles, RefreshCw } from "lucide-vue-next";
import Delta from "./Delta.vue";

type Anchor = {
  label: string;
  value: string;
  unit?: string;
  sub?: string | null;
  delta: number | null;
  invert?: boolean;
  suffix?: string;
};
type Score = {
  label: string;
  value: number | null;
  tone: "good" | "warn" | "bad" | "neutral";
  spark: number[];
  mode?: "line" | "bar";
};

const props = withDefaults(defineProps<{
  readiness: number;
  readinessTone?: "good" | "warn" | "bad";
  verdict?: string | null;
  aiEnabled?: boolean;
  onVerdictRefresh?: () => void;
  anchors: Anchor[];
  scores?: Score[];   // accepted for API parity; not rendered in slim
  mobile?: boolean;
}>(), {
  aiEnabled: true, mobile: false, readinessTone: "good",
  verdict: null, scores: () => [],
});

const readinessColor = computed(() => {
  if (props.readinessTone === "warn") return "#EAB308";
  if (props.readinessTone === "bad") return "#EF4444";
  return "#22C55E";
});
const readinessLabel = computed(() => {
  if (props.readinessTone === "warn") return "caution";
  if (props.readinessTone === "bad") return "tanking";
  return "primed";
});

// Tiny ring SVG geometry (44 px, 4 px stroke)
const RING_SIZE = 44;
const RING_THICK = 4;
const ringR = (RING_SIZE - RING_THICK) / 2;
const ringC = 2 * Math.PI * ringR;
const ringDash = computed(() => {
  const pct = Math.max(0, Math.min(1, (props.readiness ?? 0) / 100));
  return `${ringC * pct} ${ringC * (1 - pct)}`;
});
</script>

<template>
  <div class="card linkable hero-slim" :class="{ mobile }">
    <!-- LEFT: mini ring + readiness status -->
    <div class="ring-block">
      <div class="ring-wrap">
        <svg :width="RING_SIZE" :height="RING_SIZE">
          <circle :cx="RING_SIZE / 2" :cy="RING_SIZE / 2" :r="ringR"
                  stroke="#243042" :stroke-width="RING_THICK" fill="none"/>
          <circle :cx="RING_SIZE / 2" :cy="RING_SIZE / 2" :r="ringR"
                  :stroke="readinessColor" :stroke-width="RING_THICK" fill="none"
                  stroke-linecap="round"
                  :stroke-dasharray="ringDash"
                  :transform="`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`"/>
        </svg>
        <span class="ring-num mono">{{ Math.round(readiness) }}</span>
      </div>
      <div class="ring-text">
        <span class="eyebrow">Readiness</span>
        <span class="ring-status" :class="`tone-${readinessTone}`">
          <span :class="['dot', `dot-${readinessTone}`]"/>
          {{ readinessLabel }}
        </span>
      </div>
    </div>

    <div class="vdiv"/>

    <!-- MIDDLE: 4 inline anchors with thin vertical dividers between -->
    <div class="anchors">
      <template v-for="(a, i) in anchors" :key="i">
        <div v-if="i > 0" class="vdiv pad"/>
        <div class="anchor">
          <span class="eyebrow">{{ a.label }}</span>
          <div class="anchor-val-row">
            <span class="mono anchor-val">
              {{ a.value }}<span v-if="a.unit" class="unit">{{ a.unit }}</span>
              <span v-if="a.sub" class="dim sub">{{ a.sub }}</span>
            </span>
            <Delta :value="a.delta" :invert="a.invert" :suffix="a.suffix" :size="10"/>
          </div>
        </div>
      </template>
    </div>

    <div v-if="aiEnabled" class="vdiv"/>

    <!-- RIGHT: verdict inline -->
    <div v-if="aiEnabled" class="verdict-block">
      <Sparkles :size="13" class="verdict-icon"/>
      <span class="verdict-text">{{ verdict ?? "—" }}</span>
      <button class="btn btn-icon mini" title="Regenerate"
              @click="onVerdictRefresh && onVerdictRefresh()">
        <RefreshCw :size="11"/>
      </button>
    </div>
  </div>
</template>

<style scoped>
.hero-slim {
  padding: 14px 18px;
  display: flex; align-items: center; gap: 18px;
  min-height: 84px;
}
.hero-slim.mobile {
  flex-wrap: wrap;
  align-items: stretch;
  gap: 14px;
  padding: 14px 16px;
}

.ring-block {
  display: flex; align-items: center; gap: 10px;
  flex: 0 0 auto;
}
.ring-wrap { position: relative; width: 44px; height: 44px; flex: 0 0 auto; }
.ring-num {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 500; line-height: 1;
}
.ring-text { display: flex; flex-direction: column; }
.ring-status {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; margin-top: 2px;
}
.ring-status.tone-good { color: var(--good); }
.ring-status.tone-warn { color: var(--warn); }
.ring-status.tone-bad  { color: var(--bad); }

.vdiv {
  width: 1px; align-self: stretch;
  background: var(--outline);
}
.vdiv.pad { margin: 6px 0; }

.anchors {
  display: flex; flex: 1; gap: 14px;
  align-items: center; min-width: 0;
}
.anchor {
  display: flex; flex-direction: column; gap: 3px; min-width: 0;
  flex: 1;
}
.anchor-val-row {
  display: flex; align-items: baseline; gap: 6px;
  white-space: nowrap;
}
.anchor-val {
  font-size: 15px; font-weight: 500; line-height: 1;
  font-variant-numeric: tabular-nums;
}
.sub { margin-left: 4px; font-size: 11px; color: var(--on-surface-2); }

.verdict-block {
  display: flex; align-items: center; gap: 8px;
  flex: 0 0 320px; max-width: 360px;
  min-width: 240px;
}
.verdict-icon { color: var(--on-surface-2); flex: 0 0 auto; }
.verdict-text {
  flex: 1; font-size: 12px; color: var(--on-surface);
  line-height: 1.45; text-wrap: pretty;
}
.btn.mini {
  width: 22px; height: 22px;
  border-color: transparent; flex: 0 0 auto;
}

.hero-slim.mobile .anchors { width: 100%; flex-wrap: wrap; }
.hero-slim.mobile .verdict-block { flex: 1 1 100%; max-width: none; padding-top: 6px; border-top: 1px solid var(--outline); }
</style>
