<script setup lang="ts">
/**
 * /workout/strength/today — full plan view that handles every workout state
 * via one component: planned (preview + start), in_progress (active workout
 * with set logging + rest timer), completed (summary).
 */
import { toLocalISO } from "@/dates";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { releaseWakeLock, requestWakeLock } from "@/wakeLock";
import BodyMap from "@/components/BodyMap.vue";
import { useRouter } from "vue-router";
import {
  Play, Pause, RotateCw, Plus, Minus, Check, MoreVertical, Sparkles, Hourglass,
  Feather, Info, ChevronDown, ChevronRight,
} from "lucide-vue-next";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import { api } from "@/api/client";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { useConfirm } from "@/useConfirm";
import { isNeon } from "@/theme";
import { apiBase, queryToken } from "@/config";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import CoachCard from "@/components/CoachCard.vue";
import ExerciseDemo from "@/components/ExerciseDemo.vue";
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
// PR-1: transient "🏆 PR" flash keyed "<wexId>-<setNum>" → label, cleared
// after a few seconds. Only appears the moment a record is actually beaten.
const prFlash = ref<Record<string, string>>({});

// OG2-A9: which logged set is currently being corrected, keyed
// `<wexId>-<setNumber>`. Null when nothing is being edited.
//
// Hoisted here rather than held per-row: every mutation ends in `loadAll()`,
// and state living inside the v-for is dropped when the list re-renders —
// the same slot-churn failure the CoachCard state was hoisted to escape.
/**
 * OG2-C2: what this week's muscle volume becomes once today's session is
 * done, shaped for the existing BodyMap rather than a second diagram.
 *
 * The audit alone counts LOGGED sets, so it can only describe a gap already
 * trained around. Shown here — on the planning surface, before the session —
 * it is the same figure while it can still be acted on.
 */
/** OG2-D-7: the generator's notes, collapsed. One entry per decision it
 *  made, so a normal strength day carries four and prints nine lines of
 *  prose above the first exercise. Counted rather than previewed — a note
 *  cut mid-sentence reads as a rendering fault. */
const notesOpen = ref(false);
const planNotes = computed(() =>
  (workout.value?.notes ?? "").trim().split("\n").filter((l) => l.trim()),
);

const projectedMuscles = computed(() => {
  const p = workout.value?.projected_muscle_volume;
  if (!p || !Object.keys(p).length) return null;
  return Object.fromEntries(
    Object.entries(p).map(([m, v]) => [m, {
      status: v.status_projected ?? v.status,
      sets: v.sets_projected ?? v.sets,
      mev: v.mev, mav: v.mav,
    }]),
  );
});

const editingSet = ref<string | null>(null);
function isEditing(wexId: number, n: number): boolean {
  return editingSet.value === `${wexId}-${n}`;
}
function beginEdit(wexId: number, n: number): void {
  editingSet.value = `${wexId}-${n}`;
}
function cancelEdit(): void {
  editingSet.value = null;
}
/** True while any set of this exercise is being corrected, so the finished
 *  chip summary yields back to the full table. */
function isEditingExercise(wex: StrengthWorkoutExercise): boolean {
  return editingSet.value?.startsWith(`${wex.id}-`) ?? false;
}
/** Reopen a completed exercise for correction, on its last logged set —
 *  the one a typo is most often noticed in, and the one nearest the tap. */
function reopenExercise(wex: StrengthWorkoutExercise): void {
  const last = [...wex.sets]
    .filter((s: { actual_reps: number | null }) => s.actual_reps != null)
    .sort((a: { set_number: number }, b: { set_number: number }) => a.set_number - b.set_number)
    .pop() as { set_number: number } | undefined;
  if (last) beginEdit(wex.id, last.set_number);
}

// Set-logging state, keyed by `${wexId}-${setNum}`
interface SetEntry {
  weight: string;   // string so empty input doesn't show "0"
  reps: string;
  rating: number | null;
  setType: string;  // working | warmup | drop | failure (SETTYPE-1)
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

// TD-10 — append an off-plan exercise.
//
// There was no route that added an exercise to a session at all: swap is
// strictly 1:1 and refuses once a set is logged, so three extra sets of curls
// done in the moment had nowhere to go. That meant they were missing from
// tonnage, the weekly volume audit, personal records, the four-week rotation
// map and every AI payload — the work happened and the app never knew.
const addOpen = ref(false);
const addBusy = ref(false);
const addError = ref("");
const addQuery = ref("");

function openAdd() {
  addError.value = "";
  addQuery.value = "";
  addOpen.value = true;
}
function closeAdd() { addOpen.value = false; }

const addCandidates = computed<StrengthExercise[]>(() => {
  if (!workout.value) return [];
  const inWorkout = new Set(workout.value.exercises.map((x) => x.exercise_id));
  const q = addQuery.value.trim().toLowerCase();
  return Object.values(catalogById.value)
    .filter((e) => !inWorkout.has(e.id))
    .filter((e) => !q
      || e.name.toLowerCase().includes(q)
      || (e.primary_muscle ?? "").toLowerCase().includes(q))
    .sort((a, b) => a.name.localeCompare(b.name))
    .slice(0, 20);
});

async function addExercise(exerciseId: string) {
  if (!workout.value) return;
  addBusy.value = true;
  addError.value = "";
  try {
    // The server prescribes the weight from history — never guess it here.
    // A client-side number would disagree with the server on the next load.
    await api.addStrengthExercise(workout.value.id, exerciseId);
    await loadAll();
    closeAdd();
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      addError.value = resp?.data?.detail ?? `HTTP ${resp?.status}`;
    } else {
      addError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    addBusy.value = false;
  }
}

async function removeExercise(wexId: number) {
  addError.value = "";
  try {
    await api.deleteStrengthExercise(wexId);
    await loadAll();
  } catch (e: unknown) {
    // The 409 body explains itself ("skip it instead") — surface it verbatim
    // rather than inventing a generic failure message.
    const resp = (e && typeof e === "object" && "response" in e)
      ? (e as { response?: { data?: { detail?: string } } }).response
      : null;
    addError.value = resp?.data?.detail
      ?? (e instanceof Error ? e.message : String(e));
  }
}

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
  // OG3-C1 — every failure path here used to end in a bare `return` or a
  // console warning, so a tap on "Accept swap" that could not be honoured
  // did nothing at all and looked like an unresponsive button. The swaps
  // themselves are now validated server-side before the card renders, so
  // reaching one of these branches is genuinely unexpected — which is
  // precisely why it should say so rather than go quiet.
  swapError.value = "";
  if (!workout.value) {
    swapError.value = "No workout loaded — reload and try again.";
    return;
  }
  const wex = workout.value.exercises.find(
    (x) => x.exercise_id === p.targetExerciseId,
  );
  if (!wex) {
    swapError.value =
      "That exercise is no longer in today's plan — the suggestion is stale.";
    return;
  }
  try {
    await api.swapStrengthExercise(wex.id, p.replacementExerciseId);
    await loadAll();
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { detail?: string }; status?: number } })
      .response;
    swapError.value = resp?.data?.detail
      ?? (e instanceof Error ? e.message : String(e));
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

// OG2-A7: anchored to a wall-clock deadline, not decremented once per tick.
// A tick counter is only right if every tick fires, and a background tab is
// throttled to roughly one a minute — so leaving the page and coming back
// showed a rest far longer than the one actually taken. The phone has
// anchored to an epoch since it was written; this is the web catching up,
// and it is why the two surfaces disagreed about how long a rest was.
let restEndsAt = 0;
// A rest that has already chimed must not chime again when the tab is
// refocused and the deadline is re-evaluated. Mirrors the phone's
// `lastNotifiedFor`, keyed on the deadline so a NEW rest still fires.
let lastNotifiedFor = 0;

function tickRest() {
  if (!restEndsAt) return;
  const left = Math.max(0, Math.ceil((restEndsAt - Date.now()) / 1000));
  restRemaining.value = left;
  if (left <= 0 && restEndsAt !== lastNotifiedFor) {
    lastNotifiedFor = restEndsAt;
    chime();
    notifyDone(restTotal.value);
    // Vibrate (Android Chrome only)
    if ("vibrate" in navigator) navigator.vibrate([200, 80, 200]);
    // UI-2: the ring stays on "Rest complete" (Lime) until the next set is
    // logged or Skip is tapped, instead of vanishing the instant it hits 0 —
    // the moment the rest ends is exactly when you glance back at the page.
    haltRestTick();
  }
}
function haltRestTick() {
  if (restHandle !== null) { clearInterval(restHandle); restHandle = null; }
  document.removeEventListener("visibilitychange", tickRest);
  restEndsAt = 0;
}

function startRest(seconds: number) {
  stopRest();
  restTotal.value = seconds;
  restEndsAt = Date.now() + seconds * 1000;
  restRemaining.value = seconds;
  restHandle = window.setInterval(tickRest, 1000);
  // A throttled tab may not tick for a minute, so re-read the deadline the
  // moment it comes back rather than waiting for the next interval.
  document.addEventListener("visibilitychange", tickRest);
}
function stopRest() {
  if (restHandle !== null) { clearInterval(restHandle); restHandle = null; }
  document.removeEventListener("visibilitychange", tickRest);
  restEndsAt = 0;
  restRemaining.value = null;
}
function addRest(s: number) {
  if (!restEndsAt) return;  // a finished rest is not extended
  restEndsAt += s * 1000;
  restTotal.value += s;
  tickRest();
}
onUnmounted(stopRest);

// OG2-A8: hold the screen on for exactly as long as a workout is running.
//
// Keyed on the workout's own status rather than on this component being
// mounted. Mounted is the easy key and the wrong one — it pins the display
// awake while the user reads a rest-day plan or a finished session, which is
// the leak the Compose side had.
//
// `paused` deliberately releases: WP-14 pause means the user has stepped
// away, which is the one moment during a session when the screen should be
// allowed to sleep.
const workoutRunning = computed(() => workout.value?.status === "in_progress");
watch(workoutRunning, (running) => {
  if (running) requestWakeLock();
  else releaseWakeLock();
}, { immediate: true });
onUnmounted(releaseWakeLock);

// Week strip. The projected-day pattern is no longer derived here — see
// the OG2-A4 note in weekStrip; it comes from `upcoming`, which is the
// generator's own schedule.
const recentWorkouts = ref<Array<{ date: string; status: string }>>([]);
const upcoming = ref<Awaited<ReturnType<typeof api.strengthUpcoming>>["upcoming"]>([]);

async function loadAll() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  // A skip refusal describes the plan as it was; once we refetch, the sets
  // it complained about may be gone. Clearing here stops a stale 409 from
  // sitting on the card for the rest of the session.
  skipError.value = null;
  try {
    // The equipment payload was fetched only to read days_per_week for the
    // week strip's projected-day pattern; the strip now reads the server's
    // schedule via `upcoming`, so the request is gone with it (OG2-A4).
    const [w, r, cat, hist, up] = await Promise.all([
      api.strengthToday(),
      api.strengthRecovery().catch(() => null),
      api.strengthExercises().catch(() => ({ count: 0, exercises: [] as StrengthExercise[] })),
      api.strengthWorkouts({ limit: 30 }).catch(() => ({ count: 0, workouts: [] })),
      api.strengthUpcoming(7, 4).catch(() => ({ count: 0, upcoming: [] })),
    ]);
    workout.value = w;
    recovery.value = r;
    catalogById.value = Object.fromEntries(cat.exercises.map((e) => [e.id, e]));
    recentWorkouts.value = hist.workouts.map((x) => ({ date: x.date, status: x.status }));
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
            setType: s.set_type ?? "working",
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

// PDF-1: print / save-as-PDF today's workout. Renders a self-contained
// document into a fresh window and prints THAT — avoids polluting the
// app's global CSS with an @media print rule (which would otherwise blank
// out printing on every other route). The browser's print dialog handles
// the actual PDF export ("Save as PDF").
function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string
  ));
}
function printWorkout() {
  const w = workout.value;
  if (!w || !w.exercises.length) return;
  const title = `${w.split_focus.charAt(0).toUpperCase()}${w.split_focus.slice(1).replace("_", " ")} day`;
  // Parse w.date ("YYYY-MM-DD") as a LOCAL date. `new Date("YYYY-MM-DD")`
  // parses as UTC midnight, so west-of-UTC users would print the previous
  // calendar day (and disagree with the phone export, which uses the raw
  // string). Split + construct with local components to match the day the
  // rest of the UI shows.
  const [dy, dm, dd] = w.date.split("-").map(Number);
  const dateStr = new Date(dy, dm - 1, dd).toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });
  const rows = w.exercises.map((wex, i) => {
    const rep = wex.target_reps_low === wex.target_reps_high
      ? `${wex.target_reps_low}`
      : `${wex.target_reps_low}-${wex.target_reps_high}`;
    const unit = wex.is_timed ? "s" : "";
    const wt = wex.target_weight_lb ? `${wex.target_weight_lb} lb` : "—";
    const notes = [wex.program_scheme, wex.load_hint].filter(Boolean).join(" · ");
    // SKIP-1: a declined slot still prints — the sheet is the day's plan,
    // and blanking the row would renumber everything against the screen —
    // but it prints as declined, with the write-in box filled in for you.
    // Handing someone a worksheet inviting them to log a slot they already
    // said no to is the same lie the on-screen live table used to tell.
    const logged = wex.skipped ? "Skipped" : "";
    return `<tr${wex.skipped ? ' class="skipped"' : ""}><td>${i + 1}</td>`
      + `<td>${escapeHtml(exName(wex.exercise_id))}</td>`
      + `<td>${wex.target_sets} × ${rep}${unit}</td><td>${wt}</td>`
      + `<td>${escapeHtml(notes)}</td><td class="log">${logged}</td></tr>`;
  }).join("");
  const notesBlock = w.notes ? `<p class="notes">${escapeHtml(w.notes)}</p>` : "";
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)} — ${escapeHtml(dateStr)}</title>`
    + `<style>`
    + `*{box-sizing:border-box} body{font-family:system-ui,-apple-system,sans-serif;color:#000;margin:1.4cm}`
    + `h1{font-size:20px;margin:0 0 2px} .date{font-size:12px;color:#333;margin:0 0 14px}`
    + `table{width:100%;border-collapse:collapse;font-size:12px}`
    + `th,td{border:1px solid #999;padding:5px 7px;text-align:left;vertical-align:top}`
    + `th{background:#eee;font-weight:600} td.log,th.log{width:22%}`
    + `tr.skipped td{color:#777} tr.skipped td.log{font-style:italic}`
    + `.notes{font-size:11px;color:#333;font-style:italic;margin:14px 0 0}`
    + `.foot{font-size:10px;color:#888;margin:18px 0 0}`
    + `@page{margin:1.4cm}`
    + `</style></head><body>`
    + `<h1>${escapeHtml(title)}</h1><p class="date">${escapeHtml(dateStr)}</p>`
    + `<table><thead><tr><th>#</th><th>Exercise</th><th>Sets × Reps</th><th>Weight</th><th>Notes</th><th class="log">Logged</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>${notesBlock}`
    + `<p class="foot">myvitals · generated ${escapeHtml(new Date().toLocaleDateString())}</p>`
    + `</body></html>`;
  // Render into a hidden iframe rather than a popup window — a new window
  // can be silently blocked by the browser (leaving Print a no-op). An
  // iframe has no popup blocker to defeat. srcdoc fires onload reliably.
  const iframe = document.createElement("iframe");
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  iframe.srcdoc = html;
  iframe.onload = () => {
    const cw = iframe.contentWindow;
    if (!cw) { iframe.remove(); return; }
    cw.focus();
    cw.onafterprint = () => iframe.remove();
    cw.print();
    // Fallback cleanup if onafterprint never fires (some browsers).
    window.setTimeout(() => { if (document.body.contains(iframe)) iframe.remove(); }, 60000);
  };
  document.body.appendChild(iframe);
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
/** OG3-B3 — "per side" when the server says the rep target is per side.
 *
 *  Distinct from `bilateralSideLabel` below, which is the mobility
 *  mechanism: that one doubles `target_sets` and labels the two rows R/L.
 *  This one changes no numbers at all — it states what the existing rep
 *  count counts. */
function sideLabel(wex: StrengthWorkoutExercise): string | null {
  return wex.planned_sets?.find((p) => p.per_side)?.side_label ?? null;
}

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
  if (isPaused.value) return;  // WP-14: resume before starting a hold
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
            // Audible + haptic at zero. The rest timer already chimes on
            // completion; timed holds didn't until now — a hold running
            // full-screen across the room needs the beep to signal "release".
            chime();
            try { navigator.vibrate?.(200); } catch { /* no-op */ }
            // Auto-log: full hold completed, no weight, rating=4 (smooth).
            const e = entry(targetWex, setN);
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
// Full-screen hold format — always mm:ss at 60s+, bare seconds under 60,
// so the giant number reads cleanly across the room.
function fmtHold(s: number): string {
  if (s >= 60) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return String(s);
}

// The one timed hold currently counting down (non-finished). Drives the
// full-screen overlay. Realistically only one runs at a time — the UI
// only exposes a single Start per row and a hold blocks the screen.
const activeTimer = computed<{
  wex: StrengthWorkoutExercise;
  setNum: number;
  remaining: number;
  totalS: number;
  fraction: number;   // 0 → 1 elapsed, for the progress ring
} | null>(() => {
  if (!workout.value) return null;
  for (const [key, st] of Object.entries(timers.value)) {
    if (st.finished) continue;
    const [wexIdStr, setStr] = key.split("-");
    const wexId = Number(wexIdStr);
    const setNum = Number(setStr);
    const wex = workout.value.exercises.find((x) => x.id === wexId);
    if (!wex) continue;
    // tickNow keeps this reactive each second.
    const remaining = Math.max(0, Math.ceil((st.endsAt - tickNow.value) / 1000));
    const fraction = st.totalS > 0
      ? Math.min(1, Math.max(0, 1 - remaining / st.totalS))
      : 0;
    return { wex, setNum, remaining, totalS: st.totalS, fraction };
  }
  return null;
});

// Overlay "Done" — finish the hold now, logging the elapsed seconds like
// the auto-finish (rating 4), then close. Uses whatever time has already
// elapsed rather than the full target.
async function finishTimedNow(wex: StrengthWorkoutExercise, setNum: number) {
  const st = timers.value[timerKey(wex.id, setNum)];
  const total = st?.totalS ?? wex.target_reps_low;
  const remaining = timerRemaining(wex.id, setNum) ?? 0;
  const elapsed = Math.max(1, total - remaining);
  chime();
  const e = entry(wex, setNum);
  e.weight = "";
  e.reps = String(elapsed);
  e.rating = 4;
  stopTimer(wex.id, setNum);
  await logSet(wex, setNum).catch((err) => { error.value = String(err); });
}

// Overlay "Fail" — route through the existing fail path (confirm + rating 1),
// then stop the timer + close the overlay.
async function failTimedNow(wex: StrengthWorkoutExercise, setNum: number) {
  const proceeded = await logFailed(wex, setNum);
  if (proceeded) stopTimer(wex.id, setNum);
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

async function regenerate(force = false, forceFullWeight = false) {
  busy.value = "regen";
  error.value = "";
  try {
    workout.value = await api.regenerateStrengthToday(force, forceFullWeight);
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

  // OG2-A4: which days are training days is the SERVER's answer, not one
  // this component works out. There were four copies of the weekday table —
  // the generator's, the /upcoming endpoint's, this one and the phone's —
  // and the last three agreed with each other while disagreeing with the
  // generator, which is the only one that decides what actually gets made.
  // At days_per_week=2 they promised Thursday against the generator's
  // Friday. They also knew only "training day or not", so a cardio or yoga
  // day read as a blank.
  //
  // `upcoming` is the generator's own schedule, simulated, and already
  // fetched for the cards at the bottom of this screen. Rest days are
  // absent from it by construction, so membership is the whole test.
  const projectedDates = new Set(upcoming.value.map((u) => u.date));

  for (let offset = -3; offset <= 3; offset++) {
    const d = new Date(today);
    d.setDate(today.getDate() + offset);
    // LOCAL: this key indexes histByDate, so after 7pm Central the
    // "Today" chip matched TOMORROW and the week strip showed the
    // wrong session status against each day.
    const iso = toLocalISO(d);
    const label = offset === 0 ? "Today"
      : d.toLocaleDateString(undefined, { weekday: "short" });
    const past = d.getTime() < todayMs;
    const status = histByDate[iso] ?? null;
    const projected = !past && status === null && projectedDates.has(iso);
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

// WP-16 — four-button rating. "Failed" is the dedicated red action in
// the row; the chooser offers the three non-failed outcomes. Values map
// onto the backend progression thresholds (Hard=2 hold, Good=4 +rep,
// Easy=5 +weight); historical 1–5 RPE data still renders via ratingLabel.
const confirmState = useConfirm();
const ask = confirmState.ask;

const RATING_CHOICES: { v: number; label: string; title: string }[] = [
  { v: 2, label: "Hard", title: "Hard — finished it with nothing in the tank. Weight stays next time." },
  { v: 4, label: "Good", title: "Good — solid, a couple reps left. Adds a rep next time." },
  { v: 5, label: "Easy", title: "Easy — several reps left. Adds weight once you top the rep range." },
];
function ratingLabel(r: number | null): string {
  if (r == null) return "—";
  return { 1: "Failed", 2: "Hard", 3: "Good", 4: "Good", 5: "Easy" }[r] ?? `RPE ${r}`;
}

function entryKey(wexId: number, setNum: number) { return `${wexId}-${setNum}`; }

/** The server's prescription for one set, or null if it did not send one.
 *
 *  TD-6 — this view used to seed every input from the flat slot target with
 *  no rating, while the phone inherited from the most recently logged set of
 *  the same exercise and pre-selected a rating of 4. Same workout, same
 *  screen, two different starting values. The cascade now lives in
 *  `_planned_sets` server-side and both surfaces render its answer. */
function plannedSet(wex: StrengthWorkoutExercise, setNum: number) {
  return wex.planned_sets?.find((ps) => ps.set_number === setNum) ?? null;
}

function entry(wex: StrengthWorkoutExercise, setNum: number): SetEntry {
  const key = entryKey(wex.id, setNum);
  if (!setEntries.value[key]) {
    const ps = plannedSet(wex, setNum);
    setEntries.value[key] = {
      // Fall back to the flat target only when talking to a backend older
      // than this release; the seeded values are the server's job.
      weight: (ps?.prefill_weight_lb ?? wex.target_weight_lb)?.toString() ?? "",
      reps: (ps?.prefill_reps ?? wex.target_reps_low).toString(),
      rating: ps?.prefill_rating ?? null,
      setType: ps?.set_type ?? "working",
    };
  }
  return setEntries.value[key];
}
function setRating(wexId: number, setNum: number, r: number) {
  const key = entryKey(wexId, setNum);
  if (!setEntries.value[key]) setEntries.value[key] = { weight: "", reps: "", rating: null, setType: "working" };
  setEntries.value[key].rating = r;
}

function isSetLogged(wex: StrengthWorkoutExercise, setNum: number): boolean {
  return wex.sets.some((s) => s.set_number === setNum && (s.actual_reps != null || s.skipped));
}

function isExerciseDone(wex: StrengthWorkoutExercise): boolean {
  // SKIP-1: a declined slot is accounted for — otherwise it reads as
  // "not started", keeps a live logging table open on a finished session
  // and steals the current-exercise highlight.
  if (wex.skipped) return true;
  for (let n = 1; n <= wex.target_sets; n++) {
    if (!isSetLogged(wex, n)) return false;
  }
  return true;
}

// A finished session isn't writable, whatever its slots look like.
const sessionOver = computed(() =>
  workout.value?.status === "completed" || workout.value?.status === "skipped"
);

// SKIP-1 — the single notion of a slot with nothing left to do: declined,
// fully accounted for, or belonging to a session that's over. Ordering, the
// NOW highlight and the render branch all read this one predicate so they
// can't disagree.
//
// The status arm is what fixes every workout completed *before* SKIP-1
// shipped: the server's close-remaining sweep only fires on the completed
// transition and is deliberately not retroactive, so those slots still
// arrive with skipped=false and no sets — and used to render a live
// logging table on a session finished weeks ago. Display truth only; it
// writes nothing.
function isSlotClosed(wex: StrengthWorkoutExercise): boolean {
  return isExerciseDone(wex) || sessionOver.value;
}

// Did the user account for any of this slot at all? Distinguishes a slot
// the session simply ran out of time for (nothing at all — the "Not logged"
// strip) from one carrying real, partial work, which must keep showing its
// set chips. Mirrors the phone's `wex.sets.none { it.actualReps != null ||
// it.skipped }` guard so the two surfaces branch identically.
function hasAccountedSets(wex: StrengthWorkoutExercise): boolean {
  return wex.sets.some((s) => s.actual_reps != null || s.skipped);
}

// SKIP-1: progress counters are server-computed and rendered verbatim.
// Both surfaces used to derive them locally with different rules (the web
// pip excluded individually-skipped sets, the phone's counted them), so
// the same session could read differently depending on where you looked.
const completedSetsCount = computed(() => workout.value?.sets_done ?? 0);
const totalSetsCount = computed(() => workout.value?.sets_total ?? 0);
const doneExercisesCount = computed(() => workout.value?.exercises_done ?? 0);
const totalExercisesCount = computed(() => workout.value?.exercises_total ?? 0);

// Slots the user never put a rep into. Completing closes these out as
// skipped server-side, so the confirmation names them first — same
// definition as the backend's _close_remaining_exercises (a partially
// logged slot keeps its partial record and is left alone).
const unloggedExercises = computed<StrengthWorkoutExercise[]>(() =>
  workout.value?.exercises.filter(
    (wex) => !wex.skipped && !wex.sets.some((s) => s.actual_reps != null),
  ) ?? []
);

// Surface a "workout finished?" confirmation the moment the last
// prescribed set is logged. Less intrusive than auto-completing —
// user might want to add bonus sets — but more discoverable than the
// small "Complete workout" button at the bottom of the page. The same
// dialog doubles as the pre-flight confirmation when Complete is tapped
// with exercises still unlogged.
const showCompleteDialog = ref(false);
const completeDialogDismissed = ref(false);
// Which of the two prompts is on screen. They share a card but not a
// dismiss: backing out of the Complete pre-flight must change *nothing*,
// while dismissing the auto prompt latches so it doesn't re-pop.
const completeDialogMode = ref<"auto" | "preflight">("auto");
const allSetsDone = computed(() =>
  totalSetsCount.value > 0
  && completedSetsCount.value >= totalSetsCount.value
);
watch(allSetsDone, (done, prev) => {
  if (done && !prev && !completeDialogDismissed.value
      && workout.value && workout.value.status !== "completed") {
    completeDialogMode.value = "auto";
    showCompleteDialog.value = true;
  }
});
// Complete CTA entry point: ask before closing out anything unlogged,
// finish straight away when every slot is already accounted for.
async function requestComplete() {
  if (unloggedExercises.value.length > 0) {
    completeDialogMode.value = "preflight";
    showCompleteDialog.value = true;
    return;
  }
  await completeWorkout(false);
}
async function finishFromDialog() {
  showCompleteDialog.value = false;
  await completeWorkout(true);
}
function dismissCompleteDialog() {
  showCompleteDialog.value = false;
  // Only the auto prompt latches: the user explicitly chose to keep going,
  // so honour that until the next workout. "Go back" on the pre-flight is a
  // pure cancel — routing it through here used to suppress the auto prompt
  // for the rest of the session as a side effect.
  if (completeDialogMode.value === "auto") completeDialogDismissed.value = true;
}

// Canonical confirmation copy, verbatim across web and phone. Assembled
// here rather than interpolated in the template so the singular / plural
// forms and the punctuation can't drift with the markup's whitespace.
// Names come from the catalog lookup that titles the cards — never slugs.
const completeDialogTitle = computed(() => {
  if (completeDialogMode.value !== "preflight") return "Workout complete?";
  return unloggedExercises.value.length === 1
    ? "Finish with unlogged exercise?"
    : "Finish with unlogged exercises?";
});
const completeDialogBody = computed(() => {
  if (completeDialogMode.value !== "preflight") {
    return `All ${totalSetsCount.value} prescribed sets accounted for. Finish `
      + "and stamp the session, or keep going if you want to add bonus work.";
  }
  const names = unloggedExercises.value.map((u) => exName(u.exercise_id)).join(", ");
  return unloggedExercises.value.length === 1
    ? `1 exercise unlogged: ${names}. Mark it skipped and finish?`
    : `${unloggedExercises.value.length} exercises unlogged: ${names}. `
      + "Mark them skipped and finish?";
});
const completeDialogDismissLabel = computed(() =>
  completeDialogMode.value === "preflight" ? "Go back" : "Keep going"
);

const currentExercise = computed(() => {
  if (!workout.value) return null;
  // Closed slots — done, declined, or belonging to a finished session —
  // never take the NOW highlight; it walks past them to the next real one,
  // and lands on nothing once the session is over.
  return workout.value.exercises.find((ex) => !isSlotClosed(ex)) ?? null;
});

// Swap and Skip share one guard: the slot has no real work logged against
// it and the session is still live. Once actuals exist they belong to
// this exercise, and neither rewriting nor hiding the slot is honest.
function canSkipOrSwap(wex: StrengthWorkoutExercise): boolean {
  if (sessionOver.value) return false;
  return !wex.sets.some((s) => s.actual_reps != null);
}

// Skip failures land on the offending card, not in the page-level `error`
// — that one sits ahead of the workout in the v-else-if chain, so setting
// it would swap the whole plan out for a one-line message.
const skipError = ref<{ wexId: number; message: string } | null>(null);

// Any skip PATCH in flight disables every Skip/Undo button, not just the one
// that was tapped. Each PATCH returns the whole workout as it looked when the
// server handled it, so two overlapping skips race their responses and the
// slower one lands last, wiping the other's flag until the next refresh.
// The in-flight *label* still keys off the specific slot.
const skipInFlight = computed(() => busy.value.startsWith("skip-ex-"));

// SKIP-1 — decline one slot, or undo. The response carries the whole
// workout with counters recomputed, so there's no reload here.
async function setExerciseSkipped(wex: StrengthWorkoutExercise, skipped: boolean) {
  busy.value = `skip-ex-${wex.id}`;
  skipError.value = null;
  try {
    workout.value = await api.patchStrengthWorkoutExercise(wex.id, { skipped });
  } catch (e: unknown) {
    // 409 = real sets already logged for this slot; the detail says how many.
    let message: string;
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      message = resp?.data?.detail ?? `HTTP ${resp?.status}`;
    } else {
      message = e instanceof Error ? e.message : String(e);
    }
    skipError.value = { wexId: wex.id, message };
  } finally {
    busy.value = "";
  }
}

/**
 * OG2-A9: this set did not happen — remove the row.
 *
 * Distinct from correcting it to zero reps, which leaves a row
 * `_accounted_sets` still counts, so the session reads as further along than
 * it is. And distinct from marking it skipped: SKIP-1 records that
 * `recent_mobility_history` reads a skipped set as a FAILED one and lowers
 * the next hold prescription after two, so a mistyped set marked skipped
 * would quietly make future cool-downs easier.
 *
 * Confirmed, because it destroys logged work and there is no undo. The
 * ad-hoc exercise remove nearby does not confirm, but that only ever removes
 * a slot the user added and has not touched.
 */
async function removeSet(wex: StrengthWorkoutExercise, setNum: number) {
  const logged = wex.sets.find((s: { set_number: number; id: number }) => s.set_number === setNum);
  if (!logged) return;
  // OG3-M5 — a rendered dialog, because this one is not reversible and
  // its consequence reaches further than the row on screen: the set feeds
  // the progression reducer, so deleting it changes what next session
  // prescribes. `window.confirm` gave that the same one-line treatment as
  // every other confirm in the app, with the destructive action focused.
  if (!(await ask({
    title: `Delete set ${setNum}?`,
    detail: "This removes it from your log, your records, and the history "
      + "next session's weight is calculated from.",
    confirmLabel: "Delete set",
  }))) return;
  busy.value = `set-${wex.id}-${setNum}`;
  try {
    await api.deleteStrengthSet(logged.id);
    cancelEdit();
    await loadAll();
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = "";
  }
}

async function logFailed(wex: StrengthWorkoutExercise, setNum: number): Promise<boolean> {
  // Shortcut: mark the set as failed (rating=1) using whatever weight is
  // already in the input. Reps default to whatever was entered (or the
  // target if unset) — what matters is the rating, which drives the
  // -7.5% deload on next session. Returns false if the user cancels the
  // confirm so callers (e.g. the timed-hold overlay) can keep the timer
  // running instead of closing on a no-op.
  const e = entry(wex, setNum);
  // OG3-M5 — same reasoning: the rating is the single input the whole
  // progression policy runs on, and this one deliberately moves it down.
  if (!(await ask({
    title: `Mark set ${setNum} as failed?`,
    detail: "Next session's weight for this exercise will drop by about 7.5%.",
    confirmLabel: "Mark failed",
  }))) return false;
  e.rating = 1;
  await logSet(wex, setNum);
  return true;
}

async function logSet(wex: StrengthWorkoutExercise, setNum: number, skipped = false) {
  if (isPaused.value) return;  // WP-14: resume before logging
  const e = entry(wex, setNum);
  busy.value = `set-${wex.id}-${setNum}`;
  try {
    const res = await api.logStrengthSet({
      workout_exercise_id: wex.id,
      set_number: setNum,
      target_weight_lb: wex.target_weight_lb,
      target_reps: wex.target_reps_low,
      actual_weight_lb: skipped ? null : (parseFloat(e.weight) || null),
      actual_reps: skipped ? null : (parseInt(e.reps, 10) || null),
      rating: skipped ? null : e.rating,
      skipped,
      set_type: e.setType,
    });
    // OG2-A7: the server decides, having just written the set and knowing
    // the whole session. It used to be decided here — and identically but
    // separately in Kotlin — with a hard-coded 35 for the within-round
    // superset rest and no notion of the session being over, so finishing a
    // workout started a countdown while the user racked the weights.
    // 0 means there is nothing left to time.
    if (res.rest_after_s > 0) startRest(res.rest_after_s);
    // A correction closes its own editor. The server returns rest_after_s=0
    // for one, so the branch above is already silent — a typo does not earn
    // a rest and does not re-fire a PR badge.
    cancelEdit();
    await loadAll();
    // Flash the 🏆 badge only after loadAll() flips the row to logged (its
    // v-else branch), so the 5s window starts when the badge is actually
    // visible — not before, which on slow gym wifi could expire unseen.
    if (!skipped && (res.is_weight_pr || res.is_e1rm_pr)) {
      const key = `${wex.id}-${setNum}`;
      prFlash.value = { ...prFlash.value, [key]: res.is_weight_pr ? "PR" : "e1RM PR" };
      window.setTimeout(() => {
        const next = { ...prFlash.value };
        delete next[key];
        prFlash.value = next;
      }, 5000);
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = "";
  }
}

// LOG-1: faint "last time" summary from the previous session's working sets.
// Weight formatting mirrors the phone (whole → integer, else 1 decimal) so the
// same set never renders differently across surfaces.
function fmtGhostWeight(w: number): string {
  return Number.isInteger(w) ? String(w) : w.toFixed(1);
}
function lastSetsSummary(wex: StrengthWorkoutExercise): string | null {
  const ls = wex.last_sets;
  if (!ls || !ls.length) return null;
  return ls
    .map((s) => (s.weight_lb != null ? `${fmtGhostWeight(s.weight_lb)}×${s.reps}` : `${s.reps}`))
    .join(" · ");
}

/** OG3-A3 — when that last session was, and how it felt.
 *
 *  "last:" without a date reads as "last session"; the real gap on this
 *  history averages 31 days, so the line was quietly implying a recency it
 *  did not have. The rating is the input the progression policy acts on, so
 *  showing it makes the prefilled weight explicable rather than magic.
 *
 *  Built component-wise from `YYYY-MM-DD`. `new Date("2026-08-14")` parses as
 *  UTC midnight, which in Central is the previous evening — the same
 *  local-day boundary that has bitten `/summary/today` twice. */
function lastSetsWhen(wex: StrengthWorkoutExercise): string | null {
  const ls = wex.last_sets;
  const iso = ls?.find((s) => s.date)?.date;
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  const then = new Date(y, m - 1, d);
  const now = new Date();
  const days = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - then.getTime())
      / 86_400_000,
  );
  const when = days <= 0 ? "today"
    : days === 1 ? "yesterday"
    : days < 7 ? `${days}d ago`
    : then.toLocaleDateString(undefined, { month: "short", day: "numeric" });

  // One rating for the line, not one per set: the ghost is already a
  // compressed summary and a per-set rating list would be longer than the
  // weights it annotates. The worst rating is the honest one to show — a
  // session that ended in a failed set is not a session that felt "Easy".
  const rated = (ls ?? []).map((s) => s.rating).filter((r): r is number => r != null);
  const worst = rated.length ? Math.min(...rated) : null;
  return worst == null ? when : `${when} · ${ratingLabel(worst)}`;
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
  if (isNeon.value) {
    // Neon: map the stable hash onto the accent palette so superset
    // markers stay on-theme instead of landing on muddy HSL hues.
    const NEON_SS = ["#28e6ff", "#ff3ad8", "#5dff3b", "#ffb52e", "#6f7bff"];
    return NEON_SS[h % NEON_SS.length];
  }
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

// `closeRemaining` is always passed explicitly: this surface has a UI in
// which to ask, so it never leans on the server-side default (which exists
// for the phone's notification action).
async function completeWorkout(closeRemaining: boolean) {
  if (!workout.value) return;
  busy.value = "complete";
  try {
    await api.patchStrengthWorkout(workout.value.id, {
      status: "completed",
      completed_at: new Date().toISOString(),
      close_remaining: closeRemaining,
    });
    await loadAll();
    stopRest();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

// WP-14 pause/resume. Paused gates set logging until the user resumes;
// the backend folds the paused interval into total_paused_s so net
// training duration excludes time away.
const isPaused = computed(() => workout.value?.status === "paused");

async function pauseWorkout() {
  if (!workout.value) return;
  busy.value = "pause";
  try {
    await api.patchStrengthWorkout(workout.value.id, { status: "paused" });
    await loadAll();
    stopRest();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

async function resumeWorkout() {
  if (!workout.value) return;
  busy.value = "resume";
  try {
    await api.patchStrengthWorkout(workout.value.id, { status: "in_progress" });
    await loadAll();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}

// Cardio-day "Log this workout" — captures label + duration + ended-at,
// posts to complete-cardio which mints a manual Activity row that flows
// through the activity feed, HR chart markers, and cardio coach payload.
// Common cardio presets for the "Log this workout" dropdown. `type` is
// the canonical token stored on the Activity (drives the feed icon +
// analytics); `label` is the default display name (still editable).
// "Other" keeps type generic and lets the user type a custom name.
const CARDIO_PRESETS: { label: string; type: string }[] = [
  { label: "Les Mills VR", type: "les_mills_vr" },
  { label: "Other VR", type: "vr" },
  { label: "Rowing", type: "rowing" },
  { label: "Cycling", type: "cycling" },
  { label: "Elliptical", type: "elliptical" },
  { label: "Walk", type: "walk" },
  { label: "Other", type: "manual_cardio" },
];
const showCardioLog = ref(false);
const cardioType = ref("les_mills_vr");
const cardioLabel = ref("");
const cardioDuration = ref(30);
// Ended-at picker: HH:MM in local time, default = current minute. Lets
// the user backdate a session so the HR-sample scan window covers the
// real workout instead of "right now".
const cardioEndedAt = ref("");
function localTimeNow(): string {
  const d = new Date();
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}`;
}
function openCardioLog() {
  cardioType.value = "les_mills_vr";
  cardioLabel.value = "Les Mills VR";
  cardioDuration.value = 30;
  cardioEndedAt.value = localTimeNow();
  showCardioLog.value = true;
}
function onCardioPreset() {
  const p = CARDIO_PRESETS.find((x) => x.type === cardioType.value);
  // Autofill the name from the preset, except "Other" (custom free-text).
  cardioLabel.value = p && p.type !== "manual_cardio" ? p.label : "";
}
function endedAtIso(): string {
  // Compose a same-day datetime from the user's HH:MM. If their picked
  // time is in the future (e.g. they pick 11:30 PM but it's 1 AM), roll
  // it back a day — feels less surprising than dropping a future Activity.
  const [hh, mm] = cardioEndedAt.value.split(":").map(Number);
  const d = new Date();
  d.setHours(hh, mm, 0, 0);
  if (d.getTime() > Date.now()) d.setDate(d.getDate() - 1);
  return d.toISOString();
}
async function submitCardioLog() {
  if (!workout.value) return;
  const label = cardioLabel.value.trim();
  const mins = Number(cardioDuration.value);
  if (!label || !mins || mins <= 0 || mins > 1440) return;
  const endedMs = new Date(endedAtIso()).getTime();
  const startIso = new Date(endedMs - mins * 60_000).toISOString();
  busy.value = "complete";
  try {
    await api.completeStrengthCardio(workout.value.id, {
      label,
      duration_minutes: mins,
      start_at: startIso,
      type: cardioType.value,
    });
    showCardioLog.value = false;
    await loadAll();
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

// ── UI-2: the active-workout layout ─────────────────────────────────────
//
// One focal "Now" hero instead of the NOW set buried in the Nth card, one
// segmented progress bar instead of a header pip + a second bar, one strip
// of chips instead of up to four stacked banners, and finished exercises
// collapsed to a line. Every number is still the server's (counters,
// session_summary, planned_sets prefill); the logging path is untouched.

const CYAN = "#28e6ff";
const LIME = "#5dff3b";
const AMBER = "#ffb52e";

function titleCase(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
const pageTitle = computed(() =>
  workout.value ? `${titleCase(workout.value.split_focus)} day` : "Workout",
);

/** Sets on this slot the user has dealt with (logged or individually
 *  skipped), capped at the prescription. Mirrors the backend's
 *  `_accounted_sets` and the phone's `accountedSets`; the workout-level
 *  counters still come from the server verbatim. */
function accountedSets(wex: StrengthWorkoutExercise): number {
  if (wex.skipped) return wex.target_sets;
  return Math.min(
    wex.sets.filter((s) => s.actual_reps != null || s.skipped).length,
    wex.target_sets,
  );
}

const byOrder = computed<StrengthWorkoutExercise[]>(() =>
  [...(workout.value?.exercises ?? [])].sort((a, b) => a.order_index - b.order_index),
);

/** v0.7.161 ordering, shared with the phone: incomplete slots first; a
 *  non-superset slot keeps its order_index place until all its sets are
 *  done, superset partners alternate by accounted-count (the partner who is
 *  behind goes next). Finished slots drop below for reference. The slot
 *  skip flag is deliberately not consulted — tapping Skip never moves a row. */
const orderedExercises = computed<StrengthWorkoutExercise[]>(() => {
  const all = byOrder.value;
  if (sessionOver.value) return all;
  const setsComplete = (w: StrengthWorkoutExercise) =>
    w.sets.filter((s) => s.actual_reps != null || s.skipped).length >= w.target_sets;
  const incomplete = all.filter((w) => !setsComplete(w));
  const complete = all.filter((w) => setsComplete(w));
  const groups = new Map<string, StrengthWorkoutExercise[]>();
  for (const w of incomplete) {
    const k = w.superset_id ?? `solo-${w.id}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(w);
  }
  const grouped = [...groups.entries()].map(([k, exs]) =>
    k.startsWith("solo-")
      ? exs
      : [...exs].sort((a, b) => accountedSets(a) - accountedSets(b) || a.order_index - b.order_index),
  );
  grouped.sort((a, b) =>
    Math.min(...a.map((x) => x.order_index)) - Math.min(...b.map((x) => x.order_index)));
  return [...grouped.flat(), ...complete];
});

// Tapping an up-next line makes it the hero's exercise (logging out of order
// was always allowed; this is the one-tap way in). Falls back to the natural
// NOW slot the moment the focused one closes.
const focusWexId = ref<number | null>(null);
const heroWex = computed<StrengthWorkoutExercise | null>(() => {
  if (!workout.value || sessionOver.value) return null;
  const f = focusWexId.value != null
    ? workout.value.exercises.find((x) => x.id === focusWexId.value) ?? null
    : null;
  if (f && !isSlotClosed(f)) return f;
  return orderedExercises.value.find((x) => !isSlotClosed(x)) ?? null;
});
/** The set the hero logs: the first prescribed set not yet accounted for. */
const heroSet = computed<number | null>(() => {
  const w = heroWex.value;
  if (!w) return null;
  for (let n = 1; n <= w.target_sets; n++) if (!isSetLogged(w, n)) return n;
  return null;
});
const heroEntry = computed<SetEntry | null>(() =>
  heroWex.value && heroSet.value != null ? entry(heroWex.value, heroSet.value) : null,
);
const heroPos = computed(() => {
  const w = heroWex.value;
  return w ? byOrder.value.findIndex((x) => x.id === w.id) + 1 : 0;
});
const heroOf = computed(() =>
  workout.value?.exercises_total || workout.value?.exercises.length || 0,
);
function focusExercise(wex: StrengthWorkoutExercise) {
  focusWexId.value = wex.id;
  heroEditing.value = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fmtLb(w: number | null | undefined): string {
  if (w == null || Number.isNaN(w)) return "—";
  return Number.isInteger(w) ? String(w) : String(Math.round(w * 100) / 100);
}
function repsRange(wex: StrengthWorkoutExercise): string {
  return wex.target_reps_low === wex.target_reps_high
    ? String(wex.target_reps_low)
    : `${wex.target_reps_low}–${wex.target_reps_high}`;
}
/** The prescription line for the hero ("47.5 lb × 8"). */
function heroTarget(wex: StrengthWorkoutExercise, n: number): string {
  const ps = plannedSet(wex, n);
  const reps = ps?.is_amrap ? `${wex.target_reps_low}+ (AMRAP)` : repsRange(wex);
  const w = ps?.target_weight_lb ?? wex.target_weight_lb;
  return w != null ? `${fmtLb(w)} lb × ${reps}` : `${reps} reps`;
}
function setHeading(wex: StrengthWorkoutExercise, n: number): string {
  const side = bilateralSideLabel(wex, n);
  const sideWord = side === "R" ? "Right side · " : side === "L" ? "Left side · " : "";
  return `${sideWord}Set ${n} of ${wex.target_sets}`;
}

// Steppers. UI-F4: the weight walks the server's load ladder — the weights
// the user's gear can actually make, from the same micro-loader rounder that
// set the prescription — so a tap can never land on an unloadable weight.
// With no ladder (an older server) it falls back to a fixed 2.5 lb. Reps
// step by 1. Typing any weight stays possible via the readout.
const heroEditing = ref(false);
const heroLadder = computed<number[] | null>(() => {
  const l = heroWex.value?.load_ladder_lb;
  return l && l.length ? l : null;
});
const heroTargetW = computed<number | null>(() => {
  const w = heroWex.value;
  if (!w) return null;
  const n = heroSet.value;
  return (n != null ? plannedSet(w, n)?.target_weight_lb : null) ?? w.target_weight_lb ?? null;
});
/** Bodyweight slot (no target, no ladder): no weight stepper. */
const showWeightStepper = computed(() => heroLadder.value != null || heroTargetW.value != null);
/** The weight one tap moves to, or null when the ladder has no rung that way. */
function nextWeight(up: boolean): number | null {
  const e = heroEntry.value;
  if (!e) return null;
  const typed = parseFloat(e.weight);
  const base = Number.isFinite(typed) ? typed : heroTargetW.value;
  const ladder = heroLadder.value;
  if (!ladder) return Math.max(0, (base ?? 0) + (up ? 2.5 : -2.5));
  if (base == null) return up ? ladder[0] : null;
  if (up) return ladder.find((w) => w > base + 0.01) ?? null;
  for (let i = ladder.length - 1; i >= 0; i--) if (ladder[i] < base - 0.01) return ladder[i];
  return null;
}
const weightDown = computed(() => nextWeight(false));
const weightUp = computed(() => nextWeight(true));
function stepWeight(up: boolean) {
  const e = heroEntry.value;
  const w = up ? weightUp.value : weightDown.value;
  if (!e || w == null) return;
  e.weight = fmtLb(w);
}
function stepReps(d: number) {
  const e = heroEntry.value;
  if (!e) return;
  e.reps = String(Math.max(0, (parseInt(e.reps, 10) || 0) + d));
}
const HERO_RATINGS: { v: number; label: string; color: string; title: string }[] = [
  { v: 1, label: "Fail", color: "#ff5d7a", title: "Failed — missed reps. Next session's weight drops about 7.5%." },
  ...RATING_CHOICES.map((r) => ({ ...r, color: r.v === 2 ? AMBER : r.v === 4 ? LIME : CYAN })),
];
function ratingColor(r: number | null): string {
  if (r == null) return "#9b9bb0";
  return r === 1 ? "#ff5d7a" : r === 2 ? AMBER : r === 5 ? CYAN : LIME;
}
const canLogHero = computed(() => {
  const e = heroEntry.value;
  return !!e && e.rating !== null && e.reps.trim() !== ""
    && !isPaused.value && busy.value !== `set-${heroWex.value?.id}-${heroSet.value}`;
});
/** "✓ Log set N" — the SAME logSet / logFailed paths the table always used,
 *  so offline buffering, progression, bilateral and the server's
 *  rest_after_s behave exactly as before. Fail keeps its confirmation. */
async function logHero() {
  const w = heroWex.value; const n = heroSet.value; const e = heroEntry.value;
  if (!w || n == null || !e) return;
  heroEditing.value = false;
  if (e.rating === 1) await logFailed(w, n);
  else await logSet(w, n);
}

// Rest ring inside the hero.
const resting = computed(() => restRemaining.value !== null);
const restDone = computed(() => restRemaining.value !== null && restRemaining.value <= 0);
const restFraction = computed(() =>
  restTotal.value > 0 && restRemaining.value != null
    ? Math.max(0, Math.min(1, restRemaining.value / restTotal.value)) : 0,
);

// One segmented bar: a segment per exercise, filled from what the slot has
// accounted for. The label is the server's counter, verbatim.
const segments = computed(() => byOrder.value.map((w) => {
  if (w.skipped) return { id: w.id, kind: "skipped", frac: 1 };
  const a = accountedSets(w);
  if (w.target_sets > 0 && a >= w.target_sets) return { id: w.id, kind: "done", frac: 1 };
  if (a > 0) return { id: w.id, kind: "partial", frac: a / Math.max(1, w.target_sets) };
  return { id: w.id, kind: "todo", frac: 0 };
}));

// The chip strip that replaces the stacked banners.
type ChipKey = "coach" | "fast" | "deload" | "paused" | "why";
const openChip = ref<ChipKey | null>(null);
function toggleChip(k: ChipKey) { openChip.value = openChip.value === k ? null : k; }
const sessionLive = computed(() =>
  workout.value?.status === "planned" || workout.value?.status === "in_progress");
const fastingActive = computed(() => {
  const f = workout.value?.fasting_context;
  return !!f && f.active && f.modulation !== "normal";
});
const deloadActive = computed(() =>
  !!workout.value && (workout.value.deload_factor ?? 1) < 1 && sessionLive.value);
const deloadPct = computed(() =>
  Math.round((1 - (workout.value?.deload_factor ?? 1)) * 100));
const deloadReasonLine = computed(() => {
  const r = workout.value?.deload_reason || "low recovery";
  return `${r.charAt(0).toUpperCase()}${r.slice(1)} — feeling strong?`;
});
const whyVisible = computed(() =>
  (planNotes.value.length > 0 && (workout.value?.exercises.length ?? 0) > 0)
  || workout.value?.recovery_score_used != null || workout.value?.sleep_h_used != null);
const chipsVisible = computed(() =>
  (!!queryToken.value && sessionLive.value) || fastingActive.value || deloadActive.value
  || isPaused.value || whyVisible.value);

// Finished exercises collapse to a line; tapping one expands its grid.
const expanded = ref<Set<number>>(new Set());
function toggleExpanded(id: number) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expanded.value = next;
}
/** Slots other than the hero that are still open — the "up next" lines. */
const upNext = computed(() =>
  orderedExercises.value.filter((w) => !isSlotClosed(w) && w.id !== heroWex.value?.id));
/** Closed slots — finished, declined, or on a session that is over. */
const closedSlots = computed(() =>
  (sessionOver.value ? byOrder.value : orderedExercises.value).filter((w) => isSlotClosed(w)));
function slotSummary(wex: StrengthWorkoutExercise): string {
  const logged = [...wex.sets]
    .filter((s) => s.actual_reps != null || s.skipped)
    .sort((a, b) => a.set_number - b.set_number);
  if (!logged.length) return "";
  if (isTimedExercise(wex)) {
    return logged.map((s) => (s.skipped ? "fail" : `${s.actual_reps}s`)).join(" · ");
  }
  return logged.map((s) => (s.skipped ? "fail"
    : s.actual_weight_lb != null ? `${fmtLb(s.actual_weight_lb)}×${s.actual_reps}` : `${s.actual_reps}`)).join(" · ");
}
function prescriptionShort(wex: StrengthWorkoutExercise): string {
  const unit = isTimedExercise(wex) ? "s" : "";
  const w = wex.target_weight_lb != null ? ` · ${fmtLb(wex.target_weight_lb)} lb` : "";
  return `${wex.target_sets}×${repsRange(wex)}${unit}${w}`;
}
/** Render list: the hero's exercise as a full card, then the other open
 *  slots as compact "up next" lines, then closed slots as one-line
 *  summaries (a summary expands to its full grid on tap, or while one of
 *  its sets is being corrected). */
type CardMode = "full" | "next" | "summary";
const cards = computed<{ wex: StrengthWorkoutExercise; mode: CardMode; head: string | null }[]>(() => {
  const out: { wex: StrengthWorkoutExercise; mode: CardMode; head: string | null }[] = [];
  if (heroWex.value) out.push({ wex: heroWex.value, mode: "full", head: null });
  upNext.value.forEach((w, i) => out.push({ wex: w, mode: "next", head: i === 0 ? "Up next" : null }));
  closedSlots.value.forEach((w, i) => out.push({
    wex: w,
    mode: !w.skipped && hasAccountedSets(w) && (expanded.value.has(w.id) || isEditingExercise(w))
      ? "full" : "summary",
    head: i === 0 ? (sessionOver.value ? "Exercises" : "Done") : null,
  }));
  return out;
});
function exPos(wex: StrengthWorkoutExercise): number {
  return byOrder.value.findIndex((x) => x.id === wex.id) + 1;
}
function isPhoto(slug: string): boolean {
  const u = imageUrl(slug, 0);
  return !!u && /\.jpe?g($|\?)/i.test(u);
}
function loggedSet(wex: StrengthWorkoutExercise, n: number) {
  return wex.sets.find((s) => s.set_number === n && s.actual_reps != null) ?? null;
}

// Completed-session hero tiles, from the server's session_summary.
const summary = computed(() => workout.value?.session_summary ?? null);
const tonnageText = computed(() =>
  summary.value ? `${Math.round(summary.value.total_volume_lb).toLocaleString()} lb` : "—");
const durationText = computed(() => {
  const s = summary.value?.net_duration_s;
  return s == null ? "—" : `${Math.round(s / 60)} min`;
});

const isCardioDay = computed(() =>
  !!workout.value && workout.value.exercises.length === 0
  && ["cardio", "active_recovery", "yoga"].includes(workout.value.split_focus));
const menuOpen = ref(false);
const started = computed(() =>
  completedSetsCount.value > 0 || workout.value?.status === "in_progress");

onMounted(loadAll);
useVisibilityRefresh(loadAll);
</script>


<template>
  <NeonPage :title="pageTitle" back="/train" class="strength-today">
    <template #trailing>
      <div class="menu-wrap">
        <button class="icon-btn" type="button" aria-label="More actions"
                :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
          <MoreVertical :size="20" />
        </button>
        <div v-if="menuOpen" class="menu-scrim" @click="menuOpen = false" />
        <div v-if="menuOpen" class="menu" role="menu" @click="menuOpen = false">
          <button v-if="workout && workout.exercises.length" role="menuitem"
                  title="Print this workout or save it as a PDF" @click="printWorkout">
            Print / Save PDF
          </button>
          <button v-if="workout && workout.status === 'planned'" role="menuitem"
                  :disabled="busy === 'regen'"
                  title="Re-runs the plan against the latest sleep / HRV / recovery / strength signals"
                  @click="regenerate(true)">
            {{ busy === 'regen' ? 'Regenerating…' : 'Regenerate plan' }}
            <span>re-pick exercises with same split</span>
          </button>
          <div class="menu-lbl">
            {{ swapBusyType ? `Switching to ${swapBusyType}…` : "Swap day" }}
          </div>
          <button role="menuitem" :disabled="swapBusyType !== null" @click="doSwap('strength')">
            Strength <span>auto-pick today's split</span>
          </button>
          <button role="menuitem" :disabled="swapBusyType !== null" @click="doSwap('yoga')">
            Yoga / mobility <span>5 poses, 45 s holds</span>
          </button>
          <button role="menuitem" :disabled="swapBusyType !== null" @click="doSwap('cardio')">
            Cardio <span>30-45 min Z2 effort</span>
          </button>
          <template v-if="workout && sessionLive">
            <div class="menu-sep" />
            <button v-if="completedSetsCount > 0 && !isCardioDay" role="menuitem"
                    :disabled="busy === 'pause'" @click="pauseWorkout">
              Pause workout <span>time away won't count</span>
            </button>
            <button role="menuitem" class="warn" :disabled="busy === 'defer'" @click="deferToday">
              Skip workout day <span>undoable from the skipped state</span>
            </button>
          </template>
        </div>
      </div>
    </template>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load today's plan.</p>

    <!-- Failure is not absence: a failed load never renders as "no plan".
         Amber, never rose — this is a connection problem, not a crisis. -->
    <button v-if="queryToken && error" class="errbanner" type="button" @click="loadAll">
      <b>{{ workout ? "Something didn't go through" : "Couldn't load today's workout" }}</b>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>

    <template v-if="!queryToken" />

    <!-- First load: the hero's shape, shimmering. Refreshes keep the page. -->
    <NeonHero v-else-if="loading && !workout" :accent="CYAN" class="sk-hero" aria-busy="true">
      <div class="sk" style="width: 150px; height: 11px" />
      <div class="sk" style="width: 70%; height: 24px; margin-top: 10px" />
      <div class="sk" style="width: 55%; height: 13px; margin-top: 8px" />
      <div class="sk" style="width: 80%; height: 44px; margin: 16px auto 0" />
      <div class="sk-row">
        <div class="sk" style="height: 40px" /><div class="sk" style="height: 40px" />
      </div>
      <div class="sk-row four">
        <div v-for="i in 4" :key="i" class="sk" style="height: 40px" />
      </div>
      <div class="sk" style="height: 48px; margin-top: 12px; border-radius: 14px" />
    </NeonHero>

    <template v-else-if="!workout">
      <NeonHero v-if="!error && recovery?.rest_day_recommended" :accent="AMBER">
        <div class="eyebrow amber">Rest day recommended</div>
        <p class="hero-text">{{ recovery.rest_day_reason }}.</p>
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
        <button class="btn-ghost wide" :disabled="busy === 'regen'" @click="regenerate(true)">
          {{ busy === 'regen' ? 'Generating…' : 'Generate anyway' }}
        </button>
      </NeonHero>
      <NeonHero v-else-if="!error" :accent="CYAN">
        <div class="eyebrow cyan">No plan yet</div>
        <h2 class="now-name">Today's workout</h2>
        <p class="hint">The planner builds it from your recovery, sleep and history.</p>
        <button class="btn-log" :disabled="busy === 'regen'" @click="regenerate(false)">
          <Play :size="16" /> {{ busy === 'regen' ? 'Generating…' : "Generate today's plan" }}
        </button>
      </NeonHero>
    </template>

    <template v-else>
      <!-- ONE progress bar: a segment per exercise. The count is the
           server's, verbatim — no second pip, no second bar. -->
      <div v-if="workout.exercises.length" class="seg-wrap"
           role="img" :aria-label="`${completedSetsCount} of ${totalSetsCount} sets done`">
        <div class="segs">
          <div v-for="sg in segments" :key="sg.id" class="seg" :class="sg.kind">
            <i :style="{ width: `${Math.round(sg.frac * 100)}%` }" />
          </div>
        </div>
        <span class="seg-label" :class="{ lime: allSetsDone }">
          {{ completedSetsCount }}/{{ totalSetsCount }} sets
        </span>
      </div>

      <!-- ── The hero ─────────────────────────────────────────────── -->
      <NeonHero v-if="workout.status === 'skipped'" accent="#9b9bb0" class="hero">
        <div class="eyebrow">Skipped</div>
        <p class="hero-text"><b>Skipped today's workout day.</b></p>
        <p class="hint">Tomorrow will generate fresh.</p>
        <button class="btn-ghost wide" :disabled="busy === 'undo'" @click="undoSkip">
          <RotateCw :size="14" /> {{ busy === 'undo' ? 'Restoring…' : 'Undo' }}
        </button>
      </NeonHero>

      <NeonHero v-else-if="workout.status === 'completed'" :accent="LIME" class="hero">
        <div class="hero-top">
          <div class="eyebrow lime">Workout complete</div>
          <button v-if="workout.exercises.length" class="btn-text" :disabled="busy === 'regen'"
                  title="Run the same plan again — wipes today's logged sets"
                  @click="regenerate(true)">
            <RotateCw :size="13" /> Redo
          </button>
        </div>
        <h2 class="now-name">{{ isCardioDay ? "Session logged" : "Nicely done" }}</h2>
        <div class="tiles">
          <NeonStat :value="tonnageText" label="Tonnage" :accent="LIME" />
          <NeonStat :value="summary ? String(summary.working_sets) : '—'" label="Sets" />
          <NeonStat :value="durationText" label="Duration" />
        </div>
        <p class="hint center">
          {{ completedSetsCount }}/{{ totalSetsCount }} sets ·
          {{ doneExercisesCount }}/{{ totalExercisesCount }} exercises
        </p>
      </NeonHero>

      <NeonHero v-else-if="workout.exercises.length === 0" :accent="CYAN" class="hero">
        <div class="eyebrow cyan">{{
          workout.split_focus === 'cardio' ? 'Cardio prescription'
          : workout.split_focus === 'yoga' ? 'Mobility flow'
          : workout.split_focus === 'rest' ? 'Rest day' : titleCase(workout.split_focus)
        }}</div>
        <p class="hero-text">{{ workout.notes }}</p>
        <p v-if="isCardioDay" class="hint">
          Watch-tracked rides (Concept2, Strava) auto-link to today's
          plan. For anything that doesn't push (Les Mills VR, treadmill,
          outdoor walk without a watch), use "Log this workout" to add a
          named session with duration — it'll show up in your activity
          feed and on HR charts.
        </p>
        <button v-if="isCardioDay && sessionLive" class="btn-log"
                :disabled="busy === 'complete'" @click="openCardioLog">
          Log this workout
        </button>
      </NeonHero>

      <NeonHero v-else-if="isPaused" :accent="CYAN" class="hero">
        <div class="eyebrow cyan">Paused</div>
        <h2 v-if="heroWex" class="now-name">{{ exName(heroWex.exercise_id) }}</h2>
        <p class="hero-text">
          Resume to keep logging — time away won't count toward your session length.
        </p>
        <button class="btn-log" :disabled="busy === 'resume'" @click="resumeWorkout">
          <Play :size="16" /> {{ busy === 'resume' ? 'Resuming…' : 'Resume workout' }}
        </button>
      </NeonHero>

      <NeonHero v-else-if="heroWex && heroSet != null && heroEntry" :accent="CYAN" class="hero now-hero">
        <div class="hero-top">
          <div class="eyebrow cyan">Now · Exercise {{ heroPos }} of {{ heroOf }}</div>
          <select v-if="!isTimedExercise(heroWex)" v-model="heroEntry.setType"
                  class="type-sel" aria-label="Set type">
            <option value="working">work</option>
            <option value="warmup">warm-up</option>
            <option value="drop">drop</option>
          </select>
        </div>
        <h2 class="now-name">{{ exName(heroWex.exercise_id) }}</h2>
        <div class="now-sub">
          {{ setHeading(heroWex, heroSet) }} · target {{ heroTarget(heroWex, heroSet) }}<span
            v-if="sideLabel(heroWex)"> {{ sideLabel(heroWex) }}</span>
        </div>
        <div v-if="heroWex.superset_id" class="now-ss"
             :style="{ color: supersetColor(heroWex.superset_id) }">
          Superset {{ heroWex.superset_id }} — alternate with
          {{ supersetPartnerName(heroWex.superset_id, heroWex.id) }}
        </div>
        <div v-if="heroWex.load_hint" class="now-hint">Load: {{ heroWex.load_hint }}</div>
        <div v-if="lastSetsSummary(heroWex) && !isTimedExercise(heroWex)" class="now-hint">
          ↩ last<template v-if="lastSetsWhen(heroWex)"> ({{ lastSetsWhen(heroWex) }})</template>:
          {{ lastSetsSummary(heroWex) }}
        </div>

        <!-- Timed hold: the existing countdown + full-screen overlay. -->
        <template v-if="isTimedExercise(heroWex)">
          <div class="readout">
            <template v-if="timerRemaining(heroWex.id, heroSet) !== null">
              {{ fmtCountdown(timerRemaining(heroWex.id, heroSet) ?? 0) }}
            </template>
            <template v-else>{{ heroWex.target_reps_low }}<small>s hold</small></template>
          </div>
          <button v-if="timerRemaining(heroWex.id, heroSet) === null" class="btn-log"
                  :disabled="busy === `set-${heroWex.id}-${heroSet}`"
                  @click="startTimer(heroWex, heroSet)">
            <Play :size="16" /> Start hold
          </button>
          <button v-else class="btn-ghost wide" @click="stopTimer(heroWex.id, heroSet)">Cancel</button>
          <p class="hint center">Hold for the configured time — it logs itself at zero.</p>
        </template>

        <template v-else>
          <!-- Rest lives inside the hero now: a ring around mm:ss. -->
          <div v-if="resting" class="rest-row">
            <NeonRing :fraction="restFraction" :color="restDone ? LIME : CYAN" :size="96" :stroke="8">
              <b class="ring-num" :class="restDone ? 'lime' : 'cyan'">
                {{ fmtRest(Math.max(0, restRemaining ?? 0)) }}
              </b>
              <span class="ring-cap">{{ restDone ? 'done' : `of ${fmtRest(restTotal)}` }}</span>
            </NeonRing>
            <div class="rest-body">
              <div class="rest-state" :class="restDone ? 'lime' : 'cyan'">
                {{ restDone ? 'Rest complete' : 'Resting' }}
              </div>
              <div class="rest-next">
                Next: {{ heroEntry.weight || '—' }} lb × {{ heroEntry.reps || '—' }}
              </div>
              <div class="rest-actions">
                <button v-if="!restDone" class="pill" @click="addRest(30)">+30s</button>
                <button class="pill ghost" @click="stopRest">{{ restDone ? 'Dismiss' : 'Skip' }}</button>
              </div>
            </div>
          </div>

          <template v-else>
            <div v-if="heroEditing" class="edit-row">
              <label><span>lb</span>
                <input v-model="heroEntry.weight" type="number" step="0.5" inputmode="decimal"
                       :placeholder="heroWex.target_weight_lb?.toString() ?? '—'" /></label>
              <label><span>reps</span>
                <input v-model="heroEntry.reps" type="number" inputmode="numeric" /></label>
              <button class="pill" @click="heroEditing = false">Done</button>
            </div>
            <button v-else class="readout" type="button" title="Tap to type the numbers"
                    @click="heroEditing = true">
              {{ heroEntry.weight || '—' }}<small>lb</small>
              <span class="x">×</span>
              {{ heroEntry.reps || '—' }}
              <span v-if="plannedSet(heroWex, heroSet)?.is_amrap" class="amrap-tag">AMRAP</span>
            </button>
            <div class="steppers">
              <div v-if="showWeightStepper" class="stp">
                <button type="button" :disabled="weightDown == null"
                        :aria-label="weightDown == null ? 'No lighter load' : `Lighter: ${fmtLb(weightDown)} lb`"
                        @click="stepWeight(false)"><Minus :size="16" /></button>
                <span v-if="!heroLadder">2.5 lb</span>
                <span v-else :title="'Loads your dumbbells and wrist weights can make'">
                  {{ weightDown == null ? '—' : fmtLb(weightDown) }} · {{ weightUp == null ? '—' : fmtLb(weightUp) }}
                </span>
                <button type="button" :disabled="weightUp == null"
                        :aria-label="weightUp == null ? 'No heavier load' : `Heavier: ${fmtLb(weightUp)} lb`"
                        @click="stepWeight(true)"><Plus :size="16" /></button>
              </div>
              <div v-else />
              <div class="stp">
                <button type="button" aria-label="One rep fewer" @click="stepReps(-1)"><Minus :size="16" /></button>
                <span>1 rep</span>
                <button type="button" aria-label="One rep more" @click="stepReps(1)"><Plus :size="16" /></button>
              </div>
            </div>
          </template>

          <div class="ratings" role="radiogroup" aria-label="How did the set feel?">
            <button v-for="r in HERO_RATINGS" :key="r.v" type="button" class="rate"
                    role="radio" :aria-checked="heroEntry.rating === r.v"
                    :class="{ on: heroEntry.rating === r.v }" :style="{ '--c': r.color }"
                    :title="r.title" @click="heroEntry.rating = r.v">
              {{ r.label }}
            </button>
          </div>
          <button class="btn-log" :disabled="!canLogHero" @click="logHero">
            <Check :size="17" />
            {{ busy === `set-${heroWex.id}-${heroSet}` ? 'Logging…' : `Log set ${heroSet}` }}
          </button>
        </template>
      </NeonHero>

      <NeonHero v-else-if="sessionLive" :accent="LIME" class="hero">
        <div class="eyebrow lime">All sets done</div>
        <h2 class="now-name">Finish the session</h2>
        <p class="hero-text">All {{ totalSetsCount }} prescribed sets accounted for.</p>
        <div v-if="resting" class="rest-row compact">
          <NeonRing :fraction="restFraction" :color="restDone ? LIME : CYAN" :size="72" :stroke="7">
            <b class="ring-num sm" :class="restDone ? 'lime' : 'cyan'">
              {{ fmtRest(Math.max(0, restRemaining ?? 0)) }}
            </b>
          </NeonRing>
          <button class="pill ghost" @click="stopRest">{{ restDone ? 'Dismiss' : 'Skip rest' }}</button>
        </div>
        <button class="btn-log lime" :disabled="busy === 'complete'" @click="requestComplete">
          {{ busy === 'complete' ? 'Finishing…' : 'Finish workout' }}
        </button>
        <button class="btn-ghost wide" @click="openAdd"><Plus :size="15" /> Add exercise</button>
      </NeonHero>

      <!-- ── Chips: coach / fasting / deload / paused / why ─────────── -->
      <div v-if="chipsVisible" class="chips">
        <button v-if="queryToken && sessionLive" class="chip" :class="{ on: openChip === 'coach' }"
                :style="{ '--c': CYAN }" :aria-expanded="openChip === 'coach'" @click="toggleChip('coach')">
          <Sparkles :size="15" /> Coach
        </button>
        <button v-if="fastingActive && workout.fasting_context" class="chip"
                :class="{ on: openChip === 'fast' }" :style="{ '--c': AMBER }"
                :aria-expanded="openChip === 'fast'" @click="toggleChip('fast')">
          <Hourglass :size="15" /> {{ workout.fasting_context.current_hours.toFixed(0) }}h fasted
        </button>
        <button v-if="deloadActive" class="chip" :class="{ on: openChip === 'deload' }"
                :style="{ '--c': AMBER }" :aria-expanded="openChip === 'deload'" @click="toggleChip('deload')">
          <Feather :size="15" /> Load eased ~{{ deloadPct }}%
        </button>
        <button v-if="isPaused" class="chip" :class="{ on: openChip === 'paused' }"
                :style="{ '--c': CYAN }" :aria-expanded="openChip === 'paused'" @click="toggleChip('paused')">
          <Pause :size="15" /> Paused
        </button>
        <button v-if="whyVisible" class="chip" :class="{ on: openChip === 'why' }"
                :style="{ '--c': '#9b9bb0' }" :aria-expanded="openChip === 'why'" @click="toggleChip('why')">
          <Info :size="15" /> Why this plan<template v-if="planNotes.length"> · {{ planNotes.length }}</template>
        </button>
      </div>

      <!-- The coach stays MOUNTED while hidden (v-show) so its state —
           loaded swaps, dismissals, the open section — survives closing the
           chip, the same reason the phone hoists CoachCardState. -->
      <div v-if="queryToken && sessionLive" v-show="openChip === 'coach'" class="chip-panel">
        <CoachCard :workout-id="workout.id" :refresh-key="deloadRefreshKey"
                   @accept-swap="acceptNudge" />
      </div>
      <div v-if="openChip === 'fast' && fastingActive && workout.fasting_context" class="chip-panel amber">
        <!-- FAST-18 — generated against an active fast past the 18h
             volume-modulation threshold. Text shared verbatim with the phone. -->
        You're {{ workout.fasting_context.current_hours.toFixed(0) }}h fasted
        ({{ workout.fasting_context.stage.replace('_', ' ') }}) —
        <template v-if="workout.fasting_context.modulation === 'volume_-20%'">
          volume trimmed ~20%, rest +15s.
        </template>
        <template v-else>
          volume trimmed ~30%, rest +30s. A Z2 cardio block alongside is a strong option.
        </template>
      </div>
      <div v-if="openChip === 'deload' && deloadActive" class="chip-panel amber">
        <b>Load eased ~{{ deloadPct }}% for recovery</b>
        <p>{{ deloadReasonLine }}</p>
        <button class="pill" :disabled="busy === 'regen'" @click="regenerate(true, true)">
          {{ busy === 'regen' ? 'Regenerating…' : 'Full weight' }}
        </button>
      </div>
      <div v-if="openChip === 'paused' && isPaused" class="chip-panel">
        <b>Workout paused</b>
        <p>Resume to keep logging — time away won't count toward your session length.</p>
        <button class="pill" :disabled="busy === 'resume'" @click="resumeWorkout">Resume</button>
      </div>
      <div v-if="openChip === 'why' && whyVisible" class="chip-panel">
        <!-- OG2-D-7: one row per generator note; never printed raw. -->
        <ul v-if="planNotes.length" class="pn-list">
          <li v-for="(n, i) in planNotes" :key="i">{{ n }}</li>
        </ul>
        <p v-if="workout.recovery_score_used != null || workout.sleep_h_used != null" class="meta">
          <span v-if="workout.recovery_score_used != null">recovery {{ Math.round(workout.recovery_score_used) }}</span>
          <span v-if="workout.sleep_h_used != null"> · sleep {{ workout.sleep_h_used.toFixed(1) }}h</span>
        </p>
      </div>

      <!-- ── Exercises ───────────────────────────────────────────── -->
      <template v-for="c in cards" :key="c.wex.id">
        <NeonEyebrow v-if="c.head">{{ c.head }}</NeonEyebrow>

        <!-- Up next: one compact line. Tap to make it the hero's exercise. -->
        <button v-if="c.mode === 'next'" type="button" class="next-line"
                :style="c.wex.superset_id ? { borderLeftColor: supersetColor(c.wex.superset_id) } : {}"
                @click="focusExercise(c.wex)">
          <span class="nl-main">
            <span class="nl-name">{{ exPos(c.wex) }}. {{ exName(c.wex.exercise_id) }}</span>
            <span class="nl-rx">{{ prescriptionShort(c.wex) }}</span>
          </span>
          <span class="nl-count">{{ accountedSets(c.wex) }}/{{ c.wex.target_sets }}</span>
          <ChevronRight :size="16" class="nl-chev" />
        </button>

        <!-- Closed: a 56px summary line on a surface darker than a card. -->
        <div v-else-if="c.mode === 'summary'" class="sum-line" :class="{ muted: c.wex.skipped || !hasAccountedSets(c.wex) }">
          <button type="button" class="sum-main" :disabled="c.wex.skipped || !hasAccountedSets(c.wex)"
                  :aria-expanded="false" @click="toggleExpanded(c.wex.id)">
            <Check v-if="!c.wex.skipped && hasAccountedSets(c.wex)" :size="16" class="sum-ok" />
            <span class="sum-name">{{ exPos(c.wex) }}. {{ exName(c.wex.exercise_id) }}</span>
            <span class="sum-sets">
              <template v-if="c.wex.skipped">Skipped</template>
              <template v-else-if="!hasAccountedSets(c.wex)">Not logged</template>
              <template v-else>{{ slotSummary(c.wex) }}</template>
            </span>
            <ChevronDown v-if="!c.wex.skipped && hasAccountedSets(c.wex)" :size="16" class="sum-chev" />
          </button>
          <!-- SKIP-1: Undo rides the same guard as Skip — never on a session
               that is over (it would be a one-way write against the past). -->
          <button v-if="c.wex.skipped && canSkipOrSwap(c.wex)" class="btn-text"
                  :disabled="skipInFlight" @click="setExerciseSkipped(c.wex, false)">
            {{ busy === `skip-ex-${c.wex.id}` ? 'Restoring…' : 'Undo' }}
          </button>
          <p v-if="skipError?.wexId === c.wex.id" class="card-err">{{ skipError.message }}</p>
        </div>

        <!-- Full card: the hero's exercise, or an expanded closed slot. -->
        <article v-else class="ex-card" :class="{ current: heroWex?.id === c.wex.id, closed: isSlotClosed(c.wex) }"
                 :style="c.wex.superset_id ? { borderLeftColor: supersetColor(c.wex.superset_id) } : {}">
          <div v-if="c.wex.superset_id" class="ss-banner" :style="{ color: supersetColor(c.wex.superset_id) }">
            ⇄ Superset {{ c.wex.superset_id }} — alternate with
            <strong>{{ supersetPartnerName(c.wex.superset_id, c.wex.id) }}</strong>
          </div>
          <header class="ex-head">
            <div class="ex-title">
              <h3>{{ exPos(c.wex) }}. {{ exName(c.wex.exercise_id) }}</h3>
              <div class="tags">
                <!-- TD-10 / OG2-A6: plan vs improvisation, and kit no longer owned. -->
                <span v-if="c.wex.added_ad_hoc" class="tag cyan"
                      title="You added this — the planner didn't prescribe it">Added by you</span>
                <span v-if="c.wex.equipment_missing" class="tag amber"
                      title="Needs equipment your profile no longer lists — swap it or regenerate">Needs kit you no longer have</span>
              </div>
              <div class="prescription">
                {{ c.wex.target_sets }} × {{ repsRange(c.wex) }}{{ isTimedExercise(c.wex) ? 's' : '' }}
                <span v-if="sideLabel(c.wex)" class="side-label"> {{ sideLabel(c.wex) }}</span>
                <span v-if="c.wex.target_weight_lb"> @ {{ fmtLb(c.wex.target_weight_lb) }} lb</span>
                <span class="rest"> · {{ c.wex.target_rest_s }}s rest</span>
              </div>
            </div>
            <div v-if="imageUrl(c.wex.exercise_id, 0)" class="thumb">
              <ExerciseDemo v-if="isPhoto(c.wex.exercise_id)"
                            :front="imageUrl(c.wex.exercise_id, 0)"
                            :side="imageUrl(c.wex.exercise_id, 1)"
                            :alt="exName(c.wex.exercise_id)" />
              <div v-else class="ex-thumb" :title="exName(c.wex.exercise_id)"
                   :style="`-webkit-mask-image: url('${imageUrl(c.wex.exercise_id, 0)}'); mask-image: url('${imageUrl(c.wex.exercise_id, 0)}')`" />
            </div>
          </header>

          <!-- OG2-B3: why this weight, in the server's words. -->
          <p v-if="c.wex.notes" class="why-target">{{ c.wex.notes }}</p>
          <p v-if="c.wex.program_scheme" class="program-badge">Program · {{ c.wex.program_scheme }}</p>
          <p v-if="c.wex.load_hint && !isSlotClosed(c.wex) && heroWex?.id !== c.wex.id" class="last-hint">
            Load: {{ c.wex.load_hint }}
          </p>
          <p v-if="skipError?.wexId === c.wex.id" class="card-err">{{ skipError.message }}</p>

          <div class="ex-actions">
            <a class="act" :href="youtubeUrl(c.wex.exercise_id)" target="_blank" rel="noreferrer">YouTube ↗</a>
            <template v-if="canSkipOrSwap(c.wex)">
              <button class="act" @click="openSwap(c.wex.id)">Swap</button>
              <button class="act" :disabled="skipInFlight" @click="setExerciseSkipped(c.wex, true)">
                {{ busy === `skip-ex-${c.wex.id}` ? 'Skipping…' : 'Skip' }}
              </button>
            </template>
            <button v-if="c.wex.added_ad_hoc && !isSlotClosed(c.wex) && c.wex.sets.length === 0"
                    class="act" title="Remove this exercise" @click="removeExercise(c.wex.id)">Remove</button>
            <button v-if="isSlotClosed(c.wex) && !isEditingExercise(c.wex)" class="act"
                    @click="toggleExpanded(c.wex.id)">Collapse</button>
          </div>

          <!-- The set grid: SET | LB | REPS | ✓. Fits 360px (UX-W2). -->
          <div class="grid" :class="{ timed: isTimedExercise(c.wex) }" role="table">
            <div class="g-head" role="row">
              <span>Set</span>
              <template v-if="!isTimedExercise(c.wex)"><span>lb</span><span>Reps</span></template>
              <span v-else class="span2">Hold</span>
              <span class="c">✓</span>
            </div>
            <template v-for="n in c.wex.target_sets" :key="n">
              <!-- Correction editor (OG2-A9): the same logSet path, plus Delete. -->
              <div v-if="isEditing(c.wex.id, n) && !isTimedExercise(c.wex)" class="g-edit" role="row">
                <div class="ge-top">
                  <span class="ge-lbl">Set {{ bilateralSideLabel(c.wex, n) }}</span>
                  <label><span>lb</span><input v-model="entry(c.wex, n).weight" type="number" step="0.5" inputmode="decimal" /></label>
                  <label><span>reps</span><input v-model="entry(c.wex, n).reps" type="number" inputmode="numeric" /></label>
                  <select v-model="entry(c.wex, n).setType" aria-label="Set type">
                    <option value="working">work</option>
                    <option value="warmup">warm</option>
                    <option value="drop">drop</option>
                  </select>
                </div>
                <div class="ge-rates">
                  <button v-for="opt in RATING_CHOICES" :key="opt.v" type="button" class="rate"
                          :class="{ on: entry(c.wex, n).rating === opt.v }" :style="{ '--c': ratingColor(opt.v) }"
                          :title="opt.title" @click="setRating(c.wex.id, n, opt.v)">{{ opt.label }}</button>
                </div>
                <div class="ge-acts">
                  <button class="pill ghost" @click="cancelEdit">Cancel</button>
                  <button class="pill warn" :disabled="busy === `set-${c.wex.id}-${n}`"
                          title="This set did not happen — remove it" @click="removeSet(c.wex, n)">Delete set</button>
                  <button class="pill" :disabled="busy === `set-${c.wex.id}-${n}` || entry(c.wex, n).rating === null"
                          @click="logSet(c.wex, n)">Save</button>
                </div>
              </div>

              <div v-else class="g-row" role="row" :class="{
                     logged: isSetLogged(c.wex, n),
                     now: heroWex?.id === c.wex.id && heroSet === n,
                     pending: !isSetLogged(c.wex, n) && !(heroWex?.id === c.wex.id && heroSet === n),
                   }">
                <span class="g-n" :class="{ side: bilateralSideLabel(c.wex, n) !== String(n) }">
                  {{ bilateralSideLabel(c.wex, n) }}
                </span>
                <!-- Timed rows -->
                <template v-if="isTimedExercise(c.wex)">
                  <span class="span2">
                    <template v-if="loggedSet(c.wex, n)">Held {{ loggedSet(c.wex, n)!.actual_reps }}s</template>
                    <template v-else-if="isSetLogged(c.wex, n)">fail</template>
                    <template v-else-if="timerRemaining(c.wex.id, n) !== null">
                      {{ fmtCountdown(timerRemaining(c.wex.id, n) ?? 0) }} of {{ c.wex.target_reps_low }}s
                    </template>
                    <template v-else>{{ c.wex.target_reps_low }}s hold</template>
                  </span>
                  <span class="c">
                    <Check v-if="isSetLogged(c.wex, n)" :size="16" class="lime" />
                    <b v-else-if="heroWex?.id === c.wex.id && heroSet === n" class="now-tag">NOW</b>
                  </span>
                </template>
                <!-- Rep rows -->
                <template v-else-if="loggedSet(c.wex, n)">
                  <span>{{ fmtLb(loggedSet(c.wex, n)!.actual_weight_lb) }}</span>
                  <span>{{ loggedSet(c.wex, n)!.actual_reps }}
                    <em class="g-rate" :style="{ color: ratingColor(loggedSet(c.wex, n)!.rating) }">
                      {{ ratingLabel(loggedSet(c.wex, n)!.rating) }}</em>
                    <span v-if="prFlash[`${c.wex.id}-${n}`]" class="pr-badge">{{ prFlash[`${c.wex.id}-${n}`] }}</span>
                  </span>
                  <span class="c">
                    <!-- OG2-A9: correct a fat-fingered set. ≥40px target. -->
                    <button v-if="!sessionOver && !isPaused" class="edit-btn" title="Correct this set"
                            @click="beginEdit(c.wex.id, n)">edit</button>
                    <Check v-else :size="16" class="lime" />
                  </span>
                </template>
                <template v-else-if="isSetLogged(c.wex, n)">
                  <span class="span2 muted">skipped</span><span class="c" />
                </template>
                <template v-else-if="heroWex?.id === c.wex.id && heroSet === n">
                  <span>{{ entry(c.wex, n).weight || '—' }}</span>
                  <span>{{ entry(c.wex, n).reps || '—' }}
                    <span v-if="plannedSet(c.wex, n)?.is_amrap" class="amrap-tag">AMRAP</span></span>
                  <span class="c"><b class="now-tag">NOW</b></span>
                </template>
                <template v-else>
                  <span>{{ fmtLb(plannedSet(c.wex, n)?.target_weight_lb ?? c.wex.target_weight_lb) }}</span>
                  <span>{{ plannedSet(c.wex, n)?.target_reps || c.wex.target_reps_low }}
                    <span v-if="plannedSet(c.wex, n)?.is_amrap" class="amrap-tag">AMRAP</span></span>
                  <span class="c" />
                </template>
              </div>
            </template>
          </div>
          <p v-if="!isTimedExercise(c.wex) && !isSlotClosed(c.wex)" class="rating-legend">
            <b>Hard</b> = stays the same · <b>Good</b> = +1 rep next time · <b>Easy</b> = +weight ·
            <b>Fail</b> if you missed reps.
          </p>
        </article>
      </template>

      <!-- Complete (early) / Pause — the hero carries Finish once every
           set is accounted for, so this is the walk-away path (SKIP-1). -->
      <div v-if="sessionLive && workout.exercises.length && !allSetsDone" class="bottom">
        <button class="btn-log lime" :disabled="busy === 'complete'" @click="requestComplete">
          {{ busy === 'complete' ? 'Finishing…' : 'Complete workout' }}
        </button>
        <button v-if="completedSetsCount > 0" class="btn-ghost" :disabled="busy === 'pause'" @click="pauseWorkout">
          <Pause :size="15" /> Pause
        </button>
      </div>

      <!-- TD-10 — add an off-plan exercise while the session is open. -->
      <div v-if="workout.status !== 'completed' && workout.status !== 'skipped' && workout.exercises.length"
           class="add-row">
        <button class="btn-text" @click="openAdd"><Plus :size="15" /> Add exercise</button>
        <span v-if="addError" class="card-err">{{ addError }}</span>
      </div>

      <!-- Completed: the AI review below the summary hero. -->
      <section v-if="workout.status === 'completed'" class="panel ai-review">
        <button v-if="!review && !reviewLoading" class="btn-ghost wide" @click="loadReview">
          Get AI workout review
        </button>
        <p v-if="reviewLoading" class="hint">Generating review…</p>
        <p v-if="reviewError" class="card-err">{{ reviewError }}</p>
        <div v-if="review" class="review-card" :class="`tone-${review.tone}`">
          <h3>{{ review.headline }}</h3>
          <ul v-if="review.highlights.length" class="hl">
            <li v-for="(h, i) in review.highlights" :key="i">{{ h }}</li>
          </ul>
          <ul v-if="review.concerns && review.concerns.length" class="cn">
            <li v-for="(c, i) in review.concerns" :key="i">{{ c }}</li>
          </ul>
          <p class="next"><strong>Next session:</strong> {{ review.next_session_suggestion }}</p>
          <p class="cached">{{ reviewCached ? 'cached' : 'generated' }} · {{ reviewModel }}</p>
        </div>
      </section>

      <!-- OG2-C2: projected silhouette, below the session. -->
      <template v-if="projectedMuscles">
        <NeonEyebrow>This week, after today</NeonEyebrow>
        <div class="projected-map"><BodyMap :muscles="projectedMuscles" /></div>
      </template>

      <!-- 7-day strip: past 3, today, projected 3 -->
      <NeonEyebrow>This week</NeonEyebrow>
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
             }"
             :title="d.iso + (d.status ? ' · ' + d.status : (d.projected ? ' · projected workout day' : ' · rest day'))">
          <div class="dow">{{ d.label }}</div>
          <div class="dot"></div>
        </RouterLink>
      </div>

      <template v-if="upcoming.filter(u => !u.is_today).length > 0">
        <NeonEyebrow>Next workouts</NeonEyebrow>
        <div class="upcoming-grid">
          <div v-for="u in upcoming.filter(x => !x.is_today).slice(0, 3)" :key="u.date" class="up-card">
            <div class="up-head">
              <strong>{{ new Date(u.date + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) }}</strong>
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
      </template>

      <!-- Swap-exercise sheet -->
      <div v-if="swapWexId !== null" class="overlay" @click.self="closeSwap">
        <div class="sheet" role="dialog" aria-modal="true" aria-label="Swap exercise">
          <header>
            <h2>Swap exercise</h2>
            <button class="icon-btn" aria-label="Close" @click="closeSwap">✕</button>
          </header>
          <p v-if="swapError" class="card-err">{{ swapError }}</p>
          <p v-if="swapAlternatives.length === 0" class="hint">
            No alternatives in your equipment for this slot.
          </p>
          <ul v-else class="alts">
            <li v-for="alt in swapAlternatives" :key="alt.id">
              <button type="button" :disabled="swapBusy" @click="applySwap(alt.id)">
                <strong>{{ alt.name }}</strong>
                <span class="tags-line">{{ alt.movement_pattern.replace('_', ' ') }} · {{ alt.primary_muscle }}</span>
              </button>
            </li>
          </ul>
        </div>
      </div>

      <!-- TD-10 add-exercise sheet -->
      <div v-if="addOpen" class="overlay" @click.self="closeAdd">
        <div class="sheet" role="dialog" aria-modal="true" aria-label="Add exercise">
          <header>
            <h2>Add exercise</h2>
            <button class="icon-btn" aria-label="Close" @click="closeAdd">✕</button>
          </header>
          <p class="hint">
            The weight is prescribed from your history, the same way the
            planner does it — you pick the movement.
          </p>
          <input v-model="addQuery" class="add-search" type="search"
                 placeholder="Search by name or muscle…" aria-label="Search exercises" />
          <p v-if="addError" class="card-err">{{ addError }}</p>
          <p v-if="addCandidates.length === 0" class="hint">
            Nothing matches — every exercise in your equipment is either
            already in today's session or filtered out.
          </p>
          <ul v-else class="alts">
            <li v-for="alt in addCandidates" :key="alt.id">
              <button type="button" :disabled="addBusy" @click="addExercise(alt.id)">
                <strong>{{ alt.name }}</strong>
                <span class="tags-line">{{ alt.movement_pattern.replace('_', ' ') }} · {{ alt.primary_muscle }}</span>
              </button>
            </li>
          </ul>
        </div>
      </div>

      <!-- Cardio log dialog -->
      <div v-if="showCardioLog" class="overlay center" @click.self="showCardioLog = false">
        <div class="dialog" role="dialog" aria-modal="true" aria-label="Log this workout">
          <h2>Log this workout</h2>
          <p class="hint">
            The session will appear in your activity feed, as a marker
            on HR charts, and count toward your weekly cardio dose.
          </p>
          <label class="field">
            <span>Type</span>
            <select v-model="cardioType" :disabled="busy === 'complete'" @change="onCardioPreset">
              <option v-for="p in CARDIO_PRESETS" :key="p.type" :value="p.type">{{ p.label }}</option>
            </select>
          </label>
          <label class="field">
            <span>Workout name</span>
            <input v-model="cardioLabel" type="text" maxlength="120"
                   placeholder="e.g. Les Mills VR" :disabled="busy === 'complete'" />
          </label>
          <label class="field">
            <span>Duration (minutes)</span>
            <input v-model.number="cardioDuration" type="number" min="1" max="1440"
                   :disabled="busy === 'complete'" />
          </label>
          <label class="field">
            <span>Ended at</span>
            <input v-model="cardioEndedAt" type="time" :disabled="busy === 'complete'" />
            <small class="hint">
              Adjust if you're logging this later — the HR sample window
              anchors to this end time minus the duration above.
            </small>
          </label>
          <div class="dialog-actions">
            <button class="d-dismiss" :disabled="busy === 'complete'" @click="showCardioLog = false">Cancel</button>
            <button class="d-confirm"
                    :disabled="busy === 'complete' || !cardioLabel.trim() || !cardioDuration || cardioDuration <= 0"
                    @click="submitCardioLog">
              {{ busy === 'complete' ? 'Logging…' : 'Log workout' }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- Full-screen HOLD countdown (timed exercises) — unchanged flow. -->
    <div v-if="activeTimer" class="hold-overlay" role="dialog" aria-live="polite">
      <div class="hold-name">{{ exName(activeTimer.wex.exercise_id) }}</div>
      <div class="hold-center">
        <svg class="hold-ring" viewBox="0 0 100 100" aria-hidden="true">
          <circle class="hold-ring-track" cx="50" cy="50" r="46" />
          <circle class="hold-ring-fill" cx="50" cy="50" r="46"
                  :stroke-dasharray="289.0265"
                  :stroke-dashoffset="289.0265 * (1 - activeTimer.fraction)" />
        </svg>
        <div class="hold-count">{{ fmtHold(activeTimer.remaining) }}</div>
        <div class="hold-of">of {{ fmtHold(activeTimer.totalS) }}</div>
      </div>
      <div class="hold-actions">
        <button class="hold-btn fail" @click="failTimedNow(activeTimer.wex, activeTimer.setNum)">Fail</button>
        <button class="hold-btn done" @click="finishTimedNow(activeTimer.wex, activeTimer.setNum)">Done</button>
      </div>
    </div>

    <!-- Workout-complete confirmation (auto / SKIP-1 preflight). -->
    <div v-if="showCompleteDialog" class="overlay center" @click.self="dismissCompleteDialog">
      <div class="dialog" role="dialog" aria-modal="true" :aria-label="completeDialogTitle">
        <h2>{{ completeDialogTitle }}</h2>
        <p class="hint">{{ completeDialogBody }}</p>
        <div class="dialog-actions">
          <button class="d-dismiss" @click="dismissCompleteDialog">{{ completeDialogDismissLabel }}</button>
          <button class="d-confirm" :disabled="busy === 'complete'" @click="finishFromDialog">
            {{ busy === 'complete' ? 'Finishing…' : 'Finish workout' }}
          </button>
        </div>
      </div>
    </div>
  </NeonPage>

  <!-- OG3-M5: the app draws its own confirmation for the two set
       operations that rewrite progression history. -->
  <ConfirmDialog
    :open="confirmState.open.value"
    v-bind="confirmState.request.value"
    @confirm="confirmState.onConfirm"
    @cancel="confirmState.onCancel"
  />
</template>

<style scoped>
/* UI-2 — the active workout on the shared neon kit. Tokens (--rn-*) come
   from NeonPage. Everything must fit a 360px viewport with no horizontal
   scroll (UX-W2): no fixed widths wider than the column, min-width: 0 on
   every flex/grid child that holds text. */
.strength-today { --dark: #12141d; }
.strength-today :deep(*) { box-sizing: border-box; }
.hint { color: var(--rn-mut); font-size: 13px; line-height: 1.45; margin: 6px 0; }
.hint.center { text-align: center; }
.lime { color: var(--rn-lime); } .cyan { color: var(--rn-cyan); } .amber { color: var(--rn-amber); }
.muted { color: var(--rn-mut); }

/* Overflow menu */
.menu-wrap { position: relative; }
.icon-btn { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--rn-line);
  background: var(--rn-card); color: var(--rn-ink); display: inline-flex; align-items: center;
  justify-content: center; cursor: pointer; font-size: 16px; }
.menu-scrim { position: fixed; inset: 0; z-index: 40; }
.menu { position: absolute; right: 0; top: 46px; z-index: 41; min-width: 230px; max-width: calc(100vw - 32px);
  background: var(--rn-high); border: 1px solid var(--rn-track); border-radius: 16px; padding: 6px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, .5); display: flex; flex-direction: column; }
.menu button { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; text-align: left;
  min-height: 44px; padding: 8px 12px; border: 0; border-radius: 10px; background: transparent;
  color: var(--rn-ink); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
.menu button span { font-size: 11.5px; font-weight: 400; color: var(--rn-mut); }
.menu button:hover:not(:disabled) { background: rgba(40, 230, 255, .07); }
.menu button:disabled { opacity: .5; cursor: default; }
.menu button.warn { color: var(--rn-amber); }
.menu-lbl { font-family: 'Space Grotesk', monospace; font-size: 10.5px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--rn-mut); padding: 10px 12px 2px; }
.menu-sep { height: 1px; background: var(--rn-track); margin: 6px 4px; }

/* Error banner — amber, never rose */
.errbanner { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 181, 46, .10); border: 1px solid rgba(255, 181, 46, .30); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: var(--rn-mut); font: inherit; font-size: 12px;
  overflow-wrap: anywhere; }
.errbanner b { color: var(--rn-amber); font-size: 13px; }
.errbanner em { font-style: normal; color: var(--rn-cyan); font-weight: 600; }
.card-err { color: var(--rn-amber); font-size: 12px; margin: 6px 0 0; overflow-wrap: anywhere; }

/* Skeleton */
.sk { background: linear-gradient(90deg, #1f2433 0%, rgba(40, 230, 255, .16) 50%, #1f2433 100%);
  background-size: 200% 100%; border-radius: 8px; animation: sk 1.4s linear infinite; }
@keyframes sk { from { background-position: 100% 0; } to { background-position: -100% 0; } }
.sk-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.sk-row.four { grid-template-columns: repeat(4, 1fr); }

/* Segmented progress */
.seg-wrap { display: flex; align-items: center; gap: 10px; margin: -4px 0 12px; }
.segs { flex: 1; min-width: 0; display: flex; gap: 3px; }
.seg { flex: 1; height: 8px; border-radius: 4px; background: var(--rn-track); overflow: hidden; }
.seg i { display: block; height: 100%; border-radius: 4px; }
.seg.done i { background: var(--rn-lime); box-shadow: 0 0 8px rgba(93, 255, 59, .45); }
.seg.partial i { background: var(--rn-cyan); }
.seg.skipped i { background: rgba(155, 155, 176, .35); }
.seg-label { font-family: 'Space Grotesk', monospace; font-size: 12px; font-weight: 700;
  color: var(--rn-mut); white-space: nowrap; font-variant-numeric: tabular-nums; }

/* Hero */
.hero-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.eyebrow { font-family: 'Space Grotesk', monospace; font-size: 11px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--rn-mut); min-width: 0; }
.now-name { margin: 6px 0 2px; font-size: 22px; font-weight: 800; letter-spacing: -.3px; line-height: 1.15;
  color: var(--rn-ink); overflow-wrap: anywhere; }
.now-sub { font-size: 13px; color: var(--rn-mut); }
.now-ss { font-size: 12px; font-weight: 600; margin-top: 3px; }
.now-hint { font-size: 12px; color: var(--rn-mut); margin-top: 3px; font-family: 'Space Grotesk', monospace; }
.hero-text { margin: 8px 0; font-size: 14px; line-height: 1.45; color: var(--rn-ink); }
.type-sel { background: var(--rn-card); color: var(--rn-mut); border: 1px solid var(--rn-line); border-radius: 8px;
  font: inherit; font-size: 12px; padding: 4px 6px; min-height: 32px; }
@media (min-height: 760px) {
  /* Pinned under the header on screens tall enough to keep the list in view. */
  .now-hero { position: sticky; top: 8px; z-index: 5; }
}

.readout { display: flex; align-items: baseline; justify-content: center; gap: 6px; width: 100%;
  margin: 12px 0 8px; padding: 4px 0; border: 0; background: transparent; cursor: pointer;
  font-family: 'Space Grotesk', monospace; font-size: 40px; font-weight: 700; letter-spacing: -1px;
  color: var(--rn-ink); font-variant-numeric: tabular-nums; line-height: 1.05; }
.readout small { font-size: 16px; color: var(--rn-mut); font-weight: 600; letter-spacing: 0; }
.readout .x { font-size: 24px; color: var(--rn-mut); margin: 0 2px; }
.edit-row { display: flex; gap: 8px; align-items: flex-end; margin: 12px 0 8px; }
.edit-row label { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px;
  font-size: 11px; color: var(--rn-mut); }
.edit-row input, .g-edit input { width: 100%; min-width: 0; background: var(--rn-card); color: var(--rn-ink);
  border: 1px solid var(--rn-cyan); border-radius: 10px; font: inherit; font-size: 18px; font-weight: 700;
  padding: 8px 10px; font-family: 'Space Grotesk', monospace; }
.steppers { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.stp { display: flex; align-items: center; justify-content: space-between; min-width: 0;
  background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 12px; }
.stp span { font-size: 12px; color: var(--rn-mut); white-space: nowrap; }
.stp button { width: 40px; height: 40px; border: 0; background: transparent; color: var(--rn-cyan);
  display: inline-flex; align-items: center; justify-content: center; cursor: pointer; flex: 0 0 auto; }
.stp button:active { background: rgba(40, 230, 255, .12); border-radius: 12px; }
.stp button:disabled { color: var(--rn-mut); opacity: .45; cursor: default; }

.ratings { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 10px; }
.rate { min-height: 40px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--c) 45%, transparent);
  background: var(--rn-card); color: var(--c); font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; }
.rate.on { background: var(--c); color: var(--rn-onacc); border-color: var(--c); }
.btn-log { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; min-height: 48px;
  margin-top: 10px; border: 0; border-radius: 14px; background: var(--rn-cyan); color: var(--rn-onacc);
  font: inherit; font-size: 15px; font-weight: 800; cursor: pointer; box-shadow: 0 0 18px rgba(40, 230, 255, .28); }
.btn-log.lime { background: var(--rn-lime); box-shadow: 0 0 18px rgba(93, 255, 59, .25); }
.btn-log:disabled { opacity: .4; cursor: default; box-shadow: none; }
.btn-ghost { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 44px;
  padding: 0 16px; border-radius: 14px; border: 1px solid var(--rn-track); background: var(--rn-card);
  color: var(--rn-ink); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
.btn-ghost.wide { width: 100%; margin-top: 10px; }
.btn-ghost:disabled { opacity: .5; }
.btn-text { display: inline-flex; align-items: center; gap: 4px; min-height: 40px; padding: 0 10px; border: 0;
  background: transparent; color: var(--rn-cyan); font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; }
.btn-text:disabled { opacity: .5; }
.pill { min-height: 36px; padding: 0 14px; border-radius: 18px; border: 1px solid var(--rn-cyan);
  background: rgba(40, 230, 255, .12); color: var(--rn-cyan); font: inherit; font-size: 13px; font-weight: 700;
  cursor: pointer; }
.pill.ghost { border-color: var(--rn-track); background: transparent; color: var(--rn-ink); }
.pill.warn { border-color: rgba(255, 181, 46, .5); background: rgba(255, 181, 46, .10); color: var(--rn-amber); }
.pill:disabled { opacity: .5; }

/* Rest ring inside the hero */
.rest-row { display: flex; align-items: center; gap: 14px; margin: 12px 0 4px; }
.rest-row.compact { justify-content: center; margin: 8px 0; }
.ring-num { font-family: 'Space Grotesk', monospace; font-size: 20px; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.ring-num.sm { font-size: 15px; }
.ring-cap { font-size: 9px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--rn-mut); }
.rest-body { flex: 1; min-width: 0; }
.rest-state { font-size: 16px; font-weight: 800; }
.rest-next { font-size: 13px; color: var(--rn-mut); margin-top: 2px; font-family: 'Space Grotesk', monospace; }
.rest-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }

/* Completed tiles */
.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.tiles :deep(.ns-v) { font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Chip strip */
.chips { display: flex; gap: 8px; overflow-x: auto; padding: 2px 0 4px; margin-bottom: 8px;
  scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 12px;
  border-radius: 17px; border: 1px solid color-mix(in srgb, var(--c) 40%, transparent);
  background: color-mix(in srgb, var(--c) 10%, transparent); color: var(--c); font: inherit; font-size: 13px;
  font-weight: 700; cursor: pointer; white-space: nowrap; }
.chip.on { background: color-mix(in srgb, var(--c) 22%, transparent); border-color: var(--c); }
.chip-panel { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 16px; padding: 12px 14px;
  margin-bottom: 12px; font-size: 13px; line-height: 1.5; color: var(--rn-ink); overflow-wrap: anywhere; }
.chip-panel.amber { border-color: rgba(255, 181, 46, .35); background: rgba(255, 181, 46, .06); }
.chip-panel p { margin: 4px 0 8px; color: var(--rn-mut); }
.chip-panel .meta { margin: 6px 0 0; font-size: 12px; }
.pn-list { margin: 0; padding-left: 18px; color: var(--rn-mut); }
.pn-list li { margin: 3px 0; }

/* Up-next lines */
.next-line { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 52px; margin-bottom: 6px;
  padding: 8px 10px 8px 14px; border: 1px solid var(--rn-line); border-left: 3px solid var(--rn-track);
  border-radius: 14px; background: var(--rn-card); color: var(--rn-ink); font: inherit; text-align: left;
  cursor: pointer; }
.nl-name { flex: 1; min-width: 0; font-size: 14px; font-weight: 700; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.nl-rx { font-size: 12px; color: var(--rn-mut); white-space: nowrap; font-family: 'Space Grotesk', monospace; }
.nl-count { font-size: 12px; font-weight: 700; color: var(--rn-cyan); font-family: 'Space Grotesk', monospace; }
.nl-chev { color: var(--rn-mut); flex: 0 0 auto; }
.nl-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.nl-main .nl-name { flex: 0 0 auto; }

/* Closed summary lines — darker than a card */
.sum-line { display: flex; flex-wrap: wrap; align-items: center; min-height: 56px; margin-bottom: 6px;
  padding: 0 6px 0 0; background: var(--dark); border: 1px solid var(--rn-line); border-radius: 14px; }
.sum-main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; min-height: 56px; padding: 0 12px;
  border: 0; background: transparent; color: var(--rn-ink); font: inherit; text-align: left; cursor: pointer; }
.sum-main:disabled { cursor: default; }
.sum-ok { color: var(--rn-lime); flex: 0 0 auto; }
.sum-name { flex: 1 1 auto; min-width: 0; font-size: 14px; font-weight: 600; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.sum-sets { flex: 0 1 auto; min-width: 0; font-size: 12px; color: var(--rn-mut); font-family: 'Space Grotesk', monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 48%; }
.sum-chev { color: var(--rn-mut); flex: 0 0 auto; }
.sum-line.muted .sum-name { color: var(--rn-mut); }
.sum-line .card-err { flex-basis: 100%; padding: 0 12px 10px; }

/* Full exercise card */
.ex-card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px;
  margin-bottom: 10px; min-width: 0; }
.ex-card.current { border-color: rgba(40, 230, 255, .35); }
.ex-card[style*="border-left-color"] { border-left-width: 3px; }
.ss-banner { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.ss-banner strong { color: var(--rn-ink); }
.ex-head { display: flex; gap: 12px; align-items: flex-start; }
.ex-title { flex: 1; min-width: 0; }
.ex-head h3 { margin: 0; font-size: 16px; font-weight: 800; color: var(--rn-ink); overflow-wrap: anywhere; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.tag { font-size: 9.5px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; padding: 2px 6px;
  border-radius: 6px; }
.tag.cyan { background: rgba(40, 230, 255, .12); }
.tag.amber { background: rgba(255, 181, 46, .12); }
.prescription { font-family: 'Space Grotesk', monospace; font-size: 12.5px; color: var(--rn-mut); margin-top: 3px; }
.prescription .rest { opacity: .8; }
.side-label { font-weight: 600; }
.thumb { width: 56px; flex: 0 0 56px; border-radius: 10px; overflow: hidden; background: rgba(255, 58, 216, .10); }
.thumb :deep(img) { width: 56px; height: 56px; object-fit: cover; }
.ex-thumb { width: 56px; height: 56px; background: var(--rn-mag); -webkit-mask-size: 70%; mask-size: 70%;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; -webkit-mask-position: center; mask-position: center; }
.why-target, .last-hint { margin: 6px 0 0; font-size: 12px; line-height: 1.4; color: var(--rn-mut); }
.program-badge { margin: 4px 0 0; font-size: 12px; color: var(--rn-cyan); font-weight: 700;
  font-family: 'Space Grotesk', monospace; }
.ex-actions { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0 6px; }
.act { display: inline-flex; align-items: center; min-height: 40px; padding: 0 12px; border-radius: 12px;
  border: 1px solid var(--rn-track); background: var(--rn-high); color: var(--rn-ink); font: inherit;
  font-size: 13px; font-weight: 600; text-decoration: none; cursor: pointer; }
.act:disabled { opacity: .5; }

/* Set grid — SET | LB | REPS | ✓ */
.grid { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.g-head, .g-row { display: grid; grid-template-columns: 36px minmax(0, 1fr) minmax(0, 1.3fr) 52px; gap: 6px;
  align-items: center; padding: 0 8px; }
.g-head { font-family: 'Space Grotesk', monospace; font-size: 10.5px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--rn-mut); min-height: 22px; }
.g-row { min-height: 44px; border-radius: 10px; border: 1px solid transparent; font-family: 'Space Grotesk', monospace;
  font-size: 15px; font-weight: 700; color: var(--rn-ink); font-variant-numeric: tabular-nums; }
.g-row > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.span2 { grid-column: span 2; }
.c { justify-self: end; display: inline-flex; align-items: center; }
.g-n { color: var(--rn-mut); }
.g-n.side { color: var(--rn-mag); }
.g-row.logged { background: rgba(93, 255, 59, .08); }
.g-row.now { border-color: var(--rn-cyan); background: rgba(40, 230, 255, .06); }
.g-row.pending { color: var(--rn-mut); opacity: .75; font-weight: 500; }
.g-rate { font-style: normal; font-size: 11px; font-weight: 700; margin-left: 4px; font-family: 'Plus Jakarta Sans', sans-serif; }
.now-tag { font-size: 10px; letter-spacing: .08em; color: var(--rn-onacc); background: var(--rn-cyan);
  padding: 2px 6px; border-radius: 6px; }
.edit-btn { min-width: 44px; min-height: 40px; border: 0; border-radius: 10px; background: transparent;
  color: var(--rn-cyan); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.edit-btn:hover { background: rgba(40, 230, 255, .10); }
.g-edit { border: 1px solid var(--rn-cyan); border-radius: 12px; padding: 10px; background: rgba(40, 230, 255, .05); }
.ge-top { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(0, 1fr) auto; gap: 6px; align-items: end; }
.ge-top label { display: flex; flex-direction: column; gap: 2px; font-size: 10.5px; color: var(--rn-mut); min-width: 0; }
.ge-top input { font-size: 15px; padding: 6px 8px; }
.ge-top select { background: var(--rn-card); color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 8px;
  font: inherit; font-size: 12px; min-height: 36px; }
.ge-lbl { font-size: 12px; font-weight: 700; color: var(--rn-ink); padding-bottom: 8px; }
.ge-rates { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 8px; }
.ge-acts { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; margin-top: 8px; }
.rating-legend { font-size: 11.5px; color: var(--rn-mut); margin: 8px 0 0; line-height: 1.45; }
.rating-legend b { color: var(--rn-ink); }
.amrap-tag { font-size: 9.5px; font-weight: 800; letter-spacing: .06em; color: var(--rn-amber);
  background: rgba(255, 181, 46, .12); padding: 1px 5px; border-radius: 5px; margin-left: 4px;
  font-family: 'Plus Jakarta Sans', sans-serif; vertical-align: middle; }
.pr-badge { display: inline-block; margin-left: 4px; padding: 1px 6px; border-radius: 6px; font-size: 10px;
  font-weight: 800; color: #3a2400; background: var(--rn-amber); animation: pr-pop .3s ease-out;
  font-family: 'Plus Jakarta Sans', sans-serif; }
@keyframes pr-pop { from { transform: scale(.6); opacity: 0; } to { transform: scale(1); opacity: 1; } }

.bottom { display: flex; gap: 8px; align-items: center; margin-top: 6px; }
.bottom .btn-log { margin-top: 0; flex: 1; }
.add-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 6px 0; }

/* Review */
.panel { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; }
.review-card { border-radius: 14px; }
.review-card h3 { margin: 0 0 6px; font-size: 15px; color: var(--rn-ink); }
.review-card .hl { color: var(--rn-ink); padding-left: 18px; margin: 4px 0; font-size: 13px; }
.review-card .cn { color: var(--rn-amber); padding-left: 18px; margin: 4px 0; font-size: 13px; }
.review-card .next { margin: 8px 0 0; font-size: 13px; color: var(--rn-ink); }
.review-card .cached { font-size: 11px; color: var(--rn-mut); margin: 6px 0 0; }
.projected-map { max-width: 360px; margin: 0 auto; }

/* Week strip */
.week-strip { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.week-strip .day { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 7px 0;
  border-radius: 10px; border: 1px solid var(--rn-line); background: var(--rn-card); text-decoration: none; min-width: 0; }
.week-strip .dow { font-size: 10px; font-weight: 700; color: var(--rn-mut); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 100%; }
.week-strip .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--rn-track); }
.week-strip .day.today { border-color: var(--rn-cyan); }
.week-strip .day.today .dow { color: var(--rn-ink); }
.week-strip .day.completed .dot { background: var(--rn-lime); }
.week-strip .day.in_progress .dot { background: var(--rn-amber); }
.week-strip .day.skipped .dot { background: var(--rn-mut); }
.week-strip .day.planned .dot { background: var(--rn-cyan); }
.week-strip .day.projected .dot { background: transparent; border: 1.5px solid var(--rn-cyan); }

/* Upcoming */
.upcoming-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.up-card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 14px; padding: 10px 12px;
  min-width: 0; }
.up-head { display: flex; justify-content: space-between; gap: 6px; font-size: 13px; color: var(--rn-ink); }
.up-head .focus { color: var(--rn-cyan); font-size: 12px; text-transform: capitalize; }
.up-card ul { margin: 6px 0 0; padding-left: 16px; font-size: 12px; color: var(--rn-mut); }
.up-card .more { font-style: italic; }

/* Sheets + dialogs — themed (CardHigh, Lime confirm, Muted dismiss) */
.overlay { position: fixed; inset: 0; z-index: 100; background: rgba(0, 0, 0, .6); display: flex;
  align-items: flex-end; justify-content: center; }
.overlay.center { align-items: center; padding: 16px; }
.sheet { width: 100%; max-width: 560px; max-height: 85vh; overflow-y: auto; background: var(--rn-high);
  border: 1px solid var(--rn-track); border-radius: 22px 22px 0 0; padding: 16px; color: var(--rn-ink); }
.sheet header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.sheet h2, .dialog h2 { margin: 0; font-size: 18px; font-weight: 800; color: var(--rn-ink); }
.alts { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.alts button { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; min-height: 52px;
  padding: 10px 12px; border-radius: 12px; border: 1px solid var(--rn-line); background: var(--rn-card);
  color: var(--rn-ink); font: inherit; font-size: 14px; text-align: left; cursor: pointer; }
.alts button:disabled { opacity: .5; }
.tags-line { font-size: 12px; color: var(--rn-mut); }
.add-search { width: 100%; min-height: 44px; margin-top: 6px; padding: 0 12px; border-radius: 12px;
  border: 1px solid var(--rn-track); background: var(--rn-card); color: var(--rn-ink); font: inherit; font-size: 15px; }
.dialog { width: 100%; max-width: 420px; background: var(--rn-high); border: 1px solid var(--rn-track);
  border-radius: 22px; padding: 18px; color: var(--rn-ink); box-shadow: 0 16px 40px rgba(0, 0, 0, .5); }
.dialog .field { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; font-size: 12px; color: var(--rn-mut); }
.dialog .field input, .dialog .field select { min-height: 42px; padding: 0 10px; border-radius: 10px;
  border: 1px solid var(--rn-track); background: var(--rn-card); color: var(--rn-ink); font: inherit; font-size: 15px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 16px; }
.d-dismiss, .d-confirm { min-height: 44px; padding: 0 16px; border: 0; border-radius: 12px; background: transparent;
  font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; }
.d-dismiss { color: var(--rn-mut); }
.d-confirm { color: var(--rn-lime); }
.d-confirm:disabled, .d-dismiss:disabled { opacity: .5; }

/* Full-screen hold overlay (timed exercises) */
.hold-overlay { position: fixed; inset: 0; z-index: 9000; background: #0f1118; color: var(--rn-ink);
  display: flex; flex-direction: column; align-items: center; justify-content: space-between;
  padding: max(1.2rem, env(safe-area-inset-top)) 1.2rem max(1.2rem, env(safe-area-inset-bottom));
  overscroll-behavior: contain; }
.hold-name { font-size: clamp(1.1rem, 4.5vw, 2rem); font-weight: 700; text-align: center; line-height: 1.1;
  margin-top: .4rem; max-width: 90vw; }
.hold-center { position: relative; flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: center; width: 100%; min-height: 0; }
.hold-ring { position: absolute; width: min(88vw, 78vh); height: min(88vw, 78vh); transform: rotate(-90deg);
  pointer-events: none; }
.hold-ring-track { fill: none; stroke: var(--rn-track); stroke-width: 1.5; }
.hold-ring-fill { fill: none; stroke: var(--rn-peri); stroke-width: 2.5; stroke-linecap: round;
  transition: stroke-dashoffset .4s linear; filter: drop-shadow(0 0 6px rgba(111, 123, 255, .55)); }
.hold-count { position: relative; z-index: 1; font-size: clamp(96px, 42vw, 340px); font-weight: 700; line-height: .9;
  letter-spacing: -.03em; font-variant-numeric: tabular-nums; font-family: 'Space Grotesk', monospace;
  text-shadow: 0 0 22px rgba(111, 123, 255, .55); }
.hold-of { position: relative; z-index: 1; margin-top: .4rem; font-size: clamp(.9rem, 3.5vw, 1.4rem); color: var(--rn-mut); }
.hold-actions { display: flex; gap: .8rem; width: 100%; max-width: 520px; }
.hold-btn { flex: 1; min-height: 64px; border-radius: 14px; font: inherit; font-size: 1.25rem; font-weight: 800;
  cursor: pointer; border: 1px solid var(--rn-track); background: var(--rn-card); color: var(--rn-ink); }
.hold-btn.fail { color: var(--rn-bad); border-color: rgba(255, 93, 122, .5); background: rgba(255, 93, 122, .12); }
.hold-btn.done { color: #0f1118; background: var(--rn-peri); border-color: var(--rn-peri); }
</style>
