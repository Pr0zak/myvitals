<script setup lang="ts">
/**
 * Vitals grid with threshold semantics — web twin of `ui/common/VitalTiles.kt`.
 *
 * A bare "27 ms" is unreadable: it needs the user's own normal and which
 * direction is better. Both come from `/summary/tiles`; nothing here decides
 * what counts as good, so this grid and the phone's cannot disagree.
 *
 * Tiles whose reading is stale show the value and its age but NO verdict —
 * the server withholds the status, and the absence is deliberate rather than
 * something to paper over with a neutral-looking pill.
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { VitalTile } from "@/api/types";
import Sparkline from "./today/Sparkline.vue";

const router = useRouter();
const tiles = ref<VitalTile[]>([]);
const loaded = ref(false);

const ROUTE: Record<string, string> = {
  hrv: "/hrv",
  resting_hr: "/heart-rate",
  steps: "/steps",
  sleep_duration: "/sleep",
  blood_pressure: "/blood-pressure",
  recovery: "/heart-rate",
  weight: "/weight",
};

const TONE: Record<string, string> = {
  good: "#22c55e", typical: "#eab308", watch: "#ef4444",
};

async function load() {
  try {
    const r = await api.summaryTiles();
    tiles.value = r.tiles ?? [];
  } catch {
    tiles.value = [];
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

/** The sparkline takes the tile's own status colour, falling back to a
 *  neutral tone when the server withheld a verdict. */
function lineColor(t: VitalTile): string {
  return t.status ? TONE[t.status] : "#7b8496";
}

function values(t: VitalTile): Array<number | null> {
  return t.series.map((p) => p.value);
}

/** True when a series has at least two real points — one point can't draw
 *  a line, and an all-null series should show nothing rather than a flat
 *  baseline implying steady values. */
function plottable(t: VitalTile): boolean {
  return t.series.filter((p) => p.value != null).length >= 2;
}

function fmtValue(t: VitalTile): string {
  if (t.value == null) return "—";
  if (typeof t.value === "string") return t.value;
  return t.key === "steps" ? t.value.toLocaleString() : String(t.value);
}

function fmtDelta(t: VitalTile): string | null {
  if (t.delta == null) return null;
  const sign = t.delta > 0 ? "+" : "";
  return `${sign}${t.delta}${t.unit ? " " + t.unit : ""} vs baseline`;
}
</script>

<template>
  <section v-if="loaded && tiles.length" class="tiles">
    <button
      v-for="t in tiles" :key="t.key" class="tile"
      :style="{ '--tone': t.status ? TONE[t.status] : 'var(--line)' }"
      @click="router.push(ROUTE[t.key] ?? '/')"
    >
      <div class="row">
        <span class="label">{{ t.label }}</span>
        <span v-if="t.status" class="pill">{{ t.status }}</span>
      </div>

      <div class="valrow">
        <span class="val num">{{ fmtValue(t) }}</span>
        <span v-if="t.unit" class="unit">{{ t.unit }}</span>
      </div>

      <Sparkline
        v-if="plottable(t)" :data="values(t)" :color="lineColor(t)"
        :height="34" :area-opacity="0.14" :stroke-width="1.6"
      />
      <div v-else class="nospark"></div>

      <p v-if="t.status_reason" class="why">{{ t.status_reason }}</p>
      <p v-else-if="fmtDelta(t)" class="why">{{ fmtDelta(t) }}</p>
      <p v-else class="why muted">&nbsp;</p>
    </button>
  </section>
</template>

<style scoped>
.tiles {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px; margin-bottom: 14px;
}
.tile {
  display: flex; flex-direction: column; gap: 4px; text-align: left;
  background: var(--bg-2); border: 1px solid var(--line);
  border-left: 3px solid var(--tone);
  border-radius: 14px; padding: 12px 13px; cursor: pointer; color: inherit;
}
.row { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.label { font-size: .74rem; color: var(--muted); font-weight: 600; }
.pill {
  font-size: .6rem; font-weight: 800; text-transform: uppercase;
  letter-spacing: .08em; color: var(--tone);
  border: 1px solid var(--tone); border-radius: 999px; padding: 1px 6px;
}
.valrow { display: flex; align-items: baseline; gap: 4px; }
.val { font-size: 1.5rem; font-weight: 700; color: var(--text); line-height: 1.1; }
.unit { font-size: .72rem; color: var(--muted); }
.nospark { height: 34px; }
.why { font-size: .68rem; color: var(--muted); margin: 0; line-height: 1.25; }
</style>
