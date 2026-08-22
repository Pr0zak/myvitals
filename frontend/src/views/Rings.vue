<script setup lang="ts">
import TodayHero from "@/components/TodayHero.vue";
import HealthStatus from "@/components/HealthStatus.vue";
import FocusAreas from "@/components/FocusAreas.vue";
import KeyMetrics from "@/components/KeyMetrics.vue";
import NarrativeCards from "@/components/NarrativeCards.vue";
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
import { isConfigured } from "@/config";

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
const today = computed(() =>
  new Date().toLocaleDateString([], { month: "short", day: "numeric" }),
);

/** Why the page is empty, when it is. Null means "nothing is wrong".
 *
 *  Every call below swallows its own error so one dead subsystem cannot
 *  blank the page — which is right, but it also meant a TOTAL failure
 *  (no token, backend unreachable) rendered as a grid of dashes with no
 *  explanation at all. A first-run user saw a broken-looking dashboard
 *  and nothing telling them what to do. */
const emptyReason = ref<"unconfigured" | "unreachable" | null>(null);

async function load() {
  loading.value = true;
  emptyReason.value = null;

  if (!isConfigured()) {
    emptyReason.value = "unconfigured";
    loading.value = false;
    return;
  }

  const [sum, prof, sober, fast] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.getProfile().catch(() => null),
    api.soberStats().catch(() => null),
    api.fastingCurrent().catch(() => null),
  ]);
  // All four failing is a connection problem, not four coincidences.
  if (!sum && !prof && !sober && !fast) emptyReason.value = "unreachable";
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
  <div v-if="emptyReason" class="setup">
    <template v-if="emptyReason === 'unconfigured'">
      <h2>Nothing to show yet</h2>
      <p>Paste your <code>QUERY_TOKEN</code> so the dashboard can read your data.</p>
      <button class="primary" @click="router.push('/settings?tab=access')">
        Open Settings
      </button>
    </template>
    <template v-else>
      <h2>Couldn't reach the backend</h2>
      <p>Every request failed. The server may be restarting, or the token may be wrong.</p>
      <button class="primary" @click="load()">Try again</button>
    </template>
  </div>
  <div v-else class="rings-view">
    <header class="head">
      <h1>Today</h1>
      <span class="date">{{ today }}</span>
    </header>

    <TodayHero />
    <HealthStatus />

    <!-- Goal rings -->

    <!-- Streaks & goals -->
    <KeyMetrics />

    <NarrativeCards />

    <FocusAreas />

  </div>
</template>

<style scoped>
.rings-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 104px;
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

.setup { padding: 2.5rem 1rem; text-align: center; }
.setup h2 { margin: 0 0 0.4rem; font-size: 1.1rem; color: var(--text); }
.setup p { color: var(--muted); font-size: 0.9rem; margin: 0 0 1rem; }
.setup code { background: var(--surface-2); padding: 0.1rem 0.3rem; border-radius: 4px; }
</style>
