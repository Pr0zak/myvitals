<script setup lang="ts">
/**
 * /workout/strength/today — full plan view that handles every workout state
 * via one component: planned (preview + start), in_progress (active workout
 * with set logging + rest timer), completed (summary).
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { Play, Pause, RotateCw, Plus, SkipForward, Timer, Check } from "lucide-vue-next";
import { api } from "@/api/client";
import { apiBase, queryToken } from "@/config";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import Card from "@/components/Card.vue";
import CoachCard from "@/components/CoachCard.vue";
import type { StrengthExercise, StrengthWorkoutDetail, StrengthWorkoutExercise } from "@/api/types";

const router = useRouter();

function muscleGroupsFor(focus: string): string {
  const m: Record<string, string> = {
    push: "Chest · Shoulders · Triceps",
    pull: "Back · Biceps",
    legs: "Quads · Hamstrings · Glutes · Calves",
    upper: "Chest · Back · Shoulders · Arms",
    lower: "Quads · Hamstrings · Glutes · Calves",
    full_body: "Full body — chest, back, legs",
    rest: "Rest day",
  };
  return m[focus.toLowerCase()] ?? focus.replace(/_/g, " ");
}
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

// Variety-nudge accept: AI returns target/replacement by exercise_id;
// we map target_exercise_id back to the matching workout_exercise row.
async function acceptNudge(p: { targetExerciseId: string; replacementExerciseId: string }) {
  if (!workout.value) return;
  const wex = workout.value.exercises.find(
    (x) => x.exercise_id === p.targetExerciseId,
  );
  if (!wex) return;
  try {
    await api.swapStrengthExercise(wex.id, p.replacementExerciseId);
    await loadAll();
  } catch (e: unknown) {
    /* surface via existing swapError if you want; silent for now */
    console.warn("nudge swap failed", e);
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

function chime() {
  // Quick web-audio beep — no asset bundling needed
  try {
    const ctx = new (window.AudioContext || (window as unknown as {
      webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880; o.type = "sine";
    g.gain.setValueAtTime(0.001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.05);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    o.start(); o.stop(ctx.currentTime + 0.6);
  } catch (_) { /* audio context blocked */ }
}

function notifyDone(seconds: number) {
  if (!("Notification" in window)) return;
  if (Notification.permission === "granted") {
    new Notification("Rest done", { body: `${seconds}s rest complete — start your next set.`, silent: false });
  } else if (Notification.permission !== "denied") {
    Notification.requestPermission(); // permission ask only fires once
  }
}

function startRest(seconds: number) {
  stopRest();
  restRemaining.value = seconds;
  restTotal.value = seconds;
  restHandle = window.setInterval(() => {
    if (restRemaining.value === null) return;
    restRemaining.value -= 1;
    if (restRemaining.value <= 0) {
      chime();
      notifyDone(seconds);
      // Vibrate (Android Chrome only)
      if ("vibrate" in navigator) navigator.vibrate([200, 80, 200]);
      stopRest();
    }
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

// Week-strip + training prefs (drives the projected workout-day pattern)
const recentWorkouts = ref<Array<{ date: string; status: string }>>([]);
const trainingPrefs = ref<{ days_per_week: number } | null>(null);
const upcoming = ref<Awaited<ReturnType<typeof api.strengthUpcoming>>["upcoming"]>([]);

async function loadAll() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const [w, r, cat, hist, eq, up] = await Promise.all([
      api.strengthToday(),
      api.strengthRecovery().catch(() => null),
      api.strengthExercises().catch(() => ({ count: 0, exercises: [] as StrengthExercise[] })),
      api.strengthWorkouts({ limit: 30 }).catch(() => ({ count: 0, workouts: [] })),
      api.strengthEquipment().catch(() => null),
      api.strengthUpcoming(7, 4).catch(() => ({ count: 0, upcoming: [] })),
    ]);
    workout.value = w;
    recovery.value = r;
    catalogById.value = Object.fromEntries(cat.exercises.map((e) => [e.id, e]));
    recentWorkouts.value = hist.workouts.map((x) => ({ date: x.date, status: x.status }));
    trainingPrefs.value = (eq?.payload as unknown as { training?: { days_per_week: number } })
      ?.training ?? { days_per_week: 3 };
    upcoming.value = up.upcoming;
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

// Time-based exercises (yoga / mobility) use a countdown timer instead
// of weight/reps inputs. Mobility entries declare it via the catalog
// `is_timed` flag (rep-based mobility like Thread-the-Needle / Cat-Cow
// returns false). Non-mobility falls through to the prior heuristic.
function isTimedExercise(wex: StrengthWorkoutExercise): boolean {
  // Backend-supplied wex.is_timed is authoritative — derived at
  // serialization time from the catalog row's is_timed flag.
  if ((wex as { is_timed?: boolean }).is_timed === true) return true;
  const c = ex(wex.exercise_id);
  // Catalog c.is_timed is only consulted for mobility, where it
  // distinguishes yoga holds from rep-based mobility (Cat-Cow).
  // Other movement patterns rely on the workout payload's flag.
  if (c?.movement_pattern === "mobility") return c.is_timed !== false;
  if (
    wex.target_weight_lb == null &&
    wex.target_reps_low === wex.target_reps_high &&
    wex.target_reps_low >= 20
  ) return true;
  return false;
}

// For bilateral mobility (sets=2, one per side), label the sets R / L
// instead of 1 / 2 — mirrors the phone TimedSetRow treatment.
function bilateralSideLabel(wex: StrengthWorkoutExercise, n: number): string {
  const c = ex(wex.exercise_id);
  if (!c?.is_bilateral || wex.target_sets !== 2) return String(n);
  return n === 1 ? "R" : "L";
}

// Per-set countdown state — keyed by `${wexId}-${setNum}` so each row
// has independent timing. `endsAt` is the wall-clock instant when the
// timer hits zero; the UI reads `tickNow` so it re-renders each second.
type TimerState = {
  endsAt: number;          // ms epoch
  totalS: number;          // configured hold (the target_reps as seconds)
  finished: boolean;
};
const timers = ref<Record<string, TimerState>>({});
const tickNow = ref(Date.now());
let tickHandle: number | null = null;

function timerKey(wexId: number, n: number) { return `${wexId}-${n}`; }
function startTimer(wex: StrengthWorkoutExercise, n: number) {
  const seconds = wex.target_reps_low;
  const k = timerKey(wex.id, n);
  timers.value = {
    ...timers.value,
    [k]: { endsAt: Date.now() + seconds * 1000, totalS: seconds, finished: false },
  };
  if (tickHandle == null) {
    tickHandle = window.setInterval(() => {
      tickNow.value = Date.now();
      // Auto-log any expired timers exactly once.
      for (const [key, st] of Object.entries(timers.value)) {
        if (st.finished) continue;
        if (tickNow.value >= st.endsAt) {
          st.finished = true;
          const [wexIdStr, setStr] = key.split("-");
          const wexId = Number(wexIdStr);
          const setN = Number(setStr);
          const targetWex = workout.value?.exercises.find((x) => x.id === wexId);
          if (targetWex) {
            // Fire haptic if the browser supports it.
            try { navigator.vibrate?.(200); } catch { /* no-op */ }
            // Auto-log: full hold completed, no weight, rating=4 (smooth).
            const e = entry(wexId, setN, targetWex.target_reps_low, null);
            e.weight = "";
            e.reps = String(targetWex.target_reps_low);
            e.rating = 4;
            logSet(targetWex, setN).catch((err) => console.warn(err));
          }
        }
      }
      // Stop ticking when no active timers remain.
      if (Object.values(timers.value).every((s) => s.finished)) {
        if (tickHandle != null) {
          clearInterval(tickHandle);
          tickHandle = null;
        }
      }
    }, 250);
  }
}
function stopTimer(wexId: number, n: number) {
  const k = timerKey(wexId, n);
  const copy = { ...timers.value };
  delete copy[k];
  timers.value = copy;
}
function timerRemaining(wexId: number, n: number): number | null {
  const st = timers.value[timerKey(wexId, n)];
  if (!st) return null;
  if (st.finished) return 0;
  return Math.max(0, Math.ceil((st.endsAt - tickNow.value) / 1000));
}
function fmtCountdown(s: number): string {
  if (s >= 60) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return `${s}s`;
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

// Bumped after every regenerate so the DeloadBanner (keyed on this)
// remounts and re-reads /latest. We also fire the deload-check POST
// in parallel so the cached judgment is rebuilt against the same
// fresh signals the workout just used. Backend caches by signals
// hash, so re-clicks that don't change underlying data are free.
const deloadRefreshKey = ref(0);

async function regenerate(force = false) {
  busy.value = "regen";
  error.value = "";
  try {
    workout.value = await api.regenerateStrengthToday(force);
    api.aiStrengthDeloadCheck().catch(() => { /* banner stays stale on failure */ });
    deloadRefreshKey.value++;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

const swapMenuOpen = ref(false);
const swapBusyType = ref<"strength" | "yoga" | "cardio" | null>(null);
async function doSwap(t: "strength" | "yoga" | "cardio") {
  swapMenuOpen.value = false;
  swapBusyType.value = t;
  error.value = "";
  try {
    workout.value = await api.swapTodayType(t);
    await loadAll();
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { data?: { detail?: string } } }).response;
      error.value = resp?.data?.detail ?? (e instanceof Error ? e.message : String(e));
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    swapBusyType.value = null;
  }
}

async function deferToday() {
  if (!workout.value) return;
  if (!confirm("Skip today's workout day? You can undo from the Skipped state if you tap by accident.")) return;
  busy.value = "defer";
  try {
    await api.patchStrengthWorkout(workout.value.id, { status: "skipped" });
    await loadAll();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

async function undoSkip() {
  if (!workout.value) return;
  busy.value = "undo";
  try {
    await api.patchStrengthWorkout(workout.value.id, { status: "planned" });
    await loadAll();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

// Per-day strip: today centered, 3 days before + 3 days after.
type DayCell = {
  iso: string;
  label: string;            // "Mon", "Tue" or "Today"
  dow: number;              // 0=Sunday..6=Saturday
  isToday: boolean;
  isPast: boolean;
  status: string | null;    // completed | in_progress | skipped | planned | null
  projected: boolean;       // backend hasn't planned yet, but our cadence says it should be
};

const weekStrip = computed<DayCell[]>(() => {
  const out: DayCell[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayMs = today.getTime();
  const histByDate: Record<string, string> = {};
  for (const w of recentWorkouts.value) histByDate[w.date] = w.status;

  // Workout-day pattern (Mon..Sun = 0..6 in our local-Mon-first model).
  // 3 days/week → Mon/Wed/Fri; 4 → Mon/Tue/Thu/Fri; 5 → Mon-Fri; 6 → Mon-Sat.
  const dpw = trainingPrefs.value?.days_per_week ?? 3;
  const PATTERN: Record<number, number[]> = {
    2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4],
    5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5],
  };
  const pattern = new Set(PATTERN[dpw] ?? PATTERN[3]);
  // Map JS dow (0=Sun..6=Sat) to our Mon-first index (0=Mon..6=Sun)
  const monFirst = (jsDow: number) => (jsDow + 6) % 7;

  for (let offset = -3; offset <= 3; offset++) {
    const d = new Date(today);
    d.setDate(today.getDate() + offset);
    const iso = d.toISOString().slice(0, 10);
    const label = offset === 0 ? "Today"
      : d.toLocaleDateString(undefined, { weekday: "short" });
    const past = d.getTime() < todayMs;
    const status = histByDate[iso] ?? null;
    const projected = !past && status === null && pattern.has(monFirst(d.getDay()));
    out.push({
      iso, label, dow: d.getDay(),
      isToday: offset === 0,
      isPast: past,
      status,
      projected,
    });
  }
  return out;
});

// Rating helper text — Fitbod-style RIR (Reps In Reserve)
function ratingShort(r: number): string {
  return ["", "fail", "0-1", "2-3", "4-5", "6+"][r] ?? "";
}
function ratingTitle(r: number): string {
  return [
    "",
    "1 — Failed: missed reps or had to rack early",
    "2 — Very hard: 0–1 more reps possible (RIR 0–1)",
    "3 — Hard: 2–3 reps in reserve (RIR 2–3)",
    "4 — Moderate: 4–5 reps in reserve (RIR 4–5)",
    "5 — Easy: 6+ reps in reserve, ready to bump weight (RIR 6+)",
  ][r] ?? "";
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

// Surface a "workout finished?" confirmation the moment the last
// prescribed set is logged. Less intrusive than auto-completing —
// user might want to add bonus sets — but more discoverable than the
// small "Complete workout" button at the bottom of the page.
const showCompleteDialog = ref(false);
const completeDialogDismissed = ref(false);
const allSetsDone = computed(() =>
  totalSetsCount.value > 0
  && completedSetsCount.value >= totalSetsCount.value
);
watch(allSetsDone, (done, prev) => {
  if (done && !prev && !completeDialogDismissed.value
      && workout.value && workout.value.status !== "completed") {
    showCompleteDialog.value = true;
  }
});
async function finishFromDialog() {
  showCompleteDialog.value = false;
  await completeWorkout();
}
function dismissCompleteDialog() {
  showCompleteDialog.value = false;
  // Don't re-pop on every recomposition. User explicitly chose to
  // keep going; honour that until the next workout.
  completeDialogDismissed.value = true;
}

const currentExercise = computed(() => {
  if (!workout.value) return null;
  return workout.value.exercises.find((ex) => !isExerciseDone(ex)) ?? null;
});

async function logFailed(wex: StrengthWorkoutExercise, setNum: number) {
  // Shortcut: mark the set as failed (rating=1) using whatever weight is
  // already in the input. Reps default to whatever was entered (or the
  // target if unset) — what matters is the rating, which drives the
  // -7.5% deload on next session.
  const e = entry(wex.id, setNum, wex.target_reps_low, wex.target_weight_lb);
  if (!confirm("Mark set " + setNum + " as failed? Next session's weight will drop ~7.5%.")) return;
  e.rating = 1;
  await logSet(wex, setNum);
}

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
      // Pick rest duration: within-round (35s) when this is a superset
      // and the partner hasn't completed this set number yet; full
      // target_rest_s otherwise.
      let rest = wex.target_rest_s;
      if (wex.superset_id && workout.value) {
        const partner = workout.value.exercises.find(
          (x) => x.superset_id === wex.superset_id && x.id !== wex.id,
        );
        const partnerDone = partner?.sets.some(
          (s) => s.set_number === setNum && s.actual_reps != null && !s.skipped,
        );
        // 35s within-round when partner still owes this round; otherwise full rest
        rest = partnerDone ? wex.target_rest_s : 35;
      }
      startRest(rest);
    }
    await loadAll();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = "";
  }
}

// Lookup helpers for superset rendering
function supersetPartnerName(superId: string | null, ownId: number): string | null {
  if (!superId || !workout.value) return null;
  const partner = workout.value.exercises.find(
    (x) => x.superset_id === superId && x.id !== ownId,
  );
  return partner ? exName(partner.exercise_id) : null;
}
function supersetColor(superId: string | null): string {
  if (!superId) return "transparent";
  // Stable hash → hue
  let h = 0;
  for (let i = 0; i < superId.length; i++) h = (h * 31 + superId.charCodeAt(i)) % 360;
  return `hsl(${h}, 65%, 55%)`;
}
function supersetNextUp(wex: StrengthWorkoutExercise): number | null {
  // The set number the user should do next on THIS exercise based on partner state
  if (!wex.superset_id || !workout.value) return null;
  const partner = workout.value.exercises.find(
    (x) => x.superset_id === wex.superset_id && x.id !== wex.id,
  );
  if (!partner) return null;
  for (let n = 1; n <= wex.target_sets; n++) {
    const ownDone = wex.sets.some(s => s.set_number === n && s.actual_reps != null);
    const partnerDone = partner.sets.some(s => s.set_number === n && s.actual_reps != null);
    if (!ownDone && partnerDone) return n;   // partner did set n; we're up
    if (!ownDone && !partnerDone) return n;  // both haven't done set n; either can go
  }
  return null;
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
useVisibilityRefresh(loadAll);
</script>

<template>
  <main class="strength-today">
    <header class="page-head compact">
      <div class="title-block">
        <span class="eyebrow">WORKOUT</span>
        <h1 v-if="workout">{{
          workout.split_focus.charAt(0).toUpperCase() + workout.split_focus.slice(1).replace('_', ' ')
        }} day</h1>
        <h1 v-else>Today</h1>
        <span v-if="workout" class="head-pip mono">
          {{ completedSetsCount }}/{{ totalSetsCount }} sets
        </span>
        <span v-if="workout && workout.status !== 'planned' && workout.status !== 'in_progress'"
              class="status-pip" :class="`s-${workout.status}`">
          {{ workout.status.replace("_", " ") }}
        </span>
      </div>
      <div class="head-actions">
        <button v-if="workout && workout.status === 'planned'"
                class="ghost"
                :disabled="busy === 'regen'"
                :title="'Re-runs the plan against the latest sleep / HRV / recovery / strength signals'"
                @click="regenerate(true)">
          {{ busy === 'regen' ? 'Regenerating…' : 'Regenerate ↻' }}
        </button>
        <button class="ghost" :disabled="swapBusyType !== null"
                @click="swapMenuOpen = !swapMenuOpen">
          {{ swapBusyType ? `Switching to ${swapBusyType}…` : "Swap day ▾" }}
        </button>
        <div v-if="swapMenuOpen" class="swap-menu">
          <button class="swap-item" @click="doSwap('strength')">
            <strong>Strength</strong>
            <span class="dim">auto-pick today's split</span>
          </button>
          <button class="swap-item" @click="doSwap('yoga')">
            <strong>Yoga / mobility</strong>
            <span class="dim">5 poses, 45 s holds</span>
          </button>
          <button class="swap-item" @click="doSwap('cardio')">
            <strong>Cardio</strong>
            <span class="dim">30-45 min Z2 effort</span>
          </button>
          <div class="swap-divider"></div>
          <button class="swap-item"
                  v-if="workout && workout.status === 'planned'"
                  :disabled="busy === 'regen'"
                  @click="swapMenuOpen = false; regenerate(true)">
            <strong>Regenerate plan</strong>
            <span class="dim">re-pick exercises with same split</span>
          </button>
          <button class="swap-item"
                  v-if="workout && (workout.status === 'planned' || workout.status === 'in_progress')"
                  :disabled="busy === 'defer'"
                  @click="swapMenuOpen = false; deferToday()">
            <strong>Skip workout day</strong>
            <span class="dim">undoable from the skipped banner</span>
          </button>
        </div>
      </div>
    </header>

    <p v-if="workout?.notes" class="hint subtle">{{ workout.notes }}</p>

    <!-- Soft warning when the plan was generated before today's sleep
         data was ingested. Plan is still usable but its deload + load
         decisions ignored last night's recovery. Surface a "Regenerate
         to refresh" prompt so the user can grab the fresh-data plan. -->
    <div v-if="workout?.recovery_stale" class="stale-banner">
      <span class="stale-icon">↻</span>
      <span class="stale-text">
        Plan generated before today's sleep data was synced —
        tap Regenerate to refresh with fresh recovery context.
      </span>
      <button class="ghost small" :disabled="busy === 'regen'"
              @click="regenerate(true)">
        {{ busy === 'regen' ? 'Refreshing…' : 'Regenerate' }}
      </button>
    </div>
    <!-- FAST-18 — fasted-training banner. Appears when the workout
         was generated against an active fast that crossed the 18h
         volume-modulation threshold. -->
    <div v-if="workout?.fasting_context
               && workout.fasting_context.active
               && workout.fasting_context.modulation !== 'normal'"
         class="fast-banner">
      <span class="fast-icon">⏳</span>
      <span class="fast-text">
        You're <strong>{{ workout.fasting_context.current_hours.toFixed(0) }}h fasted</strong>
        ({{ workout.fasting_context.stage.replace('_', ' ') }}) —
        <template v-if="workout.fasting_context.modulation === 'volume_-20%'">
          volume trimmed ~20%, rest +15s.
        </template>
        <template v-else>
          volume trimmed ~30%, rest +30s. A Z2 cardio block alongside is a strong option.
        </template>
      </span>
    </div>
    <!-- Why + Variety nudge moved below the exercise list. -->

    <CoachCard v-if="queryToken && workout
                     && (workout.status === 'planned' || workout.status === 'in_progress')"
               :workout-id="workout.id"
               :refresh-key="deloadRefreshKey"
               @accept-swap="acceptNudge" />

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
      <!-- 7-day strip: past 3, today, projected 3 -->
      <div class="week-strip">
        <RouterLink v-for="d in weekStrip" :key="d.iso"
             :to="{ name: 'workout-strength-day', params: { date: d.iso } }"
             class="day"
             :class="{
               today: d.isToday,
               completed: d.status === 'completed',
               in_progress: d.status === 'in_progress',
               skipped: d.status === 'skipped',
               planned: d.status === 'planned',
               projected: d.projected,
               past: d.isPast,
             }"
             :title="d.iso + (d.status ? ' · ' + d.status : (d.projected ? ' · projected workout day' : ' · rest day'))">
          <div class="dow">{{ d.label }}</div>
          <div class="dot"></div>
        </RouterLink>
      </div>

      <Card v-if="workout.status === 'skipped'" class="skip-banner" :flat="true">
        <div class="skip-row">
          <span>
            <strong>Skipped today's workout day.</strong>
            Tomorrow will generate fresh.
          </span>
          <button class="ghost" :disabled="busy === 'undo'" @click="undoSkip">
            <RotateCw :size="14" /> {{ busy === 'undo' ? 'Restoring…' : 'Undo' }}
          </button>
        </div>
      </Card>

      <!-- ctx Card removed: sets count → header pip, status → header
           pip, regenerate / skip → swap-day overflow menu, recovery /
           sleep → workout.notes line above (rendered before WhyCard). -->
      <div v-if="workout.recovery_score_used != null || workout.sleep_h_used != null"
           class="ctx-meta dim">
        <span v-if="workout.recovery_score_used != null">
          recovery {{ Math.round(workout.recovery_score_used) }}
        </span>
        <span v-if="workout.sleep_h_used != null">
          · sleep {{ workout.sleep_h_used.toFixed(1) }}h
        </span>
      </div>

      <!-- Rest timer (redesigned per claude.ai/design workout bundle) -->
      <div v-if="restRemaining !== null" class="rest-timer" :class="{ done: restRemaining <= 0 }">
        <div class="icon-block">
          <Timer v-if="restRemaining > 0" :size="18" />
          <Check v-else :size="18" />
        </div>
        <div class="time-block">
          <template v-if="restRemaining > 0">
            <div class="big-time">{{ fmtRest(Math.max(0, restRemaining)) }}</div>
            <div class="of">of <span class="mono">{{ restTotal }}s</span> rest</div>
          </template>
          <template v-else>
            <div class="done-text">Rest done — go!</div>
          </template>
        </div>
        <div v-if="restRemaining > 0" class="rt-actions">
          <button class="rt-btn" @click="addRest(30)">+30s</button>
          <button class="rt-btn ghost" @click="stopRest">Skip</button>
        </div>
      </div>

      <!-- Cardio prescription — no exercise list, notes-only.
           Renders the suggestion text + a "Complete cardio" button. -->
      <div v-if="workout.split_focus === 'cardio' && workout.exercises.length === 0"
           class="cardio-card">
        <h3>Cardio session</h3>
        <p class="cardio-notes">{{ workout.notes }}</p>
        <p class="hint">
          The session itself syncs from the activity provider (Concept2 for
          rowing, Strava for biking). Once it lands in /activities you can
          mark today complete here.
        </p>
        <button v-if="workout.status === 'planned' || workout.status === 'in_progress'"
                class="primary" :disabled="busy === 'complete'"
                @click="completeWorkout">
          {{ busy === 'complete' ? 'Saving…' : 'Mark cardio complete' }}
        </button>
        <p v-else-if="workout.status === 'completed'" class="ok">
          ✓ Cardio session marked complete.
        </p>
      </div>

      <!-- Exercise list -->
      <div v-for="(wex, idx) in workout.exercises" :key="wex.id" class="ex-card"
           :class="{ current: currentExercise?.id === wex.id, done: isExerciseDone(wex), superset: !!wex.superset_id }"
           :style="wex.superset_id ? { borderLeftColor: supersetColor(wex.superset_id) } : {}">
        <div v-if="wex.superset_id" class="ss-banner" :style="{ color: supersetColor(wex.superset_id) }">
          ⇄ Superset {{ wex.superset_id }} — alternate with <strong>{{ supersetPartnerName(wex.superset_id, wex.id) }}</strong>
        </div>
        <header>
          <h3>
            {{ idx + 1 }}. {{ exName(wex.exercise_id) }}
          </h3>
          <span class="prescription">
            {{ wex.target_sets }} ×
            {{ wex.target_reps_low === wex.target_reps_high
              ? wex.target_reps_low : `${wex.target_reps_low}-${wex.target_reps_high}` }}
            <span v-if="wex.target_weight_lb"> @ {{ wex.target_weight_lb }} lb</span>
            <span class="rest"> · {{ wex.target_rest_s }}s rest</span>
          </span>
        </header>

        <!-- Completed state: collapse to chip summary instead of greyed-out inputs -->
        <div v-if="isExerciseDone(wex)" class="done-summary">
          <span v-for="s in [...wex.sets].sort((a, b) => a.set_number - b.set_number)"
                :key="s.set_number"
                class="set-chip"
                :class="s.skipped ? 'fail' : 'ok'"
                :title="`Set ${s.set_number} · RPE ${s.rating ?? '?'}`"
                :data-r="s.rating ?? 0">
            <template v-if="s.skipped">fail</template>
            <template v-else>{{ s.actual_weight_lb ?? '—' }}×{{ s.actual_reps }}</template>
          </span>
        </div>

        <div v-else class="ex-body" v-if="ex(wex.exercise_id)">
          <div class="media">
            <!-- Real demo photo wins over the violet-tinted icon.
                 Photos are .jpg from the base catalog; icons are .png
                 (from the Noun Project mask treatment). -->
            <img
              v-if="imageUrl(wex.exercise_id, 0) && /\.jpe?g($|\?)/i.test(imageUrl(wex.exercise_id, 0)!)"
              :src="imageUrl(wex.exercise_id, 0) || ''"
              :alt="exName(wex.exercise_id)"
            />
            <div
              v-else-if="imageUrl(wex.exercise_id, 0)"
              class="ex-thumb"
              :style="`-webkit-mask-image: url('${imageUrl(wex.exercise_id, 0)}'); mask-image: url('${imageUrl(wex.exercise_id, 0)}')`"
              :title="exName(wex.exercise_id)"
            />
            <a class="yt" :href="youtubeUrl(wex.exercise_id)" target="_blank" rel="noreferrer">
              Watch form video on YouTube ↗
            </a>
            <button v-if="wex.sets.filter(s => s.actual_reps != null).length === 0"
                    class="swap-btn" @click="openSwap(wex.id)">
              Swap exercise
            </button>
          </div>

          <div class="sets">
            <table>
              <thead>
                <tr v-if="!isTimedExercise(wex)">
                  <th>#</th><th>Weight (lb)</th><th>Reps</th><th>Rating</th><th></th>
                </tr>
                <tr v-else>
                  <th>#</th><th colspan="3">Hold</th><th></th>
                </tr>
              </thead>
              <tbody>
                <!-- Standard rep-based row -->
                <tr v-for="n in wex.target_sets" :key="n"
                    v-if="!isTimedExercise(wex)"
                    :class="{ logged: isSetLogged(wex, n) }">
                  <td :class="{ side: bilateralSideLabel(wex, n) !== String(n) }">
                    {{ bilateralSideLabel(wex, n) }}
                  </td>
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
                      :title="ratingTitle(r)"
                      @click="setRating(wex.id, n, r)"
                    >
                      <span class="num">{{ r }}</span>
                      <span class="rir">{{ ratingShort(r) }}</span>
                    </button>
                  </td>
                  <td>
                    <div v-if="!isSetLogged(wex, n)" class="row-actions">
                      <button class="primary small"
                              :disabled="busy === `set-${wex.id}-${n}` || entry(wex.id, n, wex.target_reps_low, wex.target_weight_lb).rating === null"
                              @click="logSet(wex, n)">
                        Log
                      </button>
                      <button class="ghost small fail"
                              :disabled="busy === `set-${wex.id}-${n}`"
                              title="Mark this set failed (rating 1 — auto-deload next session)"
                              @click="logFailed(wex, n)">
                        Failed
                      </button>
                    </div>
                    <span v-else class="ok">✓</span>
                  </td>
                </tr>

                <!-- Timed (yoga / mobility) row -->
                <tr v-for="n in wex.target_sets" :key="`t-${n}`"
                    v-if="isTimedExercise(wex)"
                    :class="{ logged: isSetLogged(wex, n) }">
                  <td :class="{ side: bilateralSideLabel(wex, n) !== String(n) }">
                    {{ bilateralSideLabel(wex, n) }}
                  </td>
                  <td colspan="3" class="timer-cell">
                    <template v-if="isSetLogged(wex, n)">
                      <span class="dim">Held {{ wex.target_reps_low }}s ✓</span>
                    </template>
                    <template v-else-if="timerRemaining(wex.id, n) !== null">
                      <div class="countdown-block">
                        <span class="countdown mono">
                          {{ fmtCountdown(timerRemaining(wex.id, n) ?? 0) }}
                        </span>
                        <span class="dim small">of {{ wex.target_reps_low }}s</span>
                      </div>
                    </template>
                    <template v-else>
                      <span class="dim">{{ wex.target_reps_low }}s hold</span>
                    </template>
                  </td>
                  <td>
                    <div v-if="!isSetLogged(wex, n)" class="row-actions">
                      <button v-if="timerRemaining(wex.id, n) === null"
                              class="primary small"
                              @click="startTimer(wex, n)">
                        ▶ Start
                      </button>
                      <button v-else
                              class="ghost small"
                              @click="stopTimer(wex.id, n)">
                        Cancel
                      </button>
                    </div>
                    <span v-else class="ok">✓</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="!isTimedExercise(wex)" class="rating-legend">
              <span class="lbl">RIR scale: how many more reps you could've done. 1 = failed → 5 = easy</span>
            </p>
            <p v-else class="rating-legend">
              <span class="lbl">Hold each pose for the configured time. Tap Start; auto-logs at zero.</span>
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

      <Card v-else title="Workout complete" :subtitle="`${completedSetsCount} sets logged`" :flat="true">
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

      <!-- Why + Variety + Deload + Focus are now consolidated into the
           single CoachCard mounted near the top of the page. -->

      <!-- Next workouts moved to bottom — "look ahead" not "do now" -->
      <div v-if="upcoming.filter(u => !u.is_today).length > 0" class="upcoming">
        <h3>Next workouts</h3>
        <div class="upcoming-grid">
          <div v-for="u in upcoming.filter(x => !x.is_today).slice(0, 3)" :key="u.date" class="up-card">
            <div class="up-head">
              <strong>{{ new Date(u.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) }}</strong>
              <span class="focus">{{ u.split_focus.replace('_', ' ') }}</span>
            </div>
            <ul>
              <li v-for="(name, i) in u.preview_exercises" :key="i">{{ name }}</li>
              <li v-if="u.exercise_count > u.preview_exercises.length" class="more">
                + {{ u.exercise_count - u.preview_exercises.length }} more
              </li>
            </ul>
          </div>
        </div>
      </div>
    </template>

    <!-- Workout-complete confirmation. Pops on the false → true
         transition of allSetsDone; user can finish now or keep
         going (e.g. bonus sets). -->
    <div v-if="showCompleteDialog" class="cd-backdrop" @click.self="dismissCompleteDialog">
      <div class="cd-card">
        <h2>Workout complete?</h2>
        <p class="cd-sub">
          All {{ totalSetsCount }} prescribed sets logged. Finish and stamp
          the session, or keep going if you want to add bonus work.
        </p>
        <div class="cd-actions">
          <button class="ghost" @click="dismissCompleteDialog">Keep going</button>
          <button class="primary" :disabled="busy === 'complete'" @click="finishFromDialog">
            {{ busy === 'complete' ? 'Finishing…' : 'Finish workout' }}
          </button>
        </div>
      </div>
    </div>
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

/* Rest timer — claude.ai/design bundle layout: icon block + mono digits + side actions */
.rest-timer {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg-2);
  border: 1px solid var(--line);
  padding: 0.6rem 0.75rem; border-radius: 12px; margin: 0.6rem 0;
  display: flex; gap: 0.7rem; align-items: center;
  transition: background 150ms ease-in-out, border-color 150ms ease-in-out;
}
.rest-timer.done {
  background: rgba(34, 197, 94, 0.10);
  border-color: rgba(34, 197, 94, 0.55);
}
.rest-timer .icon-block {
  width: 36px; height: 36px; border-radius: 10px;
  background: var(--bg-1); border: 1px solid var(--line);
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--muted); flex: 0 0 auto;
}
.rest-timer.done .icon-block {
  background: rgba(34, 197, 94, 0.15);
  border-color: rgba(34, 197, 94, 0.45);
  color: #22c55e;
}
.rest-timer .time-block { flex: 1; min-width: 0; }
.rest-timer .big-time {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 1.55rem; font-weight: 600; color: var(--text);
  line-height: 1; letter-spacing: -0.02em;
}
.rest-timer .of { font-size: 0.7rem; color: var(--muted-2); margin-top: 2px; }
.rest-timer .of .mono { font-family: 'Geist Mono', ui-monospace, monospace; }
.rest-timer .done-text { font-size: 0.95rem; font-weight: 600; color: #22c55e; }
.rest-timer .rt-actions { display: flex; gap: 0.35rem; flex: 0 0 auto; }
.rest-timer .rt-btn {
  padding: 0.32rem 0.6rem; border-radius: 7px;
  background: var(--bg-1); border: 1px solid var(--line);
  color: var(--text); font-size: 0.78rem; font-weight: 500; cursor: pointer;
}
.rest-timer .rt-btn.ghost { background: transparent; color: var(--muted); }
.rest-timer .rt-btn:hover { color: var(--text); border-color: var(--accent, #ef4444); }

.cardio-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid #38bdf8;
  border-radius: 8px;
  padding: 1rem 1.2rem;
  margin-bottom: 1rem;
}
.cardio-card h3 { margin: 0 0 0.5rem; }
.cardio-notes { color: var(--text); line-height: 1.5; margin: 0 0 0.6rem; }
.cardio-card .hint { color: var(--muted); font-size: 0.85rem; margin: 0 0 0.8rem; }
.cardio-card .ok { color: var(--good); margin: 0; }

.ex-card {
  border: 1px solid var(--line); border-radius: 10px;
  padding: 0.8rem 1rem; margin: 0.6rem 0;
  background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
}
.ex-card.current { border-color: var(--accent, #ef4444); }
.ex-card.done { opacity: 0.6; }
.ex-card.superset { border-left-width: 4px; }
.ss-banner {
  font-size: 0.75rem; padding: 0 0.4rem 0.4rem;
  font-family: 'Geist Mono', ui-monospace, monospace;
  letter-spacing: 0.02em;
}
.ss-banner strong { color: var(--text); font-weight: 600; }
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

.ex-body { display: grid; grid-template-columns: 96px 1fr; gap: 0.9rem;
  margin-top: 0.6rem; align-items: start; }
@media (max-width: 600px) { .ex-body { grid-template-columns: 80px 1fr; } }
.media img { width: 100%; border-radius: 8px; background: #111; }
.media .ex-thumb {
  width: 100%; aspect-ratio: 1 / 1;
  border-radius: 8px;
  background: var(--accent, #a78bfa);
  -webkit-mask-size: 70%; mask-size: 70%;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  /* faint violet wash so the silhouette sits in a card not on bare bg */
  box-shadow: inset 0 0 0 999px rgba(167, 139, 250, 0.10);
}
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
  display: inline-flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 1px;
  width: 2.6rem; min-height: 2.4rem; padding: 3px 0;
  border-radius: 6px; cursor: pointer;
  border: 1px solid var(--line); background: var(--bg-2);
  color: var(--muted); font-family: ui-sans-serif, system-ui;
}
.rating .num { font-weight: 700; font-size: 0.9rem; line-height: 1; }
.rating .rir { font-size: 0.6rem; color: var(--muted-2); line-height: 1;
  font-family: 'Geist Mono', ui-monospace, monospace; }
.rating:hover:not(:disabled) { transform: translateY(-1px); }
.rating:disabled { opacity: 0.5; cursor: not-allowed; }

/* Color the number always; fill background when selected. */
.rating[data-r="1"] { border-color: rgba(239,68,68,0.45); }
.rating[data-r="1"] .num { color: #ef4444; }
.rating[data-r="2"] { border-color: rgba(249,115,22,0.45); }
.rating[data-r="2"] .num { color: #f97316; }
.rating[data-r="3"] { border-color: rgba(245,158,11,0.45); }
.rating[data-r="3"] .num { color: #f59e0b; }
.rating[data-r="4"] { border-color: rgba(132,204,22,0.45); }
.rating[data-r="4"] .num { color: #84cc16; }
.rating[data-r="5"] { border-color: rgba(34,197,94,0.45); }
.rating[data-r="5"] .num { color: #22c55e; }

.rating.on[data-r="1"] { background: rgba(239,68,68,0.45); border-color: #ef4444; }
.rating.on[data-r="1"] .num, .rating.on[data-r="1"] .rir { color: #fff; }
.rating.on[data-r="2"] { background: rgba(249,115,22,0.45); border-color: #f97316; }
.rating.on[data-r="2"] .num, .rating.on[data-r="2"] .rir { color: #fff; }
.rating.on[data-r="3"] { background: rgba(245,158,11,0.5); border-color: #f59e0b; }
.rating.on[data-r="3"] .num, .rating.on[data-r="3"] .rir { color: #fff; }
.rating.on[data-r="4"] { background: rgba(132,204,22,0.5); border-color: #84cc16; }
.rating.on[data-r="4"] .num, .rating.on[data-r="4"] .rir { color: #fff; }
.rating.on[data-r="5"] { background: rgba(34,197,94,0.5); border-color: #22c55e; }
.rating.on[data-r="5"] .num, .rating.on[data-r="5"] .rir { color: #fff; }

.rating-legend { margin: 0.4rem 0 0; font-size: 0.7rem; color: var(--muted-2); }
.row-actions { display: flex; gap: 0.3rem; align-items: center; }
button.ghost.small.fail { color: #f87171; border-color: #b91c1c44; }
button.ghost.small.fail:hover { color: #fff; background: #ef4444; border-color: #ef4444; }

/* Done-state chip summary — matches claude.ai/design workout bundle */
.done-summary { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.7rem;
                padding-top: 0.7rem; border-top: 1px solid var(--line); }
.set-chip {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 0.72rem; font-weight: 500;
  padding: 0.18rem 0.45rem; border-radius: 5px;
  border: 1px solid var(--line); background: var(--bg-1);
  color: var(--muted);
}
.set-chip.fail {
  color: #fca5a5; border-color: rgba(239,68,68,0.35);
  background: rgba(239,68,68,0.07);
}
.set-chip.ok[data-r="1"] { color: #fca5a5; border-color: rgba(239,68,68,0.35); }
.set-chip.ok[data-r="2"] { color: #fdba74; border-color: rgba(249,115,22,0.35); }
.set-chip.ok[data-r="3"] { color: #fcd34d; border-color: rgba(245,158,11,0.35); }
.set-chip.ok[data-r="4"] { color: #bef264; border-color: rgba(132,204,22,0.35); }
.set-chip.ok[data-r="5"] { color: #86efac; border-color: rgba(34,197,94,0.35); }

.bottom { margin-top: 1rem; }
.big-btn { font-size: 1rem; padding: 0.7rem 1.4rem; }
.big-btn small { color: rgba(255,255,255,0.7); margin-left: 0.4rem; font-weight: 400; }
.ok { color: #22c55e; font-weight: 600; }

.ai-review { margin-top: 0.5rem; }
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

.skip-banner { border-left: 3px solid #94a3b8; }
.skip-row { display: flex; justify-content: space-between; align-items: center;
  gap: 1rem; flex-wrap: wrap; }

.upcoming { margin-bottom: 1rem; }
.upcoming h3 {
  font-size: 0.75rem; color: var(--muted); letter-spacing: 0.08em;
  text-transform: uppercase; margin: 0 0 0.5rem; font-weight: 600;
}
.upcoming-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem;
}
.up-card {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 8px; padding: 0.6rem 0.7rem;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.up-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 0.4rem; font-size: 0.82rem;
}
.up-head strong { color: var(--text); }
.up-head .focus {
  color: var(--accent, #ef4444); text-transform: capitalize;
  font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.72rem;
}
.up-card ul {
  list-style: none; padding: 0; margin: 0;
  font-size: 0.74rem; color: var(--text-soft);
  display: flex; flex-direction: column; gap: 0.15rem;
}
.up-card .more { color: var(--muted-2); font-style: italic; }

/* New design tokens — match claude.ai/design workout.html bundle */
.page-head { display: flex; align-items: flex-end; justify-content: space-between;
             padding: 0 0 0.6rem; margin-bottom: 0.6rem; }
.head-actions { position: relative; }
.head-actions .ghost {
  background: transparent; color: var(--muted);
  border: 1px solid var(--line); border-radius: 6px;
  padding: 0.4rem 0.7rem; font-size: 0.82rem; cursor: pointer;
  font-family: inherit;
}
.head-actions .ghost:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.head-actions .ghost:disabled { opacity: 0.5; cursor: wait; }
.swap-menu {
  position: absolute; top: 36px; right: 0; z-index: 20;
  background: var(--surface, #1B2331);
  border: 1px solid var(--line); border-radius: 10px; padding: 4px;
  min-width: 220px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  display: flex; flex-direction: column; gap: 2px;
}
.swap-item {
  display: flex; flex-direction: column; align-items: flex-start;
  background: transparent; border: none; padding: 8px 10px;
  border-radius: 6px; cursor: pointer; color: var(--text);
  font-family: inherit; text-align: left;
}
.swap-item:hover { background: var(--bg-2, rgba(255,255,255,0.04)); }
.swap-item strong { font-weight: 600; font-size: 0.9rem; }
.swap-item .dim { font-size: 0.78rem; color: var(--muted); margin-top: 0.1rem; }
.page-head h1 { font-size: 1.2rem; margin: 0; line-height: 1; font-weight: 600; }
.page-head.compact .title-block {
  display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;
}
.page-head.compact .eyebrow {
  font-size: 0.7rem; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
.head-pip {
  background: var(--bg-2); color: var(--muted);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 0.2rem 0.55rem; font-size: 0.78rem;
  font-feature-settings: "tnum";
}
.status-pip {
  background: var(--bg-2); color: var(--muted);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 0.18rem 0.55rem; font-size: 0.7rem;
  text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
}
.status-pip.s-completed { color: #22c55e; border-color: rgba(34,197,94,0.3); }
.status-pip.s-skipped { color: #94a3b8; border-color: rgba(148,163,184,0.3); }
.status-pip.s-in_progress { color: #f59e0b; border-color: rgba(245,158,11,0.3); }
.swap-divider { height: 1px; background: var(--line); margin: 4px 2px; }
.hint.subtle { font-size: 0.78rem; color: var(--muted); margin: 0 0 0.5rem; }
.ctx-meta {
  display: flex; gap: 0.6rem; font-size: 0.78rem;
  color: var(--muted); margin: 0.4rem 0 0.6rem;
}
.bottom-helpers {
  display: flex; flex-direction: column; gap: 0.35rem;
  margin-top: 1rem; padding-top: 0.7rem;
  border-top: 1px solid var(--line);
}

.timer-cell { text-align: center; }
.countdown-block {
  display: inline-flex; align-items: baseline; gap: 0.4rem;
  padding: 0.3rem 0.8rem;
  background: rgba(167, 139, 250, 0.12);
  border: 1px solid rgba(167, 139, 250, 0.35);
  border-radius: 8px;
}
.countdown { font-size: 1.2rem; font-weight: 600; color: #a78bfa;
             font-feature-settings: "tnum"; }
.dim.small { font-size: 0.78rem; color: var(--muted); }

.week-strip {
  display: flex; gap: 0.4rem; margin: 0.4rem 0 0.8rem;
  justify-content: space-between;
}
.week-strip .day {
  flex: 1; padding: 0.5rem 0.3rem; text-align: center;
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 8px; cursor: default;
  display: flex; flex-direction: column; align-items: center; gap: 0.4rem;
}
.week-strip .day .dow {
  font-size: 0.68rem; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
}
.week-strip .day .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--line);
}
.week-strip .day.today { border-color: var(--accent, #ef4444); }
.week-strip .day.today .dow { color: var(--text); }
.week-strip .day.completed .dot { background: #22c55e; }
.week-strip .day.in_progress .dot { background: #f59e0b; }
.week-strip .day.skipped .dot { background: #94a3b8; }
.week-strip .day.planned .dot { background: var(--accent, #ef4444); }
.week-strip .day.projected .dot {
  background: transparent; border: 1.5px solid var(--accent, #ef4444);
}
.week-strip .day.past:not(.completed):not(.in_progress):not(.skipped) {
  opacity: 0.55;
}

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

/* Soft sleep-stale warning banner */
.stale-banner {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.55rem 0.8rem; margin: 0 0 0.7rem;
  background: rgba(250, 204, 21, 0.07);
  border: 1px solid rgba(250, 204, 21, 0.35);
  border-left: 3px solid #facc15;
  border-radius: 8px; color: var(--text);
}
.stale-icon { color: #facc15; font-size: 1.05rem; }
.stale-text { flex: 1; font-size: 0.83rem; line-height: 1.35; }
.fast-banner {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.55rem 0.8rem; margin: 0 0 0.7rem;
  background: rgba(245, 158, 11, 0.07);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-left: 3px solid #f59e0b;
  border-radius: 8px; color: var(--text);
}
.fast-icon { color: #f59e0b; font-size: 1.05rem; }
.fast-text { flex: 1; font-size: 0.83rem; line-height: 1.35; }

/* Workout-complete confirmation dialog */
.cd-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  z-index: 100; padding: 1rem;
}
.cd-card {
  background: var(--bg-0); border: 1px solid var(--line);
  border-radius: 12px; padding: 1.5rem; max-width: 24rem; width: 100%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}
.cd-card h2 { margin: 0 0 0.5rem; font-size: 1.15rem; color: var(--text); }
.cd-sub { color: var(--text-soft); font-size: 0.88rem; line-height: 1.45;
          margin: 0 0 1rem; }
.cd-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
</style>
