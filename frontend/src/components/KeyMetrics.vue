<script setup lang="ts">
/**
 * "Key metrics" — a titled section of identical MetricCards, 2-up.
 *
 * Replaces the previous VitalTiles grid, which invented its own card shape
 * (outlined uppercase micro-pills, axis-less sparklines). The reference this
 * project is modelled on uses ONE card everywhere and groups them under
 * plain section headings, so the value is in the repetition — a bespoke
 * card per surface is exactly what made the app feel disconnected.
 *
 * Data still comes from `/summary/tiles`; only the presentation changed.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { VitalTile } from "@/api/types";
import MetricCard from "./MetricCard.vue";

const router = useRouter();
const tiles = ref<VitalTile[]>([]);
const loaded = ref(false);
/** The user's saved tile order / hidden set, as Vital enum names. The
 *  phone has always let people reorder and hide these; honouring the same
 *  preference here keeps the two grids in the same order, which is the
 *  whole point of one card vocabulary. */
const order = ref<string[]>([]);
const hidden = ref<string[]>([]);

/** Vital enum name → tiles key, so a preference written against the old
 *  badge grid still means something. */
const VITAL_TO_KEY: Record<string, string> = {
  HR: "resting_hr", HRV: "hrv", SLEEP: "sleep_duration", STEPS: "steps",
  WEIGHT: "weight", BP: "blood_pressure", RECOVERY: "recovery",
};

const ROUTE: Record<string, string> = {
  hrv: "/hrv", resting_hr: "/heart-rate", steps: "/steps",
  sleep_duration: "/sleep", blood_pressure: "/blood-pressure",
  recovery: "/heart-rate", weight: "/weight",
};

/** Per-metric accent, matching the reference's habit of tinting each card's
 *  chart by metric family rather than using one global colour. */
const ACCENT: Record<string, string> = {
  hrv: "#7ee2a8", resting_hr: "#7ee2a8", steps: "#5fd3c4",
  sleep_duration: "#b39ddb", blood_pressure: "#7fc8f8",
  recovery: "#7ee2a8", weight: "#e8b661",
};

const BAR = new Set(["steps"]);

async function load() {
  const [t, p] = await Promise.allSettled([api.summaryTiles(), api.getProfile()]);
  tiles.value = t.status === "fulfilled" ? (t.value.tiles ?? []) : [];
  if (p.status === "fulfilled") {
    const extra = (p.value as { extra?: Record<string, unknown> })?.extra ?? {};
    order.value = (extra.vitals_order as string[]) ?? [];
    hidden.value = (extra.vitals_hidden as string[]) ?? [];
  }
  loaded.value = true;
}
onMounted(load);

/** Sentence-case chip text per metric, the way the reference words it —
 *  "Goal not met" on a goal metric reads better than "Out of range". */
function chipLabel(t: VitalTile): string | null {
  if (!t.status) return null;
  if (t.key === "steps") return t.status === "good" ? "Goal met" : "Goal not met";
  if (t.key === "sleep_duration") {
    return t.status === "good" ? "Goal met"
      : t.status === "typical" ? "Near goal" : "Goal not met";
  }
  if (t.key === "blood_pressure") return t.status_reason?.split(" range")[0] ?? null;
  // A 0-100 composite has no "range" to be in — "In range" on a recovery
  // of 35 reads as reassurance the number does not support. The server
  // already words these ("recovered" / "partially recovered" /
  // "under-recovered"); use its wording.
  if (t.key === "recovery") {
    const r = t.status_reason;
    return r ? r[0].toUpperCase() + r.slice(1) : null;
  }
  return t.status === "watch" ? "Out of range" : "In range";
}

/** The qualifier line. The reference puts the remaining-to-goal here, which
 *  is more useful than repeating the percentage the chip already implies. */
function qualifier(t: VitalTile): string {
  if (t.key === "steps" && typeof t.value === "number" && t.target) {
    const left = Math.max(0, Math.round(t.target - t.value));
    return left > 0 ? `Today • ${left.toLocaleString()} to go` : "Today • goal met";
  }
  if (t.stale_days != null && t.stale_days > 0) {
    const d = new Date((t.as_of ?? "") + "T00:00:00");
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }
  }
  return "Today";
}

function displayValue(t: VitalTile): number | string | null {
  if (t.value == null) return null;
  if (typeof t.value !== "number") return t.value;
  if (t.key === "steps") return t.value.toLocaleString();
  // Match the phone's formatting exactly. The server sends sleep to two
  // decimals; passing it through printed "7.35 h" on web against "7.4" on
  // the phone — the same number rendered as two different readings.
  return Number.isInteger(t.value) ? String(t.value) : t.value.toFixed(1);
}

const shown = computed(() => {
  const hide = new Set(hidden.value.map((v) => VITAL_TO_KEY[v]).filter(Boolean));
  const visible = tiles.value.filter((t) => !hide.has(t.key));
  if (!order.value.length) return visible;
  const rank = new Map(
    order.value.map((v) => VITAL_TO_KEY[v]).filter(Boolean)
      .map((k, i) => [k, i] as const),
  );
  // Anything the saved order doesn't mention tail-appends rather than
  // disappearing.
  return [...visible].sort(
    (a, b) => (rank.get(a.key) ?? 1e9) - (rank.get(b.key) ?? 1e9),
  );
});
</script>

<template>
  <section v-if="loaded && shown.length" class="km">
    <h2 class="sect">Key metrics</h2>
    <div class="grid">
      <button v-for="t in shown" :key="t.key" class="cell"
              @click="router.push(ROUTE[t.key] ?? '/')">
        <MetricCard
          :name="t.label"
          :value="displayValue(t)"
          :unit="t.unit"
          :qualifier="qualifier(t)"
          :status="t.status"
          :status-label="chipLabel(t)"
          :series="t.series"
          :band-low="t.band_low"
          :band-high="t.band_high"
          :target="t.key === 'steps' ? t.target ?? null : null"
          :chart="BAR.has(t.key) ? 'bar' : 'line'"
          :accent="ACCENT[t.key] ?? '#7ee2a8'"
        />
      </button>
    </div>
  </section>
</template>

<style scoped>
.km { margin: 18px 0; }
.sect {
  font-size: 1.35rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 12px; letter-spacing: -0.2px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 10px;
  /* Each card sizes to its own content. Stretching rows to the tallest card
     leaves large voids here because the metrics are heterogeneous — some
     carry a chip and a bar chart, some have no readings in the last week. */
  align-items: start;
}
.cell {
  padding: 0; border: 0; background: none; cursor: pointer;
  text-align: left; display: block; min-width: 0;
}
</style>
