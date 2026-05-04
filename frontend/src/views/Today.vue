<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import { api } from "@/api/client";
import type {
  Activity, Annotation, HeartRateSeries, HrvSeries,
  SleepNight, StepsSeries, TodaySummary,
} from "@/api/types";
import { chartTheme } from "@/theme";
import { annotationMarkPoint, baseTimeOption, meanMarkLine, workoutMarkArea } from "@/components/charts/chartHelpers";

import Card from "@/components/Card.vue";
import RecoveryCard from "@/components/RecoveryCard.vue";
import SleepCard from "@/components/SleepCard.vue";
import StepsCard from "@/components/StepsCard.vue";

type Range = "6h" | "24h" | "3d" | "7d";
const RANGES: { key: Range; hours: number; label: string }[] = [
  { key: "6h", hours: 6, label: "6h" },
  { key: "24h", hours: 24, label: "24h" },
  { key: "3d", hours: 72, label: "3d" },
  { key: "7d", hours: 168, label: "7d" },
];

const range = ref<Range>("24h");
const summary = ref<TodaySummary | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const hrv = ref<HrvSeries | null>(null);
const sleep = ref<SleepNight | null>(null);
const steps = ref<StepsSeries | null>(null);
const activities = ref<Activity[]>([]);
const annotations = ref<Annotation[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

// Blood pressure
type BpPoint = { time: string; systolic: number; diastolic: number; pulse_bpm: number | null; source: string; notes: string | null };
const bp = ref<{ latest: BpPoint | null; avg_sys: number | null; avg_dia: number | null; points: BpPoint[] }>({ latest: null, avg_sys: null, avg_dia: null, points: [] });
const bpForm = ref({ systolic: "", diastolic: "", pulse: "", notes: "" });
const bpSaving = ref(false);
const bpError = ref<string | null>(null);
const bpFormVisible = ref(false);

async function loadBp() {
  try {
    const since = new Date();
    since.setDate(since.getDate() - 30);
    bp.value = await api.bloodPressure({ since });
  } catch (e) {
    bpError.value = e instanceof Error ? e.message : String(e);
  }
}

async function saveBp() {
  bpSaving.value = true;
  bpError.value = null;
  try {
    const sys = parseInt(bpForm.value.systolic, 10);
    const dia = parseInt(bpForm.value.diastolic, 10);
    if (!Number.isFinite(sys) || !Number.isFinite(dia)) throw new Error("Enter both systolic and diastolic");
    const pulse = bpForm.value.pulse ? parseInt(bpForm.value.pulse, 10) : null;
    await api.logBloodPressure({
      systolic: sys, diastolic: dia,
      pulse_bpm: Number.isFinite(pulse as number) ? pulse : null,
      notes: bpForm.value.notes || null,
    });
    bpForm.value = { systolic: "", diastolic: "", pulse: "", notes: "" };
    bpFormVisible.value = false;
    await loadBp();
  } catch (e) {
    bpError.value = e instanceof Error ? e.message : String(e);
  } finally {
    bpSaving.value = false;
  }
}

function bpClass(sys: number, dia: number): string {
  if (sys >= 180 || dia >= 120) return "bp-crisis";
  if (sys >= 140 || dia >= 90) return "bp-stage2";
  if (sys >= 130 || dia >= 80) return "bp-stage1";
  if (sys >= 120) return "bp-elevated";
  return "bp-normal";
}
function bpLabel(sys: number, dia: number): string {
  if (sys >= 180 || dia >= 120) return "Hypertensive crisis";
  if (sys >= 140 || dia >= 90) return "Stage 2";
  if (sys >= 130 || dia >= 80) return "Stage 1";
  if (sys >= 120) return "Elevated";
  return "Normal";
}

// Chart toggles
const showWorkouts = ref(true);
const showAnnotations = ref(true);
const showHrv = ref(false);
const showMean = ref(true);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const hours = RANGES.find((r) => r.key === range.value)!.hours;
    const since = new Date(Date.now() - hours * 3600 * 1000);
    const [s, h, hv, sl, st, a, an] = await Promise.all([
      api.todaySummary(),
      api.heartRate({ since }),
      api.hrv({ since }),
      api.lastSleep(),
      api.steps({ since }),
      api.activities({ since, limit: 50 }),
      api.listAnnotations({ since, limit: 200 }),
    ]);
    summary.value = s;
    hr.value = h;
    hrv.value = hv;
    sleep.value = sl;
    steps.value = st;
    activities.value = a;
    annotations.value = an;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(() => { load(); loadBp(); });
watch(range, load);

const hrSeriesOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const opt = baseTimeOption() as Record<string, any>;
  if (!hr.value) return opt;

  const hrPoints = hr.value.points.map((p) => [p.time, p.value]);
  const series: any[] = [
    {
      type: "line",
      name: "HR",
      showSymbol: false,
      smooth: true,
      lineStyle: { color: t.palette.hr, width: 1.5 },
      areaStyle: { color: `${t.palette.hr}22` },
      data: hrPoints,
      ...(showWorkouts.value && activities.value.length > 0
        ? { markArea: workoutMarkArea(activities.value) }
        : {}),
      ...(showMean.value && hr.value.avg !== null
        ? { markLine: meanMarkLine(hr.value.avg, "avg HR") }
        : {}),
      ...(showAnnotations.value && annotations.value.length > 0
        ? { markPoint: annotationMarkPoint(annotations.value, hr.value.max_bpm ?? 100) }
        : {}),
    },
  ];

  if (showHrv.value && hrv.value && hrv.value.points.length > 0) {
    series.push({
      type: "line",
      name: "HRV",
      yAxisIndex: 1,
      showSymbol: false,
      smooth: true,
      lineStyle: { color: t.palette.hrv, width: 1.2, type: "dashed" },
      data: hrv.value.points.map((p) => [p.time, p.value]),
    });
    opt.yAxis = [
      { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, scale: true,
        name: "bpm", nameTextStyle: t.axisLabel },
      { type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, scale: true,
        name: "ms", nameTextStyle: t.axisLabel, position: "right" },
    ];
  }

  opt.series = series;
  opt.legend = { show: showHrv.value, textStyle: t.axisLabel, top: 4 };
  return opt;
});

const stepsBarOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!steps.value || steps.value.points.length === 0) return null;
  return {
    grid: { left: 36, right: 12, top: 8, bottom: 24 },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine },
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [{
      type: "bar",
      data: steps.value.points.map((p) => [p.time, p.value]),
      itemStyle: { color: t.palette.steps },
    }],
  };
});

const subtitleHr = computed(() => {
  if (!hr.value || hr.value.points.length === 0) return "no data";
  const a = hr.value.avg, mn = hr.value.min_bpm, mx = hr.value.max_bpm;
  return `${hr.value.points.length} pts · avg ${Math.round(a ?? 0)} · min ${Math.round(mn ?? 0)} · max ${Math.round(mx ?? 0)}`;
});
</script>

<template>
  <div class="today">
    <header class="head">
      <h1>Today</h1>
      <div class="controls">
        <div class="range">
          <button v-for="r in RANGES" :key="r.key"
                  :class="{ active: range === r.key }" @click="range = r.key">
            {{ r.label }}
          </button>
        </div>
        <button class="ghost" @click="load" :disabled="loading">{{ loading ? "…" : "↻" }}</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>

    <div v-if="!loading">
      <!-- top stats row -->
      <div class="grid stats">
        <RecoveryCard
          :score="summary?.recovery_score ?? null"
          :rhr="summary?.resting_hr ?? null"
          :hrv="summary?.hrv_avg ?? null"
        />
        <StepsCard :total="summary?.steps_total ?? steps?.total ?? 0" />
        <SleepCard :sleep="sleep" />
      </div>

      <!-- HR chart with toggles -->
      <Card title="Heart rate" :subtitle="subtitleHr">
        <div class="toggle-row">
          <label v-if="activities.length > 0">
            <input type="checkbox" v-model="showWorkouts"/>
            <span>Workouts ({{ activities.length }})</span>
          </label>
          <label v-if="hrv && hrv.points.length > 0">
            <input type="checkbox" v-model="showHrv"/>
            <span>HRV overlay</span>
          </label>
          <label v-if="annotations.length > 0">
            <input type="checkbox" v-model="showAnnotations"/>
            <span>Annotations ({{ annotations.length }})</span>
          </label>
          <label>
            <input type="checkbox" v-model="showMean"/>
            <span>Mean line</span>
          </label>
        </div>
        <div class="chart-wrap">
          <VChart v-if="hr && hr.points.length > 0" :option="hrSeriesOption" autoresize />
          <div v-else class="empty">No HR data in this range</div>
        </div>
      </Card>

      <!-- steps bar chart -->
      <Card title="Steps" :subtitle="`${steps?.total ?? 0} total`">
        <div class="chart-wrap small">
          <VChart v-if="stepsBarOption" :option="stepsBarOption" autoresize />
          <div v-else class="empty">No step data</div>
        </div>
      </Card>

      <!-- Blood pressure -->
      <Card title="Blood pressure" :subtitle="bp.latest ? new Date(bp.latest.time).toLocaleString() : 'No readings yet'">
        <div v-if="bp.latest" class="bp-latest">
          <div class="bp-big" :class="bpClass(bp.latest.systolic, bp.latest.diastolic)">
            <span class="sys">{{ bp.latest.systolic }}</span>
            <span class="slash">/</span>
            <span class="dia">{{ bp.latest.diastolic }}</span>
            <span class="unit">mmHg</span>
          </div>
          <div class="bp-meta">
            <span class="bp-tag" :class="bpClass(bp.latest.systolic, bp.latest.diastolic)">{{ bpLabel(bp.latest.systolic, bp.latest.diastolic) }}</span>
            <span v-if="bp.latest.pulse_bpm" class="muted">Pulse: {{ bp.latest.pulse_bpm }} bpm</span>
            <span class="muted">via {{ bp.latest.source }}</span>
          </div>
          <div v-if="bp.avg_sys && bp.avg_dia" class="bp-avg">
            30-day avg: {{ bp.avg_sys.toFixed(0) }}/{{ bp.avg_dia.toFixed(0) }}
          </div>
        </div>
        <div v-else class="empty">
          Pair OMRON Connect with Health Connect, or log a reading manually.
        </div>

        <div class="bp-actions">
          <button class="ghost" @click="bpFormVisible = !bpFormVisible">
            {{ bpFormVisible ? 'Cancel' : '+ Log a reading' }}
          </button>
        </div>
        <div v-if="bpFormVisible" class="bp-form">
          <input v-model="bpForm.systolic" type="number" placeholder="Sys" min="40" max="260"/>
          <span>/</span>
          <input v-model="bpForm.diastolic" type="number" placeholder="Dia" min="20" max="180"/>
          <input v-model="bpForm.pulse" type="number" placeholder="Pulse (opt)" min="20" max="250"/>
          <input v-model="bpForm.notes" type="text" placeholder="Notes (optional)" class="bp-notes"/>
          <button class="primary" :disabled="bpSaving" @click="saveBp">
            {{ bpSaving ? 'Saving…' : 'Save' }}
          </button>
        </div>
        <div v-if="bpError" class="err"><small>{{ bpError }}</small></div>
      </Card>
    </div>

    <div v-if="summary?.last_sync" class="footer">
      Last sync: {{ new Date(summary.last_sync).toLocaleString() }}
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }
h1 { margin: 0; }
.controls { display: flex; gap: 0.6rem; align-items: center; }
.range { display: flex; gap: 0.25rem; }
.range button { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.8rem; }
.range button.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.55rem; cursor: pointer; font-size: 0.9rem; }

.grid { display: grid; gap: 1rem; margin-bottom: 1rem; }
.stats { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }

.toggle-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.toggle-row label { display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none; }

/* ECharts needs an explicitly-sized parent — flex grow leaves it 0×0. */
.chart-wrap { width: 100%; height: 320px; }
.chart-wrap.small { height: 160px; }
.chart-wrap > * { width: 100%; height: 100%; }
.empty { color: var(--muted-2); align-self: center; margin: auto; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
.footer { margin-top: 1.5rem; color: var(--muted-2); font-size: 0.8rem; text-align: right; }

.bp-latest { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.4rem 0; }
.bp-big { display: flex; align-items: baseline; gap: 0.3rem; font-family: ui-monospace, monospace; font-weight: 600; }
.bp-big .sys, .bp-big .dia { font-size: 2rem; }
.bp-big .slash { font-size: 1.5rem; color: var(--muted-2); }
.bp-big .unit { font-size: 0.75rem; color: var(--muted); margin-left: 0.4rem; }
.bp-meta { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; font-size: 0.85rem; }
.bp-meta .muted { color: var(--muted); }
.bp-tag { padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 500; }
.bp-normal { color: #22c55e; } .bp-normal.bp-tag { background: rgba(34, 197, 94, 0.15); }
.bp-elevated { color: #eab308; } .bp-elevated.bp-tag { background: rgba(234, 179, 8, 0.15); }
.bp-stage1 { color: #f97316; } .bp-stage1.bp-tag { background: rgba(249, 115, 22, 0.15); }
.bp-stage2 { color: #ef4444; } .bp-stage2.bp-tag { background: rgba(239, 68, 68, 0.15); }
.bp-crisis { color: #b91c1c; } .bp-crisis.bp-tag { background: rgba(185, 28, 28, 0.2); font-weight: 700; }
.bp-avg { font-size: 0.8rem; color: var(--muted); }
.bp-actions { margin: 0.6rem 0 0; }
.bp-form { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-top: 0.6rem; }
.bp-form input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.35rem 0.5rem; width: 80px; font-size: 0.9rem; font-family: inherit; }
.bp-form .bp-notes { width: 100%; }
.bp-form .primary { background: var(--accent); color: var(--accent-text); border: 1px solid var(--accent); border-radius: 4px; padding: 0.4rem 0.9rem; cursor: pointer; }
.bp-form .primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
