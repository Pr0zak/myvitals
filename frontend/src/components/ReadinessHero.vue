<script setup lang="ts">
/**
 * Readiness hero — web twin of `ui/neon/ReadinessHero.kt`.
 *
 * Everything shown is SERVER-DERIVED: score, band, z-scores, sub-scores and
 * weights all arrive from /summary/readiness. Nothing is recomputed here, so
 * the phone and the dashboard cannot disagree about the same day.
 *
 * Deliberately no narration — a number, a word, a sparkline and the drivers.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { ReadinessDetail, ReadinessDriver } from "@/api/types";

const router = useRouter();
const detail = ref<ReadinessDetail | null>(null);
const showFormula = ref(false);

/** Sparkline box, in CSS px — the SVG viewBox matches so scaling stays uniform. */
const SPARK_W = 104;
const SPARK_H = 44;

async function load() {
  try {
    detail.value = await api.readinessDetail();
  } catch {
    detail.value = null;
  }
}
onMounted(load);

const band = computed(() => detail.value?.band ?? null);
const bandClass = computed(() => `b-${band.value ?? "none"}`);

/** A driver helped when its sub-score is above the 50 midpoint. sub_score
 *  already accounts for direction, so this stays correct for resting HR
 *  where a lower value is better. */
function isGood(d: ReadinessDriver): boolean {
  return (d.sub_score ?? 50) >= 50;
}

function fmt(d: ReadinessDriver): string {
  if (d.value == null) return "—";
  const n = d.unit === "h" ? d.value.toFixed(1) : d.value.toFixed(0);
  return d.unit ? `${n} ${d.unit}` : n;
}

function openDriver(d: ReadinessDriver) {
  if (d.key === "hrv") router.push("/hrv");
  else if (d.key === "rhr") router.push("/heart-rate");
  else router.push("/sleep");
}

/** Sparkline geometry. Nulls are gaps, not zeros — a day with no score must
 *  not dive the line to the floor and imply a crash that didn't happen.
 *
 *  A point whose neighbours are both missing gets a dot: a bare moveTo draws
 *  nothing, so an isolated real reading would otherwise render as absence. */
const spark = computed(() => {
  const pts = (detail.value?.series ?? []).map((p) => p.score);
  const real = pts.filter((v): v is number => v != null);
  if (real.length < 2) return { path: "", dots: [], last: null };
  const min = Math.min(...real);
  const max = Math.max(...real);
  const span = max - min > 0.5 ? max - min : 1;
  // Drawn in the element's own coordinates (uniform scale, so dots stay
  // round) and inset by the dot radius so the endpoint isn't half-clipped.
  const PAD = 3;
  const stepX = pts.length > 1 ? (SPARK_W - PAD * 2) / (pts.length - 1) : 0;
  const at = (v: number, i: number) => ({
    x: PAD + i * stepX,
    y: SPARK_H - PAD - ((v - min) / span) * (SPARK_H - PAD * 2),
  });

  let path = "";
  let started = false;
  const dots: Array<{ x: number; y: number }> = [];
  pts.forEach((v, i) => {
    if (v == null) { started = false; return; }
    const p = at(v, i);
    if (pts[i - 1] == null && pts[i + 1] == null) dots.push(p);
    path += `${started ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)} `;
    started = true;
  });
  // Emphasise the endpoint — today is the value the header states.
  const lastIdx = pts.length - 1;
  const lastVal = pts[lastIdx];
  return {
    path: path.trim(),
    dots,
    last: lastVal == null ? null : at(lastVal, lastIdx),
  };
});

const ORDER: Array<[string, string]> = [
  ["hrv", "HRV"], ["rhr", "Resting HR"],
  ["sleep_score", "Sleep quality"], ["sleep_duration", "Sleep duration"],
];
</script>

<template>
  <section v-if="detail" class="ready" :class="bandClass">
    <div class="cap">Readiness</div>

    <div class="top">
      <button class="numblock" @click="showFormula = !showFormula">
        <template v-if="detail.score == null">
          <span class="score num">—</span>
          <span class="why">{{ detail.reason ?? "Not enough data yet" }}</span>
        </template>
        <template v-else>
          <span class="scorerow">
            <span class="score num">{{ Math.round(detail.score) }}</span>
            <span class="band">{{ band }}</span>
          </span>
          <span class="how">How this is calculated</span>
        </template>
      </button>

      <svg v-if="spark.path" class="spark"
           :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`">
        <path :d="spark.path" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
        <circle v-for="(p, i) in spark.dots" :key="i" :cx="p.x" :cy="p.y"
                r="2" fill="currentColor" vector-effect="non-scaling-stroke" />
        <circle v-if="spark.last" :cx="spark.last.x" :cy="spark.last.y"
                r="2.5" fill="currentColor" vector-effect="non-scaling-stroke" />
      </svg>
    </div>

    <ul class="drivers">
      <li v-for="d in detail.drivers" :key="d.key">
        <button class="drow" @click="openDriver(d)">
          <span class="arrow" :class="isGood(d) ? 'up' : 'down'">
            {{ isGood(d) ? "▲" : "▼" }}
          </span>
          <span class="dlabel">{{ d.label }}</span>
          <span class="dval num">{{ fmt(d) }}</span>
          <span v-if="d.z != null" class="dz" :class="isGood(d) ? 'up' : 'down'">
            {{ d.z >= 0 ? "+" : "" }}{{ d.z.toFixed(1) }}σ
          </span>
        </button>
      </li>
    </ul>

    <!-- Generated from the payload's weights, not a hand-copied formula —
         retuning the weights server-side updates this automatically. -->
    <div v-if="showFormula" class="formula">
      <p class="fintro">
        A weighted blend of four signals, each scored against your own 28-day
        baseline — not a population average. 50 is your normal.
      </p>
      <div v-for="[key, label] in ORDER" :key="key" class="frow">
        <template v-if="detail.weights[key] != null">
          <span class="flabel">{{ label }}</span>
          <span class="fsub num">
            {{ detail.drivers.find(x => x.key === key)?.sub_score?.toFixed(0) ?? "not used today" }}
          </span>
          <span class="fw">{{ (detail.weights[key] * 100).toFixed(0) }}%</span>
        </template>
      </div>
      <div class="bandkeys">
        <span class="bk low">Low ≤29</span>
        <span class="bk moderate">Moderate 30–64</span>
        <span class="bk high">High ≥65</span>
      </div>
      <p class="fnote">
        When too few signals are available the score is withheld rather than
        guessed — a number driven by one noisy input is worse than no number.
      </p>
    </div>
  </section>
</template>

<style scoped>
.ready {
  --accent: var(--muted);
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 16px; padding: 14px 16px; margin-bottom: 14px;
  color: var(--accent);
}
.ready.b-high { --accent: #22c55e; }
.ready.b-moderate { --accent: #eab308; }
.ready.b-low { --accent: #ef4444; }
.ready { border-color: color-mix(in srgb, var(--accent) 30%, var(--line)); }

.cap {
  font-size: .64rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); font-weight: 700; margin-bottom: 6px;
}
.top { display: flex; align-items: center; gap: 12px; }
.numblock {
  flex: 1; display: flex; flex-direction: column; align-items: flex-start;
  gap: 2px; background: none; border: 0; padding: 0; cursor: pointer;
  text-align: left; color: inherit;
}
.scorerow { display: flex; align-items: baseline; gap: 8px; }
.score { font-size: 2.6rem; font-weight: 800; color: var(--text); line-height: 1; }
.band {
  font-size: .78rem; font-weight: 800; letter-spacing: .1em;
  text-transform: uppercase; color: var(--accent);
}
.how, .why { font-size: .72rem; color: var(--muted); }
.how { color: #28e6ff; font-weight: 600; }
.spark { width: 104px; height: 44px; color: var(--accent); flex: none; }

.drivers { list-style: none; margin: 10px 0 0; padding: 0; }
.drow {
  width: 100%; display: flex; align-items: center; gap: 8px;
  background: none; border: 0; padding: 5px 0; cursor: pointer; color: inherit;
}
.arrow { font-size: .7rem; font-weight: 700; }
.up { color: #22c55e; } .down { color: #ef4444; }
.dlabel { flex: 1; text-align: left; font-size: .8rem; color: var(--muted); }
.dval { font-size: .85rem; color: var(--text); font-weight: 600; }
.dz { font-size: .74rem; font-weight: 600; }

.formula {
  margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line);
}
.fintro, .fnote { font-size: .78rem; color: var(--muted); margin: 0 0 8px; }
.fnote { margin: 10px 0 0; }
.frow { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.flabel { flex: 1; font-size: .8rem; color: var(--text); }
.fsub { font-size: .8rem; color: var(--text); font-weight: 600; }
.fw { font-size: .74rem; color: #28e6ff; font-weight: 700; }
.bandkeys { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; }
.bk { font-size: .7rem; color: var(--muted); }
.bk::before {
  content: ""; display: inline-block; width: 8px; height: 8px;
  border-radius: 3px; margin-right: 5px; vertical-align: middle;
}
.bk.low::before { background: #ef4444; }
.bk.moderate::before { background: #eab308; }
.bk.high::before { background: #22c55e; }
</style>
