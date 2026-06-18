<script setup lang="ts">
/**
 * CoachHub — merged AI-coach + analytics/insights screen of the
 * "Vitality Neon" redesign. A deterministic "Today's Read" hero
 * (no AI call — computed from todaySummary), correlation insight
 * cards from /analytics/discoveries, and a visual "Ask your coach…"
 * pill.
 *
 * Styling is scoped to `.coach-view` (neon tokens on the wrapper)
 * so it can land alongside the rest of the app without restyling
 * anything global.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";

interface Discovery {
  x_metric: string;
  y_metric: string;
  n: number;
  pearson_r: number;
}

const router = useRouter();
const loading = ref(true);
const sum = ref<TodaySummary | null>(null);
const disc = ref<Discovery[]>([]);

/** Humanize backend metric keys for display. */
const METRIC_LABELS: Record<string, string> = {
  resting_hr: "Resting HR",
  hrv_avg: "HRV",
  recovery_score: "Recovery",
  sleep_score: "Sleep",
  sleep_duration_s: "Sleep duration",
  sleep_consistency_score: "Sleep consistency",
  sleep_debt_h: "Sleep debt",
  readiness_score: "Readiness",
  steps_total: "Steps",
  weight_kg: "Weight",
  body_fat_pct: "Body fat",
  bp_systolic_avg: "Systolic BP",
  bp_diastolic_avg: "Diastolic BP",
  skin_temp_delta_avg: "Skin temp Δ",
  training_stress_score: "Training stress",
  ctl: "Fitness (CTL)",
  atl: "Fatigue (ATL)",
  tsb: "Form (TSB)",
};

function humanize(key: string | null | undefined): string {
  if (!key) return "—";
  return (
    METRIC_LABELS[key] ??
    key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

async function load(): Promise<void> {
  loading.value = true;
  const [s, d] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.discoveries(90).catch((): Discovery[] => []),
  ]);
  sum.value = s;
  disc.value = Array.isArray(d) ? d : [];
  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}

const today = computed<string>(() =>
  new Date().toLocaleDateString([], { weekday: "short", day: "numeric" }),
);

// ---- Deterministic "Today's Read" (NO AI call) ----
const recovery = computed<number | null>(() => sum.value?.recovery_score ?? null);
const hrv = computed<number | null>(() => sum.value?.hrv_avg ?? null);
const tsb = computed<number | null>(() => sum.value?.tsb ?? null);

type ReadTone = "strong" | "low" | "balanced";

const readTone = computed<ReadTone>(() => {
  const rec = recovery.value;
  const form = tsb.value ?? 0;
  if (rec != null && rec >= 70 && form >= 0) return "strong";
  if (rec != null && rec < 50) return "low";
  return "balanced";
});

const readHeadline = computed<string>(() => {
  switch (readTone.value) {
    case "strong":
      return "Strong recovery — make it a quality day.";
    case "low":
      return "Take it easy — recovery is low.";
    default:
      return "Balanced — train to feel.";
  }
});

const readBody = computed<string>(() => {
  switch (readTone.value) {
    case "strong":
      return "Nervous system is primed. Green light to push today — then guard the gains tonight.";
    case "low":
      return "Your body is still catching up. Keep it light, prioritise sleep, and let recovery rebound.";
    default:
      return "Nothing is flashing red. Read your warm-up and let how you feel set the intensity.";
  }
});

function fmt(n: number | null, d = 0): string {
  return n == null ? "—" : n.toFixed(d);
}
function fmtTsb(n: number | null): string {
  if (n == null) return "—";
  const r = Math.round(n);
  return r > 0 ? `+${r}` : `${r}`;
}

// ---- Insight cards (up to 3) ----
const insights = computed<Discovery[]>(() => disc.value.slice(0, 3));

const SPARK_ACCENTS = ["cyan", "lime", "mag"] as const;
type Accent = (typeof SPARK_ACCENTS)[number];
const ACCENT_HEX: Record<Accent, string> = {
  cyan: "#28e6ff",
  lime: "#5dff3b",
  mag: "#ff3ad8",
};

function accentFor(i: number): Accent {
  return SPARK_ACCENTS[i % SPARK_ACCENTS.length] ?? "cyan";
}

function rText(r: number | null | undefined): string {
  return r == null ? "—" : `r = ${r.toFixed(2)}`;
}

function strengthLabel(r: number | null | undefined): string {
  const a = Math.abs(r ?? 0);
  if (a >= 0.7) return "Strong link";
  if (a >= 0.4) return "Moderate link";
  return "Weak link";
}

/**
 * Build a deterministic monotonic point set for the inline spark.
 * Slope follows the sign of the correlation so the line reads the
 * relationship. Pure presentation — not the real series.
 */
function sparkPoints(r: number | null | undefined): { x: number; y: number }[] {
  const sign = (r ?? 0) >= 0 ? 1 : -1;
  const n = 8;
  const out: { x: number; y: number }[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const x = 14 + t * 292;
    // wobble keeps it from looking too synthetic but stays deterministic
    const wobble = (i % 2 === 0 ? 0 : 4) - (i % 3) * 1.5;
    const base = sign > 0 ? 44 - t * 32 : 12 + t * 32;
    const y = Math.max(8, Math.min(48, base + wobble));
    out.push({ x, y });
  }
  return out;
}

function sparkLine(r: number | null | undefined): string {
  const pts = sparkPoints(r);
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (!first || !last) return "";
  return `M${first.x.toFixed(1)} ${first.y.toFixed(1)} L${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
}
</script>

<template>
  <div class="coach-view">
    <header class="head">
      <div class="avatar">
        <div class="ax">✦</div>
        <h1>Coach</h1>
      </div>
      <span class="date">{{ today }}</span>
    </header>

    <!-- Today's Read hero (deterministic, no AI) -->
    <button
      class="hero"
      :class="readTone"
      @click="go('/heart-rate')"
      aria-label="Recovery detail"
    >
      <div class="lbl">Today's Read</div>
      <h2>{{ readHeadline }}</h2>
      <p>{{ readBody }}</p>
      <div class="chips">
        <span class="chip bg-cyan cyan">HRV {{ fmt(hrv) }}<small v-if="hrv != null">ms</small></span>
        <span class="chip bg-lime lime">TSB {{ fmtTsb(tsb) }}</span>
        <span class="chip bg-mag mag">Recovery {{ fmt(recovery) }}<small v-if="recovery != null">%</small></span>
      </div>
    </button>

    <div class="cap">Insights</div>

    <!-- Correlation insight cards -->
    <template v-if="insights.length">
      <button
        v-for="(ins, i) in insights"
        :key="`${ins.x_metric}-${ins.y_metric}-${i}`"
        class="card ins"
        @click="go('/insights')"
        :aria-label="`${humanize(ins.x_metric)} correlated with ${humanize(ins.y_metric)}`"
      >
        <div class="top">
          <div class="ii" :class="`bg-${accentFor(i)} ${accentFor(i)}`">⚡</div>
          <div class="ttl">
            {{ humanize(ins.x_metric) }} ↔ {{ humanize(ins.y_metric) }}
            <small>{{ strengthLabel(ins.pearson_r) }} · n = {{ ins.n ?? "—" }}</small>
          </div>
          <div class="stat" :class="accentFor(i)">{{ rText(ins.pearson_r) }}</div>
        </div>
        <div class="spark">
          <svg viewBox="0 0 320 56" width="100%" height="40" preserveAspectRatio="none">
            <defs>
              <linearGradient :id="`cl${i}`" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" :stop-color="ACCENT_HEX[accentFor(i)]" stop-opacity=".25" />
                <stop offset="1" :stop-color="ACCENT_HEX[accentFor(i)]" />
              </linearGradient>
            </defs>
            <path
              :d="sparkLine(ins.pearson_r)"
              :stroke="`url(#cl${i})`"
              stroke-width="2.5"
              stroke-linecap="round"
              fill="none"
              opacity=".55"
            />
            <circle
              v-for="(pt, j) in sparkPoints(ins.pearson_r)"
              :key="j"
              :cx="pt.x"
              :cy="pt.y"
              r="3.2"
              :fill="ACCENT_HEX[accentFor(i)]"
              :opacity="j % 2 === 0 ? 1 : 0.6"
            />
          </svg>
        </div>
      </button>
    </template>

    <!-- Empty state -->
    <div v-else class="empty">
      <div class="ei">◇</div>
      <div class="et">No strong patterns yet</div>
      <div class="es">
        Keep logging — once there's enough history, your hidden
        correlations show up here.
      </div>
    </div>

    <!-- Visual-only "Ask your coach" pill -->
    <div class="ask">
      <input placeholder="Ask your coach…" disabled />
      <div class="send" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.coach-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-card2: #1d2030; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-amber: #ffb52e; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}

.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.head .avatar { display: flex; align-items: center; gap: 10px; }
.head .ax { width: 34px; height: 34px; border-radius: 11px; display: flex; align-items: center; justify-content: center;
  font-size: 18px; color: #fff;
  background: radial-gradient(120% 120% at 30% 20%, #ff7ce6, #ff3ad8 55%, #b81f9d);
  box-shadow: 0 0 18px rgba(255, 58, 216, 0.6), inset 0 0 8px rgba(255, 255, 255, 0.35); }
.head h1 { font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px; }
.head .date { color: var(--rn-mut); font-weight: 600; font-size: 14px; }

.cap { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.12em; color: var(--rn-mut); text-transform: uppercase; margin: 2px 0 9px; }

.hero { position: relative; display: block; width: 100%; text-align: left; cursor: pointer; color: inherit;
  border-radius: 22px; padding: 15px 16px; margin-bottom: 13px; overflow: hidden;
  background: linear-gradient(135deg, rgba(255, 58, 216, 0.22), rgba(40, 230, 255, 0.12) 70%), var(--rn-card2);
  border: 1px solid rgba(255, 58, 216, 0.28); box-shadow: 0 10px 34px -16px rgba(255, 58, 216, 0.55);
  transition: transform 0.12s ease; }
.hero:active { transform: scale(0.99); }
.hero.low { background: linear-gradient(135deg, rgba(255, 181, 46, 0.22), rgba(255, 58, 216, 0.10) 70%), var(--rn-card2);
  border-color: rgba(255, 181, 46, 0.30); box-shadow: 0 10px 34px -16px rgba(255, 181, 46, 0.50); }
.hero.balanced { background: linear-gradient(135deg, rgba(40, 230, 255, 0.18), rgba(93, 255, 59, 0.10) 70%), var(--rn-card2);
  border-color: rgba(40, 230, 255, 0.28); box-shadow: 0 10px 34px -16px rgba(40, 230, 255, 0.45); }
.hero::after { content: ""; position: absolute; right: -50px; top: -60px; width: 160px; height: 160px; border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 58, 216, 0.45), transparent 65%); filter: blur(6px); pointer-events: none; }
.hero.low::after { background: radial-gradient(circle, rgba(255, 181, 46, 0.42), transparent 65%); }
.hero.balanced::after { background: radial-gradient(circle, rgba(40, 230, 255, 0.42), transparent 65%); }
.hero .lbl { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 10.5px; font-weight: 700;
  letter-spacing: 0.16em; color: var(--rn-mag); text-transform: uppercase;
  filter: drop-shadow(0 0 8px rgba(255, 58, 216, 0.6)); display: flex; align-items: center; gap: 7px; }
.hero .lbl::before { content: "✦"; font-size: 12px; }
.hero.low .lbl { color: var(--rn-amber); filter: drop-shadow(0 0 8px rgba(255, 181, 46, 0.6)); }
.hero.balanced .lbl { color: var(--rn-cyan); filter: drop-shadow(0 0 8px rgba(40, 230, 255, 0.6)); }
.hero h2 { margin: 7px 0 6px; font-size: 18px; font-weight: 800; line-height: 1.22; letter-spacing: -0.3px;
  position: relative; z-index: 1; }
.hero p { margin: 0; font-size: 12.5px; line-height: 1.42; color: #c8c8db; position: relative; z-index: 1; }
.hero p b { color: var(--rn-ink); }
.hero .chips { display: flex; gap: 7px; margin-top: 11px; position: relative; z-index: 1; flex-wrap: wrap; }
.hero .chip { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  padding: 5px 10px; border-radius: 999px; display: flex; align-items: center; gap: 4px; }
.hero .chip small { font-weight: 700; opacity: 0.7; font-size: 9.5px; }

.mag { color: var(--rn-mag); } .lime { color: var(--rn-lime); } .cyan { color: var(--rn-cyan); } .amber { color: var(--rn-amber); }
.bg-mag { background: rgba(255, 58, 216, 0.14); } .bg-lime { background: rgba(93, 255, 59, 0.14); }
.bg-cyan { background: rgba(40, 230, 255, 0.14); } .bg-amber { background: rgba(255, 181, 46, 0.14); }

.card { background: var(--rn-card); border-radius: 20px; padding: 16px 18px; margin-bottom: 12px; }
.ins { display: block; width: 100%; text-align: left; border: 0; color: inherit; cursor: pointer;
  padding: 12px 14px; margin-bottom: 10px; transition: transform 0.12s ease; }
.ins:active { transform: scale(0.99); }
.ins .top { display: flex; align-items: center; gap: 12px; }
.ins .ii { width: 34px; height: 34px; border-radius: 11px; display: flex; align-items: center; justify-content: center;
  flex: 0 0 auto; font-size: 16px; }
.ins .ttl { flex: 1; font-weight: 700; font-size: 14px; line-height: 1.22; }
.ins .ttl small { display: block; color: var(--rn-mut); font-weight: 500; font-size: 11.5px; margin-top: 2px;
  font-family: 'Space Grotesk', 'Geist Mono', monospace; }
.ins .stat { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 16px; flex: 0 0 auto; }
.spark { margin-top: 9px; }
.spark svg { display: block; }

.empty { background: var(--rn-card); border-radius: 20px; padding: 26px 20px; text-align: center; margin-bottom: 10px; }
.empty .ei { font-size: 26px; color: var(--rn-mag); filter: drop-shadow(0 0 8px rgba(255, 58, 216, 0.5)); margin-bottom: 8px; }
.empty .et { font-weight: 800; font-size: 16px; margin-bottom: 5px; }
.empty .es { color: var(--rn-mut); font-size: 12.5px; line-height: 1.5; max-width: 260px; margin: 0 auto; }

.ask { display: flex; align-items: center; gap: 10px; background: var(--rn-card); border: 1px solid #2a2d40;
  border-radius: 999px; padding: 7px 7px 7px 18px; margin-top: 6px; margin-bottom: 8px; }
.ask input { flex: 1; background: transparent; border: 0; outline: none; color: var(--rn-ink);
  font-family: 'Plus Jakarta Sans', system-ui; font-size: 14px; font-weight: 500; }
.ask input::placeholder { color: var(--rn-mut); }
.ask .send { width: 40px; height: 40px; border-radius: 50%; flex: 0 0 auto; display: flex; align-items: center;
  justify-content: center; background: radial-gradient(120% 120% at 30% 20%, #ff7ce6, #ff3ad8 60%, #c41fa6);
  box-shadow: 0 0 16px rgba(255, 58, 216, 0.55); }
.ask .send svg { width: 19px; height: 19px; color: #fff; }
</style>
