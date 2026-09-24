<script setup lang="ts">
/**
 * Glowing progress ring — phone `NeonRing`. `fraction` is clamped 0..1; a
 * missing value is drawn as 0 and SAID in the slot, never invented.
 * `ticks` mark thresholds (fasting stages); `dots` mark milestones, filled
 * once reached (sober). `outer` draws a thin second arc outside the main one.
 */
import { computed } from "vue";

const props = withDefaults(defineProps<{
  fraction: number;
  color: string;
  size?: number;
  stroke?: number;
  ticks?: number[];
  dots?: Array<{ at: number; reached: boolean }>;
  outer?: number | null;
  outerColor?: string;
}>(), { size: 140, stroke: 10, ticks: () => [], dots: () => [], outer: null, outerColor: "#28e6ff" });

const geo = computed(() => {
  const gap = props.outer != null ? 7 : 0;
  const r = props.size / 2 - props.stroke / 2 - gap - 2;
  const c = props.size / 2;
  const circ = 2 * Math.PI * r;
  const f = Math.max(0, Math.min(1, props.fraction || 0));
  const r2 = props.size / 2 - 2.5;
  const c2 = 2 * Math.PI * r2;
  const of = Math.max(0, Math.min(1, props.outer ?? 0));
  const at = (t: number, rr: number) => {
    const a = t * 2 * Math.PI - Math.PI / 2;
    return { x: c + rr * Math.cos(a), y: c + rr * Math.sin(a) };
  };
  return { r, c, circ, f, r2, c2, of, at };
});
</script>

<template>
  <div class="neon-ring" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" aria-hidden="true">
      <circle :cx="geo.c" :cy="geo.c" :r="geo.r" fill="none" stroke="#272a3b" :stroke-width="stroke" />
      <circle v-if="geo.f > 0" :cx="geo.c" :cy="geo.c" :r="geo.r" fill="none" :stroke="color"
              :stroke-width="stroke * 2.1" stroke-linecap="round" opacity="0.22"
              :stroke-dasharray="`${geo.circ * geo.f} ${geo.circ}`" :transform="`rotate(-90 ${geo.c} ${geo.c})`" />
      <circle v-if="geo.f > 0" :cx="geo.c" :cy="geo.c" :r="geo.r" fill="none" :stroke="color"
              :stroke-width="stroke" stroke-linecap="round"
              :stroke-dasharray="`${geo.circ * geo.f} ${geo.circ}`" :transform="`rotate(-90 ${geo.c} ${geo.c})`" />
      <template v-if="outer != null">
        <circle :cx="geo.c" :cy="geo.c" :r="geo.r2" fill="none" stroke="#272a3b" stroke-width="3" />
        <circle v-if="geo.of > 0" :cx="geo.c" :cy="geo.c" :r="geo.r2" fill="none" :stroke="outerColor" stroke-width="3"
                stroke-linecap="round" :stroke-dasharray="`${geo.c2 * geo.of} ${geo.c2}`"
                :transform="`rotate(-90 ${geo.c} ${geo.c})`" />
      </template>
      <line v-for="(t, i) in ticks" :key="'t' + i"
            :x1="geo.at(t, geo.r - stroke).x" :y1="geo.at(t, geo.r - stroke).y"
            :x2="geo.at(t, geo.r + stroke).x" :y2="geo.at(t, geo.r + stroke).y"
            stroke="#ececf5" stroke-width="2" opacity="0.7" />
      <circle v-for="(d, i) in dots" :key="'d' + i" :cx="geo.at(d.at, geo.r).x" :cy="geo.at(d.at, geo.r).y" r="5"
              :fill="d.reached ? color : '#0f1118'" :stroke="color" stroke-width="2" />
    </svg>
    <div class="nr-in"><slot /></div>
  </div>
</template>

<style scoped>
.neon-ring { position: relative; flex: 0 0 auto; }
.neon-ring svg { display: block; overflow: visible; }
.nr-in { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; line-height: 1.1; }
</style>
