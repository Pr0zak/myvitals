<script setup lang="ts">
/**
 * RingsRefined — the "Neon Refined" (A1) home screen.
 *
 * Ported from the locked A1 design mockup: a concentric tri-ring hero
 * (Recovery / Move / Sleep), disciplined cyan-lead palette, real vitals tiles,
 * streak cards, today's workout, sleep + weight readouts. Rendered by Rings.vue
 * when the "Neon Refined" theme is active (see theme.ts `isRefined`).
 *
 * Data comes from the same backend endpoints the rest of the app uses — nothing
 * is computed client-side beyond formatting. Scoped to `.refined-home`; colours
 * ride the neon CSS vars (--accent/--good/--warn/--violet) that are live under
 * data-theme="neon".
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { StrengthWorkoutDetail, SleepNight } from "@/api/types";

const router = useRouter();
const loading = ref(true);

const sleepScore = ref<number | null>(null);
const recoveryScore = ref<number | null>(null);
const readiness = ref<number | null>(null);
const steps = ref<number | null>(null);
const stepGoal = ref(10000);
const hrv = ref<number | null>(null);
const rhr = ref<number | null>(null);
const skinTemp = ref<number | null>(null);
const sleepDurS = ref<number | null>(null);
const weightKg = ref<number | null>(null);
const bodyFat = ref<number | null>(null);
const soberDays = ref<number | null>(null);
const fastH = ref<number | null>(null);
const fastTarget = ref(16);
const fastActive = ref(false);
const fastStage = ref<string | null>(null);
const workout = ref<StrengthWorkoutDetail | null>(null);

// deltas + sparkline
const hrvDelta = ref<number | null>(null);
const rhrDelta = ref<number | null>(null);
const weightDelta7Kg = ref<number | null>(null);
const lastSleep = ref<SleepNight | null>(null);
const weightPts = ref<number[]>([]);

async function load() {
  loading.value = true;
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 3600 * 1000);
  const since30 = new Date(now.getTime() - 30 * 24 * 3600 * 1000);
  const [sum, prof, sober, fast, wk, prior, sleepN, wt] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.getProfile().catch(() => null),
    api.soberStats().catch(() => null),
    api.fastingCurrent().catch(() => null),
    api.strengthToday().catch(() => null),
    api.summaryRange(yesterday).catch(() => null),
    api.lastSleep().catch(() => null),
    api.weight({ since: since30 }).catch(() => null),
  ]);
  if (sum) {
    sleepScore.value = sum.sleep_score;
    recoveryScore.value = sum.recovery_score;
    readiness.value = sum.readiness_score;
    steps.value = sum.steps_total;
    hrv.value = sum.hrv_avg;
    rhr.value = sum.resting_hr;
    skinTemp.value = sum.skin_temp_delta_avg;
    sleepDurS.value = sum.sleep_duration_s;
    weightKg.value = sum.weight_kg;
    bodyFat.value = sum.body_fat_pct;
  }
  const extra = prof?.extra as { steps_goal?: number } | undefined;
  if (extra?.steps_goal != null) stepGoal.value = Math.round(extra.steps_goal);
  if (sober) soberDays.value = sober.current_days;
  if (fast && fast.is_active) {
    fastActive.value = true;
    fastH.value = fast.elapsed_h;
    fastStage.value = fast.current_stage;
    if (fast.target_hours) fastTarget.value = fast.target_hours;
  }
  workout.value = wk;

  // deltas: today vs most-recent prior-day summary row
  if (prior && prior.length) {
    const todayStr = new Date().toISOString().slice(0, 10);
    const priorRows = prior
      .filter((r) => r.date < todayStr)
      .sort((a, b) => a.date.localeCompare(b.date));
    const p = priorRows.length ? priorRows[priorRows.length - 1] : null;
    if (p) {
      if (hrv.value != null && p.hrv_avg != null) hrvDelta.value = hrv.value - p.hrv_avg;
      if (rhr.value != null && p.resting_hr != null) rhrDelta.value = rhr.value - p.resting_hr;
    }
  }

  lastSleep.value = sleepN;

  // weight sparkline + 7-day delta from the 30-day series
  if (wt) {
    const rows = wt.points
      .filter((pt): pt is typeof pt & { weight_kg: number } => pt.weight_kg != null)
      .sort((a, b) => a.time.localeCompare(b.time));
    weightPts.value = rows.map((r) => r.weight_kg);
    if (rows.length) {
      const cutoff = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
      const past = rows.filter((r) => r.time <= cutoff);
      const base = past.length ? past[past.length - 1] : rows[0];
      weightDelta7Kg.value = rows[rows.length - 1].weight_kg - base.weight_kg;
    }
  }

  loading.value = false;
}
onMounted(load);

function go(path: string) {
  router.push(path);
}

// ---- ring geometry (concentric arcs, correct dash math per radius) ----
function dash(pct: number, r: number): string {
  const c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, pct));
  return `${((p / 100) * c).toFixed(1)} ${c.toFixed(1)}`;
}
const movePct = computed(() =>
  steps.value != null ? Math.min(100, (steps.value / stepGoal.value) * 100) : 0,
);
const fastPct = computed(() =>
  fastH.value != null ? Math.min(100, (fastH.value / fastTarget.value) * 100) : 0,
);

// ---- formatting ----
const today = computed(() =>
  new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }),
);
const greeting = computed(() => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
});
function fmt(n: number | null, d = 0): string {
  return n == null ? "—" : n.toFixed(d);
}
function signed(n: number | null, d = 1): string {
  if (n == null) return "—";
  return (n > 0 ? "+" : "") + n.toFixed(d);
}
const weightLb = computed(() =>
  weightKg.value == null ? null : weightKg.value * 2.2046226,
);
const sleepHm = computed(() => {
  if (sleepDurS.value == null) return "—";
  const m = Math.round(sleepDurS.value / 60);
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
});
const sleepPctTo8 = computed(() =>
  sleepDurS.value == null ? 0 : Math.min(100, (sleepDurS.value / (8 * 3600)) * 100),
);

// ---- derived reads ----
const readLine = computed(() => {
  const r = recoveryScore.value;
  if (r == null) return "Sync your watch to see today's recovery read.";
  if (r >= 67) return "Recovery good · you're clear to train hard.";
  if (r >= 34) return "Recovery moderate · train smart, keep RPE in check.";
  return "Recovery low · consider an easy day or rest.";
});
const recoveryStatus = computed(() => {
  const r = recoveryScore.value;
  if (r == null) return { t: "—", c: "muted" };
  if (r >= 67) return { t: "GOOD", c: "good" };
  if (r >= 34) return { t: "MODERATE", c: "warn" };
  return { t: "LOW", c: "bad" };
});
const workoutTitle = computed(() => {
  const w = workout.value;
  if (!w) return "No workout planned";
  const f = w.split_focus;
  const cap = f.charAt(0).toUpperCase() + f.slice(1);
  return ["push", "pull", "legs"].includes(f) ? `${cap} day` : cap;
});
const workoutSub = computed(() => {
  const w = workout.value;
  if (!w) return "Tap to generate today's plan";
  const n = w.exercises?.length ?? 0;
  const parts = [`${n} exercise${n === 1 ? "" : "s"}`];
  if (w.deload_factor != null && w.deload_factor < 1)
    parts.push(`targets eased ${Math.round((1 - w.deload_factor) * 100)}%`);
  return parts.join(" · ");
});
const workoutDone = computed(() => workout.value?.status === "completed");

// ---- deltas ----
/** class by good-direction: goodUp=true → up is lime; goodUp=false → down is lime */
function deltaClass(v: number | null, goodUp: boolean): string {
  if (v == null || v === 0) return "flat";
  const up = v > 0;
  return up === goodUp ? "up-good" : "down-bad";
}
function deltaArrow(v: number | null): string {
  if (v == null || v === 0) return "";
  return v > 0 ? "▲" : "▼";
}
function deltaLabel(v: number | null, d = 0): string {
  if (v == null) return "";
  const a = Math.abs(v);
  return a.toFixed(d);
}
const hrvDeltaClass = computed(() => deltaClass(hrvDelta.value, true));
const rhrDeltaClass = computed(() => deltaClass(rhrDelta.value, false));
// weight delta shown neutral (no universal good direction) → cyan-muted
const weightDelta7Lb = computed(() =>
  weightDelta7Kg.value == null ? null : weightDelta7Kg.value * 2.2046226,
);

// ---- sleep stages ----
type Seg = { key: string; label: string; color: string; s: number; pct: number };
const STAGE_MAP: Record<string, { label: string; color: string }> = {
  deep: { label: "Deep", color: "#ff3ad8" },
  light: { label: "Light", color: "#6f7bff" },
  rem: { label: "REM", color: "#28e6ff" },
  awake: { label: "Awake", color: "#ffb52e" },
};
const sleepSegs = computed<Seg[]>(() => {
  const sn = lastSleep.value;
  if (!sn || !sn.stages || !sn.stages.length) return [];
  // sum by normalised stage key
  const sums: Record<string, number> = {};
  for (const b of sn.stages) {
    const k = (b.stage || "").toLowerCase();
    const key = k in STAGE_MAP ? k : k.includes("rem") ? "rem" : k.includes("deep") ? "deep"
      : k.includes("light") ? "light" : k.includes("wake") || k.includes("awake") ? "awake" : "";
    if (!key) continue;
    sums[key] = (sums[key] ?? 0) + (b.duration_s || 0);
  }
  const total = Object.values(sums).reduce((a, b) => a + b, 0);
  if (total <= 0) return [];
  const order = ["deep", "rem", "light", "awake"];
  return order
    .filter((k) => sums[k] > 0)
    .map((k) => ({
      key: k,
      label: STAGE_MAP[k].label,
      color: STAGE_MAP[k].color,
      s: sums[k],
      pct: (sums[k] / total) * 100,
    }));
});
const hasSleepSegs = computed(() => sleepSegs.value.length > 0);
function segHm(s: number): string {
  const m = Math.round(s / 60);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

// ---- weight sparkline (cyan inline SVG polyline) ----
const SPARK_W = 96;
const SPARK_H = 26;
const weightSparkPoints = computed<string>(() => {
  const pts = weightPts.value;
  if (pts.length < 2) return "";
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const stepX = SPARK_W / (pts.length - 1);
  return pts
    .map((v, i) => {
      const x = i * stepX;
      const y = SPARK_H - 2 - ((v - min) / span) * (SPARK_H - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
});
</script>

<template>
  <div class="refined-home">
    <!-- top bar -->
    <header class="topbar">
      <div class="brand">
        <svg class="mark" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round">
          <circle cx="12" cy="12" r="9" stroke="var(--violet)" stroke-dasharray="42 14" />
          <circle cx="12" cy="12" r="6" stroke="var(--good)" stroke-dasharray="26 12" />
          <circle cx="12" cy="12" r="3" stroke="var(--accent)" />
        </svg>
        <div class="greet">
          <div class="hi">{{ greeting }}</div>
          <div class="dt">{{ today }}</div>
        </div>
      </div>
      <button class="iconbtn" @click="go('/settings')" aria-label="Settings">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </header>

    <!-- hero: concentric tri-ring -->
    <section class="hero card">
      <div class="hero-row">
        <button class="rings" @click="go('/heart-rate')" aria-label="Recovery detail">
          <svg viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--track)" stroke-width="7" />
            <circle cx="60" cy="60" r="41" fill="none" stroke="var(--track)" stroke-width="7" />
            <circle cx="60" cy="60" r="30" fill="none" stroke="var(--track)" stroke-width="7" />
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--accent)" stroke-width="7"
              stroke-linecap="round" :stroke-dasharray="dash(recoveryScore ?? 0, 52)"
              transform="rotate(-90 60 60)" />
            <circle cx="60" cy="60" r="41" fill="none" stroke="var(--good)" stroke-width="7"
              stroke-linecap="round" :stroke-dasharray="dash(movePct, 41)"
              transform="rotate(-90 60 60)" />
            <circle cx="60" cy="60" r="30" fill="none" stroke="var(--violet)" stroke-width="7"
              stroke-linecap="round" :stroke-dasharray="dash(sleepScore ?? 0, 30)"
              transform="rotate(-90 60 60)" />
          </svg>
          <div class="rings-center">
            <div class="big num">{{ fmt(recoveryScore) }}</div>
            <div class="lbl">RECOVERY</div>
          </div>
        </button>

        <div class="legend">
          <button class="leg" @click="go('/heart-rate')">
            <span class="dot" style="background:var(--accent)"></span>
            <span class="meta">
              <span class="k">Recovery</span>
              <span class="v num">{{ fmt(recoveryScore) }}
                <span class="pill" :class="recoveryStatus.c">{{ recoveryStatus.t }}</span>
              </span>
            </span>
          </button>
          <button class="leg" @click="go('/steps')">
            <span class="dot" style="background:var(--good)"></span>
            <span class="meta">
              <span class="k">Move · steps</span>
              <span class="v num">{{ steps != null ? steps.toLocaleString() : "—" }}
                <small>/ {{ stepGoal.toLocaleString() }}</small></span>
            </span>
          </button>
          <button class="leg" @click="go('/sleep')">
            <span class="dot" style="background:var(--violet)"></span>
            <span class="meta">
              <span class="k">Sleep score</span>
              <span class="v num">{{ fmt(sleepScore) }}</span>
            </span>
          </button>
        </div>
      </div>
      <div class="read">{{ readLine }}</div>
    </section>

    <!-- vitals tiles -->
    <section class="vitals">
      <button class="tile" @click="go('/hrv')">
        <div class="tk">HRV</div>
        <div class="tv num">{{ fmt(hrv) }}<u>ms</u></div>
        <div v-if="hrvDelta != null" class="tdelta num" :class="hrvDeltaClass">
          {{ deltaArrow(hrvDelta) }} {{ deltaLabel(hrvDelta) }}
        </div>
      </button>
      <button class="tile" @click="go('/heart-rate')">
        <div class="tk">RESTING HR</div>
        <div class="tv num">{{ fmt(rhr) }}<u>bpm</u></div>
        <div v-if="rhrDelta != null" class="tdelta num" :class="rhrDeltaClass">
          {{ deltaArrow(rhrDelta) }} {{ deltaLabel(rhrDelta) }}
        </div>
      </button>
      <button class="tile" @click="go('/skin-temp')">
        <div class="tk">SKIN TEMP</div>
        <div class="tv num">{{ signed(skinTemp) }}<u>°C</u></div>
      </button>
      <button class="tile" @click="go('/trends')">
        <div class="tk">READINESS</div>
        <div class="tv num">{{ fmt(readiness) }}</div>
      </button>
    </section>

    <!-- streaks -->
    <section class="streaks">
      <button class="streak" @click="go('/sober')">
        <span class="ico" style="background:rgba(255,58,216,.14);color:var(--violet)">✦</span>
        <span class="txt">
          <span class="lab">Sober</span>
          <span class="big num">{{ soberDays != null ? Math.floor(soberDays) : "—" }}<small> days</small></span>
        </span>
      </button>
      <button class="streak" @click="go('/fasting')">
        <span class="ico" style="background:rgba(255,181,46,.14);color:var(--warn)">◔</span>
        <span class="txt">
          <span class="lab">Fasting <template v-if="fastActive">· {{ fastStage }}</template></span>
          <span class="big num">{{ fmt(fastH, 1) }}h<small> / {{ fastTarget }}h</small></span>
          <span class="bar"><i :style="{ width: fastPct + '%', background: 'var(--warn)' }"></i></span>
        </span>
      </button>
    </section>

    <!-- today's workout -->
    <button class="card wk" @click="go('/workout/strength/today')">
      <span class="wico">🏋</span>
      <span class="wmeta">
        <span class="wt">{{ workoutTitle }}</span>
        <span class="ws">{{ workoutSub }}</span>
      </span>
      <span class="startbtn">{{ workoutDone ? "View" : "Start" }}</span>
    </button>

    <!-- sleep last night -->
    <button class="card sleep" @click="go('/sleep')">
      <div class="crow">
        <span class="ctitle">Last night</span>
        <span class="num cval">{{ sleepHm }}</span>
      </div>
      <template v-if="hasSleepSegs">
        <div class="stagebar">
          <i v-for="s in sleepSegs" :key="s.key"
            :style="{ width: s.pct + '%', background: s.color }"></i>
        </div>
        <div class="stagelegend">
          <span v-for="s in sleepSegs" :key="s.key" class="sleg">
            <span class="sdot" :style="{ background: s.color }"></span>
            <span class="slk">{{ s.label }}</span>
            <span class="slv num">{{ segHm(s.s) }}</span>
          </span>
        </div>
      </template>
      <template v-else>
        <div class="bar big"><i :style="{ width: sleepPctTo8 + '%', background: 'var(--violet)' }"></i></div>
        <div class="csub"><span>Sleep score {{ fmt(sleepScore) }}</span><span class="muted">goal 8h</span></div>
      </template>
    </button>

    <!-- weight -->
    <button class="card weight" @click="go('/weight')">
      <div class="crow">
        <span class="ctitle">Weight</span>
        <span class="num cval">{{ fmt(weightLb, 1) }}<u v-if="weightLb != null">lb</u></span>
      </div>
      <svg v-if="weightSparkPoints" class="wspark" :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`" preserveAspectRatio="none">
        <polyline :points="weightSparkPoints" fill="none" stroke="var(--accent)"
          stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <div class="csub">
        <span class="muted">Body fat {{ fmt(bodyFat, 1) }}<template v-if="bodyFat != null">%</template></span>
        <span v-if="weightDelta7Lb != null" class="num wdelta">
          {{ deltaArrow(weightDelta7Lb) }} {{ deltaLabel(weightDelta7Lb, 1) }}lb · 7d
        </span>
        <span v-else class="chev">›</span>
      </div>
    </button>
  </div>
</template>

<style scoped>
.refined-home {
  /* ride the neon tokens; local fallbacks keep it sane outside data-theme=neon */
  --accent: var(--accent, #28e6ff);
  --good: var(--good, #5dff3b);
  --warn: var(--warn, #ffb52e);
  --violet: var(--violet, #ff3ad8);
  --bad: var(--bad, #ff5d7a);
  --ink: var(--text, #f0f0f7);
  --muted-c: var(--muted, #9b9bb0);
  --dim: #7c7d94;
  --glass: rgba(255, 255, 255, 0.04);
  --hair: rgba(155, 155, 176, 0.14);
  --track: #23263a;
  --num: "Space Grotesk", "Geist Mono", monospace;

  margin: -1.25rem -1.5rem;
  padding: 22px 16px 108px;
  min-height: 100vh;
  color: var(--ink);
  font-family: "Plus Jakarta Sans", "Geist", system-ui, sans-serif;
  background: radial-gradient(120% 45% at 50% -6%, #161a2c, #0f1118 60%);
}
.refined-home button { font-family: inherit; color: inherit; cursor: pointer; }
.num { font-family: var(--num); font-variant-numeric: tabular-nums; }

.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.brand { display: flex; align-items: center; gap: 11px; }
.mark { width: 34px; height: 34px; flex: 0 0 auto; }
.greet .hi { font-size: 15px; font-weight: 700; letter-spacing: -0.01em; }
.greet .dt { font-size: 12px; color: var(--muted-c); margin-top: 1px; }
.iconbtn {
  margin-left: auto; width: 38px; height: 38px; border-radius: 12px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: var(--glass); border: 1px solid var(--hair); color: var(--muted-c);
}
.iconbtn svg { width: 19px; height: 19px; }

.card {
  display: block; width: 100%; text-align: left;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.015));
  border: 1px solid var(--hair); border-radius: 18px; padding: 15px 16px;
}
.hero { margin-bottom: 12px; padding-bottom: 0; overflow: hidden; }
.hero-row { display: flex; align-items: center; gap: 16px; }
.rings { position: relative; width: 148px; height: 148px; flex: 0 0 auto; background: none; border: 0; padding: 0; }
.rings svg { width: 100%; height: 100%; display: block; }
/* dead-center the number on the true ring center; float the label below it
 * (absolute) so it never shifts the number off-centre. */
.rings-center { position: absolute; inset: 0; display: grid; place-items: center; }
.rings-center .big { font-size: 40px; font-weight: 700; line-height: 1; letter-spacing: -0.03em; color: var(--ink); }
.rings-center .lbl { position: absolute; left: 0; right: 0; top: calc(50% + 21px); text-align: center; font-size: 9px; font-weight: 700; letter-spacing: 0.16em; color: var(--muted-c); }

.legend { display: flex; flex-direction: column; gap: 12px; flex: 1; min-width: 0; }
.leg { display: flex; align-items: flex-start; gap: 9px; background: none; border: 0; padding: 0; text-align: left; }
.leg .dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; margin-top: 5px; }
.leg .k { display: block; font-size: 10px; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; color: var(--muted-c); }
.leg .v { display: block; font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin-top: 2px; }
.leg .v small { font-size: 11px; color: var(--dim); font-weight: 500; }
.pill { display: inline-flex; align-items: center; font-size: 8.5px; font-weight: 700; letter-spacing: 0.06em;
  padding: 2px 7px; border-radius: 20px; margin-left: 4px; vertical-align: middle; }
.pill.good { color: var(--good); background: rgba(93, 255, 59, 0.13); }
.pill.warn { color: var(--warn); background: rgba(255, 181, 46, 0.14); }
.pill.bad { color: var(--bad); background: rgba(255, 93, 122, 0.14); }
.pill.muted { color: var(--muted-c); background: var(--glass); }

.read { margin: 14px -16px 0; padding: 12px 16px 14px; border-top: 1px solid var(--hair);
  font-size: 12.5px; color: var(--muted-c); line-height: 1.35; }

.vitals { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.tile { background: var(--glass); border: 1px solid var(--hair); border-radius: 13px; padding: 10px 9px; text-align: left; }
.tile .tk { font-size: 8.5px; font-weight: 700; letter-spacing: 0.04em; color: var(--muted-c); white-space: nowrap; }
.tile .tv { font-size: 19px; font-weight: 600; margin-top: 6px; letter-spacing: -0.02em; white-space: nowrap; }
.tile .tv u { font-size: 9px; color: var(--dim); text-decoration: none; font-weight: 500; margin-left: 1px; }

.streaks { display: grid; grid-template-columns: 1fr 1.25fr; gap: 9px; margin-bottom: 12px; }
.streak { display: flex; align-items: center; gap: 11px; background: var(--glass); border: 1px solid var(--hair);
  border-radius: 15px; padding: 12px; text-align: left; }
.streak .ico { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  flex: 0 0 auto; font-size: 16px; }
.streak .txt { min-width: 0; flex: 1; }
.streak .lab { display: block; font-size: 10px; font-weight: 600; color: var(--muted-c); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.streak .big { display: block; font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin-top: 1px; }
.streak .big small { font-size: 11px; color: var(--dim); font-weight: 500; }
.bar { height: 4px; border-radius: 4px; background: rgba(255, 255, 255, 0.09); overflow: hidden; margin-top: 7px; }
.bar.big { height: 8px; border-radius: 6px; margin-top: 10px; }
.bar i { display: block; height: 100%; border-radius: 6px; }

.wk { display: flex; align-items: center; gap: 13px; margin-bottom: 12px; }
.wk .wico { width: 42px; height: 42px; border-radius: 12px; flex: 0 0 auto; display: flex; align-items: center;
  justify-content: center; font-size: 20px; background: rgba(40, 230, 255, 0.12); border: 1px solid rgba(40, 230, 255, 0.22); }
.wk .wmeta { flex: 1; min-width: 0; }
.wk .wt { display: block; font-size: 16px; font-weight: 700; }
.wk .ws { display: block; font-size: 12px; color: var(--muted-c); margin-top: 2px; }
.startbtn { flex: 0 0 auto; padding: 9px 16px; border-radius: 11px; font-weight: 700; font-size: 13px;
  color: #04212a; background: linear-gradient(120deg, var(--accent), #17b9d6); }

.sleep, .weight { margin-bottom: 12px; }
.crow { display: flex; align-items: baseline; justify-content: space-between; }
.ctitle { font-size: 12px; font-weight: 600; letter-spacing: 0.02em; color: var(--muted-c); text-transform: uppercase; }
.cval { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; }
.cval u { font-size: 11px; color: var(--dim); text-decoration: none; margin-left: 2px; }
.csub { display: flex; align-items: center; justify-content: space-between; margin-top: 9px; font-size: 12px; }
.csub .muted, .muted { color: var(--muted-c); }
.chev { color: var(--dim); font-size: 18px; }

/* vitals tile deltas */
.tdelta { font-size: 10px; font-weight: 600; margin-top: 3px; letter-spacing: 0.01em; white-space: nowrap; }
.tdelta.up-good { color: var(--good); }
.tdelta.down-bad { color: var(--bad); }
.tdelta.flat { color: var(--muted-c); }

/* sleep stage bar */
.stagebar { display: flex; width: 100%; height: 9px; border-radius: 6px; overflow: hidden;
  margin-top: 11px; background: rgba(255, 255, 255, 0.06); }
.stagebar i { display: block; height: 100%; }
.stagelegend { display: flex; flex-wrap: wrap; gap: 5px 14px; margin-top: 10px; }
.sleg { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted-c); }
.sleg .sdot { width: 7px; height: 7px; border-radius: 2px; flex: 0 0 auto; }
.sleg .slk { font-weight: 600; }
.sleg .slv { color: var(--ink); font-weight: 600; margin-left: 1px; }

/* weight sparkline + delta */
.wspark { display: block; width: 100%; height: 26px; margin-top: 10px; }
.wdelta { font-size: 11px; font-weight: 600; color: var(--accent); white-space: nowrap; }
</style>
