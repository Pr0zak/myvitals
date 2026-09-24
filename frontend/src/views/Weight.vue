<script setup lang="ts">
/**
 * Weight detail (UI-4). Phone twin: `WeightDetailScreen.kt`.
 *
 * The hero is the latest weigh-in, the change over the window coloured by
 * the SERVER's tone, the goal distance, and the trend (daily readings, the
 * server's 7-day mean, the server-fitted trend line and the goal line).
 * Every figure — min/avg/max, the 7- and 30-day changes, the recomposition
 * read, and whether a change counts as progress — is `/query/weight`'s
 * `stats` block (analytics/detail_stats.py), in kilograms, shown in the
 * user's unit.
 *
 * Removed with the move: the client-side KPI math, the rolling average,
 * and the recomposition verdict (which painted "Fat gain" in the crisis rose).
 *
 * UI-F1 brought back the distribution histogram and "days at min" as
 * server fields (`stats.histogram` in kg bands, `stats.days_at_min` in
 * LOCAL days); this view only converts the band edges to the user's unit.
 */
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import { Scale } from "lucide-vue-next";
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
import { api } from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import type { VitalTile, WeightDelta, WeightStats, WeightTone } from "@/api/types";
import { chartTheme } from "@/theme";
import { useDateRange } from "@/useDateRange";
import { windowExtent, noDataSpans, coverageNote } from "@/components/charts/chartHelpers";
import { weightVal, weightUnit, fmtWeight, isImperial } from "@/units";

const AMBER = "#ffb52e";
const TRACK = "#272a3b";

const { range, options: RANGES, since: rangeSince } =
  useDateRange(["30d", "90d", "1y", "all"], "90d");
const cur = computed(() => RANGES.find((r) => r.key === range.value)!);
const yoy = ref(false);

type Point = {
  time: string; weight_kg: number | null; body_fat_pct: number | null;
  bmi: number | null; lean_mass_kg: number | null; source: string;
};
const points = ref<Point[]>([]);
const stats = ref<WeightStats | null>(null);
const tile = ref<VitalTile | null>(null);
const loaded = ref(false);
const loading = ref(true);
const error = ref<string | null>(null);

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't reach the backend.";
}

async function load() {
  loading.value = true;
  try {
    const days = yoy.value ? null : cur.value.days;
    const since = days == null ? new Date("2010-01-01") : (rangeSince.value ?? new Date("2010-01-01"));
    const [r, tiles] = await Promise.all([api.weight({ since }), api.summaryTiles().catch(() => null)]);
    points.value = r.points;
    stats.value = r.stats ?? null;
    tile.value = tiles?.tiles.find((t) => t.key === "weight") ?? null;
    loaded.value = true;
    error.value = null;
  } catch (e) {
    // Kept beside whatever is already drawn, never instead of it.
    error.value = errText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useVisibilityRefresh(load);
watch([range, yoy], load);

const sorted = computed(() =>
  points.value.filter((p) => p.weight_kg != null)
    .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime()));

const TONE_COLOR: Record<WeightTone, string> = { positive: "#5dff3b", caution: AMBER, neutral: "#ececf5" };
function signed(kg: number | null | undefined): string {
  const v = weightVal(kg ?? null);
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
}
const deltaText = computed(() => {
  const d = stats.value?.delta_kg;
  if (d == null) return null;
  const arrow = d > 0.02 ? "↑" : d < -0.02 ? "↓" : "→";
  return `${arrow} ${signed(d)} ${weightUnit.value} over ${cur.value.label}`;
});
/** Distance to the goal as a magnitude and a direction word; the server
 *  gives the signed gap, this only converts the unit. It takes no tone. */
const goalText = computed(() => {
  const s = stats.value;
  if (s?.goal_kg == null) return null;
  const gap = s.goal_gap_kg;
  let word = "";
  if (gap != null) {
    const v = weightVal(Math.abs(gap)) ?? 0;
    word = v < 0.05 ? " · at goal" : ` · ${v.toFixed(1)} ${weightUnit.value} to ${gap > 0 ? "lose" : "gain"}`;
  }
  return `Goal ${fmtWeight(s.goal_kg)}${word}`;
});
const deltaTile = (d: WeightDelta | undefined) => ({
  value: signed(d?.delta_kg),
  accent: d?.delta_kg != null ? TONE_COLOR[d.tone] : undefined,
});

const coverage = computed(() => coverageNote(
  sorted.value.map((p) => [new Date(p.time).getTime(), p.weight_kg as number] as [number, number]),
  rangeSince.value?.getTime() ?? null,
));

const axis = computed(() => chartTheme.value.axisLabel);
const split = { lineStyle: { color: TRACK } };

function goalAwareExtent(): { min?: number; max?: number } {
  const vals = sorted.value.map((p) => weightVal(p.weight_kg)).filter((v): v is number => v != null);
  if (!vals.length) return {};
  const gv = stats.value?.goal_kg != null ? weightVal(stats.value.goal_kg) : null;
  const lo = Math.min(...vals, gv ?? Infinity);
  const hi = Math.max(...vals, gv ?? -Infinity);
  const pad = Math.max((hi - lo) * 0.08, isImperial.value ? 1 : 0.5);
  const step = isImperial.value ? 5 : 2;
  return { min: Math.floor((lo - pad) / step) * step, max: Math.ceil((hi + pad) / step) * step };
}

const mainOption = computed(() => {
  void weightUnit.value;
  if (yoy.value) {
    const byYear: Record<string, [number, number][]> = {};
    for (const p of sorted.value) {
      const d = new Date(p.time);
      const v = weightVal(p.weight_kg);
      if (v == null) continue;
      (byYear[String(d.getUTCFullYear())] ??= []).push([Date.UTC(2000, d.getUTCMonth(), d.getUTCDate()), v]);
    }
    const yrs = Object.keys(byYear).sort();
    const palette = ["#9b9bb0", "#6f7bff", "#ff3ad8", "#5dff3b", "#28e6ff"];
    const md = (ms: number) => { const d = new Date(ms); return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`; };
    return {
      legend: { textStyle: axis.value, top: 0 },
      grid: { left: 40, right: 8, top: 28, bottom: 24 },
      tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
      xAxis: { type: "time", min: Date.UTC(2000, 0, 1), max: Date.UTC(2000, 11, 31),
               axisLabel: { ...axis.value, formatter: md }, splitLine: { show: false } },
      yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split },
      series: yrs.map((y, i) => ({
        name: y, type: "line", smooth: true, symbol: "none", data: byYear[y].sort((a, b) => a[0] - b[0]),
        lineStyle: { width: i === yrs.length - 1 ? 2.5 : 1.2,
                     color: i === yrs.length - 1 ? AMBER : palette[i % palette.length],
                     opacity: i === yrs.length - 1 ? 1 : 0.55 },
      })),
    };
  }
  const pts = sorted.value.map((p) => [new Date(p.time).getTime(), weightVal(p.weight_kg)] as [number, number]);
  if (pts.length < 2) return null;
  const s = stats.value;
  const series: any[] = [
    { name: `Daily ${weightUnit.value}`, type: "line", data: pts, symbol: "circle", symbolSize: 3,
      lineStyle: { width: 1, color: AMBER, opacity: 0.4 }, itemStyle: { color: AMBER } },
    { name: "7-day avg", type: "line", smooth: true, symbol: "none",
      data: (s?.rolling_7d ?? []).map((r) => [new Date(r.time).getTime(), weightVal(r.kg)]),
      lineStyle: { width: 2.5, color: AMBER, shadowColor: "rgba(255, 181, 46, 0.55)", shadowBlur: 8 } },
  ];
  if (s?.trend) series.push({
    name: "Trend", type: "line", symbol: "none", silent: true,
    data: [[new Date(s.trend.start_time).getTime(), weightVal(s.trend.start_kg)],
           [new Date(s.trend.end_time).getTime(), weightVal(s.trend.end_kg)]],
    lineStyle: { width: 1.2, color: AMBER, type: "dashed" as const, opacity: 0.55 },
  });
  const gv = s?.goal_kg != null ? weightVal(s.goal_kg) : null;
  if (gv != null) series.push({
    name: "Goal", type: "line", data: [], markLine: {
      silent: true, symbol: "none", lineStyle: { color: "#ececf5", type: "dashed" as const, width: 1.2, opacity: 0.6 },
      data: [{ yAxis: gv, label: { formatter: `goal ${gv.toFixed(0)}`, color: "#9b9bb0", fontSize: 9, position: "insideEndTop" } }],
    },
  });
  series.push(...noDataSpans(pts, rangeSince.value?.getTime() ?? null, Date.now(), AMBER));
  return {
    grid: { left: 40, right: 8, top: 14, bottom: 24 },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip },
    xAxis: { type: "time", axisLabel: axis.value, splitLine: { show: false },
             ...windowExtent(rangeSince.value?.getTime() ?? null) },
    yAxis: { type: "value", scale: true, axisLabel: axis.value, splitLine: split, ...goalAwareExtent() },
    series,
  };
});

// UI-F1 — the server's kg bands, edges converted for display only.
const histogramOption = computed(() => {
  void weightUnit.value;
  const bins = stats.value?.histogram?.bins ?? [];
  if (bins.length < 2) return null;
  const label = (kg: number) => weightVal(kg)?.toFixed(1) ?? "";
  return {
    grid: { left: 32, right: 8, top: 10, bottom: 30 },
    xAxis: { type: "category", data: bins.map((b) => label(b.lo_kg)), axisLabel: axis.value,
             name: weightUnit.value, nameLocation: "middle", nameGap: 20, nameTextStyle: axis.value },
    yAxis: { type: "value", minInterval: 1, axisLabel: axis.value, splitLine: split },
    tooltip: { trigger: "axis", ...chartTheme.value.tooltip,
               formatter: (p: any) => {
                 const b = bins[p[0].dataIndex];
                 return `${label(b.lo_kg)}–${label(b.hi_kg)} ${weightUnit.value}: ${b.count} reading${b.count === 1 ? "" : "s"}`;
               } },
    series: [{ type: "bar", data: bins.map((b) => b.count), barWidth: "85%",
               itemStyle: { color: AMBER, borderRadius: [3, 3, 0, 0] } }],
  };
});
const daysAtMinText = computed(() => {
  const n = stats.value?.days_at_min;
  if (n == null) return null;
  return `Lowest reading, ${fmtWeight(stats.value?.min_kg ?? null)}, on ${n} day${n === 1 ? "" : "s"}`;
});

const sortDesc = ref(true);
const tableRows = computed(() => (sortDesc.value ? [...sorted.value].reverse() : sorted.value));
const fmtDate = (s: string) => new Date(s).toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
</script>

<template>
  <NeonPage title="Weight" :back="true">
    <template #trailing><span class="dicon" style="--a: #ffb52e"><Scale :size="20" /></span></template>
    <div class="dtabs">
      <RangeTabs v-model="range" :options="RANGES" :disabled="yoy" aria-label="Weight time range">
        <template #before><PatternsLink metric="weight_kg" label="weight"/></template>
        <template #after>
          <label class="yoy"><input v-model="yoy" type="checkbox"/> Year-over-year</label>
        </template>
      </RangeTabs>
    </div>

    <template v-if="!loaded">
      <DetailSkeleton v-if="loading" :accent="AMBER" label="Weight" />
      <DetailError v-else-if="error" :error="error" @retry="load" />
    </template>

    <template v-else>
      <DetailError v-if="error" :error="error" cached @retry="load" />
      <p v-if="!sorted.length" class="dnote">
        No weight data in this window. Import a Fitbit/Garmin ZIP from Settings, or pair a smart scale with Health Connect.
      </p>
      <template v-else>
        <NeonHero :accent="AMBER">
          <span class="deb">Latest</span>
          <span class="dbig" :style="{ color: AMBER }">
            {{ weightVal(stats?.latest_kg ?? null)?.toFixed(1) ?? "—" }}<small>{{ weightUnit }}</small>
          </span>
          <span v-if="deltaText" class="dsubline" :style="{ color: TONE_COLOR[stats!.tone], fontWeight: 600 }">{{ deltaText }}</span>
          <div class="chips">
            <StatusChip v-if="tile?.status_reason" :text="tile.status_reason" />
            <StatusChip :text="goalText" />
            <StatusChip v-if="stats?.recomp" :status="stats.recomp.tone" :text="stats.recomp.label" />
          </div>
          <div v-if="mainOption" class="dchart tall"><VChart :option="mainOption" autoresize/></div>
          <p v-else class="dnote">Need at least 2 weigh-ins in this window to draw a trend.</p>
        </NeonHero>

        <div class="dstats">
          <NeonStat v-bind="deltaTile(stats?.delta_7d)" :label="`7-day Δ ${weightUnit}`" />
          <NeonStat v-bind="deltaTile(stats?.delta_30d)" :label="`30-day Δ ${weightUnit}`" />
          <NeonStat :value="String(stats?.count ?? 0)" label="Readings" />
        </div>
        <div class="dstats">
          <NeonStat :value="weightVal(stats?.min_kg ?? null)?.toFixed(1) ?? '—'" :label="`Min ${weightUnit}`" />
          <NeonStat :value="weightVal(stats?.avg_kg ?? null)?.toFixed(1) ?? '—'" :label="`Avg ${weightUnit}`" />
          <NeonStat :value="weightVal(stats?.max_kg ?? null)?.toFixed(1) ?? '—'" :label="`Max ${weightUnit}`" />
        </div>
        <p v-if="daysAtMinText && !yoy" class="dnote">{{ daysAtMinText }}</p>
        <p v-if="coverage" class="dnote">{{ coverage }}</p>

        <DetailCard v-if="histogramOption && !yoy" title="Distribution"
                    :subtitle="`Readings per ${weightVal(stats!.histogram!.bin_kg)?.toFixed(1)}-${weightUnit} band`">
          <div class="dchart"><VChart :option="histogramOption" autoresize/></div>
        </DetailCard>

        <DetailCard :title="`History · ${tableRows.length} readings`">
          <div class="hist-wrap">
            <table class="hist">
              <thead>
                <tr>
                  <th class="sortable" @click="sortDesc = !sortDesc">Date {{ sortDesc ? "↓" : "↑" }}</th>
                  <th>Weight</th><th>Body fat</th><th>Lean</th><th>BMI</th><th>Source</th>
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
          </div>
          <p v-if="tableRows.length > 200" class="dnote">Showing the first 200 of {{ tableRows.length }}.</p>
        </DetailCard>
      </template>
    </template>
  </NeonPage>
</template>

<style scoped>
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.yoy { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: #9b9bb0; cursor: pointer; }
.hist-wrap { overflow-x: auto; }
.hist { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.hist th { text-align: left; color: #9b9bb0; font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
  padding: 6px 8px; border-bottom: 1px solid #23263a; white-space: nowrap; }
.hist th.sortable { cursor: pointer; user-select: none; }
.hist td { padding: 6px 8px; border-bottom: 1px solid #1d2030; white-space: nowrap; }
.hist td strong { color: #ffb52e; }
.hist .m { color: #9b9bb0; }
</style>
