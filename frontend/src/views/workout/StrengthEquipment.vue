<script setup lang="ts">
/**
 * /workout/strength/equipment — full-page editor for the user's available gear.
 *
 * Edits the single-row user_equipment table. The strength workout
 * generator (Phase 3) reads this to filter the catalog and round
 * weights to plates the user can actually load.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import Card from "@/components/Card.vue";
import type { StrengthEquipment } from "@/api/types";

const ALL_DB_PAIRS_LB = [5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 32.5,
                         35, 37.5, 40, 42.5, 45, 47.5, 50, 55, 60, 65, 70, 75, 80,
                         85, 90, 95, 100];
const ALL_WRIST_LB = [0.5, 0.75, 1, 1.5, 2, 2.5, 3, 5];

const equip = ref<StrengthEquipment | null>(null);
const unit = ref<"lb" | "kg">("lb");
const updatedAt = ref<string | null>(null);
const saving = ref(false);
const result = ref<string>("");

function defaultEquip(): StrengthEquipment {
  return {
    dumbbells: {
      type: "fixed_pairs", pairs_lb: [], min_lb: null, max_lb: null,
      increment_lb: null,
    },
    wrist_weights_lb: [],
    bench: { flat: false, incline: false, decline: false },
    barbell: false, barbell_plates_lb: [],
    squat_rack: false, pull_up_bar: false,
    cable_stack: false, cable_increment_lb: null,
    kettlebells_lb: [],
    resistance_bands: false,
    bodyweight: true,
  };
}

async function load() {
  if (!queryToken.value) return;
  try {
    const r = await api.strengthEquipment();
    equip.value = r.payload;
    unit.value = r.unit;
    updatedAt.value = r.updated_at;
  } catch (e) {
    result.value = `Load failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function save() {
  if (!equip.value) return;
  saving.value = true;
  result.value = "";
  try {
    await api.putStrengthEquipment({ payload: equip.value, unit: unit.value });
    result.value = "Saved.";
    await load();
  } catch (e) {
    result.value = `Save failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    saving.value = false;
  }
}

function togglePair(lb: number) {
  if (!equip.value) return;
  const arr = equip.value.dumbbells.pairs_lb;
  const i = arr.indexOf(lb);
  if (i >= 0) arr.splice(i, 1);
  else { arr.push(lb); arr.sort((a, b) => a - b); }
}
function isPairOwned(lb: number): boolean {
  return equip.value?.dumbbells.pairs_lb.includes(lb) ?? false;
}

function toggleWrist(lb: number) {
  if (!equip.value) return;
  const arr = equip.value.wrist_weights_lb;
  const i = arr.indexOf(lb);
  if (i >= 0) arr.splice(i, 1);
  else { arr.push(lb); arr.sort((a, b) => a - b); }
}
function isWristOwned(lb: number): boolean {
  return equip.value?.wrist_weights_lb.includes(lb) ?? false;
}

const ownedSummary = computed(() => {
  if (!equip.value) return "";
  const e = equip.value;
  const parts: string[] = [];
  if (e.dumbbells.type === "fixed_pairs" && e.dumbbells.pairs_lb.length) {
    const p = e.dumbbells.pairs_lb;
    parts.push(`${p.length} DB pairs (${p[0]}–${p[p.length - 1]} lb)`);
  }
  if (e.wrist_weights_lb.length) {
    parts.push(`wrist ${e.wrist_weights_lb.join("/")} lb`);
  }
  const bench = [
    e.bench.flat ? "flat" : null,
    e.bench.incline ? "incline" : null,
    e.bench.decline ? "decline" : null,
  ].filter(Boolean).join("+");
  if (bench) parts.push(`bench: ${bench}`);
  if (e.barbell) parts.push("barbell");
  if (e.pull_up_bar) parts.push("pull-up bar");
  if (e.cable_stack) parts.push("cable");
  if (e.kettlebells_lb.length) parts.push(`kb ${e.kettlebells_lb.join("/")} lb`);
  if (e.resistance_bands) parts.push("bands");
  return parts.join(" · ") || "(nothing yet)";
});

onMounted(() => { equip.value = defaultEquip(); load(); });
</script>

<template>
  <main class="strength-equipment">
    <h1>Strength equipment</h1>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load equipment.</p>

    <Card v-else-if="equip" :subtitle="ownedSummary">
      <p class="hint">
        Used by the strength workout generator to filter the exercise catalog
        and round target weights to plates you can actually load. Adding gear
        later (e.g. a doorway pull-up bar) automatically expands the catalog —
        no code change needed.
      </p>

      <h3 class="sub">Dumbbells</h3>
      <div class="db-type">
        <label>
          <input type="radio" value="none" v-model="equip.dumbbells.type" />
          None
        </label>
        <label>
          <input type="radio" value="fixed_pairs" v-model="equip.dumbbells.type" />
          Fixed pairs (e.g. rack of 5–45 lb)
        </label>
        <label>
          <input type="radio" value="adjustable" v-model="equip.dumbbells.type" />
          Adjustable (PowerBlocks, Bowflex, …)
        </label>
      </div>

      <div v-if="equip.dumbbells.type === 'fixed_pairs'" class="chip-grid">
        <button
          v-for="lb in ALL_DB_PAIRS_LB" :key="lb"
          class="chip"
          :class="{ on: isPairOwned(lb) }"
          @click="togglePair(lb)"
        >{{ lb }}</button>
      </div>

      <div v-if="equip.dumbbells.type === 'adjustable'" class="adj-grid">
        <label>Min <input type="number" min="0" step="0.5" v-model.number="equip.dumbbells.min_lb"/></label>
        <label>Max <input type="number" min="0" step="0.5" v-model.number="equip.dumbbells.max_lb"/></label>
        <label>Step <input type="number" min="0.25" step="0.25" v-model.number="equip.dumbbells.increment_lb"/></label>
      </div>

      <h3 class="sub">Wrist weights / micro-loaders</h3>
      <p class="hint">
        Sub-5 lb weights you can strap onto a dumbbell (or wear) to bridge the
        gap between dumbbell pairs. Lets the algorithm prescribe e.g. 27 lb
        instead of "hold at 25" or "jump to 30".
      </p>
      <div class="chip-grid">
        <button
          v-for="lb in ALL_WRIST_LB" :key="lb"
          class="chip small"
          :class="{ on: isWristOwned(lb) }"
          @click="toggleWrist(lb)"
        >{{ lb }} lb</button>
      </div>

      <h3 class="sub">Bench</h3>
      <div class="checks">
        <label><input type="checkbox" v-model="equip.bench.flat"/> Flat</label>
        <label><input type="checkbox" v-model="equip.bench.incline"/> Incline</label>
        <label><input type="checkbox" v-model="equip.bench.decline"/> Decline</label>
      </div>

      <h3 class="sub">Other gear</h3>
      <div class="checks col">
        <label><input type="checkbox" v-model="equip.bodyweight"/> Bodyweight (always)</label>
        <label><input type="checkbox" v-model="equip.pull_up_bar"/> Pull-up bar</label>
        <label><input type="checkbox" v-model="equip.resistance_bands"/> Resistance bands</label>
        <label><input type="checkbox" v-model="equip.barbell"/> Barbell + plates</label>
        <label><input type="checkbox" v-model="equip.squat_rack"/> Squat rack</label>
        <label><input type="checkbox" v-model="equip.cable_stack"/> Cable stack / lat pulldown</label>
      </div>

      <div class="actions">
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? "Saving…" : "Save equipment" }}
        </button>
        <span v-if="result" class="hint">{{ result }}</span>
        <span v-else-if="updatedAt" class="hint">Last updated {{ new Date(updatedAt).toLocaleString() }}</span>
      </div>
    </Card>

    <p v-else class="hint">Loading…</p>
  </main>
</template>

<style scoped>
.strength-equipment { max-width: 720px; }
h1 { margin: 0 0 0.6rem; }
.hint { color: var(--muted); font-size: 0.85rem; margin: 0.4rem 0; }
.sub { font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); margin: 1rem 0 0.4rem; font-weight: 600; }
.db-type { display: flex; flex-wrap: wrap; gap: 0.6rem 1rem; margin: 0.4rem 0 0.6rem; }
.db-type label { display: flex; align-items: center; gap: 0.3rem; font-size: 0.85rem; }
.chip-grid { display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0.3rem 0 0.5rem; }
.chip {
  padding: 0.32rem 0.6rem; min-width: 2.6rem; border-radius: 6px;
  border: 1px solid var(--line); background: var(--bg-2);
  color: var(--muted); font-size: 0.82rem; cursor: pointer;
  font-family: 'Geist Mono', ui-monospace, monospace;
}
.chip.small { font-size: 0.75rem; padding: 0.28rem 0.5rem; }
.chip:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.chip.on {
  background: var(--accent, #ef4444); color: #fff;
  border-color: var(--accent, #ef4444); font-weight: 600;
}
.adj-grid { display: flex; gap: 0.8rem; flex-wrap: wrap; margin: 0.4rem 0 0.6rem; }
.adj-grid label { font-size: 0.82rem; color: var(--muted); }
.adj-grid input { width: 4.5rem; margin-left: 0.3rem; }
.checks { display: flex; flex-wrap: wrap; gap: 0.6rem 1rem; margin: 0.4rem 0; }
.checks.col { flex-direction: column; gap: 0.4rem; }
.checks label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; }
.actions { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.8rem; }
.actions .primary {
  background: var(--accent, #ef4444); color: #fff; border: none;
  padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer;
}
.actions .primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
