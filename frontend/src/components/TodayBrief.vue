<script setup lang="ts">
/**
 * Today brief — the home hero, web twin of `ui/common/TodayBrief.kt`.
 *
 * Replaces TodayHero (weekly-steps ring + three chips) and the Readiness
 * card under "Health status". Between them those showed readiness twice and
 * steps three times before the first metric card, and the hero answered
 * "how far through the week's steps am I" — not the question anyone opens
 * the app with in the morning.
 *
 * One concentric tri-ring, the app's own mark, with readiness at its
 * centre: Sleep outer (magenta), Move middle (lime), Readiness inner
 * (cyan). Beside it a plain legend in the same order carries the numbers.
 * The hero sits on the page ground rather than in a card.
 *
 * Every number is the server's: tile values and targets from
 * /summary/tiles, readiness and its band from /summary/readiness, the
 * weekly figure from the tiles response's `week`. value / target below is
 * arc geometry, not a metric.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { ReadinessDetail, VitalTile, VitalTilesResponse } from "@/api/types";

const router = useRouter();
const tiles = ref<VitalTile[]>([]);
const resp = ref<VitalTilesResponse | null>(null);
const readiness = ref<ReadinessDetail | null>(null);
const loaded = ref(false);

onMounted(async () => {
  const [t, r] = await Promise.allSettled([api.summaryTiles(), api.readinessDetail()]);
  if (t.status === "fulfilled") { resp.value = t.value; tiles.value = t.value.tiles ?? []; }
  if (r.status === "fulfilled") readiness.value = r.value;
  loaded.value = true;
});

const tile = (k: string) => tiles.value.find((t) => t.key === k);

function frac(t?: VitalTile): number | null {
  if (!t || typeof t.value !== "number" || !t.target || t.target <= 0) return null;
  return Math.max(0, Math.min(1, t.value / t.target));
}

function fmtSleep(v: unknown): string {
  if (typeof v !== "number") return "—";
  const h = Math.floor(v);
  return `${h}h ${Math.round((v - h) * 60)}m`;
}
const fmtHours = (h: number) => (Number.isInteger(h) ? `${h}h` : fmtSleep(h));
const cap = (s?: string | null) => (s ? s[0].toUpperCase() + s.slice(1) : null);

const score = computed(() => readiness.value?.score ?? null);

/** Outer → inner. A null fraction draws the track only: "no reading" must
 *  not look like "zero". */
const SIZE = 176, STROKE = 13, GAP = 4;
const rings = computed(() =>
  [
    { color: "#ff3ad8", f: frac(tile("sleep_duration")) },
    { color: "#5dff3b", f: frac(tile("steps")) },
    { color: "#28e6ff", f: score.value == null ? null : Math.max(0, Math.min(1, score.value / 100)) },
  ].map((r, i) => {
    const rad = SIZE / 2 - STROKE / 2 - i * (STROKE + GAP);
    const c = 2 * Math.PI * rad;
    return { ...r, rad, c, off: r.f == null ? c : c * (1 - r.f) };
  }),
);

const rows = computed(() => {
  const sleep = tile("sleep_duration");
  const steps = tile("steps");
  const week = resp.value?.week;
  return [
    { key: "sleep", color: "#ff3ad8", label: "Sleep", route: "/sleep",
      value: fmtSleep(sleep?.value),
      sub: sleep?.target ? `of ${fmtHours(sleep.target)}` : null },
    { key: "move", color: "#5dff3b", label: "Move", route: "/steps",
      value: typeof steps?.value === "number" ? steps.value.toLocaleString() : "—",
      sub: week ? `${Math.round(week.pct)}% of the week`
        : steps?.target ? `of ${steps.target.toLocaleString()}` : null },
    { key: "ready", color: "#28e6ff", label: "Readiness", route: "/body",
      value: cap(readiness.value?.band) ?? "—",
      sub: score.value != null ? "50 is your normal" : cap(readiness.value?.reason) },
  ];
});

const roll = computed(() => {
  const r = resp.value?.summary;
  return r && r.judged ? r : null;
});

const syncNote = computed(() => {
  const iso = resp.value?.last_sync;
  if (!iso) return null;
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(min)) return null;
  if (min < 1) return "Synced just now";
  if (min < 60) return `Synced ${min}m ago`;
  if (min < 1440) return `Synced ${Math.floor(min / 60)}h ago`;
  return `Synced ${Math.floor(min / 1440)}d ago`;
});
</script>

<template>
  <section v-if="loaded" class="brief">
    <div class="top">
      <button class="ring" aria-label="Readiness details" @click="router.push('/body')">
        <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" aria-hidden="true">
          <g v-for="(r, i) in rings" :key="i" :transform="`rotate(-90 ${SIZE / 2} ${SIZE / 2})`">
            <circle :cx="SIZE / 2" :cy="SIZE / 2" :r="r.rad" fill="none"
              :stroke="r.color" stroke-opacity=".13" :stroke-width="STROKE" />
            <template v-if="r.f">
              <circle :cx="SIZE / 2" :cy="SIZE / 2" :r="r.rad" fill="none"
                :stroke="r.color" stroke-opacity=".12" :stroke-width="STROKE + 4"
                stroke-linecap="round" :stroke-dasharray="r.c" :stroke-dashoffset="r.off" />
              <circle :cx="SIZE / 2" :cy="SIZE / 2" :r="r.rad" fill="none"
                :stroke="r.color" :stroke-width="STROKE"
                stroke-linecap="round" :stroke-dasharray="r.c" :stroke-dashoffset="r.off" />
            </template>
          </g>
        </svg>
        <span class="centre">
          <span class="score num">{{ score == null ? "—" : Math.round(score) }}</span>
          <span class="clabel">Readiness</span>
        </span>
      </button>

      <div class="legend">
        <button v-for="r in rows" :key="r.key" class="row" @click="router.push(r.route)">
          <span class="bar" :style="{ background: r.color }" />
          <span class="txt">
            <span class="lab">{{ r.label }}</span>
            <span class="val num">{{ r.value }}</span>
            <span v-if="r.sub" class="sub">{{ r.sub }}</span>
          </span>
        </button>
      </div>
    </div>

    <!-- The roll-up and freshness qualify the numbers above, so they sit
         directly under them with no section of their own. -->
    <div v-if="roll || syncNote" class="status">
      <template v-if="roll">
        <span class="dot" :class="{ warn: roll.in_range < roll.judged }" />
        <span class="rtext">{{ roll.in_range }} of {{ roll.judged }} vitals in your range</span>
      </template>
      <span v-if="syncNote" class="sync">{{ syncNote }}</span>
    </div>
  </section>
</template>

<style scoped>
.brief { margin: 4px 0 22px; max-width: 640px; }
.top { display: flex; align-items: center; gap: 18px; }

.ring {
  position: relative; flex: none; width: 176px; height: 176px;
  padding: 0; border: 0; background: none; border-radius: 50%;
  cursor: pointer; color: inherit;
}
.ring svg { width: 100%; height: 100%; display: block; overflow: visible; }
.centre {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
}
.score {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  font-size: 2.4rem; font-weight: 500; letter-spacing: -1px; line-height: 1;
  color: #ececf5; font-variant-numeric: tabular-nums;
}
.clabel { font-size: .7rem; color: #9b9bb0; margin-top: 4px; }

.legend { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.row {
  display: flex; align-items: flex-start; gap: 10px; text-align: left;
  padding: 0; border: 0; background: none; color: inherit; cursor: pointer;
  border-radius: 10px;
}
.bar { flex: none; width: 3px; height: 30px; margin-top: 5px; border-radius: 2px; }
.txt { display: flex; flex-direction: column; min-width: 0; }
.lab { font-size: .75rem; color: #9b9bb0; }
.val {
  font-family: 'Space Grotesk', 'Geist Mono', monospace;
  font-size: 1.25rem; font-weight: 500; color: #ececf5; line-height: 1.25;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}
.sub { font-size: .7rem; color: #9b9bb0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.status { display: flex; align-items: center; gap: 8px; margin-top: 14px; }
.dot { width: 6px; height: 6px; border-radius: 3px; background: #5dff3b; flex: none; }
.dot.warn { background: #ffb52e; }
.rtext { font-size: .82rem; color: rgba(236, 236, 245, .85); }
.sync { margin-left: auto; font-size: .75rem; color: #9b9bb0; }

.ring:focus-visible, .row:focus-visible { outline: 2px solid #28e6ff; outline-offset: 3px; }
</style>
