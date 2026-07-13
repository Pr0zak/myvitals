<script setup lang="ts">
/**
 * BodyRefined — the "Neon Refined" (A1) Body tab.
 *
 * Ported from the locked A1 body mockup: a "This week" list of tappable vitals
 * cards (Weight + sparkline, Body fat, Blood pressure, Skin-temp Δ, Resting HR,
 * HRV), disciplined cyan-lead palette. Rendered by Body.vue when the "Neon
 * Refined" theme is active (see theme.ts `isRefined`).
 *
 * Data comes from the same backend endpoints the rest of the app uses —
 * `api.todaySummary()` for the current reads plus `api.weight({since:30d})` for
 * the weight sparkline. Nothing is computed client-side beyond formatting.
 * Scoped to `.refined-body`; colours ride the neon CSS vars
 * (--accent/--good/--warn/--violet) live under data-theme="neon".
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { TodaySummary } from "@/api/types";

const router = useRouter();
const loading = ref(true);
const sum = ref<TodaySummary | null>(null);
const weightPts = ref<{ time: string; weight_kg: number | null }[]>([]);

async function load(): Promise<void> {
  loading.value = true;
  const since = new Date(Date.now() - 30 * 864e5);
  const [s, w] = await Promise.all([
    api.todaySummary().catch(() => null),
    api.weight({ since }).catch(() => null),
  ]);
  sum.value = s;
  weightPts.value = w?.points ?? [];
  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}

// ---- formatting ----
function fmt(n: number | null, d = 0): string {
  return n == null ? "—" : n.toFixed(d);
}
function signed(n: number | null, d = 1): string {
  if (n == null) return "—";
  return (n > 0 ? "+" : "") + n.toFixed(d);
}

const today = computed(() =>
  new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }),
);

const weightLb = computed<number | null>(() =>
  sum.value?.weight_kg != null ? sum.value.weight_kg * 2.2046226 : null,
);
const bodyFat = computed<number | null>(() => sum.value?.body_fat_pct ?? null);
const bpSys = computed<number | null>(() => sum.value?.bp_systolic_avg ?? null);
const bpDia = computed<number | null>(() => sum.value?.bp_diastolic_avg ?? null);
const skinTemp = computed<number | null>(() => sum.value?.skin_temp_delta_avg ?? null);
const restingHr = computed<number | null>(() => sum.value?.resting_hr ?? null);
const hrv = computed<number | null>(() => sum.value?.hrv_avg ?? null);

const bp = computed<{ label: string; cls: string }>(() => {
  const s = bpSys.value, d = bpDia.value;
  if (s == null || d == null) return { label: "—", cls: "muted" };
  if (s < 120 && d < 80) return { label: "Normal", cls: "good" };
  if (s < 130 && d < 80) return { label: "Normal", cls: "good" };
  if (s < 140 || d < 90) return { label: "Elevated", cls: "warn" };
  return { label: "High", cls: "bad" };
});

// ---- weight sparkline (inline SVG, 30d) ----
const spark = computed<string | null>(() => {
  const vals = weightPts.value
    .map((p) => p.weight_kg)
    .filter((v): v is number => v != null);
  if (vals.length < 2) return null;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const w = 100, h = 28, pad = 2;
  const step = (w - pad * 2) / (vals.length - 1);
  return vals
    .map((v, i) => {
      const x = pad + i * step;
      const y = pad + (1 - (v - min) / span) * (h - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
});
</script>

<template>
  <div class="refined-body">
    <header class="topbar">
      <div class="ttl">
        <h1>Body</h1>
        <div class="dt">{{ today }}</div>
      </div>
      <button class="iconbtn" @click="go('/weight')" aria-label="Log body metrics">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
        </svg>
      </button>
    </header>

    <div class="cap">This week</div>

    <div class="list">
      <!-- Weight -->
      <button class="vc" @click="go('/weight')" aria-label="Weight detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">⚖</span>
        <span class="meta">
          <span class="lab">Weight</span>
          <span class="val num">{{ fmt(weightLb, 1) }}<u v-if="weightLb != null">lb</u></span>
          <span class="ctx">7-day average</span>
        </span>
        <svg v-if="spark" class="spark glowcyan" viewBox="0 0 100 28" preserveAspectRatio="none"
          fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path :d="spark" />
        </svg>
        <span v-else class="chev">›</span>
      </button>

      <!-- Body fat -->
      <button class="vc" @click="go('/weight')" aria-label="Body fat detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">◐</span>
        <span class="meta">
          <span class="lab">Body fat</span>
          <span class="val num">{{ fmt(bodyFat, 1) }}<u v-if="bodyFat != null">%</u></span>
          <span class="ctx">Bioimpedance estimate</span>
        </span>
        <span class="chev">›</span>
      </button>

      <!-- Blood pressure -->
      <button class="vc" @click="go('/blood-pressure')" aria-label="Blood pressure detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">♡</span>
        <span class="meta">
          <span class="lab">Blood pressure
            <span class="pill" :class="bp.cls">{{ bp.label }}</span>
          </span>
          <span class="val num">{{ fmt(bpSys) }}<u>/</u>{{ fmt(bpDia) }}<u>mmHg</u></span>
          <span class="ctx">Measured this morning</span>
        </span>
        <span class="chev">›</span>
      </button>

      <!-- Skin-temp Δ -->
      <button class="vc" @click="go('/skin-temp')" aria-label="Skin temperature detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">🌡</span>
        <span class="meta">
          <span class="lab">Skin-temp Δ</span>
          <span class="val num">{{ signed(skinTemp) }}<u v-if="skinTemp != null">°C</u></span>
          <span class="ctx">vs baseline</span>
        </span>
        <span class="chev">›</span>
      </button>

      <!-- Resting HR -->
      <button class="vc" @click="go('/heart-rate')" aria-label="Resting heart rate detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">♥</span>
        <span class="meta">
          <span class="lab">Resting HR</span>
          <span class="val num">{{ fmt(restingHr) }}<u v-if="restingHr != null">bpm</u></span>
          <span class="ctx">Lower is better</span>
        </span>
        <span class="chev">›</span>
      </button>

      <!-- HRV -->
      <button class="vc" @click="go('/hrv')" aria-label="HRV detail">
        <span class="ico" style="background:rgba(40,230,255,.12);color:var(--accent)">∿</span>
        <span class="meta">
          <span class="lab">HRV</span>
          <span class="val num">{{ fmt(hrv) }}<u v-if="hrv != null">ms</u></span>
          <span class="ctx">Overnight average</span>
        </span>
        <span class="chev">›</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.refined-body {
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
  --num: "Space Grotesk", "Geist Mono", monospace;

  margin: -1.25rem -1.5rem;
  padding: 22px 16px 108px;
  min-height: 100vh;
  color: var(--ink);
  font-family: "Plus Jakarta Sans", "Geist", system-ui, sans-serif;
  background: radial-gradient(120% 45% at 50% -6%, #161a2c, #0f1118 60%);
}
.refined-body button { font-family: inherit; color: inherit; cursor: pointer; }
.num { font-family: var(--num); font-variant-numeric: tabular-nums; }

.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.ttl h1 { font-size: 27px; font-weight: 800; margin: 0; letter-spacing: -0.02em; }
.ttl .dt { font-size: 12px; color: var(--muted-c); margin-top: 2px; }
.iconbtn {
  margin-left: auto; width: 38px; height: 38px; border-radius: 12px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: var(--glass); border: 1px solid var(--hair); color: var(--muted-c);
}
.iconbtn svg { width: 18px; height: 18px; }

.cap {
  font-family: var(--num); font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
  color: var(--muted-c); text-transform: uppercase; margin: 4px 2px 11px;
}

.list { display: flex; flex-direction: column; gap: 10px; }
.vc {
  display: flex; align-items: center; gap: 13px; width: 100%; text-align: left;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.015));
  border: 1px solid var(--hair); border-radius: 18px; padding: 14px 15px;
  transition: transform 0.12s ease;
}
.vc:active { transform: scale(0.985); }
.vc .ico {
  width: 42px; height: 42px; border-radius: 12px; flex: 0 0 auto; font-size: 19px;
  display: flex; align-items: center; justify-content: center;
}
.vc .meta { flex: 1; min-width: 0; }
.vc .lab {
  display: block; font-size: 10px; font-weight: 700; letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--muted-c);
}
.vc .val { display: block; font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin-top: 3px; }
.vc .val u { font-size: 11px; color: var(--dim); text-decoration: none; font-weight: 500; margin-left: 2px; }
.vc .ctx { display: block; font-size: 11.5px; color: var(--dim); margin-top: 3px; }

.pill {
  display: inline-flex; align-items: center; font-size: 8.5px; font-weight: 700;
  letter-spacing: 0.06em; padding: 2px 7px; border-radius: 20px; margin-left: 5px;
  vertical-align: middle;
}
.pill.good { color: var(--good); background: rgba(93, 255, 59, 0.13); }
.pill.warn { color: var(--warn); background: rgba(255, 181, 46, 0.14); }
.pill.bad { color: var(--bad); background: rgba(255, 93, 122, 0.14); }
.pill.muted { color: var(--muted-c); background: var(--glass); }

.spark { width: 76px; height: 28px; flex: 0 0 auto; }
.glowcyan { filter: drop-shadow(0 0 4px rgba(40, 230, 255, 0.5)); }
.chev { color: var(--dim); font-size: 20px; flex: 0 0 auto; }
</style>
