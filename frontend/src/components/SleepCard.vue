<script setup lang="ts">
import { computed } from "vue";
import Card from "./Card.vue";
import type { SleepNight } from "@/api/types";

const props = defineProps<{ sleep: SleepNight | null }>();

const STAGE_COLORS: Record<string, string> = {
  awake: "#f97316",
  light: "#60a5fa",
  deep: "#1e40af",
  rem: "#a78bfa",
};

function fmtDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

const total = computed(() => props.sleep?.total_s ?? 0);

const segments = computed(() => {
  if (!props.sleep || total.value === 0) return [];
  return props.sleep.stages.map((s) => ({
    stage: s.stage,
    pct: (s.duration_s / total.value) * 100,
    color: STAGE_COLORS[s.stage] ?? "#64748b",
    duration_s: s.duration_s,
  }));
});

const subtitle = computed(() => {
  if (!props.sleep) return "";
  const start = new Date(props.sleep.start);
  const end = new Date(props.sleep.end);
  const fmt = (d: Date) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const ms = Date.now() - end.getTime();
  const h = Math.round(ms / 3600000);
  const ago = h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
  return `${fmt(start)} → ${fmt(end)}  ·  ${ago}`;
});
</script>

<template>
  <Card title="Last sleep" :subtitle="subtitle">
    <template v-if="sleep">
      <div class="big">{{ fmtDuration(total) }}</div>
      <div class="stack">
        <div
          v-for="seg in segments"
          :key="seg.stage"
          class="seg"
          :style="{ width: seg.pct + '%', background: seg.color }"
          :title="`${seg.stage}: ${fmtDuration(seg.duration_s)}`"
        />
      </div>
      <ul class="legend">
        <li v-for="seg in segments" :key="seg.stage">
          <span class="dot" :style="{ background: seg.color }" />
          <span class="lbl">{{ seg.stage }}</span>
          <span class="val">{{ fmtDuration(seg.duration_s) }}</span>
        </li>
      </ul>
    </template>
    <template v-else>
      <div class="empty">No sleep data yet</div>
    </template>
  </Card>
</template>

<style scoped>
.big { font-size: 2rem; font-weight: 300; color: var(--violet); line-height: 1; margin: 0.5rem 0; }
.stack { display: flex; height: 16px; border-radius: 4px; overflow: hidden; margin-top: 0.5rem; }
.seg { transition: opacity 0.2s; }
.seg:hover { opacity: 0.85; cursor: help; }
.legend { list-style: none; padding: 0; margin: 0.6rem 0 0; display: grid; grid-template-columns: 1fr 1fr; gap: 0.2rem 1rem; font-size: 0.8rem; }
.legend li { display: flex; align-items: center; gap: 0.4rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.lbl { color: var(--muted); flex: 1; text-transform: capitalize; }
.val { color: var(--text); }
.empty { color: var(--muted-2); padding: 1rem 0; text-align: center; }
</style>
