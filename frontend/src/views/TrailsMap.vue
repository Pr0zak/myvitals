<script setup lang="ts">
/**
 * /trails/map — overview map with every pinned trail as a colored
 * marker (open=green, delayed=amber, closed=red, unknown=slate).
 * Click → popup with name / status / source-time / quick links.
 */
import { onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import "@/leaflet-icons";
import { api } from "@/api/client";
import { effectiveTheme } from "@/theme";
import { ChevronLeft } from "lucide-vue-next";

type Trail = Awaited<ReturnType<typeof api.trails>>["trails"][number];

const router = useRouter();
const mapEl = ref<HTMLDivElement | null>(null);
const loading = ref(true);
const error = ref<string>("");
const trails = ref<Trail[]>([]);
const counts = ref({ open: 0, delayed: 0, closed: 0, other: 0, unpinned: 0 });

let map: L.Map | null = null;
let cluster: L.MarkerClusterGroup | null = null;
let markers: L.CircleMarker[] = [];

const STATUS_COLOR: Record<string, string> = {
  open: "#22c55e",
  delayed: "#eab308",
  closed: "#ef4444",
  unknown: "#94a3b8",
};

function fmtAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - Date.parse(iso);
  if (Number.isNaN(ms) || ms < 0) return "—";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function tileUrl(): string {
  return effectiveTheme.value === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
}

function ensureMap() {
  if (map || !mapEl.value) return;
  map = L.map(mapEl.value, { zoomControl: true });
  L.tileLayer(tileUrl(), {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; CARTO',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);
}

function plot() {
  if (!map) return;
  if (cluster) { cluster.clearLayers(); }
  else {
    cluster = L.markerClusterGroup({
      chunkedLoading: true,
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      // Color each cluster bubble by majority status of children.
      iconCreateFunction: (c) => {
        const counts: Record<string, number> = {};
        for (const m of c.getAllChildMarkers() as any[]) {
          const k = (m.options as any)._mvStatus ?? "unknown";
          counts[k] = (counts[k] ?? 0) + 1;
        }
        const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "unknown";
        const color = STATUS_COLOR[dominant] ?? STATUS_COLOR.unknown;
        const total = c.getChildCount();
        return L.divIcon({
          html: `<div style="background:${color};border:2px solid #fff;border-radius:50%;`
              + `width:34px;height:34px;display:flex;align-items:center;justify-content:center;`
              + `color:#0f172a;font-weight:700;font-size:13px;`
              + `box-shadow:0 2px 6px rgba(0,0,0,0.4);">${total}</div>`,
          className: "mv-cluster", iconSize: [34, 34],
        });
      },
    }).addTo(map);
  }
  markers = [];
  const pinned = trails.value.filter((t) => t.latitude != null && t.longitude != null);
  if (pinned.length === 0) return;

  const bounds = L.latLngBounds([]);
  for (const t of pinned) {
    const color = STATUS_COLOR[t.status ?? "unknown"] ?? STATUS_COLOR.unknown;
    const marker = L.circleMarker([t.latitude!, t.longitude!], {
      radius: 8,
      color: "#0f172a",
      weight: 1.5,
      fillColor: color,
      fillOpacity: 0.9,
      // Tag each marker with its status so the cluster icon-creator
      // can read it via getAllChildMarkers (Leaflet has no native
      // metadata channel for circleMarker options).
      ...({ _mvStatus: t.status ?? "unknown" } as any),
    });
    const ts = t.source_ts ?? t.fetched_at ?? null;
    const popup = `
      <div style="font-family: inherit; min-width: 180px;">
        <div style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(t.name)}</div>
        <div style="color: ${color}; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;">
          ${t.status ?? "unknown"}
        </div>
        <div style="color: #64748b; font-size: 0.78rem; margin-top: 2px;">
          updated ${fmtAge(ts)}
        </div>
        ${t.comment ? `<div style="font-size: 0.85rem; margin-top: 6px;">${escapeHtml(t.comment)}</div>` : ""}
      </div>
    `;
    marker.bindPopup(popup);
    cluster!.addLayer(marker);
    markers.push(marker);
    bounds.extend([t.latitude!, t.longitude!]);
  }
  if (bounds.isValid()) map!.fitBounds(bounds.pad(0.1));
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

onMounted(async () => {
  ensureMap();
  try {
    const r = await api.trails();
    trails.value = r.trails;
    counts.value = {
      open: r.trails.filter((t) => t.status === "open").length,
      delayed: r.trails.filter((t) => t.status === "delayed").length,
      closed: r.trails.filter((t) => t.status === "closed").length,
      other: r.trails.filter((t) => t.status && !["open", "delayed", "closed"].includes(t.status)).length,
      unpinned: r.trails.filter((t) => t.latitude == null).length,
    };
    plot();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
});
</script>

<template>
  <main class="trails-map">
    <header>
      <button class="back" @click="router.push('/trails')">
        <ChevronLeft :size="16" /> Trails
      </button>
      <h1>Trail status map</h1>
      <div class="legend">
        <span><span class="dot" style="background:#22c55e"/> {{ counts.open }} open</span>
        <span v-if="counts.delayed"><span class="dot" style="background:#eab308"/> {{ counts.delayed }} delayed</span>
        <span><span class="dot" style="background:#ef4444"/> {{ counts.closed }} closed</span>
        <span v-if="counts.unpinned" class="muted">{{ counts.unpinned }} unpinned</span>
      </div>
    </header>
    <div v-if="error" class="err">{{ error }}</div>
    <div ref="mapEl" class="map"/>
    <p v-if="loading" class="hint">Loading…</p>
  </main>
</template>

<style scoped>
.trails-map { display: flex; flex-direction: column; height: calc(100vh - 56px); padding: 0 1rem 1rem; }
header { display: flex; align-items: baseline; gap: 1rem; padding: 0.6rem 0; flex-wrap: wrap; }
header h1 { margin: 0; font-size: 1.4rem; }
.back {
  display: inline-flex; align-items: center; gap: 0.2rem;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.3rem 0.6rem; font-size: 0.85rem; cursor: pointer;
}
.legend { display: flex; gap: 0.8rem; color: var(--muted); font-size: 0.85rem; align-items: center; }
.legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 0.3rem; vertical-align: middle; }
.legend .muted { color: var(--muted-2); }
.map { flex: 1; border-radius: 8px; overflow: hidden; min-height: 60vh; }
.hint { color: var(--muted); font-size: 0.85rem; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.4rem 0; }
</style>
