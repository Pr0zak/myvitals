<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import polylineDecoder from "@mapbox/polyline";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useRoute, useRouter } from "vue-router";

import Card from "@/components/Card.vue";
import ActivityIcon from "@/components/ActivityIcon.vue";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import type { Activity, HeartRateSeries } from "@/api/types";
import { chartTheme, effectiveTheme } from "@/theme";
import { fmtDistance, fmtElevation, distanceVal, distanceUnit } from "@/units";

const route = useRoute();
const router = useRouter();

const activities = ref<Activity[]>([]);
const search = ref("");

const a = ref<Activity | null>(null);
const b = ref<Activity | null>(null);
const aHr = ref<HeartRateSeries | null>(null);
const bHr = ref<HeartRateSeries | null>(null);

const COLOR_A = "#38bdf8";
const COLOR_B = "#a78bfa";

async function loadList() {
  activities.value = await api.activities({ limit: 500 });
  // Initial selection from URL ?a=src/id&b=src/id, else last two activities.
  const aQ = (route.query.a as string | undefined)?.split("/");
  const bQ = (route.query.b as string | undefined)?.split("/");
  if (aQ?.length === 2) a.value = activities.value.find((x) => x.source === aQ[0] && x.source_id === aQ[1]) ?? null;
  if (bQ?.length === 2) b.value = activities.value.find((x) => x.source === bQ[0] && x.source_id === bQ[1]) ?? null;
  if (!a.value && activities.value[0]) a.value = activities.value[0];
  if (!b.value && activities.value[1]) b.value = activities.value[1];
}

async function loadDetails() {
  const tasks: Promise<unknown>[] = [];
  if (a.value) tasks.push(api.heartRate({
    since: new Date(a.value.start_at),
    until: new Date(new Date(a.value.start_at).getTime() + a.value.duration_s * 1000 + 60_000),
  }).then((r) => { aHr.value = r; }).catch(() => { aHr.value = null; }));
  if (b.value) tasks.push(api.heartRate({
    since: new Date(b.value.start_at),
    until: new Date(new Date(b.value.start_at).getTime() + b.value.duration_s * 1000 + 60_000),
  }).then((r) => { bHr.value = r; }).catch(() => { bHr.value = null; }));
  await Promise.all(tasks);
}

watch([a, b], () => {
  loadDetails();
  // Sync URL so the comparison is bookmarkable.
  router.replace({ query: {
    a: a.value ? `${a.value.source}/${a.value.source_id}` : undefined,
    b: b.value ? `${b.value.source}/${b.value.source_id}` : undefined,
  }});
});

const filtered = computed(() => {
  if (!search.value) return activities.value.slice(0, 60);
  const s = search.value.toLowerCase();
  return activities.value.filter((x) =>
    (x.name?.toLowerCase().includes(s)) ||
    x.type.includes(s) ||
    x.start_at.startsWith(s)
  ).slice(0, 60);
});

// === Stats table ===
function fmtDuration(s: number | null | undefined): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function isRide(t: string): boolean { return t.includes("ride") || t.includes("bik"); }
function fmtPace(meters: number | null | undefined, seconds: number | null | undefined): string {
  if (!meters || !seconds || meters < 50) return "—";
  const dist = distanceVal(meters)!;
  const minPerUnit = (seconds / 60) / dist;
  const m = Math.floor(minPerUnit);
  const s = Math.round((minPerUnit - m) * 60);
  return `${m}:${s.toString().padStart(2, "0")}/${distanceUnit.value}`;
}
function fmtSpeed(meters: number | null | undefined, seconds: number | null | undefined): string {
  if (!meters || !seconds || meters < 50) return "—";
  return `${(distanceVal(meters)! / (seconds / 3600)).toFixed(1)} ${distanceUnit.value}/h`;
}
function fmtNum(v: number | null | undefined, digits = 0): string {
  return v == null ? "—" : v.toFixed(digits);
}
function delta(va: number | null | undefined, vb: number | null | undefined, lowerIsBetter = false): { pct: number; cls: "win-a" | "win-b" | "" } | null {
  if (va == null || vb == null || va === 0 || vb === 0) return null;
  const pct = ((va - vb) / Math.abs(vb)) * 100;
  const aWins = lowerIsBetter ? va < vb : va > vb;
  return { pct, cls: Math.abs(pct) < 0.5 ? "" : aWins ? "win-a" : "win-b" };
}

// === Map ===
const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let layers: L.Layer[] = [];
function rerenderMap() {
  if (!mapEl.value) return;
  if (!map) {
    map = L.map(mapEl.value, { zoomControl: true });
    const dark = effectiveTheme.value === "dark";
    L.tileLayer(dark
      ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      { attribution: "© OpenStreetMap, © CARTO", subdomains: "abcd", maxZoom: 19 }
    ).addTo(map);
  }
  for (const l of layers) map.removeLayer(l);
  layers = [];
  const allPts: L.LatLng[] = [];
  for (const [act, color] of [[a.value, COLOR_A], [b.value, COLOR_B]] as const) {
    if (!act?.polyline) continue;
    let coords: [number, number][];
    try { coords = polylineDecoder.decode(act.polyline) as [number, number][]; }
    catch { continue; }
    if (coords.length < 2) continue;
    const ln = L.polyline(coords, { color, weight: 3, opacity: 0.85 }).addTo(map);
    layers.push(ln);
    coords.forEach((c) => allPts.push(L.latLng(c[0], c[1])));
  }
  if (allPts.length) map.fitBounds(L.latLngBounds(allPts), { padding: [30, 30] });
  else map.setView([0, 0], 2);
}
watch([a, b, effectiveTheme], () => setTimeout(rerenderMap, 50));

// === HR overlay chart ===
const hrOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  // Normalize each HR series to "elapsed minutes from start" so we compare apples to apples.
  const norm = (act: Activity | null, hr: HeartRateSeries | null) => {
    if (!act || !hr) return [];
    const t0 = new Date(act.start_at).getTime();
    return hr.points.map((p) => [(new Date(p.time).getTime() - t0) / 60000, p.value]);
  };
  const aData = norm(a.value, aHr.value);
  const bData = norm(b.value, bHr.value);
  if (!aData.length && !bData.length) return null;
  return {
    grid: { left: 50, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "value", name: "min", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: "bpm", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      { name: a.value?.name ?? "A", type: "line", data: aData,
        showSymbol: false, smooth: true, sampling: "lttb",
        lineStyle: { color: COLOR_A, width: 1.5 }, itemStyle: { color: COLOR_A } },
      { name: b.value?.name ?? "B", type: "line", data: bData,
        showSymbol: false, smooth: true, sampling: "lttb",
        lineStyle: { color: COLOR_B, width: 1.5 }, itemStyle: { color: COLOR_B } },
    ],
  };
});

onMounted(loadList);
onUnmounted(() => { if (map) { map.remove(); map = null; } });
</script>

<template>
  <div>
    <header class="head">
      <h1>Compare activities</h1>
      <div class="search">
        <input v-model="search" placeholder="Filter by name / type / date…"/>
        <span class="muted">{{ filtered.length }} shown</span>
      </div>
    </header>

    <div class="picker-row">
      <div class="picker">
        <h3 :style="{ color: COLOR_A }">A</h3>
        <select v-model="a">
          <option :value="null">— pick —</option>
          <option v-for="x in filtered" :key="`a-${x.source}-${x.source_id}`" :value="x">
            {{ new Date(x.start_at).toLocaleDateString() }} · {{ x.type }} · {{ x.name ?? '(untitled)' }}
          </option>
        </select>
      </div>
      <div class="picker">
        <h3 :style="{ color: COLOR_B }">B</h3>
        <select v-model="b">
          <option :value="null">— pick —</option>
          <option v-for="x in filtered" :key="`b-${x.source}-${x.source_id}`" :value="x">
            {{ new Date(x.start_at).toLocaleDateString() }} · {{ x.type }} · {{ x.name ?? '(untitled)' }}
          </option>
        </select>
      </div>
    </div>

    <Card title="Stats">
      <table v-if="a || b" class="cmp">
        <thead>
          <tr>
            <th>Metric</th>
            <th :style="{ color: COLOR_A }">
              <ActivityIcon v-if="a" :type="a.type" :size="14"/>
              {{ a?.name ?? a?.type ?? '—' }}
            </th>
            <th :style="{ color: COLOR_B }">
              <ActivityIcon v-if="b" :type="b.type" :size="14"/>
              {{ b?.name ?? b?.type ?? '—' }}
            </th>
            <th>Δ</th>
          </tr>
        </thead>
        <tbody>
          <tr><td class="m">Date</td>
              <td>{{ a ? fmtDateTime(a.start_at) : '—' }}</td>
              <td>{{ b ? fmtDateTime(b.start_at) : '—' }}</td>
              <td>—</td></tr>
          <tr><td class="m">Distance</td>
              <td>{{ fmtDistance(a?.distance_m, 2) }}</td>
              <td>{{ fmtDistance(b?.distance_m, 2) }}</td>
              <td :class="delta(a?.distance_m, b?.distance_m)?.cls">
                {{ delta(a?.distance_m, b?.distance_m) ? `${delta(a?.distance_m, b?.distance_m)!.pct > 0 ? '+' : ''}${delta(a?.distance_m, b?.distance_m)!.pct.toFixed(1)}%` : '—' }}
              </td></tr>
          <tr><td class="m">Duration</td>
              <td>{{ fmtDuration(a?.duration_s) }}</td>
              <td>{{ fmtDuration(b?.duration_s) }}</td>
              <td :class="delta(a?.duration_s, b?.duration_s)?.cls">
                {{ delta(a?.duration_s, b?.duration_s) ? `${delta(a?.duration_s, b?.duration_s)!.pct > 0 ? '+' : ''}${delta(a?.duration_s, b?.duration_s)!.pct.toFixed(1)}%` : '—' }}
              </td></tr>
          <tr><td class="m">{{ isRide(a?.type ?? b?.type ?? '') ? 'Avg speed' : 'Avg pace' }}</td>
              <td>{{ isRide(a?.type ?? '') ? fmtSpeed(a?.distance_m, a?.duration_s) : fmtPace(a?.distance_m, a?.duration_s) }}</td>
              <td>{{ isRide(b?.type ?? '') ? fmtSpeed(b?.distance_m, b?.duration_s) : fmtPace(b?.distance_m, b?.duration_s) }}</td>
              <td>—</td></tr>
          <tr><td class="m">Elevation</td>
              <td>{{ fmtElevation(a?.elevation_gain_m) }}</td>
              <td>{{ fmtElevation(b?.elevation_gain_m) }}</td>
              <td :class="delta(a?.elevation_gain_m, b?.elevation_gain_m)?.cls">
                {{ delta(a?.elevation_gain_m, b?.elevation_gain_m) ? `${delta(a?.elevation_gain_m, b?.elevation_gain_m)!.pct > 0 ? '+' : ''}${delta(a?.elevation_gain_m, b?.elevation_gain_m)!.pct.toFixed(1)}%` : '—' }}
              </td></tr>
          <tr><td class="m">Avg HR</td>
              <td>{{ fmtNum(a?.avg_hr) }}</td>
              <td>{{ fmtNum(b?.avg_hr) }}</td>
              <td :class="delta(a?.avg_hr, b?.avg_hr)?.cls">
                {{ delta(a?.avg_hr, b?.avg_hr) ? `${delta(a?.avg_hr, b?.avg_hr)!.pct > 0 ? '+' : ''}${delta(a?.avg_hr, b?.avg_hr)!.pct.toFixed(1)}%` : '—' }}
              </td></tr>
          <tr><td class="m">Max HR</td>
              <td>{{ fmtNum(a?.max_hr) }}</td>
              <td>{{ fmtNum(b?.max_hr) }}</td>
              <td>—</td></tr>
          <tr><td class="m">Calories</td>
              <td>{{ fmtNum(a?.kcal) }}</td>
              <td>{{ fmtNum(b?.kcal) }}</td>
              <td :class="delta(a?.kcal, b?.kcal)?.cls">
                {{ delta(a?.kcal, b?.kcal) ? `${delta(a?.kcal, b?.kcal)!.pct > 0 ? '+' : ''}${delta(a?.kcal, b?.kcal)!.pct.toFixed(1)}%` : '—' }}
              </td></tr>
          <tr><td class="m">Suffer</td>
              <td>{{ fmtNum(a?.suffer_score) }}</td>
              <td>{{ fmtNum(b?.suffer_score) }}</td>
              <td>—</td></tr>
        </tbody>
      </table>
    </Card>

    <Card title="Routes overlaid" v-if="(a?.polyline || b?.polyline)">
      <div ref="mapEl" class="map"></div>
    </Card>

    <Card title="HR over elapsed time" v-if="hrOption">
      <div class="chart"><VChart :option="hrOption" autoresize/></div>
    </Card>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
h1 { margin: 0; }
.search { display: flex; gap: 0.5rem; align-items: center; }
.search input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.4rem 0.6rem; font-family: inherit; min-width: 240px; }
.search .muted { color: var(--muted); font-size: 0.8rem; }

.picker-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin-bottom: 1rem; }
.picker h3 { margin: 0 0 0.3rem; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
.picker select { width: 100%; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem; font-family: inherit; }

.cmp { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.cmp th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
.cmp td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--surface-2); }
.cmp .m { color: var(--muted); }
.cmp .win-a { color: #38bdf8; font-weight: 500; }
.cmp .win-b { color: #a78bfa; font-weight: 500; }

.map { width: 100%; height: 400px; border-radius: 6px; }
.chart { width: 100%; height: 280px; }
.chart > * { width: 100%; height: 100%; }
</style>
