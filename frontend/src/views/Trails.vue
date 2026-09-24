<script setup lang="ts">
/**
 * /trails — RainoutLine status board for the user's local trail
 * network. Phone twin: `TrailsScreen.kt`.
 *
 * UI-5: the page leads with a status hero — "11 of 14 open" with the open
 * count big in lime, a segmented bar (open lime / delayed amber / closed
 * rose — rose here is the trail's literal status, not an alarm), a
 * "synced 4m" pill and a non-interactive mini map of status pins that opens
 * the full map. The counts are the server's `status_counts`. Starred
 * trails sit in a carousel with how long since you rode each. A failed
 * refresh is an amber banner ABOVE the cached trails; it used to replace
 * them.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import { baseTileUrl, labelTileUrl, tileOptions } from "@/mapTiles";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "@/leaflet-icons";   // side-effect: fixes default marker URLs under Vite
import { Star, RefreshCw, Pencil, Map as MapIcon, MapPin, Route, Bike, ChevronRight, Rows3, Rows2 } from "lucide-vue-next";
import { api, trailsWithSummary } from "@/api/client";
import type { TrailStatusCounts } from "@/api/types";
import { queryToken } from "@/config";
import Skeleton from "@/components/Skeleton.vue";
import TrailMap from "@/components/TrailMap.vue";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import { useRouter } from "vue-router";

/** Condensed rows: name + age only, tighter padding, no comment or meta.
 *  Fits roughly three times as many trails on screen, which matters with
 *  two dozen open trails and a status you scan rather than read.
 *  Persisted — a density preference you have to re-set every visit is
 *  worse than not offering one. */
const DENSE_KEY = "myvitals.trails.dense";
const dense = ref(localStorage.getItem(DENSE_KEY) === "1");
function toggleDense() {
  dense.value = !dense.value;
  localStorage.setItem(DENSE_KEY, dense.value ? "1" : "0");
}

type Trail = Awaited<ReturnType<typeof api.trails>>["trails"][number];

const trails = ref<Trail[]>([]);
const dnisUrl = ref<string | null>(null);
const counts = ref<TrailStatusCounts | null>(null);
const syncedAt = ref<string | null>(null);
const router = useRouter();
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string>("");
const tickNow = ref(Date.now());
let tickHandle: number | null = null;

// Trails whose status flipped since the previous load. Cleared 2.5s
// after detection so the CSS animation has time to play.
const flipped = ref<Set<number>>(new Set());

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = trails.value.length === 0;
  error.value = "";
  try {
    const r = await trailsWithSummary();
    // Detect status flips before swapping refs.
    const prevStatus = new Map(trails.value.map((t) => [t.id, t.status]));
    const newlyFlipped: number[] = [];
    for (const t of r.trails) {
      const prev = prevStatus.get(t.id);
      if (prev !== undefined && prev !== t.status) {
        newlyFlipped.push(t.id);
      }
    }
    trails.value = r.trails;
    dnisUrl.value = r.dnis_url ?? null;
    counts.value = r.status_counts ?? null;
    syncedAt.value = r.synced_at ?? null;
    if (newlyFlipped.length > 0) {
      const next = new Set(flipped.value);
      newlyFlipped.forEach((id) => next.add(id));
      flipped.value = next;
      window.setTimeout(() => {
        const cleared = new Set(flipped.value);
        newlyFlipped.forEach((id) => cleared.delete(id));
        flipped.value = cleared;
      }, 2500);
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  refreshing.value = true;
  try {
    await api.refreshTrails();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    refreshing.value = false;
  }
}

const linking = ref(false);
const linkResult = ref<string>("");
async function linkActivities() {
  linking.value = true;
  linkResult.value = "";
  try {
    const r = await api.linkActivitiesToTrails(2.0, false);
    linkResult.value = `Linked ${r.linked} new · ${r.already_linked_skipped} already · ${r.no_match_within_km} no match · ${r.no_gps} no GPS`;
    await load();
  } catch (e) {
    linkResult.value = e instanceof Error ? e.message : String(e);
  } finally {
    linking.value = false;
  }
}

const fetchingOsm = ref(false);
async function fetchAllOsm() {
  if (!confirm("Pull official trail geometry from OpenStreetMap for every pinned trail? Takes ~1s per trail (32 trails ≈ 40s).")) return;
  fetchingOsm.value = true;
  linkResult.value = "";
  try {
    const r = await api.fetchAllTrailOsmPaths(500, false);
    linkResult.value = `OSM paths: ${r.fetched} fetched · ${r.skipped} cached · ${r.failed} failed`;
  } catch (e) {
    linkResult.value = e instanceof Error ? e.message : String(e);
  } finally {
    fetchingOsm.value = false;
  }
}

async function toggleSubscribe(t: Trail) {
  try {
    if (t.subscribed) {
      await api.unsubscribeTrail(t.id);
    } else {
      await api.subscribeTrail(t.id, "any");
    }
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

function openMaps(t: Trail) {
  if (t.latitude == null || t.longitude == null) return;
  const q = encodeURIComponent(`${t.latitude},${t.longitude} (${t.name})`);
  window.open(`https://www.google.com/maps/search/?api=1&query=${q}`, "_blank", "noreferrer");
}

// Edit location modal state
const editTrail = ref<Trail | null>(null);
const editLat = ref<string>("");
const editLon = ref<string>("");
const editCity = ref<string>("");
const editState = ref<string>("");
const editSaving = ref(false);
const editError = ref<string>("");

// Inline Leaflet map state
const editMapEl = ref<HTMLDivElement | null>(null);
let editMap: L.Map | null = null;
let editPin: L.Marker | null = null;

function openEdit(t: Trail) {
  editTrail.value = t;
  editLat.value = t.latitude?.toString() ?? "";
  editLon.value = t.longitude?.toString() ?? "";
  editCity.value = t.city ?? "";
  editState.value = t.state ?? "";
  editError.value = "";
  nextTick(() => initEditMap(t));
}

function closeEdit() {
  if (editMap) { editMap.remove(); editMap = null; editPin = null; }
  editTrail.value = null;
}

const KC_CENTER: [number, number] = [39.0997, -94.5786];
function initEditMap(t: Trail) {
  if (!editMapEl.value) return;
  if (editMap) editMap.remove();
  const start: [number, number] = (t.latitude != null && t.longitude != null)
    ? [t.latitude, t.longitude]
    : KC_CENTER;
  editMap = L.map(editMapEl.value, { zoomControl: true })
    .setView(start, t.latitude != null ? 14 : 9);
  const dark = true;
  L.tileLayer(baseTileUrl(dark), tileOptions()).addTo(editMap);
  L.tileLayer(labelTileUrl(dark), { ...tileOptions(), pane: "shadowPane" }).addTo(editMap);

  if (t.latitude != null && t.longitude != null) {
    editPin = L.marker(start, { draggable: true }).addTo(editMap);
    editPin.on("dragend", () => {
      if (!editPin) return;
      const ll = editPin.getLatLng();
      editLat.value = ll.lat.toFixed(6);
      editLon.value = ll.lng.toFixed(6);
    });
  }

  editMap.on("click", (e: L.LeafletMouseEvent) => {
    const { lat, lng } = e.latlng;
    if (editPin) {
      editPin.setLatLng([lat, lng]);
    } else {
      editPin = L.marker([lat, lng], { draggable: true }).addTo(editMap!);
      editPin.on("dragend", () => {
        if (!editPin) return;
        const ll = editPin.getLatLng();
        editLat.value = ll.lat.toFixed(6);
        editLon.value = ll.lng.toFixed(6);
      });
    }
    editLat.value = lat.toFixed(6);
    editLon.value = lng.toFixed(6);
  });
}

// Sync map → inputs (rare; mostly the other way) when user types coords manually
watch([editLat, editLon], ([la, lo]) => {
  if (!editMap) return;
  const lat = parseFloat(la), lon = parseFloat(lo);
  if (Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90) {
    if (editPin) editPin.setLatLng([lat, lon]);
    else editPin = L.marker([lat, lon], { draggable: true }).addTo(editMap);
  }
});

function useMyLocation() {
  if (!navigator.geolocation) {
    editError.value = "Geolocation not supported in this browser";
    return;
  }
  editError.value = "Locating…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      editLat.value = pos.coords.latitude.toFixed(6);
      editLon.value = pos.coords.longitude.toFixed(6);
      editError.value = "";
    },
    (err) => { editError.value = `Location failed: ${err.message}`; },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 60_000 },
  );
}

function openInMaps() {
  const t = editTrail.value;
  if (!t) return;
  // Pre-zoom to the existing pin if known, else search by trail name.
  const url = (t.latitude != null && t.longitude != null)
    ? `https://www.google.com/maps/@${t.latitude},${t.longitude},15z`
    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(t.name)}`;
  window.open(url, "_blank", "noreferrer");
}

// Place-name / Google-Maps-link search.
// Accepts any of:
//   - Google Maps place URL: ".../maps/place/X/@LAT,LON,17z/..."
//   - Google Maps embed iframe URL: "...maps/embed?pb=!...!2dLON!3dLAT..."
//   - Google Maps search URL: ".../maps/search/?api=1&query=LAT,LON"
//   - Plain "lat, lon" pasted text
//   - Short link "https://maps.app.goo.gl/XXXX" (resolves via fetch follow)
//   - Anything else → falls through to Nominatim free-text geocode
const placeQuery = ref<string>("");
const searching = ref(false);

// Pull lat/lon out of common Google Maps URL formats.
function parseMapsCoords(input: string): { lat: number; lon: number } | null {
  // 1. The @LAT,LON,zoom anchor in place / search URLs
  const at = input.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (at) return { lat: parseFloat(at[1]), lon: parseFloat(at[2]) };
  // 2. Embed iframe pb-param: ...!2dLON!3dLAT
  const embed = input.match(/!2d(-?\d+\.\d+)!3d(-?\d+\.\d+)/);
  if (embed) return { lat: parseFloat(embed[2]), lon: parseFloat(embed[1]) };
  // 3. Query-style: ?q=LAT,LON / ?query=LAT,LON / ?destination=LAT,LON
  const q = input.match(/[?&](?:q|query|destination|center)=(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (q) return { lat: parseFloat(q[1]), lon: parseFloat(q[2]) };
  // 4. Plain "LAT, LON" or "LAT,LON"
  const plain = input.trim().match(/^(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)$/);
  if (plain) return { lat: parseFloat(plain[1]), lon: parseFloat(plain[2]) };
  return null;
}

async function expandShortLink(short: string): Promise<string | null> {
  // maps.app.goo.gl 302s but Google strips Access-Control-Allow-Origin,
  // so a client-side fetch can't read the redirect target. Round-trip
  // through the backend, which follows the redirect server-side.
  try {
    const { resolved_url } = await api.resolveTrailLink(short);
    return resolved_url || null;
  } catch {
    return null;
  }
}

async function searchPlace() {
  const raw = placeQuery.value.trim();
  if (!raw) return;
  searching.value = true;
  editError.value = "";
  try {
    let q = raw;
    // Resolve maps.app.goo.gl short links first (no CORS on the goo.gl host
    // for HEAD, but try anyway — many will fail and the user will be told).
    if (q.includes("maps.app.goo.gl")) {
      const expanded = await expandShortLink(q);
      if (expanded) q = expanded;
    }
    // Try parsing as a Maps URL first
    const parsed = parseMapsCoords(q);
    if (parsed) {
      editLat.value = parsed.lat.toFixed(6);
      editLon.value = parsed.lon.toFixed(6);
      if (editMap) editMap.setView([parsed.lat, parsed.lon], 16);
      return;
    }
    // Fall through to Nominatim for free-text place names
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(raw)}`,
      { headers: { Accept: "application/json" } },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json() as Array<{ lat: string; lon: string; display_name: string }>;
    if (data.length === 0) {
      editError.value = `No results for "${raw}". If you pasted a maps.app.goo.gl short link, open it once to expand.`;
      return;
    }
    const lat = parseFloat(data[0].lat);
    const lon = parseFloat(data[0].lon);
    editLat.value = lat.toFixed(6);
    editLon.value = lon.toFixed(6);
    if (editMap) editMap.setView([lat, lon], 15);
  } catch (e) {
    editError.value = `Search failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    searching.value = false;
  }
}

async function saveEdit() {
  if (!editTrail.value) return;
  const lat = parseFloat(editLat.value);
  const lon = parseFloat(editLon.value);
  if (editLat.value && (Number.isNaN(lat) || lat < -90 || lat > 90)) {
    editError.value = "Latitude must be between -90 and 90";
    return;
  }
  if (editLon.value && (Number.isNaN(lon) || lon < -180 || lon > 180)) {
    editError.value = "Longitude must be between -180 and 180";
    return;
  }
  editSaving.value = true;
  try {
    await api.editTrailLocation(editTrail.value.id, {
      latitude: editLat.value ? lat : null,
      longitude: editLon.value ? lon : null,
      city: editCity.value || null,
      state: editState.value || null,
    });
    await load();
    closeEdit();
  } catch (e) {
    editError.value = e instanceof Error ? e.message : String(e);
  } finally {
    editSaving.value = false;
  }
}

// Inline map expand state — set of trail IDs currently showing their map
const expandedMaps = ref<Set<number>>(new Set());
function toggleMap(t: Trail) {
  const next = new Set(expandedMaps.value);
  if (next.has(t.id)) next.delete(t.id);
  else next.add(t.id);
  expandedMaps.value = next;
}

// Fullscreen map modal
const fullMapTrail = ref<Trail | null>(null);
function openFullMap(t: Trail) { fullMapTrail.value = t; }
function closeFullMap() { fullMapTrail.value = null; }

function visitAgeClass(iso: string | null | undefined): string {
  if (!iso) return "age-old";
  const days = (Date.now() - new Date(iso).getTime()) / 86_400_000;
  if (days < 7) return "age-fresh";
  if (days < 30) return "age-recent";
  if (days < 90) return "age-medium";
  if (days < 180) return "age-old";
  return "age-stale";
}

function fmtAge(iso: string | null): string {
  if (!iso) return "";
  const ms = tickNow.value - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function statusUpdateTs(t: Trail): number {
  // Prefer source_ts (RainoutLine's own status-change time) so a trail
  // that flipped today sorts above one that's been sitting in the same
  // status for weeks. Fall back to fetched_at, then last_seen_at.
  const v = t.source_ts ?? t.fetched_at ?? t.last_seen_at ?? null;
  return v ? Date.parse(v) : 0;
}
function byStatusDesc(a: Trail, b: Trail): number {
  return statusUpdateTs(b) - statusUpdateTs(a);
}

const grouped = computed(() => {
  const open = trails.value.filter((t) => t.status === "open").sort(byStatusDesc);
  const closed = trails.value.filter((t) => t.status === "closed").sort(byStatusDesc);
  const delayed = trails.value.filter((t) => t.status === "delayed").sort(byStatusDesc);
  const other = trails.value
    .filter((t) => t.status !== "open" && t.status !== "closed" && t.status !== "delayed")
    .sort(byStatusDesc);
  return { open, closed, delayed, other };
});

// ── Hero ──
const total = computed(() => counts.value
  ? counts.value.open + counts.value.delayed + counts.value.closed + counts.value.other : 0);
const segments = computed(() => {
  const c = counts.value;
  if (!c || total.value === 0) return [];
  return [
    { n: c.open, color: "#5dff3b", label: "open" },
    { n: c.delayed, color: "#ffb52e", label: "delayed" },
    { n: c.closed, color: "#ff5d7a", label: "closed" },
    { n: c.other, color: "#272a3b", label: "unknown" },
  ].filter((x) => x.n > 0);
});
const starred = computed(() => trails.value.filter((t) => t.subscribed));
const STATUS_COLOR: Record<string, string> = { open: "#5dff3b", delayed: "#ffb52e", closed: "#ff5d7a" };
const statusColor = (s: string | null | undefined) => STATUS_COLOR[s ?? ""] ?? "#9b9bb0";

// Non-interactive mini map of status pins; the whole box opens /trails/map.
const miniEl = ref<HTMLDivElement | null>(null);
let mini: L.Map | null = null;
function renderMini() {
  if (!miniEl.value) return;
  const pinned = trails.value.filter((t) => t.latitude != null && t.longitude != null);
  if (!pinned.length) return;
  if (mini) { mini.remove(); mini = null; }
  mini = L.map(miniEl.value, {
    zoomControl: false, attributionControl: false, dragging: false, touchZoom: false,
    scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false, keyboard: false,
  });
  L.tileLayer(baseTileUrl(true), tileOptions()).addTo(mini);
  L.tileLayer(labelTileUrl(true), { ...tileOptions(), pane: "shadowPane" }).addTo(mini);
  const b = L.latLngBounds([]);
  for (const t of pinned) {
    L.circleMarker([t.latitude!, t.longitude!], {
      radius: 6, color: "#ffffff", weight: 2, fillColor: statusColor(t.status), fillOpacity: 1, interactive: false,
    }).addTo(mini);
    b.extend([t.latitude!, t.longitude!]);
  }
  mini.fitBounds(b.pad(0.15));
}
watch(() => trails.value.map((t) => `${t.id}:${t.status}:${t.latitude}`).join(","), () => nextTick(renderMini));
onUnmounted(() => { if (mini) { mini.remove(); mini = null; } });

onMounted(() => {
  load();
  tickHandle = window.setInterval(() => { tickNow.value = Date.now(); }, 60000);
});
useVisibilityRefresh(() => { load(); });
onUnmounted(() => { if (tickHandle) clearInterval(tickHandle); });
</script>

<template>
  <NeonPage title="Trails">
    <template #trailing>
      <div class="hdr-actions">
        <button class="icon-btn" :title="dense ? 'Switch to expanded rows' : 'Switch to condensed rows'"
                :aria-label="dense ? 'Expanded rows' : 'Condensed rows'" @click="toggleDense">
          <Rows2 v-if="dense" :size="18" /><Rows3 v-else :size="18" />
        </button>
        <button class="icon-btn" :disabled="refreshing" title="Refresh trail status" aria-label="Refresh" @click="refresh">
          <RefreshCw :size="18" :class="{ spinning: refreshing }" />
        </button>
      </div>
    </template>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load trails.</p>

    <template v-else>
      <div v-if="error" class="stale" role="alert" @click="load">
        <strong>{{ trails.length ? "Couldn't refresh — showing saved trail status" : "Couldn't load trails" }}</strong>
        <span>{{ error }}</span><em>Tap to retry</em>
      </div>

      <div v-if="loading && !trails.length" class="skeleton-trails">
        <Skeleton width="100%" height="220px" radius="22px" />
        <div v-for="n in 4" :key="n"><Skeleton width="100%" height="64px" radius="18px" /></div>
      </div>
      <!-- A failed first load is not "no trails seeded": the banner says why. -->
      <template v-else-if="!trails.length && error" />
      <p v-else-if="!trails.length" class="card hint">
        No trails seeded yet. The poller runs every 15 minutes; tap Refresh to trigger an immediate poll.
      </p>

      <template v-else>
        <NeonHero accent="#5dff3b">
          <div class="hero-head">
            <NeonEyebrow style="margin: 0">Trail status</NeonEyebrow>
            <span v-if="syncedAt" class="pill peri">synced {{ fmtAge(syncedAt).replace(' ago', '') }}</span>
          </div>
          <template v-if="counts">
            <div class="count-row">
              <span class="count">{{ counts.open }}</span>
              <span class="of">of {{ total }} open</span>
            </div>
            <div v-if="segments.length" class="seg" role="img"
                 :aria-label="segments.map((x) => `${x.n} ${x.label}`).join(', ')">
              <span v-for="x in segments" :key="x.label" :style="{ flex: x.n, background: x.color }" />
            </div>
            <div class="seg-legend">
              <span v-for="x in segments" :key="x.label"><i :style="{ background: x.label === 'unknown' ? '#9b9bb0' : x.color }" />{{ x.n }} {{ x.label }}</span>
            </div>
          </template>
          <!-- An older server without counts: say nothing rather than count here. -->
          <p v-else class="hint">Status counts unavailable.</p>
          <button class="mini" type="button" aria-label="Open the trail status map" @click="router.push('/trails/map')">
            <div ref="miniEl" class="mini-map" />
            <span class="pill cyan open-map"><MapIcon :size="13" /> Open map</span>
          </button>
        </NeonHero>

        <template v-if="starred.length">
          <NeonEyebrow>Your trails</NeonEyebrow>
          <div class="carousel">
            <RouterLink v-for="t in starred" :key="t.id" class="tile"
                        :to="(t.visits_total ?? 0) > 0 ? `/trails/${t.id}/visits` : '/trails'"
                        :style="{ borderColor: statusColor(t.status) + '4d' }">
              <span class="tile-st" :style="{ color: statusColor(t.status) }">
                <i class="dot" :style="{ background: statusColor(t.status) }" />{{ t.status ?? "unknown" }}
              </span>
              <strong>{{ t.name }}</strong>
              <span class="visits" :class="visitAgeClass(t.last_visit_at)">
                {{ t.last_visit_at ? `ridden ${fmtAge(t.last_visit_at)}` : "not ridden yet" }}
              </span>
            </RouterLink>
          </div>
        </template>

        <section v-for="g in [
          { key: 'open', label: 'Open', list: grouped.open },
          { key: 'delayed', label: 'Delayed', list: grouped.delayed },
          { key: 'closed', label: 'Closed', list: grouped.closed },
          { key: 'other', label: 'Other', list: grouped.other },
        ]" :key="g.key" v-show="g.list.length" :class="{ dense }">
          <NeonEyebrow>{{ g.label }} · {{ g.list.length }}</NeonEyebrow>
          <article v-for="t in g.list" :key="t.id" class="trail"
                   :class="{ flip: flipped.has(t.id), [`st-${t.status ?? 'other'}`]: true }"
                   :style="{ borderColor: statusColor(t.status) + '2e' }">
            <div class="trail-main">
              <i class="dot glow" :style="{ background: statusColor(t.status), color: statusColor(t.status) }" />
              <div class="trail-body">
                <strong>{{ t.name }}</strong>
                <template v-if="!dense">
                  <p v-if="t.comment" class="comment">{{ t.comment }}</p>
                  <p class="meta">
                    {{ fmtAge(t.source_ts || t.fetched_at) }}
                    <template v-if="t.city"> · {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</template>
                    <span v-else-if="t.latitude == null" class="nopin"> · no pin</span>
                  </p>
                  <RouterLink v-if="(t.visits_total ?? 0) > 0" class="visit-chip visits" :class="visitAgeClass(t.last_visit_at)"
                              :to="`/trails/${t.id}/visits`" title="Show the activities linked to this trail">
                    <Bike :size="16" /> {{ t.visits_total }} ride{{ t.visits_total === 1 ? '' : 's' }}
                    <template v-if="t.last_visit_at"> · {{ fmtAge(t.last_visit_at) }}</template>
                    <ChevronRight :size="16" />
                  </RouterLink>
                </template>
                <span v-else class="meta">{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              </div>
              <button v-if="t.latitude != null" class="act" :class="{ on: expandedMaps.has(t.id) }"
                      :aria-label="expandedMaps.has(t.id) ? 'Hide map' : 'Show map'" @click="toggleMap(t)">
                <MapIcon :size="18" />
              </button>
              <button v-if="!dense" class="act" aria-label="Edit pin location" title="Edit pin location" @click="openEdit(t)">
                <Pencil :size="16" />
              </button>
              <button class="act star" :class="{ on: t.subscribed }"
                      :aria-label="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click="toggleSubscribe(t)">
                <Star :size="18" />
              </button>
            </div>
            <div v-if="expandedMaps.has(t.id) && t.latitude != null && t.longitude != null" class="inline-map">
              <TrailMap :trail-id="t.id" :name="t.name" :latitude="t.latitude" :longitude="t.longitude"
                        @expand="openFullMap(t)" />
              <div class="inline-actions">
                <button class="primary" @click="openMaps(t)">Navigate</button>
                <button class="ghost" @click="openEdit(t)">Edit pin</button>
              </div>
            </div>
          </article>
        </section>

        <div class="tools">
          <a v-if="dnisUrl" :href="dnisUrl" target="_blank" rel="noreferrer" class="chip">RainoutLine board ↗</a>
          <button class="chip" :disabled="linking" title="Auto-link activities to trails by GPS proximity" @click="linkActivities">
            <Bike :size="14" /> {{ linking ? "Linking…" : "Link activities" }}
          </button>
          <button class="chip" :disabled="fetchingOsm" title="Pull trail geometry from OpenStreetMap" @click="fetchAllOsm">
            <Route :size="14" /> {{ fetchingOsm ? "Fetching OSM…" : "OSM routes" }}
          </button>
        </div>
        <p v-if="linkResult" class="hint">{{ linkResult }}</p>
      </template>
    </template>

    <!-- Fullscreen map modal -->
    <div v-if="fullMapTrail" class="full-map-overlay" @click.self="closeFullMap">
      <div class="full-map-wrap">
        <header class="full-map-head">
          <strong>{{ fullMapTrail.name }}</strong>
          <span v-if="fullMapTrail.city" class="muted-suffix">· {{ fullMapTrail.city }}{{ fullMapTrail.state ? ', ' + fullMapTrail.state : '' }}</span>
          <button class="close" aria-label="Close map" @click="closeFullMap">✕</button>
        </header>
        <TrailMap v-if="fullMapTrail.latitude != null && fullMapTrail.longitude != null"
                  :trail-id="fullMapTrail.id" :name="fullMapTrail.name"
                  :latitude="fullMapTrail.latitude" :longitude="fullMapTrail.longitude"
                  :expandable="false" :fullscreen="true" />
      </div>
    </div>

    <!-- Edit location drawer -->
    <div v-if="editTrail" class="overlay" @click.self="closeEdit">
      <div class="edit-drawer" role="dialog" aria-modal="true">
        <header>
          <h2>Edit location · {{ editTrail.name }}</h2>
          <button class="close" aria-label="Close" @click="closeEdit">✕</button>
        </header>
        <p class="hint">Search a place name, click the map, or use your GPS. Drag the pin to fine-tune.</p>
        <div class="search-row">
          <input v-model="placeQuery" class="field-in" type="text"
                 placeholder='Place name, "lat, lon", or paste any Google Maps URL' @keydown.enter="searchPlace" />
          <button class="ghost" :disabled="searching || !placeQuery.trim()" @click="searchPlace">{{ searching ? "Searching…" : "Find" }}</button>
        </div>
        <p class="hint small">Accepts place names, "38.92, -94.57", Maps share links, embed URLs, and maps.app.goo.gl short links.</p>
        <div ref="editMapEl" class="edit-map" />
        <div class="quick-actions">
          <button class="ghost" @click="useMyLocation"><MapPin :size="13" /> Use my location</button>
          <button class="ghost" @click="openInMaps"><MapIcon :size="13" /> Open in Google Maps</button>
        </div>
        <div class="form-grid">
          <label>Latitude<input v-model="editLat" class="field-in" type="number" step="0.0001" placeholder="e.g. 38.9881" /></label>
          <label>Longitude<input v-model="editLon" class="field-in" type="number" step="0.0001" placeholder="e.g. -94.7625" /></label>
          <label>City<input v-model="editCity" class="field-in" placeholder="optional" /></label>
          <label>State<input v-model="editState" class="field-in" placeholder="KS / MO / …" maxlength="8" /></label>
        </div>
        <p v-if="editError" class="warn">{{ editError }}</p>
        <div class="actions">
          <button class="primary" :disabled="editSaving" @click="saveEdit">{{ editSaving ? "Saving…" : "Save" }}</button>
          <button class="ghost" @click="closeEdit">Cancel</button>
        </div>
      </div>
    </div>
  </NeonPage>
</template>

<style scoped>
.hdr-actions { display: flex; gap: 8px; }
.icon-btn { width: 42px; height: 42px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(40, 230, 255, .14); border: 1px solid rgba(40, 230, 255, .45); color: var(--rn-cyan); cursor: pointer; }
.icon-btn:disabled { opacity: .5; cursor: default; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
.hint { color: var(--rn-mut); font-size: 13px; margin: 6px 0; }
.hint.small { font-size: 11px; margin-top: 0; }
.warn { color: var(--rn-amber); font-size: 12px; }
.stale { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; margin-bottom: 12px; border-radius: 14px;
  background: rgba(255, 181, 46, .10); border: 1px solid rgba(255, 181, 46, .32); cursor: pointer; }
.stale strong { color: var(--rn-amber); font-size: 13px; }
.stale span { color: var(--rn-mut); font-size: 12px; }
.stale em { color: var(--rn-cyan); font-size: 12px; font-style: normal; font-weight: 600; }
.skeleton-trails { display: flex; flex-direction: column; gap: 8px; }
.card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; }

.hero-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.pill { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 12px; padding: 5px 12px; border-radius: 999px;
  border: 1px solid; display: inline-flex; align-items: center; gap: 4px; }
.pill.peri { color: var(--rn-peri); background: rgba(111, 123, 255, .12); border-color: rgba(111, 123, 255, .4); }
.pill.cyan { color: var(--rn-cyan); background: rgba(15, 17, 24, .75); border-color: rgba(40, 230, 255, .45); }
.count-row { display: flex; align-items: baseline; gap: 10px; }
.count { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 56px; line-height: 1; color: var(--rn-lime);
  letter-spacing: -1px; text-shadow: 0 0 18px rgba(93, 255, 59, .35); }
.of { font-size: 18px; font-weight: 600; }
.seg { display: flex; height: 10px; border-radius: 5px; overflow: hidden; margin: 12px 0 8px; }
.seg-legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--rn-mut); font-size: 12px; font-family: 'Space Grotesk', monospace; }
.seg-legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
.mini { position: relative; display: block; width: 100%; height: 160px; margin-top: 12px; padding: 0; border: 1px solid var(--rn-line);
  border-radius: 16px; overflow: hidden; background: var(--rn-bg); cursor: pointer; }
.mini:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.mini-map { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.open-map { position: absolute; right: 8px; bottom: 8px; z-index: 500; }

.carousel { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }
.tile { flex: 0 0 150px; display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: 18px; background: var(--rn-card);
  border: 1px solid; color: inherit; text-decoration: none; }
.tile strong { font-size: 14px; min-height: 2.5em; }
.tile-st { font-family: 'Space Grotesk', monospace; font-size: 10px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 6px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
.dot.glow { width: 12px; height: 12px; box-shadow: 0 0 9px currentColor; margin-top: 5px; }
.visits { font-size: 12px; font-weight: 600; }
.visits.age-fresh, .visits.age-recent { color: var(--rn-lime); }
.visits.age-medium, .visits.age-old { color: var(--rn-amber); }
.visits.age-stale { color: var(--rn-mut); }

.trail { background: var(--rn-card); border: 1px solid; border-radius: 18px; margin-bottom: 8px; overflow: hidden; }
.trail.st-closed { opacity: .9; }
.trail-main { display: flex; align-items: flex-start; gap: 10px; padding: 10px 6px 10px 14px; }
.dense .trail-main { padding-top: 4px; padding-bottom: 4px; align-items: center; }
.dense .dot.glow { margin-top: 0; }
.trail-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; padding-top: 2px; }
.trail-body strong { font-size: 15px; }
.comment { color: #c4c4d4; font-size: 13px; margin: 0; }
.meta { color: var(--rn-mut); font-size: 12px; margin: 0; font-family: 'Space Grotesk', monospace; }
.nopin { color: var(--rn-amber); }
.visit-chip { align-self: flex-start; display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 0 10px; margin-top: 6px;
  border-radius: 16px; border: 1px solid currentColor; background: color-mix(in srgb, currentColor 10%, transparent); text-decoration: none; }
.act { width: 44px; height: 44px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
  background: none; border: 0; color: var(--rn-mut); cursor: pointer; }
.act:hover, .act.on { color: var(--rn-cyan); background: #ffffff10; }
.act.star.on { color: var(--rn-amber); filter: drop-shadow(0 0 4px rgba(255, 181, 46, .55)); }
.act:focus-visible { outline: 2px solid var(--rn-cyan); }
.inline-map { border-top: 1px solid var(--rn-line); }
.inline-actions { display: flex; gap: 8px; padding: 10px 12px; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 14px; border-radius: 999px; border: 1px solid var(--rn-line);
  background: var(--rn-card); color: var(--rn-mut); font: inherit; font-size: 12px; cursor: pointer; text-decoration: none; }
.chip:disabled { opacity: .5; }

@keyframes flip-open { 20% { box-shadow: 0 0 22px rgba(93, 255, 59, .45); background: rgba(93, 255, 59, .18); } }
@keyframes flip-closed { 20% { box-shadow: 0 0 22px rgba(255, 93, 122, .45); background: rgba(255, 93, 122, .18); } }
@keyframes flip-delayed { 20% { box-shadow: 0 0 22px rgba(255, 181, 46, .45); background: rgba(255, 181, 46, .18); } }
.trail.st-open.flip { animation: flip-open 2.5s ease-out; }
.trail.st-closed.flip { animation: flip-closed 2.5s ease-out; }
.trail.st-delayed.flip { animation: flip-delayed 2.5s ease-out; }

.primary { background: var(--rn-cyan); color: var(--rn-onacc); border: 0; border-radius: 10px; padding: 8px 16px; font: inherit; font-weight: 700; cursor: pointer; }
.primary:disabled { opacity: .6; }
.ghost { background: transparent; color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 10px; padding: 8px 14px; font: inherit; cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px; }
.field-in { background: var(--rn-bg); border: 1px solid var(--rn-line); color: var(--rn-ink); border-radius: 10px; padding: 8px 10px; font: inherit; font-size: 14px; }

.full-map-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .7); z-index: 1100; display: flex; align-items: stretch;
  justify-content: center; padding: 2vh 2vw; }
.full-map-wrap { flex: 1; max-width: 1400px; max-height: 96vh; background: var(--rn-bg); border: 1px solid var(--rn-track);
  border-radius: 16px; overflow: hidden; display: flex; flex-direction: column; }
.full-map-head { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--rn-card); }
.full-map-head .muted-suffix { color: var(--rn-mut); font-size: 13px; flex: 1; }
.close { background: none; border: 0; color: var(--rn-mut); cursor: pointer; font-size: 18px; min-width: 40px; min-height: 40px; }
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .55); z-index: 1100; display: flex; justify-content: flex-end; }
.edit-drawer { width: min(420px, 100%); height: 100%; overflow-y: auto; background: var(--rn-bg); border-left: 1px solid var(--rn-track);
  padding: 16px 18px; box-sizing: border-box; }
.edit-drawer header { display: flex; justify-content: space-between; align-items: center; }
.edit-drawer h2 { margin: 0; font-size: 16px; }
.search-row { display: flex; gap: 6px; margin: 6px 0; }
.search-row .field-in { flex: 1; }
.edit-map { height: 280px; border-radius: 12px; overflow: hidden; border: 1px solid var(--rn-line); margin: 8px 0; }
.quick-actions { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--rn-mut); }
.actions { display: flex; gap: 8px; margin-top: 16px; }
</style>
