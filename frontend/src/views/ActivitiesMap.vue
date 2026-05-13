<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import polylineDecoder from "@mapbox/polyline";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { api } from "@/api/client";
import type { Activity } from "@/api/types";
import { effectiveTheme } from "@/theme";
import { fmtDistance, distanceVal, distanceUnit } from "@/units";

const TYPE_COLOR: Record<string, string> = {
  ebikeride: "#22c55e", ride: "#22c55e", virtualride: "#22c55e",
  run: "#ef4444", trailrun: "#ef4444",
  walk: "#a78bfa", hike: "#a78bfa", hiking: "#a78bfa",
  swim: "#38bdf8", swimming_pool: "#38bdf8", swimming_open_water: "#38bdf8",
};
function colorFor(t: string) { return TYPE_COLOR[t.toLowerCase()] ?? "#94a3b8"; }

const activities = ref<Activity[]>([]);
const trails = ref<Awaited<ReturnType<typeof api.trails>>["trails"]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
// "all" = entire history (default). yearOffset is only consulted when
// timeRange === "year"; left for back-compat with the year arrows.
const timeRange = ref<"all" | "year">("all");
const yearOffset = ref(0);
const stats = ref({ count: 0, totalDistance: 0 });
const homeLat = ref<number | null>(null);
const homeLng = ref<number | null>(null);
// Suppresses fit-bounds on the first render so the All-time view stays
// centered on home; year navigation re-enables it.
let initialAllTimeRender = true;

const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let tileLayer: L.TileLayer | null = null;
const lines: L.Polyline[] = [];

// View mode: "lines" colors by activity type; "heatmap" stacks low-opacity
// polylines in a single warm tone so overlapping routes glow brighter.
const viewMode = ref<"lines" | "heatmap">("lines");

// Trail layer state
const trailMarkers = new Map<number, L.CircleMarker>();
const trailOsmLayers = new Map<number, L.GeoJSON>();
const hiddenTrailPins = ref<Set<number>>(new Set());
const trailFullMapOpen = ref<Set<number>>(new Set());  // ids with OSM paths shown
const loadingOsmFor = ref<Set<number>>(new Set());
const trailsPanelOpen = ref(false);

const TRAIL_STATUS_COLOR: Record<string, string> = {
  open: "#22c55e", closed: "#ef4444", delayed: "#f59e0b", unknown: "#94a3b8",
};

async function load() {
  loading.value = true;
  error.value = null;
  try {
    let since: Date;
    let untilMs: number;
    if (timeRange.value === "all") {
      since = new Date(2000, 0, 1);
      untilMs = Date.now();
    } else {
      since = new Date();
      since.setFullYear(since.getFullYear() - 1 + yearOffset.value);
      const until = new Date();
      until.setFullYear(until.getFullYear() + yearOffset.value);
      untilMs = until.getTime();
    }
    const [all, tr, prof] = await Promise.all([
      api.activities({ since, limit: 2000 }),
      api.trails().catch(() => ({ trails: [] as any[] })),
      api.getProfile().catch(() => null),
    ]);
    activities.value = all.filter((a) => new Date(a.start_at).getTime() <= untilMs);
    trails.value = (tr as any).trails ?? [];
    if (prof) {
      homeLat.value = prof.home_latitude;
      homeLng.value = prof.home_longitude;
    }
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

  const heat = viewMode.value === "heatmap";
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
    const ln = L.polyline(coords, heat ? {
      color: "#fb923c",
      weight: 4,
      opacity: 0.18,
      lineCap: "round",
    } : {
      color: colorFor(a.type),
      weight: 2.5,
      opacity: 0.7,
    });
    if (!heat) {
      ln.bindTooltip(
        `<b>${a.name ?? a.type}</b><br/>${new Date(a.start_at).toLocaleDateString()}<br/>${fmtDistance(a.distance_m ?? 0, 1)}`,
        { sticky: true },
      );
      ln.on("mouseover", () => { ln.setStyle({ weight: 5, opacity: 1 }); });
      ln.on("mouseout", () => { ln.setStyle({ weight: 2.5, opacity: 0.7 }); });
      ln.on("click", () => {
        window.location.href = `/activity/${a.source}/${a.source_id}`;
      });
    }
    ln.addTo(map);
    lines.push(ln);
    coords.forEach((c) => allBounds.push(L.latLng(c[0], c[1])));
  }

  stats.value = { count: withPoly, totalDistance: totalDist };

  // Centering rule:
  //   - All-time + home set → center on home at zoom 12 (don't fit-to-all).
  //   - All-time + no home → centroid of all polylines.
  //   - Year navigation → always fit-to-bounds for the focused window.
  if (timeRange.value === "all" && initialAllTimeRender) {
    initialAllTimeRender = false;
    if (homeLat.value != null && homeLng.value != null) {
      map.setView([homeLat.value, homeLng.value], 12);
    } else if (allBounds.length > 0) {
      const c = L.latLngBounds(allBounds).getCenter();
      map.setView([c.lat, c.lng], 12);
    }
  } else if (timeRange.value === "year" && allBounds.length > 0) {
    map.fitBounds(L.latLngBounds(allBounds), { padding: [30, 30] });
  }

  applyTrailLayer();
}

function applyTrailLayer() {
  if (!map) return;
  // Clear old pins
  for (const m of trailMarkers.values()) m.remove();
  trailMarkers.clear();
  for (const t of trails.value) {
    if (t.latitude == null || t.longitude == null) continue;
    if (hiddenTrailPins.value.has(t.id)) continue;
    const color = TRAIL_STATUS_COLOR[t.status ?? "unknown"];
    const marker = L.circleMarker([t.latitude, t.longitude], {
      radius: 7, color, weight: 2, fillColor: color, fillOpacity: 0.7,
    }).addTo(map);
    marker.bindTooltip(
      `<strong>${t.name}</strong><br/>${t.status ?? "unknown"}` +
      (t.city ? `<br/><span style="color:#94a3b8">${t.city}${t.state ? ", " + t.state : ""}</span>` : "") +
      (t.visits_total ? `<br/><span style="color:#94a3b8">${t.visits_total} visit${t.visits_total === 1 ? "" : "s"}</span>` : ""),
      { direction: "top" },
    );
    trailMarkers.set(t.id, marker);
  }
}

async function toggleTrailFullMap(id: number) {
  if (!map) return;
  const open = trailFullMapOpen.value;
  if (open.has(id)) {
    // Hide it
    trailOsmLayers.get(id)?.remove();
    trailOsmLayers.delete(id);
    const next = new Set(open); next.delete(id); trailFullMapOpen.value = next;
    return;
  }
  if (trailOsmLayers.has(id)) {
    trailOsmLayers.get(id)!.addTo(map);
    const next = new Set(open); next.add(id); trailFullMapOpen.value = next;
    return;
  }
  // Load
  loadingOsmFor.value = new Set([...loadingOsmFor.value, id]);
  try {
    const r = await api.getTrailOsmPaths(id);
    if (!r.geojson) {
      // No cached paths yet — try to fetch them
      try { await api.fetchTrailOsmPaths(id); }
      catch { /* swallow — leave layer empty */ }
      const r2 = await api.getTrailOsmPaths(id);
      if (!r2.geojson) return;
      addTrailOsmLayer(id, r2.geojson);
    } else {
      addTrailOsmLayer(id, r.geojson);
    }
    const next = new Set(open); next.add(id); trailFullMapOpen.value = next;
  } catch (e) {
    error.value = `Trail map load failed: ${e instanceof Error ? e.message : e}`;
  } finally {
    const ls = new Set(loadingOsmFor.value); ls.delete(id); loadingOsmFor.value = ls;
  }
}

function addTrailOsmLayer(id: number, geojson: any) {
  if (!map) return;
  const t = trails.value.find((x) => x.id === id);
  const color = TRAIL_STATUS_COLOR[t?.status ?? "unknown"];
  const layer = L.geoJSON(geojson, {
    style: { color, weight: 3, opacity: 0.85 },
  }).addTo(map);
  trailOsmLayers.set(id, layer);
}

function toggleTrailPin(id: number) {
  const s = new Set(hiddenTrailPins.value);
  if (s.has(id)) s.delete(id); else s.add(id);
  hiddenTrailPins.value = s;
  applyTrailLayer();
}

function panToTrail(id: number) {
  const t = trails.value.find((x) => x.id === id);
  if (!t || !map || t.latitude == null || t.longitude == null) return;
  map.setView([t.latitude, t.longitude], 13);
}

const visibleTrails = computed(() => {
  return trails.value
    .filter((t) => t.latitude != null && t.longitude != null)
    .sort((a, b) => (b.visits_total ?? 0) - (a.visits_total ?? 0) || a.name.localeCompare(b.name));
});

onMounted(() => {
  load().then(() => setTimeout(renderMap, 50));
});
watch(activities, () => setTimeout(renderMap, 50));
watch(effectiveTheme, () => setTimeout(renderMap, 50));
watch(yearOffset, load);
watch(viewMode, () => setTimeout(renderMap, 50));
watch(trails, () => applyTrailLayer());
watch(hiddenTrailPins, () => applyTrailLayer(), { deep: true });

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
});

const yearLabel = () => {
  if (timeRange.value === "all") return "All time";
  const today = new Date();
  if (yearOffset.value === 0) return "Last 12 months";
  return `${today.getFullYear() + yearOffset.value}`;
};

function stepYear(delta: number) {
  // First click on the year arrows from All-time mode switches to year
  // navigation; subsequent clicks step yearOffset. Re-enables fit-bounds
  // so the focused year fills the viewport.
  if (timeRange.value === "all") {
    timeRange.value = "year";
    yearOffset.value = 0;
  }
  yearOffset.value += delta;
  initialAllTimeRender = false;
}

function backToAllTime() {
  timeRange.value = "all";
  yearOffset.value = 0;
  initialAllTimeRender = true;
}

watch(timeRange, load);
</script>

<template>
  <div>
    <header class="head">
      <h1>Map view</h1>
      <div class="ctrls">
        <button v-if="timeRange === 'year'" @click="backToAllTime" title="Back to All time">All</button>
        <button @click="stepYear(-1)">‹</button>
        <span>{{ yearLabel() }}</span>
        <button :disabled="timeRange === 'year' && yearOffset >= 0" @click="stepYear(1)">›</button>
        <span class="stat">
          {{ stats.count }} routes · {{ distanceVal(stats.totalDistance)?.toFixed(0) }} {{ distanceUnit }}
        </span>
      </div>
    </header>
    <div class="map-toolbar">
      <button class="toggle" :class="{ on: viewMode === 'lines' }"
              @click="viewMode = 'lines'">Lines (by type)</button>
      <button class="toggle" :class="{ on: viewMode === 'heatmap' }"
              @click="viewMode = 'heatmap'"
              title="Stack low-opacity polylines so high-traffic routes glow">
        Ride heatmap
      </button>
      <button v-if="visibleTrails.length"
              class="toggle"
              :class="{ on: trailsPanelOpen }"
              @click="trailsPanelOpen = !trailsPanelOpen"
              :title="`${visibleTrails.length} trail(s) in your library`">
        Trails ({{ visibleTrails.length }})
      </button>
    </div>
    <div v-if="trailsPanelOpen && visibleTrails.length" class="trails-panel">
      <p class="hint">Click a trail name to pan. Tick to hide the pin.
        ‘Map’ overlays the trail's full path network (loads from OSM the first time).</p>
      <ul>
        <li v-for="t in visibleTrails" :key="t.id">
          <input type="checkbox"
                 :checked="!hiddenTrailPins.has(t.id)"
                 @change="toggleTrailPin(t.id)"/>
          <span class="status-dot"
                :style="`background:${ {open:'#22c55e',closed:'#ef4444',delayed:'#f59e0b',unknown:'#94a3b8'}[t.status ?? 'unknown'] }`"
                :title="t.status ?? 'unknown'"/>
          <button class="t-name" @click="panToTrail(t.id)">{{ t.name }}</button>
          <span class="t-meta">
            {{ t.status ?? 'unknown' }}{{ t.city ? ' · ' + t.city : '' }}
            <span v-if="t.visits_total"> · {{ t.visits_total }} visit{{ t.visits_total === 1 ? '' : 's' }}</span>
          </span>
          <button class="t-map" :class="{ on: trailFullMapOpen.has(t.id) }"
                  :disabled="loadingOsmFor.has(t.id)"
                  @click="toggleTrailFullMap(t.id)">
            {{ loadingOsmFor.has(t.id) ? '…' : (trailFullMapOpen.has(t.id) ? 'Hide map' : 'Map') }}
          </button>
        </li>
      </ul>
    </div>
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
.map-toolbar {
  display: flex; gap: 6px; align-items: center;
  margin-bottom: 0.5rem; flex-wrap: wrap;
}
.toggle {
  font-size: 0.75rem; padding: 4px 12px; border-radius: 999px;
  background: var(--surface); color: var(--muted);
  border: 1px solid var(--border); cursor: pointer;
}
.toggle.on {
  background: var(--accent, #a78bfa); color: white; border-color: var(--accent, #a78bfa);
}
.trails-panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.5rem 0.8rem; margin-bottom: 0.6rem;
  max-height: 240px; overflow-y: auto;
}
.trails-panel .hint { font-size: 0.7rem; color: var(--muted); margin: 0 0 6px 0; }
.trails-panel ul { list-style: none; margin: 0; padding: 0; }
.trails-panel li {
  display: flex; align-items: center; gap: 8px;
  padding: 3px 0; font-size: 0.82rem;
}
.status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
.t-name {
  background: none; border: none; padding: 0;
  color: var(--accent, #a78bfa); cursor: pointer;
  text-align: left; font-size: 0.82rem; flex: 0 1 auto;
}
.t-name:hover { text-decoration: underline; }
.t-meta {
  font-size: 0.7rem; color: var(--muted); flex: 1 1 auto;
}
.t-map {
  font-size: 0.7rem; padding: 2px 10px; border-radius: 999px;
  background: transparent; color: var(--muted);
  border: 1px solid var(--border); cursor: pointer;
}
.t-map.on { background: var(--accent, #a78bfa); color: white; border-color: var(--accent, #a78bfa); }
.t-map:disabled { opacity: 0.5; cursor: wait; }
.map { height: calc(100vh - 280px); width: 100%; border-radius: 8px; }
.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
