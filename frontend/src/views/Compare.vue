<script setup lang="ts">
import { toLocalISO } from "@/dates";
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { PeriodCompare, TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";
import { weightVal, weightUnit } from "@/units";

type SummaryWithWeight = TodaySummary & { weight_kg?: number | null };
const data = ref<SummaryWithWeight[]>([]);
const cmp = ref<PeriodCompare | null>(null);
const loading = ref(true);
const cmpLoading = ref(true);
const cmpError = ref<string | null>(null);

// CMP-1: the window and the thing being compared against are both server
// parameters now. Previously the page hardcoded "7 days vs prior 7 days"
// and there was no way to ask a different question.
const days = ref(7);
const vs = ref<"previous" | "last_year">("previous");

const WINDOWS = [
  { days: 7, label: "Week" },
  { days: 30, label: "Month" },
  { days: 90, label: "Quarter" },
];

async function loadChart() {
  loading.value = true;
  // 9 weeks = 63 days
  const since = new Date();
  since.setDate(since.getDate() - 63);
  const [summaries, weight] = await Promise.all([
    api.summaryRange(since),
    api.weight({ since }).catch(() => ({ points: [] as { time: string; weight_kg: number | null }[] })),
  ]);
  // Last weight reading per local YYYY-MM-DD wins (daily weigh-in).
  const weightByDate = new Map<string, number>();
  for (const p of weight.points) {
    if (p.weight_kg == null) continue;
    // LOCAL day: this key is matched against daily_summary.date, which is
    // a local calendar day. A 9pm Central weigh-in maps to the next UTC
    // day and would silently fail to match its own row.
    const d = toLocalISO(new Date(p.time));
    weightByDate.set(d, p.weight_kg);
  }
  data.value = summaries.map((s) => ({
    ...s,
    weight_kg: weightByDate.get(s.date) ?? null,
  }));
  loading.value = false;
}

async function loadCompare() {
  cmpLoading.value = true;
  cmpError.value = null;
  try {
    cmp.value = await api.summaryCompare(days.value, vs.value);
  } catch {
    cmpError.value = "Couldn't load the comparison.";
    cmp.value = null;
  } finally {
    cmpLoading.value = false;
  }
}

onMounted(() => { loadChart(); loadCompare(); });
watch([days, vs], loadCompare);

/** Rows in the server's declared order, so this table and the phone agree. */
const rows = computed(() => {
  if (!cmp.value) return [];
  return cmp.value.order
    .filter((k) => cmp.value!.metrics[k])
    .map((k) => ({ key: k, ...cmp.value!.metrics[k] }));
});

/** The server reports weight in kg; the display unit is a local preference.
 *  Conversion is the only arithmetic left on this page, and it is a unit
 *  change rather than a derived statistic. */
function display(v: number | null, unit: string): { v: number | null; unit: string } {
  if (v !== null && unit === "kg") return { v: weightVal(v), unit: weightUnit.value };
  return { v, unit };
}

function fmt(v: number | null, unit: string): string {
  const d = display(v, unit);
  if (d.v === null) return "—";
  const n = d.unit === "" ? d.v.toFixed(1) : d.unit === "h" ? d.v.toFixed(2) : String(Math.round(d.v * 100) / 100);
  return d.unit ? `${n} ${d.unit}` : n;
}

function fmtDelta(v: number | null, unit: string): string {
  if (v === null) return "—";
  // weightVal converts an absolute weight; a *delta* in kg scales by the
  // same factor but must not have an offset applied, so convert via the
  // ratio rather than calling weightVal on the delta directly.
  const scaled = unit === "kg" ? v * ((weightVal(100) ?? 100) / 100) : v;
  return `${scaled > 0 ? "+" : ""}${Math.round(scaled * 100) / 100}`;
}

function pct(v: number | null): string {
  if (v === null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

const rangeLabel = computed(() => {
  if (!cmp.value) return "";
  const c = cmp.value.current;
  const b = cmp.value.baseline;
  return `${c.since} → ${c.until} vs ${b.since} → ${b.until}`;
});

const trendOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (data.value.length === 0) return null;
  return {
    grid: { left: 50, right: 50, top: 40, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: data.value.map((d) => d.date), axisLabel: t.axisLabel },
    yAxis: [
      { type: "value", axisLabel: t.axisLabel, splitLine: t.splitLine, name: "RHR/HRV", nameTextStyle: t.axisLabel },
      { type: "value", axisLabel: t.axisLabel, splitLine: { show: false }, name: "Score", nameTextStyle: t.axisLabel, position: "right" },
    ],
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      { name: "RHR", type: "line", smooth: true, yAxisIndex: 0, lineStyle: { color: t.palette.hr, width: 2 }, itemStyle: { color: t.palette.hr },
        data: data.value.map((d) => [d.date, d.resting_hr]), connectNulls: true },
      { name: "HRV", type: "line", smooth: true, yAxisIndex: 0, lineStyle: { color: t.palette.hrv, width: 2 }, itemStyle: { color: t.palette.hrv },
        data: data.value.map((d) => [d.date, d.hrv_avg]), connectNulls: true },
      { name: "Recovery", type: "line", smooth: true, yAxisIndex: 1, lineStyle: { color: t.palette.recovery, width: 2 }, itemStyle: { color: t.palette.recovery },
        data: data.value.map((d) => [d.date, d.recovery_score]), connectNulls: true },
    ],
  };
});
</script>

<template>
  <div>
    <h1>Compare</h1>
    <p class="hint">{{ rangeLabel || "Loading window…" }}</p>

    <div class="controls">
      <div class="seg">
        <button
          v-for="w in WINDOWS" :key="w.days"
          :class="{ on: days === w.days }"
          @click="days = w.days">{{ w.label }}</button>
      </div>
      <div class="seg">
        <button :class="{ on: vs === 'previous' }" @click="vs = 'previous'">vs previous</button>
        <button :class="{ on: vs === 'last_year' }" @click="vs = 'last_year'">vs last year</button>
      </div>
    </div>

    <Card :title="vs === 'previous' ? 'Period-over-period' : 'Year-over-year'">
      <div v-if="cmpLoading" class="empty">Loading…</div>
      <div v-else-if="cmpError" class="empty">{{ cmpError }}</div>
      <table v-else class="cmp">
        <thead>
          <tr>
            <th>Metric</th>
            <th>This period</th>
            <th>{{ vs === "previous" ? "Previous" : "Last year" }}</th>
            <th>Δ</th>
            <th>%</th>
            <th class="cov">Days</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.key" :class="{ thin: !r.sufficient }">
            <td class="m">{{ r.label }}</td>
            <td>{{ fmt(r.current, r.unit) }}</td>
            <td>{{ fmt(r.baseline, r.unit) }}</td>
            <!-- Colour comes from the server's `direction`, which already
                 accounts for whether up or down is the good way for this
                 metric. Do not re-derive it from the sign of the delta. -->
            <td :class="r.direction ?? ''">{{ fmtDelta(r.delta, r.unit) }}</td>
            <td :class="r.direction ?? ''">{{ pct(r.pct_change) }}</td>
            <td class="cov" :title="`${r.n_current} of ${cmp?.days} days this period, ${r.n_baseline} in the baseline`">
              {{ r.n_current }}/{{ r.n_baseline }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="rows.some((r) => !r.sufficient)" class="foot">
        Greyed rows cover under half the period on one side, so the average
        describes fewer days than the window claims.
      </p>
    </Card>

    <Card title="Past 9 weeks at a glance">
      <div class="chart"><VChart v-if="trendOption" :option="trendOption" autoresize/></div>
    </Card>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 1rem; font-variant-numeric: tabular-nums; }

.controls { display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 0 0 1rem; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button {
  background: transparent; border: 0; color: var(--muted);
  padding: 0.35rem 0.75rem; font-size: 0.82rem; cursor: pointer;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button.on { background: var(--surface-2); color: var(--text); }
.seg button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

.cmp { width: 100%; border-collapse: collapse; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
.cmp th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
.cmp td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--surface-2); color: var(--text); }
.cmp .m { color: var(--muted); }
.cmp tr.thin td { opacity: 0.5; }
.cmp .cov { color: var(--muted-2); font-size: 0.8rem; }
.cmp .improved { color: var(--good); font-weight: 500; }
.cmp .worse { color: var(--bad); font-weight: 500; }
.cmp .flat { color: var(--muted-2); }
/* `neutral` = the metric changed but has no universal good direction
   (bodyweight depends on whether you are cutting or bulking). Show the
   number, withhold the judgement. */
.cmp .neutral { color: var(--text); font-weight: 500; }
.foot { color: var(--muted-2); font-size: 0.78rem; margin: 0.8rem 0 0; }

.chart { width: 100%; height: 320px; }
.chart > * { width: 100%; height: 100%; }
.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
</style>
