<script setup lang="ts">
/**
 * Body — recovery hero + the shared metric cards in two tiers. Phone twin:
 * `BodyScreen.kt`.
 *
 *   hero     recovery ring (the recovery tile's value and server wording),
 *            HRV / resting HR / sleep beside it with their server deltas,
 *            then one status line: "N of M vitals in your range" and the
 *            sync age, from the rollup
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

const rollText = computed(() => {
  const s = data.value?.summary;
  return s && s.judged > 0 ? `${s.in_range} of ${s.judged} vitals in your range` : null;
});
const rollWarn = computed(() => {
  const s = data.value?.summary;
  return !!s && s.in_range < s.judged;
});
const syncText = computed(() => {
  const age = syncAge(data.value?.last_sync);
  return age ? `Synced ${age}` : null;
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
        <!-- Hero on the page ground, in the Today brief's language: the
             ring on the left, a coloured-bar legend on the right carrying
             the numbers, then one quiet status line. -->
        <section class="brief">
          <button class="rcol" aria-label="Recovery trend" @click="router.push('/trends')">
            <NeonRing :fraction="(recValue ?? 0) / 100" color="#28e6ff" :size="176" :stroke="13">
              <div class="rv" :class="{ mut: recValue == null }">{{ recValue != null ? fmt(recValue) : "—" }}</div>
              <div class="rc">Recovery</div>
            </NeonRing>
          </button>
          <div class="legend">
            <template v-for="d in DRIVERS" :key="d.key">
              <button v-if="byKey[d.key]" class="row" @click="router.push(d.route)">
                <span class="bar" :style="{ background: d.color }" />
                <span class="txt">
                  <span class="lab">{{ byKey[d.key]!.label }}</span>
                  <span class="val">
                    {{ fmt(byKey[d.key]!.value) }}<small v-if="byKey[d.key]!.value != null && byKey[d.key]!.unit"> {{ byKey[d.key]!.unit }}</small>
                  </span>
                  <span v-if="deltaChip(byKey[d.key]!)" class="sub" :style="{ color: deltaChip(byKey[d.key]!)!.color }">
                    {{ deltaChip(byKey[d.key]!)!.text }} vs your normal
                  </span>
                  <!-- Sleep is judged against a target, not a baseline, so
                       it carries no delta; name the target instead. -->
                  <span v-else-if="d.key === 'sleep_duration' && byKey[d.key]!.value != null && byKey[d.key]!.target != null"
                        class="sub">of {{ fmt(byKey[d.key]!.target ?? null) }}h</span>
                </span>
              </button>
            </template>
          </div>
        </section>
        <div v-if="rollText || recChip || syncText" class="status">
          <template v-if="rollText">
            <span class="dot" :class="{ warn: rollWarn }" />
            <span class="stext">{{ rollText }}</span>
          </template>
          <span v-else-if="recChip" class="stext" :style="{ color: rec?.status === 'watch' ? '#ffb52e' : undefined }">{{ recChip }}</span>
          <span v-if="syncText" class="sync">{{ syncText }}</span>
        </div>
        <p v-if="rollText && recChip" class="recnote" :class="{ watch: rec?.status === 'watch' }">
          {{ recChip }}<template v-if="asOf(rec)">, {{ asOf(rec) }}</template>
        </p>

        <KeyMetrics :data="data" :title="null" :exclude="['recovery']" tiered :chart-height="56" />
      </template>
    </template>
  </NeonPage>
</template>

<style scoped>
.brief { display: flex; align-items: center; gap: 18px; margin: 4px 0 0; max-width: 640px; }
.rcol { flex: none; background: none; border: 0; padding: 0; cursor: pointer; color: inherit; border-radius: 50%; }
.rv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 500; font-size: 2.4rem;
  letter-spacing: -1px; line-height: 1; color: #ececf5; font-variant-numeric: tabular-nums; }
.rv.mut, .mut { color: #9b9bb0; }
.rc { font-size: .7rem; color: #9b9bb0; margin-top: 4px; text-align: center; }
.legend { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; align-items: flex-start; gap: 10px; text-align: left; padding: 0; border: 0;
  background: none; color: inherit; cursor: pointer; border-radius: 10px; }
.bar { flex: none; width: 3px; height: 30px; margin-top: 5px; border-radius: 2px; }
.txt { display: flex; flex-direction: column; min-width: 0; }
.lab { font-size: .75rem; color: #9b9bb0; }
.val { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 1.25rem; font-weight: 500;
  color: #ececf5; line-height: 1.25; white-space: nowrap; font-variant-numeric: tabular-nums; }
.val small { font-family: 'Plus Jakarta Sans', system-ui; font-size: .7rem; color: #9b9bb0; font-weight: 400; }
.sub { font-size: .7rem; color: #9b9bb0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status { display: flex; align-items: center; gap: 8px; margin: 14px 0 0; max-width: 640px; }
.dot { width: 6px; height: 6px; border-radius: 3px; background: #5dff3b; flex: none; }
.dot.warn { background: #ffb52e; }
.stext { font-size: .82rem; color: rgba(236, 236, 245, .85); }
.sync { margin-left: auto; font-size: .75rem; color: #9b9bb0; }
.recnote { margin: 6px 0 0; font-size: .75rem; color: #9b9bb0; }
.recnote.watch { color: #ffb52e; }
.status + *, .recnote + * { margin-top: 22px; }
.rcol:focus-visible, .row:focus-visible { outline: 2px solid #28e6ff; outline-offset: 3px; }

.errbar { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 93, 122, .10); border: 1px solid rgba(255, 93, 122, .28); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: inherit; font: inherit; }
.errbar b { color: #ff5d7a; font-size: 13px; }
.errbar span { color: #9b9bb0; font-size: 12px; }
.errbar em { color: #28e6ff; font-size: 12px; font-style: normal; font-weight: 600; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 7px; text-align: center;
  background: #181b27; border-radius: 20px; padding: 28px 20px; }
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
