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
import type { StrengthEquipment, StrengthExercise, ProgramLiftState } from "@/api/types";

const ALL_DB_PAIRS_LB = [5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30, 32.5,
                         35, 37.5, 40, 42.5, 45, 47.5, 50, 55, 60, 65, 70, 75, 80,
                         85, 90, 95, 100];
const ALL_WRIST_LB = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5];

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
    cardio_rower: false,
    cardio_bike_indoor: false,
    cardio_mtb_outdoor: false,
    cardio_road_bike: false,
    cardio_treadmill: false,
    training: {
      level: "intermediate",
      days_per_week: 3,
      split_preference: "auto",
      workout_minutes: 50,
    },
  };
}

function ensureTraining(e: StrengthEquipment): NonNullable<StrengthEquipment["training"]> {
  if (!e.training) {
    e.training = {
      level: "intermediate", days_per_week: 3,
      split_preference: "auto", workout_minutes: 50,
      include_mobility: true, yoga_on_rest_days: true,
    };
  }
  return e.training;
}

// PROG-1 — program mode config. Scheme defaults mirror the backend
// PROGRAM_SCHEME_DEFAULTS so a lift added here matches what the server
// would seed.
const SCHEME_LABELS: Record<ProgramLiftState["scheme"], string> = {
  greyskull: "Greyskull LP", linear: "Linear", double: "Double progression",
};
const SCHEME_DEFAULTS: Record<ProgramLiftState["scheme"], Partial<ProgramLiftState>> = {
  greyskull: { sets: 3, reps_low: 5, reps_high: 5, amrap_last_set: true,
               increment_lb: 5, fails_before_deload: 1, deload_pct: 0.10, rest_s: 180 },
  linear:    { sets: 3, reps_low: 5, reps_high: 5, amrap_last_set: false,
               increment_lb: 5, fails_before_deload: 3, deload_pct: 0.10, rest_s: 180 },
  double:    { sets: 3, reps_low: 8, reps_high: 12, amrap_last_set: false,
               increment_lb: 5, fails_before_deload: 3, deload_pct: 0.10, rest_s: 150 },
};

const catalog = ref<StrengthExercise[]>([]);
const addLiftId = ref<string>("");

function ensureProgram(e: StrengthEquipment): NonNullable<NonNullable<StrengthEquipment["training"]>["program"]> {
  const t = ensureTraining(e);
  if (!t.program) t.program = { enabled: false, lifts: [] };
  return t.program;
}

// Candidate lifts for program mode: compound, weighted (dumbbell/barbell/
// cable), non-timed. These are the movements that progress by fixed
// increments — the core barbell/dumbbell lifts a program is built on.
const programCandidates = computed<StrengthExercise[]>(() =>
  catalog.value
    .filter((x) =>
      x.is_compound &&
      !x.is_timed &&
      (x.equipment.includes("dumbbell") || x.equipment.includes("barbell") ||
       x.equipment.includes("cable")))
    .sort((a, b) => a.name.localeCompare(b.name)),
);

// Candidates not already in the program (for the add dropdown).
const availableToAdd = computed<StrengthExercise[]>(() => {
  const inUse = new Set((equip.value?.training?.program?.lifts ?? []).map((l) => l.exercise_id));
  return programCandidates.value.filter((x) => !inUse.has(x.id));
});

function exName(id: string): string {
  return catalog.value.find((x) => x.id === id)?.name ?? id;
}

function addProgramLift() {
  if (!equip.value || !addLiftId.value) return;
  const prog = ensureProgram(equip.value);
  const scheme: ProgramLiftState["scheme"] = "linear";
  prog.lifts.push({
    exercise_id: addLiftId.value,
    scheme,
    current_weight_lb: null,
    ...SCHEME_DEFAULTS[scheme],
  } as ProgramLiftState);
  addLiftId.value = "";
}

function setScheme(lift: ProgramLiftState, scheme: ProgramLiftState["scheme"]) {
  lift.scheme = scheme;
  Object.assign(lift, SCHEME_DEFAULTS[scheme]);
}

function removeProgramLift(idx: number) {
  equip.value?.training?.program?.lifts.splice(idx, 1);
}

async function load() {
  if (!queryToken.value) return;
  try {
    const [r, ex] = await Promise.all([
      api.strengthEquipment(),
      api.strengthExercises().catch(() => ({ count: 0, exercises: [] as StrengthExercise[] })),
    ]);
    equip.value = r.payload;
    unit.value = r.unit;
    updatedAt.value = r.updated_at;
    catalog.value = ex.exercises;
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
const wristInput = ref<string>("");
function addWristCustom() {
  if (!equip.value) return;
  const v = Number(wristInput.value);
  if (!isFinite(v) || v <= 0) return;
  const rounded = Math.round(v * 4) / 4;  // 0.25 lb resolution
  if (rounded <= 0) { wristInput.value = ""; return; }  // sub-0.125 rounds to 0 — ignore
  if (!equip.value.wrist_weights_lb.includes(rounded)) {
    equip.value.wrist_weights_lb.push(rounded);
    equip.value.wrist_weights_lb.sort((a, b) => a - b);
  }
  wristInput.value = "";
}
function removeWrist(lb: number) {
  if (!equip.value) return;
  const i = equip.value.wrist_weights_lb.indexOf(lb);
  if (i >= 0) equip.value.wrist_weights_lb.splice(i, 1);
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
    <h1>Workout equipment</h1>

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
          v-for="lb in ALL_WRIST_LB" :key="'preset-' + lb"
          class="chip small"
          :class="{ on: isWristOwned(lb) }"
          @click="toggleWrist(lb)"
        >{{ lb }} lb</button>
        <button
          v-for="lb in equip?.wrist_weights_lb.filter(x => !ALL_WRIST_LB.includes(x)) ?? []"
          :key="'custom-' + lb"
          class="chip small on"
          @click="removeWrist(lb)"
          title="Click to remove"
        >{{ lb }} lb ×</button>
      </div>
      <div class="wrist-add">
        <input
          type="number" min="0.25" step="0.25"
          v-model="wristInput" placeholder="custom lb"
          @keydown.enter.prevent="addWristCustom"
        />
        <button class="ghost" @click="addWristCustom" :disabled="!wristInput">
          Add custom
        </button>
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

      <h3 class="sub">Cardio modalities</h3>
      <p class="hint">
        Suggested on cardio days. Outdoor options are picked first when
        available. Rowing logs via Concept2 ERG; biking via Strava —
        these checkboxes don't change the data pipeline, just the
        prescription text.
      </p>
      <div class="checks col">
        <label><input type="checkbox" v-model="equip.cardio_rower"/> Rower (Concept2)</label>
        <label><input type="checkbox" v-model="equip.cardio_mtb_outdoor"/> Mountain bike (outdoors)</label>
        <label><input type="checkbox" v-model="equip.cardio_road_bike"/> Road bike</label>
        <label><input type="checkbox" v-model="equip.cardio_bike_indoor"/> Indoor bike / trainer</label>
        <label><input type="checkbox" v-model="equip.cardio_treadmill"/> Treadmill</label>
      </div>

      <h3 class="sub">Training preferences</h3>
      <p class="hint">
        Drive how the generator picks today's plan. "Auto" split maps to
        Full Body for 2–3 days/week, Upper-Lower for 4, Push-Pull-Legs
        for 5–6.
      </p>

      <div class="train-grid">
        <label class="train-row">
          <span>Experience level</span>
          <div class="seg">
            <button v-for="lvl in (['beginner','intermediate','advanced'] as const)" :key="lvl"
                    :class="{ on: ensureTraining(equip).level === lvl }"
                    @click="ensureTraining(equip).level = lvl">{{ lvl }}</button>
          </div>
        </label>

        <label class="train-row">
          <span>Days per week</span>
          <div class="seg">
            <button v-for="n in [2,3,4,5,6]" :key="n"
                    :class="{ on: ensureTraining(equip).days_per_week === n }"
                    @click="ensureTraining(equip).days_per_week = n">{{ n }}</button>
          </div>
        </label>

        <label class="train-row">
          <span>Split preference</span>
          <div class="seg">
            <button v-for="s in (['auto','full_body','upper_lower','ppl'] as const)" :key="s"
                    :class="{ on: ensureTraining(equip).split_preference === s }"
                    @click="ensureTraining(equip).split_preference = s">{{ s.replace('_',' ') }}</button>
          </div>
        </label>

        <label class="train-row">
          <span>Goal</span>
          <div class="seg">
            <button v-for="g in (['strength','hypertrophy','general'] as const)" :key="g"
                    :class="{ on: (ensureTraining(equip).goal ?? 'hypertrophy') === g }"
                    @click="ensureTraining(equip).goal = g">{{ g }}</button>
          </div>
        </label>
        <p class="hint" style="margin: -0.4rem 0 0.6rem;">
          <strong>Strength</strong>: 3–6 reps, 3–4 min rest, heavier loads.
          <strong>Hypertrophy</strong>: 6–12 reps, 60–120 s rest, balanced —
          recommended for dumbbell-only training. <strong>General</strong>:
          8–15 reps, 30–75 s rest, time-efficient.
        </p>

        <label class="train-row">
          <span>Exercises per workout</span>
          <label class="auto-chk">
            <input type="checkbox"
                   :checked="ensureTraining(equip).exercises_per_workout == null"
                   @change="ensureTraining(equip).exercises_per_workout = ($event.target as HTMLInputElement).checked ? null : 6"/>
            Auto
          </label>
        </label>
        <div v-if="ensureTraining(equip).exercises_per_workout != null" class="train-row slider-row">
          <input type="range" min="4" max="8" step="1"
                 :value="ensureTraining(equip).exercises_per_workout ?? 6"
                 @input="ensureTraining(equip).exercises_per_workout = parseInt(($event.target as HTMLInputElement).value, 10)"/>
          <span class="mono">{{ ensureTraining(equip).exercises_per_workout }}</span>
        </div>
        <p class="hint" style="margin: -0.4rem 0 0.6rem;">
          More exercises adds accessory work for your under-trained muscles
          (core favored). <strong>Auto</strong> sizes each day to its split
          plus smart finishers. Mobility poses don't count toward this.
        </p>

        <label class="train-row toggle">
          <input type="checkbox"
                 :checked="ensureTraining(equip).include_mobility !== false"
                 @change="ensureTraining(equip).include_mobility = ($event.target as HTMLInputElement).checked"/>
          <span class="toggle-text">
            <strong>Mobility cool-down</strong>
            <span class="hint">Adds 2 yoga poses (~30 s holds) to the end of each strength workout.</span>
          </span>
        </label>

        <label class="train-row toggle">
          <input type="checkbox"
                 :checked="ensureTraining(equip).yoga_on_rest_days !== false"
                 @change="ensureTraining(equip).yoga_on_rest_days = ($event.target as HTMLInputElement).checked"/>
          <span class="toggle-text">
            <strong>Yoga on rest days</strong>
            <span class="hint">Generates a 5-pose yoga flow (~45 s holds) instead of leaving recovery days empty.</span>
          </span>
        </label>
      </div>

      <!-- PROG-1 — program mode -->
      <h3 class="sub">Program mode</h3>
      <p class="hint" style="margin: 0 0 0.5rem;">
        Put chosen core lifts on a fixed linear-progression scheme. Weight
        advances by set rules (e.g. +5 lb per session, AMRAP last set,
        deload on failure) instead of the recovery-aware generator. Other
        exercises are unaffected.
      </p>
      <div class="train-grid">
        <label class="train-row toggle">
          <input type="checkbox"
                 :checked="ensureProgram(equip).enabled"
                 @change="ensureProgram(equip).enabled = ($event.target as HTMLInputElement).checked"/>
          <span class="toggle-text">
            <strong>Enable program mode</strong>
            <span class="hint">When on, the lifts below are pinned into your plan whenever their movement pattern is trained that day.</span>
          </span>
        </label>

        <template v-if="ensureProgram(equip).enabled">
          <div v-for="(lift, idx) in ensureProgram(equip).lifts" :key="lift.exercise_id" class="prog-lift">
            <div class="prog-lift-head">
              <strong>{{ exName(lift.exercise_id) }}</strong>
              <button class="link-danger" @click="removeProgramLift(idx)">Remove</button>
            </div>
            <div class="seg">
              <button v-for="s in (['greyskull','linear','double'] as const)" :key="s"
                      :class="{ on: lift.scheme === s }"
                      @click="setScheme(lift, s)">{{ SCHEME_LABELS[s] }}</button>
            </div>
            <label class="prog-weight">
              <span>Working weight (lb)</span>
              <input type="number" min="0" step="2.5" placeholder="auto"
                     :value="lift.current_weight_lb ?? ''"
                     @input="lift.current_weight_lb = ($event.target as HTMLInputElement).value === '' ? null : parseFloat(($event.target as HTMLInputElement).value)"/>
            </label>
            <span class="hint prog-detail">
              {{ lift.scheme === 'greyskull'
                  ? `${lift.sets}×${lift.reps_low}, last set AMRAP · +${lift.increment_lb} lb (double at ${(lift.reps_low ?? 5) * 2}+) · 1 miss → deload`
                  : lift.scheme === 'double'
                  ? `${lift.sets}×${lift.reps_low}-${lift.reps_high} · +${lift.increment_lb} lb once every set hits ${lift.reps_high}`
                  : `${lift.sets}×${lift.reps_low} · +${lift.increment_lb} lb/session · ${lift.fails_before_deload} misses → deload` }}
            </span>
          </div>

          <p v-if="!ensureProgram(equip).lifts.length" class="hint">No lifts yet — add your core barbell/dumbbell movements below.</p>

          <div class="prog-add">
            <select v-model="addLiftId">
              <option value="">Add a lift…</option>
              <option v-for="x in availableToAdd" :key="x.id" :value="x.id">{{ x.name }}</option>
            </select>
            <button class="ghost" :disabled="!addLiftId" @click="addProgramLift">Add</button>
          </div>
        </template>
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
.wrist-add { display: flex; gap: 0.4rem; align-items: center; margin: 0.4rem 0 0.8rem; }
.wrist-add input { width: 6rem; padding: 0.3rem 0.5rem; font-size: 0.85rem; }
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

.train-grid { display: flex; flex-direction: column; gap: 0.7rem; margin: 0.4rem 0 0.6rem; }
.train-row {
  display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap;
  font-size: 0.85rem; color: var(--text);
}
.train-row > span:first-child { min-width: 11rem; color: var(--muted); }
.train-row.toggle { align-items: flex-start; }
.train-row.toggle > input[type="checkbox"] { margin-top: 0.25rem; }
.train-row.toggle .toggle-text {
  display: flex; flex-direction: column; gap: 0.2rem;
  min-width: 0;
}
.train-row.toggle .toggle-text strong {
  color: var(--text); font-weight: 600; font-size: 0.9rem;
}
.train-row.toggle .toggle-text .hint {
  margin: 0; font-size: 0.78rem; color: var(--muted);
}
.muted-suffix { color: var(--muted); font-size: 0.8rem; }
.auto-chk { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.82rem; color: var(--muted); }
.slider-row input[type="range"] { flex: 1; min-width: 8rem; }
.slider-row .mono { min-width: 1.4rem; text-align: center; font-weight: 700; color: var(--text); font-family: 'Geist Mono', ui-monospace, monospace; }
.seg { display: inline-flex; gap: 0.25rem; flex-wrap: wrap; }
.seg button {
  padding: 0.32rem 0.7rem; font-size: 0.8rem;
  border-radius: 5px; border: 1px solid var(--line); background: var(--bg-2);
  color: var(--muted); cursor: pointer;
  font-family: 'Geist Mono', ui-monospace, monospace; text-transform: capitalize;
}
.seg button:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.seg button.on {
  background: var(--accent, #ef4444); color: #fff; font-weight: 600;
  border-color: var(--accent, #ef4444);
}

/* PROG-1 — program-mode lift cards */
.prog-lift {
  display: flex; flex-direction: column; gap: 0.45rem;
  padding: 0.7rem 0.8rem; border: 1px solid var(--line);
  border-radius: 8px; background: var(--bg-2);
}
.prog-lift-head { display: flex; justify-content: space-between; align-items: center; }
.prog-lift-head strong { font-size: 0.95rem; }
.link-danger {
  background: none; border: none; color: #ef4444; cursor: pointer;
  font-size: 0.78rem; padding: 0.1rem 0.2rem;
}
.link-danger:hover { text-decoration: underline; }
.prog-weight { display: flex; align-items: center; gap: 0.6rem; font-size: 0.82rem; }
.prog-weight > span { min-width: 9rem; color: var(--muted); }
.prog-weight input {
  width: 6rem; padding: 0.3rem 0.5rem; border-radius: 5px;
  border: 1px solid var(--line); background: var(--bg); color: var(--text);
  font-family: 'Geist Mono', ui-monospace, monospace;
}
.prog-detail { font-family: 'Geist Mono', ui-monospace, monospace; }
.prog-add { display: flex; gap: 0.5rem; align-items: center; }
.prog-add select {
  flex: 1; padding: 0.35rem 0.5rem; border-radius: 5px;
  border: 1px solid var(--line); background: var(--bg-2); color: var(--text);
}

/* ===== Vitality Neon — scoped, neon-theme-only overrides ===== */
html[data-theme="neon"] .strength-equipment {
  --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-cyan: #28e6ff; --rn-lime: #5dff3b; --rn-mag: #ff3ad8;
  --rn-amber: #ffb52e; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 1.25rem 1.5rem 2rem;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}

html[data-theme="neon"] .strength-equipment h1 {
  color: var(--rn-ink); letter-spacing: -0.5px;
}

/* Section sub-headers + hints → neon muted, Space Grotesk caps */
html[data-theme="neon"] .strength-equipment .sub {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  letter-spacing: 0.12em; color: var(--rn-mut);
}
html[data-theme="neon"] .strength-equipment .hint { color: var(--rn-mut); }
html[data-theme="neon"] .strength-equipment .hint strong { color: var(--rn-ink); }

/* ---- Selectable chips (DB pairs) → neon card surface, lime when owned ---- */
html[data-theme="neon"] .strength-equipment .chip {
  background: var(--rn-card); border-color: #21243480;
  color: var(--rn-mut);
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  border-radius: 9px;
}
html[data-theme="neon"] .strength-equipment .chip:hover {
  color: var(--rn-ink); border-color: rgba(40, 230, 255, 0.45);
}
html[data-theme="neon"] .strength-equipment .chip.on {
  background: rgba(93, 255, 59, 0.14); color: var(--rn-lime);
  border-color: rgba(93, 255, 59, 0.55);
  text-shadow: 0 0 8px rgba(93, 255, 59, 0.40);
}

/* ---- Micro-loader / wrist-weight chips → lime (owned = good/completed,
       matching the DB-pair chips; magenta is reserved for sleep/sober) ---- */
html[data-theme="neon"] .strength-equipment .chip.small.on {
  background: rgba(93, 255, 59, 0.14); color: var(--rn-lime);
  border-color: rgba(93, 255, 59, 0.55);
  text-shadow: 0 0 8px rgba(93, 255, 59, 0.40);
}
html[data-theme="neon"] .strength-equipment .wrist-add input,
html[data-theme="neon"] .strength-equipment .adj-grid input {
  background: var(--rn-card); border: 1px solid #21243480;
  color: var(--rn-ink); border-radius: 8px;
}
html[data-theme="neon"] .strength-equipment .adj-grid label,
html[data-theme="neon"] .strength-equipment .auto-chk,
html[data-theme="neon"] .strength-equipment .train-row > span:first-child {
  color: var(--rn-mut);
}

/* ---- Ghost button (Add custom) ---- */
html[data-theme="neon"] .strength-equipment .ghost {
  background: rgba(40, 230, 255, 0.08); color: var(--rn-cyan);
  border: 1px solid rgba(40, 230, 255, 0.32); border-radius: 8px;
}

/* ---- Status indicators: radios / checkboxes / range tint to neon cyan ---- */
html[data-theme="neon"] .strength-equipment input[type="checkbox"],
html[data-theme="neon"] .strength-equipment input[type="radio"],
html[data-theme="neon"] .strength-equipment input[type="range"] {
  accent-color: var(--rn-cyan);
}
html[data-theme="neon"] .strength-equipment .db-type label,
html[data-theme="neon"] .strength-equipment .checks label,
html[data-theme="neon"] .strength-equipment .train-row {
  color: var(--rn-ink);
}
html[data-theme="neon"] .strength-equipment .train-row.toggle .toggle-text strong {
  color: var(--rn-ink);
}
html[data-theme="neon"] .strength-equipment .slider-row .mono {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  color: var(--rn-cyan); text-shadow: 0 0 8px rgba(40, 230, 255, 0.40);
}

/* ---- Segmented toggles (training prefs) → cyan when selected ---- */
html[data-theme="neon"] .strength-equipment .seg button {
  background: var(--rn-card); border-color: #21243480;
  color: var(--rn-mut);
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
}
html[data-theme="neon"] .strength-equipment .seg button:hover {
  color: var(--rn-ink); border-color: rgba(40, 230, 255, 0.45);
}
html[data-theme="neon"] .strength-equipment .seg button.on {
  background: rgba(40, 230, 255, 0.16); color: var(--rn-cyan);
  border-color: rgba(40, 230, 255, 0.55);
  text-shadow: 0 0 8px rgba(40, 230, 255, 0.40);
}

/* ---- Primary save button → cyan with glow ---- */
html[data-theme="neon"] .strength-equipment .actions .primary {
  background: var(--rn-cyan); color: #0f1118; font-weight: 700;
  box-shadow: 0 0 16px rgba(40, 230, 255, 0.40);
}
</style>
