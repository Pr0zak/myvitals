<script setup lang="ts">
/**
 * Read-only view of a specific day's strength workout. Reached via the
 * clickable week strip on /workout/strength/today. Past dates render the
 * persisted workout (logged sets with their WP-16 rating); future dates
 * render the planner's preview. The Android day view mirrors this layout.
 *
 * Every number is the server's: session_summary for the tiles, the
 * SKIP-1 counters for the done/total line. Nothing is derived here.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import NeonPage from "@/components/neon/NeonPage.vue";
import { api } from "@/api/client";
import { apiBase } from "@/config";
import { ratingColor, ratingLabel } from "@/strength/rating";
import type {
  StrengthExercise, StrengthSet, StrengthWorkoutDetail, StrengthWorkoutExercise,
} from "@/api/types";


const route = useRoute();

const workout = ref<StrengthWorkoutDetail | null>(null);
const catalogById = ref<Record<string, StrengthExercise>>({});
const notFound = ref(false);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  const date = String(route.params.date ?? "");
  if (!date) { error.value = "no date in route"; loading.value = false; return; }
  loading.value = true; error.value = null; notFound.value = false;
  try {
    const [w, cat] = await Promise.all([
      api.strengthWorkoutByDate(date),
      api.strengthExercises().catch(() => ({ count: 0, exercises: [] as StrengthExercise[] })),
    ]);
    catalogById.value = Object.fromEntries(cat.exercises.map((e) => [e.id, e]));
    if (w === null) { notFound.value = true; workout.value = null; }
    else { workout.value = w; }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally { loading.value = false; }
}
onMounted(load);
watch(() => route.params.date, load);

const isPreview = computed(() => {
  const w = workout.value;
  return !!w && (w.id < 0 || w.status === "preview");
});
/** No sets can exist yet: show the prescription with "Planned". */
const isPlanned = computed(() => isPreview.value || workout.value?.status === "planned");

function titleCase(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
const pageTitle = computed(() =>
  workout.value ? `${titleCase(workout.value.split_focus)} day` : "Workout");

function muscleGroupsFor(focus: string): string {
  const m: Record<string, string> = {
    push: "Chest, shoulders, triceps",
    pull: "Back, biceps",
    legs: "Quads, hamstrings, glutes, calves",
    upper: "Chest, back, shoulders, arms",
    lower: "Quads, hamstrings, glutes, calves",
    full_body: "Full body — chest, back, legs",
    rest: "Rest day",
  };
  return m[focus.toLowerCase()] ?? focus.replace(/_/g, " ");
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  } catch { return iso; }
}
const dateLabel = computed(() => fmtDate(workout.value?.date ?? String(route.params.date ?? "")));
const muscles = computed(() => (workout.value ? muscleGroupsFor(workout.value.split_focus) : ""));

const status = computed<{ label: string; tone: string }>(() => {
  const w = workout.value;
  if (!w || isPreview.value) return { label: "Preview", tone: "muted" };
  switch (w.status) {
    case "completed": return { label: "Complete", tone: "lime" };
    case "in_progress":
    case "paused": return { label: "In progress", tone: "cyan" };
    case "skipped": return { label: "Skipped", tone: "amber" };
    case "planned": return { label: "Planned", tone: "muted" };
    default: return { label: titleCase(w.status), tone: "muted" };
  }
});

// Session tiles — same fields and formatting as StrengthToday's completed hero.
const summary = computed(() => workout.value?.session_summary ?? null);
const tonnageText = computed(() => {
  const s = summary.value;
  if (!s) return "—";
  if (s.total_volume_lb === 0 && s.working_sets > 0) return "BW";
  return Math.round(s.total_volume_lb).toLocaleString();
});
const durationText = computed(() => {
  const s = summary.value?.net_duration_s;
  return s == null ? "—" : String(Math.round(s / 60));
});
/** The hero legend, outer to inner in the Today-brief style. Every value is
 *  the server's session_summary or the workout's own counters. */
const legend = computed(() => {
  const w = workout.value;
  if (!w) return [];
  const bw = tonnageText.value === "BW";
  return [
    { key: "lift", color: "var(--rn-lime)", label: "Lifted", value: tonnageText.value,
      sub: bw ? "bodyweight" : summary.value ? "lb" : null },
    { key: "sets", color: "var(--rn-cyan)", label: "Sets",
      value: w.sets_total == null ? "—" : `${w.sets_done ?? 0}/${w.sets_total}`,
      sub: w.exercises_total == null ? null : `${w.exercises_done ?? 0} of ${w.exercises_total} exercises` },
    { key: "dur", color: "var(--rn-mag)", label: "Duration", value: durationText.value,
      sub: summary.value?.net_duration_s == null ? null : "min" },
  ];
});

const exercises = computed(() =>
  [...(workout.value?.exercises ?? [])].sort((a, b) => a.order_index - b.order_index));

function ex(slug: string): StrengthExercise | undefined { return catalogById.value[slug]; }
function exName(slug: string): string { return ex(slug)?.name ?? slug.replace(/_/g, " "); }
function imageUrl(slug: string): string | null {
  const path = ex(slug)?.image_front;
  if (!path) return null;
  const base = (apiBase.value || "/api").replace(/\/$/, "");
  return `${base}${path}`;
}
function isPhoto(slug: string): boolean {
  const u = imageUrl(slug);
  return !!u && /\.jpe?g($|\?)/i.test(u);
}

/** Same rule as StrengthToday.isTimedExercise. */
function isTimed(wex: StrengthWorkoutExercise): boolean {
  if (wex.is_timed === true) return true;
  const c = ex(wex.exercise_id);
  if (c?.movement_pattern === "mobility") return c.is_timed !== false;
  return wex.target_weight_lb == null
    && wex.target_reps_low === wex.target_reps_high
    && wex.target_reps_low >= 20;
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
function sideLabel(wex: StrengthWorkoutExercise): string | null {
  return wex.planned_sets?.find((p) => p.per_side)?.side_label ?? null;
}
/** StrengthToday's prescription line: "4×8 per side @ 25 lb · 45s rest". */
function prescriptionLine(wex: StrengthWorkoutExercise): string {
  const unit = isTimed(wex) ? "s" : "";
  const side = sideLabel(wex);
  const w = wex.target_weight_lb ? ` @ ${fmtLb(wex.target_weight_lb)} lb` : "";
  return `${wex.target_sets}×${repsRange(wex)}${unit}${side ? ` ${side}` : ""}${w} · ${wex.target_rest_s}s rest`;
}

/** Logged or individually skipped sets, in order. */
function rows(wex: StrengthWorkoutExercise): StrengthSet[] {
  return wex.sets
    .filter((s) => s.actual_reps != null || s.skipped)
    .sort((a, b) => a.set_number - b.set_number);
}
function weightCell(wex: StrengthWorkoutExercise, s: StrengthSet): string {
  if (isTimed(wex)) return "—";
  return s.actual_weight_lb == null ? "BW" : fmtLb(s.actual_weight_lb);
}
function repsCell(wex: StrengthWorkoutExercise, s: StrengthSet): string {
  return isTimed(wex) ? `${s.actual_reps}s` : String(s.actual_reps);
}
function pillLabel(r: number): string { return r === 1 ? "Fail" : ratingLabel(r); }
</script>

<template>
  <NeonPage :title="pageTitle" back="/workout/strength/today" class="day-view">
    <!-- Hero on the page ground: date and status, the muscle groups as the
         headline, then the session as a legend. No card, no border. -->
    <section class="hero">
      <div class="hero-top">
        <span class="date">{{ dateLabel }}</span>
        <span v-if="workout" class="word" :class="status.tone">{{ status.label }}</span>
      </div>
      <h2 v-if="muscles" class="muscles">{{ muscles }}</h2>
      <div v-if="workout" class="legend">
        <div v-for="l in legend" :key="l.key" class="lrow">
          <span class="bar" :style="{ background: l.color }" />
          <span class="ltxt">
            <span class="llab">{{ l.label }}</span>
            <span class="lval num">{{ l.value }}</span>
            <span v-if="l.sub" class="lsub">{{ l.sub }}</span>
          </span>
        </div>
      </div>
    </section>

    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <div v-else-if="notFound" class="card muted-card">No workout recorded for this day.</div>

    <template v-else-if="workout">
      <!-- SKIP-1: a declined slot is muted so history doesn't read it as an
           untouched prescription the user might still get to. -->
      <article v-for="wex in exercises" :key="wex.id"
               class="card ex-card" :class="{ dim: wex.skipped }">
        <header class="ex-head">
          <div class="thumb">
            <img v-if="isPhoto(wex.exercise_id)" :src="imageUrl(wex.exercise_id)!"
                 :alt="exName(wex.exercise_id)" loading="lazy" />
            <div v-else-if="imageUrl(wex.exercise_id)" class="thumb-mask"
                 :style="`-webkit-mask-image: url('${imageUrl(wex.exercise_id)}'); mask-image: url('${imageUrl(wex.exercise_id)}')`" />
          </div>
          <div class="ex-title">
            <h3>{{ exName(wex.exercise_id) }}</h3>
            <div class="rx">{{ prescriptionLine(wex) }}</div>
          </div>
          <span v-if="wex.skipped" class="word amber">Skipped</span>
        </header>

        <template v-if="!wex.skipped">
          <p v-if="isPlanned" class="state">Planned</p>
          <p v-else-if="!rows(wex).length" class="state">Not logged</p>
          <table v-else class="sets">
            <thead>
              <tr><th>Set</th><th>lb</th><th>Reps</th><th class="r"><span class="sr">Rating</span></th></tr>
            </thead>
            <tbody>
              <tr v-for="s in rows(wex)" :key="s.set_number" :class="{ skip: s.actual_reps == null }">
                <td class="n">{{ s.set_number }}</td>
                <template v-if="s.actual_reps == null">
                  <td colspan="3" class="skip-cell">skipped</td>
                </template>
                <template v-else>
                  <td>{{ weightCell(wex, s) }}</td>
                  <td>{{ repsCell(wex, s) }}</td>
                  <td class="r">
                    <span v-if="s.rating != null" class="rate" :style="{ '--c': ratingColor(s.rating) }">
                      {{ pillLabel(s.rating) }}
                    </span>
                  </td>
                </template>
              </tr>
            </tbody>
          </table>
        </template>
      </article>
    </template>
  </NeonPage>
</template>

<style scoped>
.hero { margin: -6px 0 22px; }
.hero-top { display: flex; align-items: baseline; gap: 10px; }
.date { flex: 1; color: var(--rn-mut); font-size: 13px; }
/* Status is a coloured word, not a bordered pill: the colour is the signal. */
.word { --c: var(--rn-mut); color: var(--c); font-size: 13px; font-weight: 500; white-space: nowrap; }
.word.lime { --c: var(--rn-lime); }
.word.cyan { --c: var(--rn-cyan); }
.word.amber { --c: var(--rn-amber); }
.muscles { margin: 2px 0 16px; font-size: 20px; font-weight: 500; color: var(--rn-ink); }
.legend { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.lrow { display: flex; gap: 9px; min-width: 0; }
.bar { flex: none; width: 3px; height: 30px; margin-top: 4px; border-radius: 2px; }
.ltxt { display: flex; flex-direction: column; min-width: 0; }
.llab { font-size: 12px; color: var(--rn-mut); }
.lval { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 20px; font-weight: 500;
  color: var(--rn-ink); line-height: 1.25; white-space: nowrap; font-variant-numeric: tabular-nums; }
.lsub { font-size: 11px; color: var(--rn-mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.muted { color: var(--rn-mut); }
.err { color: var(--rn-bad); }
.card {
  background: var(--rn-card); border-radius: 20px;
  padding: 14px; margin-bottom: 10px; min-width: 0;
}
.muted-card { color: var(--rn-mut); }


.ex-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
.thumb { width: 44px; height: 44px; flex: 0 0 44px; border-radius: 10px; overflow: hidden;
  background: rgba(255, 58, 216, .10); }
.thumb img { width: 44px; height: 44px; object-fit: cover; display: block; }
.thumb-mask { width: 44px; height: 44px; background: var(--rn-mag);
  -webkit-mask-size: 70%; mask-size: 70%; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center; }
.ex-title { flex: 1; min-width: 0; }
.ex-title h3 { margin: 0; font-size: 15px; font-weight: 500; color: var(--rn-ink); text-transform: capitalize;
  overflow-wrap: anywhere; }
.rx { color: var(--rn-mut); font-size: 12.5px; margin-top: 2px; font-variant-numeric: tabular-nums;
  font-family: 'Space Grotesk', 'Geist Mono', monospace; overflow-wrap: anywhere; }
.ex-card.dim { opacity: .55; }
.ex-card.dim h3 { font-weight: 500; }

.state { color: var(--rn-mut); font-size: 13px; margin: 10px 0 0; }

.sets { width: 100%; border-collapse: collapse; margin-top: 10px; table-layout: fixed;
  font-variant-numeric: tabular-nums; }
.sets th { font-size: 11px; font-weight: 400;
  color: var(--rn-mut); text-align: left; padding: 0 0 4px; }
.sets th:first-child { width: 3rem; }
.sets th.r, .sets td.r { text-align: right; width: 5.5rem; }
.sets td { height: 38px; border-top: 1px solid var(--rn-line); color: var(--rn-ink); font-size: 14px;
  font-family: 'Space Grotesk', 'Geist Mono', monospace; white-space: nowrap; }
.sets td.n { color: var(--rn-mut); }
.sets tr.skip td { color: var(--rn-mut); }
.skip-cell { font-family: inherit; font-style: italic; }
.rate { display: inline-block; font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
  font-size: 12px; font-weight: 500; color: var(--c); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
