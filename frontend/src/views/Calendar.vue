<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";
import { chartTheme } from "@/theme";

type Metric = "recovery_score" | "sleep_score" | "resting_hr" | "hrv_avg" | "steps_total" | "sleep_hours";

const METRICS: { key: Metric; label: string; reverse?: boolean; suffix?: string }[] = [
  { key: "recovery_score", label: "Recovery", suffix: "" },
  { key: "sleep_score", label: "Sleep score", suffix: "" },
  { key: "sleep_hours", label: "Sleep duration", suffix: "h" },
  { key: "hrv_avg", label: "HRV", suffix: "ms" },
  { key: "resting_hr", label: "Resting HR", suffix: "bpm", reverse: true },
  { key: "steps_total", label: "Steps", suffix: "" },
];

const metric = ref<Metric>("recovery_score");
const yearOffset = ref(0); // 0 = this year, -1 = last year, etc.
const data = ref<TodaySummary[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const drilldown = ref<TodaySummary | null>(null);

const year = computed(() => new Date().getFullYear() + yearOffset.value);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    // Pull a wide window — past 365 days
    const since = new Date();
    since.setDate(since.getDate() - 400);
    data.value = await api.summaryRange(since);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function valueOf(d: TodaySummary, m: Metric): number | null {
  if (m === "sleep_hours") return d.sleep_duration_s ? d.sleep_duration_s / 3600 : null;
  return d[m] as number | null;
}

const calendarOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  const m = metric.value;
  const meta = METRICS.find((x) => x.key === m)!;
  const filtered = data.value.filter((d) => new Date(d.date).getFullYear() === year.value);
  const heatData = filtered
    .map((d) => [d.date, valueOf(d, m)])
    .filter((p) => p[1] !== null && p[1] !== undefined) as [string, number][];

  const values = heatData.map(([, v]) => v);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 100;

  return {
    tooltip: {
      ...t.tooltip,
      formatter: (params: { value: [string, number] }) => {
        const [date, val] = params.value;
        return `<b>${date}</b><br/>${meta.label}: ${val.toFixed(1)} ${meta.suffix ?? ""}`;
      },
    },
    visualMap: {
      min, max,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 8,
      textStyle: t.axisLabel,
      inRange: meta.reverse
        ? { color: ["#22c55e", "#fde047", "#ef4444"] }
        : { color: ["#1e3a5f", "#7dd3fc", "#22c55e"] },
    },
    calendar: {
      top: 40, left: 30, right: 30,
      cellSize: ["auto", 16],
      range: year.value.toString(),
      // Calendar's own itemStyle sets the BACKGROUND for cells (empty days
      // would otherwise render white from ECharts' default). Match the
      // surrounding card background and use a soft border.
      itemStyle: {
        color: "#1a2332",
        borderColor: "rgba(148, 163, 184, 0.12)",
        borderWidth: 1,
      },
      splitLine: { show: false },
      yearLabel: { show: false },
      monthLabel: { color: t.axisLabel.color, fontSize: 11 },
      dayLabel: { color: t.axisLabel.color, fontSize: 9 },
    },
    series: {
      type: "heatmap",
      coordinateSystem: "calendar",
      data: heatData,
    },
  };
});

function onClickCell(params: unknown) {
  const d = (params as { data?: [string, number] }).data;
  if (!d) return;
  const date = d[0];
  drilldown.value = data.value.find((s) => s.date === date) ?? null;
}
</script>

<template>
  <div class="calendar">
    <header class="head">
      <h1>Calendar</h1>
      <div class="ctrls">
        <select v-model="metric" class="sel">
          <option v-for="m in METRICS" :key="m.key" :value="m.key">{{ m.label }}</option>
        </select>
        <div class="year-pick">
          <button @click="yearOffset--">‹</button>
          <span>{{ year }}</span>
          <button :disabled="yearOffset >= 0" @click="yearOffset++">›</button>
        </div>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>

    <Card v-else :title="`${METRICS.find((m) => m.key === metric)?.label} · ${year}`">
      <div class="cal-wrap">
        <VChart :option="calendarOption" autoresize @click="(p: any) => onClickCell(p)"/>
      </div>
    </Card>

    <Card v-if="drilldown" :title="`${drilldown.date} detail`">
      <div class="kv">
        <div v-if="drilldown.recovery_score !== null"><dt>Recovery</dt><dd>{{ drilldown.recovery_score!.toFixed(0) }}</dd></div>
        <div v-if="drilldown.resting_hr !== null"><dt>RHR</dt><dd>{{ drilldown.resting_hr!.toFixed(0) }} bpm</dd></div>
        <div v-if="drilldown.hrv_avg !== null"><dt>HRV</dt><dd>{{ drilldown.hrv_avg!.toFixed(0) }} ms</dd></div>
        <div v-if="drilldown.sleep_score !== null"><dt>Sleep score</dt><dd>{{ drilldown.sleep_score!.toFixed(0) }}</dd></div>
        <div v-if="drilldown.sleep_duration_s !== null">
          <dt>Sleep dur</dt>
          <dd>{{ Math.floor(drilldown.sleep_duration_s! / 3600) }}h {{ Math.floor((drilldown.sleep_duration_s! % 3600) / 60) }}m</dd>
        </div>
        <div v-if="drilldown.steps_total !== null"><dt>Steps</dt><dd>{{ drilldown.steps_total!.toLocaleString() }}</dd></div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }
h1 { margin: 0; }
.ctrls { display: flex; gap: 1rem; align-items: center; }
.sel {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.4rem 0.6rem; font-size: 0.85rem; font-family: inherit;
}
.year-pick { display: flex; gap: 0.5rem; align-items: center; color: var(--muted); }
.year-pick button {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; padding: 0.2rem 0.6rem;
}
.year-pick button:disabled { opacity: 0.4; cursor: not-allowed; }
.year-pick span { font-weight: 600; min-width: 50px; text-align: center; }

.cal-wrap { width: 100%; height: 220px; }
.cal-wrap > * { width: 100%; height: 100%; }

.kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.6rem 1.2rem; }
.kv > div { display: flex; flex-direction: column; }
.kv dt { color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }
.kv dd { margin: 0.2rem 0 0; color: var(--text); font-weight: 500; font-size: 1.1rem; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
