<script setup lang="ts">
/**
 * Weight + 30-day sparkline + dashed goal line. "Log weight" button
 * is reserved for a future slide-over; for now it routes the user
 * to /weight where the existing form lives.
 */
import { RouterLink } from "vue-router";
import { Plus } from "lucide-vue-next";
import Sparkline from "./Sparkline.vue";
import Delta from "./Delta.vue";

defineProps<{
  latestLb: number | null;
  goalLb: number | null;
  series: number[];   // up to 30 days, trailing
  delta30Lb: number | null;
  fromLabel: string;
  toLabel: string;
  asOfLabel?: string | null;
}>();
</script>

<template>
  <div class="card">
    <div class="card-title">
      <span>Body</span>
      <RouterLink to="/weight" class="btn btn-tiny">
        <Plus :size="11"/> Log weight
      </RouterLink>
    </div>
    <div class="hl-row">
      <span class="mono num-xl">
        {{ latestLb != null ? latestLb.toFixed(1) : "—" }}
        <span class="unit">lb</span>
      </span>
      <Delta v-if="delta30Lb != null" :value="+delta30Lb.toFixed(1)" suffix=" lb" invert/>
      <span class="dim ago">30d</span>
    </div>
    <div class="dim sub" v-if="asOfLabel || goalLb != null">
      <template v-if="asOfLabel">last reading · {{ asOfLabel }}</template>
      <template v-if="goalLb != null"> · goal {{ goalLb.toFixed(1) }} lb</template>
    </div>
    <div class="chart">
      <Sparkline :data="series" color="#94A3B8" :mean="goalLb"
                 :height="64" :area-opacity="0.10" :dashed-mean="true" :pad-top="6"/>
    </div>
    <div class="legend">
      <span class="dim mono">{{ fromLabel }}</span>
      <span v-if="goalLb != null" class="dim mono">— goal {{ goalLb.toFixed(1) }}</span>
      <span class="dim mono">{{ toLabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.hl-row { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
.ago { font-size: 11px; margin-left: auto; }
.sub { font-size: 11px; margin-bottom: 12px; }
.chart { height: 64px; margin-top: 16px; }
.legend {
  display: flex; justify-content: space-between;
  font-size: 10px; margin-top: 6px;
}
.dim { color: var(--on-surface-2); }
.btn-tiny { text-transform: none; letter-spacing: 0; text-decoration: none; }
</style>
