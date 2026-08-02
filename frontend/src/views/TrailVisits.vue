<script setup lang="ts">
/**
 * Every activity linked to one trail, newest first.
 *
 * Web mirror of the phone's TrailVisitsScreen. Both read
 * `GET /trails/{id}/visits`, which already backed the visit counters on
 * the trails list — this surfaces the rows behind the count.
 *
 * `days` is set wide (10 years) rather than the endpoint's 365-day
 * default: the trails list badge is an all-time `visits_total`, so a
 * one-year window here would show fewer rows than the badge promises.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeft, Bike, Footprints, Mountain, Activity as ActivityIcon } from "lucide-vue-next";
import { api } from "@/api/client";
import { fmtDistance } from "@/units";

const route = useRoute();
const trailId = computed(() => Number(route.params.id));

const name = ref<string>("");
const visits = ref<Awaited<ReturnType<typeof api.trailVisits>>["visits"]>([]);
const loading = ref(true);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const r = await api.trailVisits(trailId.value, 3650);
    name.value = r.name;
    visits.value = r.visits;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(trailId, load);

const totalDistance = computed(() =>
  visits.value.reduce((s, v) => s + (v.distance_m ?? 0), 0),
);

function iconFor(type: string) {
  const t = (type ?? "").toLowerCase();
  if (t.includes("hike")) return Mountain;
  if (t.includes("walk") || t.includes("run") || t.includes("jog")) return Footprints;
  if (t.includes("bike") || t.includes("cycl") || t.includes("ride")) return Bike;
  return ActivityIcon;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}

function fmtDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
</script>

<template>
  <section class="trail-visits">
    <header class="head">
      <RouterLink to="/trails" class="back" title="Back to trails">
        <ArrowLeft :size="18" />
      </RouterLink>
      <div class="titles">
        <h2>{{ name || "Trail" }}</h2>
        <p class="sub">
          <template v-if="loading">Loading…</template>
          <template v-else-if="!visits.length">No linked activities</template>
          <template v-else>
            {{ visits.length }} linked
            {{ visits.length === 1 ? "activity" : "activities" }}
            · {{ fmtDistance(totalDistance, 1) }} total
          </template>
        </p>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>

    <p v-else-if="!loading && !visits.length" class="hint">
      Nothing linked yet. Use “Link activities” on the Trails page to match
      GPS activities to this trail.
    </p>

    <ul v-else class="list">
      <li v-for="v in visits" :key="`${v.source}/${v.source_id}`">
        <RouterLink :to="`/activity/${v.source}/${v.source_id}`" class="row">
          <component :is="iconFor(v.type)" :size="16" class="ic" />
          <span class="nm">
            <strong>{{ v.name || v.type }}</strong>
            <em>{{ fmtDate(v.start_at) }}</em>
          </span>
          <span class="stats">
            <b v-if="v.distance_m != null">{{ fmtDistance(v.distance_m, 1) }}</b>
            <em>{{ fmtDuration(v.duration_s) }}</em>
          </span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.trail-visits { padding: 0.5rem 0 2rem; }
.head { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.9rem; }
.back {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--bg-2);
  color: var(--text-soft); text-decoration: none; flex: none;
}
.back:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.titles h2 { margin: 0; font-size: 1.1rem; }
.sub { margin: 0.1rem 0 0; color: var(--muted); font-size: 0.8rem; }
.err { color: #ef4444; }
.hint { color: var(--muted); }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
.row {
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.65rem 0.8rem;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 10px;
  color: inherit; text-decoration: none;
}
.row:hover { border-color: var(--accent, #ef4444); }
.ic { color: var(--muted-2); flex: none; }
.nm { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.nm strong {
  font-weight: 600; font-size: 0.9rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.nm em { font-style: normal; color: var(--muted); font-size: 0.74rem; }
.stats { display: flex; flex-direction: column; align-items: flex-end; flex: none; }
.stats b { font-size: 0.86rem; }
.stats em { font-style: normal; color: var(--muted); font-size: 0.74rem; }
</style>
