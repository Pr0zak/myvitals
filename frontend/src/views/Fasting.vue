<script setup lang="ts">
/**
 * Fasting view — protocol picker, start/end controls, live progress
 * ring, current stage label, history list, streak / stats card.
 *
 * Backend ownership: all stage thresholds + computed elapsed_h come
 * from /fasting/* — phone + web render identical labels because the
 * server is the source of truth (FASTING_STAGES in api/fasting.py).
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, type FastingSessionOut, type FastingStatsOut } from "@/api/client";
import { Check, Play, Square, History } from "lucide-vue-next";

const PROTOCOLS: Array<{ slug: string; label: string; target_h: number; eating_h?: number }> = [
  { slug: "16:8", label: "16:8", target_h: 16, eating_h: 8 },
  { slug: "18:6", label: "18:6", target_h: 18, eating_h: 6 },
  { slug: "20:4", label: "20:4", target_h: 20, eating_h: 4 },
  { slug: "omad", label: "OMAD (23:1)", target_h: 23, eating_h: 1 },
  { slug: "extended_24", label: "24h fast", target_h: 24 },
  { slug: "extended_36", label: "36h fast", target_h: 36 },
  { slug: "extended_48", label: "48h fast", target_h: 48 },
  { slug: "extended_72", label: "72h fast", target_h: 72 },
];

const STAGE_LABELS: Record<string, string> = {
  fed: "Fed state",
  gut_rest: "Gut rest",
  glycogen_depleting: "Glycogen depleting",
  ketosis: "Ketosis",
  autophagy: "Autophagy",
  deep_autophagy: "Deep autophagy",
  extended_36: "36h territory",
  extended_48: "48h territory",
  extended_72: "72h+ territory",
};

const current = ref<FastingSessionOut | null>(null);
const history = ref<FastingSessionOut[]>([]);
const stats = ref<FastingStatsOut | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const selectedProtocol = ref("16:8");
const now = ref(Date.now());
let tickTimer: number | null = null;

const selectedSpec = computed(() =>
  PROTOCOLS.find((p) => p.slug === selectedProtocol.value) ?? PROTOCOLS[0],
);

// In-fast logging — surfaces in active-fast view once elapsed > 12h
// or for any extended_* protocol. Inputs map to /fasting/logs.
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

// Recompute elapsed locally from started_at so the ring ticks every
// second; current_stage / next_stage_at_h come from the backend.
const liveElapsedH = computed<number>(() => {
  if (!current.value) return 0;
  const startMs = new Date(current.value.started_at).getTime();
  return Math.max(0, (now.value - startMs) / 3_600_000);
});
const targetH = computed<number>(() => current.value?.target_hours ?? 16);
const progressPct = computed<number>(() => {
  if (!current.value) return 0;
  const t = targetH.value;
  if (t <= 0) return 0;
  return Math.min(100, (liveElapsedH.value / t) * 100);
});
const stageLabel = computed<string>(() => {
  const s = current.value?.current_stage ?? "fed";
  return STAGE_LABELS[s] ?? s;
});
const ringDash = computed<number>(() => {
  // Ring stroke circumference = 2 * PI * r. We use r=84 → 527.79.
  const c = 527.79;
  return c * (1 - progressPct.value / 100);
});

function fmtHours(h: number): string {
  const wh = Math.floor(h);
  const m = Math.floor((h - wh) * 60);
  return `${wh}h ${m.toString().padStart(2, "0")}m`;
}
function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "short", day: "numeric",
  }) + " " + d.toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit",
  });
}

async function loadAll() {
  loading.value = true;
  error.value = null;
  try {
    const [c, h, s] = await Promise.all([
      api.fastingCurrent(),
      api.fastingHistory(20),
      api.fastingStats(90),
    ]);
    current.value = c;
    history.value = h;
    stats.value = s;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function start() {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    const spec = selectedSpec.value;
    current.value = await api.fastingStart({
      protocol: spec.slug,
      target_hours: spec.target_h,
      target_eating_window_h: spec.eating_h,
    });
    await loadAll();
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function end() {
  if (busy.value) return;
  if (!confirm("End the current fast?")) return;
  busy.value = true;
  error.value = null;
  try {
    await api.fastingEnd();
    await loadAll();
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  loadAll();
  tickTimer = window.setInterval(() => { now.value = Date.now(); }, 1_000);
});
onBeforeUnmount(() => {
  if (tickTimer !== null) window.clearInterval(tickTimer);
});
</script>

<template>
  <div class="fasting">
    <header class="hdr">
      <h1>Fasting</h1>
      <div v-if="stats" class="streak">
        <span class="streak-n">{{ stats.current_streak_days }}</span>
        <span class="streak-l">day streak</span>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>

    <!-- Active fast hero -->
    <section v-if="current && current.is_active" class="active">
      <div class="ring-wrap">
        <svg viewBox="0 0 200 200" class="ring">
          <circle cx="100" cy="100" r="84" class="track"/>
          <circle cx="100" cy="100" r="84" class="fill"
                  :stroke-dashoffset="ringDash"/>
        </svg>
        <div class="ring-center">
          <div class="elapsed">{{ fmtHours(liveElapsedH) }}</div>
          <div class="stage">{{ stageLabel }}</div>
          <div class="target">of {{ targetH.toFixed(0) }}h target</div>
        </div>
      </div>

      <div class="meta">
        <div><span class="muted">Protocol</span> {{ current.protocol }}</div>
        <div><span class="muted">Started</span> {{ fmtDateTime(current.started_at) }}</div>
        <div v-if="current.next_stage_at_h !== null">
          <span class="muted">Next milestone</span>
          {{ (current.next_stage_at_h - liveElapsedH).toFixed(1) }}h
          → {{ STAGE_LABELS[
            // Pick the next stage label by inspecting FASTING_STAGES locally.
            // Mirrors the server thresholds.
            (() => {
              const stages: Array<[number, string]> = [
                [0, "fed"], [4, "gut_rest"], [12, "glycogen_depleting"],
                [16, "ketosis"], [18, "autophagy"], [24, "deep_autophagy"],
                [36, "extended_36"], [48, "extended_48"], [72, "extended_72"],
              ];
              const next = stages.find(([h]) => h === current!.next_stage_at_h);
              return next ? next[1] : "";
            })()
          ] ?? "" }}
        </div>
      </div>

      <!-- Symptoms / hydration logging card. Surfaces for any
           extended_* protocol or once a 16:8-style fast has crossed
           12h — the early hunger phase is where notes start mattering. -->
      <div v-if="current.protocol.startsWith('extended_') || liveElapsedH >= 12" class="log-card">
        <h4>How are you feeling?</h4>
        <label class="slider">
          <span>Hunger</span>
          <input type="range" min="0" max="10" v-model.number="logHunger"/>
          <span class="val">{{ logHunger }}</span>
        </label>
        <label class="slider">
          <span>Mood</span>
          <input type="range" min="0" max="10" v-model.number="logMood"/>
          <span class="val">{{ logMood }}</span>
        </label>
        <label class="numfield">
          <span>Hydration today (ml)</span>
          <input type="number" min="0" step="50" v-model.number="logHydration" placeholder="optional"/>
        </label>
        <label class="numfield">
          <span>Notes</span>
          <textarea v-model="logNotes" rows="2" placeholder="brief — what symptoms, what's working"/>
        </label>
        <button class="ghost" :disabled="logSaving" @click="submitLog">
          {{ logSaving ? "Saving…" : "Log entry" }}
        </button>
        <span v-if="logMsg" class="log-msg">{{ logMsg }}</span>
      </div>

      <div class="actions">
        <button class="end" :disabled="busy" @click="end">
          <Square :size="14"/> End fast
        </button>
      </div>
    </section>

    <!-- Idle state — protocol picker + start -->
    <section v-else class="idle">
      <h3>Start a new fast</h3>
      <div class="protocols">
        <button v-for="p in PROTOCOLS" :key="p.slug"
                class="proto"
                :class="{ on: selectedProtocol === p.slug }"
                @click="selectedProtocol = p.slug">
          <span class="proto-label">{{ p.label }}</span>
          <span class="proto-sub">{{ p.target_h }}h fast<span v-if="p.eating_h">, {{ p.eating_h }}h eating</span></span>
        </button>
      </div>
      <div class="actions">
        <button class="primary" :disabled="busy" @click="start">
          <Play :size="14"/> {{ busy ? "Starting…" : `Start ${selectedSpec.label}` }}
        </button>
      </div>
    </section>

    <!-- Stats -->
    <section v-if="stats && stats.sessions_count > 0" class="stats">
      <h3><History :size="14"/> Last 90 days</h3>
      <div class="kpi">
        <div><span class="muted">Completed</span><span>{{ stats.completed_count }} / {{ stats.sessions_count }}</span></div>
        <div v-if="stats.avg_duration_h !== null"><span class="muted">Avg</span><span>{{ stats.avg_duration_h.toFixed(1) }}h</span></div>
        <div v-if="stats.median_duration_h !== null"><span class="muted">Median</span><span>{{ stats.median_duration_h.toFixed(1) }}h</span></div>
        <div v-if="stats.longest_h !== null"><span class="muted">Longest</span><span>{{ stats.longest_h.toFixed(1) }}h</span></div>
      </div>
    </section>

    <!-- History -->
    <section v-if="history.length > 0" class="history">
      <h3>Recent</h3>
      <ul>
        <li v-for="row in history" :key="row.id">
          <div class="row">
            <span class="proto-tag">{{ row.protocol }}</span>
            <span class="duration">{{ row.elapsed_h.toFixed(1) }}h</span>
            <span class="when muted">{{ fmtDateTime(row.started_at) }}</span>
            <Check v-if="row.target_hours && row.elapsed_h >= row.target_hours" :size="14" class="done"/>
          </div>
        </li>
      </ul>
    </section>

    <p v-if="loading" class="hint">Loading…</p>
  </div>
</template>

<style scoped>
.fasting { max-width: 720px; margin: 0 auto; padding: 1rem; }
.hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
h1 { margin: 0; }
.streak { display: flex; align-items: baseline; gap: 0.4rem; color: var(--text); }
.streak-n { font-size: 1.6rem; font-weight: 700; color: #38bdf8; }
.streak-l { color: var(--muted); font-size: 0.85rem; }
.err { color: #ef4444; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; padding: 0.6rem 0.8rem; margin: 0.5rem 0; }
.hint { color: var(--muted); }

section { margin: 1rem 0 1.5rem; padding: 1.2rem; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
section h3 { margin: 0 0 0.8rem; font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; gap: 0.4rem; }

/* Active hero */
.active { display: grid; grid-template-columns: 1fr; gap: 1rem; }
.ring-wrap { position: relative; width: 200px; height: 200px; margin: 0 auto; }
.ring { width: 100%; height: 100%; transform: rotate(-90deg); }
.ring .track { fill: none; stroke: var(--border); stroke-width: 10; }
.ring .fill {
  fill: none; stroke: #38bdf8; stroke-width: 10;
  stroke-dasharray: 527.79; stroke-linecap: round;
  transition: stroke-dashoffset 1s linear;
}
.ring-center {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.2rem;
}
.elapsed { font-size: 1.8rem; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.stage { font-size: 0.78rem; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
.target { font-size: 0.8rem; color: var(--muted); }

.meta { display: flex; flex-direction: column; gap: 0.4rem; font-size: 0.9rem; }
.meta .muted { color: var(--muted); margin-right: 0.4rem; }

/* Idle */
.protocols { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 0.5rem; margin-bottom: 1rem; }
.proto {
  display: flex; flex-direction: column; gap: 0.25rem; padding: 0.65rem;
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; cursor: pointer; text-align: left;
}
.proto.on { background: rgba(56, 189, 248, 0.12); border-color: #38bdf8; }
.proto-label { font-weight: 600; font-size: 0.95rem; }
.proto-sub { color: var(--muted); font-size: 0.78rem; }

.actions { display: flex; gap: 0.5rem; }
button { font-family: inherit; cursor: pointer; border-radius: 8px; padding: 0.65rem 1.2rem; border: 1px solid transparent; font-weight: 500; display: inline-flex; align-items: center; gap: 0.4rem; }
.primary { background: #38bdf8; color: #0f172a; flex: 1; justify-content: center; }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.end { background: transparent; color: #ef4444; border-color: #ef4444; }

.log-card { margin-top: 1rem; padding: 0.9rem; background: var(--surface-2); border-radius: 8px; border: 1px solid var(--border); }
.log-card h4 { margin: 0 0 0.6rem; font-size: 0.85rem; color: var(--text); }
.log-card .slider { display: grid; grid-template-columns: 80px 1fr 32px; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem; font-size: 0.85rem; color: var(--muted); }
.log-card .slider .val { text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }
.log-card .numfield { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.5rem; font-size: 0.78rem; color: var(--muted); }
.log-card .numfield input,
.log-card .numfield textarea { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.5rem; font-family: inherit; }
.log-card .ghost { background: transparent; color: var(--text); border: 1px solid var(--border); padding: 0.45rem 0.9rem; }
.log-msg { margin-left: 0.5rem; color: var(--muted); font-size: 0.78rem; }

/* Stats */
.kpi { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.4rem; }
.kpi > div { display: flex; justify-content: space-between; padding: 0.2rem 0; font-size: 0.9rem; }
.kpi .muted { color: var(--muted); }

/* History */
.history ul { list-style: none; padding: 0; margin: 0; }
.history li { padding: 0.4rem 0; border-bottom: 1px solid rgba(148, 163, 184, 0.1); }
.history li:last-child { border-bottom: none; }
.row { display: flex; align-items: center; gap: 0.8rem; font-size: 0.9rem; }
.proto-tag { font-weight: 600; min-width: 4rem; }
.duration { color: var(--text); font-variant-numeric: tabular-nums; }
.when { margin-left: auto; }
.done { color: #22c55e; }
</style>
