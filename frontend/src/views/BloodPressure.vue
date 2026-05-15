<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import PatternsLink from "@/components/PatternsLink.vue";
import { api } from "@/api/client";
import { chartTheme } from "@/theme";
import { fmtDateTime } from "@/format";

type Range = "30d" | "90d" | "1y" | "all";
const RANGES: { key: Range; label: string; days: number | null }[] = [
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "1y",  label: "1y",  days: 365 },
  { key: "all", label: "all", days: null },
];
const range = ref<Range>("90d");

type BpPoint = {
  time: string; systolic: number; diastolic: number;
  pulse_bpm: number | null; source: string; notes: string | null;
};
const series = ref<BpPoint[]>([]);
const stats = ref<{ avg_sys: number | null; avg_dia: number | null; latest: BpPoint | null }>({
  avg_sys: null, avg_dia: null, latest: null,
});
const loading = ref(false);

// Manual entry form
const form = ref({ systolic: "", diastolic: "", pulse: "", notes: "" });
const saving = ref(false);
const saveErr = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const since = days == null
      ? new Date("2010-01-01")
      : (() => { const d = new Date(); d.setDate(d.getDate() - days); return d; })();
    const r = await api.bloodPressure({ since });
    series.value = r.points;
    stats.value = { avg_sys: r.avg_sys, avg_dia: r.avg_dia, latest: r.latest };
  } finally { loading.value = false; }
}

async function logBp() {
  saving.value = true; saveErr.value = null;
  try {
    const sys = parseInt(form.value.systolic, 10);
    const dia = parseInt(form.value.diastolic, 10);
    if (!Number.isFinite(sys) || !Number.isFinite(dia)) throw new Error("Enter both systolic and diastolic");
    const pulse = form.value.pulse ? parseInt(form.value.pulse, 10) : null;
    await api.logBloodPressure({
      systolic: sys, diastolic: dia,
      pulse_bpm: Number.isFinite(pulse as number) ? pulse : null,
      notes: form.value.notes || null,
    });
    form.value = { systolic: "", diastolic: "", pulse: "", notes: "" };
    await load();
  } catch (e) {
    saveErr.value = e instanceof Error ? e.message : String(e);
  } finally { saving.value = false; }
}

onMounted(load);
watch(range, load);

const sorted = computed(() =>
  [...series.value].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
);

// AHA category breakdown over the window
function categoryOf(sys: number, dia: number): string {
  if (sys >= 180 || dia >= 120) return "crisis";
  if (sys >= 140 || dia >= 90)  return "stage2";
  if (sys >= 130 || dia >= 80)  return "stage1";
  if (sys >= 120) return "elevated";
  return "normal";
}
const breakdown = computed(() => {
  const counts: Record<string, number> = { normal: 0, elevated: 0, stage1: 0, stage2: 0, crisis: 0 };
  for (const p of sorted.value) counts[categoryOf(p.systolic, p.diastolic)] += 1;
  return counts;
});

// Rolling 7-day window stats relative to most recent reading
const recent = computed(() => {
  if (sorted.value.length === 0) return null;
  const now = new Date(sorted.value[sorted.value.length - 1].time).getTime();
  const week = now - 7 * 86400_000;
  const month = now - 30 * 86400_000;
  const w7 = sorted.value.filter((p) => new Date(p.time).getTime() >= week);
  const w30 = sorted.value.filter((p) => new Date(p.time).getTime() >= month);
  const avg = (rows: BpPoint[], k: "systolic" | "diastolic") =>
    rows.length === 0 ? null : rows.reduce((s, r) => s + r[k], 0) / rows.length;
  return {
    n7: w7.length, n30: w30.length,
    sys7: avg(w7, "systolic"), dia7: avg(w7, "diastolic"),
    sys30: avg(w30, "systolic"), dia30: avg(w30, "diastolic"),
  };
});

// Main chart — sys + dia over time + threshold reference lines.
const trendOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const sys = sorted.value.map((p) => [p.time, p.systolic]);
  const dia = sorted.value.map((p) => [p.time, p.diastolic]);
  return {
    grid: { left: 50, right: 50, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: "mmHg", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      { name: "Systolic", type: "line", data: sys, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 5,
        lineStyle: { width: 2, color: t.palette.hr }, itemStyle: { color: t.palette.hr },
        markLine: {
          silent: true, symbol: "none", lineStyle: { type: "dashed" as const },
          data: [
            { yAxis: 120, lineStyle: { color: "#eab308" }, label: { formatter: "elev", color: "#eab308" } },
            { yAxis: 130, lineStyle: { color: "#f97316" }, label: { formatter: "stage 1", color: "#f97316" } },
            { yAxis: 140, lineStyle: { color: "#ef4444" }, label: { formatter: "stage 2", color: "#ef4444" } },
          ],
        },
      },
      { name: "Diastolic", type: "line", data: dia, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 5,
        lineStyle: { width: 2, color: t.palette.recovery }, itemStyle: { color: t.palette.recovery },
      },
    ],
    dataZoom: [{ type: "inside" }],
  };
});

// Pulse line (when present)
const pulseOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const pts = sorted.value
    .filter((p) => p.pulse_bpm != null)
    .map((p) => [p.time, p.pulse_bpm]);
  if (pts.length === 0) return null;
  return {
    grid: { left: 40, right: 12, top: 16, bottom: 28 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: "bpm", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      name: "Pulse @ reading", type: "line", data: pts, smooth: true,
      symbol: "circle", symbolSize: 4, connectNulls: true,
      lineStyle: { width: 1.5, color: t.palette.hr }, itemStyle: { color: t.palette.hr },
    }],
  };
});

const sortDesc = ref(true);
const tableRows = computed(() => {
  const arr = [...sorted.value];
  if (sortDesc.value) arr.reverse();
  return arr;
});

function fmtDate(s: string): string {
  return fmtDateTime(s);
}
function categoryLabel(s: number, d: number): string {
  const labels: Record<string, string> = {
    normal: "Normal", elevated: "Elevated", stage1: "Stage 1",
    stage2: "Stage 2", crisis: "Crisis",
  };
  return labels[categoryOf(s, d)] ?? "Normal";
}
</script>

<template>
  <div class="bp">
    <header class="head">
      <h1>Blood pressure</h1>
      <div class="picker">
        <PatternsLink metric="bp_systolic_avg" label="BP"/>
        <button v-for="r in RANGES" :key="r.key"
                :class="{ active: range === r.key }" @click="range = r.key">{{ r.label }}</button>
      </div>
    </header>

    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="sorted.length === 0" class="empty">
      No BP readings yet. Pair OMRON Connect → Health Connect, or log manually below.
    </div>

    <template v-else>
      <!-- KPI banner -->
      <div class="kpis">
        <div class="kpi" v-if="stats.latest">
          <div class="kpi-label">Latest</div>
          <div class="kpi-val" :class="`bp-${categoryOf(stats.latest.systolic, stats.latest.diastolic)}`">
            <strong>{{ stats.latest.systolic }}/{{ stats.latest.diastolic }}</strong>
            <span class="unit">mmHg</span>
          </div>
          <div class="kpi-sub muted">
            {{ categoryLabel(stats.latest.systolic, stats.latest.diastolic) }}
            · {{ fmtDate(stats.latest.time) }}
          </div>
        </div>
        <div class="kpi" v-if="recent">
          <div class="kpi-label">7-day avg</div>
          <div class="kpi-val">
            <strong>{{ recent.sys7?.toFixed(0) ?? '—' }}/{{ recent.dia7?.toFixed(0) ?? '—' }}</strong>
          </div>
          <div class="kpi-sub muted">{{ recent.n7 }} reading(s)</div>
        </div>
        <div class="kpi" v-if="recent">
          <div class="kpi-label">30-day avg</div>
          <div class="kpi-val">
            <strong>{{ recent.sys30?.toFixed(0) ?? '—' }}/{{ recent.dia30?.toFixed(0) ?? '—' }}</strong>
          </div>
          <div class="kpi-sub muted">{{ recent.n30 }} reading(s)</div>
        </div>
        <div class="kpi">
          <div class="kpi-label">Window avg</div>
          <div class="kpi-val">
            <strong>{{ stats.avg_sys?.toFixed(0) ?? '—' }}/{{ stats.avg_dia?.toFixed(0) ?? '—' }}</strong>
          </div>
          <div class="kpi-sub muted">{{ sorted.length }} total</div>
        </div>
        <div class="kpi" v-if="breakdown">
          <div class="kpi-label">Category split</div>
          <div class="cats">
            <span v-if="breakdown.normal"   class="cat bp-normal">N {{ breakdown.normal }}</span>
            <span v-if="breakdown.elevated" class="cat bp-elevated">E {{ breakdown.elevated }}</span>
            <span v-if="breakdown.stage1"   class="cat bp-stage1">S1 {{ breakdown.stage1 }}</span>
            <span v-if="breakdown.stage2"   class="cat bp-stage2">S2 {{ breakdown.stage2 }}</span>
            <span v-if="breakdown.crisis"   class="cat bp-crisis">!! {{ breakdown.crisis }}</span>
          </div>
        </div>
      </div>

      <Card title="Trend">
        <div class="chart"><VChart :option="trendOption" autoresize/></div>
      </Card>

      <Card v-if="pulseOption" title="Pulse at time of reading">
        <div class="chart small"><VChart :option="pulseOption" autoresize/></div>
      </Card>
    </template>

    <Card title="Log a reading">
      <div class="bp-form">
        <input v-model="form.systolic" type="number" placeholder="Sys" min="40" max="260"/>
        <span>/</span>
        <input v-model="form.diastolic" type="number" placeholder="Dia" min="20" max="180"/>
        <input v-model="form.pulse" type="number" placeholder="Pulse (opt)" min="20" max="250"/>
        <input v-model="form.notes" type="text" placeholder="Notes" class="bp-notes"/>
        <button class="primary" :disabled="saving" @click="logBp">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <div v-if="saveErr" class="err"><small>{{ saveErr }}</small></div>
    </Card>

    <Card v-if="sorted.length" :title="`History (${tableRows.length} readings)`">
      <table class="hist">
        <thead>
          <tr>
            <th @click="sortDesc = !sortDesc" class="sortable">Date {{ sortDesc ? '↓' : '↑' }}</th>
            <th>BP</th>
            <th>Category</th>
            <th>Pulse</th>
            <th>Source</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in tableRows.slice(0, 200)" :key="`${r.time}-${i}`">
            <td class="m">{{ fmtDate(r.time) }}</td>
            <td><strong :class="`bp-${categoryOf(r.systolic, r.diastolic)}`">
              {{ r.systolic }}/{{ r.diastolic }}
            </strong></td>
            <td>{{ categoryLabel(r.systolic, r.diastolic) }}</td>
            <td>{{ r.pulse_bpm ?? '—' }}</td>
            <td class="m">{{ r.source }}</td>
            <td class="m">{{ r.notes ?? '' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="tableRows.length > 200" class="muted">
        Showing first 200 of {{ tableRows.length }}.
      </div>
    </Card>
  </div>
</template>

<style scoped>
.bp { max-width: 1200px; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
h1 { margin: 0; }
.picker { display: flex; gap: 0.25rem; }
.picker button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.85rem; }
.picker button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.6rem; margin-bottom: 1rem; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem 1rem; }
.kpi-label { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-val { font-size: 1.5rem; font-weight: 600; margin: 0.2rem 0 0.1rem; font-family: ui-monospace, monospace; }
.kpi-val .unit { font-size: 0.7rem; color: var(--muted); margin-left: 0.3rem; }
.kpi-sub { color: var(--muted); font-size: 0.8rem; }
.cats { display: flex; gap: 0.3rem; flex-wrap: wrap; margin: 0.2rem 0; }
.cat { padding: 0.15rem 0.45rem; border-radius: 4px; font-size: 0.75rem; font-family: ui-monospace, monospace; }
.bp-normal   { background: rgba(34, 197, 94, 0.18); color: #22c55e; }
.bp-elevated { background: rgba(234, 179, 8, 0.18); color: #eab308; }
.bp-stage1   { background: rgba(249, 115, 22, 0.18); color: #f97316; }
.bp-stage2   { background: rgba(239, 68, 68, 0.18); color: #ef4444; }
.bp-crisis   { background: rgba(185, 28, 28, 0.25); color: #b91c1c; font-weight: 700; }

.chart { width: 100%; height: 380px; }
.chart.small { height: 200px; }
.chart > * { width: 100%; height: 100%; }

.bp-form { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.bp-form input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.45rem 0.6rem; font-size: 0.9rem; font-family: inherit; width: 90px; }
.bp-form .bp-notes { flex: 1; min-width: 200px; }
.bp-form .primary { background: var(--accent); color: var(--accent-text); border: 1px solid var(--accent); border-radius: 4px; padding: 0.45rem 1rem; cursor: pointer; }
.bp-form .primary:disabled { opacity: 0.5; cursor: not-allowed; }

.hist { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.hist th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
.hist th.sortable { cursor: pointer; user-select: none; }
.hist td { padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--surface-2); }
.hist .m { color: var(--muted); font-size: 0.85rem; }
.muted { color: var(--muted); font-size: 0.85rem; padding: 0.6rem; }

.empty { color: var(--muted-2); padding: 2rem; text-align: center; }
.err { color: var(--bad); padding: 0.4rem 0.6rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin-top: 0.4rem; }
</style>
