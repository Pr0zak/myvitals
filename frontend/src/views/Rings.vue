<script setup lang="ts">
/**
 * Rings home — first screen of the "Vitality Neon" redesign (Direction D).
 * Glanceable goal rings + streak pills wired to the real backend. Tapping a
 * ring/pill drills into the existing detail views; the redesign migrates
 * outward from here.
 *
 * Styling is deliberately scoped to `.rings-view` so this view can land in the
 * live app without restyling everything else yet.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";

const router = useRouter();
const loading = ref(true);

const sleepScore = ref<number | null>(null);
const recoveryScore = ref<number | null>(null);
const steps = ref<number | null>(null);
const stepGoal = ref(10000);
const soberDays = ref<number | null>(null);
const fastH = ref<number | null>(null);
const fastTarget = ref(16);
const fastActive = ref(false);

const C = 2 * Math.PI * 42; // ring circumference

function dash(pct: number): string {
  const p = Math.max(0, Math.min(100, pct));
  return `${((p / 100) * C).toFixed(1)} ${C.toFixed(1)}`;
}
const movePct = computed(() =>
  steps.value != null ? Math.min(100, (steps.value / stepGoal.value) * 100) : 0,
);
const today = computed(() =>
  new Date().toLocaleDateString([], { month: "short", day: "numeric" }),
);
const stepsToGoal = computed(() =>
  steps.value != null ? Math.max(0, stepGoal.value - steps.value) : null,
);

async function load() {
  loading.value = true;
  const [sum, prof, sober, fast] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.getProfile().catch(() => null),
    api.soberStats().catch(() => null),
    api.fastingCurrent().catch(() => null),
  ]);
  if (sum) {
    sleepScore.value = sum.sleep_score;
    recoveryScore.value = sum.recovery_score;
    steps.value = sum.steps_total;
  }
  const extra = prof?.extra as { steps_goal?: number } | undefined;
  if (extra?.steps_goal != null) stepGoal.value = Math.round(extra.steps_goal);
  if (sober) soberDays.value = sober.current_days;
  if (fast && fast.is_active) {
    fastActive.value = true;
    fastH.value = fast.elapsed_h;
    if (fast.target_hours) fastTarget.value = fast.target_hours;
  }
  loading.value = false;
}
onMounted(load);

function go(path: string) {
  router.push(path);
}
function fmt(n: number | null, d = 0): string {
  return n == null ? "—" : n.toFixed(d);
}
</script>

<template>
  <div class="rings-view">
    <header class="head">
      <h1>Today</h1>
      <span class="date">{{ today }}</span>
    </header>

    <!-- Goal rings -->
    <div class="rings">
      <button class="ring" @click="go('/sleep')" aria-label="Sleep detail">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-track)" stroke-width="9" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-mag)" stroke-width="9"
            stroke-linecap="round" :stroke-dasharray="dash(sleepScore ?? 0)"
            transform="rotate(-90 50 50)" style="filter:drop-shadow(0 0 5px var(--rn-mag))" />
          <text x="50" y="58" text-anchor="middle" font-size="22" fill="var(--rn-mag)">☾</text>
        </svg>
        <div class="lab">SLEEP</div>
        <div class="pct">{{ fmt(sleepScore) }}<small v-if="sleepScore != null">%</small></div>
      </button>
      <button class="ring" @click="go('/steps')" aria-label="Move / steps detail">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-track)" stroke-width="9" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-lime)" stroke-width="9"
            stroke-linecap="round" :stroke-dasharray="dash(movePct)"
            transform="rotate(-90 50 50)" style="filter:drop-shadow(0 0 6px var(--rn-lime))" />
          <text x="50" y="58" text-anchor="middle" font-size="22" fill="var(--rn-lime)">🏃</text>
        </svg>
        <div class="lab">MOVE</div>
        <div class="pct">{{ steps != null ? Math.round(movePct) : "—" }}<small v-if="steps != null">%</small></div>
      </button>
      <button class="ring" @click="go('/heart-rate')" aria-label="Recovery detail">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-track)" stroke-width="9" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--rn-cyan)" stroke-width="9"
            stroke-linecap="round" :stroke-dasharray="dash(recoveryScore ?? 0)"
            transform="rotate(-90 50 50)" style="filter:drop-shadow(0 0 5px var(--rn-cyan))" />
          <text x="50" y="58" text-anchor="middle" font-size="22" fill="var(--rn-cyan)">♥</text>
        </svg>
        <div class="lab">RECOVERY</div>
        <div class="pct">{{ fmt(recoveryScore) }}<small v-if="recoveryScore != null">%</small></div>
      </button>
    </div>

    <!-- Streaks & goals -->
    <div class="list">
      <button class="pill" @click="go('/fasting')">
        <span class="pi cyan">⏱</span><span class="pn">Fasting</span>
        <span class="pv">
          <b>{{ fmt(fastH, 0) }}</b> / {{ fastTarget }}h
          <span v-if="fastH != null && fastH >= fastTarget" class="ok">✓</span>
        </span>
      </button>
      <button class="pill" @click="go('/sober')">
        <span class="pi mag">🔥</span><span class="pn">Sober</span>
        <span class="pv"><b class="mag">{{ soberDays != null ? Math.floor(soberDays) : "—" }}</b> days</span>
      </button>
      <button class="pill" @click="go('/steps')">
        <span class="pi lime">👟</span><span class="pn">Steps</span>
        <span class="pv"><b class="lime">{{ steps != null ? steps.toLocaleString() : "—" }}</b> / {{ stepGoal.toLocaleString() }}</span>
      </button>
      <button class="pill" @click="go('/workout/strength/today')">
        <span class="pi cyan">🏋</span><span class="pn">Workout</span>
        <span class="pv">Today's plan <span class="chev">›</span></span>
      </button>
    </div>

    <button v-if="stepsToGoal != null && stepsToGoal > 0" class="cta" @click="go('/steps')">
      <span class="ct">
        <span class="h3">Almost there!</span>
        <span class="p">{{ stepsToGoal.toLocaleString() }} steps to close your Move ring</span>
      </span>
      <span class="goarrow">→</span>
    </button>
  </div>
</template>

<style scoped>
.rings-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}
.head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 24px; }
.head h1 { font-size: 32px; font-weight: 800; margin: 0; letter-spacing: -0.5px; }
.head .date { color: var(--rn-mut); font-weight: 600; font-size: 15px; }

.rings { display: flex; justify-content: space-between; gap: 6px; margin-bottom: 28px; }
.ring { flex: 1; text-align: center; background: none; border: 0; padding: 0; cursor: pointer; color: inherit;
  transition: transform 0.12s ease; }
.ring:active { transform: scale(0.96); }
.ring svg { width: 100%; max-width: 110px; height: auto; display: block; margin: 0 auto; }
.ring .lab { font-size: 11px; font-weight: 700; letter-spacing: 0.12em; color: var(--rn-mut); margin-top: 8px; }
.ring .pct { font-weight: 800; font-size: 19px; margin-top: 1px; }
.ring .pct small { font-size: 13px; color: var(--rn-mut); font-weight: 700; }

.list { display: flex; flex-direction: column; gap: 12px; }
.pill { display: flex; align-items: center; gap: 14px; background: var(--rn-card); border: 0; border-radius: 22px;
  padding: 15px 18px; cursor: pointer; color: inherit; text-align: left; transition: transform 0.12s ease; }
.pill:active { transform: scale(0.985); }
.pill .pi { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  flex: 0 0 auto; font-size: 18px; }
.pill .pi.cyan { background: rgba(40, 230, 255, 0.14); }
.pill .pi.mag { background: rgba(255, 58, 216, 0.14); }
.pill .pi.lime { background: rgba(93, 255, 59, 0.14); }
.pill .pn { flex: 1; font-weight: 700; font-size: 16px; }
.pill .pv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 14px; color: var(--rn-mut); }
.pill .pv b { color: var(--rn-ink); }
.pv b.mag { color: var(--rn-mag); } .pv b.lime { color: var(--rn-lime); }
.pv .ok { color: var(--rn-lime); } .pv .chev { color: var(--rn-mut); }

.cta { width: 100%; margin-top: 18px; border-radius: 26px; padding: 22px; display: flex; align-items: center; gap: 14px;
  cursor: pointer; color: inherit; text-align: left;
  background: linear-gradient(120deg, rgba(93, 255, 59, 0.22), rgba(93, 255, 59, 0.05));
  border: 1px solid rgba(93, 255, 59, 0.30); transition: transform 0.12s ease; }
.cta:active { transform: scale(0.99); }
.cta .ct { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.cta .h3 { font-size: 21px; font-weight: 800; }
.cta .p { color: #c7d8c0; font-size: 14px; }
.cta .goarrow { width: 54px; height: 54px; border-radius: 50%; background: var(--rn-lime); color: #063b00;
  display: flex; align-items: center; justify-content: center; box-shadow: 0 0 26px rgba(93, 255, 59, 0.55);
  font-size: 24px; flex: 0 0 auto; }
</style>
