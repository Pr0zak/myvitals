<script setup lang="ts">
/**
 * "Health status" — the reference's opening section.
 *
 * Two things, in the same card vocabulary as everything below it:
 *   - a one-line roll-up ("Vitals · 3 of 5 in range"), counted server-side
 *   - Readiness as a full-width MetricCard
 *
 * Readiness used to be a bespoke hero: an uppercase micro-label, a bare
 * dash and a right-hand sparkline — a third card style stacked above the
 * Focus pills and the Key metrics grid. It is a metric with a value, a
 * band and a series, so it should look like every other metric. Its
 * drivers and the "how this is calculated" sheet survive behind a tap.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { ReadinessDetail, VitalTilesResponse } from "@/api/types";
import MetricCard from "./MetricCard.vue";

defineProps<{ syncNote?: string | null }>();

const readiness = ref<ReadinessDetail | null>(null);
const roll = ref<VitalTilesResponse["summary"] | null>(null);
const open = ref(false);

async function load() {
  const [r, t] = await Promise.allSettled([
    api.readinessDetail(),
    api.summaryTiles(),
  ]);
  if (r.status === "fulfilled") readiness.value = r.value;
  if (t.status === "fulfilled") roll.value = t.value.summary ?? null;
}
onMounted(load);

/** Band → the same three-value status vocabulary the tiles use, so one
 *  chip style covers the whole screen. */
const status = computed(() => {
  switch (readiness.value?.band) {
    case "high": return "good";
    case "moderate": return "typical";
    case "low": return "watch";
    default: return null;
  }
});

const chipLabel = computed(() => {
  const b = readiness.value?.band;
  return b ? b[0].toUpperCase() + b.slice(1) : null;
});

const series = computed(() =>
  (readiness.value?.series ?? []).map((p) => ({ date: p.date, value: p.score })),
);

const value = computed(() =>
  readiness.value?.score == null ? null : Math.round(readiness.value.score),
);

const qualifier = computed(() =>
  readiness.value?.score == null
    ? sentence(readiness.value?.reason ?? "Not enough data yet")
    : "Today",
);

/** The server's reasons are lowercase fragments ("no inputs"); the card
 *  puts them where a sentence belongs. */
function sentence(t: string): string {
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

const rollText = computed(() => {
  const r = roll.value;
  if (!r || !r.judged) return null;
  return `${r.in_range} of ${r.judged} in range`;
});

const ORDER: Array<[string, string]> = [
  ["hrv", "HRV"], ["rhr", "Resting HR"],
  ["sleep_score", "Sleep quality"], ["sleep_duration", "Sleep duration"],
];
</script>

<template>
  <section class="hs">
    <h2 class="sect">Health status</h2>

    <div v-if="rollText" class="roll">
      <span class="rl">Vitals</span>
      <span class="rv">{{ rollText }}</span>
      <!-- Freshness qualifies these numbers, so it sits with them rather
           than floating between sections as bare text. -->
      <span v-if="syncNote" class="sync">{{ syncNote }}</span>
    </div>

    <button class="wide" @click="open = !open">
      <MetricCard
        name="Readiness"
        :value="value"
        unit=""
        :qualifier="qualifier"
        :status="status"
        :status-label="chipLabel"
        :series="series"
        accent="#7ee2a8"
      />
    </button>

    <!-- Drivers + weights, generated from the payload so retuning them
         server-side updates this instead of drifting from it. -->
    <div v-if="open && readiness" class="drawer">
      <p class="intro">
        A weighted blend of four signals, each scored against your own
        28-day baseline — not a population average. 50 is your normal.
      </p>
      <div v-for="d in readiness.drivers" :key="d.key" class="drow">
        <span class="dl">{{ d.label }}</span>
        <span class="dv">
          {{ d.value == null ? "—" : (d.unit === "h" ? d.value.toFixed(1) : d.value.toFixed(0)) }}
          <small v-if="d.unit">{{ d.unit }}</small>
        </span>
        <span v-if="d.z != null" class="dz" :class="(d.sub_score ?? 50) >= 50 ? 'up' : 'down'">
          {{ d.z >= 0 ? "+" : "" }}{{ d.z.toFixed(1) }}σ
        </span>
        <span class="dw">{{ ((readiness.weights[d.key] ?? 0) * 100).toFixed(0) }}%</span>
      </div>
      <div v-for="[key, label] in ORDER" :key="'m' + key">
        <div v-if="!readiness.drivers.some(d => d.key === key)" class="drow missing">
          <span class="dl">{{ label }}</span>
          <span class="dv">not used today</span>
        </div>
      </div>
      <p class="note">
        When too few signals are available the score is withheld rather than
        guessed — a number driven by one noisy input is worse than no number.
      </p>
    </div>
  </section>
</template>

<style scoped>
.hs { margin: 14px 0 18px; }
.sect {
  font-size: 1.35rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 10px; letter-spacing: -0.2px;
}
.roll {
  display: flex; align-items: baseline; gap: 8px;
  background: #1b1c1f; border-radius: 16px;
  padding: 12px 14px; margin-bottom: 10px;
}
.rl { font-size: .8rem; color: #b9bec6; }
.rv { font-size: 1.05rem; font-weight: 300; color: #e9edf2; }
.sync { margin-left: auto; font-size: .7rem; color: #6f767f; }

.wide {
  display: block; width: 100%; padding: 0; border: 0;
  background: none; text-align: left; cursor: pointer;
}

.drawer {
  background: #1b1c1f; border-radius: 16px;
  padding: 14px; margin-top: 10px;
}
.intro, .note { font-size: .76rem; color: #8d949d; margin: 0 0 10px; }
.note { margin: 10px 0 0; }
.drow { display: flex; align-items: baseline; gap: 10px; padding: 5px 0; }
.dl { flex: 1; font-size: .82rem; color: #e9edf2; }
.dv { font-size: .82rem; color: #e9edf2; font-variant-numeric: tabular-nums; }
.dv small { color: #8d949d; font-size: .7rem; margin-left: 2px; }
.dz { font-size: .74rem; font-weight: 500; }
.dz.up { color: #7ee2a8; }
.dz.down { color: #e8b661; }
.dw { font-size: .72rem; color: #6f767f; min-width: 30px; text-align: right; }
.drow.missing .dv { color: #6f767f; font-size: .74rem; }
</style>
