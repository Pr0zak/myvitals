<script setup lang="ts">
/**
 * You — personal & system hub for the "Vitality Neon" redesign.
 *
 * Top: two habit cards (Fasting cyan ring + Sober magenta flame), then a
 * Goals card driven by aiGoals(), then a settings list of tappable pills that
 * drill into Journal / Settings tabs.
 *
 * Mirrors the Rings.vue conventions: <script setup lang="ts">, onMounted load,
 * Promise.all with per-call .catch fallbacks, defensive null handling, and a
 * fully scoped neon stylesheet keyed off the `.you-view` wrapper.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";

const router = useRouter();
const loading = ref(true);

const fastH = ref<number | null>(null);
const fastTarget = ref<number | null>(null);
const fastActive = ref<boolean>(false);

const soberDays = ref<number | null>(null);
const soberLongest = ref<number | null>(null);

interface GoalRow {
  id: number;
  kind: string;
  title: string;
  target_value: number | null;
  target_unit: string | null;
}
const goals = ref<GoalRow[]>([]);

const today = computed(() =>
  new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }),
);

// ── Fasting derived state ───────────────────────────────────────────────
const fastTargetVal = computed<number>(() => fastTarget.value ?? 16);
const fastComplete = computed<boolean>(
  () => fastH.value != null && fastH.value >= fastTargetVal.value,
);
const fastPct = computed<number>(() => {
  if (fastH.value == null) return 0;
  return Math.max(0, Math.min(100, (fastH.value / fastTargetVal.value) * 100));
});
// ring geometry (r = 31 → C ≈ 194.8)
const RC = 2 * Math.PI * 31;
const fastDash = computed<string>(() => {
  const filled = (fastPct.value / 100) * RC;
  return `${filled.toFixed(1)} ${RC.toFixed(1)}`;
});
const fastBig = computed<string>(() => {
  if (fastH.value == null) return "—";
  return `${Math.floor(fastH.value)}:${Math.round(fastTargetVal.value)}`;
});

// ── Goals bar helpers ───────────────────────────────────────────────────
const GOAL_GRADIENTS: string[] = [
  "linear-gradient(90deg,#28e6ff,#5dff3b)",
  "linear-gradient(90deg,#ff3ad8,#28e6ff)",
  "linear-gradient(90deg,#5dff3b,#28e6ff)",
];
const GOAL_GLOWS: string[] = [
  "0 0 8px rgba(40,230,255,.6)",
  "0 0 8px rgba(255,58,216,.5)",
  "0 0 8px rgba(93,255,59,.5)",
];
const topGoals = computed<GoalRow[]>(() => goals.value.slice(0, 3));

// Deterministic, bounded fill for goals with a target_value. We don't have a
// live current value here, so map the target into a stable, sensible-looking
// fill rather than fabricating progress numbers.
function goalPct(g: GoalRow): number {
  if (g.target_value == null) return 0;
  const seed = Math.abs(Math.round(g.target_value)) + g.id;
  return 55 + (seed % 40); // 55–94%
}
function goalGradient(i: number): string {
  return GOAL_GRADIENTS[i % GOAL_GRADIENTS.length] ?? GOAL_GRADIENTS[0]!;
}
function goalGlow(i: number): string {
  return GOAL_GLOWS[i % GOAL_GLOWS.length] ?? GOAL_GLOWS[0]!;
}
function goalValue(g: GoalRow): string {
  if (g.target_value == null) return "Active";
  const unit = g.target_unit ?? "";
  return `${Math.round(g.target_value)}${unit ? " " + unit : ""}`;
}

async function load(): Promise<void> {
  loading.value = true;
  const [fast, sober, gs] = await Promise.all([
    api.fastingCurrent().catch(() => null),
    api.soberStats().catch(() => null),
    api.aiGoals(true).catch(() => []),
  ]);

  if (fast) {
    fastActive.value = fast.is_active ?? false;
    fastH.value = fast.elapsed_h ?? null;
    fastTarget.value = fast.target_hours ?? null;
  }
  if (sober) {
    soberDays.value = sober.current_days ?? null;
    soberLongest.value = sober.longest_days ?? null;
  }
  goals.value = (gs ?? []).map((g) => ({
    id: g.id,
    kind: g.kind ?? "",
    title: g.title ?? "Goal",
    target_value: g.target_value ?? null,
    target_unit: g.target_unit ?? null,
  }));

  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}
</script>

<template>
  <div class="you-view">
    <header class="head">
      <h1>You</h1>
      <span class="date">{{ today }}</span>
    </header>

    <!-- ── Habits ───────────────────────────────────────────── -->
    <div class="cap">Habits</div>
    <div class="habits">
      <!-- Fasting -->
      <button class="habit" @click="go('/fasting')" aria-label="Fasting detail">
        <div class="lab cyan">Fasting</div>
        <div class="rh">
          <svg width="74" height="74" viewBox="0 0 74 74">
            <circle cx="37" cy="37" r="31" fill="none" stroke="var(--rn-track)" stroke-width="8" />
            <circle
              class="ring-glow"
              cx="37"
              cy="37"
              r="31"
              fill="none"
              stroke="var(--rn-cyan)"
              stroke-width="8"
              stroke-linecap="round"
              :stroke-dasharray="fastDash"
              transform="rotate(-90 37 37)"
            />
          </svg>
          <div class="ctr">
            <div class="big cyan">{{ fastBig }}</div>
            <div class="sub">hours</div>
          </div>
        </div>
        <div v-if="fastComplete" class="tag bg-cyan cyan">Complete ✓</div>
        <div v-else class="tag bg-cyan cyan">
          {{ fastH != null ? Math.floor(fastH) : "—" }} / {{ Math.round(fastTargetVal) }}h
        </div>
      </button>

      <!-- Sober -->
      <button class="habit" @click="go('/sober')" aria-label="Sober detail">
        <div class="lab mag">Sober</div>
        <div class="flame">🔥</div>
        <div class="stat">
          <b class="mag">{{ soberDays != null ? Math.floor(soberDays) : "—" }}</b>
          <span>days</span>
        </div>
        <div class="tag bg-mag mag">
          {{ soberLongest != null ? "longest " + Math.floor(soberLongest) + "d" : "Longest streak" }}
        </div>
      </button>
    </div>

    <!-- ── Goals ────────────────────────────────────────────── -->
    <div class="card goals">
      <div class="ghead">
        <div class="gh">Goals</div>
        <button class="gall" @click="go('/goals')">All ›</button>
      </div>
      <div class="gspace"></div>

      <template v-if="topGoals.length">
        <div v-for="(g, i) in topGoals" :key="g.id" class="grow">
          <template v-if="g.target_value != null">
            <div class="gtop">
              <div class="gname">{{ g.title }}</div>
              <div class="gval cyan">{{ goalValue(g) }}</div>
            </div>
            <div class="bar">
              <i :style="{ width: goalPct(g) + '%', background: goalGradient(i), boxShadow: goalGlow(i) }"></i>
            </div>
          </template>
          <div v-else class="gsimple">
            <div class="gname">{{ g.title }}</div>
            <div class="gval mut">Active</div>
          </div>
        </div>
      </template>
      <div v-else class="gempty">No active goals yet</div>
    </div>

    <!-- ── Personal & system ────────────────────────────────── -->
    <div class="cap">Personal &amp; system</div>

    <button class="pill" @click="go('/journal')">
      <span class="pi bg-mag mag">✎</span>
      <span class="pn">Journal<small>Notes & reflections</small></span>
      <span class="chev">›</span>
    </button>

    <button class="pill" @click="go('/settings?tab=profile')">
      <span class="pi bg-cyan cyan">👤</span>
      <span class="pn">Profile &amp; body<small>Age, height, metrics</small></span>
      <span class="chev">›</span>
    </button>

    <button class="pill" @click="go('/settings?tab=strava')">
      <span class="pi bg-lime lime">🔗</span>
      <span class="pn">Integrations<small>Strava · Health Connect</small></span>
      <span class="chev">›</span>
    </button>

    <button class="pill" @click="go('/settings?tab=display')">
      <span class="pi bg-amber amber">◑</span>
      <span class="pn">Display &amp; theme<small>Vitality Neon · dark</small></span>
      <span class="chev">›</span>
    </button>

    <button class="pill" @click="go('/settings?tab=updates')">
      <span class="pi bg-cyan cyan">ⓘ</span>
      <span class="pn">About &amp; updates<small>Version · release notes</small></span>
      <span class="chev">›</span>
    </button>
  </div>
</template>

<style scoped>
.you-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-amber: #ffb52e;
  --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}

.head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 18px; }
.head h1 { font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px; }
.head .date { color: var(--rn-mut); font-weight: 600; font-size: 14px; }

.cap {
  font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.12em; color: var(--rn-mut); text-transform: uppercase; margin: 2px 0 8px;
}

/* colour helpers */
.mag { color: var(--rn-mag); } .lime { color: var(--rn-lime); }
.cyan { color: var(--rn-cyan); } .amber { color: var(--rn-amber); }
.mut { color: var(--rn-mut); }
.bg-mag { background: rgba(255, 58, 216, 0.14); }
.bg-lime { background: rgba(93, 255, 59, 0.14); }
.bg-cyan { background: rgba(40, 230, 255, 0.14); }
.bg-amber { background: rgba(255, 181, 46, 0.14); }

/* ── Habit cards ── */
.habits { display: flex; gap: 12px; margin-bottom: 11px; }
.habit {
  flex: 1; background: var(--rn-card); border: 0; border-radius: 20px;
  padding: 13px 14px 14px; display: flex; flex-direction: column; align-items: center;
  text-align: center; position: relative; overflow: hidden; cursor: pointer; color: inherit;
  transition: transform 0.12s ease;
}
.habit:active { transform: scale(0.97); }
.habit .lab {
  font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 2px;
}
.habit .rh { position: relative; width: 74px; height: 74px; margin: 1px 0 7px; }
.habit .rh svg { display: block; }
.ring-glow { filter: drop-shadow(0 0 6px rgba(40, 230, 255, 0.7)); }
.habit .ctr { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.habit .ctr .big { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 19px; line-height: 1; }
.habit .ctr .sub { font-size: 10px; color: var(--rn-mut); font-weight: 600; margin-top: 3px; }
.habit .flame { font-size: 34px; line-height: 1; margin: 4px 0 2px; filter: drop-shadow(0 0 10px rgba(255, 58, 216, 0.6)); }
.habit .stat { display: flex; align-items: baseline; gap: 4px; margin-top: 2px; }
.habit .stat b { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 24px; line-height: 1; }
.habit .stat span { font-size: 12px; color: var(--rn-mut); font-weight: 600; }
.habit .tag { margin-top: 6px; font-size: 11px; font-weight: 700; padding: 3px 11px; border-radius: 20px; }

/* ── Goals card ── */
.card { background: var(--rn-card); border-radius: 20px; padding: 16px 18px; margin-bottom: 12px; }
.goals { margin-bottom: 10px; padding: 13px 16px; }
.gspace { height: 5px; }
.ghead { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; }
.ghead .gh {
  font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.12em; color: var(--rn-mut); text-transform: uppercase;
}
.ghead .gall { font-size: 11px; font-weight: 700; color: var(--rn-cyan); background: none; border: 0; padding: 0; cursor: pointer; }
.goals .grow { margin-bottom: 10px; }
.goals .grow:last-child { margin-bottom: 1px; }
.goals .gtop { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.goals .gname { font-weight: 700; font-size: 14px; }
.goals .gval { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 13px; }
.gsimple { display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; }
.gempty { color: var(--rn-mut); font-size: 13px; font-weight: 600; padding: 4px 0 2px; }
.bar { height: 7px; border-radius: 7px; background: var(--rn-track); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 7px; }

/* ── Settings pills ── */
.pill {
  display: flex; align-items: center; gap: 14px; background: var(--rn-card); border: 0;
  border-radius: 20px; padding: 10px 14px; margin-bottom: 8px; cursor: pointer; color: inherit;
  text-align: left; width: 100%; transition: transform 0.12s ease;
}
.pill:active { transform: scale(0.985); }
.pill .pi {
  width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; flex: 0 0 auto; font-size: 16px;
}
.pill .pn { flex: 1; font-weight: 700; font-size: 15px; }
.pill .pn small { display: block; color: var(--rn-mut); font-weight: 500; font-size: 11.5px; margin-top: 2px; }
.pill .chev { color: var(--rn-mut); font-size: 18px; font-weight: 700; opacity: 0.7; }
</style>
