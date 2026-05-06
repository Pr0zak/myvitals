<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import VChart from "vue-echarts";
import polylineDecoder from "@mapbox/polyline";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { Activity, HeartRateSeries } from "@/api/types";
import { chartTheme, effectiveTheme } from "@/theme";
import { fmtDistance, fmtElevation, distanceVal, distanceUnit, isImperial } from "@/units";
import { fmtDateTime } from "@/format";

const route = useRoute();
const router = useRouter();
const activity = ref<Activity | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let polylineLayer: L.Polyline | null = null;

// Notes & tags state
const notesInput = ref("");
const tagInput = ref("");
const savingNotes = ref(false);
const savedFlag = ref(false);
const tags = ref<string[]>([]);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const a = await api.activity(route.params.source as string, route.params.id as string);
    activity.value = a;
    notesInput.value = a.notes ?? "";
    tags.value = a.tags ?? [];
    // Pull HR for the activity window plus a bit of padding
    const start = new Date(a.start_at);
    const end = new Date(start.getTime() + a.duration_s * 1000);
    hr.value = await api.heartRate({
      since: new Date(start.getTime() - 5 * 60 * 1000),
      until: new Date(end.getTime() + 5 * 60 * 1000),
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

function renderMap() {
  if (!mapEl.value || !activity.value || !activity.value.polyline) return;
  if (map) { map.remove(); map = null; }

  const coords = polylineDecoder.decode(activity.value.polyline) as [number, number][];
  if (coords.length === 0) return;

  map = L.map(mapEl.value, { zoomControl: true });
  const tiles = effectiveTheme.value === "dark"
    ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
  L.tileLayer(tiles, {
    attribution: "© OpenStreetMap, © CARTO",
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  polylineLayer = L.polyline(coords, { color: "#38bdf8", weight: 3 }).addTo(map);

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
          radius: 4, color: "#ffffff", weight: 1, fillColor: "#0ea5e9", fillOpacity: 1,
        }).addTo(map).bindTooltip(`${nextMark} ${distanceUnit.value}`, { permanent: false, direction: "top" });
        nextMark += stepUnits;
      }
    }
  }

  map.fitBounds(polylineLayer.getBounds(), { padding: [20, 20] });
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
watch(effectiveTheme, () => setTimeout(renderMap, 50));

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
});

// Profile-driven max HR for zone bucketing (fallback 220 - 30 = 190 if unset).
const maxHr = ref<number>(190);
async function loadMaxHr() {
  try {
    const p = await api.getProfile();
    if (p.derived?.max_hr_estimated) maxHr.value = p.derived.max_hr_estimated;
  } catch { /* ignore */ }
}
onMounted(loadMaxHr);

const ZONE_COLORS = ["#38bdf8", "#22c55e", "#eab308", "#f97316", "#ef4444"];
const ZONE_LABELS = ["Z1 Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold", "Z5 VO2"];

function zoneFor(bpm: number): number {
  // 1-indexed Z1..Z5; clamp at 1 below 50% and 5 above 100%.
  const pct = bpm / maxHr.value;
  if (pct < 0.60) return 1;
  if (pct < 0.70) return 2;
  if (pct < 0.80) return 3;
  if (pct < 0.90) return 4;
  return 5;
}

// Stacked-area streamgraph: time spent in each zone over the activity,
// bucketed into ~50 buckets across the duration so the curves smooth out.
const hrZoneStreamOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr.value || hr.value.points.length < 5 || !activity.value) return null;
  const start = new Date(activity.value.start_at).getTime();
  const dur = activity.value.duration_s * 1000;
  const N = 50;
  const buckets: number[][] = Array.from({ length: 5 }, () => Array(N).fill(0));
  for (const p of hr.value.points) {
    const t_ms = new Date(p.time).getTime();
    const idx = Math.max(0, Math.min(N - 1, Math.floor(((t_ms - start) / dur) * N)));
    const z = zoneFor(p.value) - 1;  // 0-indexed
    buckets[z][idx] += 1;
  }
  const xs = Array.from({ length: N }, (_, i) =>
    Math.round((i / N) * activity.value!.duration_s / 60));
  return {
    grid: { left: 40, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: xs, name: "min", axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "samples", axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: buckets.map((data, i) => ({
      name: ZONE_LABELS[i], type: "line", stack: "z", areaStyle: { color: ZONE_COLORS[i], opacity: 0.7 },
      symbol: "none", smooth: true, lineStyle: { width: 0 }, data,
    })),
  };
});

// Pie of total time in zone — quick "polarized vs sweet-spot" read.
const hrZonePieOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr.value || hr.value.points.length < 5) return null;
  const counts = [0, 0, 0, 0, 0];
  for (const p of hr.value.points) counts[zoneFor(p.value) - 1] += 1;
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  return {
    tooltip: { ...t.tooltip, formatter: (p: any) =>
      `${p.name}: ${p.value} samples (${(p.value / total * 100).toFixed(0)}%)` },
    series: [{
      type: "pie", radius: ["45%", "75%"],
      label: { color: t.axisLabel.color, formatter: "{b}\n{d}%" },
      data: counts.map((v, i) => ({
        value: v, name: ZONE_LABELS[i], itemStyle: { color: ZONE_COLORS[i] },
      })),
    }],
  };
});

const hrChartOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!hr.value || hr.value.points.length === 0 || !activity.value) return null;
  const start = new Date(activity.value.start_at).getTime();
  const end = start + activity.value.duration_s * 1000;
  return {
    grid: { left: 40, right: 12, top: 8, bottom: 28 },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "line", smooth: true, showSymbol: false,
      lineStyle: { color: t.palette.hr, width: 1.5 },
      areaStyle: { color: `${t.palette.hr}22` },
      data: hr.value.points.map((p) => [p.time, p.value]),
      markArea: {
        silent: true,
        itemStyle: { color: t.palette.activity },
        data: [[{ xAxis: new Date(start).toISOString() }, { xAxis: new Date(end).toISOString() }]],
      },
    }],
  };
});

// HR zones (basic Karvonen-ish breakdown using max HR estimate)
const zoneBreakdown = computed(() => {
  if (!activity.value || !hr.value) return null;
  const maxHr = activity.value.max_hr ?? 190;
  const zones = [
    { name: "Z1 (rest)", lo: 0, hi: 0.6 * maxHr, color: "#94a3b8" },
    { name: "Z2 (fat burn)", lo: 0.6 * maxHr, hi: 0.7 * maxHr, color: "#22c55e" },
    { name: "Z3 (aerobic)", lo: 0.7 * maxHr, hi: 0.8 * maxHr, color: "#38bdf8" },
    { name: "Z4 (threshold)", lo: 0.8 * maxHr, hi: 0.9 * maxHr, color: "#eab308" },
    { name: "Z5 (anaerobic)", lo: 0.9 * maxHr, hi: 999, color: "#ef4444" },
  ];
  const start = new Date(activity.value.start_at).getTime();
  const end = start + activity.value.duration_s * 1000;
  const inWindow = hr.value.points.filter((p) => {
    const t = new Date(p.time).getTime();
    return t >= start && t <= end;
  });
  return zones.map((z) => ({
    ...z,
    count: inWindow.filter((p) => p.value >= z.lo && p.value < z.hi).length,
    pct: inWindow.length === 0 ? 0 : 100 * inWindow.filter((p) => p.value >= z.lo && p.value < z.hi).length / inWindow.length,
  }));
});

function fmtDur(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function fmtKm(m: number | null): string {
  return fmtDistance(m, 2);
}

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
</script>

<template>
  <div class="detail">
    <button class="back" @click="router.push('/activities')">← Back to activities</button>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>

    <div v-else-if="activity">
      <header class="head">
        <div>
          <h1>{{ activity.name ?? "(untitled)" }}</h1>
          <p class="meta">
            <span class="type">{{ activity.type }}</span>
            ·
            {{ fmtDateTime(activity.start_at) }}
            ·
            {{ fmtDur(activity.duration_s) }}
          </p>
        </div>
      </header>

      <div class="grid">
        <Card title="Stats">
          <dl class="kv">
            <div><dt>Distance</dt><dd>{{ fmtKm(activity.distance_m) }}</dd></div>
            <div v-if="activity.elevation_gain_m !== null"><dt>Elevation</dt><dd>{{ fmtElevation(activity.elevation_gain_m) }}</dd></div>
            <div v-if="activity.avg_hr"><dt>Avg HR</dt><dd>{{ Math.round(activity.avg_hr) }} bpm</dd></div>
            <div v-if="activity.max_hr"><dt>Max HR</dt><dd>{{ Math.round(activity.max_hr) }} bpm</dd></div>
            <div v-if="activity.avg_power_w"><dt>Avg power</dt><dd>{{ Math.round(activity.avg_power_w) }} W</dd></div>
            <div v-if="activity.max_power_w"><dt>Max power</dt><dd>{{ Math.round(activity.max_power_w) }} W</dd></div>
            <div v-if="activity.kcal"><dt>Calories</dt><dd>{{ Math.round(activity.kcal) }} kcal</dd></div>
            <div v-if="activity.suffer_score"><dt>Suffer</dt><dd>{{ Math.round(activity.suffer_score) }}</dd></div>
          </dl>
        </Card>

        <Card v-if="activity.polyline" title="Route">
          <div ref="mapEl" class="map"></div>
        </Card>

        <Card v-if="hrZoneStreamOption" title="HR zones over time">
          <div class="chart"><VChart :option="hrZoneStreamOption" autoresize/></div>
        </Card>

        <Card v-if="hrZonePieOption" title="HR zone distribution">
          <div class="chart" style="height: 240px;"><VChart :option="hrZonePieOption" autoresize/></div>
        </Card>

        <Card title="Heart rate during activity">
          <div class="chart">
            <VChart v-if="hrChartOption" :option="hrChartOption" autoresize/>
            <div v-else class="empty">No HR data captured during this window</div>
          </div>
        </Card>

        <Card v-if="zoneBreakdown" title="HR zones">
          <div class="zones">
            <div v-for="z in zoneBreakdown" :key="z.name" class="zone">
              <div class="zone-label">{{ z.name }}</div>
              <div class="zone-bar"><div class="zone-fill" :style="{ width: z.pct + '%', background: z.color }"></div></div>
              <div class="zone-pct">{{ z.pct.toFixed(0) }}%</div>
            </div>
          </div>
        </Card>

        <Card title="Notes & tags">
          <div class="tag-row">
            <span v-for="t in tags" :key="t" class="tag-chip">
              {{ t }}
              <button class="tag-x" @click="removeTag(t)" type="button">×</button>
            </span>
            <input
              v-model="tagInput"
              @keydown.enter.prevent="addTag"
              @keydown.comma.prevent="addTag"
              placeholder="add tag (Enter)"
              class="tag-input"
            />
          </div>
          <textarea
            v-model="notesInput"
            placeholder="Felt strong, tail wind on the climb, etc."
            class="notes-area"
            rows="4"
          />
          <div class="notes-actions">
            <button class="primary" :disabled="savingNotes" @click="saveNotes">
              {{ savingNotes ? "Saving…" : "Save" }}
            </button>
            <span v-if="savedFlag" class="saved">saved</span>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.back {
  background: transparent; color: var(--accent); border: 0; cursor: pointer;
  padding: 0.4rem 0; font-size: 0.9rem; margin-bottom: 0.5rem;
}
.head { margin-bottom: 1rem; }
.head h1 { margin: 0; }
.meta { margin: 0.3rem 0 0; color: var(--muted); font-size: 0.9rem; }
.type { color: var(--accent); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.75rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1rem; }

.kv { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.4rem 1rem; margin: 0; }
.kv > div { display: flex; flex-direction: column; }
dt { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
dd { margin: 0.1rem 0 0; color: var(--text); font-weight: 500; }

.map { height: 360px; width: 100%; border-radius: 6px; }
:deep(.start-marker > div) { width: 14px; height: 14px; border-radius: 50%; background: #22c55e; border: 2px solid white; box-shadow: 0 0 6px rgba(0,0,0,0.5); }
:deep(.end-marker > div)   { width: 14px; height: 14px; border-radius: 50%; background: #ef4444; border: 2px solid white; box-shadow: 0 0 6px rgba(0,0,0,0.5); }

.chart { width: 100%; height: 260px; }
.chart > * { width: 100%; height: 100%; }

.zones { display: flex; flex-direction: column; gap: 0.4rem; }
.zone { display: grid; grid-template-columns: 110px 1fr 50px; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: var(--muted); }
.zone-label { color: var(--text); }
.zone-bar { height: 12px; background: var(--surface-2); border-radius: 6px; overflow: hidden; }
.zone-fill { height: 100%; transition: width 0.3s; }
.zone-pct { text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }

.tag-row { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.6rem; }
.tag-chip {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 100px; padding: 0.15rem 0.6rem; font-size: 0.8rem;
  display: inline-flex; align-items: center; gap: 0.3rem;
}
.tag-x { background: transparent; color: var(--muted-2); border: 0; cursor: pointer; padding: 0; font-size: 1rem; line-height: 1; }
.tag-x:hover { color: var(--bad); }
.tag-input {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 100px; padding: 0.2rem 0.7rem; font-size: 0.8rem; min-width: 120px; font-family: inherit;
}
.notes-area {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.5rem 0.7rem; width: 100%; font-family: inherit;
  font-size: 0.9rem; resize: vertical;
}
.notes-actions { margin-top: 0.6rem; display: flex; gap: 0.6rem; align-items: center; }
.primary { background: var(--accent); color: var(--accent-text); border: 0; border-radius: 6px; padding: 0.4rem 0.9rem; cursor: pointer; font-weight: 500; }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.saved { color: var(--good); font-size: 0.85rem; }
</style>
