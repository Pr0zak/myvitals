<script setup lang="ts">
/**
 * Per-trail map preview. Renders a Leaflet map with:
 *   - the trail's pin (single marker)
 *   - every linked activity polyline overlaid (your actual rides)
 *
 * Self-contained — pulls /trails/{id}/visits on mount and decodes
 * each visit's polyline. No external map APIs (OSM via CARTO tiles,
 * same as ActivitiesMap.vue).
 */
import { onMounted, onUnmounted, ref, watch } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "@/leaflet-icons";   // side-effect: fixes default marker URLs under Vite
import polylineDecoder from "@mapbox/polyline";
import { api } from "@/api/client";
import { effectiveTheme } from "@/theme";

const props = defineProps<{
  trailId: number;
  name: string;
  latitude: number;
  longitude: number;
}>();

const mapEl = ref<HTMLDivElement | null>(null);
const visits = ref<Awaited<ReturnType<typeof api.trailVisits>>["visits"]>([]);
const loading = ref(true);
const error = ref<string>("");

let map: L.Map | null = null;
let tileLayer: L.TileLayer | null = null;
const overlays: L.Layer[] = [];

const TYPE_COLORS: Record<string, string> = {
  ride: "#ef4444", mountain_biking: "#ef4444", cycling: "#ef4444",
  run: "#22c55e", trailrun: "#84cc16", running: "#22c55e",
  hike: "#f59e0b", walk: "#f59e0b", walking: "#f59e0b",
};
function colorFor(type: string): string {
  return TYPE_COLORS[type?.toLowerCase()] ?? "#a78bfa";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const r = await api.trailVisits(props.trailId, 730);
    visits.value = r.visits;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    visits.value = [];
  } finally {
    loading.value = false;
  }
}

function render() {
  if (!mapEl.value) return;
  if (!map) {
    map = L.map(mapEl.value, { zoomControl: true, scrollWheelZoom: false });
  }
  if (tileLayer) { map.removeLayer(tileLayer); }
  const tiles = effectiveTheme.value === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
  tileLayer = L.tileLayer(tiles, {
    attribution: "© OpenStreetMap, © CARTO",
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  // Clear previous overlays
  for (const o of overlays) map.removeLayer(o);
  overlays.length = 0;

  // Pin
  const pin = L.marker([props.latitude, props.longitude], {
    title: props.name,
  }).addTo(map);
  overlays.push(pin);

  // Center on the pin; polylines load asynchronously after via
  // loadAndRenderPolylines() and adjust the bounds.
  map.setView([props.latitude, props.longitude], 14);
}

async function loadAndRenderPolylines() {
  // Fetch each visit's full activity to get the polyline.
  const polys: Array<{ coords: L.LatLngTuple[]; type: string; name: string; date: string }> = [];
  for (const v of visits.value) {
    try {
      const a = await api.activity(v.source, v.source_id);
      if (!a.polyline) continue;
      const decoded = polylineDecoder.decode(a.polyline) as L.LatLngTuple[];
      if (decoded.length < 2) continue;
      polys.push({ coords: decoded, type: a.type, name: a.name ?? a.type,
                   date: v.start_at });
    } catch { /* ignore individual fetch errors */ }
  }
  if (!map) return;
  const allPoints: L.LatLngTuple[] = [[props.latitude, props.longitude]];

  // Cached OSM official paths first, drawn underneath
  try {
    const osm = await api.getTrailOsmPaths(props.trailId);
    for (const f of osm.geojson.features) {
      // GeoJSON is [lon, lat]; Leaflet wants [lat, lon]
      const coords = (f.geometry.coordinates as [number, number][])
        .map(([lon, lat]) => [lat, lon] as L.LatLngTuple);
      if (coords.length < 2) continue;
      const ln = L.polyline(coords, {
        color: "#94a3b8", weight: 2, opacity: 0.55, dashArray: "4 4",
      }).bindTooltip(
        `<b>${(f.properties.name as string) || "OSM trail"}</b><br/>${(f.properties.highway as string) ?? ""}`,
        { sticky: true },
      );
      ln.addTo(map);
      overlays.push(ln);
      coords.forEach((c) => allPoints.push(c));
    }
  } catch { /* no cached OSM paths yet — silent */ }

  for (const p of polys) {
    const ln = L.polyline(p.coords, {
      color: colorFor(p.type), weight: 3, opacity: 0.85,
    }).bindTooltip(
      `<b>${p.name}</b><br/>${new Date(p.date).toLocaleDateString()}`,
      { sticky: true },
    );
    ln.addTo(map);
    overlays.push(ln);
    p.coords.forEach((c) => allPoints.push(c));
  }
  if (allPoints.length > 1) {
    map.fitBounds(L.latLngBounds(allPoints), { padding: [40, 40], maxZoom: 16 });
  }
}

onMounted(async () => {
  await load();
  setTimeout(() => { render(); loadAndRenderPolylines(); }, 50);
});
onUnmounted(() => {
  if (map) { map.remove(); map = null; }
  overlays.length = 0;
});
watch(effectiveTheme, () => setTimeout(render, 50));
</script>

<template>
  <div class="trail-map-wrap">
    <div ref="mapEl" class="trail-map" />
    <p v-if="loading" class="hint">Loading visits…</p>
    <p v-else-if="error" class="err">{{ error }}</p>
    <p v-else-if="visits.length === 0" class="hint">
      No linked rides yet — Strava activities within 2 km of the pin auto-link
      via the "Link activities" button on the Trails page.
    </p>
    <p v-else class="hint">
      <strong>{{ visits.length }}</strong> linked ride{{ visits.length === 1 ? '' : 's' }} on this trail
    </p>
  </div>
</template>

<style scoped>
.trail-map-wrap { margin-top: 0.5rem; }
.trail-map {
  height: 240px; border-radius: 8px; overflow: hidden;
  border: 1px solid var(--line);
}
.hint { color: var(--muted); font-size: 0.78rem; margin: 0.4rem 0 0; }
.err { color: #f87171; font-size: 0.78rem; margin: 0.4rem 0 0; }
</style>
