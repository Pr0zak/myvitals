<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "@/api/client";
import type { Activity } from "@/api/types";

const activities = ref<Activity[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const typeFilter = ref<string>("");

async function load() {
  loading.value = true;
  error.value = null;
  try {
    activities.value = await api.activities({ limit: 200, type: typeFilter.value || undefined });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

const allTypes = computed(() => {
  return Array.from(new Set(activities.value.map((a) => a.type))).sort();
});

function fmtDate(ts: string): string {
  return new Date(ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function fmtKm(meters: number | null): string {
  if (meters === null) return "—";
  return `${(meters / 1000).toFixed(2)} km`;
}

function fmtPace(meters: number | null, seconds: number): string {
  if (!meters || meters < 50) return "—";
  const minPerKm = (seconds / 60) / (meters / 1000);
  const m = Math.floor(minPerKm);
  const s = Math.round((minPerKm - m) * 60);
  return `${m}:${s.toString().padStart(2, "0")} /km`;
}

function fmtSpeed(meters: number | null, seconds: number): string {
  if (!meters || meters < 50) return "—";
  const kmh = (meters / 1000) / (seconds / 3600);
  return `${kmh.toFixed(1)} km/h`;
}

function isRide(t: string): boolean {
  return t.includes("ride") || t.includes("bik");
}

onMounted(load);
</script>

<template>
  <div class="activities">
    <header class="head">
      <h1>Activities</h1>
      <div class="controls">
        <select v-model="typeFilter" @change="load">
          <option value="">all types</option>
          <option v-for="t in allTypes" :key="t" :value="t">{{ t }}</option>
        </select>
        <button @click="load" :disabled="loading">Refresh</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="activities.length === 0" class="empty">
      No activities yet. Connect Strava in <RouterLink to="/settings">Settings</RouterLink>
      and click "Sync last 90 days".
    </div>

    <div v-else class="list">
      <RouterLink
        v-for="a in activities" :key="`${a.source}-${a.source_id}`"
        :to="`/activity/${a.source}/${a.source_id}`"
        class="card"
      >
        <header class="card-head">
          <span class="type">{{ a.type }}</span>
          <span class="when">{{ fmtDate(a.start_at) }}</span>
        </header>
        <h3>{{ a.name ?? "(untitled)" }}</h3>
        <dl class="stats">
          <div><dt>Duration</dt><dd>{{ fmtDuration(a.duration_s) }}</dd></div>
          <div><dt>Distance</dt><dd>{{ fmtKm(a.distance_m) }}</dd></div>
          <div v-if="a.elevation_gain_m !== null"><dt>Elevation</dt><dd>{{ Math.round(a.elevation_gain_m) }} m</dd></div>
          <div><dt>{{ isRide(a.type) ? "Avg speed" : "Pace" }}</dt>
               <dd>{{ isRide(a.type) ? fmtSpeed(a.distance_m, a.duration_s) : fmtPace(a.distance_m, a.duration_s) }}</dd></div>
          <div v-if="a.avg_hr"><dt>Avg HR</dt><dd>{{ Math.round(a.avg_hr) }} bpm</dd></div>
          <div v-if="a.max_hr"><dt>Max HR</dt><dd>{{ Math.round(a.max_hr) }} bpm</dd></div>
          <div v-if="a.avg_power_w"><dt>Avg power</dt><dd>{{ Math.round(a.avg_power_w) }} W</dd></div>
          <div v-if="a.kcal"><dt>Calories</dt><dd>{{ Math.round(a.kcal) }} kcal</dd></div>
          <div v-if="a.suffer_score"><dt>Suffer</dt><dd>{{ Math.round(a.suffer_score) }}</dd></div>
        </dl>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; }
h1 { margin: 0; }
.controls { display: flex; gap: 0.4rem; align-items: center; font-size: 0.85rem; }
select, button { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.5rem; font-size: 0.8rem; font-family: inherit; }
button:disabled { opacity: 0.5; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.empty a { color: var(--accent); }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }

.list { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; margin-top: 1rem; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 1rem; text-decoration: none; color: inherit; display: block;
  transition: border-color 0.15s, transform 0.15s;
}
.card:hover { border-color: var(--accent); transform: translateY(-1px); }
.card-head { display: flex; justify-content: space-between; align-items: baseline; font-size: 0.75rem; }
.type { color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.when { color: var(--muted-2); }
.card h3 { margin: 0.3rem 0 0.6rem; font-size: 1rem; color: var(--text); font-weight: 500; }
dl.stats { margin: 0; display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.4rem 1rem; font-size: 0.85rem; }
dl.stats > div { display: flex; flex-direction: column; }
dt { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
dd { margin: 0.1rem 0 0; color: var(--text); font-weight: 500; }
</style>
