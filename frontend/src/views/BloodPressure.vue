<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import PageHeader from "@/components/PageHeader.vue";
import RangeTabs from "@/components/RangeTabs.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadState from "@/components/LoadState.vue";
import PatternsLink from "@/components/PatternsLink.vue";
import { api } from "@/api/client";
import { chartTheme, isNeon } from "@/theme";
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
  void isNeon.value;
  const t = chartTheme.value;
  const neon = isNeon.value;
  const sys = sorted.value.map((p) => [p.time, p.systolic]);
  const dia = sorted.value.map((p) => [p.time, p.diastolic]);
  // Threshold reference-line colors. Neon: elev→amber, stage1→amber, stage2→red.
  const cElev = neon ? "#ffb52e" : "#eab308";
  const cStage1 = neon ? "#ffb52e" : "#f97316";
  const cStage2 = neon ? "#ff5d7a" : "#ef4444";
  // Series colors. Neon: systolic→cyan, diastolic→magenta.
  const cSys = neon ? "#28e6ff" : t.palette.hr;
  const cDia = neon ? "#ff3ad8" : t.palette.recovery;
  return {
    grid: { left: 50, right: 50, top: 36, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: "mmHg", scale: true, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      { name: "Systolic", type: "line", data: sys, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 5,
        lineStyle: { width: 2, color: cSys }, itemStyle: { color: cSys },
        markLine: {
          silent: true, symbol: "none", lineStyle: { type: "dashed" as const },
          data: [
            { yAxis: 120, lineStyle: { color: cElev }, label: { formatter: "elev", color: cElev } },
            { yAxis: 130, lineStyle: { color: cStage1 }, label: { formatter: "stage 1", color: cStage1 } },
            { yAxis: 140, lineStyle: { color: cStage2 }, label: { formatter: "stage 2", color: cStage2 } },
          ],
        },
      },
      { name: "Diastolic", type: "line", data: dia, smooth: true, connectNulls: true,
        symbol: "circle", symbolSize: 5,
        lineStyle: { width: 2, color: cDia }, itemStyle: { color: cDia },
      },
    ],
    dataZoom: [{ type: "inside" }],
  };
});

// Pulse line (when present)
const pulseOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const cPulse = isNeon.value ? "#28e6ff" : t.palette.hr;
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
      lineStyle: { width: 1.5, color: cPulse }, itemStyle: { color: cPulse },
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
    <PageHeader title="Blood pressure">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Blood-pressure time range">
        <template #before>
          <PatternsLink metric="bp_systolic_avg" label="BP"/>
        </template>
      </RangeTabs>
    </PageHeader>

    <LoadState v-if="loading" />
    <EmptyState v-else-if="sorted.length === 0">
      No BP readings yet. Pair OMRON Connect → Health Connect, or log manually below.
    </EmptyState>

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

.err { color: var(--bad); padding: 0.4rem 0.6rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin-top: 0.4rem; }

/* ── Vitality Neon ─────────────────────────────────────────────────────
   Scoped to html[data-theme="neon"]; classic/light/dark untouched. */
html[data-theme="neon"] .bp {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-cyan: #28e6ff; --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-amber: #ffb52e;
  --rn-red: #ff5d7a; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 22px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}

/* KPI cards → neon surface, with a Space Grotesk monospace numeric readout */
html[data-theme="neon"] .bp .kpi {
  background: var(--rn-card); border: 1px solid #21243450; border-radius: 18px;
  box-shadow: inset 0 1px 0 #ffffff08;
}
html[data-theme="neon"] .bp .kpi-label {
  color: var(--rn-mut); font-family: 'Space Grotesk', 'Geist Mono', monospace;
  letter-spacing: 0.11em;
}
html[data-theme="neon"] .bp .kpi-val {
  font-family: 'Space Grotesk', 'Geist Mono', monospace; color: var(--rn-ink);
}
html[data-theme="neon"] .bp .kpi-val .unit,
html[data-theme="neon"] .bp .kpi-sub { color: var(--rn-mut); }

/* Glow on the headline "Latest" reading (color comes from the bp-* badge class) */
html[data-theme="neon"] .bp .kpi-val.bp-normal   { text-shadow: 0 0 14px rgba(93, 255, 59, 0.45); }
html[data-theme="neon"] .bp .kpi-val.bp-elevated,
html[data-theme="neon"] .bp .kpi-val.bp-stage1   { text-shadow: 0 0 14px rgba(255, 181, 46, 0.45); }
html[data-theme="neon"] .bp .kpi-val.bp-stage2,
html[data-theme="neon"] .bp .kpi-val.bp-crisis   { text-shadow: 0 0 14px rgba(255, 93, 122, 0.5); }

/* Category badges: normal→lime, elevated/stage1→amber, stage2/crisis→red */
html[data-theme="neon"] .bp .bp-normal   { background: rgba(93, 255, 59, 0.16);  color: var(--rn-lime); }
html[data-theme="neon"] .bp .bp-elevated { background: rgba(255, 181, 46, 0.16); color: var(--rn-amber); }
html[data-theme="neon"] .bp .bp-stage1   { background: rgba(255, 181, 46, 0.16); color: var(--rn-amber); }
html[data-theme="neon"] .bp .bp-stage2   { background: rgba(255, 93, 122, 0.16); color: var(--rn-red); }
html[data-theme="neon"] .bp .bp-crisis   { background: rgba(255, 93, 122, 0.24); color: var(--rn-red); font-weight: 700; }
html[data-theme="neon"] .bp .cat { font-family: 'Space Grotesk', 'Geist Mono', monospace; }

/* The bp-* classes also tint the inline "Latest" value + history-table BP cells;
   the kpi-val rule above keeps that legible against the dark surface. */

/* Manual-entry form on the neon surface */
html[data-theme="neon"] .bp .bp-form input {
  background: #11131c; color: var(--rn-ink); border: 1px solid #2a2e42; border-radius: 9px;
}
html[data-theme="neon"] .bp .bp-form input::placeholder { color: var(--rn-mut); }
html[data-theme="neon"] .bp .bp-form .primary {
  background: var(--rn-cyan); color: #0a0d16; border: 1px solid var(--rn-cyan); border-radius: 9px;
  font-weight: 700; box-shadow: 0 0 14px rgba(40, 230, 255, 0.35);
}

/* History table chrome */
html[data-theme="neon"] .bp .hist th { color: var(--rn-mut); border-bottom-color: #2a2e42; }
html[data-theme="neon"] .bp .hist td { border-bottom-color: #21243450; }
html[data-theme="neon"] .bp .hist .m,
html[data-theme="neon"] .bp .muted { color: var(--rn-mut); }
</style>
