<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, ref, watch } from "vue";
import VChart from "vue-echarts";
import { ArrowRightLeft, ChevronDown, ArrowDown, ArrowUp } from "lucide-vue-next";
import Card from "@/components/Card.vue";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import { chartTheme } from "@/theme";
import { weightUnit, weightVal, units } from "@/units";
import { renderMarkdown } from "@/markdown";

// ────────── METRIC METADATA ──────────
const METRIC_LABEL: Record<string, string> = {
  hrv_avg: "HRV",
  resting_hr: "resting HR",
  recovery_score: "recovery",
  sleep_score: "sleep score",
  sleep_duration_s: "sleep duration",
  weight_kg: "weight",
  body_fat_pct: "body fat",
  bp_systolic_avg: "systolic BP",
  bp_diastolic_avg: "diastolic BP",
  skin_temp_delta_avg: "skin temperature",
  steps_total: "steps",
  activity_duration_s: "activity duration",
  alcohol_count: "alcohol drinks",
  caffeine_mg: "caffeine",
  mood_score: "mood",
};
const mLabel = (k: string): string => METRIC_LABEL[k] ?? k;

function fmtVal(metric: string, v: number): string {
  if (metric === "sleep_duration_s") return `${(v / 3600).toFixed(1)} h`;
  if (metric === "activity_duration_s") return `${Math.round(v / 60)} min`;
  if (metric === "caffeine_mg") return `${Math.round(v)} mg`;
  if (metric === "alcohol_count") return `${v.toFixed(1)} drinks`;
  if (metric === "weight_kg") {
    const w = weightVal(v);
    return w != null ? `${w.toFixed(1)} ${weightUnit.value}` : `${v.toFixed(1)} kg`;
  }
  if (metric === "body_fat_pct") return `${v.toFixed(1)}%`;
  if (metric === "bp_systolic_avg" || metric === "bp_diastolic_avg") return `${Math.round(v)} mmHg`;
  if (metric === "skin_temp_delta_avg")
    return units.value === "imperial" ? `${(v * 1.8).toFixed(2)} °F` : `${v.toFixed(2)} °C`;
  if (metric === "resting_hr") return `${Math.round(v)} bpm`;
  if (metric === "hrv_avg") return `${Math.round(v)} ms`;
  if (metric === "steps_total") return Math.round(v).toLocaleString();
  if (metric === "recovery_score" || metric === "sleep_score") return Math.round(v).toString();
  if (metric === "mood_score") return v.toFixed(1);
  return v.toFixed(2);
}

// ────────── STRENGTH ──────────
function strengthIdx(r: number | null | undefined): number {
  if (r === null || r === undefined) return 0;
  const a = Math.abs(r);
  if (a < 0.1) return 0;
  if (a < 0.3) return 1;
  if (a < 0.5) return 2;
  if (a < 0.7) return 3;
  return 4;
}
const STRENGTH_LABELS = ["no link", "weak", "moderate", "strong", "very strong"];

function findingPhrase(x: string, y: string, r: number): string {
  const dir = r < 0 ? "less" : "more";
  return `More ${mLabel(x)} → ${dir} ${mLabel(y)}`;
}

function effectSentence(points: { x: number; y: number }[], x: string, y: string): string | null {
  if (points.length < 6) return null;
  const sorted = [...points].sort((a, b) => a.x - b.x);
  const half = Math.floor(sorted.length / 2);
  const lo = sorted.slice(0, half);
  const hi = sorted.slice(-half);
  const loY = lo.reduce((s, p) => s + p.y, 0) / lo.length;
  const hiY = hi.reduce((s, p) => s + p.y, 0) / hi.length;
  const loX = lo.reduce((s, p) => s + p.x, 0) / lo.length;
  const hiX = hi.reduce((s, p) => s + p.x, 0) / hi.length;
  const delta = hiY - loY;
  const dirWord = delta >= 0 ? "higher" : "lower";
  return (
    `On high-${mLabel(x)} days (~${fmtVal(x, hiX)}), ${mLabel(y)} averaged ${fmtVal(y, hiY)} — ` +
    `${fmtVal(y, Math.abs(delta))} ${dirWord} than on low-${mLabel(x)} days (${fmtVal(y, loY)}, ~${fmtVal(x, loX)}).`
  );
}

// ────────── FINDINGS FEED ──────────
interface Finding {
  x_metric: string;
  y_metric: string;
  pearson_r: number;
  n: number;
  points?: { date: string; x: number; y: number }[];
}
const findings = ref<Finding[]>([]);
const findingsLoading = ref(true);
const findingsErr = ref<string | null>(null);

async function loadFindings() {
  findingsLoading.value = true;
  findingsErr.value = null;
  try {
    const list = (await api.discoveries(90)) as Finding[];
    findings.value = list;
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    await Promise.all(
      list.slice(0, 8).map(async (f) => {
        try {
          const r = await axios.get(`${base}/analytics/correlate`, {
            headers: { Authorization: `Bearer ${queryToken.value}` },
            params: { x: f.x_metric, y: f.y_metric, lag: 0, days: 90 },
          });
          f.points = r.data.points;
        } catch {
          /* ignore — render without mini chart */
        }
      })
    );
    findings.value = [...list];
  } catch (e) {
    findingsErr.value = e instanceof Error ? e.message : String(e);
  } finally {
    findingsLoading.value = false;
  }
}

function miniOption(f: Finding) {
  void chartTheme.value;
  if (!f.points || f.points.length < 3) return null;
  return {
    grid: { left: 4, right: 4, top: 4, bottom: 4 },
    xAxis: { type: "value", show: false, scale: true },
    yAxis: { type: "value", show: false, scale: true },
    animation: false,
    series: [
      {
        type: "scatter",
        symbolSize: 5,
        itemStyle: {
          color: f.pearson_r < 0 ? "#ef4444" : "#22c55e",
          opacity: 0.7,
        },
        data: f.points.map((p) => [p.x, p.y]),
      },
    ],
  };
}

// ────────── EXPLORER ──────────
const METRIC_GROUPS = [
  { label: "Cardio", metrics: [
    { key: "hrv_avg", label: "HRV" },
    { key: "resting_hr", label: "Resting HR" },
    { key: "recovery_score", label: "Recovery" },
  ]},
  { label: "Sleep", metrics: [
    { key: "sleep_score", label: "Sleep score" },
    { key: "sleep_duration_s", label: "Sleep duration" },
  ]},
  { label: "Body", metrics: [
    { key: "weight_kg", label: "Weight" },
    { key: "body_fat_pct", label: "Body fat" },
    { key: "bp_systolic_avg", label: "Systolic BP" },
    { key: "bp_diastolic_avg", label: "Diastolic BP" },
    { key: "skin_temp_delta_avg", label: "Skin temperature" },
  ]},
  { label: "Activity", metrics: [
    { key: "steps_total", label: "Steps" },
    { key: "activity_duration_s", label: "Activity duration" },
  ]},
  { label: "Logged inputs", metrics: [
    { key: "alcohol_count", label: "Alcohol drinks" },
    { key: "caffeine_mg", label: "Caffeine" },
    { key: "mood_score", label: "Mood" },
  ]},
];

const x = ref("alcohol_count");
const y = ref("hrv_avg");
const lag = ref(1);
const days = ref(90);
const explorerOpen = ref(false);

const LAG_OPTIONS = [
  { v: 0, label: "Same day" },
  { v: 1, label: "Next day" },
  { v: 2, label: "Two days later" },
  { v: 7, label: "A week later" },
];
function lagLabel(n: number): string {
  return LAG_OPTIONS.find((o) => o.v === n)?.label ?? `${n}d later`;
}

const PRESETS = [
  { x: "alcohol_count", y: "hrv_avg", lag: 1, label: "Alcohol → next-day HRV" },
  { x: "alcohol_count", y: "resting_hr", lag: 1, label: "Alcohol → next-day RHR" },
  { x: "alcohol_count", y: "sleep_score", lag: 0, label: "Alcohol → that night's sleep" },
  { x: "caffeine_mg", y: "sleep_score", lag: 0, label: "Caffeine → that night's sleep" },
  { x: "activity_duration_s", y: "hrv_avg", lag: 1, label: "Workout → next-day HRV" },
  { x: "activity_duration_s", y: "resting_hr", lag: 1, label: "Workout → next-day RHR" },
  { x: "sleep_duration_s", y: "recovery_score", lag: 0, label: "Sleep duration → recovery" },
  { x: "steps_total", y: "sleep_score", lag: 0, label: "Steps → that night's sleep" },
];

interface Result {
  x_metric: string;
  y_metric: string;
  lag_days: number;
  n: number;
  pearson_r: number | null;
  points: { date: string; x: number; y: number }[];
}
const result = ref<Result | null>(null);
const explorerErr = ref<string | null>(null);

async function fetchData() {
  if (!queryToken.value) {
    explorerErr.value = "Set QUERY_TOKEN in Settings first.";
    return;
  }
  explorerErr.value = null;
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const r = await axios.get<Result>(`${base}/analytics/correlate`, {
      headers: { Authorization: `Bearer ${queryToken.value}` },
      params: { x: x.value, y: y.value, lag: lag.value, days: days.value },
    });
    result.value = r.data;
  } catch (e) {
    explorerErr.value = e instanceof Error ? e.message : "Failed to load";
  }
}

function openInExplorer(f: Finding) {
  x.value = f.x_metric;
  y.value = f.y_metric;
  lag.value = 0;
  explorerOpen.value = true;
  fetchData();
  setTimeout(() => {
    document.getElementById("explorer")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 80);
}

function applyPreset(p: typeof PRESETS[number]) {
  x.value = p.x;
  y.value = p.y;
  lag.value = p.lag;
}

function swapXY() {
  const t = x.value;
  x.value = y.value;
  y.value = t;
}

// ── AI integration: Ask + Discovery explainer ─────────────
const aiCfgEnabled = ref(false);
const askQuestion = ref("");
const askAnswer = ref<{ content: string } | null>(null);
const askBusy = ref(false);
const askError = ref<string | null>(null);
const explainResults = ref<Record<string, string>>({});
const explainBusy = ref<string | null>(null);

async function loadAiCfg() {
  try {
    const cfg = await api.aiConfig();
    aiCfgEnabled.value = !!cfg.enabled;
  } catch { /* ignore */ }
}
async function submitAsk() {
  if (!askQuestion.value.trim()) return;
  askBusy.value = true; askError.value = null; askAnswer.value = null;
  try {
    askAnswer.value = await api.aiAsk(askQuestion.value.trim());
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { data?: { detail?: string } } }).response;
      askError.value = r?.data?.detail ?? "Ask failed";
    } else askError.value = e instanceof Error ? e.message : "Ask failed";
  } finally { askBusy.value = false; }
}
async function explainCorrelation(xm: string, ym: string) {
  const k = `${xm}-${ym}`;
  explainBusy.value = k;
  try {
    const r = await api.aiExplainDiscovery(xm, ym);
    explainResults.value = { ...explainResults.value, [k]: r.content };
  } catch (e) {
    explainResults.value = { ...explainResults.value, [k]: "(explain failed: " +
      (e instanceof Error ? e.message : "unknown") + ")" };
  } finally { explainBusy.value = null; }
}

onMounted(() => {
  loadFindings();
  loadAiCfg();
  if (queryToken.value) fetchData();
});
watch([x, y, lag, days], fetchData);

const scatterOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!result.value) return null;
  const points = result.value.points;
  if (points.length === 0) return null;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const n = points.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = my - slope * mx;
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const fitLine =
    den === 0 ? [] : [[xMin, slope * xMin + intercept], [xMax, slope * xMax + intercept]];

  return {
    grid: { left: 56, right: 14, top: 24, bottom: 40 },
    xAxis: {
      type: "value",
      name: mLabel(result.value.x_metric),
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: t.axisLabel,
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
      scale: true,
    },
    yAxis: {
      type: "value",
      name: mLabel(result.value.y_metric),
      nameLocation: "middle",
      nameGap: 42,
      nameTextStyle: t.axisLabel,
      axisLabel: t.axisLabel,
      splitLine: t.splitLine,
      scale: true,
    },
    tooltip: {
      ...t.tooltip,
      trigger: "item",
      formatter: (p: any) => {
        const d = points[p.dataIndex];
        return `<b>${d.date}</b><br/>${mLabel(result.value!.x_metric)}: ${fmtVal(
          result.value!.x_metric,
          d.x
        )}<br/>${mLabel(result.value!.y_metric)}: ${fmtVal(result.value!.y_metric, d.y)}`;
      },
    },
    series: [
      {
        type: "scatter",
        symbolSize: 8,
        itemStyle: { color: t.palette.steps, opacity: 0.7 },
        data: points.map((p) => [p.x, p.y]),
      },
      ...(fitLine.length > 0
        ? [{
            type: "line" as const,
            showSymbol: false,
            smooth: false,
            silent: true,
            lineStyle: { color: t.palette.recovery, width: 2, type: "dashed" as const },
            data: fitLine,
          }]
        : []),
    ],
  };
});

const explorerEffect = computed(() =>
  result.value ? effectSentence(result.value.points, result.value.x_metric, result.value.y_metric) : null
);
const explorerStrength = computed(() => strengthIdx(result.value?.pearson_r));
</script>

<template>
  <div class="insights">
    <h1>Insights</h1>
    <p class="hint">
      Patterns we've spotted in your last 90 days. Click <em>Open</em> to see the data,
      or scroll down to test your own hunches.
    </p>

    <!-- ──────── ASK CLAUDE ──────── -->
    <Card v-if="aiCfgEnabled" title="Ask">
      <p class="hint" style="margin-bottom: 0.6rem;">
        Free-form question about your data — e.g. "what's hurting my sleep this month?"
      </p>
      <div class="ask-row">
        <input v-model="askQuestion" type="text"
               placeholder="What's hurting my sleep this month?"
               class="ask-input"
               @keydown.enter="submitAsk()"/>
        <button class="ask-send" :disabled="askBusy || !askQuestion.trim()"
                @click="submitAsk()">
          {{ askBusy ? 'Thinking…' : 'Ask' }}
        </button>
      </div>
      <div v-if="askError" class="err" style="margin-top: 0.5rem;">{{ askError }}</div>
      <div v-if="askAnswer" class="ask-answer" v-html="renderMarkdown(askAnswer.content)"/>
    </Card>

    <!-- ──────── FINDINGS FEED ──────── -->
    <div v-if="findingsLoading" class="loading">Looking for patterns…</div>
    <div v-else-if="findingsErr" class="err">{{ findingsErr }}</div>
    <div v-else-if="findings.length === 0" class="empty-state">
      <Card flat>
        <p><strong>No strong patterns yet.</strong></p>
        <p class="hint">
          We need ≥ 14 days where two metrics overlap, and a |Pearson r| ≥ 0.4 between
          them, before a finding surfaces here. Keep logging — patterns will appear.
        </p>
      </Card>
    </div>
    <div v-else class="findings">
      <Card v-for="f in findings" :key="`${f.x_metric}-${f.y_metric}`" flat>
        <div class="finding-row">
          <div class="finding-text">
            <button v-if="aiCfgEnabled" class="explain-btn"
                    :disabled="explainBusy === `${f.x_metric}-${f.y_metric}`"
                    @click="explainCorrelation(f.x_metric, f.y_metric)">
              {{ explainBusy === `${f.x_metric}-${f.y_metric}` ? '…' : '✦ Explain' }}
            </button>
            <div v-if="explainResults[`${f.x_metric}-${f.y_metric}`]" class="explain-out"
                 v-html="renderMarkdown(explainResults[`${f.x_metric}-${f.y_metric}`])"/>
            <div class="finding-headline" :class="{ neg: f.pearson_r < 0 }">
              <component :is="f.pearson_r < 0 ? ArrowDown : ArrowUp" :size="16" class="dir-icon"/>
              {{ findingPhrase(f.x_metric, f.y_metric, f.pearson_r) }}
            </div>
            <div v-if="f.points" class="finding-effect">
              {{ effectSentence(f.points, f.x_metric, f.y_metric) }}
            </div>
            <div class="finding-meta">
              <span class="strength-bar" :title="`Pearson r = ${f.pearson_r.toFixed(2)}`">
                <span v-for="i in 4" :key="i" class="seg"
                      :class="{ on: i <= strengthIdx(f.pearson_r), neg: f.pearson_r < 0 }"/>
              </span>
              <span class="strength-label">{{ STRENGTH_LABELS[strengthIdx(f.pearson_r)] }}</span>
              <span class="muted">· n={{ f.n }} days</span>
              <button class="open-btn" @click="openInExplorer(f)">Open →</button>
            </div>
          </div>
          <div v-if="miniOption(f)" class="mini-chart">
            <VChart :option="miniOption(f)!" autoresize/>
          </div>
        </div>
      </Card>
    </div>

    <!-- ──────── EXPLORER ──────── -->
    <details
      class="explorer-shell"
      :open="explorerOpen"
      id="explorer"
      @toggle="(e) => (explorerOpen = (e.target as HTMLDetailsElement).open)"
    >
      <summary>
        <ChevronDown :size="16" class="chev"/>
        <span>Explore your own correlations</span>
      </summary>

      <Card title="Pick two metrics">
        <div class="cfg">
          <label class="metric-pick">
            <span>X (cause)</span>
            <select v-model="x">
              <optgroup v-for="g in METRIC_GROUPS" :key="`x-${g.label}`" :label="g.label">
                <option v-for="m in g.metrics" :key="m.key" :value="m.key">{{ m.label }}</option>
              </optgroup>
            </select>
          </label>
          <button class="swap" @click="swapXY" title="Swap X and Y">
            <ArrowRightLeft :size="14"/>
          </button>
          <label class="metric-pick">
            <span>Y (effect)</span>
            <select v-model="y">
              <optgroup v-for="g in METRIC_GROUPS" :key="`y-${g.label}`" :label="g.label">
                <option v-for="m in g.metrics" :key="m.key" :value="m.key">{{ m.label }}</option>
              </optgroup>
            </select>
          </label>
          <label>
            <span>Effect appears</span>
            <select v-model.number="lag">
              <option v-for="opt in LAG_OPTIONS" :key="opt.v" :value="opt.v">{{ opt.label }}</option>
            </select>
          </label>
          <label>
            <span>Window</span>
            <select v-model.number="days">
              <option :value="30">last 30 days</option>
              <option :value="90">last 90 days</option>
              <option :value="180">last 6 months</option>
              <option :value="365">last year</option>
            </select>
          </label>
        </div>
      </Card>

      <Card
        v-if="result"
        :title="`${mLabel(result.x_metric)} → ${mLabel(result.y_metric)}`"
        :subtitle="lagLabel(result.lag_days)"
      >
        <div class="result-meta">
          <span class="strength-bar large">
            <span v-for="i in 4" :key="i" class="seg"
                  :class="{ on: i <= explorerStrength, neg: (result.pearson_r ?? 0) < 0 }"/>
          </span>
          <span class="strength-label">{{ STRENGTH_LABELS[explorerStrength] }}</span>
          <span class="muted">· {{ result.n }} days · r={{ result.pearson_r?.toFixed(2) ?? "—" }}</span>
        </div>
        <p v-if="explorerEffect" class="effect-line">{{ explorerEffect }}</p>
        <p v-else class="hint">Not enough overlapping days for a clean effect estimate.</p>
        <div class="chart">
          <VChart v-if="scatterOption" :option="scatterOption" autoresize/>
          <div v-else class="empty">Not enough overlapping data points to plot.</div>
        </div>
      </Card>

      <div v-if="explorerErr" class="err">{{ explorerErr }}</div>

      <Card title="Common questions">
        <div class="presets">
          <button v-for="p in PRESETS" :key="p.label" class="preset" @click="applyPreset(p)">
            {{ p.label }}
          </button>
        </div>
      </Card>
    </details>
  </div>
</template>

<style scoped>
.ask-row { display: flex; gap: 0.5rem; }
.ask-input {
  flex: 1; background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 0.6rem 0.8rem; font-family: inherit; font-size: 0.9rem;
}
.ask-input:focus { outline: none; border-color: var(--violet); }
.ask-send {
  background: var(--violet); color: #fff; border: 0;
  border-radius: 8px; padding: 0.5rem 1rem; cursor: pointer;
  font-family: inherit; font-weight: 600; font-size: 0.85rem;
}
.ask-send:disabled { opacity: 0.5; cursor: not-allowed; }
.ask-answer {
  margin-top: 0.7rem; padding: 0.8rem 1rem;
  background: rgba(167, 139, 250, 0.05);
  border-left: 3px solid var(--violet);
  border-radius: 4px;
  color: var(--text-soft); font-size: 0.92rem; line-height: 1.55;
}
.ask-answer :deep(p) { margin: 0.3rem 0; }
.ask-answer :deep(ul) { margin: 0.3rem 0 0.3rem 1rem; padding: 0; }
.ask-answer :deep(strong) { color: var(--text); }

.explain-btn {
  background: rgba(167, 139, 250, 0.1); color: var(--violet);
  border: 1px solid rgba(167, 139, 250, 0.3); border-radius: 6px;
  padding: 0.2rem 0.6rem; font-size: 0.7rem; cursor: pointer;
  font-family: inherit; font-weight: 600;
  align-self: flex-start;
  margin-bottom: 0.3rem;
}
.explain-btn:hover { background: rgba(167, 139, 250, 0.2); }
.explain-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.explain-out {
  background: rgba(167, 139, 250, 0.05);
  border-left: 2px solid var(--violet);
  border-radius: 4px;
  padding: 0.5rem 0.7rem; margin-bottom: 0.4rem;
  font-size: 0.85rem; line-height: 1.45; color: var(--text-soft);
}
.explain-out :deep(p) { margin: 0.2rem 0; }
h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 1.2rem; }
.hint em { color: var(--text-soft); font-style: normal; font-weight: 500; }
.loading { color: var(--muted); padding: 2rem 0; text-align: center; }

.findings { display: flex; flex-direction: column; gap: 0.7rem; margin-bottom: 1.5rem; }

.finding-row {
  display: grid;
  grid-template-columns: 1fr 140px;
  gap: 1.2rem;
  align-items: center;
}
.finding-text { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.finding-headline {
  display: flex; align-items: center; gap: 0.4rem;
  font-size: 1.05rem; font-weight: 600; color: #22c55e;
  letter-spacing: -0.01em;
}
.finding-headline.neg { color: #ef4444; }
.dir-icon { flex-shrink: 0; }

.finding-effect { color: var(--text-soft); font-size: 0.88rem; line-height: 1.45; }

.finding-meta {
  display: flex; align-items: center; gap: 0.5rem;
  flex-wrap: wrap; font-size: 0.8rem; color: var(--muted);
}
.muted { color: var(--muted); }
.strength-label {
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--text-soft); font-weight: 600;
}
.strength-bar { display: inline-flex; gap: 2px; align-items: center; }
.strength-bar .seg {
  width: 14px; height: 6px; border-radius: 1px;
  background: rgba(148, 163, 184, 0.15);
}
.strength-bar .seg.on { background: #22c55e; }
.strength-bar .seg.on.neg { background: #ef4444; }
.strength-bar.large .seg { width: 18px; height: 8px; }

.open-btn {
  margin-left: auto;
  background: transparent; color: var(--accent);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.25rem 0.6rem; font-size: 0.78rem; font-family: inherit;
  cursor: pointer;
}
.open-btn:hover { border-color: var(--accent); background: rgba(56, 189, 248, 0.08); }

.mini-chart { width: 140px; height: 70px; }
.mini-chart > * { width: 100%; height: 100%; }

@media (max-width: 600px) {
  .finding-row { grid-template-columns: 1fr; }
  .mini-chart { width: 100%; height: 70px; }
}

/* ────── EMPTY ────── */
.empty-state p { margin: 0.4rem 0; }

/* ────── EXPLORER ────── */
.explorer-shell {
  margin-top: 1.2rem;
  border-top: 1px solid var(--border);
  padding-top: 1rem;
}
.explorer-shell > summary {
  cursor: pointer; list-style: none;
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 0;
  font-size: 0.95rem; font-weight: 500; color: var(--text-soft);
  user-select: none;
}
.explorer-shell > summary::-webkit-details-marker { display: none; }
.explorer-shell > summary .chev {
  transition: transform 0.15s; color: var(--muted);
}
.explorer-shell[open] > summary .chev { transform: rotate(180deg); }
.explorer-shell[open] > summary { margin-bottom: 0.6rem; }

.cfg {
  display: grid;
  grid-template-columns: 1fr auto 1fr 1fr 1fr;
  gap: 0.6rem;
  align-items: end;
}
.cfg label {
  display: flex; flex-direction: column; gap: 0.3rem;
  font-size: 0.75rem; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.05em;
}
.cfg select {
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.5rem 0.6rem; font-size: 0.9rem; font-family: inherit;
}
.swap {
  background: var(--surface-2); color: var(--muted);
  border: 1px solid var(--border); border-radius: 6px;
  width: 36px; height: 38px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; align-self: flex-end;
  margin-bottom: 0.05rem;
}
.swap:hover { color: var(--accent); border-color: var(--accent); }
@media (max-width: 700px) {
  .cfg { grid-template-columns: 1fr 1fr; }
  .swap { grid-column: span 2; width: 100%; height: 32px; }
}

.result-meta {
  display: flex; align-items: center; gap: 0.55rem;
  margin: 0.2rem 0 0.6rem; flex-wrap: wrap;
}
.effect-line {
  margin: 0 0 0.8rem; padding: 0.7rem 0.9rem;
  background: rgba(56, 189, 248, 0.06);
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  color: var(--text-soft); font-size: 0.92rem; line-height: 1.5;
}

.chart { width: 100%; height: 340px; }
.chart > * { width: 100%; height: 100%; }

.presets { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.preset {
  background: var(--surface-2); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.4rem 0.7rem; cursor: pointer;
  font-size: 0.8rem; font-family: inherit;
}
.preset:hover { border-color: var(--accent); color: var(--accent); }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err {
  color: var(--bad); padding: 0.6rem 0.8rem;
  background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad);
  margin: 0.6rem 0;
}
</style>
