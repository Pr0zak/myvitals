<script setup lang="ts">
/**
 * /workout/strength/today — full plan view that handles every workout state
 * via one component: planned (preview + start), in_progress (active workout
 * with set logging + rest timer), completed (summary).
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Play, Pause, RotateCw, Plus, SkipForward, Replace as SwapIcon } from "lucide-vue-next";
import { api } from "@/api/client";
import { apiBase, queryToken } from "@/config";
import Card from "@/components/Card.vue";
import type { StrengthExercise, StrengthWorkoutDetail, StrengthWorkoutExercise } from "@/api/types";

const router = useRouter();
const workout = ref<StrengthWorkoutDetail | null>(null);
const recovery = ref<Awaited<ReturnType<typeof api.strengthRecovery>> | null>(null);
const catalogById = ref<Record<string, StrengthExercise>>({});
const loading = ref(true);
const error = ref<string>("");
const busy = ref<string>(""); // e.g. "regen", "complete", "skip-3"

// Set-logging state, keyed by `${wexId}-${setNum}`
interface SetEntry {
  weight: string;   // string so empty input doesn't show "0"
  reps: string;
  rating: number | null;
}
const setEntries = ref<Record<string, SetEntry>>({});

// Swap-exercise modal state
const swapWexId = ref<number | null>(null);
const swapBusy = ref(false);
const swapError = ref<string>("");

function openSwap(wexId: number) {
  swapError.value = "";
  swapWexId.value = wexId;
}
function closeSwap() { swapWexId.value = null; }

const swapAlternatives = computed<StrengthExercise[]>(() => {
  if (swapWexId.value === null || !workout.value) return [];
  const wex = workout.value.exercises.find((x) => x.id === swapWexId.value);
  if (!wex) return [];
  const current = catalogById.value[wex.exercise_id];
  if (!current) return [];
  // In-workout already, exclude
  const inWorkout = new Set(workout.value.exercises.map((x) => x.exercise_id));
  return Object.values(catalogById.value)
    .filter((e) =>
      e.id !== wex.exercise_id
      && !inWorkout.has(e.id)
      && (e.primary_muscle === current.primary_muscle
          || e.movement_pattern === current.movement_pattern),
    )
    .sort((a, b) => {
      // Prefer same movement pattern first, then alphabetical
      const aPat = a.movement_pattern === current.movement_pattern ? 0 : 1;
      const bPat = b.movement_pattern === current.movement_pattern ? 0 : 1;
      return aPat - bPat || a.name.localeCompare(b.name);
    })
    .slice(0, 12);
});

async function applySwap(newExId: string) {
  if (swapWexId.value === null) return;
  swapBusy.value = true;
  swapError.value = "";
  try {
    await api.swapStrengthExercise(swapWexId.value, newExId);
    await loadAll();
    closeSwap();
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      swapError.value = resp?.data?.detail ?? `HTTP ${resp?.status}`;
    } else {
      swapError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    swapBusy.value = false;
  }
}

// AI review (optional, on-demand)
const review = ref<Awaited<ReturnType<typeof api.aiStrengthReview>>["review"] | null>(null);
const reviewLoading = ref(false);
const reviewError = ref<string>("");
const reviewCached = ref(false);
const reviewModel = ref<string>("");

async function loadReview() {
  if (!workout.value) return;
  reviewLoading.value = true;
  reviewError.value = "";
  try {
    const r = await api.aiStrengthReview(workout.value.id);
    review.value = r.review;
    reviewCached.value = r.cached;
    reviewModel.value = r.model;
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      reviewError.value = resp?.data?.detail ?? `HTTP ${resp?.status}`;
    } else {
      reviewError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    reviewLoading.value = false;
  }
}

// Rest timer
const restRemaining = ref<number | null>(null);  // seconds
const restTotal = ref<number>(0);
let restHandle: number | null = null;

function startRest(seconds: number) {
  stopRest();
  restRemaining.value = seconds;
  restTotal.value = seconds;
  restHandle = window.setInterval(() => {
    if (restRemaining.value === null) return;
    restRemaining.value -= 1;
    if (restRemaining.value <= 0) stopRest();
  }, 1000);
}
function stopRest() {
  if (restHandle !== null) { clearInterval(restHandle); restHandle = null; }
  restRemaining.value = null;
}
function addRest(s: number) {
  if (restRemaining.value === null) return;
  restRemaining.value += s;
}
onUnmounted(stopRest);

async function loadAll() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const [w, r, cat] = await Promise.all([
      api.strengthToday(),
      api.strengthRecovery().catch(() => null),
      api.strengthExercises().catch(() => ({ count: 0, exercises: [] as StrengthExercise[] })),
    ]);
    workout.value = w;
    recovery.value = r;
    catalogById.value = Object.fromEntries(cat.exercises.map((e) => [e.id, e]));
    // Pre-fill set entries from any already-logged sets so the user can
    // resume without losing data
    if (w) {
      for (const ex of w.exercises) {
        for (const s of ex.sets) {
          setEntries.value[`${ex.id}-${s.set_number}`] = {
            weight: s.actual_weight_lb?.toString() ?? "",
            reps: s.actual_reps?.toString() ?? "",
            rating: s.rating,
          };
        }
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function ex(slug: string): StrengthExercise | undefined { return catalogById.value[slug]; }
function exName(slug: string): string {
  return ex(slug)?.name ?? slug.replace(/_/g, " ");
}
function imageUrl(slug: string, side: 0 | 1 = 0): string | null {
  const cat = ex(slug);
  if (!cat) return null;
  const path = side === 0 ? cat.image_front : cat.image_side;
  if (!path) return null;
  const base = (apiBase.value || "/api").replace(/\/$/, "");
  return `${base}${path}`;
}
function youtubeUrl(slug: string): string {
  const q = encodeURIComponent(`${exName(slug)} form`);
  return `https://www.youtube.com/results?search_query=${q}`;
}

async function regenerate(force = false) {
  busy.value = "regen";
  error.value = "";
  try {
    workout.value = await api.regenerateStrengthToday(force);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

function entryKey(wexId: number, setNum: number) { return `${wexId}-${setNum}`; }
function entry(wexId: number, setNum: number, target: number, targetWeight: number | null): SetEntry {
  const key = entryKey(wexId, setNum);
  if (!setEntries.value[key]) {
    setEntries.value[key] = {
      weight: targetWeight?.toString() ?? "",
      reps: target.toString(),
      rating: null,
    };
  }
  return setEntries.value[key];
}
function setRating(wexId: number, setNum: number, r: number) {
  const key = entryKey(wexId, setNum);
  if (!setEntries.value[key]) setEntries.value[key] = { weight: "", reps: "", rating: null };
  setEntries.value[key].rating = r;
}

function isSetLogged(wex: StrengthWorkoutExercise, setNum: number): boolean {
  return wex.sets.some((s) => s.set_number === setNum && (s.actual_reps != null || s.skipped));
}

function isExerciseDone(wex: StrengthWorkoutExercise): boolean {
  for (let n = 1; n <= wex.target_sets; n++) {
    if (!isSetLogged(wex, n)) return false;
  }
  return true;
}

const completedSetsCount = computed(() => {
  if (!workout.value) return 0;
  let n = 0;
  for (const ex of workout.value.exercises) {
    for (const s of ex.sets) if (s.actual_reps != null && !s.skipped) n++;
  }
  return n;
});

const totalSetsCount = computed(() =>
  workout.value?.exercises.reduce((acc, ex) => acc + ex.target_sets, 0) ?? 0
);

const currentExercise = computed(() => {
  if (!workout.value) return null;
  return workout.value.exercises.find((ex) => !isExerciseDone(ex)) ?? null;
});

async function logSet(wex: StrengthWorkoutExercise, setNum: number, skipped = false) {
  const e = entry(wex.id, setNum, wex.target_reps_low, wex.target_weight_lb);
  busy.value = `set-${wex.id}-${setNum}`;
  try {
    await api.logStrengthSet({
      workout_exercise_id: wex.id,
      set_number: setNum,
      target_weight_lb: wex.target_weight_lb,
      target_reps: wex.target_reps_low,
      actual_weight_lb: skipped ? null : (parseFloat(e.weight) || null),
      actual_reps: skipped ? null : (parseInt(e.reps, 10) || null),
      rating: skipped ? null : e.rating,
      skipped,
    });
    if (!skipped) {
      // Start rest timer
      const rest = wex.target_rest_s;
      startRest(rest);
    }
    await loadAll();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = "";
  }
}

async function completeWorkout() {
  if (!workout.value) return;
  busy.value = "complete";
  try {
    await api.patchStrengthWorkout(workout.value.id, {
      status: "completed",
      completed_at: new Date().toISOString(),
    });
    await loadAll();
    stopRest();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

function fmtRest(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

onMounted(loadAll);
</script>

<template>
  <main class="strength-today">
    <h1>
      Today's strength
      <small v-if="workout">· {{ workout.split_focus.replace('_', ' ') }}</small>
    </h1>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load today's plan.</p>
    <p v-else-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <!-- Rest day card -->
    <Card v-else-if="!workout && recovery?.rest_day_recommended" title="Rest day recommended">
      <p class="big">{{ recovery.rest_day_reason }}.</p>
      <p class="hint">
        Recovery {{ Math.round(recovery.recovery_score ?? 0) }} ·
        sleep {{ recovery.sleep_h?.toFixed(1) ?? '?' }}h ·
        readiness {{ Math.round(recovery.readiness_score ?? 0) }}
      </p>
      <p class="hint">
        Skipping a heavy session today and resting actively (walk, stretch,
        mobility) will likely produce better results tomorrow than grinding
        through this one. Generate anyway if you have a different read.
      </p>
      <div class="actions">
        <button class="primary" :disabled="busy === 'regen'" @click="regenerate(true)">
          Generate anyway
        </button>
      </div>
    </Card>

    <!-- No plan and no rest-day -->
    <Card v-else-if="!workout" title="No plan generated">
      <button class="primary" :disabled="busy === 'regen'" @click="regenerate(false)">
        Generate today's plan
      </button>
    </Card>

    <!-- Plan exists -->
    <template v-else>
      <Card class="ctx" :flat="true">
        <div class="ctx-row">
          <span><strong>{{ completedSetsCount }}</strong> / {{ totalSetsCount }} sets</span>
          <span v-if="workout.recovery_score_used != null">
            recovery <strong>{{ Math.round(workout.recovery_score_used) }}</strong>
          </span>
          <span v-if="workout.sleep_h_used != null">
            sleep <strong>{{ workout.sleep_h_used.toFixed(1) }}h</strong>
          </span>
          <span class="status">{{ workout.status.replace('_', ' ') }}</span>
        </div>
        <p v-if="workout.notes" class="notes">{{ workout.notes }}</p>
        <div class="actions" v-if="workout.status === 'planned'">
          <button class="ghost" :disabled="busy === 'regen'" @click="regenerate(true)">
            <RotateCw :size="14" /> Regenerate
          </button>
        </div>
      </Card>

      <!-- Rest timer -->
      <div v-if="restRemaining !== null" class="rest-timer" :class="{ done: restRemaining <= 0 }">
        <strong>{{ fmtRest(Math.max(0, restRemaining)) }}</strong>
        <span class="of">of {{ fmtRest(restTotal) }}</span>
        <button class="ghost" @click="addRest(30)"><Plus :size="14" /> 30s</button>
        <button class="ghost" @click="stopRest"><SkipForward :size="14" /> Skip</button>
      </div>

      <!-- Exercise list -->
      <div v-for="(wex, idx) in workout.exercises" :key="wex.id" class="ex-card"
           :class="{ current: currentExercise?.id === wex.id, done: isExerciseDone(wex) }">
        <header>
          <h3>
            {{ idx + 1 }}. {{ exName(wex.exercise_id) }}
            <small v-if="wex.superset_id">· superset {{ wex.superset_id }}</small>
          </h3>
          <span class="prescription">
            {{ wex.target_sets }} ×
            {{ wex.target_reps_low === wex.target_reps_high
              ? wex.target_reps_low : `${wex.target_reps_low}-${wex.target_reps_high}` }}
            <span v-if="wex.target_weight_lb"> @ {{ wex.target_weight_lb }} lb</span>
            <span class="rest"> · {{ wex.target_rest_s }}s rest</span>
          </span>
        </header>

        <div class="ex-body" v-if="ex(wex.exercise_id)">
          <div class="media">
            <img v-if="imageUrl(wex.exercise_id, 0)" :src="imageUrl(wex.exercise_id, 0) || ''" :alt="exName(wex.exercise_id)" />
            <a class="yt" :href="youtubeUrl(wex.exercise_id)" target="_blank" rel="noreferrer">
              Watch form video on YouTube ↗
            </a>
            <button v-if="wex.sets.filter(s => s.actual_reps != null).length === 0"
                    class="swap-btn" @click="openSwap(wex.id)">
              <SwapIcon :size="13" /> Swap exercise
            </button>
          </div>

          <div class="sets">
            <table>
              <thead>
                <tr><th>#</th><th>Weight (lb)</th><th>Reps</th><th>Rating</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="n in wex.target_sets" :key="n"
                    :class="{ logged: isSetLogged(wex, n) }">
                  <td>{{ n }}</td>
                  <td>
                    <input
                      type="number" step="0.5" inputmode="decimal"
                      :placeholder="wex.target_weight_lb?.toString() ?? '—'"
                      v-model="entry(wex.id, n, wex.target_reps_low, wex.target_weight_lb).weight"
                      :disabled="isSetLogged(wex, n)"
                    />
                  </td>
                  <td>
                    <input
                      type="number" inputmode="numeric"
                      :placeholder="wex.target_reps_low.toString()"
                      v-model="entry(wex.id, n, wex.target_reps_low, wex.target_weight_lb).reps"
                      :disabled="isSetLogged(wex, n)"
                    />
                  </td>
                  <td class="rating-cell">
                    <button
                      v-for="r in 5" :key="r"
                      class="rating" :data-r="r"
                      :class="{ on: entry(wex.id, n, wex.target_reps_low, wex.target_weight_lb).rating === r }"
                      :disabled="isSetLogged(wex, n)"
                      @click="setRating(wex.id, n, r)"
                    >{{ r }}</button>
                  </td>
                  <td>
                    <button v-if="!isSetLogged(wex, n)" class="primary small"
                            :disabled="busy === `set-${wex.id}-${n}` || entry(wex.id, n, wex.target_reps_low, wex.target_weight_lb).rating === null"
                            @click="logSet(wex, n)">
                      Log
                    </button>
                    <span v-else class="ok">✓</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p class="rating-legend">
              <span class="lbl">1 Failed · 2 Very hard · 3 Hard · 4 Moderate · 5 Easy</span>
            </p>
          </div>
        </div>
      </div>

      <!-- Complete CTA -->
      <div v-if="workout.status !== 'completed'" class="bottom">
        <button class="primary big-btn" :disabled="completedSetsCount === 0 || busy === 'complete'"
                @click="completeWorkout">
          Complete workout
          <small>({{ completedSetsCount }}/{{ totalSetsCount }} sets)</small>
        </button>
      </div>
      <!-- Swap-exercise modal -->
      <div v-if="swapWexId !== null" class="overlay" @click.self="closeSwap">
        <div class="drawer swap-drawer">
          <header>
            <h2>Swap exercise</h2>
            <button class="close" @click="closeSwap">✕</button>
          </header>
          <p v-if="swapError" class="err">{{ swapError }}</p>
          <p v-if="swapAlternatives.length === 0" class="hint">
            No alternatives in your equipment for this slot.
          </p>
          <ul v-else class="alts">
            <li v-for="alt in swapAlternatives" :key="alt.id"
                :class="{ disabled: swapBusy }" @click="applySwap(alt.id)">
              <strong>{{ alt.name }}</strong>
              <span class="tags">{{ alt.movement_pattern.replace('_', ' ') }} · {{ alt.primary_muscle }}</span>
            </li>
          </ul>
        </div>
      </div>

      <Card v-else title="Workout complete" :subtitle="`${completedSetsCount} sets logged`">
        <p class="hint">
          Nicely done. Today's session is logged — you'll see the next-session
          weight progression baked in tomorrow.
        </p>

        <div class="ai-review">
          <button v-if="!review && !reviewLoading" class="ghost" @click="loadReview">
            Get AI workout review
          </button>
          <p v-if="reviewLoading" class="hint">Generating review…</p>
          <p v-if="reviewError" class="err">{{ reviewError }}</p>

          <div v-if="review" class="review-card" :class="`tone-${review.tone}`">
            <h3>{{ review.headline }}</h3>
            <ul v-if="review.highlights.length" class="hl">
              <li v-for="(h, i) in review.highlights" :key="i">{{ h }}</li>
            </ul>
            <ul v-if="review.concerns && review.concerns.length" class="cn">
              <li v-for="(c, i) in review.concerns" :key="i">{{ c }}</li>
            </ul>
            <p class="next"><strong>Next session:</strong> {{ review.next_session_suggestion }}</p>
            <p class="cached" v-if="reviewCached">cached · {{ reviewModel }}</p>
            <p class="cached" v-else>generated · {{ reviewModel }}</p>
          </div>
        </div>
      </Card>
    </template>
  </main>
</template>

<style scoped>
.strength-today { max-width: 880px; }
h1 { margin: 0 0 0.6rem; }
h1 small { color: var(--muted); font-weight: 400; text-transform: capitalize; }
.hint { color: var(--muted); font-size: 0.85rem; margin: 0.4rem 0; }
.err { color: #f87171; }

.ctx-row {
  display: flex; gap: 1rem; flex-wrap: wrap; align-items: baseline;
  font-size: 0.85rem; color: var(--muted);
  font-family: 'Geist Mono', ui-monospace, monospace;
}
.ctx-row strong { color: var(--text); font-weight: 600; }
.ctx-row .status {
  margin-left: auto; padding: 0.15rem 0.5rem; border-radius: 4px;
  background: var(--bg-2); border: 1px solid var(--line);
  text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.7rem;
}
.notes { margin-top: 0.4rem; color: var(--muted); font-size: 0.78rem; }
.actions { display: flex; gap: 0.5rem; margin-top: 0.6rem; }

.rest-timer {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg-2); border: 1px solid var(--accent, #ef4444);
  padding: 0.6rem 1rem; border-radius: 10px; margin: 0.6rem 0;
  display: flex; gap: 0.8rem; align-items: center;
  font-family: 'Geist Mono', ui-monospace, monospace;
}
.rest-timer.done { border-color: #22c55e; }
.rest-timer strong { font-size: 1.4rem; color: var(--accent, #ef4444); }
.rest-timer.done strong { color: #22c55e; }
.rest-timer .of { color: var(--muted); }

.ex-card {
  border: 1px solid var(--line); border-radius: 10px;
  padding: 0.8rem 1rem; margin: 0.6rem 0;
  background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
}
.ex-card.current { border-color: var(--accent, #ef4444); }
.ex-card.done { opacity: 0.6; }
.ex-card header {
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 0.4rem;
}
.ex-card h3 { margin: 0; font-size: 1rem; }
.ex-card h3 small { color: var(--muted); font-weight: 400; }
.prescription {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 0.82rem; color: var(--muted);
}
.prescription .rest { color: var(--muted-2); }

.ex-body { display: grid; grid-template-columns: 200px 1fr; gap: 1rem;
  margin-top: 0.6rem; }
@media (max-width: 600px) { .ex-body { grid-template-columns: 1fr; } }
.media img { width: 100%; border-radius: 8px; background: #111; }
.yt { display: inline-block; margin-top: 0.4rem; font-size: 0.78rem;
  color: var(--muted); text-decoration: none; }
.yt:hover { color: var(--accent, #ef4444); }

.sets table { width: 100%; border-collapse: collapse;
  font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.85rem; }
.sets th { text-align: left; padding: 0.3rem 0.4rem; color: var(--muted);
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--line); font-weight: 500; }
.sets td { padding: 0.3rem 0.4rem; vertical-align: middle; }
.sets tr.logged input { background: transparent; }
.sets input {
  width: 5rem; padding: 0.3rem 0.4rem; border: 1px solid var(--line);
  border-radius: 5px; background: var(--bg-1); color: var(--text);
  font-family: inherit; font-size: 0.85rem;
}
.sets input:disabled { color: var(--muted); border-color: var(--line); }

.rating-cell { display: flex; gap: 0.2rem; }
.rating {
  width: 1.6rem; height: 1.6rem; padding: 0; border-radius: 4px;
  border: 1px solid var(--line); background: var(--bg-2);
  color: var(--muted); font-weight: 600; cursor: pointer;
  font-family: ui-sans-serif, system-ui;
}
.rating:hover:not(:disabled) { border-color: var(--accent, #ef4444); color: var(--text); }
.rating:disabled { opacity: 0.5; cursor: not-allowed; }
.rating.on[data-r="1"] { background: rgba(239,68,68,0.4); color: #fff; border-color: #ef4444; }
.rating.on[data-r="2"] { background: rgba(249,115,22,0.4); color: #fff; border-color: #f97316; }
.rating.on[data-r="3"] { background: rgba(245,158,11,0.4); color: #fff; border-color: #f59e0b; }
.rating.on[data-r="4"] { background: rgba(132,204,22,0.4); color: #fff; border-color: #84cc16; }
.rating.on[data-r="5"] { background: rgba(34,197,94,0.4); color: #fff; border-color: #22c55e; }

.rating-legend { margin: 0.4rem 0 0; font-size: 0.7rem; color: var(--muted-2); }

.bottom { margin-top: 1rem; }
.big-btn { font-size: 1rem; padding: 0.7rem 1.4rem; }
.big-btn small { color: rgba(255,255,255,0.7); margin-left: 0.4rem; font-weight: 400; }
.ok { color: #22c55e; font-weight: 600; }

.ai-review { margin-top: 1rem; }
.review-card {
  margin-top: 0.6rem; padding: 0.9rem 1rem;
  border-radius: 10px; border: 1px solid var(--line);
  background: var(--bg-2);
}
.review-card.tone-good { border-color: #22c55e44; }
.review-card.tone-warn { border-color: #f59e0b66; }
.review-card.tone-bad { border-color: #ef444466; }
.review-card h3 { margin: 0 0 0.5rem; font-size: 1rem; color: var(--text); }
.review-card .hl { color: var(--text-soft); padding-left: 1.1rem; margin: 0.3rem 0; }
.review-card .cn { color: #f59e0b; padding-left: 1.1rem; margin: 0.3rem 0; }
.review-card .next { margin: 0.6rem 0 0; color: var(--text-soft); font-size: 0.88rem; }
.review-card .cached { font-size: 0.7rem; color: var(--muted-2);
  margin-top: 0.4rem; font-family: 'Geist Mono', ui-monospace, monospace; }

.swap-btn {
  display: inline-flex; align-items: center; gap: 0.3rem;
  margin-top: 0.4rem; padding: 0.3rem 0.6rem;
  font-size: 0.75rem; color: var(--text-soft);
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 5px; cursor: pointer;
}
.swap-btn:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 100;
  display: flex; justify-content: flex-end; }
.drawer.swap-drawer { width: min(420px, 100%); height: 100%;
  overflow-y: auto; background: var(--bg-1);
  border-left: 1px solid var(--line); padding: 1rem 1.2rem; }
.alts { list-style: none; padding: 0; margin: 0.4rem 0 0;
  display: flex; flex-direction: column; gap: 0.4rem; }
.alts li {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 8px; padding: 0.6rem 0.85rem; cursor: pointer;
  display: flex; flex-direction: column; gap: 0.2rem;
}
.alts li:hover { border-color: var(--accent, #ef4444); }
.alts li.disabled { opacity: 0.5; pointer-events: none; }
.alts li strong { color: var(--text); font-size: 0.92rem; }
.alts li .tags { color: var(--muted); font-size: 0.74rem;
  font-family: 'Geist Mono', ui-monospace, monospace; }

button.primary, button.ghost {
  padding: 0.4rem 0.85rem; border-radius: 6px; font-size: 0.85rem;
  cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem;
  border: 1px solid var(--line);
}
button.primary { background: var(--accent, #ef4444); color: #fff; border-color: var(--accent, #ef4444); }
button.primary.small { padding: 0.25rem 0.6rem; font-size: 0.78rem; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--text-soft); }
button.ghost:hover { color: var(--text); border-color: var(--accent, #ef4444); }
</style>
