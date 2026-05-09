<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import VChart from "vue-echarts";
import { Pencil, Trash2, X, Check, RotateCcw, Award, Calendar as CalIcon, TrendingUp } from "lucide-vue-next";
import Card from "@/components/Card.vue";
import Skeleton from "@/components/Skeleton.vue";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import { chartTheme } from "@/theme";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";

interface Streak {
  id: number;
  addiction: string;
  start_at: string;
  end_at: string | null;
  notes: string | null;
  days: number;
}

const current = ref<Awaited<ReturnType<typeof api.soberCurrent>> | null>(null);
const history = ref<Streak[]>([]);
const stats = ref<Awaited<ReturnType<typeof api.soberStats>> | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

// Live ticker — updates every second so the counter doesn't feel frozen.
const tick = ref(Date.now());
let tickHandle: ReturnType<typeof setInterval> | null = null;

const liveCounter = computed(() => {
  if (!current.value?.active) return null;
  const startMs = new Date(current.value.active.start_at).getTime();
  const elapsedMs = tick.value - startMs;
  if (elapsedMs < 0) return { d: 0, h: 0, m: 0, s: 0 };
  const totalS = Math.floor(elapsedMs / 1000);
  const d = Math.floor(totalS / 86400);
  const h = Math.floor((totalS % 86400) / 3600);
  const m = Math.floor((totalS % 3600) / 60);
  const s = totalS % 60;
  return { d, h, m, s };
});

const startedAtLabel = computed(() => {
  if (!current.value?.active) return "—";
  return fmtDateTime(current.value.active.start_at);
});

// Milestone ring: progress to the next round-number milestone. Caps
// once the user passes the last milestone (730d) — the ring fills.
const MILESTONES = [7, 14, 30, 60, 90, 180, 365, 730];
const milestone = computed(() => {
  if (!liveCounter.value) return null;
  const elapsedDays = liveCounter.value.d
    + liveCounter.value.h / 24
    + liveCounter.value.m / 1440;
  const next = MILESTONES.find((m) => m > elapsedDays);
  if (next == null) {
    return { current: elapsedDays, target: 730, fraction: 1, label: "All milestones cleared", remaining: 0 };
  }
  const prev = [...MILESTONES].reverse().find((m) => m <= elapsedDays) ?? 0;
  const fraction = Math.max(0, Math.min(1, (elapsedDays - prev) / (next - prev)));
  return {
    current: elapsedDays,
    target: next,
    fraction,
    label: `Next: ${next}-day milestone`,
    remaining: Math.max(0, next - elapsedDays),
  };
});

async function load() {
  loading.value = true;
  error.value = null;
  try {
    [current.value, history.value, stats.value] = await Promise.all([
      api.soberCurrent(),
      api.soberHistory(500),
      api.soberStats(),
    ]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

useVisibilityRefresh(() => { load(); });
onMounted(() => {
  load();
  tickHandle = setInterval(() => { tick.value = Date.now(); }, 1000);
});
onUnmounted(() => { if (tickHandle) clearInterval(tickHandle); });

// ── Reset ─────────────────────────────────────────────────────
const resetting = ref(false);
async function resetTimer() {
  if (!confirm("Reset the sober timer? This closes the current streak and starts a new one from now.")) return;
  resetting.value = true;
  try {
    await api.soberReset();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Reset failed";
  } finally {
    resetting.value = false;
  }
}

// ── Edit / delete in history ──────────────────────────────────
type EditDraft = { id: number; start: string; end: string; notes: string; isCurrent: boolean };
const editing = ref<EditDraft | null>(null);

function toLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocal(s: string): string | null {
  if (!s) return null;
  return new Date(s).toISOString();
}

function startEdit(s: Streak) {
  editing.value = {
    id: s.id,
    start: toLocal(s.start_at),
    end: toLocal(s.end_at),
    notes: s.notes ?? "",
    isCurrent: s.end_at === null,
  };
}
function cancelEdit() { editing.value = null; }
async function saveEdit() {
  if (!editing.value) return;
  try {
    await api.soberUpdate(editing.value.id, {
      start_at: fromLocal(editing.value.start) ?? undefined,
      end_at: editing.value.isCurrent ? null : fromLocal(editing.value.end),
      notes: editing.value.notes || null,
    });
    editing.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Save failed";
  }
}
async function removeStreak(s: Streak) {
  if (!confirm(`Delete this ${s.days.toFixed(1)}-day streak?`)) return;
  try {
    await api.soberDelete(s.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Delete failed";
  }
}

// ── Charts ────────────────────────────────────────────────────
const histogramOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!history.value.length) return null;
  // Bucket streak durations: 0-1, 1-3, 3-7, 7-14, 14-30, 30-60, 60-90, 90+
  const buckets = [
    { label: "<1d", lo: 0, hi: 1 },
    { label: "1-3d", lo: 1, hi: 3 },
    { label: "3-7d", lo: 3, hi: 7 },
    { label: "1-2w", lo: 7, hi: 14 },
    { label: "2-4w", lo: 14, hi: 30 },
    { label: "1-2mo", lo: 30, hi: 60 },
    { label: "2-3mo", lo: 60, hi: 90 },
    { label: "3mo+", lo: 90, hi: Infinity },
  ];
  const counts = buckets.map((b) =>
    history.value.filter((s) => s.days >= b.lo && s.days < b.hi).length
  );
  return {
    grid: { left: 36, right: 12, top: 16, bottom: 28 },
    tooltip: { ...t.tooltip },
    xAxis: {
      type: "category",
      data: buckets.map((b) => b.label),
      axisLabel: t.axisLabel, axisLine: { lineStyle: { color: t.splitLine.lineStyle.color } },
    },
    yAxis: {
      type: "value",
      axisLabel: t.axisLabel, splitLine: t.splitLine,
    },
    series: [{
      type: "bar",
      data: counts,
      itemStyle: { color: t.palette.accent, borderRadius: [4, 4, 0, 0] },
    }],
  };
});

const timelineOption = computed(() => {
  void chartTheme.value;
  const t = chartTheme.value;
  if (!history.value.length) return null;
  // Sort ascending by start_at, plot duration of each streak as a step line over time.
  const sorted = [...history.value].sort((a, b) => a.start_at.localeCompare(b.start_at));
  const points = sorted.map((s) => [s.start_at, +s.days.toFixed(2)]);
  return {
    grid: { left: 50, right: 14, top: 18, bottom: 36 },
    tooltip: { ...t.tooltip, trigger: "axis" },
    xAxis: { type: "time", axisLabel: t.axisLabel, splitLine: t.splitLine },
    yAxis: { type: "value", name: "days", nameTextStyle: t.axisLabel, axisLabel: t.axisLabel, splitLine: t.splitLine },
    series: [{
      type: "scatter",
      data: points,
      symbolSize: (val: [string, number]) => Math.min(20, 4 + Math.sqrt(val[1])),
      itemStyle: { color: "#22c55e", opacity: 0.7 },
    }],
  };
});
</script>

<template>
  <div class="sober">
    <h1>Sober time</h1>
    <p class="hint">Tap reset whenever a slip happens. Past streaks stay in your history so you can see progress over time.</p>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="skel-stack">
      <Skeleton width="100%" height="120px" radius="12px"/>
      <Skeleton width="100%" height="80px" radius="12px"/>
    </div>

    <template v-else>
      <!-- ────── Big live counter ────── -->
      <Card flat>
        <div class="counter-card">
          <div v-if="liveCounter" class="counter">
            <!-- Milestone ring wraps the counter; SVG circle stroke
                 advances clockwise from 12 o'clock to the next
                 milestone target. -->
            <div class="ring-wrap">
              <svg class="ring" viewBox="0 0 120 120" aria-hidden="true">
                <circle class="ring-bg" cx="60" cy="60" r="54"/>
                <circle class="ring-fg" cx="60" cy="60" r="54"
                        :stroke-dasharray="2 * Math.PI * 54"
                        :stroke-dashoffset="(2 * Math.PI * 54) * (1 - (milestone?.fraction ?? 0))"/>
              </svg>
              <div class="ring-content">
                <div class="counter-num">
                  <span class="d">{{ liveCounter.d }}</span><span class="lbl">d</span>
                  <span class="h">{{ String(liveCounter.h).padStart(2, '0') }}</span><span class="lbl">h</span>
                  <span class="m">{{ String(liveCounter.m).padStart(2, '0') }}</span><span class="lbl">m</span>
                  <span class="s mono">{{ String(liveCounter.s).padStart(2, '0') }}</span>
                </div>
                <div v-if="milestone" class="counter-milestone">
                  {{ milestone.remaining > 0
                     ? `${milestone.remaining.toFixed(1)} d to ${milestone.target}d milestone`
                     : milestone.label }}
                </div>
              </div>
            </div>
            <div class="counter-since">since {{ startedAtLabel }}</div>
          </div>
          <div v-else class="counter-empty">
            <p>No active streak yet. Tap <strong>Start streak</strong> to begin tracking.</p>
          </div>
          <button class="reset-btn" :disabled="resetting" @click="resetTimer">
            <RotateCcw :size="14"/>
            {{ liveCounter ? (resetting ? "Resetting…" : "Reset") : "Start streak" }}
          </button>
        </div>
      </Card>

      <!-- ────── Stats row ────── -->
      <div v-if="stats" class="stats-grid">
        <Card flat>
          <div class="stat-tile">
            <div class="stat-icon" style="color: #fbbf24"><Award :size="18"/></div>
            <div class="stat-num">{{ stats.longest_days.toFixed(1) }}<span class="unit">d</span></div>
            <div class="stat-lbl">Longest streak</div>
          </div>
        </Card>
        <Card flat>
          <div class="stat-tile">
            <div class="stat-icon" style="color: #38bdf8"><TrendingUp :size="18"/></div>
            <div class="stat-num">{{ stats.avg_days.toFixed(1) }}<span class="unit">d</span></div>
            <div class="stat-lbl">Avg streak</div>
          </div>
        </Card>
        <Card flat>
          <div class="stat-tile">
            <div class="stat-icon" style="color: #ef4444"><RotateCcw :size="18"/></div>
            <div class="stat-num">{{ stats.total_resets }}</div>
            <div class="stat-lbl">Total resets</div>
          </div>
        </Card>
        <Card flat>
          <div class="stat-tile">
            <div class="stat-icon" style="color: #a78bfa"><CalIcon :size="18"/></div>
            <div class="stat-num">{{ stats.total_tracked_days.toFixed(0) }}<span class="unit">d</span></div>
            <div class="stat-lbl">Total tracked</div>
          </div>
        </Card>
      </div>

      <!-- ────── Charts ────── -->
      <div class="charts-grid">
        <Card title="Streak distribution">
          <div class="chart">
            <VChart v-if="histogramOption" :option="histogramOption" autoresize/>
            <div v-else class="empty">Not enough history yet.</div>
          </div>
        </Card>
        <Card title="Streak length over time">
          <div class="chart">
            <VChart v-if="timelineOption" :option="timelineOption" autoresize/>
            <div v-else class="empty">Not enough history yet.</div>
          </div>
        </Card>
      </div>

      <!-- ────── Editable history list ────── -->
      <Card :title="`History · ${history.length} streaks`">
        <ul class="history">
          <template v-for="s in history" :key="s.id">
            <li v-if="editing?.id !== s.id" class="srow" :class="{ active: s.end_at === null }">
              <span class="srow-when">
                {{ new Date(s.start_at).toLocaleDateString() }}
                <span v-if="s.end_at" class="muted">→ {{ new Date(s.end_at).toLocaleDateString() }}</span>
              </span>
              <span class="srow-days">
                {{ s.days.toFixed(1) }} days
                <span v-if="s.end_at === null" class="active-pill">active</span>
              </span>
              <span v-if="s.notes" class="srow-notes">{{ s.notes }}</span>
              <span class="srow-actions">
                <button class="icon-btn" @click="startEdit(s)" title="Edit"><Pencil :size="14"/></button>
                <button class="icon-btn danger" @click="removeStreak(s)" title="Delete"><Trash2 :size="14"/></button>
              </span>
            </li>
            <li v-else class="srow editing">
              <form class="edit-grid" @submit.prevent="saveEdit">
                <label>
                  <span>start</span>
                  <input v-model="editing.start" type="datetime-local" step="60"/>
                </label>
                <label v-if="!editing.isCurrent">
                  <span>end</span>
                  <input v-model="editing.end" type="datetime-local" step="60"/>
                </label>
                <label class="full">
                  <span>notes</span>
                  <input v-model="editing.notes" placeholder="optional"/>
                </label>
                <div class="edit-actions">
                  <button type="submit" class="primary"><Check :size="14"/> Save</button>
                  <button type="button" class="ghost" @click="cancelEdit"><X :size="14"/> Cancel</button>
                </div>
              </form>
            </li>
          </template>
          <li v-if="history.length === 0" class="empty">No streaks yet.</li>
        </ul>
      </Card>
    </template>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 1.2rem; }
.loading { color: var(--muted); padding: 2rem 0; text-align: center; }
.skel-stack { display: flex; flex-direction: column; gap: 0.6rem; margin: 1rem 0; }
.err {
  color: var(--bad); padding: 0.6rem 0.8rem;
  background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad);
  margin: 0.6rem 0;
}

/* ── Big counter ── */
.counter-card {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 1rem;
}
.counter { display: flex; flex-direction: column; gap: 0.4rem; }
.counter-num {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 2.4rem; font-weight: 600; letter-spacing: -0.02em;
  color: #22c55e;
  display: flex; align-items: baseline; gap: 0.15rem;
}
.counter-num .d { color: #22c55e; }
.counter-num .h { color: #86efac; }
.counter-num .m { color: #a7f3d0; }
.counter-num .s { color: var(--muted-2); font-size: 1.6rem; margin-left: 0.4rem; }
.counter-num .lbl {
  font-size: 0.8rem; color: var(--muted-2); font-family: 'Geist', sans-serif;
  font-weight: 500; margin: 0 0.5rem 0 0.05rem; align-self: center;
}
.counter-since { color: var(--muted); font-size: 0.85rem; }
.counter-milestone { color: var(--muted); font-size: 0.78rem; margin-top: 0.2rem; }
/* Milestone ring: SVG circle whose stroke advances clockwise toward
   the next round-number milestone (7/14/30/60/90/180/365/730 days). */
.ring-wrap {
  position: relative;
  width: 240px; height: 240px;
  display: flex; align-items: center; justify-content: center;
}
.ring {
  position: absolute; inset: 0;
  transform: rotate(-90deg);  /* start arc at 12 o'clock */
}
.ring-bg {
  fill: none; stroke: rgba(34, 197, 94, 0.10); stroke-width: 6;
}
.ring-fg {
  fill: none; stroke: #22c55e; stroke-width: 6;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s ease-out;
}
.ring-content {
  position: relative; z-index: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.3rem;
  text-align: center;
}
.ring-content .counter-num { font-size: 1.8rem; }
.ring-content .counter-num .s { font-size: 1.1rem; }
.counter-empty p { margin: 0; color: var(--muted); }
.reset-btn {
  background: rgba(239, 68, 68, 0.08); color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 8px;
  padding: 0.6rem 1.1rem; cursor: pointer; font-weight: 600;
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: inherit; font-size: 0.9rem;
}
.reset-btn:hover { background: rgba(239, 68, 68, 0.15); }
.reset-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Stat tiles ── */
.stats-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.7rem; margin: 1rem 0;
}
.stat-tile {
  display: flex; flex-direction: column; gap: 0.2rem;
  padding: 0.4rem 0;
}
.stat-icon { display: inline-flex; }
.stat-num {
  font-size: 1.6rem; font-weight: 600; color: var(--text);
  font-family: 'Geist Mono', ui-monospace, monospace;
  letter-spacing: -0.02em;
}
.stat-num .unit {
  font-size: 0.85rem; color: var(--muted-2); margin-left: 0.15rem;
}
.stat-lbl {
  color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: 600;
}

/* ── Charts ── */
.charts-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 0.7rem;
}
.chart { width: 100%; height: 220px; }
.chart > * { width: 100%; height: 100%; }
.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }

/* ── History list ── */
.history { list-style: none; padding: 0; margin: 0; }
.srow {
  display: grid;
  grid-template-columns: 200px 130px 1fr auto;
  gap: 0.6rem; align-items: center;
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  font-size: 0.85rem;
}
.srow.active { background: rgba(34, 197, 94, 0.04); border-radius: 6px; padding-left: 0.5rem; }
.srow-when { color: var(--text-soft); font-family: 'Geist Mono', ui-monospace, monospace; }
.srow-when .muted { color: var(--muted); }
.srow-days {
  color: var(--text); font-weight: 500;
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.active-pill {
  background: rgba(34, 197, 94, 0.15); color: #22c55e;
  font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; padding: 0.1rem 0.45rem; border-radius: 3px;
}
.srow-notes { color: var(--muted); font-size: 0.78rem; }
.srow-actions { display: flex; gap: 0.2rem; opacity: 0.4; transition: opacity 0.15s; }
.srow:hover .srow-actions { opacity: 1; }
.icon-btn {
  background: transparent; border: 1px solid transparent;
  border-radius: 6px; padding: 0.25rem; cursor: pointer; color: var(--muted);
  display: inline-flex; align-items: center; justify-content: center;
}
.icon-btn:hover { color: var(--text); border-color: var(--border); }
.icon-btn.danger:hover { color: #ef4444; border-color: rgba(239, 68, 68, 0.3); }

.srow.editing { display: block; }
.edit-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.5rem; padding: 0.4rem;
}
.edit-grid label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.edit-grid label.full { grid-column: 1 / -1; }
.edit-grid input {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.45rem 0.55rem; font-size: 0.9rem; font-family: inherit;
}
.edit-actions { grid-column: 1 / -1; display: flex; gap: 0.5rem; justify-content: flex-end; }
.edit-actions .primary {
  background: var(--accent); color: var(--accent-text);
  border: 0; border-radius: 6px; padding: 0.45rem 0.85rem;
  display: inline-flex; align-items: center; gap: 0.3rem; cursor: pointer; font-weight: 600;
}
.edit-actions .ghost {
  background: transparent; color: var(--muted); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.45rem 0.85rem;
  display: inline-flex; align-items: center; gap: 0.3rem; cursor: pointer;
}
</style>
