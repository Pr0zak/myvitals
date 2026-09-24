<script setup lang="ts">
/**
 * Fasting (UI-6) — stage ring, history bars, 90-day stats, protocol carousel.
 *
 * Backend ownership: elapsed_h, the stage and its label, the next stage,
 * every stage threshold (ring ticks), the target end instant and whether a
 * past fast reached its target all come from /fasting/* (FASTING_STAGES in
 * api/fasting.py). The only local arithmetic is the live ticker from the
 * server's start instant. Times print in the user's LOCAL clock.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, type FastingSessionOut, type FastingStatsOut } from "@/api/client";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";

const CYAN = "#28e6ff";
const PROTOCOLS: Array<{ slug: string; label: string; target_h: number; eating_h?: number }> = [
  { slug: "16:8", label: "16:8", target_h: 16, eating_h: 8 },
  { slug: "18:6", label: "18:6", target_h: 18, eating_h: 6 },
  { slug: "20:4", label: "20:4", target_h: 20, eating_h: 4 },
  { slug: "omad", label: "OMAD", target_h: 23, eating_h: 1 },
  { slug: "extended_24", label: "24h", target_h: 24 },
  { slug: "extended_36", label: "36h", target_h: 36 },
  { slug: "extended_48", label: "48h", target_h: 48 },
  { slug: "extended_72", label: "72h", target_h: 72 },
];

const current = ref<FastingSessionOut | null>(null);
// Whether we KNOW if a fast is running. A failed /current must never fall
// through to the picker, which reads as "not fasting".
const currentKnown = ref(false);
const history = ref<FastingSessionOut[]>([]);
const stats = ref<FastingStatsOut | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const actionError = ref<string | null>(null);
const selectedProtocol = ref("16:8");
const now = ref(Date.now());
let tickTimer: number | null = null;

const selectedSpec = computed(() => PROTOCOLS.find((p) => p.slug === selectedProtocol.value) ?? PROTOCOLS[0]);

// In-fast logging.
const logHunger = ref<number>(5);
const logMood = ref<number>(5);
const logHydration = ref<number | null>(null);
const logNotes = ref<string>("");
const logSaving = ref(false);
const logMsg = ref<string>("");

async function submitLog() {
  if (!current.value || !current.value.is_active) return;
  logSaving.value = true; logMsg.value = "";
  try {
    await api.fastingLogAdd({
      session_id: current.value.id,
      hunger: Number(logHunger.value),
      mood: Number(logMood.value),
      hydration_ml: logHydration.value ? Number(logHydration.value) : undefined,
      notes: logNotes.value.trim() || undefined,
    });
    logMsg.value = "Logged.";
    logNotes.value = "";
  } catch (e: unknown) {
    logMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    logSaving.value = false;
  }
}

const liveElapsedH = computed<number>(() => {
  if (!current.value) return 0;
  return Math.max(0, (now.value - new Date(current.value.started_at).getTime()) / 3_600_000);
});
// Ring scale: the target, else the next stage threshold, else the last.
const ringScale = computed<number>(() => {
  const c = current.value;
  if (!c) return 16;
  const stages = c.stages ?? [];
  return c.target_hours
    ?? stages.find((s) => s.at_h > liveElapsedH.value)?.at_h
    ?? stages[stages.length - 1]?.at_h
    ?? 72;
});
const ticks = computed(() =>
  (current.value?.stages ?? []).filter((s) => s.at_h > 0 && s.at_h < ringScale.value).map((s) => s.at_h / ringScale.value),
);
const elapsedClock = computed(() => {
  const h = Math.floor(liveElapsedH.value);
  const m = Math.floor((liveElapsedH.value - h) * 60);
  return `${h}:${String(m).padStart(2, "0")}`;
});
function localTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
function localStart(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
    + ", " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
const heroLine = computed(() => {
  const c = current.value;
  if (!c) return "";
  const parts: string[] = [];
  const end = localTime(c.target_end_at);
  if (end) parts.push(`Ends ${end}`);
  if (c.next_stage_at_h != null && c.next_stage_label) {
    parts.push(`${c.next_stage_label} in ${Math.max(0, c.next_stage_at_h - liveElapsedH.value).toFixed(1)}h`);
  }
  return parts.join(" · ");
});

// History bars — oldest left; heights scaled to the tallest bar or target.
const bars = computed(() => [...history.value].slice(0, 20).reverse());
const barMax = computed(() => Math.max(1, ...bars.value.map((r) => Math.max(r.elapsed_h, r.target_hours ?? 0))));

async function loadAll() {
  try {
    const [c, h, s] = await Promise.all([api.fastingCurrent(), api.fastingHistory(20), api.fastingStats(90)]);
    current.value = c;
    currentKnown.value = true;
    history.value = h;
    stats.value = s;
    error.value = null;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function start() {
  if (busy.value) return;
  busy.value = true;
  actionError.value = null;
  try {
    const spec = selectedSpec.value;
    current.value = await api.fastingStart({ protocol: spec.slug, target_hours: spec.target_h, target_eating_window_h: spec.eating_h });
    await loadAll();
  } catch (e: unknown) {
    actionError.value = "Couldn't start: " + (e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

async function end() {
  if (busy.value) return;
  if (!confirm("End the current fast?")) return;
  busy.value = true;
  actionError.value = null;
  try {
    await api.fastingEnd();
    await loadAll();
  } catch (e: unknown) {
    actionError.value = "Couldn't end: " + (e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  loadAll();
  tickTimer = window.setInterval(() => { now.value = Date.now(); }, 1_000);
});
onBeforeUnmount(() => { if (tickTimer !== null) window.clearInterval(tickTimer); });
</script>

<template>
  <NeonPage title="Fasting" back="/you">
    <template #trailing>
      <span v-if="stats" class="pill">{{ stats.current_streak_days }}d streak</span>
    </template>

    <p v-if="error && currentKnown" class="stale">Showing what we last loaded — refresh failed.</p>

    <button v-if="!currentKnown && error" class="fail" type="button" @click="loadAll">
      <strong>Couldn't load your fast</strong>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>

    <NeonHero v-else-if="!currentKnown" :accent="CYAN">
      <div class="hero"><NeonRing :fraction="0" :color="CYAN" :size="260" :stroke="12"><span class="muted">Loading your fast…</span></NeonRing></div>
    </NeonHero>

    <template v-else-if="current && current.is_active">
      <NeonHero :accent="CYAN">
        <div class="hero">
          <NeonRing :fraction="liveElapsedH / ringScale" :color="CYAN" :size="260" :stroke="12" :ticks="ticks">
            <span class="elapsed">{{ elapsedClock }}</span>
            <span class="cap">{{ current.target_hours ? `of ${current.target_hours.toFixed(0)}h · ${current.protocol}` : current.protocol }}</span>
          </NeonRing>
          <span class="pill">{{ current.current_stage_label ?? current.current_stage }}</span>
          <span v-if="heroLine" class="line">{{ heroLine }}</span>
          <span class="since">started {{ localStart(current.started_at) }}</span>
        </div>
      </NeonHero>

      <template v-if="current.protocol.startsWith('extended_') || liveElapsedH >= 12">
        <NeonEyebrow>How are you feeling?</NeonEyebrow>
        <div class="card log-card">
          <label class="slider"><span>Hunger</span><input v-model.number="logHunger" type="range" min="0" max="10" /><span class="val">{{ logHunger }}</span></label>
          <label class="slider"><span>Mood</span><input v-model.number="logMood" type="range" min="0" max="10" /><span class="val">{{ logMood }}</span></label>
          <label class="field"><span>Hydration today (ml)</span><input v-model.number="logHydration" type="number" min="0" step="50" placeholder="optional" /></label>
          <label class="field"><span>Notes</span><textarea v-model="logNotes" rows="2" placeholder="brief — what symptoms, what's working" /></label>
          <button class="outline" :disabled="logSaving" @click="submitLog">{{ logSaving ? "Saving…" : "Log entry" }}</button>
          <span v-if="logMsg" class="muted small">{{ logMsg }}</span>
        </div>
      </template>

      <button class="outline big" :disabled="busy" @click="end">{{ busy ? "Ending…" : "End fast" }}</button>
    </template>

    <template v-else>
      <NeonEyebrow>Start a fast</NeonEyebrow>
      <div class="carousel">
        <button v-for="p in PROTOCOLS" :key="p.slug" class="proto" :class="{ on: selectedProtocol === p.slug }"
                type="button" @click="selectedProtocol = p.slug">
          <span class="proto-label">{{ p.label }}</span>
          <span class="muted small">{{ p.target_h }}h fast</span>
          <span class="win"><i class="fast" :style="{ flexGrow: 24 - (p.eating_h ?? 0) }" /><i v-if="p.eating_h" class="eat" :style="{ flexGrow: p.eating_h }" /></span>
          <span class="muted tiny">{{ p.eating_h ? `${p.eating_h}h eating` : "no eating window" }}</span>
        </button>
      </div>
      <button class="primary" :disabled="busy" @click="start">{{ busy ? "Starting…" : `Start ${selectedSpec.label}` }}</button>
    </template>

    <p v-if="actionError" class="action-err">{{ actionError }}</p>

    <template v-if="bars.length">
      <NeonEyebrow>Last {{ bars.length }} fasts</NeonEyebrow>
      <div class="card chart">
        <div v-for="r in bars" :key="r.id" class="col" :title="`${r.protocol} · ${r.elapsed_h.toFixed(1)}h · ${localStart(r.started_at)}`">
          <div class="bar" :class="r.reached_target === true ? 'done' : r.reached_target === false ? 'short' : 'open'"
               :style="{ height: Math.max(2, (r.elapsed_h / barMax) * 100) + '%' }" />
          <div v-if="r.target_hours" class="tgt" :style="{ bottom: (r.target_hours / barMax) * 100 + '%' }" />
        </div>
      </div>
      <div class="legend"><i class="sw done" />reached target <i class="sw short" />short <span>— target</span></div>
      <ul class="recent">
        <li v-for="r in history.slice(0, 5)" :key="r.id">
          <span class="muted">{{ localStart(r.started_at) }}</span>
          <span class="muted">{{ r.protocol }}</span>
          <span class="num" :class="{ ok: r.reached_target === true }">{{ r.elapsed_h.toFixed(1) }}h</span>
        </li>
      </ul>
    </template>

    <template v-if="stats && stats.sessions_count > 0">
      <NeonEyebrow>Last 90 days</NeonEyebrow>
      <div class="grid2">
        <NeonStat :value="`${stats.completed_count} / ${stats.sessions_count}`" label="completed" />
        <NeonStat :value="stats.avg_duration_h != null ? `${stats.avg_duration_h.toFixed(1)}h` : '—'" label="average" />
        <NeonStat :value="stats.median_duration_h != null ? `${stats.median_duration_h.toFixed(1)}h` : '—'" label="median" />
        <NeonStat :value="stats.longest_h != null ? `${stats.longest_h.toFixed(1)}h` : '—'" label="longest" :accent="CYAN" />
      </div>
    </template>
  </NeonPage>
</template>

<style scoped>
.hero { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.elapsed { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 48px; color: var(--rn-ink); letter-spacing: -1px; line-height: 1; }
.cap { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); margin-top: 4px; }
.pill { font-size: 12px; font-weight: 600; color: #28e6ff; padding: 6px 12px; border-radius: 22px; white-space: nowrap;
  background: rgba(40, 230, 255, .12); border: 1px solid rgba(40, 230, 255, .35); }
.line { font-size: 13px; color: var(--rn-mut); text-align: center; }
.since { font-size: 11px; color: var(--rn-mut); }
.muted { color: var(--rn-mut); }
.small { font-size: 12px; }
.tiny { font-size: 10px; }
.stale { font-size: 11px; color: var(--rn-mut); margin: 0 0 8px; }
.fail { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 181, 46, .08); border: 1px solid rgba(255, 181, 46, .3); border-radius: 14px; padding: 12px 14px;
  color: var(--rn-mut); font: inherit; font-size: 12px; margin-bottom: 12px; }
.fail strong { color: #ffb52e; font-size: 13px; }
.fail em { font-style: normal; color: #28e6ff; font-weight: 600; }
.action-err { color: #ffb52e; font-size: 12px; }
.card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; }
.log-card { display: flex; flex-direction: column; gap: 8px; }
.slider { display: grid; grid-template-columns: 70px 1fr 28px; align-items: center; gap: 8px; font-size: 12px; color: var(--rn-mut); }
.slider input { accent-color: #28e6ff; }
.val { color: var(--rn-ink); text-align: right; }
.field { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--rn-mut); }
.field input, .field textarea { background: var(--rn-bg); color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 8px; padding: 8px; font: inherit; font-size: 14px; }
.outline { min-height: 44px; border-radius: 16px; border: 1px solid var(--rn-line); background: transparent; color: var(--rn-ink);
  font: inherit; font-weight: 600; cursor: pointer; }
.outline.big { width: 100%; height: 52px; margin-top: 12px; font-size: 15px; }
.outline:disabled, .primary:disabled { opacity: .6; cursor: default; }
.primary { width: 100%; height: 52px; margin-top: 12px; border-radius: 16px; border: 0; background: #28e6ff; color: var(--rn-onacc);
  font: inherit; font-weight: 700; font-size: 15px; cursor: pointer; }
.carousel { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; scroll-snap-type: x mandatory; }
.proto { flex: 0 0 118px; scroll-snap-align: start; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left;
  background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 12px; cursor: pointer; font: inherit; color: var(--rn-ink); }
.proto.on { background: var(--rn-high); border: 1.5px solid #28e6ff; }
.proto-label { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 20px; }
.proto.on .proto-label { color: #28e6ff; }
.win { display: flex; width: 100%; height: 6px; border-radius: 3px; overflow: hidden; background: var(--rn-track); margin: 8px 0 2px; }
.win .fast { background: rgba(40, 230, 255, .55); }
.win .eat { background: #5dff3b; }
.chart { display: flex; align-items: flex-end; gap: 4px; height: 148px; }
.col { position: relative; flex: 1; height: 120px; display: flex; align-items: flex-end; justify-content: center; }
.bar { width: 62%; max-width: 18px; border-radius: 3px 3px 0 0; }
.bar.done { background: #28e6ff; }
.bar.short { background: rgba(155, 155, 176, .55); }
.bar.open { background: rgba(111, 123, 255, .7); }
.tgt { position: absolute; left: 12%; right: 12%; height: 2px; background: rgba(236, 236, 245, .75); }
.legend { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--rn-mut); margin: 6px 0 4px; }
.legend .sw { width: 8px; height: 8px; border-radius: 2px; display: inline-block; margin-left: 8px; }
.legend .sw:first-child { margin-left: 0; }
.legend .sw.done { background: #28e6ff; }
.legend .sw.short { background: rgba(155, 155, 176, .55); }
.legend span { margin-left: 10px; }
.recent { list-style: none; margin: 4px 0 0; padding: 0; }
.recent li { display: flex; gap: 10px; padding: 5px 0; font-size: 12px; }
.recent li .muted:first-child { flex: 1; }
.num { font-family: 'Space Grotesk', monospace; font-weight: 700; color: var(--rn-ink); }
.num.ok { color: #28e6ff; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
</style>
