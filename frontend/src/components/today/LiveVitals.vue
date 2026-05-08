<script setup lang="ts">
/**
 * Live vitals row — HR, HRV, Steps. Each cell is a RouterLink.
 * Props: pre-bucketed 24h hourly arrays + headline numbers.
 */
import { RouterLink } from "vue-router";
import { Heart, Activity, Footprints } from "lucide-vue-next";
import Sparkline from "./Sparkline.vue";
import HourlyBuckets from "./HourlyBuckets.vue";
import Delta from "./Delta.vue";

withDefaults(defineProps<{
  hr: { latest: number | null; rest: number | null; ageLabel: string | null;
        series: number[]; mean?: number | null };
  hrv: { latest: number | null; series: number[]; mean?: number | null;
         deltaVsBaseline: number | null };
  steps: { total: number; goal: number; hourly: number[]; currentHour: number };
  mobile?: boolean;
}>(), { mobile: false });
</script>

<template>
  <div class="card live-row" :class="{ mobile }">
    <!-- HR -->
    <RouterLink to="/heart-rate" class="cell linkable hr">
      <div class="head">
        <div class="title hr-title">
          <Heart :size="14"/>
          <span class="eyebrow brand">Heart Rate</span>
        </div>
        <span class="dim age">{{ hr.ageLabel ?? "—" }}</span>
      </div>
      <div class="val-row">
        <span class="mono num-l">
          {{ hr.latest != null ? Math.round(hr.latest) : "—" }}
          <span class="unit">bpm</span>
        </span>
        <span v-if="hr.rest != null" class="dim small">rest {{ Math.round(hr.rest) }}</span>
      </div>
      <div class="spark">
        <Sparkline v-if="hr.series.length" :data="hr.series" color="#EF4444"
                   :mean="hr.mean ?? null" :height="28" :area-opacity="0.18" :pad-top="4"/>
      </div>
    </RouterLink>

    <!-- HRV -->
    <RouterLink to="/heart-rate" class="cell linkable">
      <div class="head">
        <div class="title">
          <Activity :size="14" class="good"/>
          <span class="eyebrow">HRV</span>
        </div>
        <span class="dim age">tonight</span>
      </div>
      <div class="val-row">
        <span class="mono num-l">
          {{ hrv.latest != null ? Math.round(hrv.latest) : "—" }}
          <span class="unit">ms</span>
        </span>
        <Delta :value="hrv.deltaVsBaseline" :size="11"/>
      </div>
      <div class="spark">
        <Sparkline v-if="hrv.series.length" :data="hrv.series" color="#22C55E"
                   :mean="hrv.mean ?? null" :height="28" :area-opacity="0.16" :pad-top="4"/>
      </div>
    </RouterLink>

    <!-- Steps -->
    <RouterLink to="/trends#steps" class="cell linkable last">
      <div class="head">
        <div class="title">
          <Footprints :size="14" class="muted"/>
          <span class="eyebrow">Steps</span>
        </div>
        <span class="mono dim age">
          {{ steps.goal > 0 ? Math.round((steps.total / steps.goal) * 100) : 0 }}%
        </span>
      </div>
      <div class="val-row">
        <span class="mono num-l">{{ steps.total.toLocaleString() }}</span>
        <span class="dim small">/ {{ steps.goal.toLocaleString() }}</span>
      </div>
      <div class="steps-bar-wrap">
        <div class="hourly-bg">
          <HourlyBuckets :data="steps.hourly" color="#94A3B8"
                         :height="24" :current-hour="steps.currentHour"/>
        </div>
        <div class="prog-track">
          <div class="prog-fill"
               :style="{ width: `${Math.min(100, (steps.total / Math.max(1, steps.goal)) * 100)}%` }"/>
        </div>
      </div>
    </RouterLink>
  </div>
</template>

<style scoped>
.live-row {
  padding: 0;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  min-height: 96px;
}
.live-row.mobile { grid-template-columns: 1fr; }
.cell {
  display: flex; flex-direction: column; justify-content: space-between;
  padding: 14px 18px; min-width: 0; position: relative; cursor: pointer;
  text-decoration: none; color: inherit;
  border-right: 1px solid var(--outline);
}
.cell.last { border-right: none; }
.live-row.mobile .cell {
  border-right: none; border-bottom: 1px solid var(--outline);
}
.live-row.mobile .cell.last { border-bottom: none; }
.cell.hr {
  border-radius: 12px 0 0 12px;
}
.live-row.mobile .cell.hr { border-radius: 12px 12px 0 0; }
.cell.last { border-radius: 0 12px 12px 0; }
.live-row.mobile .cell.last { border-radius: 0 0 12px 12px; }
.head { display: flex; align-items: center; justify-content: space-between; }
.title { display: flex; align-items: center; gap: 6px; }
.title.hr-title { color: var(--brand); }
.brand { color: var(--brand); }
.good  { color: var(--good); }
.muted { color: var(--on-surface-2); }
.age { font-size: 11px; }
.val-row { display: flex; align-items: baseline; gap: 8px; margin-top: 2px; }
.small { font-size: 11px; }
.spark { height: 28px; margin-top: 4px; }
.steps-bar-wrap { position: relative; margin-top: 6px; }
.hourly-bg { position: absolute; inset: 0; opacity: 0.6; }
.prog-track {
  position: relative; height: 6px; margin-top: 18px;
  border-radius: 999px; background: var(--outline);
}
.prog-fill {
  position: absolute; left: 0; top: 0; bottom: 0;
  border-radius: 999px; background: var(--on-surface);
}
</style>
