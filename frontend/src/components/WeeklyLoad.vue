<script setup lang="ts">
/**
 * Weekly training load against a personal target band.
 *
 * Google Health dropped daily cardio goals for weekly load targets, on the
 * grounds that a daily number punishes an ordinary rest day. This is that idea
 * in the units this app already computes.
 *
 * Nothing here is judged client-side: the band, the verdict and the daily
 * breakdown all come from `/summary/training-load`, so the phone card and this
 * one cannot disagree. Phone twin: `WeeklyLoad.kt`.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";

import type { TrainingLoad } from "@/api/types";

const data = ref<TrainingLoad | null>(null);
const failed = ref(false);

onMounted(async () => {
  try {
    data.value = await api.trainingLoad();
  } catch {
    failed.value = true;
  }
});

const TONE: Record<string, string> = {
  under: "#28e6ff", optimal: "#5dff3b",
  overreaching: "#ffb52e", unknown: "#9b9bb0",
};
const tone = computed(() => TONE[data.value?.band ?? "unknown"] ?? "#9b9bb0");

const verdict = computed(() => {
  switch (data.value?.band) {
    case "under": return "Below your usual load";
    case "optimal": return "In your usual range";
    case "overreaching": return "Above your usual load";
    default: return "Not enough history yet";
  }
});

/** Bar heights are relative to the busiest day, so a quiet week still reads. */
const peak = computed(() =>
  Math.max(1, ...(data.value?.daily ?? []).map((d) => d.load)));

/** Where the week sits along the target band, as a 0-1 position for the marker. */
const markerPct = computed(() => {
  const d = data.value;
  if (!d || d.target_low == null || d.target_high == null) return null;
  // Scale runs to 1.6x the top of the band so "over" has somewhere to sit.
  const full = d.target_high * 1.6;
  return Math.max(0, Math.min(100, (d.week_load / full) * 100));
});
const bandLeft = computed(() => {
  const d = data.value;
  if (!d || d.target_low == null || d.target_high == null) return null;
  const full = d.target_high * 1.6;
  return {
    left: `${(d.target_low / full) * 100}%`,
    width: `${((d.target_high - d.target_low) / full) * 100}%`,
  };
});

const DOW = ["S", "M", "T", "W", "T", "F", "S"];
function letter(iso: string): string {
  return DOW[new Date(iso + "T00:00:00").getDay()] ?? "";
}
</script>

<template>
  <section v-if="data && !failed" class="wl" :style="{ '--tone': tone }">
    <p class="lbl">Training load · this week</p>

    <div class="row">
      <span class="big num">{{ Math.round(data.week_load) }}</span>
      <span v-if="data.target_low != null" class="of num">
        of {{ Math.round(data.target_low) }}–{{ Math.round(data.target_high!) }}
      </span>
    </div>
    <p class="verdict">{{ verdict }}</p>

    <div class="bars">
      <span
        v-for="d in data.daily" :key="d.date" class="bar"
        :style="{ height: `${Math.max(3, (d.load / peak) * 100)}%`,
                  opacity: d.load > 0 ? 1 : 0.28 }"
      />
    </div>
    <div class="days">
      <span v-for="d in data.daily" :key="d.date">{{ letter(d.date) }}</span>
    </div>

    <div v-if="bandLeft" class="track">
      <span class="band" :style="bandLeft" />
      <span class="marker" :style="{ left: `${markerPct}%` }" />
    </div>
    <div v-if="bandLeft" class="scale">
      <span>under</span><span>your usual range</span><span>over</span>
    </div>
  </section>
</template>

<style scoped>
.wl {
  background: #181b27; border: 1px solid color-mix(in srgb, var(--tone) 22%, transparent);
  border-radius: 20px; padding: 14px; margin: 12px 0;
}
.lbl {
  font-size: .7rem; letter-spacing: .12em; text-transform: uppercase;
  color: #9b9bb0; margin: 0 0 8px;
}
.row { display: flex; align-items: baseline; gap: 8px; }
.num { font-variant-numeric: tabular-nums; }
.big {
  font-size: 2.4rem; font-weight: 700; letter-spacing: -.045em; color: #ececf5;
  line-height: 1;
}
.of { font-size: .85rem; color: #9b9bb0; }
.verdict { font-size: .8rem; color: var(--tone); margin: 6px 0 0; font-weight: 600; }

.bars {
  display: flex; align-items: flex-end; gap: 4px; height: 54px; margin: 14px 0 4px;
}
.bar { flex: 1; background: var(--tone); border-radius: 4px 4px 2px 2px; }
.days {
  display: flex; gap: 4px; font-size: .65rem; color: #9b9bb0;
}
.days span { flex: 1; text-align: center; }

.track {
  position: relative; height: 8px; border-radius: 999px;
  background: #23263a; margin: 14px 0 6px;
}
.band {
  position: absolute; top: 0; bottom: 0; border-radius: 999px;
  background: color-mix(in srgb, #5dff3b 45%, transparent);
}
.marker {
  position: absolute; top: -5px; width: 3px; height: 18px; border-radius: 2px;
  background: #ececf5; box-shadow: 0 0 12px rgba(255, 255, 255, .55);
  transform: translateX(-1.5px);
}
.scale {
  display: flex; justify-content: space-between; font-size: .62rem; color: #9b9bb0;
}
</style>
