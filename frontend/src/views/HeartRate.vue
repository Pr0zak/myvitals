<script setup lang="ts">
/**
 * Heart rate detail (UI-4). Phone twin: `HrDetailScreen.kt`.
 *
 * 24h: the hero is the chosen day's trace over the SERVER's zone bands
 * (analytics/cardio.py — the same bounds the Activities screen uses), with
 * workouts, the sleep window, sober resets and journal markers laid over
 * it; below, the server's min/avg/max, time-in-zone and band histogram.
 *
 * 7d and longer: the hero is resting HR over the window with the normal
 * band and baseline from /summary/tiles; below, the server's window stats
 * and weekday means, then the plain daily HRV and year-over-year plots.
 *
 * Removed with the move to server stats: the zone bucketing (it used a max
 * HR of 187 when the profile was thin, so a minute could be Z3 here and Z4
 * on Activities), the histogram, the weekday means, the prior-window deltas
 * and the per-activity-type HR averages — each a client-side copy of a
 * number. The last two have no server block yet and are deferred.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import { HeartPulse } from "lucide-vue-next";
import RangeTabs from "@/components/RangeTabs.vue";
import DayNav from "@/components/DayNav.vue";
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
import type {
  Activity, Annotation, HeartRateSeries, RangeStats, SleepNight, TodaySummary, VitalTile,
} from "@/api/types";
import { chartTheme } from "@/theme";
import { useDateRange } from "@/useDateRange";
import { toLocalISO } from "@/dates";
import {
  annotationMarkPoint, daysToPoints, meanMarkLine, noDataSpans, normalBandMarkArea,
  sleepMarkArea, soberResetMarkLine, timeAxisFormatter, windowExtent, workoutMarkArea,
} from "@/components/charts/chartHelpers";

const CYAN = "#28e6ff";
const TRACK = "#272a3b";
/** Z1..Z5 — Periwinkle → Cyan → Lime → Amber → Bad (Z5 only). */
const ZONE_COLORS = ["#6f7bff", "#28e6ff", "#5dff3b", "#ffb52e", "#ff5d7a"];

const { range, options: RANGES, since: rangeSince } =
  useDateRange(["24h", "7d", "30d", "90d", "1y"], "24h");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);
const isDay = computed(() => range.value === "24h");

const selectedDay = ref<string>(toLocalISO(new Date()));
const dayIsToday = computed(() => selectedDay.value === toLocalISO(new Date()));
const dayWindow = computed(() => {
  const [y, m, d] = selectedDay.value.split("-").map(Number);
  const start = new Date(y, m - 1, d, 0, 0, 0, 0);
  const end = dayIsToday.value ? new Date() : new Date(y, m - 1, d + 1, 0, 0, 0, 0);
  return { start, end };
});

const hr = ref<HeartRateSeries | null>(null);
const annotations = ref<Annotation[]>([]);
const dayActivities = ref<Activity[]>([]);
const soberResets = ref<Array<{ start_at: string }>>([]);
const lastSleep = ref<SleepNight | null>(null);
const rows = ref<TodaySummary[]>([]);
const yearAgoRows = ref<TodaySummary[]>([]);
const stats = ref<RangeStats | null>(null);
const tiles = ref<Record<string, VitalTile>>({});
const loading = ref(true);
const error = ref<string | null>(null);

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't reach the backend.";
}

async function loadTiles() {
  try {
    const r = await api.summaryTiles();
    tiles.value = Object.fromEntries(r.tiles.map((t) => [t.key, t]));
  } catch { /* a chart without its band is still a chart */ }
}

async function loadDay() {
  const { start: since, end: until } = dayWindow.value;
  const [series, acts, sleep, swo, sb, anns] = await Promise.all([
    api.heartRate({ since, until }),
    api.activities({ since, limit: 30 }).catch(() => [] as Activity[]),
    api.lastSleep().catch(() => null),
    api.strengthWorkouts({ limit: 5 }).catch(() => ({ count: 0, workouts: [] })),
    api.soberHistory(50).catch(() => []),
    api.listAnnotations({ since, until, limit: 50 }).catch(() => [] as Annotation[]),
  ]);
  hr.value = series;
  annotations.value = anns;
  lastSleep.value = sleep;
  const s0 = since.getTime(); const e0 = until.getTime();
  const inWin = (a: { start_at: string }) => {
    const t = new Date(a.start_at).getTime();
    return t >= s0 && t <= e0;
  };
  const strength: Activity[] = (swo.workouts ?? [])
    .filter((w) => w.started_at && w.completed_at)
    .map((w) => ({
      source: "strength", source_id: String(w.id), type: "strength",
      name: `${w.split_focus.replace(/_/g, " ")} workout`, start_at: w.started_at!,
      duration_s: Math.max(0, Math.round((new Date(w.completed_at!).getTime() - new Date(w.started_at!).getTime()) / 1000)),
      distance_m: null, elevation_gain_m: null, avg_hr: w.avg_hr ?? null, max_hr: w.max_hr ?? null,
      avg_power_w: null, max_power_w: null, kcal: null, suffer_score: null, polyline: null,
    }) as Activity);
  dayActivities.value = [...acts, ...strength].filter(inWin);
  // The chronological first row is the start of tracking, not a reset.
  const sorted = Array.isArray(sb) ? [...sb].sort((a, b) => a.start_at.localeCompare(b.start_at)) : [];
  soberResets.value = sorted.slice(1).filter((r) => new Date(r.start_at).getTime() >= s0)
    .map((r) => ({ start_at: r.start_at }));
}

async function loadHistory() {
  const since = rangeSince.value ?? new Date(0);
  const yaSince = new Date(since); yaSince.setFullYear(yaSince.getFullYear() - 1);
  const yaUntil = new Date(); yaUntil.setFullYear(yaUntil.getFullYear() - 1);
  const [r, s, ya] = await Promise.all([
    api.summaryRange(since),
    summaryRangeStats(since, toLocalISO(new Date())),
    api.summaryRange(yaSince, yaUntil).catch(() => [] as TodaySummary[]),
  ]);
  rows.value = r;
  stats.value = s;
  yearAgoRows.value = ya;
}

async function load() {
  loading.value = true;
  try {
    await Promise.all([isDay.value ? loadDay() : loadHistory(), loadTiles()]);
    error.value = null;
  } catch (e) {
    error.value = errText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useVisibilityRefresh(load);
watch(range, (r) => {
  if (r !== "24h" && !dayIsToday.value) selectedDay.value = toLocalISO(new Date());
  load();
});
watch(selectedDay, () => { if (isDay.value) { hr.value = null; load(); } });

const hasContent = computed(() => (isDay.value ? hr.value != null : rows.value.length > 0 || stats.value != null));
const rest = computed(() => tiles.value.resting_hr ?? null);
const restChip = computed(() => {
  const t = rest.value;
  if (!t || typeof t.value !== "number") return null;
  return `Resting ${Math.round(t.value)}${t.status_reason ? ` · ${t.status_reason}` : ""}`;
});
const rs = computed(() => stats.value?.resting_hr ?? null);
const zs = computed(() => hr.value?.stats ?? null);
const r0 = (v: number | null | undefined) => (v == null ? "—" : String(Math.round(v)));

const axis = computed(() => chartTheme.value.axisLabel);
const split = { lineStyle: { color: TRACK } };

function fmtDur(s: number): string {
  const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function maxHrWord(src?: string | null): string {
  return src === "profile" ? "from your profile" : src === "estimated" ? "estimated from age"
    : "a default — add your birth date for a better one";
}

// ── 24h trace over the server's zone bands ──
const traceOption = computed(() => {
  const h = hr.value;
  if (!h || h.points.length < 2) return null;
  const zones = h.stats?.time_in_zone ?? [];
  const markLineData: any[] = [];
  if (h.avg != null) markLineData.push({
    yAxis: h.avg, lineStyle: { color: "#ececf5", type: "dashed" as const, opacity: 0.45 },
    label: { show: true, formatter: `avg ${Math.round(h.avg)}`, color: "#9b9bb0", fontSize: 9 },
  });
  const reset = soberResetMarkLine(soberResets.value);
  if (reset) for (const d of (reset.data as any[])) markLineData.push(d);
  const hi = h.points.reduce((m, p) => Math.max(m, p.value ?? 0), 0);
  const series: any[] = [
    {
      type: "line", name: "HR", showSymbol: false, smooth: true,
      lineStyle: { color: CYAN, width: 1.6 }, areaStyle: { color: `${CYAN}18` },
      data: h.points.map((p) => [p.time, p.value]),
      ...(markLineData.length ? { markLine: { silent: true, symbol: ["none", "none"], data: markLineData } } : {}),
      ...(dayActivities.value.length ? { markArea: workoutMarkArea(dayActivities.value) } : {}),
      ...(annotations.value.length ? { markPoint: annotationMarkPoint(annotations.value, hi > 0 ? hi + 8 : 100) } : {}),
    },
    {
      // Zone bands, one host series (markArea is one-per-series).
      type: "line", name: "zones", data: [], silent: true,
      markArea: { silent: true, data: zones.map((z, i) => [
        { yAxis: z.lo_bpm, itemStyle: { color: ZONE_COLORS[Math.min(i, 4)], opacity: 0.09 } },
        { yAxis: z.hi_bpm ?? 250 },
      ]) },
    },
  ];
  const sleepArea = sleepMarkArea(lastSleep.value, dayWindow.value.start.getTime(), dayWindow.value.end.getTime());
  if (sleepArea) series.push({ type: "line", name: "Sleep", data: [], silent: true, markArea: sleepArea });
  return {
    grid: { left: 36, right: 8, top: 12, bottom: 24 },
    xAxis: { type: "time", min: dayWindow.value.start.getTime(), max: dayWindow.value.end.getTime(),
             axisLabel: { ...axis.value, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series,
  };
});

const histogramOption = computed(() => {
  const bins = zs.value?.histogram ?? [];
  if (!bins.length) return null;
  return {
    grid: { left: 40, right: 8, top: 10, bottom: 30 },
    xAxis: { type: "category", data: bins.map((b) => String(b.lo)), axisLabel: axis.value,
             name: "bpm", nameLocation: "middle", nameGap: 20, nameTextStyle: axis.value },
    yAxis: { type: "value", axisLabel: { ...axis.value, formatter: (v: number) => (v >= 60 ? `${Math.round(v / 60)}h` : `${v}m`) },
             splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip,
               formatter: (p: any) => `${p[0].name}–${Number(p[0].name) + 5} bpm: ${p[0].value} min` },
    series: [{ type: "bar", data: bins.map((b) => b.minutes), barWidth: "85%",
               itemStyle: { color: CYAN, borderRadius: [3, 3, 0, 0] } }],
  };
});

// ── Resting HR over the window ──
function bandAwareExtent(values: number[], low?: number | null, high?: number | null) {
  if (!values.length) return {};
  const lo = Math.min(...values, low ?? Infinity);
  const hi = Math.max(...values, high ?? -Infinity);
  const pad = Math.max((hi - lo) * 0.12, 1);
  return { min: Math.floor((lo - pad) / 5) * 5, max: Math.ceil((hi + pad) / 5) * 5 };
}
const restingOption = computed(() => {
  const data = rows.value.map((r) => [r.date, r.resting_hr] as [string, number | null]);
  if (!data.some((d) => d[1] != null)) return null;
  const t = rest.value;
  return {
    grid: { left: 36, right: 8, top: 14, bottom: 24 },
    xAxis: { type: "time", axisLabel: { ...axis.value, formatter: timeAxisFormatter }, splitLine: { show: false },
             ...windowExtent(rangeSince.value?.getTime() ?? null) },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split,
             ...bandAwareExtent([...data.map((d) => d[1]).filter((v): v is number => v != null),
                                 ...(t?.baseline != null ? [t.baseline] : [])], t?.band_low, t?.band_high) },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [
      { type: "line", name: "Resting HR", smooth: true, connectNulls: false, showSymbol: data.length < 90,
        lineStyle: { color: CYAN, width: 2 }, itemStyle: { color: CYAN }, areaStyle: { color: `${CYAN}1f` }, data,
        markArea: normalBandMarkArea(t?.band_low, t?.band_high),
        markLine: t?.baseline != null ? meanMarkLine(t.baseline, "baseline") : undefined },
      ...noDataSpans(daysToPoints(data), rangeSince.value?.getTime() ?? null, Date.now(), CYAN),
    ],
  };
});

const weekdayOption = computed(() => {
  const wm = rs.value?.weekday_means ?? [];
  if (!wm.some((w) => w.mean != null)) return null;
  return {
    grid: { left: 36, right: 8, top: 18, bottom: 24 },
    xAxis: { type: "category", data: wm.map((w) => w.dow), axisLabel: axis.value },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [{ type: "bar", data: wm.map((w) => w.mean), barWidth: "55%",
               itemStyle: { color: CYAN, opacity: 0.85, borderRadius: [3, 3, 0, 0] },
               label: { show: true, position: "top", color: "#9b9bb0", fontSize: 10,
                        formatter: (p: any) => (p.value != null ? `${Math.round(p.value)}` : "") } }],
  };
});

const hrvOption = computed(() => {
  const data = rows.value.map((r) => [r.date, r.hrv_avg] as [string, number | null]);
  if (!data.some((d) => d[1] != null)) return null;
  const t = tiles.value.hrv;
  return {
    grid: { left: 36, right: 8, top: 14, bottom: 24 },
    xAxis: { type: "time", axisLabel: { ...axis.value, formatter: timeAxisFormatter }, splitLine: { show: false },
             ...windowExtent(rangeSince.value?.getTime() ?? null) },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [{ type: "line", name: "HRV (ms)", smooth: true, connectNulls: false, showSymbol: data.length < 90,
               lineStyle: { color: "#6f7bff", width: 1.8 }, itemStyle: { color: "#6f7bff" }, data,
               markArea: normalBandMarkArea(t?.band_low, t?.band_high, "#6f7bff") }],
  };
});

const yoyOption = computed(() => {
  const now = rows.value.map((r) => [new Date(r.date + "T00:00:00").getTime(), r.resting_hr] as [number, number | null]);
  const ya = yearAgoRows.value.map((r) => {
    const d = new Date(r.date + "T00:00:00"); d.setFullYear(d.getFullYear() + 1);
    return [d.getTime(), r.resting_hr] as [number, number | null];
  });
  if (!ya.some((d) => d[1] != null)) return null;
  return {
    legend: { textStyle: axis.value, top: 0 },
    grid: { left: 36, right: 8, top: 28, bottom: 24 },
    xAxis: { type: "time", axisLabel: { ...axis.value, formatter: timeAxisFormatter }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [
      { type: "line", name: "This period", smooth: true, connectNulls: false, showSymbol: false,
        lineStyle: { color: CYAN, width: 1.8 }, itemStyle: { color: CYAN }, data: now },
      { type: "line", name: "Same period last year", smooth: true, connectNulls: false, showSymbol: false,
        lineStyle: { color: "#9b9bb0", width: 1.4, type: "dashed" }, itemStyle: { color: "#9b9bb0" }, data: ya },
    ],
  };
});
</script>

<template>
  <NeonPage title="Heart rate" :back="true">
    <template #trailing><span class="dicon" style="--a: #28e6ff"><HeartPulse :size="20" /></span></template>
    <div class="dtabs">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Heart-rate time range">
        <template #before><PatternsLink metric="resting_hr" label="resting HR"/></template>
        <template #after><DayNav v-if="isDay" v-model="selectedDay"/></template>
      </RangeTabs>
    </div>

    <template v-if="!hasContent">
      <DetailSkeleton v-if="loading" :accent="CYAN" label="Heart rate" />
      <DetailError v-else-if="error" :error="error" @retry="load" />
    </template>

    <template v-else-if="isDay && hr">
      <DetailError v-if="error" :error="error" cached @retry="load" />
      <NeonHero :accent="CYAN">
        <span class="deb">{{ dayIsToday ? "Today" : selectedDay }}</span>
        <span class="dbig" :style="{ color: CYAN }">{{ r0(hr.avg) }}<small>avg bpm</small></span>
        <StatusChip v-if="dayIsToday" :status="rest?.status" :text="restChip" />
        <div v-if="traceOption" class="dchart tall"><VChart :option="traceOption" autoresize/></div>
        <p v-else class="dnote">{{ dayIsToday ? "No HR samples yet today." : "No HR samples on this day." }}</p>
        <div v-if="zs" class="dlegend">
          <span v-for="(z, i) in zs.time_in_zone" :key="z.zone"><i :style="{ background: ZONE_COLORS[Math.min(i, 4)] }"></i>{{ z.zone }}</span>
        </div>
      </NeonHero>
      <div class="dstats">
        <NeonStat :value="r0(hr.min_bpm)" label="Min bpm" />
        <NeonStat :value="r0(hr.avg)" label="Avg bpm" :accent="CYAN" />
        <NeonStat :value="r0(hr.max_bpm)" label="Max bpm" />
      </div>
      <p class="dnote">The line is a 2-minute average; min and max are from every reading.</p>

      <DetailCard v-if="zs && zs.tracked_s > 0" title="Time in zone"
                  :subtitle="zs.max_hr ? `Zones from a max HR of ${zs.max_hr} bpm (${maxHrWord(zs.max_hr_source)})` : null">
        <div class="zbar">
          <span v-for="(z, i) in zs.time_in_zone" :key="z.zone" v-show="z.seconds > 0"
                :style="{ flex: z.seconds, background: ZONE_COLORS[Math.min(i, 4)] }"></span>
        </div>
        <div v-for="(z, i) in zs.time_in_zone" :key="'r' + z.zone" class="zrow">
          <i :style="{ background: ZONE_COLORS[Math.min(i, 4)] }"></i>
          <span class="zl">{{ z.zone }} · {{ z.label }}</span>
          <span class="zb">{{ z.hi_bpm != null ? `${z.lo_bpm}–${z.hi_bpm}` : `${z.lo_bpm}+` }}</span>
          <b>{{ fmtDur(z.seconds) }}</b>
          <span class="zp">{{ z.pct != null ? `${Math.round(z.pct)}%` : "—" }}</span>
        </div>
      </DetailCard>

      <DetailCard v-if="histogramOption" title="HR distribution" subtitle="5-bpm bins · time spent in each">
        <div class="dchart"><VChart :option="histogramOption" autoresize/></div>
      </DetailCard>
    </template>

    <template v-else>
      <DetailError v-if="error" :error="error" cached @retry="load" />
      <NeonHero :accent="CYAN">
        <span class="deb">Resting HR · {{ cur.label }}</span>
        <span class="dbig" :style="{ color: CYAN }">{{ r0(rs?.latest) }}<small>bpm latest</small></span>
        <span v-if="rs?.latest_vs_avg != null" class="dsubline">
          {{ Math.abs(rs.latest_vs_avg) < 0.5 ? `at your ${cur.label} average`
             : `${rs.latest_vs_avg > 0 ? "+" : ""}${Math.round(rs.latest_vs_avg)} vs ${cur.label} average` }}
        </span>
        <StatusChip :status="rest?.status" :text="restChip" />
        <div v-if="restingOption" class="dchart tall"><VChart :option="restingOption" autoresize/></div>
        <p v-else class="dnote">No resting HR data in this window.</p>
      </NeonHero>
      <div class="dstats">
        <NeonStat :value="r0(rs?.min)" label="Min" />
        <NeonStat :value="r0(rs?.avg)" label="Avg" :accent="CYAN" />
        <NeonStat :value="r0(rs?.max)" label="Max" />
      </div>
      <DetailCard v-if="weekdayOption" title="Resting HR by weekday" subtitle="Average on each weekday in this window">
        <div class="dchart"><VChart :option="weekdayOption" autoresize/></div>
      </DetailCard>
      <DetailCard v-if="hrvOption" :title="`Daily HRV · ${cur.label}`">
        <div class="dchart"><VChart :option="hrvOption" autoresize/></div>
      </DetailCard>
      <DetailCard v-if="yoyOption" :title="`Year over year · ${cur.label}`">
        <div class="dchart"><VChart :option="yoyOption" autoresize/></div>
      </DetailCard>
    </template>
  </NeonPage>
</template>

<style scoped>
.zbar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; margin-bottom: 10px; background: #272a3b; }
.zrow { display: grid; grid-template-columns: 9px 1fr 64px 60px 36px; gap: 8px; align-items: center;
  font-size: 12px; padding: 2px 0; }
.zrow i { width: 9px; height: 9px; border-radius: 2px; }
.zl { color: #ececf5; }
.zb, .zp { color: #9b9bb0; font-size: 11px; }
.zrow b { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 600; }
</style>
