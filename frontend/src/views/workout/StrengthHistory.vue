<script setup lang="ts">
/**
 * Strength workout history — chronological list. Tap-through opens the
 * full detail with every set's actual weight/reps/rating.
 *
 * Phase 2: read-only. Active-workout / set-logging UI lands in Phase 4.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import Card from "@/components/Card.vue";
import type { StrengthExercise, StrengthWorkoutDetail } from "@/api/types";

interface ListItem {
  id: number;
  date: string;
  split_focus: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  generated_at: string;
}

const items = ref<ListItem[]>([]);
const detail = ref<StrengthWorkoutDetail | null>(null);
const detailId = ref<number | null>(null);
const catalogById = ref<Record<string, StrengthExercise>>({});
const loading = ref(true);
const error = ref<string>("");

async function loadList() {
  if (!queryToken.value) return;
  loading.value = true;
  error.value = "";
  try {
    const r = await api.strengthWorkouts({ limit: 200 });
    items.value = r.workouts;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function loadCatalog() {
  if (!queryToken.value) return;
  try {
    const r = await api.strengthExercises();
    catalogById.value = Object.fromEntries(r.exercises.map((e) => [e.id, e]));
  } catch { /* swallow — names will fall back to slug */ }
}

async function showDetail(id: number) {
  detailId.value = id;
  detail.value = null;
  try {
    detail.value = await api.strengthWorkout(id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

function closeDetail() { detail.value = null; detailId.value = null; }

function exerciseName(id: string): string {
  return catalogById.value[id]?.name ?? id.replace(/_/g, " ");
}

function fmtDuration(start: string | null, end: string | null): string {
  if (!start || !end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

const grouped = computed(() => {
  const byMonth: Record<string, ListItem[]> = {};
  for (const it of items.value) {
    const k = it.date.slice(0, 7); // YYYY-MM
    (byMonth[k] ??= []).push(it);
  }
  return Object.entries(byMonth).sort(([a], [b]) => b.localeCompare(a));
});

onMounted(() => { loadList(); loadCatalog(); });
</script>

<template>
  <main class="strength-history">
    <h1>Workout history</h1>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load history.</p>
    <p v-else-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>
    <Card v-else-if="items.length === 0" title="No workouts yet">
      <p class="hint">
        Once the strength plan generator ships in v0.6.0, completed sessions
        will land here. You can also manually create a session via the API.
      </p>
    </Card>

    <template v-else>
      <div v-for="[ym, group] in grouped" :key="ym" class="group">
        <h2>{{ new Date(`${ym}-01`).toLocaleString(undefined, { month: 'long', year: 'numeric' }) }}</h2>
        <ul class="list">
          <li v-for="it in group" :key="it.id" :class="`status-${it.status}`" @click="showDetail(it.id)">
            <div class="date">
              <strong>{{ new Date(it.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) }}</strong>
              <span class="status">{{ it.status }}</span>
            </div>
            <div class="meta">
              <span class="focus">{{ it.split_focus }}</span>
              <span v-if="it.started_at && it.completed_at" class="dur">
                {{ fmtDuration(it.started_at, it.completed_at) }}
              </span>
            </div>
          </li>
        </ul>
      </div>
    </template>

    <!-- Detail drawer -->
    <div v-if="detailId !== null" class="overlay" @click.self="closeDetail">
      <div class="drawer">
        <header>
          <h2 v-if="detail">
            {{ new Date(detail.date).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' }) }}
            <small>· {{ detail.split_focus }}</small>
          </h2>
          <h2 v-else>Loading…</h2>
          <button class="close" @click="closeDetail">✕</button>
        </header>

        <template v-if="detail">
          <div class="ctx">
            <span class="status" :class="`status-${detail.status}`">{{ detail.status }}</span>
            <span v-if="detail.recovery_score_used != null" class="metric">
              recovery {{ Math.round(detail.recovery_score_used) }}
            </span>
            <span v-if="detail.sleep_h_used != null" class="metric">
              sleep {{ detail.sleep_h_used.toFixed(1) }}h
            </span>
          </div>

          <div v-for="ex in detail.exercises" :key="ex.id" class="ex">
            <h3>
              {{ ex.order_index + 1 }}. {{ exerciseName(ex.exercise_id) }}
              <small v-if="ex.superset_id">· superset {{ ex.superset_id }}</small>
            </h3>
            <p class="target">
              Target: {{ ex.target_sets }} × {{ ex.target_reps_low === ex.target_reps_high
                ? ex.target_reps_low : `${ex.target_reps_low}–${ex.target_reps_high}` }} reps
              <span v-if="ex.target_weight_lb"> @ {{ ex.target_weight_lb }} lb</span>
              <span class="rest">· {{ ex.target_rest_s }}s rest</span>
            </p>
            <table v-if="ex.sets.length" class="sets">
              <thead><tr><th>#</th><th>Weight</th><th>Reps</th><th>Rating</th></tr></thead>
              <tbody>
                <tr v-for="s in ex.sets" :key="s.id" :class="{ skipped: s.skipped }">
                  <td>{{ s.set_number }}</td>
                  <td>{{ s.actual_weight_lb ?? '—' }}<span class="unit">{{ s.actual_weight_lb != null ? ' lb' : '' }}</span></td>
                  <td>{{ s.actual_reps ?? '—' }}</td>
                  <td><span v-if="s.rating" class="rating" :data-r="s.rating">{{ s.rating }}</span><span v-else>—</span></td>
                </tr>
              </tbody>
            </table>
            <p v-else class="hint">No sets logged.</p>
          </div>
        </template>
      </div>
    </div>
  </main>
</template>

<style scoped>
.strength-history { max-width: 720px; }
h1 { margin: 0 0 0.6rem; }
h2 { margin: 1.2rem 0 0.6rem; font-size: 0.85rem;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.hint { color: var(--muted); }
.err { color: #f87171; }

.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.list li {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 10px;
  padding: 0.7rem 0.9rem; cursor: pointer;
  display: flex; justify-content: space-between; align-items: center;
  transition: border-color 0.12s;
}
.list li:hover { border-color: var(--accent); }
.list li.status-skipped { opacity: 0.55; }
.list li.status-in_progress { border-color: #f59e0b; }
.date strong { font-size: 0.95rem; }
.date .status {
  margin-left: 0.6rem; font-size: 0.7rem; text-transform: uppercase;
  color: var(--muted); letter-spacing: 0.06em;
}
.meta { font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 0.82rem; color: var(--muted); display: flex; gap: 0.8rem; }
.focus { text-transform: capitalize; }

/* Detail drawer */
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100;
  display: flex; justify-content: flex-end; }
.drawer { width: min(560px, 100%); height: 100%; overflow-y: auto;
  background: var(--bg-1); border-left: 1px solid var(--line); padding: 1rem 1.2rem; }
.drawer header { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.6rem; }
.drawer header h2 { margin: 0; font-size: 1rem; text-transform: none;
  letter-spacing: 0; color: var(--text); }
.drawer header h2 small { color: var(--muted); font-weight: 400; }
.close { background: none; border: none; color: var(--muted);
  font-size: 1.2rem; cursor: pointer; padding: 0.2rem 0.4rem; }
.ctx { display: flex; gap: 0.8rem; margin: 0.4rem 0 1rem;
  font-size: 0.78rem; color: var(--muted); }
.ctx .metric { font-family: 'Geist Mono', ui-monospace, monospace; }
.ctx .status { padding: 0.15rem 0.5rem; border-radius: 4px;
  background: var(--bg-2); border: 1px solid var(--line);
  text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.7rem; }
.ex { margin-bottom: 1.2rem; padding-bottom: 0.8rem;
  border-bottom: 1px solid var(--line); }
.ex h3 { margin: 0 0 0.3rem; font-size: 0.95rem; }
.ex h3 small { color: var(--muted); font-weight: 400; }
.target { margin: 0 0 0.5rem; color: var(--muted); font-size: 0.82rem;
  font-family: 'Geist Mono', ui-monospace, monospace; }
.target .rest { color: var(--muted-2); }
.sets { width: 100%; border-collapse: collapse; font-size: 0.85rem;
  font-family: 'Geist Mono', ui-monospace, monospace; }
.sets th, .sets td { text-align: left; padding: 0.25rem 0.4rem; }
.sets thead th { color: var(--muted); border-bottom: 1px solid var(--line);
  font-weight: 500; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.06em; }
.sets tbody tr.skipped { opacity: 0.5; }
.rating {
  display: inline-block; width: 1.4rem; height: 1.4rem; line-height: 1.4rem;
  text-align: center; border-radius: 50%; font-weight: 600;
  font-family: ui-sans-serif, system-ui;
}
.rating[data-r="1"] { background: rgba(239,68,68,0.2); color: #ef4444; }
.rating[data-r="2"] { background: rgba(249,115,22,0.2); color: #f97316; }
.rating[data-r="3"] { background: rgba(245,158,11,0.2); color: #f59e0b; }
.rating[data-r="4"] { background: rgba(132,204,22,0.2); color: #84cc16; }
.rating[data-r="5"] { background: rgba(34,197,94,0.2); color: #22c55e; }
.unit { color: var(--muted); }
</style>
