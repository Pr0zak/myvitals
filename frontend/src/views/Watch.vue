<script setup lang="ts">
/**
 * Dedicated Pixel-Watch status view. Renders the WatchStatus tile
 * full-width plus a config-link footer pointing at the HA section
 * in Settings. The tile component itself owns polling + the live
 * "Xm ago" tick.
 *
 * Adds (WATCH-1) a 24-hour history strip below the live tile: battery
 * line, on-body bar, activity-state timeline. All three share an
 * X-axis so a single tooltip stitches the watch's whole day together.
 */
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import VChart from "vue-echarts";
import WatchStatus from "@/components/today/WatchStatus.vue";
import { api } from "@/api/client";
import { chartTheme } from "@/theme";

type DeviceStatusSeries = Awaited<ReturnType<typeof api.deviceStatusSeries>>;

const series = ref<DeviceStatusSeries | null>(null);
const error = ref<string | null>(null);
const loading = ref(false);
const windowHours = ref<6 | 12 | 24>(24);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date(Date.now() - windowHours.value * 3_600_000);
    series.value = await api.deviceStatusSeries({ since });
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load device-status series";
    series.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(windowHours, load);

const onPctLabel = computed(() => {
  if (!series.value || series.value.on_body_pct == null) return "—";
  return `${series.value.on_body_pct.toFixed(0)}% on body`;
});

const summaryCells = computed(() => {
  if (!series.value) return [] as { label: string; value: string }[];
  const onH = series.value.on_body_seconds / 3600;
  const offH = series.value.off_body_seconds / 3600;
  const unkH = series.value.unknown_seconds / 3600;
  return [
    { label: "On body",  value: `${onH.toFixed(1)} h` },
    { label: "Off body", value: `${offH.toFixed(1)} h` },
    { label: "Unknown",  value: `${unkH.toFixed(1)} h` },
    { label: "Samples",  value: `${series.value.count}` },
  ];
});

const batteryOption = computed(() => {
  const t = chartTheme.value;
  const points = series.value?.points ?? [];
  const data = points
    .filter((p) => p.battery_pct != null)
    .map((p) => [new Date(p.time).getTime(), p.battery_pct as number]);
  return {
    backgroundColor: "transparent",
    grid: { top: 16, left: 36, right: 12, bottom: 24, containLabel: false },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        const d = new Date(p.data[0]);
        const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        return `${time} · ${p.data[1]}%`;
      },
    },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: {
      type: "value", min: 0, max: 100, name: "%", axisLabel: t.axisLabel,
      splitLine: t.splitLine,
    },
    series: [{
      type: "line", smooth: true, symbol: "none",
      lineStyle: { width: 2, color: t.palette.recovery },
      areaStyle: { color: "rgba(167, 139, 250, 0.16)" },
      data,
    }],
  };
});

const onBodyOption = computed(() => {
  const t = chartTheme.value;
  const points = series.value?.points ?? [];
  // Render as a categorical step line: 1 = on, 0 = off, null gap = unknown.
  const data = points.map((p) => {
    const v = p.is_worn === true ? 1 : p.is_worn === false ? 0 : null;
    return [new Date(p.time).getTime(), v];
  });
  return {
    backgroundColor: "transparent",
    grid: { top: 16, left: 36, right: 12, bottom: 24, containLabel: false },
    tooltip: { trigger: "axis", ...t.tooltip,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        const d = new Date(p.data[0]);
        const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const v = p.data[1];
        const label = v === 1 ? "on body" : v === 0 ? "off body" : "—";
        return `${time} · ${label}`;
      },
    },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: {
      type: "value", min: 0, max: 1, interval: 1,
      axisLabel: {
        ...t.axisLabel,
        formatter: (v: number) => (v === 1 ? "on" : v === 0 ? "off" : ""),
      },
      splitLine: t.splitLine,
    },
    series: [{
      type: "line", step: "end", symbol: "none",
      lineStyle: { width: 2, color: t.palette.steps },
      areaStyle: { color: "rgba(56, 189, 248, 0.18)" },
      connectNulls: false,
      data,
    }],
  };
});

const ACTIVITY_PALETTE: Record<string, string> = {
  still:    "#475569",
  walking:  "#22c55e",
  running:  "#22c55e",
  on_bike:  "#38bdf8",
  in_vehicle: "#a78bfa",
  tilting:  "#eab308",
  unknown:  "#334155",
};

const activityOption = computed(() => {
  const t = chartTheme.value;
  const points = series.value?.points ?? [];
  // Build distinct rows per activity_state so each lights up as bars at its row.
  const seen = new Set<string>();
  for (const p of points) if (p.activity_state) seen.add(p.activity_state);
  const states = Array.from(seen);
  if (states.length === 0) return null;

  // For each consecutive pair, draw a custom-rendered bar from t_i to t_{i+1}.
  type Seg = { state: string; start: number; end: number };
  const segs: Seg[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const s = points[i].activity_state;
    if (!s) continue;
    segs.push({
      state: s,
      start: new Date(points[i].time).getTime(),
      end: new Date(points[i + 1].time).getTime(),
    });
  }
  return {
    backgroundColor: "transparent",
    grid: { top: 16, left: 60, right: 12, bottom: 24, containLabel: false },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" }, ...t.tooltip,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params;
        if (!p?.data) return "";
        return `${p.data.state}<br/>${new Date(p.data.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} → ${new Date(p.data.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
      },
    },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: {
      type: "category", data: states, axisLabel: { ...t.axisLabel, fontSize: 10 },
      splitLine: t.splitLine,
    },
    series: [{
      type: "custom",
      renderItem: (params: any, apiArg: any) => {
        const state = segs[params.dataIndex].state;
        const stateIdx = states.indexOf(state);
        const startCoord = apiArg.coord([segs[params.dataIndex].start, stateIdx]);
        const endCoord   = apiArg.coord([segs[params.dataIndex].end, stateIdx]);
        return {
          type: "rect",
          shape: {
            x: startCoord[0],
            y: startCoord[1] - 8,
            width: Math.max(1, endCoord[0] - startCoord[0]),
            height: 16,
          },
          style: { fill: ACTIVITY_PALETTE[state] ?? ACTIVITY_PALETTE.unknown },
        };
      },
      encode: { x: [1, 2], y: 0 },
      data: segs.map((s) => ({
        value: [s.state, s.start, s.end],
        state: s.state,
        start: s.start,
        end: s.end,
      })),
    }],
  };
});
</script>

<template>
  <div class="watch-view">
    <header class="hdr">
      <h1>Watch</h1>
      <p class="muted">
        Realtime Pixel Watch liveness from Home Assistant — battery,
        on-body, charging, activity state. Heart rate / HRV / sleep
        continue to come from Health Connect (Wear OS Companion App
        publishes HR too sparsely for HA to replace HC).
      </p>
    </header>

    <WatchStatus/>

    <section class="charts">
      <div class="charts-head">
        <span class="card-title">Last {{ windowHours }} h</span>
        <div class="seg-toggle">
          <button :class="{ active: windowHours === 6 }"  @click="windowHours = 6">6h</button>
          <button :class="{ active: windowHours === 12 }" @click="windowHours = 12">12h</button>
          <button :class="{ active: windowHours === 24 }" @click="windowHours = 24">24h</button>
        </div>
        <span v-if="loading" class="muted small">loading…</span>
        <span v-else-if="series" class="muted small">{{ onPctLabel }}</span>
      </div>

      <p v-if="error" class="err">{{ error }}</p>

      <div v-if="!error && series && series.count > 0" class="grid">
        <div class="card chart-card">
          <span class="card-title">Battery</span>
          <VChart class="chart" :option="batteryOption" autoresize/>
        </div>
        <div class="card chart-card">
          <span class="card-title">On body</span>
          <VChart class="chart" :option="onBodyOption" autoresize/>
        </div>
        <div v-if="activityOption" class="card chart-card wide">
          <span class="card-title">Activity state</span>
          <VChart class="chart" :option="activityOption" autoresize/>
        </div>
        <div class="card summary-card wide">
          <div class="summary-grid">
            <div v-for="c in summaryCells" :key="c.label" class="summary-cell">
              <span class="muted">{{ c.label }}</span>
              <span class="summary-val">{{ c.value }}</span>
            </div>
          </div>
        </div>
      </div>

      <p v-else-if="!error && !loading" class="muted small">
        No samples in this window — the HA consumer may not be running yet.
        See Settings → Home Assistant.
      </p>
    </section>

    <p class="cfg-hint">
      Configure HA URL + token in
      <RouterLink to="/settings">Settings</RouterLink>
      under "Home Assistant (watch status)".
    </p>
  </div>
</template>

<style scoped>
.watch-view { max-width: 1080px; margin: 0 auto; padding: 1rem; }
.hdr { margin-bottom: 1rem; }
h1 { margin: 0 0 0.5rem; }
.muted { color: var(--muted); font-size: 0.9rem; max-width: 60ch; }
.small { font-size: 0.78rem; }
.err { color: #ef4444; font-size: 0.85rem; }

.charts { margin-top: 1rem; }
.charts-head {
  display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
}
.charts-head .card-title {
  text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75rem;
  color: var(--on-surface-2);
}
.seg-toggle {
  display: inline-flex; border: 1px solid var(--outline); border-radius: 999px;
  overflow: hidden;
}
.seg-toggle button {
  appearance: none; border: 0; background: transparent;
  padding: 4px 10px; font-size: 11px; color: var(--on-surface-2);
  cursor: pointer;
}
.seg-toggle button.active {
  background: var(--surface); color: var(--on-surface);
}

.grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 6px;
}
.wide { grid-column: 1 / -1; }
.chart-card {
  padding: 12px; display: flex; flex-direction: column; gap: 6px;
  min-height: 180px;
}
.chart-card .card-title {
  text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.7rem;
  color: var(--on-surface-2);
}
.chart { width: 100%; height: 150px; }

.summary-card { padding: 12px; }
.summary-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.summary-cell { display: flex; flex-direction: column; }
.summary-cell .muted {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
}
.summary-val { font-size: 1.05rem; font-weight: 600; color: var(--on-surface); }

.cfg-hint { margin-top: 1.5rem; font-size: 0.85rem; color: var(--muted); }
.cfg-hint a { color: #38bdf8; }

@media (max-width: 720px) {
  .grid { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
