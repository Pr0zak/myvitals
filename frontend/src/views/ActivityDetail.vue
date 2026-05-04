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

const route = useRoute();
const router = useRouter();
const activity = ref<Activity | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

const mapEl = ref<HTMLDivElement | null>(null);
let map: L.Map | null = null;
let polylineLayer: L.Polyline | null = null;

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const a = await api.activity(route.params.source as string, route.params.id as string);
    activity.value = a;
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
  map.fitBounds(polylineLayer.getBounds(), { padding: [20, 20] });
}

onMounted(() => {
  load().then(() => setTimeout(renderMap, 50));
});

watch(activity, () => setTimeout(renderMap, 50));
watch(effectiveTheme, () => setTimeout(renderMap, 50));

onUnmounted(() => {
  if (map) { map.remove(); map = null; }
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
  return m === null ? "—" : `${(m / 1000).toFixed(2)} km`;
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
            {{ new Date(activity.start_at).toLocaleString() }}
            ·
            {{ fmtDur(activity.duration_s) }}
          </p>
        </div>
      </header>

      <div class="grid">
        <Card title="Stats">
          <dl class="kv">
            <div><dt>Distance</dt><dd>{{ fmtKm(activity.distance_m) }}</dd></div>
            <div v-if="activity.elevation_gain_m !== null"><dt>Elevation</dt><dd>{{ Math.round(activity.elevation_gain_m) }} m</dd></div>
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

.map { height: 300px; width: 100%; border-radius: 6px; }

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
</style>
