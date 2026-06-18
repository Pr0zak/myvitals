<script setup lang="ts">
/**
 * Body — the consolidated vitals & recovery overview for the "Vitality Neon"
 * redesign. A 2-column grid of glanceable metric cards (heart rate, HRV, sleep,
 * steps, blood pressure, weight, skin temp) plus a header recovery pill. Each
 * card carries a tiny inline SVG element from the mockup and drills into the
 * existing detail view on tap.
 *
 * Styling is scoped to `.body-view` so the redesign can land alongside the
 * current app without restyling everything else yet.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";

const router = useRouter();
const loading = ref(true);
const sum = ref<TodaySummary | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  sum.value = await api.todaySummary().catch(() => null);
  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}

// Recovery ring (r=15 → circumference ≈ 94.2)
const RC = 2 * Math.PI * 15;
const recovery = computed<number | null>(() => sum.value?.recovery_score ?? null);
const recoveryOffset = computed<number>(() => {
  const pct = Math.max(0, Math.min(100, recovery.value ?? 0));
  return RC * (1 - pct / 100);
});

// Sleep ring (same geometry as the recovery ring)
const sleepScore = computed<number | null>(() => sum.value?.sleep_score ?? null);
const sleepOffset = computed<number>(() => {
  const pct = Math.max(0, Math.min(100, sleepScore.value ?? 0));
  return RC * (1 - pct / 100);
});

const restingHr = computed<number | null>(() => sum.value?.resting_hr ?? null);
const hrv = computed<number | null>(() => sum.value?.hrv_avg ?? null);

const sleepDurationS = computed<number | null>(() => sum.value?.sleep_duration_s ?? null);
const sleepHours = computed<number | null>(() =>
  sleepDurationS.value != null ? Math.floor(sleepDurationS.value / 3600) : null,
);
const sleepMinutes = computed<number | null>(() =>
  sleepDurationS.value != null
    ? Math.floor((sleepDurationS.value % 3600) / 60)
    : null,
);

const steps = computed<number | null>(() => sum.value?.steps_total ?? null);
const STEP_GOAL = 10000;
const stepsPct = computed<number | null>(() =>
  steps.value != null ? Math.round((steps.value / STEP_GOAL) * 100) : null,
);

const bpSys = computed<number | null>(() => sum.value?.bp_systolic_avg ?? null);
const bpDia = computed<number | null>(() => sum.value?.bp_diastolic_avg ?? null);
const bpLabel = computed<string>(() => {
  const s = bpSys.value;
  const d = bpDia.value;
  if (s == null || d == null) return "—";
  if (s < 120 && d < 80) return "Optimal";
  if (s < 130 && d < 80) return "Normal";
  if (s < 140 || d < 90) return "Elevated";
  return "High";
});

const weightLb = computed<number | null>(() =>
  sum.value?.weight_kg != null ? sum.value.weight_kg * 2.20462 : null,
);

const skinTemp = computed<number | null>(() => sum.value?.skin_temp_delta_avg ?? null);

function fmt(n: number | null, d = 0): string {
  return n == null ? "—" : n.toFixed(d);
}
function signed(n: number | null, d = 1): string {
  if (n == null) return "—";
  const v = n.toFixed(d);
  return n > 0 ? `+${v}` : v;
}
</script>

<template>
  <div class="body-view">
    <header class="head">
      <h1>Body</h1>
      <button class="recchip" @click="go('/heart-rate')" aria-label="Recovery detail">
        <svg class="rr" viewBox="0 0 36 36">
          <circle cx="18" cy="18" r="15" fill="none" stroke="var(--rn-track)" stroke-width="4" />
          <circle cx="18" cy="18" r="15" fill="none" stroke="var(--rn-cyan)" stroke-width="4"
            stroke-linecap="round" :stroke-dasharray="RC.toFixed(1)"
            :stroke-dashoffset="recoveryOffset.toFixed(1)" transform="rotate(-90 18 18)" />
        </svg>
        <div class="rmeta">
          <div class="rt">Recovery</div>
          <div class="rv">{{ fmt(recovery) }}</div>
        </div>
      </button>
    </header>

    <div class="cap">Vitals &amp; recovery · today</div>

    <div class="grid">
      <!-- Heart rate -->
      <button class="mc" @click="go('/heart-rate')" aria-label="Heart rate detail">
        <div class="top">
          <span class="lab">Heart rate</span>
          <svg class="viz glowcyan" viewBox="0 0 40 24" fill="none" stroke="var(--rn-cyan)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 14 L7 14 L10 6 L14 20 L18 11 L22 14 L26 14 L29 9 L33 14 L39 14" />
          </svg>
        </div>
        <div class="big">{{ fmt(restingHr) }}<span class="u">bpm</span></div>
        <div class="sub"><span class="ctx">resting</span></div>
      </button>

      <!-- HRV -->
      <button class="mc" @click="go('/hrv')" aria-label="HRV detail">
        <div class="top">
          <span class="lab">HRV</span>
          <svg class="viz glowcyan" viewBox="0 0 40 24" fill="none" stroke="var(--rn-cyan)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 18 L7 15 L13 17 L19 9 L25 12 L31 5 L39 7" />
          </svg>
        </div>
        <div class="big">{{ fmt(hrv) }}<span class="u">ms</span></div>
        <div class="sub"><span class="ctx">overnight avg</span></div>
      </button>

      <!-- Sleep -->
      <button class="mc" @click="go('/sleep')" aria-label="Sleep detail">
        <div class="top">
          <span class="lab">Sleep</span>
          <svg class="ring glowmag" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--rn-track)" stroke-width="4" />
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--rn-mag)" stroke-width="4"
              stroke-linecap="round" :stroke-dasharray="RC.toFixed(1)"
              :stroke-dashoffset="sleepOffset.toFixed(1)" transform="rotate(-90 18 18)" />
          </svg>
        </div>
        <div class="big">
          <template v-if="sleepHours != null">
            {{ sleepHours }}<span class="u">h</span>{{ sleepMinutes ?? 0 }}<span class="u">m</span>
          </template>
          <template v-else>—</template>
        </div>
        <div class="sub">
          <span class="mag" v-if="sleepScore != null">score {{ fmt(sleepScore) }}</span>
          <span class="ctx" v-else>no night</span>
        </div>
      </button>

      <!-- Steps -->
      <button class="mc" @click="go('/steps')" aria-label="Steps detail">
        <div class="top">
          <span class="lab">Steps</span>
          <svg class="viz glowlime" viewBox="0 0 40 24" fill="none" stroke="var(--rn-lime)"
            stroke-width="2.4" stroke-linecap="round">
            <line x1="3" y1="22" x2="3" y2="15" />
            <line x1="9" y1="22" x2="9" y2="11" />
            <line x1="15" y1="22" x2="15" y2="17" />
            <line x1="21" y1="22" x2="21" y2="8" />
            <line x1="27" y1="22" x2="27" y2="13" />
            <line x1="33" y1="22" x2="33" y2="6" />
            <line x1="39" y1="22" x2="39" y2="10" />
          </svg>
        </div>
        <div class="big">{{ steps != null ? steps.toLocaleString() : "—" }}</div>
        <div class="sub">
          <span class="good" v-if="stepsPct != null">{{ stepsPct }}%</span>
          <span class="ctx">of 10k</span>
        </div>
      </button>

      <!-- Blood pressure (full width) -->
      <button class="mc span2" @click="go('/blood-pressure')" aria-label="Blood pressure detail">
        <div class="left">
          <span class="lab">Blood pressure</span>
          <div class="big">
            {{ fmt(bpSys) }}<span class="u">/</span>{{ fmt(bpDia) }}<span class="u">mmHg</span>
          </div>
          <div class="sub"><span class="cyan">{{ bpLabel }}</span></div>
        </div>
        <svg class="bpviz glowcyan" viewBox="0 0 88 42" fill="none" stroke="var(--rn-cyan)"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2 30 L12 28 L22 31 L32 22 L42 26 L52 18 L62 23 L72 16 L86 20" opacity=".95" />
          <path d="M2 38 L12 37 L22 38 L32 33 L42 36 L52 31 L62 34 L72 29 L86 32"
            stroke="var(--rn-cyan)" opacity=".4" />
        </svg>
      </button>

      <!-- Weight -->
      <button class="mc" @click="go('/weight')" aria-label="Weight detail">
        <div class="top">
          <span class="lab">Weight</span>
          <svg class="viz glowamber" viewBox="0 0 40 24" fill="none" stroke="var(--rn-amber)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 8 L8 9 L15 11 L22 12 L29 15 L39 17" />
          </svg>
        </div>
        <div class="big">{{ fmt(weightLb, 1) }}<span class="u">lb</span></div>
        <div class="sub"><span class="ctx">latest</span></div>
      </button>

      <!-- Skin temp -->
      <button class="mc" @click="go('/skin-temp')" aria-label="Skin temperature detail">
        <div class="top">
          <span class="lab">Skin temp</span>
          <svg class="viz" viewBox="0 0 40 24" fill="none" stroke="var(--rn-mut)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 13 L8 12 L15 14 L22 12 L29 11 L39 12" />
            <line x1="1" y1="18" x2="39" y2="18" stroke="var(--rn-track)" stroke-dasharray="2 3" />
          </svg>
        </div>
        <div class="big">{{ signed(skinTemp) }}<span class="u">°C</span></div>
        <div class="sub"><span class="muted">vs baseline</span></div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.body-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-amber: #ffb52e;
  --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}

.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.head h1 { font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px; }

.recchip { display: flex; align-items: center; gap: 9px; cursor: pointer; color: inherit;
  background: rgba(40, 230, 255, 0.10); border: 1px solid rgba(40, 230, 255, 0.32);
  border-radius: 999px; padding: 6px 13px 6px 8px; transition: transform 0.12s ease; }
.recchip:active { transform: scale(0.97); }
.recchip .rr { width: 26px; height: 26px; flex: 0 0 auto; filter: drop-shadow(0 0 5px rgba(40, 230, 255, 0.55)); }
.recchip .rmeta { text-align: left; }
.recchip .rt { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.10em; color: var(--rn-cyan); text-transform: uppercase; line-height: 1; }
.recchip .rv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 20px; font-weight: 700;
  color: var(--rn-ink); line-height: 1; margin-top: 3px; }

.cap { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.12em; color: var(--rn-mut); text-transform: uppercase; margin: 6px 0 11px; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

.mc { position: relative; background: var(--rn-card); border: 1px solid #21243450; border-radius: 18px;
  padding: 13px 14px 12px; overflow: hidden; display: flex; flex-direction: column; min-height: 108px;
  cursor: pointer; color: inherit; text-align: left; transition: transform 0.12s ease; }
.mc:active { transform: scale(0.97); }
.mc::after { content: ""; position: absolute; inset: 0; border-radius: 18px; pointer-events: none;
  box-shadow: inset 0 1px 0 #ffffff08; }
.mc .top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; }
.mc .lab { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 10px; font-weight: 700;
  letter-spacing: 0.11em; color: var(--rn-mut); text-transform: uppercase; }
.mc .viz { width: 40px; height: 24px; flex: 0 0 auto; }
.mc .ring { width: 30px; height: 30px; flex: 0 0 auto; }
.mc .big { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 25px;
  line-height: 1; letter-spacing: -0.5px; color: var(--rn-ink); display: flex; align-items: baseline; gap: 4px; }
.mc .big .u { font-size: 12px; font-weight: 700; color: var(--rn-mut); letter-spacing: 0; }
.mc .sub { margin-top: 7px; display: flex; align-items: center; gap: 5px; font-size: 12px;
  font-weight: 700; font-family: 'Space Grotesk', 'Geist Mono', monospace; }
.mc .sub .ctx { color: var(--rn-mut); font-weight: 600; font-family: 'Plus Jakarta Sans', system-ui; font-size: 11.5px; }

.good { color: var(--rn-lime); }
.bad { color: var(--rn-amber); }
.muted { color: var(--rn-mut); }
.mag { color: var(--rn-mag); }
.lime { color: var(--rn-lime); }
.cyan { color: var(--rn-cyan); }
.amber { color: var(--rn-amber); }

.span2 { grid-column: 1 / -1; }
.mc.span2 { flex-direction: row; align-items: center; justify-content: space-between;
  min-height: auto; padding: 14px 16px; }
.mc.span2 .left { display: flex; flex-direction: column; gap: 8px; }
.mc.span2 .big { font-size: 27px; }
.mc.span2 .bpviz { width: 88px; height: 42px; flex: 0 0 auto; opacity: 0.92; }

.glowcyan { filter: drop-shadow(0 0 4px rgba(40, 230, 255, 0.5)); }
.glowmag { filter: drop-shadow(0 0 4px rgba(255, 58, 216, 0.5)); }
.glowlime { filter: drop-shadow(0 0 4px rgba(93, 255, 59, 0.5)); }
.glowamber { filter: drop-shadow(0 0 4px rgba(255, 181, 46, 0.5)); }
</style>
