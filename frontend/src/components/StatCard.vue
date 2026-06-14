<script setup lang="ts">
/**
 * Headline metric card: a big tabular-numeric value + unit, with an optional
 * delta line ("▲ 2.1 vs prior", coloured good/bad) or a free sub-line via the
 * default slot. Replaces the `.big` / `.val` + `.unit` + `.delta` markup +
 * CSS each detail view reinvented.
 *
 * Delta direction: `deltaGoodWhen` says whether up or down is the good outcome
 * (RHR down = good, HRV up = good), driving the colour.
 *
 * Usage:
 *   <StatCard title="Resting HR" :value="rhr" unit="bpm"
 *             :delta="rhrDelta" delta-good-when="down" />
 *   <StatCard title="Max HR (24h)" :value="maxHr" unit="bpm">
 *     <span class="muted">est max {{ estMax }}</span>
 *   </StatCard>
 */
import { computed } from "vue";
import Card from "./Card.vue";

const props = withDefaults(defineProps<{
  title: string;
  value: string | number;
  unit?: string;
  flat?: boolean;
  delta?: number | null;
  deltaGoodWhen?: "up" | "down";
  deltaSuffix?: string;
  deltaDigits?: number;
}>(), {
  flat: true,
  deltaGoodWhen: "up",
  deltaSuffix: "vs prior",
  deltaDigits: 1,
});

const deltaClass = computed(() => {
  if (props.delta == null || props.delta === 0) return "";
  const up = props.delta > 0;
  const good = props.deltaGoodWhen === "up" ? up : !up;
  return good ? "good" : "bad";
});
</script>

<template>
  <Card :title="title" :flat="flat">
    <div class="stat-big">
      {{ value }}<span v-if="unit" class="stat-unit">{{ unit }}</span>
    </div>
    <div v-if="delta != null" class="stat-delta" :class="deltaClass">
      {{ delta < 0 ? "▼" : "▲" }} {{ Math.abs(delta).toFixed(deltaDigits) }} {{ deltaSuffix }}
    </div>
    <div v-else-if="$slots.default" class="stat-delta"><slot /></div>
  </Card>
</template>

<style scoped>
.stat-big {
  font-size: 1.7rem; font-weight: 600;
  font-feature-settings: "tnum"; line-height: 1.1;
}
.stat-unit {
  font-size: 0.8rem; color: var(--muted); font-weight: 500; margin-left: 0.2rem;
}
.stat-delta {
  font-size: 0.78rem; color: var(--muted); margin-top: 0.2rem;
  font-feature-settings: "tnum";
}
.stat-delta.good { color: var(--good); }
.stat-delta.bad  { color: var(--bad); }
</style>
