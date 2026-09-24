<script setup lang="ts">
/**
 * Sleep detail (UI-4). Phone twin: `SleepDetailScreen.kt`.
 *
 *   hero     the latest night: duration, the server's verdict chip, and the
 *            hypnogram with its legend inline
 *   stats    avg / shortest / longest night — the server's sleep block from
 *            `/summary/range/stats` (naps excluded THERE, not here)
 *   below    recent nights, per-night stage stack, bedtime consistency
 *
 * Stage colours are tokens: deep = periwinkle, light/core = periwinkle 60%,
 * REM = magenta, awake = amber. Deep used to be navy on a near-black card —
 * the stage that matters most was the one you could not see.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import { Moon } from "lucide-vue-next";
import RangeTabs from "@/components/RangeTabs.vue";
import PatternsLink from "@/components/PatternsLink.vue";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import StatusChip from "@/components/detail/StatusChip.vue";
import DetailCard from "@/components/detail/DetailCard.vue";
import DetailSkeleton from "@/components/detail/DetailSkeleton.vue";
import DetailError from "@/components/detail/DetailError.vue";
import "@/components/detail/detail.css";
import { api, summaryRangeStats } from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import type { RangeStats, SleepNight, VitalTile } from "@/api/types";
import { chartTheme } from "@/theme";
import { toLocalISO } from "@/dates";
import { zeroAxisIncluding } from "@/chartAxis";
import { fmtTime } from "@/format";

const MAG = "#ff3ad8";
const TRACK = "#272a3b";
const STAGE_COLORS: Record<string, string> = {
  deep: "#6f7bff",
  light: "rgba(111, 123, 255, 0.6)",
  core: "rgba(111, 123, 255, 0.6)",
  rem: "#ff3ad8",
  awake: "#ffb52e",
  wake: "#ffb52e",
  asleep: "rgba(111, 123, 255, 0.8)",
  restless: "rgba(255, 181, 46, 0.55)",
  out_of_bed: "#9b9bb0",
  unmeasurable: "rgba(155, 155, 176, 0.6)",
  unknown: "rgba(155, 155, 176, 0.6)",
};
const stageColor = (s: string) => STAGE_COLORS[s] ?? "#9b9bb0";
/** Shallowest first; the hypnogram draws only the stages present. */
const HYPNO_ORDER = ["awake", "wake", "restless", "rem", "light", "core", "asleep", "deep"];
const STACK_ORDER = ["deep", "asleep", "light", "core", "rem", "restless", "awake", "wake"];

type Raw = { time: string; stage: string; duration_s: number };
const nights = ref<SleepNight[]>([]);
const raw = ref<Raw[]>([]);
const stats = ref<RangeStats | null>(null);
const tile = ref<VitalTile | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const range = ref<7 | 14 | 30 | 90>(14);
const RANGES: ReadonlyArray<{ key: 7 | 14 | 30 | 90; label: string }> = [
  { key: 7, label: "7 nights" }, { key: 14, label: "14" }, { key: 30, label: "30" }, { key: 90, label: "90" },
];

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't reach the backend.";
}

async function load() {
  loading.value = true;
  try {
    const today = new Date();
    const first = new Date(); first.setDate(first.getDate() - (range.value - 1));
    // The same local window the stats endpoint uses — a night belongs to
    // the day it ends, so start 18:00 the evening before the first day.
    const nightsSince = new Date(first); nightsSince.setDate(nightsSince.getDate() - 1);
    nightsSince.setHours(18, 0, 0, 0);
    const [n, r, s, tiles] = await Promise.all([
      api.sleepRange(nightsSince),
      api.sleepRaw(new Date(Date.now() - 36 * 3600 * 1000)),
      summaryRangeStats(toLocalISO(first), toLocalISO(today)),
      api.summaryTiles().catch(() => null),
    ]);
    nights.value = n;
    raw.value = r;
    stats.value = s;
    tile.value = tiles?.tiles.find((t) => t.key === "sleep_duration") ?? null;
    error.value = null;
  } catch (e) {
    error.value = errText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useVisibilityRefresh(load);
watch(range, load);

const hasContent = computed(() => nights.value.length > 0 || stats.value != null);
const lastNight = computed(() => {
  const real = nights.value.filter((n) => n.kind !== "nap");
  return real[real.length - 1] ?? null;
});
const ss = computed(() => stats.value?.sleep ?? null);
function fmtDur(s: number | null | undefined): string {
  if (s == null) return "—";
  const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
const axis = computed(() => chartTheme.value.axisLabel);
const split = { lineStyle: { color: TRACK } };

/** The most recent contiguous session in the raw rows (a 2h gap splits). */
const session = computed<Raw[]>(() => {
  const sorted = [...raw.value].sort((a, b) => a.time.localeCompare(b.time));
  let cur: Raw[] = [];
  const out: Raw[][] = [];
  for (const row of sorted) {
    const last = cur[cur.length - 1];
    if (last && new Date(row.time).getTime() - new Date(last.time).getTime() > 2 * 3600 * 1000) {
      out.push(cur); cur = [];
    }
    cur.push(row);
  }
  if (cur.length) out.push(cur);
  return out[out.length - 1] ?? [];
});
const presentStages = computed(() => {
  const set = new Set(session.value.map((r) => r.stage.toLowerCase()));
  return HYPNO_ORDER.filter((s) => set.has(s));
});

const hypnogramOption = computed(() => {
  const rows = presentStages.value;
  if (!session.value.length || !rows.length) return null;
  // One custom bar per segment, on its stage's row.
  const data = session.value.map((r) => {
    const st = r.stage.toLowerCase();
    const s0 = new Date(r.time).getTime();
    return { value: [rows.indexOf(st), s0, s0 + r.duration_s * 1000], itemStyle: { color: stageColor(st) } };
  }).filter((d) => d.value[0] >= 0);
  return {
    grid: { left: 58, right: 8, top: 6, bottom: 22 },
    xAxis: { type: "time", axisLabel: { ...axis.value, formatter: (v: number) => fmtTime(v) }, splitLine: { show: false } },
    yAxis: { type: "category", data: rows, inverse: true, axisLabel: axis.value, axisTick: { show: false },
             splitLine: { show: true, lineStyle: { color: TRACK } } },
    tooltip: { ...chartTheme.value.tooltip,
               formatter: (p: any) => `${rows[p.value[0]]}<br/>${fmtTime(p.value[1])} → ${fmtTime(p.value[2])}` },
    series: [{
      type: "custom",
      renderItem: (_: unknown, api: any) => {
        const y = api.value(0);
        const start = api.coord([api.value(1), y]);
        const end = api.coord([api.value(2), y]);
        const h = api.size([0, 1])[1] * 0.66;
        return { type: "rect", shape: { x: start[0], y: start[1] - h / 2, width: Math.max(1, end[0] - start[0]), height: h, r: 2 },
                 style: api.style() };
      },
      encode: { x: [1, 2], y: 0 },
      data,
    }],
  };
});

const lastStageMinutes = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {};
  for (const s of lastNight.value?.stages ?? []) out[s.stage.toLowerCase()] = Math.round(s.duration_s / 60);
  return out;
});

/** Nights on a continuous day axis, null where none was recorded. */
function onDayAxis(list: SleepNight[]): Array<{ date: string; night: SleepNight | null }> {
  if (!list.length) return [];
  const byDate = new Map(list.map((n) => [n.date, n]));
  const times = list.map((n) => new Date(n.date + "T00:00:00").getTime()).filter(Number.isFinite);
  const first = Math.min(...times);
  const days = Math.round((Math.max(...times) - first) / 86_400_000);
  if (days < 0 || days > 400) return list.map((n) => ({ date: n.date, night: n }));
  return Array.from({ length: days + 1 }, (_, i) => {
    const d = toLocalISO(new Date(first + i * 86_400_000));
    return { date: d, night: byDate.get(d) ?? null };
  });
}

const stackedOption = computed(() => {
  const slots = onDayAxis(nights.value);
  if (!slots.length) return null;
  const present = new Set(nights.value.flatMap((n) => n.stages.map((s) => s.stage.toLowerCase())));
  const order = [...STACK_ORDER.filter((s) => present.has(s)), ...[...present].filter((s) => !STACK_ORDER.includes(s))];
  const series: any[] = order.map((stage) => ({
    name: stage, type: "bar", stack: "sleep", barWidth: "70%",
    // null, not 0, for a day with no night — an unrecorded night is not
    // a night of zero sleep.
    data: slots.map(({ night }) => {
      if (!night) return null;
      const s = night.stages.filter((x) => x.stage.toLowerCase() === stage).reduce((a, x) => a + x.duration_s, 0);
      return Math.round(s / 60);
    }),
    itemStyle: { color: stageColor(stage) },
  }));
  const target = tile.value?.target ?? null;
  if (target != null && series.length) {
    series[0].markLine = { silent: true, symbol: ["none", "none"], data: [{
      yAxis: target * 60, lineStyle: { color: "#ececf5", type: "dashed" as const, opacity: 0.55 },
      label: { formatter: `target ${target.toFixed(1)}h`, color: "#9b9bb0", fontSize: 9, position: "insideEndTop" },
    }] };
  }
  return {
    grid: { left: 40, right: 8, top: 14, bottom: 24 },
    xAxis: { type: "category", data: slots.map((s) => s.date.slice(5)), axisLabel: axis.value },
    yAxis: { type: "value", axisLabel: { ...axis.value, formatter: (v: number) => `${Math.round(v / 60)}h` }, splitLine: split,
             ...zeroAxisIncluding(nights.value.map((n) => n.stages.reduce((a, x) => a + x.duration_s / 60, 0)),
                                  target != null ? target * 60 : null) },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series,
  };
});
const stackLegend = computed(() => {
  const present = new Set(nights.value.flatMap((n) => n.stages.map((s) => s.stage.toLowerCase())));
  return STACK_ORDER.filter((s) => present.has(s));
});

const consistencyOption = computed(() => {
  if (!nights.value.length) return null;
  const bed: [string, number][] = [];
  const wake: [string, number][] = [];
  for (const n of nights.value) {
    const s = new Date(n.start); const e = new Date(n.end);
    bed.push([n.date, +((((s.getHours() + s.getMinutes() / 60) - 18 + 24) % 24).toFixed(2))]);
    wake.push([n.date, +((e.getHours() + e.getMinutes() / 60).toFixed(2))]);
  }
  return {
    legend: { textStyle: axis.value, top: 0 },
    grid: { left: 40, right: 40, top: 28, bottom: 24 },
    xAxis: { type: "category", data: nights.value.map((n) => n.date.slice(5)), axisLabel: axis.value },
    yAxis: [
      { type: "value", name: "bed (h after 6pm)", axisLabel: axis.value, splitLine: split, nameTextStyle: { color: MAG, fontSize: 9 } },
      { type: "value", name: "wake hour", axisLabel: axis.value, splitLine: { show: false }, nameTextStyle: { color: "#28e6ff", fontSize: 9 } },
    ],
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [
      { name: "Bedtime", type: "scatter", yAxisIndex: 0, symbolSize: 8, data: bed, itemStyle: { color: MAG } },
      { name: "Wake", type: "scatter", yAxisIndex: 1, symbolSize: 8, data: wake, itemStyle: { color: "#28e6ff" } },
    ],
  };
});

const expanded = ref(false);
const recent = computed(() => {
  const all = [...nights.value].sort((a, b) => b.start.localeCompare(a.start));
  return expanded.value ? all : all.slice(0, 7);
});
const recentMax = computed(() => Math.max(1, ...recent.value.map((n) => n.total_s)));
</script>

<template>
  <NeonPage title="Sleep" :back="true">
    <template #trailing><span class="dicon" style="--a: #ff3ad8"><Moon :size="20" /></span></template>
    <div class="dtabs">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Sleep time range">
        <template #before><PatternsLink metric="sleep_score" label="sleep"/></template>
      </RangeTabs>
    </div>

    <template v-if="!hasContent">
      <DetailSkeleton v-if="loading" :accent="MAG" label="Sleep" />
      <DetailError v-else-if="error" :error="error" @retry="load" />
      <p v-else class="dnote">
        No sleep sessions in this range. Make sure your watch is logging sleep and sharing it with Health Connect.
      </p>
    </template>

    <template v-else>
      <DetailError v-if="error" :error="error" cached @retry="load" />
      <NeonHero :accent="MAG">
        <span class="deb">Last night</span>
        <span class="dbig" :style="{ color: MAG }">{{ fmtDur(lastNight?.total_s) }}</span>
        <span class="dsubline">
          {{ lastNight ? `${fmtTime(new Date(lastNight.start))} → ${fmtTime(new Date(lastNight.end))}` : "No night recorded" }}
        </span>
        <StatusChip :status="tile?.status" :text="tile?.status_reason" />
        <div v-if="hypnogramOption" class="dchart" :style="{ height: `${Math.max(96, presentStages.length * 28 + 30)}px` }">
          <VChart :option="hypnogramOption" autoresize/>
        </div>
        <p v-else class="dnote">No stage detail synced for this night yet.</p>
        <div v-if="presentStages.length" class="dlegend">
          <span v-for="s in presentStages" :key="s">
            <i :style="{ background: stageColor(s) }"></i>{{ s }}<template v-if="lastStageMinutes[s] != null"> {{ lastStageMinutes[s] }}m</template>
          </span>
        </div>
      </NeonHero>

      <div class="dstats">
        <NeonStat :value="fmtDur(ss?.avg_s)" label="Avg night" :accent="MAG" />
        <NeonStat :value="fmtDur(ss?.min_s)" label="Shortest" />
        <NeonStat :value="fmtDur(ss?.max_s)" label="Longest" />
      </div>
      <p v-if="ss" class="dnote">
        {{ ss.nights }} night{{ ss.nights === 1 ? "" : "s" }} in this window<template v-if="ss.naps"> · {{ ss.naps }} nap{{ ss.naps === 1 ? "" : "s" }} not counted</template>
      </p>

      <DetailCard v-if="stackedOption" title="Stage breakdown">
        <div class="dchart tall"><VChart :option="stackedOption" autoresize/></div>
        <div class="dlegend"><span v-for="s in stackLegend" :key="s"><i :style="{ background: stageColor(s) }"></i>{{ s }}</span></div>
      </DetailCard>

      <DetailCard title="Recent nights" subtitle="bed → wake · total">
        <ul class="rn">
          <li v-for="n in recent" :key="`${n.date}-${n.start}`">
            <span class="rd">{{ new Date(n.start).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) }}
              <em v-if="n.kind === 'nap'">nap</em></span>
            <span class="rw">{{ fmtTime(new Date(n.start)) }} → {{ fmtTime(new Date(n.end)) }}</span>
            <span class="rb" :style="{ width: `${(n.total_s / recentMax) * 100}%` }"></span>
            <b>{{ fmtDur(n.total_s) }}</b>
          </li>
        </ul>
        <button v-if="nights.length > 7" class="rt" @click="expanded = !expanded">
          {{ expanded ? "Show last 7 only" : `Show all ${nights.length} sessions →` }}
        </button>
      </DetailCard>

      <DetailCard v-if="consistencyOption" title="Bedtime / wake consistency">
        <div class="dchart tall"><VChart :option="consistencyOption" autoresize/></div>
      </DetailCard>
    </template>
  </NeonPage>
</template>

<style scoped>
.rn { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.rn li { display: grid; grid-template-columns: minmax(90px, auto) minmax(120px, auto) 1fr auto; gap: 10px;
  align-items: center; font-size: 12.5px; }
.rd { color: #ececf5; white-space: nowrap; }
.rd em { font-style: normal; font-size: 10px; color: #9b9bb0; border: 1px solid currentColor; border-radius: 999px;
  padding: 0 5px; margin-left: 4px; }
.rw { color: #9b9bb0; font-family: 'Space Grotesk', 'Geist Mono', monospace; white-space: nowrap; }
.rb { height: 6px; border-radius: 999px; background: linear-gradient(90deg, rgba(255, 58, 216, .3), rgba(255, 58, 216, .85)); }
.rn b { font-family: 'Space Grotesk', 'Geist Mono', monospace; }
.rt { margin-top: 8px; background: none; border: 0; color: #28e6ff; cursor: pointer; font: inherit; font-size: 12.5px; padding: 0; }
@media (max-width: 520px) { .rn li { grid-template-columns: 1fr auto; } .rw, .rb { display: none; } }
</style>
