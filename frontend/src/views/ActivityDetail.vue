<script setup lang="ts">
/**
 * Activity detail (UI-5) — map first. Phone twin: `ActivityDetailScreen.kt`.
 *
 * The route leads: a 300px map card with a scrim carrying the type, name
 * and local start time (no route → a category-tinted card in its place).
 * Below it three big numbers and a quiet stat line instead of a flat
 * key/value grid. The HR chart shades the server's Z1-Z5 bands behind the
 * line, and time-in-zone is ONE stacked bar with a legend. Max HR is Ink,
 * or Amber when the session reached the top zone — never the crisis
 * colour. A failed edit is an inline notice; it used to set the page-level
 * error. Zones were requested with an undefined id (`params.source_id` on
 * a route whose param is `id`), so the zone cards never rendered.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import VChart from "@/echarts";
import { baseTileUrl, labelTileUrl, tileOptions } from "@/mapTiles";
import polylineDecoder from "@mapbox/polyline";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import ActivityIcon from "@/components/ActivityIcon.vue";
import { api } from "@/api/client";
import { categoryColor, categoryForType } from "@/utils/activityCategory";
import type { Activity, HeartRateSeries } from "@/api/types";
import { chartTheme, isNeon } from "@/theme";
import { fmtElevation, fmtPace, distanceVal, distanceUnit, isImperial } from "@/units";
import { fmtActivityType, fmtDateTime } from "@/format";
import { timeAxisFormatter } from "@/components/charts/chartHelpers";

const route = useRoute();
const router = useRouter();
const activity = ref<Activity | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
/** Failure of an ACTION on a loaded activity (edit, link, notes). Shown
 *  inline; never replaces the page. */
const notice = ref<string | null>(null);

const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let polylineLayer: L.Polyline | null = null;
let heatmapSegments: L.Polyline[] = [];
let mapCursor: L.CircleMarker | null = null;
let polylineCoords: [number, number][] = [];
const mapMode = ref<"line" | "heatmap">("line");

// Trail-layer overlay state
const trailMarkers = new Map<number, L.CircleMarker>();
const hiddenTrailIds = ref<Set<number>>(new Set());
const trailLayerOpen = ref(false);  // legend collapsed by default
const NEARBY_TRAIL_MILES = 25;       // ~40 km — generous so out-of-state activities still pull in something

const TRAIL_STATUS_COLOR = computed<Record<string, string>>(() =>
  isNeon.value
    ? { open: "#5dff3b", closed: "#ff5d7a", delayed: "#ffb52e", unknown: "#9b9bb0" }
    : { open: "#22c55e", closed: "#ef4444", delayed: "#f59e0b", unknown: "#94a3b8" },
);

// Shared cursor (seconds since activity.start_at). Hover on any
// time-aligned chart sets this; the map marker + the other chart's
// tooltips track it.
const cursorOffsetS = ref<number | null>(null);
const hrChartRef = ref<any>(null);
const streamChartRef = ref<any>(null);
// Re-entry guard: showTip dispatched programmatically also fires
// updateAxisPointer on the target chart, which would re-emit and
// loop. Set during programmatic dispatch.
let dispatching = false;

// Notes & tags state
const notesInput = ref("");
const tagInput = ref("");
const savingNotes = ref(false);
const savedFlag = ref(false);
const tags = ref<string[]>([]);

async function load() {
  loading.value = activity.value == null;
  try {
    const a = await api.activity(route.params.source as string, route.params.id as string);
    error.value = null;
    activity.value = a;
    notesInput.value = a.notes ?? "";
    loadTrails();
    tags.value = a.tags ?? [];
    // HR for exactly the activity window (the phone asks for the same).
    const start = new Date(a.start_at);
    const end = new Date(start.getTime() + a.duration_s * 1000);
    try { hr.value = await api.heartRate({ since: start, until: end }); }
    catch { hr.value = null; }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

function renderMap() {
  if (!mapEl.value || !activity.value || !activity.value.polyline) return;
  if (map) { map.remove(); map = null; }
  mapCursor = null;
  heatmapSegments = [];

  const coords = polylineDecoder.decode(activity.value.polyline) as [number, number][];
  if (coords.length === 0) return;
  polylineCoords = coords;

  map = L.map(mapEl.value, { zoomControl: true });
  const dark = true;
  L.tileLayer(baseTileUrl(dark), tileOptions()).addTo(map);
  L.tileLayer(labelTileUrl(dark), { ...tileOptions(), pane: "shadowPane" }).addTo(map);

  polylineLayer = L.polyline(coords, {
    color: isNeon.value ? "#28e6ff" : "#38bdf8", weight: 3,
  }).addTo(map);
  applyMapMode();

  // Start (green) + end (red) markers
  const startIcon = L.divIcon({
    className: "se-marker start-marker",
    html: "<div></div>",
    iconSize: [14, 14], iconAnchor: [7, 7],
  });
  const endIcon = L.divIcon({
    className: "se-marker end-marker",
    html: "<div></div>",
    iconSize: [14, 14], iconAnchor: [7, 7],
  });
  L.marker(coords[0], { icon: startIcon }).addTo(map).bindTooltip("Start", { direction: "top" });
  L.marker(coords[coords.length - 1], { icon: endIcon }).addTo(map).bindTooltip("End", { direction: "top" });

  // Distance markers every 5 mi/km along the polyline (user units)
  if (activity.value.distance_m && activity.value.distance_m >= 5000) {
    const totalUnits = distanceVal(activity.value.distance_m)!;
    const stepUnits = totalUnits > 50 ? 10 : 5;
    const unitMeters = isImperial.value ? 1609.344 : 1000;
    let cumDist = 0;  // meters
    let nextMark = stepUnits;
    for (let i = 1; i < coords.length; i++) {
      cumDist += haversine(coords[i - 1], coords[i]);
      while (cumDist / unitMeters >= nextMark && nextMark < totalUnits) {
        L.circleMarker(coords[i], {
          radius: 4, color: "#ffffff", weight: 1,
          fillColor: isNeon.value ? "#28e6ff" : "#0ea5e9", fillOpacity: 1,
        }).addTo(map).bindTooltip(`${nextMark} ${distanceUnit.value}`, { permanent: false, direction: "top" });
        nextMark += stepUnits;
      }
    }
  }

  map.fitBounds(polylineLayer.getBounds(), { padding: [20, 20] });
  applyTrailLayer();
}

function haversine(a: [number, number], b: [number, number]): number {
  const R = 6371000;
  const toRad = (x: number) => (x * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]); const lat2 = toRad(b[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

onMounted(() => {
  load().then(() => setTimeout(renderMap, 50));
});

watch(activity, () => setTimeout(renderMap, 50));

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
});

// TD-2 — HR zones come from the server, whole.
//
// This screen used to compute them three separate times and disagree with
// itself: the streamgraph and the pie bucketed by percentage of a profile-
// derived max and counted *samples*, while the zone-breakdown card divided
// by `activity.max_hr` — the session's own observed peak — so an easy ride
// that topped out at 140 bpm reported time in Z4 and Z5. None of the three
// matched the time-weighted figures the cardio coach was quoting back to
// the user from the same data.
//
// Now there is one number, computed once, in analytics/cardio.py.
const zoneData = ref<import("../api/types").ActivityZones | null>(null);
async function loadZones() {
  const src = route.params.source as string;
  const sid = route.params.id as string;
  try {
    zoneData.value = await api.activityZones(src, sid);
  } catch { /* leave null — the zone cards stay hidden */ }
}
onMounted(loadZones);
// Labels for the type chip ("Yard work", not "yard_work"). Optional: the
// chip falls back to the raw key if this fails.
onMounted(async () => {
  try { typeChoices.value = await api.activityTypeChoices(); } catch { /* raw key */ }
});

/** 0-indexed zone for a bpm reading, looked up against the *server's*
 *  boundaries. Used only to colour things (the map heat overlay), never to
 *  produce a duration or a percentage — those come down already computed. */
function zoneIndexFor(bpm: number): number {
  const zones = zoneData.value?.zones;
  if (!zones) return 0;
  for (let i = zones.length - 1; i >= 0; i--) {
    if (bpm >= zones[i].lo_bpm) return i;
  }
  return 0;
}

const maxHrNote = computed<string | null>(() => {
  const z = zoneData.value;
  if (!z) return null;
  if (z.max_hr_source === "profile") return `Zones from your max HR of ${z.max_hr} bpm.`;
  if (z.max_hr_source === "estimated")
    return `Zones from an estimated max HR of ${z.max_hr} bpm (Tanaka, age ${z.age_used}). Set a measured max in Settings → Profile for accurate zones.`;
  return `Zones from a default max HR of ${z.max_hr} bpm — no birth date or measured max on file, so these boundaries are a guess.`;
});

// Z1..Z5 cool to hot — the NeonMV tokens, same as the phone.
const ZONE_COLORS = computed<string[]>(() => ["#6f7bff", "#28e6ff", "#5dff3b", "#ffb52e", "#ff5d7a"]);
const ZONE_LABELS = ["Z1 Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold", "Z5 VO2"];

// Toggle map between solid-blue polyline and HR-colored segments.
// Heatmap uses the same zone palette as the HR-zones chart so the
// visual story stays consistent across cards. Assumes uniform GPS
// sample spacing in time across the activity — same approximation
// as the cursor sync.
function applyMapMode() {
  if (!map || !activity.value) return;
  // Clear any previous heatmap segments
  for (const seg of heatmapSegments) seg.remove();
  heatmapSegments = [];
  if (mapMode.value === "line") {
    if (polylineLayer) polylineLayer.setStyle({ opacity: 1 });
    return;
  }
  if (!hr.value || hr.value.points.length === 0 || polylineCoords.length < 2) {
    // No HR data → fall back to line view silently.
    if (polylineLayer) polylineLayer.setStyle({ opacity: 1 });
    return;
  }
  if (polylineLayer) polylineLayer.setStyle({ opacity: 0.15 });
  const startMs = new Date(activity.value.start_at).getTime();
  const durMs = activity.value.duration_s * 1000;
  // Pre-bin HR samples by time bucket aligned to polyline-index for fast lookup.
  const N = polylineCoords.length;
  for (let i = 0; i < N - 1; i++) {
    const tFrac = i / (N - 1);
    const tMs = startMs + tFrac * durMs;
    // Find nearest HR sample
    let nearest = hr.value.points[0];
    let nearestDelta = Math.abs(new Date(nearest.time).getTime() - tMs);
    for (const p of hr.value.points) {
      const d = Math.abs(new Date(p.time).getTime() - tMs);
      if (d < nearestDelta) { nearest = p; nearestDelta = d; }
    }
    const z = zoneIndexFor(nearest.value);
    const seg = L.polyline([polylineCoords[i], polylineCoords[i + 1]], {
      color: ZONE_COLORS.value[z], weight: 4, opacity: 0.9,
    }).addTo(map);
    heatmapSegments.push(seg);
  }
}

watch(mapMode, () => applyMapMode());
watch(hr, () => { if (mapMode.value === "heatmap") applyMapMode(); });

// ── Trail layer ──
const activityCentroid = computed<[number, number] | null>(() => {
  if (polylineCoords.length === 0) return null;
  let sLat = 0, sLng = 0;
  for (const [la, ln] of polylineCoords) { sLat += la; sLng += ln; }
  return [sLat / polylineCoords.length, sLng / polylineCoords.length];
});

/**
 * SA-P3 — which of the three no-route states this activity is in, in
 * words. Derived, never decided here: the state is computed on the phone
 * against Health Connect and stored on the row, for the same reason
 * `analytics/compare.py` owns `better` and `_goal_progress` owns
 * `state_tone` — a client guessing at it would eventually tell the user a
 * route is waiting for them when Health Connect has already said there
 * is none.
 *
 * `null` is deliberately NOT read as "no route". It means nobody has
 * asked, which is every activity ingested before routes were read, and
 * saying "there is no GPS track" about data that was never requested is
 * the same class of false confidence the null-is-not-zero rule exists to
 * prevent everywhere else in this app.
 */
const routeEmptyText = computed(() => {
  switch (activity.value?.route_state) {
    case "consent_required":
      return "Health Connect has a GPS track for this session and is holding it back until route access is granted on your phone.";
    case "none":
      return "Health Connect was asked and has no GPS track for this session.";
    default:
      return "No route has been requested for this session yet — it was recorded before this app read exercise routes.";
  }
});

const nearbyTrails = computed(() => {
  const c = activityCentroid.value;
  if (!c) return [];
  return trails.value
    .filter((t) => t.latitude != null && t.longitude != null)
    .map((t) => ({ t, mi: haversineMi(c, [t.latitude!, t.longitude!]) }))
    .filter((x) => x.mi <= NEARBY_TRAIL_MILES)
    .sort((a, b) => a.mi - b.mi);
});

function haversineMi(a: [number, number], b: [number, number]): number {
  const R = 3958.8;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const s = Math.sin(dLat / 2) ** 2 +
    Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.sqrt(s));
}

function applyTrailLayer() {
  if (!map) return;
  for (const m of trailMarkers.values()) m.remove();
  trailMarkers.clear();
  for (const { t } of nearbyTrails.value) {
    if (hiddenTrailIds.value.has(t.id)) continue;
    const color = TRAIL_STATUS_COLOR.value[t.status ?? "unknown"];
    const marker = L.circleMarker([t.latitude!, t.longitude!], {
      radius: 8, color, weight: 2, fillColor: color, fillOpacity: 0.75,
    }).addTo(map);
    marker.bindTooltip(
      `<strong>${t.name}</strong><br/>${t.status ?? "unknown"}` +
      (t.city ? `<br/><span style="color:#94a3b8">${t.city}${t.state ? ', ' + t.state : ''}</span>` : ''),
      { direction: "top" },
    );
    trailMarkers.set(t.id, marker);
  }
}

watch([nearbyTrails, hiddenTrailIds], () => applyTrailLayer(), { deep: true });

function toggleTrail(id: number) {
  const s = new Set(hiddenTrailIds.value);
  if (s.has(id)) s.delete(id); else s.add(id);
  hiddenTrailIds.value = s;
}

function panToTrail(id: number) {
  const t = nearbyTrails.value.find((x) => x.t.id === id)?.t;
  if (!t || !map) return;
  map.setView([t.latitude!, t.longitude!], 13);
}

// ── Synchronized cursor across HR-time chart, HR-zones-stream chart, and map ──
// Each time-aligned chart emits `updateAxisPointer` on hover; we
// translate the chart-local x-value into a duration-offset in seconds,
// then mirror that offset onto the other chart + the Leaflet map.

function clampOffset(s: number): number {
  if (!activity.value) return 0;
  return Math.max(0, Math.min(activity.value.duration_s, s));
}

function onHrChartAxisPointer(ev: any) {
  if (dispatching || !activity.value || !hr.value) return;
  const info = ev.axesInfo?.[0];
  if (!info || info.value == null) return;
  const startMs = new Date(activity.value.start_at).getTime();
  cursorOffsetS.value = clampOffset((Number(info.value) - startMs) / 1000);
}

function onStreamChartAxisPointer(ev: any) {
  if (dispatching || !activity.value) return;
  const info = ev.axesInfo?.[0];
  if (!info || info.value == null) return;
  // Stream chart x-axis is category index 0..N-1 mapped to bucket midpoints.
  const N = 50;
  const idx = Math.max(0, Math.min(N - 1, Math.round(Number(info.value))));
  cursorOffsetS.value = clampOffset(((idx + 0.5) / N) * activity.value.duration_s);
}

// When cursor moves, dispatch showTip on the chart(s) that didn't originate
// the event so their tooltip + axisPointer line stays in sync. Skip the
// source chart to avoid re-entrant loops.
watch(cursorOffsetS, (offsetS) => {
  if (offsetS == null || !activity.value) return;
  const startMs = new Date(activity.value.start_at).getTime();

  // HR-over-time chart: find the nearest point in hr.value.points
  if (hr.value && hrChartRef.value && hr.value.points.length > 0) {
    const targetMs = startMs + offsetS * 1000;
    let nearest = 0;
    let nearestDelta = Infinity;
    for (let i = 0; i < hr.value.points.length; i++) {
      const d = Math.abs(new Date(hr.value.points[i].time).getTime() - targetMs);
      if (d < nearestDelta) { nearest = i; nearestDelta = d; }
    }
    dispatching = true;
    try {
      hrChartRef.value.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: nearest });
    } finally { dispatching = false; }
  }

  // Zone-stream chart: bucket index
  if (streamChartRef.value) {
    const N = 50;
    const idx = Math.max(0, Math.min(N - 1, Math.floor((offsetS / activity.value.duration_s) * N)));
    dispatching = true;
    try {
      streamChartRef.value.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: idx });
    } finally { dispatching = false; }
  }

  // Map marker: interpolate position along the polyline. Linear-by-index
  // (assumes uniform GPS sample spacing in time across the activity —
  // imperfect on rest-y rides but a reasonable first cut).
  if (map && polylineCoords.length > 0) {
    const t = offsetS / activity.value.duration_s;
    const fIdx = t * (polylineCoords.length - 1);
    const i0 = Math.floor(fIdx);
    const i1 = Math.min(i0 + 1, polylineCoords.length - 1);
    const frac = fIdx - i0;
    const lat = polylineCoords[i0][0] + frac * (polylineCoords[i1][0] - polylineCoords[i0][0]);
    const lng = polylineCoords[i0][1] + frac * (polylineCoords[i1][1] - polylineCoords[i0][1]);
    if (mapCursor) {
      mapCursor.setLatLng([lat, lng]);
    } else {
      mapCursor = L.circleMarker([lat, lng], {
        radius: 7,
        color: isNeon.value ? "#ffb52e" : "#fbbf24", weight: 3,
        fillColor: isNeon.value ? "#ffb52e" : "#fbbf24", fillOpacity: 0.9,
      }).addTo(map);
    }
  }
});

// Stacked-area streamgraph of the server's per-bucket zone seconds.
// The backend buckets the activity and applies the same 30s gap cap it uses
// for the totals, so this chart and the distribution below always sum to the
// same session rather than telling two stories.
const hrZoneStreamOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const z = zoneData.value;
  if (!z || z.series.length === 0) return null;
  const xs = z.series.map((b) => Math.round(b.minute));
  return {
    grid: { left: 40, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: xs, name: "min", axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "sec", axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: z.zones.map((zone, i) => ({
      name: ZONE_LABELS[i], type: "line", stack: "z",
      areaStyle: { color: ZONE_COLORS.value[i], opacity: 0.7 },
      symbol: "none", smooth: true, lineStyle: { width: 0 },
      data: z.series.map((b) => b[zone.zone] ?? 0),
    })),
  };
});

const hrChartOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr.value || hr.value.points.length === 0 || !activity.value) return null;
  const zones = zoneData.value?.zones ?? [];
  const avg = activity.value.avg_hr;
  return {
    grid: { left: 40, right: 12, top: 8, bottom: 28 },
    xAxis: { type: "time", axisLabel: { ...t.axisLabel, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true },
    tooltip: { trigger: "axis", ...t.tooltip },
    // Colour the line by the SERVER's zone boundaries; no client zone model.
    visualMap: zones.length ? {
      show: false, dimension: 1, seriesIndex: 0,
      pieces: zones.map((z, i) => ({
        gte: z.lo_bpm, ...(z.hi_bpm != null ? { lt: z.hi_bpm + 1 } : {}), color: ZONE_COLORS.value[i],
      })),
      outOfRange: { color: "#28e6ff" },
    } : undefined,
    series: [{
      type: "line", smooth: true, showSymbol: false,
      lineStyle: { width: 2, color: "#28e6ff" },
      data: hr.value.points.map((p) => [p.time, p.value]),
      // Z1-Z5 bands shaded behind the line.
      markArea: zones.length ? {
        silent: true,
        data: zones.map((z, i) => [
          { yAxis: z.lo_bpm, itemStyle: { color: ZONE_COLORS.value[i], opacity: 0.10 } },
          { yAxis: z.hi_bpm ?? 260 },
        ]),
      } : undefined,
      markLine: avg ? {
        silent: true, symbol: "none",
        lineStyle: { color: "#ececf5", type: "dashed", opacity: 0.55 },
        label: { formatter: `avg ${Math.round(avg)}`, color: "#ececf5", position: "insideEndTop" },
        data: [{ yAxis: avg }],
      } : undefined,
    }],
  };
});

// The zone table. Every field here is server-computed: the bpm boundaries,
// the seconds, and the percentage. The client's only contribution is colour.
const zoneBreakdown = computed(() => {
  const z = zoneData.value;
  if (!z || z.total_seconds === 0) return null;
  return z.zones.map((zone, i) => ({
    name: `${zone.zone} ${zone.label}`,
    range: zone.hi_bpm === null ? `${zone.lo_bpm}+ bpm` : `${zone.lo_bpm}–${zone.hi_bpm} bpm`,
    seconds: zone.seconds,
    pct: zone.pct,
    color: ZONE_COLORS.value[i],
  }));
});

function fmtDur(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

// ── Hero + numbers ──
const tintColor = computed(() => categoryColor(categoryForType(activity.value?.type), true));
const heroWhen = computed(() => activity.value
  ? new Date(activity.value.start_at).toLocaleString([], {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  })
  : "");
const isFoot = computed(() => /run|walk|hike/i.test(activity.value?.type ?? ""));
/** m/s from the activity's own distance and time — a unit conversion of
 *  two server numbers, rendered through units.ts like every other pace. */
const speedMs = computed(() => {
  const a = activity.value;
  if (!a || !a.distance_m || a.distance_m <= 0 || a.duration_s <= 0) return null;
  return a.distance_m / a.duration_s;
});
interface Big { label: string; value: string; unit: string | null }
const bigs = computed<Big[]>(() => {
  const a = activity.value;
  if (!a) return [];
  const out: Big[] = [];
  if (a.distance_m && a.distance_m > 0) out.push({ label: "Distance", value: (distanceVal(a.distance_m) ?? 0).toFixed(2), unit: distanceUnit.value });
  out.push({ label: "Time", value: fmtDur(a.duration_s), unit: null });
  if (isFoot.value && speedMs.value) {
    const [v, u] = fmtPace(speedMs.value).split(" ");
    out.push({ label: "Pace", value: v ?? "—", unit: u ?? null });
  } else if (a.avg_hr) out.push({ label: "Avg HR", value: String(Math.round(a.avg_hr)), unit: "bpm" });
  if (out.length < 3 && a.kcal) out.push({ label: "Energy", value: String(Math.round(a.kcal)), unit: "kcal" });
  return out.slice(0, 3);
});
const quiet = computed(() => {
  const a = activity.value;
  if (!a) return [];
  const bigLabels = new Set(bigs.value.map((b) => b.label));
  const topLo = zoneData.value?.zones.at(-1)?.lo_bpm ?? null;
  const out: { label: string; value: string; amber?: boolean }[] = [];
  if (a.elevation_gain_m != null) out.push({ label: "Climb", value: fmtElevation(a.elevation_gain_m) });
  if (!bigLabels.has("Avg HR") && a.avg_hr) out.push({ label: "Avg HR", value: `${Math.round(a.avg_hr)} bpm` });
  // Max HR is not a warning: Ink, or Amber when it reached the top zone.
  if (a.max_hr) out.push({ label: "Max HR", value: `${Math.round(a.max_hr)} bpm`, amber: topLo != null && a.max_hr >= topLo });
  if (!isFoot.value && speedMs.value) {
    out.push({ label: "Speed", value: `${(distanceVal(speedMs.value * 3600) ?? 0).toFixed(1)} ${distanceUnit.value}/h` });
  }
  if (a.avg_power_w) out.push({ label: "Power", value: `${Math.round(a.avg_power_w)} W` });
  if (!bigLabels.has("Energy") && a.kcal) out.push({ label: "Energy", value: `${Math.round(a.kcal)} kcal` });
  if (a.suffer_score) out.push({ label: "Suffer", value: String(Math.round(a.suffer_score)) });
  return out.slice(0, 6);
});

async function saveNotes() {
  if (!activity.value) return;
  savingNotes.value = true;
  savedFlag.value = false;
  try {
    await api.updateActivityNotes(activity.value.source, activity.value.source_id, {
      notes: notesInput.value.trim() || null,
      tags: tags.value.length > 0 ? tags.value : null,
    });
    savedFlag.value = true;
    setTimeout(() => { savedFlag.value = false; }, 2000);
  } catch (e) {
    notice.value = `Couldn't save notes: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    savingNotes.value = false;
  }
}

function addTag() {
  const t = tagInput.value.trim().toLowerCase();
  if (!t) return;
  if (tags.value.includes(t)) { tagInput.value = ""; return; }
  tags.value.push(t);
  tagInput.value = "";
}

function removeTag(t: string) {
  tags.value = tags.value.filter((x) => x !== t);
}

// Trail linking
const trails = ref<Awaited<ReturnType<typeof api.trails>>["trails"]>([]);
const trailSelection = ref<number | "" >("");
const linkingTrail = ref(false);
const linkedFlag = ref(false);

async function loadTrails() {
  try {
    const r = await api.trails();
    trails.value = r.trails;
    trailSelection.value = activity.value?.trail_id ?? "";
  } catch { trails.value = []; }
}

async function applyTrailLink() {
  if (!activity.value) return;
  linkingTrail.value = true;
  linkedFlag.value = false;
  try {
    const tid = trailSelection.value === "" ? null : Number(trailSelection.value);
    await api.linkActivityToTrail(activity.value.source, activity.value.source_id, tid);
    // Update local view of the activity
    if (activity.value) {
      activity.value.trail_id = tid;
      activity.value.trail_name = tid === null ? null
        : trails.value.find((x) => x.id === tid)?.name ?? null;
    }
    linkedFlag.value = true;
    setTimeout(() => { linkedFlag.value = false; }, 2000);
  } catch (e) {
    notice.value = `Couldn't change the trail link: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    linkingTrail.value = false;
  }
}

// Edit dialog for manual activities. Server-side guard restricts the
// PATCH to source=manual rows so imported activities stay locked.
const showEdit = ref(false);
const editName = ref("");
const editDuration = ref(30);
const editEndedAt = ref("");
const editing = ref(false);
function localHHMM(d: Date): string {
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}
// Type correction — any source (migration 0069). A watch guesses the
// activity, and it guesses wrong: mowing arrived as "cycling". The server
// keeps what the device said in `recorded_type`, so this can always be
// undone, and a re-sync does not put the guess back.
const showTypeEdit = ref(false);
const typeChoices = ref<Array<{ type: string; label: string }>>([]);
const pickedType = ref("");
const savingType = ref(false);
const typeError = ref<string | null>(null);

function typeLabel(t: string | null | undefined): string {
  if (!t) return "";
  return typeChoices.value.find((c) => c.type === t)?.label ?? fmtActivityType(t);
}

async function openTypeEdit() {
  if (!activity.value) return;
  typeError.value = null;
  pickedType.value = activity.value.type;
  showTypeEdit.value = true;
  if (!typeChoices.value.length) {
    try { typeChoices.value = await api.activityTypeChoices(); }
    catch (e) { typeError.value = e instanceof Error ? e.message : "could not load types"; }
  }
}

async function saveType(body: { type?: string; reset_type?: boolean }) {
  if (!activity.value) return;
  savingType.value = true;
  typeError.value = null;
  try {
    activity.value = await api.editActivity(activity.value.source, activity.value.source_id, body);
    showTypeEdit.value = false;
  } catch (e) {
    typeError.value = e instanceof Error ? e.message : "could not save";
    if (!showTypeEdit.value) notice.value = `Couldn't change the type: ${typeError.value}`;
  } finally {
    savingType.value = false;
  }
}

function openEdit() {
  if (!activity.value) return;
  editName.value = activity.value.name ?? "";
  editDuration.value = Math.max(1, Math.round(activity.value.duration_s / 60));
  const start = new Date(activity.value.start_at);
  const end = new Date(start.getTime() + activity.value.duration_s * 1000);
  editEndedAt.value = localHHMM(end);
  showEdit.value = true;
}
function editedEndedAtIso(): string {
  // Anchor the picked HH:MM to the activity's original calendar date,
  // not "today" — editing a 3-day-old entry shouldn't yank it to today.
  const startDate = new Date(activity.value!.start_at);
  const [hh, mm] = editEndedAt.value.split(":").map(Number);
  const d = new Date(startDate);
  d.setHours(hh, mm, 0, 0);
  return d.toISOString();
}
async function submitEdit() {
  if (!activity.value) return;
  const name = editName.value.trim();
  const mins = Number(editDuration.value);
  if (!name || !mins || mins <= 0 || mins > 1440) return;
  editing.value = true;
  try {
    const endedMs = new Date(editedEndedAtIso()).getTime();
    const startIso = new Date(endedMs - mins * 60_000).toISOString();
    const updated = await api.editActivity(
      activity.value.source, activity.value.source_id,
      { name, duration_minutes: mins, start_at: startIso },
    );
    activity.value = updated;
    showEdit.value = false;
    notice.value = null;
  } catch (e) {
    // Inline — this used to set the page error and hide the activity.
    notice.value = `Edit failed: ${e instanceof Error ? e.message : String(e)}`;
    showEdit.value = false;
  } finally {
    editing.value = false;
  }
}
</script>

<template>
  <NeonPage title="Activity" back="/activities">
    <template #trailing>
      <div v-if="activity" class="hdr-actions">
        <button class="icon-btn" title="Change activity type" aria-label="Change activity type" @click="openTypeEdit">✎</button>
        <button v-if="activity.source === 'manual'" class="pill-btn" @click="openEdit">Edit</button>
      </div>
    </template>

    <div v-if="notice" class="stale" role="alert" @click="notice = null">
      <strong>{{ notice }}</strong><em>Dismiss</em>
    </div>

    <template v-if="!activity">
      <div v-if="loading" class="hero-map placeholder"><span>Loading activity…</span></div>
      <div v-else-if="error" class="stale" role="alert" @click="load">
        <strong>Couldn't load this activity</strong><span>{{ error }}</span><em>Tap to retry</em>
      </div>
      <p v-else class="muted">Not found.</p>
    </template>

    <template v-else>
      <div v-if="error" class="stale" role="alert" @click="load">
        <strong>Couldn't refresh — showing the saved copy</strong><span>{{ error }}</span><em>Tap to retry</em>
      </div>

      <!-- Map first. No route → a category-tinted card in the same place. -->
      <section v-if="activity.polyline" class="hero-map">
        <div ref="mapEl" class="map"></div>
        <div class="scrim" aria-hidden="true"></div>
        <div class="caption">
          <button class="type" title="Change activity type" @click="openTypeEdit">{{ typeLabel(activity.type) }}</button>
          <h2>{{ activity.name || typeLabel(activity.type) }}</h2>
          <p>{{ heroWhen }}</p>
        </div>
      </section>
      <section v-else class="hero-map no-route"
               :style="{ background: `linear-gradient(135deg, ${tintColor}60, #1e2230 55%, #181b27)`, borderColor: tintColor + '4d' }">
        <span class="big-ic" :style="{ color: tintColor }"><ActivityIcon :type="activity.type" :size="56" /></span>
        <div class="caption">
          <button class="type" title="Change activity type" @click="openTypeEdit">{{ typeLabel(activity.type) }}</button>
          <h2>{{ activity.name || typeLabel(activity.type) }}</h2>
          <p>{{ heroWhen }}</p>
        </div>
      </section>

      <div v-if="activity.polyline" class="map-toolbar">
        <button class="chip" :class="{ on: mapMode === 'line' }" @click="mapMode = 'line'">Line</button>
        <button class="chip" :class="{ on: mapMode === 'heatmap' }" :disabled="!hr || hr.points.length === 0"
                :title="!hr || hr.points.length === 0 ? 'No HR data for this activity' : 'Color the route by HR zone'"
                @click="mapMode = 'heatmap'">HR heatmap</button>
        <button v-if="nearbyTrails.length" class="chip" :class="{ on: trailLayerOpen }"
                @click="trailLayerOpen = !trailLayerOpen">Trails ({{ nearbyTrails.length }})</button>
      </div>
      <div v-if="trailLayerOpen && nearbyTrails.length" class="card trail-legend">
        <p class="hint">Nearby trails — click to pan, checkbox to hide</p>
        <ul>
          <li v-for="{ t, mi } in nearbyTrails" :key="t.id">
            <input type="checkbox" :checked="!hiddenTrailIds.has(t.id)" @change="toggleTrail(t.id)" />
            <span class="dot" :style="`background:${TRAIL_STATUS_COLOR[t.status ?? 'unknown']}`" />
            <button class="trail-name" @click="panToTrail(t.id)">{{ t.name }}</button>
            <span class="trail-meta">{{ t.status ?? 'unknown' }} · {{ mi.toFixed(1) }} mi</span>
          </li>
        </ul>
      </div>

      <p v-if="activity.recorded_type" class="recorded">
        Recorded as {{ typeLabel(activity.recorded_type) }} ·
        <button class="link" :disabled="savingType" @click="saveType({ reset_type: true })">Undo</button>
      </p>

      <div class="bigs">
        <div v-for="b in bigs" :key="b.label">
          <div class="big-v">{{ b.value }}<small v-if="b.unit">{{ b.unit }}</small></div>
          <div class="big-l">{{ b.label }}</div>
        </div>
      </div>
      <div v-if="quiet.length" class="card quiet">
        <div v-for="q in quiet" :key="q.label">
          <div class="q-v" :class="{ amber: q.amber }">{{ q.value }}</div>
          <div class="q-l">{{ q.label }}</div>
        </div>
      </div>

      <section v-if="!activity.polyline && activity.source === 'healthconnect'" class="card">
        <NeonEyebrow style="margin-top: 0">Route</NeonEyebrow>
        <!-- SA-P3: three different states — withheld, none, never asked. -->
        <p class="route-empty">{{ routeEmptyText }}</p>
        <p v-if="activity.route_state !== 'none'" class="hint">
          Open this activity in the phone app and tap <strong>Fetch route from Health Connect</strong>.
          Health Connect releases routes one session at a time unless <em>Exercise routes</em> is on for
          myvitals in Health Connect → App permissions; a browser has no path to the data.
        </p>
      </section>

      <section class="card">
        <NeonEyebrow style="margin-top: 0">Heart rate</NeonEyebrow>
        <div class="chart">
          <VChart v-if="hrChartOption" ref="hrChartRef" :option="hrChartOption" autoresize @updateAxisPointer="onHrChartAxisPointer" />
          <p v-else class="muted">No heart-rate samples for this activity.</p>
        </div>
      </section>

      <section v-if="zoneBreakdown" class="card">
        <NeonEyebrow style="margin-top: 0">Time in zone</NeonEyebrow>
        <div class="zbar" role="img" :aria-label="zoneBreakdown.map((z) => `${z.name} ${z.pct.toFixed(0)}%`).join(', ')">
          <span v-for="z in zoneBreakdown" :key="z.name" :style="{ width: z.pct + '%', background: z.color }" />
        </div>
        <div v-for="z in zoneBreakdown" :key="z.name" class="zrow">
          <i :style="{ background: z.color }" />
          <span class="zn">{{ z.name }}</span>
          <span class="zr">{{ z.range }}</span>
          <span class="zt">{{ fmtDur(z.seconds) }}</span>
          <span class="zp">{{ z.pct.toFixed(0) }}%</span>
        </div>
        <p v-if="zoneData && !zoneData.sampled" class="hint">
          No heart-rate series was recorded, so the whole duration is attributed to the zone its
          average falls in. Treat the split as coarse.
        </p>
        <p v-if="maxHrNote" class="hint">{{ maxHrNote }}</p>
      </section>

      <section v-if="hrZoneStreamOption" class="card">
        <NeonEyebrow style="margin-top: 0">Zones over time</NeonEyebrow>
        <div class="chart"><VChart ref="streamChartRef" :option="hrZoneStreamOption" autoresize @updateAxisPointer="onStreamChartAxisPointer" /></div>
      </section>

      <section class="card">
        <NeonEyebrow style="margin-top: 0">Trail</NeonEyebrow>
        <p class="hint" v-if="activity.trail_name">Linked to <strong>{{ activity.trail_name }}</strong>
          <RouterLink to="/trails" class="link-a">· view trails</RouterLink></p>
        <p class="hint" v-else>Not linked to a trail yet.</p>
        <div class="trail-pick">
          <select v-model="trailSelection" class="field-in" aria-label="Trail">
            <option value="">— None —</option>
            <option v-for="t in trails" :key="t.id" :value="t.id">{{ t.name }}{{ t.city ? ` (${t.city})` : '' }}</option>
          </select>
          <button class="primary" :disabled="linkingTrail" @click="applyTrailLink">{{ linkingTrail ? "Saving…" : "Update" }}</button>
          <span v-if="linkedFlag" class="saved">saved</span>
        </div>
      </section>

      <section class="card">
        <NeonEyebrow style="margin-top: 0">Notes & tags</NeonEyebrow>
        <div class="tag-row">
          <span v-for="t in tags" :key="t" class="tag-chip">{{ t }}
            <button class="tag-x" type="button" :aria-label="`Remove tag ${t}`" @click="removeTag(t)">×</button>
          </span>
          <input v-model="tagInput" class="field-in tag-input" placeholder="add tag (Enter)"
                 @keydown.enter.prevent="addTag" @keydown.comma.prevent="addTag" />
        </div>
        <textarea v-model="notesInput" class="field-in notes" rows="4" placeholder="Felt strong, tail wind on the climb, etc." />
        <div class="notes-actions">
          <button class="primary" :disabled="savingNotes" @click="saveNotes">{{ savingNotes ? "Saving…" : "Save" }}</button>
          <span v-if="savedFlag" class="saved">saved</span>
        </div>
      </section>

      <!-- Type correction (any source) -->
      <div v-if="showTypeEdit" class="modal-backdrop" @click.self="showTypeEdit = false">
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="type-edit-title" @keydown.esc="showTypeEdit = false">
          <h3 id="type-edit-title">What was this?</h3>
          <p class="hint">Watches guess the activity type. Pick what it really was — stats, icons and training
            load follow. A re-sync won't change it back.</p>
          <p v-if="typeError" class="warn">{{ typeError }}</p>
          <div class="type-grid">
            <button v-for="c in typeChoices" :key="c.type" :class="['type-choice', { on: pickedType === c.type }]"
                    :aria-pressed="pickedType === c.type" @click="pickedType = c.type">{{ c.label }}</button>
          </div>
          <div class="modal-actions">
            <button class="ghost" :disabled="savingType" @click="showTypeEdit = false">Cancel</button>
            <button class="primary" :disabled="savingType || !pickedType || pickedType === activity.type"
                    @click="saveType({ type: pickedType })">{{ savingType ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>
      </div>

      <!-- Edit dialog (manual activities only) -->
      <div v-if="showEdit" class="modal-backdrop" @click.self="showEdit = false">
        <div class="modal" role="dialog" aria-modal="true">
          <h3>Edit activity</h3>
          <p class="hint">Adjust name, duration, or end time. Avg/max HR will be re-scanned over the new window.</p>
          <label class="field"><span>Name</span><input v-model="editName" class="field-in" type="text" maxlength="120" :disabled="editing" /></label>
          <label class="field"><span>Duration (minutes)</span><input v-model.number="editDuration" class="field-in" type="number" min="1" max="1440" :disabled="editing" /></label>
          <label class="field"><span>Ended at</span><input v-model="editEndedAt" class="field-in" type="time" :disabled="editing" />
            <small class="hint">Anchored to {{ fmtDateTime(activity.start_at).split(',')[0] }} — change if you mis-timed it.</small></label>
          <div class="modal-actions">
            <button class="ghost" :disabled="editing" @click="showEdit = false">Cancel</button>
            <button class="primary" :disabled="editing || !editName.trim() || !editDuration || editDuration <= 0"
                    @click="submitEdit">{{ editing ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>
      </div>
    </template>
  </NeonPage>
</template>

<style scoped>
.hdr-actions { display: flex; gap: 8px; align-items: center; }
.icon-btn { width: 42px; height: 42px; border-radius: 50%; background: rgba(40, 230, 255, .14);
  border: 1px solid rgba(40, 230, 255, .45); color: var(--rn-cyan); font-size: 16px; cursor: pointer; }
.pill-btn { min-height: 40px; padding: 0 16px; border-radius: 999px; background: rgba(40, 230, 255, .14);
  border: 1px solid rgba(40, 230, 255, .45); color: var(--rn-cyan); font: inherit; font-weight: 700; cursor: pointer; }

.stale { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; margin-bottom: 12px; border-radius: 14px;
  background: rgba(255, 181, 46, .10); border: 1px solid rgba(255, 181, 46, .32); cursor: pointer; }
.stale strong { color: var(--rn-amber); font-size: 13px; }
.stale span { color: var(--rn-mut); font-size: 12px; }
.stale em { color: var(--rn-cyan); font-size: 12px; font-style: normal; font-weight: 600; }
.muted { color: var(--rn-mut); font-size: 13px; }
.hint { color: var(--rn-mut); font-size: 12px; margin: 6px 0 0; }
.warn { color: var(--rn-amber); font-size: 12px; }

.hero-map { position: relative; height: 300px; border-radius: 24px; overflow: hidden; margin-bottom: 12px;
  border: 1px solid rgba(40, 230, 255, .22); background: var(--rn-card); }
.hero-map.placeholder { display: flex; align-items: center; justify-content: center; color: var(--rn-mut); font-size: 13px; }
.hero-map.no-route { height: 190px; border: 1px solid; }
.map { position: absolute; inset: 0; z-index: 0; }
.scrim { position: absolute; left: 0; right: 0; bottom: 0; height: 140px; z-index: 400; pointer-events: none;
  background: linear-gradient(transparent, rgba(15, 17, 24, .92)); }
.caption { position: absolute; left: 16px; right: 16px; bottom: 14px; z-index: 401; }
.caption .type { background: none; border: 0; padding: 0; cursor: pointer; color: var(--rn-cyan);
  font-family: 'Space Grotesk', monospace; font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.caption h2 { margin: 2px 0; font-size: 24px; font-weight: 800; line-height: 1.15; color: var(--rn-ink); }
.caption p { margin: 0; font-size: 13px; color: rgba(236, 236, 245, .8); }
.big-ic { position: absolute; top: 18px; right: 18px; opacity: .6; }
.map-toolbar { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.chip { min-height: 32px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--rn-line); background: var(--rn-card);
  color: var(--rn-mut); font: inherit; font-size: 12px; cursor: pointer; }
.chip.on { background: rgba(40, 230, 255, .14); border-color: rgba(40, 230, 255, .45); color: var(--rn-cyan); font-weight: 700; }
.chip:disabled { opacity: .45; cursor: default; }
.recorded { color: var(--rn-mut); font-size: 12px; margin: 0 0 8px; }
.link { background: none; border: 0; padding: 0; color: var(--rn-cyan); cursor: pointer; font: inherit; font-weight: 600; }
.link-a { color: var(--rn-cyan); text-decoration: none; }

.bigs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 4px 0 14px; }
.big-v { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 30px; letter-spacing: -.5px; line-height: 1.1; }
.big-v small { color: var(--rn-mut); font-size: 12px; margin-left: 3px; font-weight: 500; }
.big-l, .q-l { font-family: 'Space Grotesk', monospace; font-size: 10px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--rn-mut); }
.card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; margin-bottom: 12px; }
.quiet { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.q-v { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 15px; }
.q-v.amber { color: var(--rn-amber); }
.route-empty { margin: 0; line-height: 1.5; }

.chart { width: 100%; height: 240px; }
.chart > * { width: 100%; height: 100%; }
.zbar { display: flex; height: 14px; border-radius: 7px; overflow: hidden; background: var(--rn-track); margin-bottom: 10px; }
.zbar span { height: 100%; }
.zrow { display: grid; grid-template-columns: 10px 1fr auto 56px 42px; align-items: center; gap: 8px; padding: 3px 0; font-size: 13px; }
.zrow i { width: 10px; height: 10px; border-radius: 3px; }
.zr, .zp { color: var(--rn-mut); font-size: 11px; font-family: 'Space Grotesk', monospace; text-align: right; }
.zt { font-family: 'Space Grotesk', monospace; text-align: right; }

.trail-legend ul { list-style: none; margin: 6px 0 0; padding: 0; }
.trail-legend li { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 13px; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
.trail-name { background: none; border: 0; padding: 0; color: var(--rn-cyan); cursor: pointer; font: inherit; text-align: left; }
.trail-meta { margin-left: auto; color: var(--rn-mut); font-size: 11px; }
.trail-pick { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.field-in { background: var(--rn-bg); border: 1px solid var(--rn-line); color: var(--rn-ink); border-radius: 10px;
  padding: 8px 10px; font: inherit; font-size: 14px; }
select.field-in { flex: 1; min-width: 12rem; }
.notes { width: 100%; box-sizing: border-box; resize: vertical; margin-top: 8px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tag-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 999px;
  background: rgba(111, 123, 255, .14); border: 1px solid rgba(111, 123, 255, .4); font-size: 12px; }
.tag-x { background: none; border: 0; color: var(--rn-mut); cursor: pointer; font-size: 16px; line-height: 1; padding: 0 2px; }
.tag-input { border-radius: 999px; padding: 4px 12px; font-size: 12px; min-width: 120px; }
.notes-actions { display: flex; gap: 10px; align-items: center; margin-top: 8px; }
.primary { background: var(--rn-cyan); color: var(--rn-onacc); border: 0; border-radius: 10px; padding: 8px 16px;
  font: inherit; font-weight: 700; cursor: pointer; }
.primary:disabled { opacity: .5; cursor: default; }
.ghost { background: transparent; color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 10px; padding: 8px 16px; font: inherit; cursor: pointer; }
.saved { color: var(--rn-lime); font-size: 13px; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, .6); display: flex; align-items: center;
  justify-content: center; z-index: 1000; padding: 16px; }
.modal { background: var(--rn-high); border: 1px solid var(--rn-line); border-radius: 18px; padding: 18px; max-width: 440px; width: 100%; }
.modal h3 { margin: 0 0 6px; }
.field { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; }
.field > span { font-size: 12px; color: var(--rn-mut); }
.type-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr)); gap: 6px; margin: 10px 0; }
.type-choice { min-height: 44px; border-radius: 10px; border: 1px solid var(--rn-line); background: none; color: inherit; font: inherit; cursor: pointer; }
.type-choice.on { border-color: rgba(40, 230, 255, .55); background: rgba(40, 230, 255, .12); font-weight: 700; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }

:deep(.start-marker > div) { width: 14px; height: 14px; border-radius: 50%; background: #5dff3b; border: 2px solid white; box-shadow: 0 0 8px rgba(93, 255, 59, .7); }
:deep(.end-marker > div) { width: 14px; height: 14px; border-radius: 50%; background: #ececf5; border: 2px solid #0f1118; box-shadow: 0 0 6px rgba(0, 0, 0, .5); }
</style>
