<script setup lang="ts">
/**
 * Hero band — readiness gauge + 4 anchor numbers + 2x2 score mini-cards.
 * Props are derived from /summary/today + 7d trailing summary upstream
 * so this component stays presentational.
 */
import { computed } from "vue";
import { Sparkles, RefreshCw } from "lucide-vue-next";
import Gauge from "./Gauge.vue";
import Delta from "./Delta.vue";
import Sparkline from "./Sparkline.vue";

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
  readiness: number;            // 0-100
  readinessTone?: "good" | "warn" | "bad";
  verdict?: string | null;       // AI-generated; null when AI off / not yet
  aiEnabled?: boolean;
  onVerdictRefresh?: () => void;
  anchors: Anchor[];
  scores: Score[];
  mobile?: boolean;
}>(), { aiEnabled: true, mobile: false, readinessTone: "good", verdict: null });

const readinessColor = computed(() => {
  if (props.readinessTone === "warn") return "#EAB308";
  if (props.readinessTone === "bad") return "#EF4444";
  return "#22C55E";
});

function toneColor(t: Score["tone"]) {
  if (t === "good") return "#22C55E";
  if (t === "warn") return "#EAB308";
  if (t === "bad") return "#EF4444";
  return "#94A3B8";
}
</script>

<template>
  <div class="card linkable hero" :class="{ mobile }">
    <!-- LEFT: gauge + verdict -->
    <div class="left">
      <Gauge :value="readiness" :color="readinessColor" :size="mobile ? 132 : 140"/>
      <div class="verdict" :class="{ disabled: !aiEnabled }">
        <Sparkles :size="13" class="verdict-icon" :class="{ off: !aiEnabled }"/>
        <span class="verdict-text">{{ aiEnabled ? (verdict ?? "—") : "—" }}</span>
        <button class="btn btn-icon mini" title="Regenerate"
                @click="onVerdictRefresh && onVerdictRefresh()">
          <RefreshCw :size="11"/>
        </button>
      </div>
    </div>

    <!-- MIDDLE: anchor rows — grid so columns line up across rows -->
    <div class="middle">
      <div v-for="(a, i) in anchors" :key="i" class="anchor-row">
        <span class="eyebrow">{{ a.label }}</span>
        <span class="anchor-val mono">
          {{ a.value }}<span v-if="a.unit" class="unit">{{ a.unit }}</span>
          <span v-if="a.sub" class="dim sub">{{ a.sub }}</span>
        </span>
        <span class="anchor-delta">
          <Delta :value="a.delta" :invert="a.invert" :suffix="a.suffix" :size="11"/>
        </span>
      </div>
    </div>

    <!-- RIGHT: score grid -->
    <div class="right">
      <div v-for="(s, i) in scores" :key="i" class="score-card">
        <div class="score-head">
          <span class="score-label">{{ s.label }}</span>
          <span :class="['dot', `dot-${s.tone}`]"/>
        </div>
        <div class="mono score-value">{{ s.value ?? "—" }}</div>
        <div class="score-spark">
          <Sparkline :data="s.spark" :color="toneColor(s.tone)"
                     :height="28" :area-opacity="0.22"
                     :dashed-mean="false" :pad-top="2"
                     :mode="s.mode ?? 'line'"
                     :show-symbol="(s.mode ?? 'line') === 'line' && s.spark.length <= 14"
                     :symbol-size="3"/>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hero {
  padding: 20px;
  display: grid;
  grid-template-columns: 40% 30% 30%;
  gap: 20px;
  min-height: 220px;
}
.hero.mobile {
  grid-template-columns: 1fr;
  gap: 24px;
  min-height: auto;
}
.left {
  display: flex; flex-direction: column;
  align-items: flex-start; gap: 16px;
  justify-content: space-between; padding-right: 8px;
}
.hero.mobile .left { align-items: center; padding-right: 0; }
.verdict {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 12px; color: var(--on-surface-2); line-height: 1.5;
  padding-right: 6px;
}
.verdict.disabled .verdict-text { color: var(--dim); }
.verdict-icon { color: var(--on-surface-2); margin-top: 1px; flex-shrink: 0; }
.verdict-icon.off { opacity: 0.4; }
.verdict-text { flex: 1; color: var(--on-surface); }
.btn.mini { width: 22px; height: 22px; border-color: transparent; }

.middle {
  display: flex; flex-direction: column;
  justify-content: space-between; gap: 12px;
  padding-left: 12px; border-left: 1px solid var(--outline);
}
.hero.mobile .middle { border-left: none; padding-left: 0; gap: 16px; }
.anchor-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 56px;
  align-items: baseline;
  gap: 12px;
}
.anchor-val {
  font-size: 16px; font-weight: 500;
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.anchor-delta {
  text-align: right; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.sub { margin-left: 6px; font-size: 13px; }

.right {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  padding-left: 8px; border-left: 1px solid var(--outline);
}
.hero.mobile .right { border-left: none; padding-left: 0; }
.score-card {
  background: var(--surface-low);
  border: 1px solid var(--outline);
  border-radius: 10px; padding: 10px;
  display: flex; flex-direction: column; justify-content: space-between;
  min-height: 96px;
}
.score-head { display: flex; align-items: center; justify-content: space-between; }
.score-label {
  font-size: 10px; letter-spacing: 1.2px; text-transform: uppercase;
  color: var(--on-surface-2);
}
.score-value {
  font-size: 22px; font-weight: 500;
  color: var(--on-surface); letter-spacing: -0.3px;
}
.score-spark { height: 28px; margin-top: 2px; }
.score-card { min-height: 108px; }
</style>
