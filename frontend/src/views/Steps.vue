<script setup lang="ts">
/**
 * Steps detail (UI-4). Phone twin: `StepsDetailScreen.kt`.
 *
 *   hero     today's count, the server's verdict chip, a goal ring against
 *            today's own target, and today's hourly bars
 *   stats    the window's avg / goal days / total / best — server
 *            `/summary/range/stats`, rendered verbatim
 *   daily    bars per day (met = lime, under = track) with the goal line and
 *            the server's trailing 7-day mean
 *   weekday  the server's per-weekday means
 *
 * This view used to bucket the minute series into hours, sum, average,
 * count goal days and build a moving average itself — each a second copy of
 * a number the phone also computed. All of that is the server's now.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import { Footprints } from "lucide-vue-next";
import RangeTabs from "@/components/RangeTabs.vue";
import PatternsLink from "@/components/PatternsLink.vue";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import StatusChip from "@/components/detail/StatusChip.vue";
import DetailCard from "@/components/detail/DetailCard.vue";
import DetailSkeleton from "@/components/detail/DetailSkeleton.vue";
import DetailError from "@/components/detail/DetailError.vue";
import "@/components/detail/detail.css";
import { api, summaryRangeStats } from "@/api/client";
import type { RangeStats, TodaySummary, VitalTile } from "@/api/types";
import { useDateRange } from "@/useDateRange";
import { zeroAxisIncluding } from "@/chartAxis";
import { windowExtent, timeAxisFormatter } from "@/components/charts/chartHelpers";
import { toLocalISO } from "@/dates";
import { chartTheme } from "@/theme";

const LIME = "#5dff3b";
const TRACK = "#272a3b";
const PERI = "#6f7bff";

const { range, options: RANGES, since: rangeSince } =
  useDateRange(["7d", "30d", "90d", "1y"], "30d");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);

const rows = ref<TodaySummary[]>([]);
const stats = ref<RangeStats | null>(null);
const tile = ref<VitalTile | null>(null);
const hourly = ref<number[] | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't reach the backend.";
}

async function load() {
  loading.value = true;
  try {
    const since = rangeSince.value ?? new Date(0);
    const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
    const [r, s, tiles, series] = await Promise.all([
      api.summaryRange(since),
      summaryRangeStats(since, toLocalISO(new Date())),
      api.summaryTiles().catch(() => null),
      api.steps({ since: midnight, until: new Date() }).catch(() => null),
    ]);
    rows.value = r;
    stats.value = s;
    tile.value = tiles?.tiles.find((t) => t.key === "steps") ?? null;
    hourly.value = series?.hourly ?? null;
    error.value = null;
  } catch (e) {
    error.value = errText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(range, load);

const hasContent = computed(() => rows.value.length > 0 || stats.value != null);
const todayRow = computed(() => rows.value.find((r) => r.date === toLocalISO(new Date())) ?? null);
const todaySteps = computed<number | null>(() => todayRow.value?.steps_total ?? null);
const todayGoal = computed<number | null>(() =>
  todayRow.value?.steps_goal ?? (tile.value?.target != null ? Math.round(tile.value.target) : null));
const s = computed(() => stats.value?.steps ?? null);

function compact(n: number): string {
  if (n >= 100_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}
const fmtN = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());

const axis = computed(() => chartTheme.value.axisLabel);
const split = { lineStyle: { color: TRACK } };

const hourlyOption = computed(() => {
  const h = hourly.value;
  if (!h || h.every((v) => v === 0)) return null;
  return {
    grid: { left: 36, right: 6, top: 10, bottom: 22 },
    xAxis: { type: "category", data: h.map((_, i) => (i === 0 ? "12a" : i < 12 ? `${i}a` : i === 12 ? "12p" : `${i - 12}p`)),
             axisLabel: { ...axis.value, interval: 5 }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { ...axis.value, formatter: (v: number) => compact(v) }, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [{ type: "bar", data: h, itemStyle: { color: LIME, borderRadius: [3, 3, 0, 0] }, barWidth: "70%" }],
  };
});

const dailyOption = computed(() => {
  if (!rows.value.some((r) => r.steps_total != null)) return null;
  const goalLine = todayGoal.value;
  return {
    grid: { left: 40, right: 8, top: 16, bottom: 24 },
    xAxis: { type: "time", axisLabel: { ...axis.value, formatter: timeAxisFormatter }, splitLine: { show: false },
             ...windowExtent(rangeSince.value?.getTime() ?? null) },
    yAxis: {
      type: "value", axisLabel: { ...axis.value, formatter: (v: number) => compact(v) }, splitLine: split,
      ...zeroAxisIncluding(rows.value.map((r) => r.steps_total), goalLine),
    },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [
      {
        type: "bar", name: "Steps",
        // Each day against its OWN target (UX-D10). Under-goal days sit in
        // the track colour so a met day is the only thing lit.
        data: rows.value.filter((r) => r.steps_total != null).map((r) => ({
          value: [r.date, r.steps_total],
          itemStyle: { color: r.steps_goal != null && (r.steps_total as number) >= r.steps_goal ? LIME : TRACK,
                       borderRadius: [3, 3, 0, 0] },
        })),
        markLine: goalLine ? {
          symbol: ["none", "none"], silent: true,
          lineStyle: { color: "#ececf5", type: "dashed" as const, opacity: 0.55 },
          label: { show: true, position: "insideStartTop" as const, formatter: `goal ${goalLine.toLocaleString()}`,
                   color: "#9b9bb0", fontSize: 9 },
          data: [{ yAxis: goalLine }],
        } : undefined,
      },
      {
        type: "line", name: "7-day avg", smooth: true, showSymbol: false,
        lineStyle: { color: PERI, width: 2 },
        data: (s.value?.rolling_7d ?? []).map((p) => [p.date, p.value]),
      },
    ],
  };
});

const weekdayOption = computed(() => {
  const wm = s.value?.weekday_means ?? [];
  if (!wm.some((w) => w.mean != null)) return null;
  return {
    grid: { left: 40, right: 8, top: 16, bottom: 24 },
    xAxis: { type: "category", data: wm.map((w) => w.dow), axisLabel: axis.value },
    yAxis: { type: "value", axisLabel: { ...axis.value, formatter: (v: number) => compact(v) }, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    series: [{ type: "bar", data: wm.map((w) => w.mean), barWidth: "55%",
               itemStyle: { color: LIME, opacity: 0.85, borderRadius: [3, 3, 0, 0] } }],
  };
});
</script>

<template>
  <NeonPage title="Steps" :back="true">
    <template #trailing><span class="dicon" style="--a: #5dff3b"><Footprints :size="20" /></span></template>
    <div class="dtabs">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Steps time range">
        <template #before><PatternsLink metric="steps_total" label="steps"/></template>
      </RangeTabs>
    </div>

    <template v-if="!hasContent">
      <DetailSkeleton v-if="loading" :accent="LIME" label="Steps" />
      <DetailError v-else-if="error" :error="error" @retry="load" />
    </template>

    <template v-else>
      <DetailError v-if="error" :error="error" cached @retry="load" />

      <NeonHero :accent="LIME">
        <div class="dhero-top">
          <div class="dhero-main">
            <span class="deb">Today</span>
            <span class="dbig" :style="{ color: LIME }">{{ fmtN(todaySteps) }}</span>
            <span class="dsubline">
              {{ todaySteps == null ? "No step data yet today" : todayGoal ? `of ${todayGoal.toLocaleString()} goal` : "steps" }}
            </span>
            <StatusChip :status="tile?.status" :text="tile?.status_reason" />
          </div>
          <NeonRing v-if="todayGoal" :fraction="(todaySteps ?? 0) / todayGoal" :color="LIME" :size="96" :stroke="9">
            <b class="rg">{{ compact(todayGoal) }}</b><span class="rc">GOAL</span>
          </NeonRing>
        </div>
        <div class="deb" style="margin-top: 14px">Today by hour</div>
        <div v-if="hourlyOption" class="dchart"><VChart :option="hourlyOption" autoresize/></div>
        <p v-else class="dnote">No hourly detail synced yet today.</p>
      </NeonHero>

      <div class="dstats">
        <NeonStat :value="s?.avg != null ? s.avg.toLocaleString() : '—'" :label="`${cur.label} daily avg`" :accent="LIME" />
        <NeonStat :value="s ? `${s.goal_days}/${s.days_with_data}` : '—'" label="Days ≥ goal" />
        <NeonStat :value="s?.total != null ? compact(s.total) : '—'" label="Total" />
      </div>

      <DetailCard v-if="dailyOption" :title="`Daily — ${cur.label}`">
        <div class="dchart tall"><VChart :option="dailyOption" autoresize/></div>
        <div class="dlegend">
          <span><i :style="{ background: LIME }"></i>goal met</span>
          <span><i :style="{ background: TRACK }"></i>under goal</span>
          <span><i :style="{ background: PERI }"></i>7-day avg</span>
        </div>
      </DetailCard>

      <DetailCard v-if="weekdayOption" title="Weekday pattern" subtitle="Average steps on each weekday in this window">
        <div class="dchart"><VChart :option="weekdayOption" autoresize/></div>
      </DetailCard>
    </template>
  </NeonPage>
</template>

<style scoped>
.rg { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 16px; color: #ececf5; }
.rc { font-size: 9px; font-weight: 700; letter-spacing: .12em; color: #9b9bb0; }
</style>
