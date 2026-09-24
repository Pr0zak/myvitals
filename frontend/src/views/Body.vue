<script setup lang="ts">
/**
 * Body — recovery hero + the shared metric cards in two tiers. Phone twin:
 * `BodyScreen.kt`.
 *
 *   hero     recovery ring (the recovery tile's value and server wording),
 *            HRV / resting HR / sleep beside it with their server deltas,
 *            and "N of M vitals in range · synced Xm ago" from the rollup
 *   daily    2-up MetricCards with a taller spark
 *   by hand  weight, blood pressure, skin temp as compact rows with the
 *            reading's own date and a 14-day reading strip
 *
 * The tier is each tile's `cadence`, decided server-side, so the two
 * clients cannot keep different lists. One request feeds everything; it is
 * handed to `KeyMetrics` rather than fetched twice.
 *
 * Failure is not absence: a failed request shows an error with a retry, and
 * a server that answered with no tiles says "no vitals yet" — two different
 * sentences for two different facts.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { VitalTile, VitalTilesResponse } from "@/api/types";
import KeyMetrics from "@/components/KeyMetrics.vue";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";

const router = useRouter();
const data = ref<VitalTilesResponse | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    data.value = await api.summaryTiles();
    error.value = null;
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    error.value = typeof detail === "string" ? detail : "Couldn't reach the backend.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const byKey = computed<Record<string, VitalTile>>(() =>
  Object.fromEntries((data.value?.tiles ?? []).map((t) => [t.key, t])),
);
const rec = computed(() => byKey.value.recovery ?? null);
const recValue = computed<number | null>(() =>
  typeof rec.value?.value === "number" ? rec.value.value : null,
);
const recChip = computed(() => {
  const r = rec.value?.status_reason;
  if (r) return r[0].toUpperCase() + r.slice(1);
  return recValue.value == null ? "No reading yet" : null;
});
const TONE: Record<string, string> = { good: "#5dff3b", typical: "#9b9bb0", watch: "#ffb52e" };
const recTone = computed(() => TONE[rec.value?.status ?? ""] ?? "#9b9bb0");

function asOf(t: VitalTile | null): string | null {
  if (!t || t.stale_days == null || t.stale_days <= 0 || !t.as_of) return null;
  const d = new Date(t.as_of + "T00:00:00");
  return Number.isNaN(d.getTime())
    ? null : "as of " + d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const DRIVERS = [
  { key: "hrv", color: "#28e6ff", route: "/hrv" },
  { key: "resting_hr", color: "#28e6ff", route: "/heart-rate" },
  { key: "sleep_duration", color: "#ff3ad8", route: "/sleep" },
];

function fmt(v: number | string | null): string {
  if (v == null) return "—";
  if (typeof v !== "number") return v;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** The server's delta, verbatim — the client never subtracts. Coloured by
 *  the server's `higher_is_better`; null direction stays neutral. */
function deltaChip(t: VitalTile): { text: string; color: string } | null {
  const d = t.delta;
  if (t.value == null || d == null || Math.abs(d) < 0.05) return null;
  const better = t.higher_is_better == null ? null : (t.higher_is_better ? d > 0 : d < 0);
  return {
    text: `${d > 0 ? "▲" : "▼"} ${Math.abs(d).toFixed(1)}`,
    color: better == null ? "#9b9bb0" : better ? "#5dff3b" : "#ffb52e",
  };
}

function syncAge(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const min = Math.max(0, Math.floor((Date.now() - t) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  if (min < 1440) return `${Math.floor(min / 60)}h ago`;
  return `${Math.floor(min / 1440)}d ago`;
}

const footer = computed(() => {
  const s = data.value?.summary;
  const parts: string[] = [];
  if (s && s.judged > 0) parts.push(`${s.in_range} of ${s.judged} vitals in range`);
  const age = syncAge(data.value?.last_sync);
  if (age) parts.push(`synced ${age}`);
  return parts.join(" · ");
});
</script>

<template>
  <NeonPage title="Body">
    <!-- Nothing has loaded yet. -->
    <template v-if="!data">
      <div v-if="loading" class="skel" aria-busy="true">
        <div class="sk hero"><span>Recovery</span></div>
        <div class="sk-row"><div class="sk"><span>HRV</span></div><div class="sk"><span>Resting HR</span></div></div>
        <div class="sk-row"><div class="sk"><span>Sleep</span></div><div class="sk"><span>Steps</span></div></div>
        <div class="sk short"><span>Weight</span></div>
      </div>
      <button v-else-if="error" class="errbar" @click="load">
        <b>Couldn't load your vitals</b>
        <span>{{ error }}</span>
        <em>Tap to retry</em>
      </button>
    </template>

    <template v-else>
      <button v-if="error" class="errbar" @click="load">
        <b>Couldn't refresh</b>
        <span>Showing the last copy loaded. {{ error }}</span>
        <em>Tap to retry</em>
      </button>

      <div v-if="!data.tiles.length" class="empty">
        <b>No vitals yet</b>
        <span>They appear here once your watch has synced through Health Connect.</span>
      </div>

      <template v-else>
        <NeonHero accent="#28e6ff">
          <div class="hero">
            <button class="rcol" @click="router.push('/trends')">
              <NeonRing :fraction="(recValue ?? 0) / 100" color="#28e6ff" :size="108" :stroke="9">
                <div class="rv" :class="{ mut: recValue == null }">{{ recValue != null ? fmt(recValue) : "—" }}</div>
                <div class="rc">RECOVERY</div>
              </NeonRing>
              <span v-if="recChip" class="chip"
                    :style="{ color: recTone, background: `color-mix(in srgb, ${recTone} 13%, transparent)` }">
                {{ recChip }}
              </span>
              <span v-if="asOf(rec)" class="asof">{{ asOf(rec) }}</span>
            </button>
            <div class="drivers">
              <template v-for="d in DRIVERS" :key="d.key">
                <button v-if="byKey[d.key]" class="drv" @click="router.push(d.route)">
                  <span class="dl">{{ byKey[d.key]!.label }}</span>
                  <span class="dv">
                    <b :style="{ color: byKey[d.key]!.value != null ? d.color : '#9b9bb0' }">{{ fmt(byKey[d.key]!.value) }}</b>
                    <small v-if="byKey[d.key]!.value != null && byKey[d.key]!.unit">{{ byKey[d.key]!.unit }}</small>
                    <i v-if="deltaChip(byKey[d.key]!)" :style="{ color: deltaChip(byKey[d.key]!)!.color }">
                      {{ deltaChip(byKey[d.key]!)!.text }}
                    </i>
                    <!-- Sleep is judged against a target, not a baseline, so
                         it carries no delta; name the target instead. -->
                    <i v-else-if="d.key === 'sleep_duration' && byKey[d.key]!.value != null && byKey[d.key]!.target != null"
                       class="mut">of {{ fmt(byKey[d.key]!.target ?? null) }}h</i>
                  </span>
                </button>
              </template>
            </div>
          </div>
          <div v-if="footer" class="foot">{{ footer }}</div>
        </NeonHero>

        <KeyMetrics :data="data" :title="null" :exclude="['recovery']" tiered :chart-height="56" />
      </template>
    </template>
  </NeonPage>
</template>

<style scoped>
.hero { display: flex; align-items: center; gap: 16px; }
.rcol { display: flex; flex-direction: column; align-items: center; gap: 8px; background: none; border: 0;
  padding: 0; cursor: pointer; color: inherit; }
.rv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 28px; color: #ececf5; }
.rv.mut, .mut { color: #9b9bb0; }
.rc { font-size: 9px; font-weight: 700; letter-spacing: .12em; color: #9b9bb0; }
.chip { font-size: 10.5px; font-weight: 600; padding: 3px 9px; border-radius: 999px; white-space: nowrap; }
.asof { font-size: 10px; color: #9b9bb0; }
.drivers { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.drv { display: flex; flex-direction: column; align-items: flex-start; background: none; border: 0; padding: 0;
  cursor: pointer; color: inherit; text-align: left; }
.dl { font-size: 11px; color: #9b9bb0; }
.dv { display: flex; align-items: baseline; gap: 4px; }
.dv b { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 19px; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.dv small { font-size: 11px; color: #9b9bb0; }
.dv i { font-style: normal; font-size: 11px; font-weight: 600; margin-left: 4px; }
.foot { border-top: 1px solid #23263a; margin-top: 12px; padding-top: 10px; font-size: 12px; color: #9b9bb0; }

.errbar { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 93, 122, .10); border: 1px solid rgba(255, 93, 122, .28); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: inherit; font: inherit; }
.errbar b { color: #ff5d7a; font-size: 13px; }
.errbar span { color: #9b9bb0; font-size: 12px; }
.errbar em { color: #28e6ff; font-size: 12px; font-style: normal; font-weight: 600; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 7px; text-align: center;
  background: #1e2230; border: 1px solid rgba(40, 230, 255, .22); border-radius: 18px; padding: 28px 20px; }
.empty b { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 15px; }
.empty span { color: #9b9bb0; font-size: 12.5px; }

.skel { display: flex; flex-direction: column; gap: 10px; }
.sk-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.sk { height: 180px; border-radius: 20px; position: relative; overflow: hidden;
  background: linear-gradient(90deg, rgba(31,41,55,.5), rgba(40,230,255,.12), rgba(31,41,55,.5));
  background-size: 300% 100%; animation: sweep 1.4s linear infinite; }
.sk.hero { height: 190px; }
.sk.short { height: 92px; }
.sk span { position: absolute; top: 14px; left: 14px; font-size: 12px; color: rgba(40, 230, 255, .75); }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
