<script setup lang="ts">
/**
 * Read-only view of a specific day's strength workout. Reached via the
 * clickable week strip on /workout/strength/today. Past dates render
 * the persisted workout (with logged sets/RPE); future dates render
 * the planner's preview as a "Preview" card.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter, RouterLink } from "vue-router";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { StrengthWorkoutDetail } from "@/api/types";

const route = useRoute();
const router = useRouter();

const workout = ref<StrengthWorkoutDetail | null>(null);
const notFound = ref(false);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  const date = String(route.params.date ?? "");
  if (!date) { error.value = "no date in route"; loading.value = false; return; }
  loading.value = true; error.value = null; notFound.value = false;
  try {
    const w = await api.strengthWorkoutByDate(date);
    if (w === null) { notFound.value = true; }
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

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric", year: "numeric",
    });
  } catch { return iso; }
}
</script>

<template>
  <section class="day-view">
    <header class="page-head">
      <RouterLink class="back" :to="{ name: 'workout-strength-today' }">
        ← Today
      </RouterLink>
      <h1>{{ workout ? fmtDate(workout.date) : (route.params.date as string) }}</h1>
      <span v-if="isPreview" class="preview-pip">Preview</span>
    </header>

    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <Card v-else-if="notFound" class="not-found" :flat="true">
      No workout recorded for this day.
    </Card>

    <template v-else-if="workout">
      <Card :flat="true" class="hero">
        <div class="split">
          {{ workout.split_focus.charAt(0).toUpperCase() + workout.split_focus.slice(1) }}
          {{ isPreview ? "" : "day" }}
        </div>
        <div class="muscles">{{ muscleGroupsFor(workout.split_focus) }}</div>
        <div v-if="!isPreview" class="status-row">
          <span class="status-pip" :class="workout.status">
            {{ workout.status === "completed" ? "Complete"
               : workout.status === "in_progress" ? "In progress"
               : workout.status === "skipped" ? "Skipped"
               : workout.status === "planned" ? "Planned"
               : workout.status }}
          </span>
        </div>
      </Card>

      <Card v-for="wex in workout.exercises" :key="wex.id"
            class="ex-card" :flat="true">
        <div class="ex-name">{{ wex.exercise_id.replace(/_/g, " ") }}</div>
        <div class="ex-target">
          {{ wex.target_sets }}×{{
            wex.target_reps_low === wex.target_reps_high
              ? wex.target_reps_low
              : `${wex.target_reps_low}-${wex.target_reps_high}`
          }}{{ wex.target_weight_lb !== null ? ` @ ${wex.target_weight_lb}lb` : "" }}
        </div>
        <ul v-if="wex.sets.length" class="sets">
          <li v-for="s in [...wex.sets].sort((a, b) => a.set_number - b.set_number)"
              :key="s.set_number"
              v-show="s.actual_reps !== null">
            <span class="num">{{ s.set_number }}</span>
            <span class="result">
              {{ s.actual_weight_lb ?? "—" }} lb × {{ s.actual_reps }}
            </span>
            <span v-if="s.rating !== null" class="rpe" :class="`rpe-${s.rating}`">
              RPE {{ s.rating }}
            </span>
          </li>
        </ul>
      </Card>
    </template>
  </section>
</template>

<style scoped>
.day-view { max-width: 720px; margin: 0 auto; padding: 1rem; }
.page-head { display: flex; align-items: baseline; gap: 0.6rem;
             margin-bottom: 1rem; flex-wrap: wrap; }
.page-head h1 { margin: 0; font-size: 1.25rem; }
.back { color: var(--muted); text-decoration: none; font-size: 0.85rem; }
.back:hover { color: var(--text); }
.preview-pip { background: rgba(234, 179, 8, 0.18); color: #eab308;
               padding: 0.15rem 0.5rem; border-radius: 999px;
               font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em;
               text-transform: uppercase; }
.muted { color: var(--muted); }
.err { color: var(--accent, #ef4444); }
.not-found { padding: 1rem; color: var(--muted); }
.hero { padding: 1rem; margin-bottom: 0.6rem; }
.split { font-size: 1.1rem; font-weight: 600; }
.muscles { color: var(--muted); font-size: 0.85rem; }
.status-row { margin-top: 0.4rem; }
.status-pip { font-size: 0.7rem; letter-spacing: 0.05em;
              text-transform: uppercase; font-weight: 700; }
.status-pip.completed { color: #22c55e; }
.status-pip.in_progress { color: #eab308; }
.status-pip.skipped { color: var(--muted); }
.status-pip.planned { color: var(--accent, #ef4444); }
.ex-card { padding: 0.8rem; margin-bottom: 0.5rem; }
.ex-name { font-weight: 600; text-transform: capitalize; }
.ex-target { color: var(--muted); font-size: 0.85rem;
             font-family: 'Geist Mono', ui-monospace, monospace; }
.sets { list-style: none; padding: 0; margin: 0.4rem 0 0; }
.sets li { display: flex; gap: 0.6rem; padding: 0.15rem 0;
           font-size: 0.85rem; align-items: center; }
.sets .num { color: var(--muted); width: 1.4rem; }
.sets .result { font-family: 'Geist Mono', ui-monospace, monospace; }
.sets .rpe { font-size: 0.75rem; font-weight: 600; }
.rpe-1 { color: #ef4444; }
.rpe-2 { color: #f97316; }
.rpe-3 { color: #fbbf24; }
.rpe-4 { color: #84cc16; }
.rpe-5 { color: #22c55e; }
</style>
