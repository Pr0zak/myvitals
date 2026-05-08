<script setup lang="ts">
/**
 * /trails — RainoutLine status board for the user's local trail
 * network. Pull-to-refresh hits POST /trails/refresh; star toggle
 * subscribes for status-flip pings.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "@/leaflet-icons";   // side-effect: fixes default marker URLs under Vite
import { effectiveTheme } from "@/theme";
import { Star, RefreshCw, Navigation, Pencil, Map as MapIcon, Bike } from "lucide-vue-next";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import Card from "@/components/Card.vue";
import TrailMap from "@/components/TrailMap.vue";

type Trail = Awaited<ReturnType<typeof api.trails>>["trails"][number];

const trails = ref<Trail[]>([]);
const dnisUrl = ref<string | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string>("");
const tickNow = ref(Date.now());
let tickHandle: number | null = null;

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = trails.value.length === 0;
  error.value = "";
  try {
    const r = await api.trails();
    trails.value = r.trails;
    dnisUrl.value = r.dnis_url ?? null;
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
  const tiles = effectiveTheme.value === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
  L.tileLayer(tiles, {
    attribution: "© OpenStreetMap, © CARTO",
    subdomains: "abcd", maxZoom: 19,
  }).addTo(editMap);

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

onMounted(() => {
  load();
  tickHandle = window.setInterval(() => { tickNow.value = Date.now(); }, 60000);
});
onUnmounted(() => { if (tickHandle) clearInterval(tickHandle); });
</script>

<template>
  <main class="trails">
    <header>
      <h1>Trails</h1>
      <div class="header-actions">
        <a v-if="dnisUrl" :href="dnisUrl" target="_blank" rel="noreferrer"
           class="refresh dnis-link"
           title="Open the full RainoutLine status board">
          rainoutline ↗
        </a>
        <button class="refresh" :disabled="refreshing" @click="refresh">
          <RefreshCw :size="16" :class="{ spinning: refreshing }" />
          {{ refreshing ? "Refreshing…" : "Refresh" }}
        </button>
        <button class="refresh" :disabled="linking" @click="linkActivities"
                title="Auto-link Strava / Garmin activities to trails by GPS proximity">
          <Bike :size="14" /> {{ linking ? "Linking…" : "Link activities" }}
        </button>
        <button class="refresh" :disabled="fetchingOsm" @click="fetchAllOsm"
                title="Pull official trail route geometry from OpenStreetMap (free, no key)">
          🗺 {{ fetchingOsm ? "Fetching OSM…" : "OSM routes" }}
        </button>
      </div>
    </header>
    <p v-if="linkResult" class="hint" style="text-align: right">{{ linkResult }}</p>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load trails.</p>
    <p v-else-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>
    <Card v-else-if="trails.length === 0" title="No trails seeded yet">
      <p class="hint">
        The trail poller runs on a 15-minute schedule; the first tick
        seeds the catalog. Tap <strong>Refresh now</strong> to trigger
        an immediate poll.
      </p>
    </Card>

    <template v-else>
      <section v-if="grouped.open.length" class="group group-open">
        <h2>Open · {{ grouped.open.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.open" :key="t.id" class="card status-open"
                   :class="{ has_loc: t.latitude != null }"
                   @click="openMaps(t)">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click.stop="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
              <button v-if="t.latitude != null" class="star map-toggle"
                      :class="{ on: expandedMaps.has(t.id) }"
                      title="Show map + linked rides"
                      @click.stop="toggleMap(t)">
                <MapIcon :size="14" />
              </button>
              <button class="star edit-pin"
                      title="Edit pin location"
                      @click.stop="openEdit(t)">
                <Pencil :size="14" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">
              <span>{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              <span v-if="t.city" class="loc">· {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</span>
              <span v-else-if="t.latitude == null" class="loc nopin">· no pin</span>
              <span v-if="(t.visits_total ?? 0) > 0" class="visits"
                    :class="visitAgeClass(t.last_visit_at)">
                · <Bike :size="11" class="bike-ic" /> {{ t.visits_total }} visit{{ t.visits_total === 1 ? '' : 's' }}
                <span v-if="t.last_visit_at" class="last-visit">
                  · last {{ fmtAge(t.last_visit_at) }}
                </span>
              </span>
              <Navigation v-if="t.latitude != null" :size="12" class="nav-ic" />
            </p>
            <TrailMap
              v-if="expandedMaps.has(t.id) && t.latitude != null && t.longitude != null"
              :trail-id="t.id" :name="t.name"
              :latitude="t.latitude" :longitude="t.longitude"
              @click.stop
              @expand="openFullMap(t)"
            />
          </article>
        </div>
      </section>

      <section v-if="grouped.delayed.length" class="group group-delayed">
        <h2>Delayed · {{ grouped.delayed.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.delayed" :key="t.id" class="card status-delayed"
                   :class="{ has_loc: t.latitude != null }"
                   @click="openMaps(t)">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click.stop="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
              <button v-if="t.latitude != null" class="star map-toggle"
                      :class="{ on: expandedMaps.has(t.id) }"
                      title="Show map + linked rides"
                      @click.stop="toggleMap(t)">
                <MapIcon :size="14" />
              </button>
              <button class="star edit-pin"
                      title="Edit pin location"
                      @click.stop="openEdit(t)">
                <Pencil :size="14" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">
              <span>{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              <span v-if="t.city" class="loc">· {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</span>
              <span v-else-if="t.latitude == null" class="loc nopin">· no pin</span>
              <Navigation v-if="t.latitude != null" :size="12" class="nav-ic" />
            </p>
            <TrailMap
              v-if="expandedMaps.has(t.id) && t.latitude != null && t.longitude != null"
              :trail-id="t.id" :name="t.name"
              :latitude="t.latitude" :longitude="t.longitude"
              @click.stop
              @expand="openFullMap(t)"
            />
          </article>
        </div>
      </section>

      <section v-if="grouped.closed.length" class="group group-closed">
        <h2>Closed · {{ grouped.closed.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.closed" :key="t.id" class="card status-closed"
                   :class="{ has_loc: t.latitude != null }"
                   @click="openMaps(t)">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click.stop="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
              <button v-if="t.latitude != null" class="star map-toggle"
                      :class="{ on: expandedMaps.has(t.id) }"
                      title="Show map + linked rides"
                      @click.stop="toggleMap(t)">
                <MapIcon :size="14" />
              </button>
              <button class="star edit-pin"
                      title="Edit pin location"
                      @click.stop="openEdit(t)">
                <Pencil :size="14" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">
              <span>{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              <span v-if="t.city" class="loc">· {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</span>
              <span v-else-if="t.latitude == null" class="loc nopin">· no pin</span>
              <span v-if="(t.visits_total ?? 0) > 0" class="visits"
                    :class="visitAgeClass(t.last_visit_at)">
                · <Bike :size="11" class="bike-ic" /> {{ t.visits_total }} visit{{ t.visits_total === 1 ? '' : 's' }}
                <span v-if="t.last_visit_at" class="last-visit">
                  · last {{ fmtAge(t.last_visit_at) }}
                </span>
              </span>
              <Navigation v-if="t.latitude != null" :size="12" class="nav-ic" />
            </p>
            <TrailMap
              v-if="expandedMaps.has(t.id) && t.latitude != null && t.longitude != null"
              :trail-id="t.id" :name="t.name"
              :latitude="t.latitude" :longitude="t.longitude"
              @click.stop
              @expand="openFullMap(t)"
            />
          </article>
        </div>
      </section>

      <section v-if="grouped.other.length" class="group">
        <h2>Other · {{ grouped.other.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.other" :key="t.id" class="card">
            <header>
              <strong>{{ t.name }}</strong>
              <span class="status-tag">{{ t.status ?? "—" }}</span>
              <button class="star" :class="{ on: t.subscribed }"
                      @click="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
          </article>
        </div>
      </section>
    </template>

    <!-- Fullscreen map modal -->
    <div v-if="fullMapTrail" class="full-map-overlay" @click.self="closeFullMap">
      <div class="full-map-wrap">
        <header class="full-map-head">
          <strong>{{ fullMapTrail.name }}</strong>
          <span v-if="fullMapTrail.city" class="muted-suffix">
            · {{ fullMapTrail.city }}{{ fullMapTrail.state ? ', ' + fullMapTrail.state : '' }}
          </span>
          <button class="close" @click="closeFullMap">✕</button>
        </header>
        <TrailMap
          v-if="fullMapTrail.latitude != null && fullMapTrail.longitude != null"
          :trail-id="fullMapTrail.id" :name="fullMapTrail.name"
          :latitude="fullMapTrail.latitude" :longitude="fullMapTrail.longitude"
          :expandable="false" :fullscreen="true"
        />
      </div>
    </div>

    <!-- Edit location modal -->
    <div v-if="editTrail" class="overlay" @click.self="closeEdit">
      <div class="edit-drawer">
        <header>
          <h2>Edit location · {{ editTrail.name }}</h2>
          <button class="close" @click="closeEdit">✕</button>
        </header>
        <p class="hint">Search a place name, click the map, or use your GPS. Drag the pin to fine-tune.</p>
        <div class="search-row">
          <input
            v-model="placeQuery"
            type="text"
            placeholder='Place name, "lat, lon", or paste any Google Maps URL'
            @keydown.enter="searchPlace"
          />
          <button class="ghost" :disabled="searching || !placeQuery.trim()"
                  @click="searchPlace">
            {{ searching ? "Searching…" : "Find" }}
          </button>
        </div>
        <p class="hint" style="font-size: 0.7rem; color: var(--muted-2); margin-top: 0">
          Accepts place names, "38.92, -94.57", Maps share links, embed URLs,
          and maps.app.goo.gl short links.
        </p>
        <div ref="editMapEl" class="edit-map" />
        <div class="quick-actions">
          <button class="ghost" @click="useMyLocation">📍 Use my location</button>
          <button class="ghost" @click="openInMaps">🗺 Open in Google Maps</button>
        </div>
        <div class="form-grid">
          <label>Latitude<input type="number" step="0.0001" v-model="editLat" placeholder="e.g. 38.9881" /></label>
          <label>Longitude<input type="number" step="0.0001" v-model="editLon" placeholder="e.g. -94.7625" /></label>
          <label>City<input v-model="editCity" placeholder="optional" /></label>
          <label>State<input v-model="editState" placeholder="KS / MO / …" maxlength="8" /></label>
        </div>
        <p v-if="editError" class="err">{{ editError }}</p>
        <div class="actions">
          <button class="primary" :disabled="editSaving" @click="saveEdit">
            {{ editSaving ? "Saving…" : "Save" }}
          </button>
          <button class="ghost" @click="closeEdit">Cancel</button>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.trails { max-width: 880px; }
header { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; }
header h1 { margin: 0; }
.refresh {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.45rem 0.9rem; background: var(--bg-2);
  border: 1px solid var(--line); border-radius: 6px;
  color: var(--text-soft); cursor: pointer;
}
.refresh:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }

.hint { color: var(--muted); margin: 0.5rem 0; }
.err { color: #f87171; }

.group { margin-bottom: 1.4rem; }
.group h2 {
  font-size: 0.78rem; color: var(--muted); letter-spacing: 0.08em;
  text-transform: uppercase; margin: 0 0 0.6rem; font-weight: 600;
}
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.6rem;
}
.card {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 10px; padding: 0.7rem 0.9rem;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.card.status-open { border-left: 3px solid #22c55e; }
.card.status-closed { border-left: 3px solid #ef4444; opacity: 0.85; }
.card.status-delayed { border-left: 3px solid #eab308; }
.card.has_loc { cursor: pointer; transition: border-color 0.12s; }
.card.has_loc:hover { border-color: var(--accent, #ef4444); }
.nav-ic { color: var(--muted-2); margin-left: 0.4rem; vertical-align: middle; }
.rainout-link { color: var(--muted); text-decoration: none; margin-left: 0.3rem; }
.rainout-link:hover { color: var(--accent); }
.loc { color: var(--muted); }
.loc.nopin { color: #f59e0b; }
.visits { font-weight: 500; }
.visits.age-fresh   { color: #22c55e; }   /* < 7 days */
.visits.age-recent  { color: #84cc16; }   /* 7-30 days */
.visits.age-medium  { color: #f59e0b; }   /* 30-90 days */
.visits.age-old     { color: #fb923c; }   /* 90-180 days */
.visits.age-stale   { color: #94a3b8; }   /* > 180 days */
.last-visit { color: var(--muted-2); font-weight: 400; font-size: 0.7rem; }
.header-actions { display: flex; gap: 0.5rem; }
.edit-pin { color: var(--muted-2); }
.edit-pin:hover { color: var(--accent, #ef4444); }
.map-toggle { color: var(--muted-2); }
.map-toggle:hover { color: var(--accent, #ef4444); }
.map-toggle.on { color: var(--accent, #ef4444); }

.full-map-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 110;
  display: flex; align-items: stretch; justify-content: center;
  padding: 2vh 2vw;
}
.full-map-wrap {
  flex: 1; max-width: 1400px; max-height: 96vh;
  background: var(--bg-1); border: 1px solid var(--line);
  border-radius: 12px; overflow: hidden;
  display: flex; flex-direction: column;
}
.full-map-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.7rem 1rem; border-bottom: 1px solid var(--line);
  background: var(--bg-2);
}
.full-map-head strong { color: var(--text); font-size: 1rem; }
.full-map-head .muted-suffix { color: var(--muted); font-size: 0.85rem; flex: 1; }
.full-map-head .close {
  background: none; border: none; color: var(--muted); cursor: pointer;
  font-size: 1.2rem; padding: 0.2rem 0.5rem;
}
.full-map-head .close:hover { color: var(--text); }

.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 100;
  display: flex; justify-content: flex-end; }
.edit-drawer {
  width: min(420px, 100%); height: 100%; overflow-y: auto;
  background: var(--bg-1); border-left: 1px solid var(--line);
  padding: 1rem 1.2rem;
}
.edit-drawer header { display: flex; justify-content: space-between; align-items: center; }
.edit-drawer header h2 { margin: 0; font-size: 1rem; color: var(--text); }
.edit-drawer .close { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.1rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; margin-top: 1rem; }
.form-grid label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.78rem; color: var(--muted); }
.form-grid input {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 0.4rem 0.55rem; color: var(--text);
  font-family: inherit;
}
.edit-map {
  height: 280px; border-radius: 8px; overflow: hidden;
  border: 1px solid var(--line); margin: 0.5rem 0;
}
.search-row { display: flex; gap: 0.4rem; margin: 0.4rem 0; }
.search-row input {
  flex: 1; padding: 0.45rem 0.6rem; font-size: 0.85rem;
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 6px; color: var(--text); font-family: inherit;
}
.search-row .ghost { white-space: nowrap; padding: 0.45rem 0.85rem;
  font-size: 0.85rem; }
.quick-actions { display: flex; gap: 0.4rem; margin: 0.5rem 0 0.6rem; flex-wrap: wrap; }
.quick-actions .ghost { padding: 0.4rem 0.7rem; font-size: 0.78rem; }

.actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.actions .primary {
  background: var(--accent, #ef4444); color: #fff; border: none;
  padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer;
}
.actions .primary:disabled { opacity: 0.6; cursor: not-allowed; }
.actions .ghost {
  background: transparent; color: var(--muted); border: 1px solid var(--line);
  padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer;
}

.card header {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 0.2rem;
}
.card header strong { flex: 1; font-size: 0.95rem; color: var(--text); }
.card .dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0;
}
.card.status-open .dot { background: #22c55e; }
.card.status-closed .dot { background: #ef4444; }
.card.status-delayed .dot { background: #eab308; }

.star {
  background: none; border: none; cursor: pointer; padding: 4px;
  color: var(--muted); border-radius: 4px;
}
.star:hover { color: var(--accent, #ef4444); background: var(--bg-1); }
.star.on { color: #f59e0b; }

.status-tag { color: var(--muted); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.06em; }
.comment { color: var(--text-soft); font-size: 0.82rem; margin: 0; }
.meta { color: var(--muted-2); font-size: 0.74rem; margin: 0;
  font-family: 'Geist Mono', ui-monospace, monospace; }
</style>
