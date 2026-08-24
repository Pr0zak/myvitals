<script setup lang="ts">
// BODY-1: body circumference measurements (waist/chest/arms/hips/thighs/neck/
// calves), manual entry + per-site trend. Mirrors the Blood Pressure view's
// manual-entry pattern.
import { useDateRange } from "@/useDateRange";
import { computed, onMounted, ref, watch } from "vue";
import VChart from "@/echarts";
import Card from "@/components/Card.vue";
import PageHeader from "@/components/PageHeader.vue";
import RangeTabs from "@/components/RangeTabs.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadState from "@/components/LoadState.vue";
import { api } from "@/api/client";
import { chartTheme, isNeon } from "@/theme";
import { windowExtent, noDataSpans, daysToPoints } from "@/components/charts/chartHelpers";
import { fmtDateTime } from "@/format";

// RANGE-1: one vocabulary, and the range in the URL. This view used
// to declare its own key type and option list; ten views did, and
// they disagreed — seven spelled a year "1y" and three "365d".
const { range, options: RANGES, since: rangeSince, days: rangeDays } =
  useDateRange(["30d", "90d", "1y", "all"], "1y");

const SITES = [
  { key: "waist_cm", label: "Waist" },
  { key: "chest_cm", label: "Chest" },
  { key: "arms_cm", label: "Arms" },
  { key: "hips_cm", label: "Hips" },
  { key: "thighs_cm", label: "Thighs" },
  { key: "neck_cm", label: "Neck" },
  { key: "calves_cm", label: "Calves" },
] as const;
type SiteKey = (typeof SITES)[number]["key"];

type Point = { time: string } & Record<SiteKey, number | null>;
const points = ref<Point[]>([]);
const latestPerSite = ref<Record<string, number>>({});
const loading = ref(false);
const selectedSite = ref<SiteKey>("waist_cm");

// Manual entry: one input per site, all optional.
const form = ref<Record<SiteKey, string>>({
  waist_cm: "", chest_cm: "", arms_cm: "", hips_cm: "",
  thighs_cm: "", neck_cm: "", calves_cm: "",
});
const saving = ref(false);
const saveErr = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    const days = RANGES.find((r) => r.key === range.value)!.days;
    const since = days == null
      ? new Date("2010-01-01")
      : (() => { const d = new Date(); d.setDate(d.getDate() - days); return d; })();
    const r = await api.circumference({ since });
    points.value = r.points as Point[];
    latestPerSite.value = r.latest_per_site;
  } finally { loading.value = false; }
}

async function save() {
  saving.value = true; saveErr.value = null;
  let saved = false;
  try {
    const body: Record<string, number> = {};
    for (const s of SITES) {
      const raw = form.value[s.key].trim();
      if (raw) {
        const v = parseFloat(raw);
        if (Number.isFinite(v) && v > 0) body[s.key] = v;
      }
    }
    if (Object.keys(body).length === 0) throw new Error("Enter at least one measurement.");
    await api.logCircumference(body);
    for (const s of SITES) form.value[s.key] = "";
    saved = true;
  } catch (e) {
    saveErr.value = e instanceof Error ? e.message : String(e);
  } finally { saving.value = false; }
  // Reload separately — a transient reload failure must NOT read as a save error.
  if (saved) { try { await load(); } catch { /* saved OK; trend refreshes next load */ } }
}

const hasData = computed(() => Object.keys(latestPerSite.value).length > 0);

// Site trend: the selected site's non-null points over the range.
const trendOption = computed(() => {
  const t = chartTheme.value;
  void isNeon.value;
  const site = selectedSite.value;
  const data = points.value
    .filter((p) => p[site] != null)
    .map((p) => [p.time, p[site] as number]);
  if (data.length < 2) return null;
  const color = isNeon.value ? "#28e6ff" : "#0ea5e9";
  return {
    grid: { left: 52, right: 16, top: 20, bottom: 28 },
    tooltip: { trigger: "axis", ...t.tooltip },
    xAxis: { type: "time", axisLabel: t.axisLabel,
             // Axis spans the SELECTED window, not just the days with data.
             ...windowExtent(rangeSince.value?.getTime() ?? null), },
    yAxis: { type: "value", name: "cm", scale: true,
             axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [
      ...noDataSpans(daysToPoints(data as Array<[string, number | null]>),
                     rangeSince.value?.getTime() ?? null, Date.now(), color),
      {
      name: SITES.find((s) => s.key === site)!.label, type: "line",
      smooth: true, symbol: "circle", symbolSize: 5, data,
      lineStyle: { color, width: 2 }, itemStyle: { color },
      areaStyle: { color, opacity: 0.14 },
    }],
  };
});

function siteDelta(key: SiteKey): number | null {
  const vals = points.value.filter((p) => p[key] != null).map((p) => p[key] as number);
  if (vals.length < 2) return null;
  return Math.round((vals[vals.length - 1] - vals[0]) * 10) / 10;
}

onMounted(load);
watch(range, load);
</script>

<template>
  <div class="measure">
    <PageHeader title="Measurements">
      <RangeTabs v-model="range" :options="RANGES" aria-label="Measurement time range" />
    </PageHeader>

    <LoadState v-if="loading && !hasData" />

    <template v-else>
      <div v-if="hasData" class="kpis">
        <div v-for="s in SITES" :key="s.key" class="kpi"
             v-show="latestPerSite[s.key] != null">
          <div class="kpi-label">{{ s.label }}</div>
          <div class="kpi-val"><strong>{{ latestPerSite[s.key] }}</strong><span class="unit">cm</span></div>
          <div class="kpi-sub muted" v-if="siteDelta(s.key) != null">
            {{ siteDelta(s.key)! > 0 ? "+" : "" }}{{ siteDelta(s.key) }} cm over range
          </div>
        </div>
      </div>

      <Card v-if="hasData" title="Trend">
        <div class="picker">
          <select v-model="selectedSite">
            <option v-for="s in SITES" :key="s.key" :value="s.key">{{ s.label }}</option>
          </select>
        </div>
        <div v-if="trendOption" class="chart"><VChart :option="trendOption" autoresize /></div>
        <p v-else class="muted small">Need at least 2 entries of this site to chart a trend.</p>
      </Card>

      <EmptyState v-else>
        No measurements yet. Grab a tape measure and log below — waist, chest,
        arms, hips, thighs, neck, calves (cm).
      </EmptyState>
    </template>

    <Card title="Log measurements">
      <div class="measure-form">
        <label v-for="s in SITES" :key="s.key" class="mf-field">
          <span>{{ s.label }}</span>
          <input v-model="form[s.key]" type="number" step="0.1" min="0"
                 inputmode="decimal" placeholder="cm" />
        </label>
      </div>
      <button class="primary" :disabled="saving" @click="save">
        {{ saving ? "Saving…" : "Save measurements" }}
      </button>
      <div v-if="saveErr" class="err"><small>{{ saveErr }}</small></div>
      <p class="muted small" style="margin-top: 0.4rem;">
        Leave a field blank to skip it. All entered sites share one timestamp.
      </p>
    </Card>
  </div>
</template>

<style scoped>
.measure { max-width: 880px; margin: 0 auto; padding: 1rem; }
.kpis { display: flex; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 0.8rem; }
.kpi { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 0.6rem 0.9rem; min-width: 104px; }
.kpi-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); font-weight: 700; }
.kpi-val { font-size: 1.4rem; font-weight: 600;
  font-family: 'Geist Mono', ui-monospace, monospace; }
.kpi-val .unit { font-size: 0.75rem; color: var(--muted); margin-left: 0.2rem; }
.kpi-sub { font-size: 0.72rem; margin-top: 0.1rem; }
.chart { width: 100%; height: 300px; }
.chart > * { width: 100%; height: 100%; }
.picker { margin-bottom: 0.6rem; }
.picker select { background: var(--bg-2, var(--surface)); color: var(--text);
  border: 1px solid var(--border); padding: 0.3rem 0.6rem;
  border-radius: 6px; font-size: 0.85rem; }
.measure-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.6rem; margin-bottom: 0.8rem; }
.mf-field { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.75rem;
  color: var(--muted); }
.mf-field input { background: var(--bg-2, var(--surface)); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.5rem;
  font-size: 0.95rem; }
.muted { color: var(--muted); }
.small { font-size: 0.85rem; }
.err { color: var(--accent, #ef4444); margin-top: 0.4rem; }
</style>
