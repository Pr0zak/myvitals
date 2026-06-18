<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import PageHeader from "@/components/PageHeader.vue";
import RangeTabs from "@/components/RangeTabs.vue";
import PatternsLink from "@/components/PatternsLink.vue";
import Skeleton from "@/components/Skeleton.vue";
import { api } from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import type { SleepNight } from "@/api/types";
import { chartTheme, isNeon } from "@/theme";
import { fmtTime, fmtDateTime } from "@/format";

// Classic stage palette (byte-for-byte unchanged for non-neon themes).
const STAGE_COLORS_CLASSIC: Record<string, string> = {
  awake: "#f97316",
  rem: "#a78bfa",
  light: "#60a5fa",
  deep: "#1e40af",
  out_of_bed: "#94a3b8",
  unknown: "#64748b",
};
// Vitality Neon sleep-stage palette.
const STAGE_COLORS_NEON: Record<string, string> = {
  awake: "#ffb52e",
  rem: "#28e6ff",
  light: "#6f7bff",
  deep: "#ff3ad8",
  out_of_bed: "#9b9bb0",
  unknown: "#9b9bb0",
};
const stageColors = computed<Record<string, string>>(() =>
  isNeon.value ? STAGE_COLORS_NEON : STAGE_COLORS_CLASSIC,
);

// Order top-to-bottom in the hypnogram (REM is shallowest after awake)
const STAGE_ORDER = ["awake", "rem", "light", "deep"];

const nights = ref<SleepNight[]>([]);
const lastNightRaw = ref<{ time: string; stage: string; duration_s: number }[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const range = ref<7 | 30 | 90>(30);
const SLEEP_RANGES: ReadonlyArray<{ key: 7 | 30 | 90; label: string }> = [
  { key: 7, label: "7 days" },
  { key: 30, label: "30 days" },
  { key: 90, label: "90 days" },
];
watch(range, load);
// Sleep target from profile (GOALS-2). Drives the markLine on the
// stacked-nights chart so the user can see at a glance which nights
// hit their goal.
const sleepTargetH = ref<number | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date();
    since.setDate(since.getDate() - range.value);
    const [n, raw, prof] = await Promise.all([
      api.sleepRange(since),
      api.sleepRaw(new Date(Date.now() - 36 * 3600 * 1000)),
      api.getProfile().catch(() => null),
    ]);
    nights.value = n;
    lastNightRaw.value = raw;
    sleepTargetH.value = (prof as { sleep_target_h?: number | null } | null)
      ?.sleep_target_h ?? null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const lastNight = computed(() => nights.value[nights.value.length - 1] ?? null);

function fmtDur(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}


function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// === Hypnogram of the most recent night ===
// Real hypnogram: time on X, stage on categorical Y (deep at bottom, awake top).
// Use a step line that jumps between stages, plus markArea bands colored per
// segment so the eye reads it like a Fitbit/Garmin sleep chart.
const STAGE_Y_INDEX: Record<string, number> = {
  deep: 0, light: 1, rem: 2, awake: 3, out_of_bed: 3, unknown: 1,
};
const Y_LABELS = ["Deep", "Light", "REM", "Awake"];

const hypnogramOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const STAGE_COLORS = stageColors.value;
  if (lastNightRaw.value.length === 0) return null;

  // Group raw rows into the most recent contiguous session (gap > 2h splits).
  const sorted = [...lastNightRaw.value].sort(
    (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime(),
  );
  const sessions: typeof sorted[] = [];
  let cur: typeof sorted = [];
  for (const row of sorted) {
    if (cur.length > 0) {
      const last = cur[cur.length - 1];
      const gap = new Date(row.time).getTime() - new Date(last.time).getTime();
      if (gap > 2 * 3600 * 1000) {
        sessions.push(cur);
        cur = [];
      }
    }
    cur.push(row);
  }
  if (cur.length > 0) sessions.push(cur);
  const session = sessions[sessions.length - 1];
  if (!session || session.length === 0) return null;

  // Step line: for each stage row, emit two points (start and end) at its Y.
  const linePts: [number, number][] = [];
  // markArea: one rect per stage row, full-height vertical band colored by stage.
  const areas: any[] = [];
  for (const row of session) {
    const start = new Date(row.time).getTime();
    const end = start + row.duration_s * 1000;
    const y = STAGE_Y_INDEX[row.stage] ?? 1;
    linePts.push([start, y]);
    linePts.push([end, y]);
    areas.push([
      { xAxis: row.time, itemStyle: { color: (STAGE_COLORS[row.stage] ?? "#64748b") + "30" } },
      { xAxis: new Date(end).toISOString() },
    ]);
  }

  return {
    grid: { left: 60, right: 12, top: 16, bottom: 30 },
    xAxis: {
      type: "time",
      axisLabel: { ...t.axisLabel, formatter: (v: number) => fmtTime(v) },
      splitLine: { show: false },
    },
    yAxis: {
      type: "category",
      data: Y_LABELS,
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
    },
    tooltip: {
      trigger: "axis",
      ...t.tooltip,
      formatter: (params: any[]) => {
        const p = params[0];
        if (!p) return "";
        const t = new Date(p.value[0]);
        return `${fmtTime(t)}<br/><b>${Y_LABELS[p.value[1]]}</b>`;
      },
    },
    series: [{
      type: "line",
      step: "end" as const,
      showSymbol: false,
      lineStyle: { color: isNeon.value ? "#ff3ad8" : t.palette.violet, width: 2 },
      data: linePts,
      markArea: { silent: true, data: areas },
    }],
  };
});

// === Last N nights stacked bar ===
const stackedNightsOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const STAGE_COLORS = stageColors.value;
  const dates = nights.value.map((n) => n.date);
  const allStages = Array.from(new Set(nights.value.flatMap((n) => n.stages.map((s) => s.stage))));
  const orderedStages = [...STAGE_ORDER, ...allStages.filter((s) => !STAGE_ORDER.includes(s))];

  const series: any[] = orderedStages.filter((s) => allStages.includes(s)).map((stage) => ({
    name: stage,
    type: "bar",
    stack: "sleep",
    data: nights.value.map((n) => {
      const s = n.stages.find((x) => x.stage === stage);
      return s ? +(s.duration_s / 60).toFixed(0) : 0;
    }),
    itemStyle: { color: STAGE_COLORS[stage] ?? "#64748b" },
  }));

  // Sleep target markLine (GOALS-2). Attached to the first series so
  // it renders once across the full chart width. Skipped when no
  // target is configured.
  if (sleepTargetH.value != null && series.length > 0) {
    const targetMin = sleepTargetH.value * 60;
    const targetColor = isNeon.value ? "#5dff3b" : t.palette.recovery;
    series[0] = {
      ...series[0],
      markLine: {
        silent: true,
        symbol: ["none", "none"],
        data: [{
          yAxis: targetMin,
          lineStyle: { color: targetColor, type: "dashed" as const, width: 1.5, opacity: 0.7 },
          label: {
            formatter: `Target ${sleepTargetH.value!.toFixed(1)}h`,
            color: targetColor,
            fontSize: 10,
            position: "insideEndTop",
          },
        }],
      },
    };
  }

  return {
    grid: { left: 50, right: 12, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: dates, axisLabel: t.axisLabel },
    yAxis: { type: "value", name: "minutes", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: t.axisLabel },
    tooltip: { trigger: "axis", ...t.tooltip },
    series,
    dataZoom: [{ type: "inside" }],
  };
});

// === Bedtime / wake time consistency scatter ===
const consistencyOption = computed(() => {
  void chartTheme.value;
  void isNeon.value;
  const t = chartTheme.value;
  const bedColor = isNeon.value ? "#ff3ad8" : t.palette.violet;
  const wakeColor = isNeon.value ? "#28e6ff" : t.palette.steps;
  // Map each night to (date, fractional hour of bedtime) and (date, fractional hour of wake).
  // Bedtime can wrap past midnight; encode hours since 18:00 to keep them positive.
  const bedData: [string, number][] = [];
  const wakeData: [string, number][] = [];
  for (const n of nights.value) {
    const start = new Date(n.start);
    const end = new Date(n.end);
    const bedH = ((start.getHours() + start.getMinutes() / 60) - 18 + 24) % 24;
    const wakeH = (end.getHours() + end.getMinutes() / 60);
    bedData.push([n.date, +bedH.toFixed(2)]);
    wakeData.push([n.date, +wakeH.toFixed(2)]);
  }
  return {
    grid: { left: 50, right: 50, top: 30, bottom: 28 },
    legend: { textStyle: t.axisLabel, top: 4 },
    xAxis: { type: "category", data: nights.value.map((n) => n.date), axisLabel: t.axisLabel },
    yAxis: [
      { type: "value", name: "bedtime (h after 6pm)", axisLabel: t.axisLabel, splitLine: t.splitLine, nameTextStyle: { color: bedColor, fontSize: 9 } },
      { type: "value", name: "wake hour", axisLabel: t.axisLabel, splitLine: { show: false }, position: "right", nameTextStyle: { color: wakeColor, fontSize: 9 } },
    ],
    tooltip: { trigger: "axis", ...t.tooltip },
    series: [
      { name: "Bedtime", type: "scatter", yAxisIndex: 0, symbolSize: 8, data: bedData, itemStyle: { color: bedColor } },
      { name: "Wake", type: "scatter", yAxisIndex: 1, symbolSize: 8, data: wakeData, itemStyle: { color: wakeColor } },
    ],
  };
});

const stats = computed(() => {
  if (nights.value.length === 0) return null;
  const totals = nights.value.map((n) => n.total_s);
  const avg = totals.reduce((a, b) => a + b, 0) / totals.length;
  const min = Math.min(...totals);
  const max = Math.max(...totals);
  return { avg, min, max, count: nights.value.length };
});

// Most-recent-first, capped at the visible window (default 7 nights;
// expandable up to whatever the range pull returned).
const expandedRecent = ref(false);
const allRecentNights = computed(() =>
  [...nights.value].sort((a, b) => b.start.localeCompare(a.start)),
);
const recentNights = computed(() =>
  expandedRecent.value
    ? allRecentNights.value
    : allRecentNights.value.slice(0, 7),
);

function fmtNightDate(n: SleepNight): string {
  // Show the *evening* the night belongs to (i.e. the day before
  // the wake-up date) if the start is past midnight.
  const startD = new Date(n.start);
  const opts = { weekday: "short", month: "short", day: "numeric" } as const;
  return startD.toLocaleDateString(undefined, opts);
}
</script>

<template>
  <div class="sleep">
    <PageHeader title="Sleep">
      <RangeTabs v-model="range" :options="SLEEP_RANGES" aria-label="Sleep time range">
        <template #before>
          <PatternsLink metric="sleep_score" label="sleep"/>
        </template>
      </RangeTabs>
    </PageHeader>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="sleep-skel">
      <Skeleton width="100%" height="180px" radius="12px"/>
      <Skeleton width="100%" height="60px" radius="12px"/>
      <Skeleton width="100%" height="60px" radius="12px"/>
    </div>
    <div v-else-if="nights.length === 0" class="empty">
      No sleep sessions in this range. Make sure your watch is logging sleep + Fitbit is sharing it with Health Connect.
    </div>

    <div v-if="lastNight" class="last-banner">
      <span class="dot" :style="{ background: 'var(--violet)' }"></span>
      Last sleep logged: <strong>{{ fmtDateTime(lastNight.end) }}</strong>
      <span class="rel">({{ relativeTime(lastNight.end) }})</span>
    </div>

    <div v-if="!loading && nights.length > 0" class="grid">
      <Card v-if="lastNight" title="Last night — hypnogram"
            :subtitle="`${fmtTime(new Date(lastNight.start))} → ${fmtTime(new Date(lastNight.end))}  ·  ${fmtDur(lastNight.total_s)}`">
        <div class="chart hypno"><VChart v-if="hypnogramOption" :option="hypnogramOption" autoresize/></div>
        <div class="legend">
          <span v-for="s in lastNight.stages" :key="s.stage" class="lg-item">
            <span class="dot" :style="{ background: stageColors[s.stage] ?? '#64748b' }"></span>
            {{ s.stage }} {{ Math.round(s.duration_s / 60) }} min
          </span>
        </div>
      </Card>

      <Card title="Recent nights"
            :subtitle="`${expandedRecent ? allRecentNights.length : Math.min(7, allRecentNights.length)} of ${allRecentNights.length} · bed → wake → total`">
        <!-- Range stats — moved into this card per the redesign -->
        <div v-if="stats" class="rn-stats">
          <div class="rn-stat">
            <span class="rn-stat-label">Avg</span>
            <span class="rn-stat-val mono">{{ fmtDur(stats.avg) }}</span>
          </div>
          <div class="rn-stat">
            <span class="rn-stat-label">Min</span>
            <span class="rn-stat-val mono">{{ fmtDur(stats.min) }}</span>
          </div>
          <div class="rn-stat">
            <span class="rn-stat-label">Max</span>
            <span class="rn-stat-val mono">{{ fmtDur(stats.max) }}</span>
          </div>
          <div class="rn-stat">
            <span class="rn-stat-label">Nights</span>
            <span class="rn-stat-val mono">{{ stats.count }}</span>
          </div>
        </div>

        <ul class="recent-nights">
          <li v-for="n in recentNights" :key="n.date">
            <span class="rn-date">{{ fmtNightDate(n) }}</span>
            <span class="rn-window mono">
              {{ fmtTime(new Date(n.start)) }}
              <span class="dim">→</span>
              {{ fmtTime(new Date(n.end)) }}
            </span>
            <span class="rn-bar" :style="{ width: `${(n.total_s / Math.max(...recentNights.map(x => x.total_s))) * 100}%` }"></span>
            <span class="rn-total mono">{{ fmtDur(n.total_s) }}</span>
          </li>
        </ul>

        <button v-if="allRecentNights.length > 7"
                class="rn-toggle"
                @click="expandedRecent = !expandedRecent">
          {{ expandedRecent
              ? `Show last 7 only`
              : `Show all ${allRecentNights.length} nights →` }}
        </button>
      </Card>

      <Card title="Per-night stage breakdown">
        <div class="chart"><VChart :option="stackedNightsOption" autoresize/></div>
      </Card>

      <Card title="Bedtime / wake-time consistency">
        <div class="chart"><VChart :option="consistencyOption" autoresize/></div>
      </Card>
    </div>
  </div>
</template>

<style scoped>

.grid { display: grid; gap: 1rem; margin-top: 1rem; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); }
.chart { width: 100%; height: 280px; }
.chart.small { height: 100px; }
.chart.hypno { height: 200px; }
.chart > * { width: 100%; height: 100%; }

.legend { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.5rem; font-size: 0.8rem; color: var(--muted); }
.lg-item { display: inline-flex; align-items: center; gap: 0.3rem; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }

.kv { display: flex; gap: 2rem; margin-top: 0.5rem; }
.kv > div { display: flex; flex-direction: column; }
.kv dt { color: var(--muted-2); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.kv dd { margin: 0.2rem 0 0; color: var(--text); font-weight: 500; font-size: 1.4rem; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.sleep-skel { display: flex; flex-direction: column; gap: 0.6rem; margin: 1rem 0; }

.rn-stats {
  display: flex; gap: 1.4rem;
  padding: 0 0.4rem 0.85rem;
  margin-bottom: 0.85rem;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.rn-stat { display: flex; flex-direction: column; gap: 0.15rem; }
.rn-stat-label {
  font-size: 0.65rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
.rn-stat-val {
  color: var(--text); font-size: 1.15rem; font-weight: 500;
  font-feature-settings: "tnum";
}
.rn-toggle {
  margin-top: 0.7rem; align-self: flex-start;
  background: transparent; border: none; cursor: pointer;
  color: var(--accent, #ef4444); font-size: 0.82rem;
  padding: 0.3rem 0; font-family: inherit;
}
.rn-toggle:hover { text-decoration: underline; }

.recent-nights {
  list-style: none; padding: 0; margin: 0;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.recent-nights li {
  display: grid;
  grid-template-columns: minmax(80px, auto) minmax(140px, auto) 1fr auto;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.6rem;
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 0.85rem;
}
.rn-date { color: var(--text); font-weight: 500; white-space: nowrap; }
.rn-window {
  color: var(--text); font-size: 0.78rem; white-space: nowrap;
  font-feature-settings: "tnum";
}
.rn-window .dim { color: var(--muted); margin: 0 4px; }
.rn-bar {
  display: block; height: 6px; max-width: 200px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(167,139,250,0.3), rgba(167,139,250,0.7));
  justify-self: stretch;
}
.rn-total {
  color: var(--text); font-weight: 600; font-size: 0.88rem;
  font-feature-settings: "tnum"; white-space: nowrap;
}
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }

.last-banner {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.6rem 0.9rem; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; margin: 0.5rem 0 1rem; font-size: 0.9rem; color: var(--muted);
}
.last-banner strong { color: var(--text); }
.last-banner .rel { color: var(--muted-2); font-size: 0.85rem; margin-left: auto; }

/* ===== Vitality Neon — scoped overrides (neon theme only) ===== */
html[data-theme="neon"] .sleep {
  --rn-mag: #ff3ad8; --rn-cyan: #28e6ff; --rn-lime: #5dff3b;
  --rn-amber: #ffb52e; --rn-track: #272a3b; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 1.25rem 1.5rem 2rem;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink);
}

/* Big numeric readouts → Space Grotesk monospace */
html[data-theme="neon"] .sleep .rn-stat-val,
html[data-theme="neon"] .sleep .rn-total,
html[data-theme="neon"] .sleep .rn-window {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
}
html[data-theme="neon"] .sleep .rn-stat-val { color: var(--rn-ink); }
html[data-theme="neon"] .sleep .rn-stat-label { color: var(--rn-mut); }

/* Recent-night duration bar → neon sleep magenta gradient + glow */
html[data-theme="neon"] .sleep .rn-bar {
  background: linear-gradient(90deg, rgba(255, 58, 216, 0.28), rgba(255, 58, 216, 0.85));
  box-shadow: 0 0 6px rgba(255, 58, 216, 0.45);
}

/* Last-sleep banner dot → magenta glow */
html[data-theme="neon"] .sleep .last-banner .dot {
  background: var(--rn-mag) !important;
  box-shadow: 0 0 7px rgba(255, 58, 216, 0.7);
}

/* Toggle accent → cyan */
html[data-theme="neon"] .sleep .rn-toggle { color: var(--rn-cyan); }

/* Per-night row chrome reads slightly brighter against the obsidian bg */
html[data-theme="neon"] .sleep .recent-nights li {
  border-color: #2a2e42;
}
</style>
