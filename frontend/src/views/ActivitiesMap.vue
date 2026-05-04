<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import polylineDecoder from "@mapbox/polyline";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { api } from "@/api/client";
import type { Activity } from "@/api/types";
import { effectiveTheme } from "@/theme";

const TYPE_COLOR: Record<string, string> = {
  ebikeride: "#22c55e", ride: "#22c55e", virtualride: "#22c55e",
  run: "#ef4444", trailrun: "#ef4444",
  walk: "#a78bfa", hike: "#a78bfa", hiking: "#a78bfa",
  swim: "#38bdf8", swimming_pool: "#38bdf8", swimming_open_water: "#38bdf8",
};
function colorFor(t: string) { return TYPE_COLOR[t.toLowerCase()] ?? "#94a3b8"; }

const activities = ref<Activity[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const yearOffset = ref(0);
const stats = ref({ count: 0, totalDistance: 0 });

const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let tileLayer: L.TileLayer | null = null;
const lines: L.Polyline[] = [];

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date();
    since.setFullYear(since.getFullYear() - 1 + yearOffset.value);
    const until = new Date();
    until.setFullYear(until.getFullYear() + yearOffset.value);
    activities.value = await api.activities({ since, until, limit: 500 });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function renderMap() {
  if (!mapEl.value) return;
  if (!map) {
    map = L.map(mapEl.value, { zoomControl: true });
  }

  // Tile layer (theme-reactive)
  if (tileLayer) { map.removeLayer(tileLayer); }
  const tiles = effectiveTheme.value === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
  tileLayer = L.tileLayer(tiles, {
    attribution: "© OpenStreetMap, © CARTO",
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  // Clear old polylines
  for (const ln of lines) map.removeLayer(ln);
  lines.length = 0;

  // Add a polyline for every activity that has one
  let withPoly = 0;
  let totalDist = 0;
  const allBounds: L.LatLng[] = [];
  for (const a of activities.value) {
    if (!a.polyline) continue;
    let coords: [number, number][];
    try { coords = polylineDecoder.decode(a.polyline) as [number, number][]; }
    catch { continue; }
    if (coords.length < 2) continue;
    withPoly++;
    totalDist += a.distance_m ?? 0;
    const ln = L.polyline(coords, {
      color: colorFor(a.type),
      weight: 2.5,
      opacity: 0.7,
    }).bindTooltip(
      `<b>${a.name ?? a.type}</b><br/>${new Date(a.start_at).toLocaleDateString()}<br/>${((a.distance_m ?? 0) / 1000).toFixed(1)} km`,
      { sticky: true },
    );
    ln.on("mouseover", () => { ln.setStyle({ weight: 5, opacity: 1 }); });
    ln.on("mouseout", () => { ln.setStyle({ weight: 2.5, opacity: 0.7 }); });
    ln.on("click", () => {
      window.location.href = `/activity/${a.source}/${a.source_id}`;
    });
    ln.addTo(map);
    lines.push(ln);
    coords.forEach((c) => allBounds.push(L.latLng(c[0], c[1])));
  }

  stats.value = { count: withPoly, totalDistance: totalDist };
  if (allBounds.length > 0) map.fitBounds(L.latLngBounds(allBounds), { padding: [30, 30] });
}

onMounted(() => {
  load().then(() => setTimeout(renderMap, 50));
});
watch(activities, () => setTimeout(renderMap, 50));
watch(effectiveTheme, () => setTimeout(renderMap, 50));
watch(yearOffset, load);

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
});

const yearLabel = () => {
  const today = new Date();
  if (yearOffset.value === 0) return "Last 12 months";
  return `${today.getFullYear() + yearOffset.value}`;
};
</script>

<template>
  <div>
    <header class="head">
      <h1>Map view</h1>
      <div class="ctrls">
        <button @click="yearOffset--">‹</button>
        <span>{{ yearLabel() }}</span>
        <button :disabled="yearOffset >= 0" @click="yearOffset++">›</button>
        <span class="stat">
          {{ stats.count }} routes · {{ (stats.totalDistance / 1000).toFixed(0) }} km
        </span>
      </div>
    </header>
    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div ref="mapEl" class="map"></div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
h1 { margin: 0; }
.ctrls { display: flex; gap: 0.6rem; align-items: center; color: var(--muted); }
.ctrls button {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; padding: 0.3rem 0.7rem;
}
.ctrls button:disabled { opacity: 0.4; cursor: not-allowed; }
.ctrls span { font-weight: 500; min-width: 100px; text-align: center; }
.ctrls .stat { font-weight: 400; font-size: 0.85rem; color: var(--muted); min-width: 0; margin-left: 1rem; }
.map { height: calc(100vh - 200px); width: 100%; border-radius: 8px; }
.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
