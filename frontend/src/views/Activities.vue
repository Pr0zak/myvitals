<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import PolylineThumbnail from "@/components/PolylineThumbnail.vue";
import { api } from "@/api/client";
import type { Activity, ActivityStats } from "@/api/types";
import { chartTheme } from "@/theme";
import { fmtDistance, fmtElevation, distanceVal, distanceUnit } from "@/units";

const TYPE_ICON: Record<string, string> = {
  ebikeride: "🚴",
  ride: "🚴",
  virtualride: "🚴",
  run: "🏃",
  trailrun: "🏃",
  walk: "🚶",
  hike: "🥾",
  hiking: "🥾",
  swim: "🏊",
  swimming_pool: "🏊",
  swimming_open_water: "🏊",
  yoga: "🧘",
  pilates: "🧘",
  strength: "🏋️",
  weightlifting: "🏋️",
  workout: "💪",
  rowing: "🚣",
};
function iconFor(t: string): string {
  return TYPE_ICON[t.toLowerCase()] ?? "•";
}

type SortKey = "date" | "distance" | "duration" | "avg_hr" | "suffer" | "kcal" | "elevation";
type ViewMode = "grid" | "list";
type RangeKey = "7d" | "30d" | "90d" | "365d" | "all";

const RANGES: { key: RangeKey; label: string; days: number | null }[] = [
  { key: "7d", label: "7d", days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "365d", label: "1y", days: 365 },
  { key: "all", label: "all", days: null },
];

const activities = ref<Activity[]>([]);
const stats = ref<ActivityStats | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

const range = ref<RangeKey>(loadPref("range", "30d") as RangeKey);
const sortKey = ref<SortKey>(loadPref("sort", "date") as SortKey);
const sortDesc = ref<boolean>(loadPref("sortDesc", "true") === "true");
const typesActive = ref<Set<string>>(new Set(loadPref("types", "").split(",").filter(Boolean)));
const viewMode = ref<ViewMode>(loadPref("viewMode", "grid") as ViewMode);
const groupByMonth = ref(loadPref("groupByMonth", "false") === "true");

function loadPref(key: string, def: string): string {
  return localStorage.getItem(`myvitals.activities.${key}`) ?? def;
}
function savePref(key: string, val: string) {
  localStorage.setItem(`myvitals.activities.${key}`, val);
}

watch(range, (v) => savePref("range", v));
watch(sortKey, (v) => savePref("sort", v));
watch(sortDesc, (v) => savePref("sortDesc", String(v)));
watch(typesActive, (s) => savePref("types", [...s].join(",")), { deep: true });
watch(viewMode, (v) => savePref("viewMode", v));
watch(groupByMonth, (v) => savePref("groupByMonth", String(v)));

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const params: { since?: Date; limit: number } = { limit: 500 };
    if (days !== null) {
      const since = new Date();
      since.setDate(since.getDate() - days);
      params.since = since;
    }
    const [list, st] = await Promise.all([
      api.activities(params),
      api.activitiesStats(days ?? 365),
    ]);
    activities.value = list;
    stats.value = st;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(range, load);

const allTypes = computed(() =>
  Array.from(new Set(activities.value.map((a) => a.type))).sort()
);

const filtered = computed(() => {
  const types = typesActive.value;
  if (types.size === 0) return activities.value;
  return activities.value.filter((a) => types.has(a.type));
});

const sorted = computed(() => {
  const arr = [...filtered.value];
  const sign = sortDesc.value ? -1 : 1;
  arr.sort((a, b) => {
    const va = sortVal(a);
    const vb = sortVal(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return sign * (va < vb ? -1 : va > vb ? 1 : 0);
  });
  return arr;
});

function sortVal(a: Activity): number | null {
  switch (sortKey.value) {
    case "date": return new Date(a.start_at).getTime();
    case "distance": return a.distance_m ?? null;
    case "duration": return a.duration_s ?? null;
    case "avg_hr": return a.avg_hr ?? null;
    case "suffer": return a.suffer_score ?? null;
    case "kcal": return a.kcal ?? null;
    case "elevation": return a.elevation_gain_m ?? null;
  }
}

const grouped = computed(() => {
  if (!groupByMonth.value) return null;
  const groups: Record<string, Activity[]> = {};
  for (const a of sorted.value) {
    const d = new Date(a.start_at);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    (groups[key] ??= []).push(a);
  }
  return Object.entries(groups).sort(([a], [b]) => (sortDesc.value ? b.localeCompare(a) : a.localeCompare(b)));
});

// === Personal records ===
const records = computed(() => {
  if (activities.value.length === 0) return null;
  const cmp = (k: keyof Activity) => activities.value
    .filter((a) => a[k] != null)
    .sort((x, y) => ((y[k] as number) - (x[k] as number)))[0];
  return {
    longestDistance: cmp("distance_m"),
    longestDuration: cmp("duration_s"),
    mostElevation: cmp("elevation_gain_m"),
    highestSuffer: cmp("suffer_score"),
    mostKcal: cmp("kcal"),
  };
});

function isPR(a: Activity): string[] {
  if (!records.value) return [];
  const tags: string[] = [];
  if (records.value.longestDistance?.source_id === a.source_id) tags.push("🏆 longest");
  if (records.value.mostElevation?.source_id === a.source_id) tags.push("⛰️ most climb");
  if (records.value.highestSuffer?.source_id === a.source_id) tags.push("🔥 most suffer");
  return tags;
}

// === Mini activity heatmap ===
const heatmapOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const bucket: Record<string, number> = {};
  for (const a of activities.value) {
    const d = a.start_at.slice(0, 10);
    bucket[d] = (bucket[d] ?? 0) + a.duration_s / 60; // minutes
  }
  const data = Object.entries(bucket).map(([d, v]) => [d, +v.toFixed(0)]);
  if (data.length === 0) return null;
  const year = new Date(activities.value[0]?.start_at ?? Date.now()).getFullYear();
  return {
    tooltip: { ...t.tooltip, formatter: (p: any) => `${p.value[0]}: ${p.value[1]} min` },
    visualMap: {
      min: 0, max: Math.max(...data.map((d) => d[1] as number)),
      calculable: false, orient: "horizontal", show: false,
      inRange: { color: ["#1e3a5f", "#7dd3fc", "#22c55e"] },
    },
    calendar: {
      top: 24, left: 30, right: 12,
      cellSize: ["auto", 14],
      range: year.toString(),
      itemStyle: { borderColor: t.tooltip.backgroundColor, borderWidth: 1 },
      splitLine: { show: false },
      yearLabel: { show: false },
      monthLabel: { color: t.axisLabel.color, fontSize: 10 },
      dayLabel: { color: t.axisLabel.color, fontSize: 9 },
    },
    series: { type: "heatmap", coordinateSystem: "calendar", data },
  };
});

// === Formatters ===
function fmtDate(ts: string): string {
  return new Date(ts).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}
function fmtDateTime(ts: string): string {
  return new Date(ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function fmtKm(m: number | null): string { return fmtDistance(m, 2); }
function fmtKmShort(m: number | null): string {
  const v = distanceVal(m);
  return v === null ? "—" : `${v.toFixed(1)}${distanceUnit.value}`;
}
function fmtPace(meters: number | null, seconds: number): string {
  if (!meters || meters < 50) return "—";
  const dist = distanceVal(meters)!;  // in km or mi
  const minPerUnit = (seconds / 60) / dist;
  const m = Math.floor(minPerUnit);
  const s = Math.round((minPerUnit - m) * 60);
  return `${m}:${s.toString().padStart(2, "0")}/${distanceUnit.value}`;
}
function fmtSpeed(meters: number | null, seconds: number): string {
  if (!meters || meters < 50) return "—";
  const dist = distanceVal(meters)!;
  return `${(dist / (seconds / 3600)).toFixed(1)} ${distanceUnit.value}/h`;
}
function isRide(t: string): boolean { return t.includes("ride") || t.includes("bik"); }

function intensityColor(s: number | null): string {
  if (s === null) return "var(--muted-2)";
  if (s < 30) return "#22c55e";
  if (s < 80) return "#eab308";
  if (s < 150) return "#f97316";
  return "#ef4444";
}

function pctClass(v: number): string {
  if (Math.abs(v) < 1) return "same";
  return v > 0 ? "up" : "down";
}

function toggleType(t: string) {
  const s = new Set(typesActive.value);
  if (s.has(t)) s.delete(t); else s.add(t);
  typesActive.value = s;
}

const monthLabel = (key: string) =>
  new Date(`${key}-01`).toLocaleDateString([], { month: "long", year: "numeric" });
</script>

<template>
  <div class="activities">
    <header class="head">
      <h1>Activities</h1>
      <div class="controls">
        <div class="ranges">
          <button v-for="r in RANGES" :key="r.key"
                  :class="{ active: range === r.key }" @click="range = r.key">{{ r.label }}</button>
        </div>
        <RouterLink to="/activities/map" class="map-link">🗺️ Map view</RouterLink>
      </div>
    </header>

    <!-- Stats banner -->
    <Card v-if="stats && !loading" :title="`Stats — ${stats.period_label}`">
      <div class="stat-row">
        <div class="stat">
          <div class="num">{{ stats.n_activities }}</div>
          <div class="lbl">activities <span :class="pctClass(stats.period_pct_vs_prev.n)">
            {{ stats.period_pct_vs_prev.n > 0 ? "↑" : stats.period_pct_vs_prev.n < 0 ? "↓" : "·" }}
            {{ Math.abs(stats.period_pct_vs_prev.n).toFixed(0) }}%
          </span></div>
        </div>
        <div class="stat">
          <div class="num">{{ distanceVal(stats.total_distance_m)?.toFixed(0) }} <span class="unit">{{ distanceUnit }}</span></div>
          <div class="lbl">distance <span :class="pctClass(stats.period_pct_vs_prev.distance)">
            {{ stats.period_pct_vs_prev.distance > 0 ? "↑" : "↓" }}
            {{ Math.abs(stats.period_pct_vs_prev.distance).toFixed(0) }}%
          </span></div>
        </div>
        <div class="stat">
          <div class="num">{{ Math.round(stats.total_duration_s / 3600) }} <span class="unit">h</span></div>
          <div class="lbl">moving time</div>
        </div>
        <div class="stat">
          <div class="num">{{ Math.round(stats.total_elevation_m).toLocaleString() }} <span class="unit">m</span></div>
          <div class="lbl">climbed</div>
        </div>
        <div class="stat">
          <div class="num">{{ Math.round(stats.total_kcal).toLocaleString() }}</div>
          <div class="lbl">kcal burned</div>
        </div>
        <div class="stat">
          <div class="num">{{ stats.streak_days }} <span class="unit">d</span></div>
          <div class="lbl">streak</div>
        </div>
      </div>
    </Card>

    <!-- Activity heatmap -->
    <Card v-if="heatmapOption" title="Activity calendar">
      <div class="heat"><VChart :option="heatmapOption" autoresize/></div>
    </Card>

    <!-- Personal records -->
    <Card v-if="records" title="Personal records">
      <div class="pr-grid">
        <RouterLink v-if="records.longestDistance"
                    :to="`/activity/${records.longestDistance.source}/${records.longestDistance.source_id}`"
                    class="pr">
          <div class="pr-label">🏆 Longest distance</div>
          <div class="pr-val">{{ fmtKm(records.longestDistance.distance_m) }}</div>
          <div class="pr-meta">{{ records.longestDistance.name ?? records.longestDistance.type }}</div>
        </RouterLink>
        <RouterLink v-if="records.longestDuration"
                    :to="`/activity/${records.longestDuration.source}/${records.longestDuration.source_id}`"
                    class="pr">
          <div class="pr-label">⏱ Longest duration</div>
          <div class="pr-val">{{ fmtDuration(records.longestDuration.duration_s) }}</div>
          <div class="pr-meta">{{ records.longestDuration.name ?? records.longestDuration.type }}</div>
        </RouterLink>
        <RouterLink v-if="records.mostElevation"
                    :to="`/activity/${records.mostElevation.source}/${records.mostElevation.source_id}`"
                    class="pr">
          <div class="pr-label">⛰️ Most climbed</div>
          <div class="pr-val">{{ fmtElevation(records.mostElevation.elevation_gain_m!) }}</div>
          <div class="pr-meta">{{ records.mostElevation.name ?? records.mostElevation.type }}</div>
        </RouterLink>
        <RouterLink v-if="records.highestSuffer"
                    :to="`/activity/${records.highestSuffer.source}/${records.highestSuffer.source_id}`"
                    class="pr">
          <div class="pr-label">🔥 Highest suffer</div>
          <div class="pr-val">{{ Math.round(records.highestSuffer.suffer_score!) }}</div>
          <div class="pr-meta">{{ records.highestSuffer.name ?? records.highestSuffer.type }}</div>
        </RouterLink>
      </div>
    </Card>

    <!-- Filter / sort bar -->
    <Card title="Filter & sort">
      <div class="bar">
        <div class="chip-row">
          <span class="hint">Types:</span>
          <button v-for="t in allTypes" :key="t"
                  class="chip" :class="{ active: typesActive.has(t) }"
                  @click="toggleType(t)">
            <span class="emoji">{{ iconFor(t) }}</span> {{ t }}
          </button>
          <button v-if="typesActive.size > 0" class="chip-clear" @click="typesActive = new Set()">clear</button>
        </div>
        <div class="sort-row">
          <span class="hint">Sort:</span>
          <select v-model="sortKey" class="sel">
            <option value="date">Date</option>
            <option value="distance">Distance</option>
            <option value="duration">Duration</option>
            <option value="elevation">Elevation</option>
            <option value="avg_hr">Avg HR</option>
            <option value="suffer">Suffer score</option>
            <option value="kcal">Calories</option>
          </select>
          <button class="dir" @click="sortDesc = !sortDesc">{{ sortDesc ? "↓ desc" : "↑ asc" }}</button>
          <span class="spacer"></span>
          <span class="hint">View:</span>
          <button class="dir" :class="{ active: viewMode === 'grid' }" @click="viewMode = 'grid'">grid</button>
          <button class="dir" :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'">list</button>
          <label class="dir">
            <input type="checkbox" v-model="groupByMonth"/> group by month
          </label>
        </div>
      </div>
    </Card>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="sorted.length === 0" class="empty">
      No activities matching the current filters.
    </div>

    <!-- Grouped or flat -->
    <template v-else>
      <template v-if="grouped">
        <div v-for="[key, list] in grouped" :key="key" class="group">
          <h2 class="group-h">{{ monthLabel(key) }} <span class="group-n">{{ list.length }}</span></h2>
          <div :class="viewMode === 'grid' ? 'list' : 'rows'">
            <component :is="'RouterLink'" v-for="a in list" :key="`${a.source}-${a.source_id}`"
                       :to="`/activity/${a.source}/${a.source_id}`"
                       :class="viewMode === 'grid' ? 'card' : 'row'">
              <template v-if="viewMode === 'grid'">
                <PolylineThumbnail :polyline="a.polyline" :size="100" class="thumb"/>
                <header class="card-head">
                  <span class="type">{{ iconFor(a.type) }} {{ a.type }}</span>
                  <span class="when">{{ fmtDate(a.start_at) }}</span>
                </header>
                <h3>{{ a.name ?? "(untitled)" }}</h3>
                <div class="badges">
                  <span v-for="b in isPR(a)" :key="b" class="badge">{{ b }}</span>
                </div>
                <dl class="stats">
                  <div><dt>Time</dt><dd>{{ fmtDuration(a.duration_s) }}</dd></div>
                  <div><dt>Distance</dt><dd>{{ fmtKm(a.distance_m) }}</dd></div>
                  <div v-if="a.elevation_gain_m"><dt>Elev</dt><dd>{{ fmtElevation(a.elevation_gain_m) }}</dd></div>
                  <div><dt>{{ isRide(a.type) ? "Speed" : "Pace" }}</dt>
                       <dd>{{ isRide(a.type) ? fmtSpeed(a.distance_m, a.duration_s) : fmtPace(a.distance_m, a.duration_s) }}</dd></div>
                  <div v-if="a.avg_hr"><dt>HR</dt><dd>{{ Math.round(a.avg_hr) }} / {{ Math.round(a.max_hr ?? 0) }}</dd></div>
                  <div v-if="a.suffer_score">
                    <dt>Suffer</dt>
                    <dd><span class="suffer" :style="{ color: intensityColor(a.suffer_score) }">{{ Math.round(a.suffer_score) }}</span></dd>
                  </div>
                </dl>
              </template>
              <template v-else>
                <PolylineThumbnail :polyline="a.polyline" :size="48"/>
                <span class="row-emoji">{{ iconFor(a.type) }}</span>
                <span class="row-when">{{ fmtDateTime(a.start_at) }}</span>
                <span class="row-name">{{ a.name ?? "(untitled)" }}</span>
                <span class="row-stat">{{ fmtKmShort(a.distance_m) }}</span>
                <span class="row-stat">{{ fmtDuration(a.duration_s) }}</span>
                <span class="row-stat" v-if="a.elevation_gain_m">{{ fmtElevation(a.elevation_gain_m) }}</span>
                <span class="row-stat" v-if="a.avg_hr">{{ Math.round(a.avg_hr) }} bpm</span>
                <span class="row-stat" v-if="a.suffer_score" :style="{ color: intensityColor(a.suffer_score) }">{{ Math.round(a.suffer_score) }}</span>
              </template>
            </component>
          </div>
        </div>
      </template>

      <template v-else>
        <div :class="viewMode === 'grid' ? 'list' : 'rows'">
          <component :is="'RouterLink'" v-for="a in sorted" :key="`${a.source}-${a.source_id}`"
                     :to="`/activity/${a.source}/${a.source_id}`"
                     :class="viewMode === 'grid' ? 'card' : 'row'">
            <template v-if="viewMode === 'grid'">
              <PolylineThumbnail :polyline="a.polyline" :size="100" class="thumb"/>
              <header class="card-head">
                <span class="type">{{ iconFor(a.type) }} {{ a.type }}</span>
                <span class="when">{{ fmtDate(a.start_at) }}</span>
              </header>
              <h3>{{ a.name ?? "(untitled)" }}</h3>
              <div class="badges">
                <span v-for="b in isPR(a)" :key="b" class="badge">{{ b }}</span>
              </div>
              <dl class="stats">
                <div><dt>Time</dt><dd>{{ fmtDuration(a.duration_s) }}</dd></div>
                <div><dt>Distance</dt><dd>{{ fmtKm(a.distance_m) }}</dd></div>
                <div v-if="a.elevation_gain_m"><dt>Elev</dt><dd>{{ fmtElevation(a.elevation_gain_m) }}</dd></div>
                <div><dt>{{ isRide(a.type) ? "Speed" : "Pace" }}</dt>
                     <dd>{{ isRide(a.type) ? fmtSpeed(a.distance_m, a.duration_s) : fmtPace(a.distance_m, a.duration_s) }}</dd></div>
                <div v-if="a.avg_hr"><dt>HR</dt><dd>{{ Math.round(a.avg_hr) }} / {{ Math.round(a.max_hr ?? 0) }}</dd></div>
                <div v-if="a.suffer_score">
                  <dt>Suffer</dt>
                  <dd><span class="suffer" :style="{ color: intensityColor(a.suffer_score) }">{{ Math.round(a.suffer_score) }}</span></dd>
                </div>
              </dl>
            </template>
            <template v-else>
              <PolylineThumbnail :polyline="a.polyline" :size="48"/>
              <span class="row-emoji">{{ iconFor(a.type) }}</span>
              <span class="row-when">{{ fmtDateTime(a.start_at) }}</span>
              <span class="row-name">{{ a.name ?? "(untitled)" }}</span>
              <span class="row-stat">{{ fmtKmShort(a.distance_m) }}</span>
              <span class="row-stat">{{ fmtDuration(a.duration_s) }}</span>
              <span class="row-stat" v-if="a.elevation_gain_m">{{ fmtElevation(a.elevation_gain_m) }}</span>
              <span class="row-stat" v-if="a.avg_hr">{{ Math.round(a.avg_hr) }} bpm</span>
              <span class="row-stat" v-if="a.suffer_score" :style="{ color: intensityColor(a.suffer_score) }">{{ Math.round(a.suffer_score) }}</span>
            </template>
          </component>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }
h1 { margin: 0; }
.controls { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; }
.ranges { display: flex; gap: 0.25rem; }
.ranges button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.8rem; }
.ranges button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.map-link { color: var(--accent); text-decoration: none; font-size: 0.9rem; padding: 0.3rem 0.6rem; border: 1px solid var(--border); border-radius: 4px; }
.map-link:hover { border-color: var(--accent); }

/* Stats banner */
.stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1rem; }
.stat .num { font-size: 1.6rem; font-weight: 300; color: var(--text); line-height: 1; }
.stat .num .unit { font-size: 0.85rem; color: var(--muted); margin-left: 0.2rem; }
.stat .lbl { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.3rem; }
.stat .up { color: var(--good); margin-left: 0.3rem; }
.stat .down { color: var(--bad); margin-left: 0.3rem; }
.stat .same { color: var(--muted-2); margin-left: 0.3rem; }

/* Heatmap */
.heat { width: 100%; height: 200px; }
.heat > * { width: 100%; height: 100%; }

/* PRs */
.pr-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.6rem; }
.pr {
  display: block; background: var(--surface-2); padding: 0.7rem; border-radius: 8px;
  border: 1px solid var(--border); text-decoration: none; color: inherit;
  transition: border-color 0.15s;
}
.pr:hover { border-color: var(--accent); }
.pr-label { color: var(--muted-2); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.pr-val { color: var(--accent); font-size: 1.4rem; font-weight: 500; margin: 0.2rem 0; }
.pr-meta { color: var(--muted); font-size: 0.8rem; }

/* Filter bar */
.bar { display: flex; flex-direction: column; gap: 0.6rem; }
.chip-row { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
.sort-row { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
.hint { color: var(--muted-2); font-size: 0.8rem; }
.spacer { flex: 1; }
.chip {
  background: var(--surface-2); color: var(--muted); border: 1px solid var(--border);
  border-radius: 100px; padding: 0.25rem 0.7rem; font-size: 0.8rem; cursor: pointer; font-family: inherit;
}
.chip:hover { color: var(--text); }
.chip.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.chip .emoji { margin-right: 0.2rem; }
.chip-clear { background: transparent; color: var(--bad); border: 0; cursor: pointer; font-size: 0.75rem; padding: 0.25rem 0.5rem; }
.sel {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.3rem 0.5rem; font-size: 0.85rem; font-family: inherit;
}
.dir, label.dir {
  background: var(--surface); color: var(--muted); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.3rem 0.6rem; font-size: 0.8rem; cursor: pointer; font-family: inherit;
  display: inline-flex; align-items: center; gap: 0.3rem;
}
.dir.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }

/* Group headers */
.group { margin-top: 1rem; }
.group-h { font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin: 1rem 0 0.6rem; font-weight: 500; }
.group-n { color: var(--muted-2); margin-left: 0.4rem; font-size: 0.75rem; }

/* Grid view */
.list { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 1rem; text-decoration: none; color: inherit; display: block;
  transition: border-color 0.15s, transform 0.15s;
  position: relative;
}
.card:hover { border-color: var(--accent); transform: translateY(-1px); }
.card .thumb { float: right; margin: 0 0 0.5rem 0.7rem; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; font-size: 0.75rem; }
.type { color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.when { color: var(--muted-2); }
.card h3 { margin: 0.3rem 0 0.4rem; font-size: 1rem; color: var(--text); font-weight: 500; clear: none; }
.badges { margin-bottom: 0.5rem; }
.badge { background: var(--surface-2); color: var(--accent); border: 1px solid var(--accent); border-radius: 4px; padding: 0.1rem 0.4rem; font-size: 0.7rem; margin-right: 0.3rem; }
dl.stats { margin: 0; display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.4rem 1rem; font-size: 0.85rem; clear: both; }
dl.stats > div { display: flex; flex-direction: column; }
dt { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
dd { margin: 0.1rem 0 0; color: var(--text); font-weight: 500; }
.suffer { font-weight: 600; }

/* List view */
.rows { display: flex; flex-direction: column; gap: 0.3rem; }
.row {
  display: grid;
  grid-template-columns: 48px 24px 140px 1fr repeat(5, auto);
  align-items: center; gap: 0.6rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.4rem 0.7rem; text-decoration: none; color: inherit;
  font-size: 0.85rem;
}
.row:hover { border-color: var(--accent); }
.row-emoji { font-size: 1.2rem; }
.row-when { color: var(--muted); font-size: 0.75rem; }
.row-name { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-stat { color: var(--muted); font-variant-numeric: tabular-nums; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
