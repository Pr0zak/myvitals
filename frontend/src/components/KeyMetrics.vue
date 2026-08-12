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
/** Section headings and their order — both from the server, so the two
 *  grids can't disagree about where a metric belongs. */
const groupOrder = ref<string[]>([]);

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

/**
 * Per-metric accent — the accent of the DETAIL VIEW this card opens.
 *
 * This was a separate hand-picked set left over from the classic theme, so a
 * mint-green "Resting HR" card opened a cyan heart-rate chart. Same domain
 * palette as the phone's `Vital.accent`: heart family cyan, sleep magenta,
 * move lime, weight/temp amber.
 */
const ACCENT: Record<string, string> = {
  resting_hr: "#28e6ff", hrv: "#28e6ff", blood_pressure: "#28e6ff",
  recovery: "#28e6ff", sleep_duration: "#ff3ad8", steps: "#5dff3b",
  weight: "#ffb52e", skin_temp: "#ffb52e",
};

const BAR = new Set(["steps"]);
/** Measured every few weeks, not daily — a 7-day window is usually empty
 *  for these, so they plot the full 14 days the server sends. */
const INTERMITTENT = new Set(["weight", "blood_pressure"]);

async function load() {
  const [t, p] = await Promise.allSettled([api.summaryTiles(), api.getProfile()]);
  tiles.value = t.status === "fulfilled" ? (t.value.tiles ?? []) : [];
  if (t.status === "fulfilled") groupOrder.value = t.value.group_order ?? [];
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

/** Tiles bucketed under their server-assigned heading, in server order.
 *  A group with nothing in it is dropped rather than rendering an empty
 *  heading. */
const grouped = computed(() => {
  const byGroup = new Map<string, VitalTile[]>();
  for (const t of shown.value) {
    const g = t.group ?? "Other";
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g)!.push(t);
  }
  const ordered = groupOrder.value.length ? groupOrder.value : [...byGroup.keys()];
  const out = ordered
    .filter((g) => byGroup.has(g))
    .map((g) => ({ name: g, tiles: byGroup.get(g)! }));
  // Anything the server didn't order still appears, rather than vanishing.
  for (const [g, ts] of byGroup) {
    if (!ordered.includes(g)) out.push({ name: g, tiles: ts });
  }
  return out;
});

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
    <div class="sechead">
      <h2 class="sect">Key metrics</h2>
      <button class="edit" @click="router.push('/settings')">Edit</button>
    </div>

    <div v-for="g in grouped" :key="g.name" class="group">
      <h3 class="ghead">{{ g.name }}</h3>
      <div class="grid">
      <button v-for="t in g.tiles" :key="t.key" class="cell"
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
          :span="INTERMITTENT.has(t.key) ? 14 : 7"
          :accent="ACCENT[t.key] ?? '#28e6ff'"
          :delta="t.delta"
          :higher-is-better="t.higher_is_better"
        />
      </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.km { margin: 18px 0; max-width: 640px; }
.sechead {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 4px;
}
.edit {
  background: none; border: 0; cursor: pointer;
  color: #8ab4f8; font-size: .82rem; padding: 4px 2px;
}
.group { margin-bottom: 14px; }
.ghead {
  font-size: 1rem; font-weight: 500; color: #e9edf2;
  margin: 18px 0 10px; letter-spacing: 0;
}
.sect {
  font-size: 1.35rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 12px; letter-spacing: -0.2px;
}
/* Exactly two columns, matching the phone and the reference. `auto-fill`
   opened 4-6 columns on a desktop dashboard, so the two surfaces laid the
   same data out differently and a lone card left a hole several columns
   wide. minmax(0,1fr) rather than 1fr so the long "139/92 mmHg" value
   can't push its column past its share. */
/* Rows stretch and the chip anchors to the card bottom, so a card with a
   shorter chart (weight and blood pressure are measured weekly, so theirs
   is often empty) ends level with its neighbour instead of stopping short.
   Sizing to content left visibly ragged bottoms across every row. */
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: stretch;
}

/* A lone trailing card spans the row instead of sitting beside a hole.
   Hole-proof for any tile count — which matters because hiding a tile in
   Settings changes the count at runtime. */
.grid > .cell:last-child:nth-child(odd) { grid-column: 1 / -1; }
.cell {
  padding: 0; border: 0; background: none; cursor: pointer;
  text-align: left; display: block; min-width: 0;
}
</style>
