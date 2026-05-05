<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import { chartTheme } from "@/theme";
import { weightVal, weightUnit, fmtWeight, isImperial } from "@/units";

type Range = "30d" | "90d" | "1y" | "all";
const RANGES: { key: Range; label: string; days: number | null }[] = [
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "1y",  label: "1y",  days: 365 },
  { key: "all", label: "all", days: null },
];

const range = ref<Range>("90d");
const yoy = ref(false);

type Point = {
  time: string; weight_kg: number | null; body_fat_pct: number | null;
  bmi: number | null; lean_mass_kg: number | null; source: string;
};
const series = ref<Point[]>([]);
const loading = ref(false);

// Profile (height for BMI bands + goal for progress)
const heightCm = ref<number>(178);
const goalKg = ref<number | null>(null);

async function loadProfile() {
  try {
    const p = await api.getProfile();
    if (p.height_cm) heightCm.value = p.height_cm;
    if (p.weight_goal_kg) goalKg.value = p.weight_goal_kg;
  } catch { /* not configured yet */ }
}

async function load() {
  loading.value = true;
  try {
    // YoY needs the full history regardless of range picker.
    const days = yoy.value ? null : RANGES.find((r) => r.key === range.value)!.days;
    const since = days == null
      ? new Date("2010-01-01")
      : (() => { const d = new Date(); d.setDate(d.getDate() - days); return d; })();
    const r = await api.weight({ since });
    series.value = r.points;
  } finally { loading.value = false; }
}
watch(yoy, load);
onMounted(() => { loadProfile(); load(); });
watch(range, load);

// === Sorted, filtered series ===
const sorted = computed(() =>
  [...series.value]
    .filter((p) => p.weight_kg != null)
    .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
);

// === Body recomposition direction (last 30d) ===
const recomp = computed(() => {
  const cutoff = Date.now() - 30 * 86400_000;
  const recent = sorted.value.filter((p) => new Date(p.time).getTime() >= cutoff && p.body_fat_pct != null);
  if (recent.length < 5) return null;
  const first = recent[0];
  const last = recent[recent.length - 1];
  const fatA = (first.weight_kg as number) * ((first.body_fat_pct as number) / 100);
  const leanA = (first.weight_kg as number) - fatA;
  const fatB = (last.weight_kg as number) * ((last.body_fat_pct as number) / 100);
  const leanB = (last.weight_kg as number) - fatB;
  const fatΔ = fatB - fatA;       // negative = good
  const leanΔ = leanB - leanA;    // positive = good
  let label: string;
  let cls: string;
  if (fatΔ < -0.3 && leanΔ > -0.2) { label = "Body recomp ↗"; cls = "good"; }
  else if (fatΔ < 0 && leanΔ < 0) { label = "Cutting"; cls = ""; }
  else if (fatΔ > 0 && leanΔ > 0) { label = "Bulking"; cls = ""; }
  else if (fatΔ > 0.3) { label = "Fat gain"; cls = "bad"; }
  else { label = "Stable"; cls = ""; }
  return { label, cls, fatΔ, leanΔ };
});

// === KPIs ===
const stats = computed(() => {
  if (sorted.value.length === 0) return null;
  const vals = sorted.value.map((p) => p.weight_kg as number);
  const latest = vals[vals.length - 1];
  const first = vals[0];
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  const since7 = Date.now() - 7 * 86400_000;
  const since30 = Date.now() - 30 * 86400_000;
  const w7 = sorted.value.find((p) => new Date(p.time).getTime() >= since7);
  const w30 = sorted.value.find((p) => new Date(p.time).getTime() >= since30);
  return {
    latest, first, min, max, avg,
    delta_period: latest - first,
    delta_7d: w7 ? latest - (w7.weight_kg as number) : null,
    delta_30d: w30 ? latest - (w30.weight_kg as number) : null,
    n_readings: vals.length,
    days_at_min: sorted.value.filter((p) => Math.abs((p.weight_kg as number) - min) < 0.05).length,
  };
});

// === 7-day rolling moving average ===
function rolling7Avg(pts: { t: number; v: number }[]): { t: number; v: number }[] {
  if (!pts.length) return [];
  const W = 7 * 86400_000;
  const out: { t: number; v: number }[] = [];
  let i0 = 0;
  for (let i = 0; i < pts.length; i++) {
    while (pts[i].t - pts[i0].t > W) i0++;
    let s = 0; let n = 0;
    for (let j = i0; j <= i; j++) { s += pts[j].v; n++; }
    out.push({ t: pts[i].t, v: s / n });
  }
  return out;
}

// === Main chart ===
function bmiBands(): unknown[] {
  const heightM = (heightCm.value || 178) / 100;
  const toUnit = (kg: number) => weightVal(kg) ?? kg;
  const u = toUnit(18.5 * heightM * heightM);
  const n = toUnit(25 * heightM * heightM);
  const o = toUnit(30 * heightM * heightM);
  return [
    [{ yAxis: 0,    itemStyle: { color: "rgba(56, 189, 248, 0.07)" } }, { yAxis: u }],
    [{ yAxis: u,    itemStyle: { color: "rgba(34, 197, 94, 0.07)" } }, { yAxis: n }],
    [{ yAxis: n,    itemStyle: { color: "rgba(234, 179, 8, 0.07)" } }, { yAxis: o }],
    [{ yAxis: o,    itemStyle: { color: "rgba(239, 68, 68, 0.10)" } }, { yAxis: 9999 }],
  ];
}

const mainOption = computed(() => {
  void chartTheme.value; void weightUnit.value;
  const t = chartTheme.value;
  // Year-over-year overlay: split series into per-year curves aligned by
  // day-of-year so seasonal patterns become obvious.
  if (yoy.value) {
    const byYear: Record<string, [string, number][]> = {};
    for (const p of sorted.value) {
      const d = new Date(p.time);
      const y = d.getUTCFullYear();
      // Pseudo-date in a fixed reference year so all series share the x-axis.
      const ref = `2000-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
      (byYear[String(y)] ??= []).push([ref, weightVal(p.weight_kg) as number]);
    }
    const yrs = Object.keys(byYear).sort();
    const palette = ["#94a3b8", "#64748b", "#a78bfa", "#22c55e", "#eab308", "#f97316", "#ef4444", "#38bdf8", "#0ea5e9"];
    const series = yrs.map((y, i) => ({
      name: y, type: "line", smooth: true, symbol: "none",
      data: byYear[y].sort((a, b) => a[0].localeCompare(b[0])),
      lineStyle: {
        width: i === yrs.length - 1 ? 2.5 : 1.2,
        color: palette[i % palette.length],
        opacity: i === yrs.length - 1 ? 1 : 0.55,
      },
    }));
    return {
      grid: { left: 50, right: 12, top: 36, bottom: 28 },
      legend: { textStyle: t.axisLabel, top: 4 },
      tooltip: { trigger: "axis", ...t.tooltip,
        formatter: (params: any[]) => {
          const md = params[0].name.slice(5);  // strip "2000-"
          return md + "<br/>" + params.map((p) => `${p.marker}${p.seriesName}: <b>${p.value[1]?.toFixed(1)}</b>`).join("<br/>");
        }},
      xAxis: { type: "category", axisLabel: { color: t.axisLabel.color, formatter: (v: string) => v.slice(5) }, splitLine: t.splitLine },
      yAxis: { type: "value", name: weightUnit.value, scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
      series,
      dataZoom: [{ type: "inside" }],
    };
  }

  const raw = sorted.value.map((p) => ({ t: new Date(p.time).getTime(), v: weightVal(p.weight_kg) as number }));
  const pts = raw.map((p) => [p.t, p.v]);
  const ma = rolling7Avg(raw).map((p) => [p.t, p.v]);
  const fatPts = sorted.value
    .filter((p) => p.body_fat_pct != null)
    .map((p) => [new Date(p.time).getTime(), p.body_fat_pct]);

  const series: Array<Record<string, unknown>> = [];
  if (pts.length) series.push({
    name: `Daily ${weightUnit.value}`, type: "line", data: pts,
    symbol: "circle", symbolSize: 3, connectNulls: false,
    lineStyle: { width: 1, color: t.palette.accent, opacity: 0.4 },
    itemStyle: { color: t.palette.accent }, yAxisIndex: 0,
    markArea: { silent: true, data: bmiBands() },
  });
  if (ma.length) series.push({
    name: "7-day avg", type: "line", data: ma, smooth: true,
    symbol: "none", lineStyle: { width: 2.5, color: t.palette.accent }, yAxisIndex: 0,
  });
  if (goalKg.value != null) {
    const gv = weightVal(goalKg.value);
    if (gv != null) series.push({
      name: "Goal", type: "line", data: [],
      yAxisIndex: 0, markLine: {
        silent: true, symbol: "none", lineStyle: { color: t.palette.recovery, type: "dashed" as const, width: 1.5 },
        data: [{ yAxis: gv, label: { formatter: `Goal ${gv.toFixed(1)} ${weightUnit.value}`, color: t.palette.recovery } }],
      },
    });
  }
  if (fatPts.length) series.push({
    name: "Body fat %", type: "line", data: fatPts, smooth: true,
    symbol: "circle", symbolSize: 4, connectNulls: true,
    lineStyle: { width: 1.5, color: t.palette.annotation, type: "dashed" as const },
    itemStyle: { color: t.palette.annotation }, yAxisIndex: 1,
  });

  return {
    grid: { left: 50, right: 50, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: [
      { type: "value", name: weightUnit.value, scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
      { type: "value", name: "%", scale: true, axisLabel: t.axisLabel, splitLine: { show: false } },
    ],
    series,
    dataZoom: [{ type: "inside" }],
  };
});

// === Distribution histogram ===
const histogramOption = computed(() => {
  void chartTheme.value; void weightUnit.value;
  const t = chartTheme.value;
  if (sorted.value.length === 0) return null;
  const vals = sorted.value.map((p) => weightVal(p.weight_kg) as number);
  const min = Math.floor(Math.min(...vals));
  const max = Math.ceil(Math.max(...vals));
  const binSize = isImperial.value ? 1 : 0.5;
  const bins: Record<string, number> = {};
  for (let v = min; v <= max; v += binSize) bins[v.toFixed(1)] = 0;
  for (const v of vals) {
    const bucket = (Math.floor(v / binSize) * binSize).toFixed(1);
    bins[bucket] = (bins[bucket] ?? 0) + 1;
  }
  const cats = Object.keys(bins).sort((a, b) => parseFloat(a) - parseFloat(b));
  return {
    grid: { left: 40, right: 12, top: 16, bottom: 36 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "category", data: cats, name: weightUnit.value, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "days", axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{ type: "bar", data: cats.map((c) => bins[c]),
               itemStyle: { color: t.palette.accent } }],
  };
});

// === History table ===
const sortDesc = ref(true);
const tableRows = computed(() => {
  const arr = [...sorted.value];
  if (sortDesc.value) arr.reverse();
  return arr;
});

function fmtDate(s: string): string {
  return new Date(s).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}
function fmtDelta(kg: number | null): string {
  if (kg == null) return "—";
  const v = weightVal(kg) as number;
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)} ${weightUnit.value}`;
}
function deltaCls(kg: number | null, lowerIsBetter = true): string {
  if (kg == null) return "";
  if (Math.abs(kg) < 0.05) return "";
  const good = lowerIsBetter ? kg < 0 : kg > 0;
  return good ? "delta-good" : "delta-bad";
}
</script>

<template>
  <div class="weight">
    <header class="head">
      <h1>Weight
        <span v-if="recomp" class="recomp" :class="recomp.cls">· {{ recomp.label }}</span>
      </h1>
      <div class="picker">
        <button v-for="r in RANGES" :key="r.key"
                :class="{ active: range === r.key, dim: yoy }"
                :disabled="yoy" @click="range = r.key">{{ r.label }}</button>
        <label class="yoy-tog">
          <input type="checkbox" v-model="yoy"/> Year-over-year
        </label>
      </div>
    </header>

    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="!stats" class="empty">
      No weight data yet. Import a Fitbit/Garmin ZIP from Settings, or pair a smart scale with Health Connect.
    </div>

    <template v-else>
      <!-- KPI banner -->
      <div class="kpis">
        <div class="kpi">
          <div class="kpi-label">Latest</div>
          <div class="kpi-val">{{ fmtWeight(stats.latest) }}</div>
          <div v-if="goalKg" class="kpi-sub">
            Goal: <strong>{{ fmtWeight(goalKg) }}</strong>
            <span :class="deltaCls(stats.latest - goalKg, false)">
              ({{ fmtDelta(stats.latest - goalKg) }} to go)
            </span>
          </div>
        </div>
        <div class="kpi">
          <div class="kpi-label">7-day Δ</div>
          <div class="kpi-val" :class="deltaCls(stats.delta_7d)">{{ fmtDelta(stats.delta_7d) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">30-day Δ</div>
          <div class="kpi-val" :class="deltaCls(stats.delta_30d)">{{ fmtDelta(stats.delta_30d) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Range Δ</div>
          <div class="kpi-val" :class="deltaCls(stats.delta_period)">{{ fmtDelta(stats.delta_period) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Min · Max</div>
          <div class="kpi-val small">{{ fmtWeight(stats.min) }} – {{ fmtWeight(stats.max) }}</div>
          <div class="kpi-sub">avg {{ fmtWeight(stats.avg) }}</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Readings</div>
          <div class="kpi-val">{{ stats.n_readings }}</div>
          <div class="kpi-sub">{{ stats.days_at_min }} day(s) at min</div>
        </div>
      </div>

      <Card title="Trend">
        <div class="chart"><VChart :option="mainOption" autoresize/></div>
      </Card>

      <Card title="Distribution (days at each weight)">
        <div class="chart small"><VChart v-if="histogramOption" :option="histogramOption" autoresize/></div>
      </Card>

      <Card :title="`History (${tableRows.length} readings)`">
        <table class="hist">
          <thead>
            <tr>
              <th @click="sortDesc = !sortDesc" class="sortable">
                Date {{ sortDesc ? "↓" : "↑" }}
              </th>
              <th>Weight</th>
              <th>Body fat %</th>
              <th>Lean</th>
              <th>BMI</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in tableRows.slice(0, 200)" :key="`${r.time}-${i}`">
              <td class="m">{{ fmtDate(r.time) }}</td>
              <td><strong>{{ fmtWeight(r.weight_kg) }}</strong></td>
              <td>{{ r.body_fat_pct != null ? r.body_fat_pct.toFixed(1) + " %" : "—" }}</td>
              <td>{{ fmtWeight(r.lean_mass_kg) }}</td>
              <td>{{ r.bmi != null ? r.bmi.toFixed(1) : "—" }}</td>
              <td class="m">{{ r.source }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="tableRows.length > 200" class="muted">
          Showing first 200 of {{ tableRows.length }}. Narrow the range to see different windows.
        </div>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.weight { max-width: 1200px; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
h1 { margin: 0; }
.picker { display: flex; gap: 0.25rem; }
.picker button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.85rem; }
.picker button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.picker button.dim { opacity: 0.4; }
.yoy-tog { display: inline-flex; align-items: center; gap: 0.3rem; margin-left: 0.6rem; font-size: 0.85rem; color: var(--muted); cursor: pointer; }
.recomp { font-size: 0.7em; color: var(--muted); margin-left: 0.5rem; font-weight: 400; }
.recomp.good { color: #22c55e; }
.recomp.bad { color: #ef4444; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.6rem; margin-bottom: 1rem; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem 1rem; }
.kpi-label { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-val { font-size: 1.6rem; font-weight: 600; margin: 0.2rem 0 0.1rem; font-family: ui-monospace, monospace; }
.kpi-val.small { font-size: 1rem; }
.kpi-sub { color: var(--muted); font-size: 0.8rem; }
.delta-good { color: #22c55e; }
.delta-bad { color: #ef4444; }

.chart { width: 100%; height: 380px; }
.chart.small { height: 220px; }
.chart > * { width: 100%; height: 100%; }

.hist { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.hist th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
.hist th.sortable { cursor: pointer; user-select: none; }
.hist td { padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--surface-2); }
.hist .m { color: var(--muted); font-size: 0.85rem; }
.muted { color: var(--muted); font-size: 0.85rem; padding: 0.6rem; }

.empty { color: var(--muted-2); padding: 2rem; text-align: center; }
</style>
