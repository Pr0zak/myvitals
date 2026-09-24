<script setup lang="ts">
/**
 * Sober time (UI-6). Milestones, the ring fill and the next milestone come
 * from `/sober/current`; the only local arithmetic is the seconds ticker from
 * the server's start instant and the countdown to `next_milestone_at`.
 *
 * The reset is deliberately quiet — an outlined bar below the history, with a
 * faint periwinkle hold fill. It used to be a red button: colouring a reset
 * as a warning is the one thing this screen must not do.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Pencil, Trash2, X, Check } from "lucide-vue-next";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";

interface Streak {
  id: number;
  addiction: string;
  start_at: string;
  end_at: string | null;
  notes: string | null;
  days: number;
}

const MAG = "#ff3ad8";
const current = ref<Awaited<ReturnType<typeof api.soberCurrent>> | null>(null);
const history = ref<Streak[]>([]);
const stats = ref<Awaited<ReturnType<typeof api.soberStats>> | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const actionError = ref<string | null>(null);

const tick = ref(Date.now());
let tickHandle: ReturnType<typeof setInterval> | null = null;

/** h/m/s since the server's start instant — the day count is the server's. */
const ticker = computed(() => {
  const a = current.value?.active;
  if (!a) return null;
  const totalS = Math.max(0, Math.floor((tick.value - new Date(a.start_at).getTime()) / 1000));
  return {
    h: Math.floor((totalS % 86400) / 3600),
    m: Math.floor((totalS % 3600) / 60),
    s: totalS % 60,
    d: Math.floor(totalS / 86400),
  };
});

const dots = computed(() => {
  const ms = current.value?.milestones ?? [];
  const reached = current.value?.milestones_reached ?? 0;
  return ms.map((_, i) => ({ at: (i + 1) / ms.length, reached: i < reached }));
});

function fmtCountdown(sec: number): string {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
const nextPill = computed(() => {
  const c = current.value;
  if (!c?.active || c.next_milestone_days == null || !c.next_milestone_at) return null;
  const left = Math.max(0, Math.floor((new Date(c.next_milestone_at).getTime() - tick.value) / 1000));
  return `Next · ${c.next_milestone_days} days in ${fmtCountdown(left)}`;
});

// Bars: newest first, every streak, current full-opacity.
const bars = computed(() => [...history.value].sort((a, b) => b.start_at.localeCompare(a.start_at)).slice(0, 12));
const longest = computed(() => Math.max(0.01, ...bars.value.map((s) => s.days)));

async function load() {
  error.value = null;
  try {
    [current.value, history.value, stats.value] = await Promise.all([
      api.soberCurrent(),
      api.soberHistory(500),
      api.soberStats(),
    ]);
  } catch (e) {
    // A failed request is never "no active streak": keep what we had.
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

useVisibilityRefresh(() => { load(); });
onMounted(() => {
  load();
  tickHandle = setInterval(() => {
    tick.value = Date.now();
    // Server owns the day count: when the ticker rolls into a new day, ask.
    const t = ticker.value;
    if (t && current.value?.days != null && t.d > current.value.days) load();
  }, 1000);
});
onUnmounted(() => { if (tickHandle) clearInterval(tickHandle); stopHold(); });

// ── Reset (press & hold) ──────────────────────────────────────
const HOLD_MS = 1500;
const resetting = ref(false);
const hold = ref(0);
let holdStart = 0;
let holdRaf: number | null = null;
function stopHold() {
  if (holdRaf != null) cancelAnimationFrame(holdRaf);
  holdRaf = null;
  hold.value = 0;
}
function startHold() {
  if (resetting.value) return;
  holdStart = performance.now();
  const step = () => {
    hold.value = Math.min(1, (performance.now() - holdStart) / HOLD_MS);
    if (hold.value >= 1) { stopHold(); doReset(); return; }
    holdRaf = requestAnimationFrame(step);
  };
  holdRaf = requestAnimationFrame(step);
}
async function doReset() {
  resetting.value = true;
  actionError.value = null;
  try {
    await api.soberReset();
    await load();
  } catch (e) {
    actionError.value = "Reset didn't go through: " + (e instanceof Error ? e.message : "error");
  } finally {
    resetting.value = false;
  }
}
/** Keyboard users can't press-and-hold; they get a confirm instead. */
function keyReset() {
  if (confirm("Reset the sober timer? This closes the current streak and starts a new one from now.")) doReset();
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
  editing.value = { id: s.id, start: toLocal(s.start_at), end: toLocal(s.end_at), notes: s.notes ?? "", isCurrent: s.end_at === null };
}
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
    actionError.value = e instanceof Error ? e.message : "Save failed";
  }
}
async function removeStreak(s: Streak) {
  if (!confirm(`Delete this ${s.days.toFixed(1)}-day streak?`)) return;
  try {
    await api.soberDelete(s.id);
    await load();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : "Delete failed";
  }
}
</script>

<template>
  <NeonPage title="Sober" back="/you">
    <p v-if="error && current" class="stale">Showing the last streak we loaded — refresh failed.</p>

    <!-- Failed with nothing loaded: say so. Never the "no streak" state. -->
    <button v-if="!current && error" class="fail" type="button" @click="load">
      <strong>Couldn't load your streak</strong>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>

    <NeonHero v-else :accent="MAG">
      <div class="hero">
        <NeonRing :fraction="current?.active ? (current.milestone_progress ?? 0) : 0" :color="MAG"
                  :size="260" :stroke="12" :dots="current?.active ? dots : []">
          <template v-if="loading && !current">
            <span class="muted">Loading your streak…</span>
          </template>
          <template v-else-if="current?.active">
            <span class="days">{{ current.days ?? 0 }}</span>
            <span class="cap">{{ current.days === 1 ? "day sober" : "days sober" }}</span>
            <span v-if="ticker" class="tick">
              {{ ticker.h }}<i>h</i> {{ String(ticker.m).padStart(2, "0") }}<i>m</i>
              {{ String(ticker.s).padStart(2, "0") }}<i>s</i>
            </span>
          </template>
          <template v-else>
            <span class="days zero">0</span>
            <span class="cap">no active streak</span>
          </template>
        </NeonRing>
        <span v-if="nextPill" class="pill">{{ nextPill }}</span>
        <span v-if="current?.active" class="since">since {{ fmtDateTime(current.active.start_at) }}</span>
        <span v-else-if="current" class="since">Start counting from now, or edit a start date below.</span>
      </div>
    </NeonHero>

    <template v-if="stats && stats.total_tracked_days > 0">
      <NeonEyebrow>All time</NeonEyebrow>
      <div class="grid2">
        <NeonStat :value="`${stats.longest_days.toFixed(1)}d`" label="longest" :accent="MAG" />
        <NeonStat :value="`${stats.avg_days.toFixed(1)}d`" label="average" />
        <NeonStat :value="String(stats.total_resets)" label="resets" />
        <NeonStat :value="`${stats.total_tracked_days.toFixed(0)}d`" label="tracked" />
      </div>
    </template>

    <template v-if="bars.length">
      <NeonEyebrow>Streaks</NeonEyebrow>
      <ul class="bars">
        <template v-for="s in bars" :key="s.id">
          <li v-if="editing?.id !== s.id" :class="{ now: s.end_at === null }">
            <div class="bar-head">
              <span class="when">
                {{ s.end_at === null ? "Now · since" : "from" }} {{ new Date(s.start_at).toLocaleDateString() }}
                <template v-if="s.end_at"> → {{ new Date(s.end_at).toLocaleDateString() }}</template>
              </span>
              <span class="len">{{ s.days.toFixed(1) }} d</span>
              <button class="icon-btn" title="Edit" @click="startEdit(s)"><Pencil :size="13" /></button>
              <button class="icon-btn" title="Delete" @click="removeStreak(s)"><Trash2 :size="13" /></button>
            </div>
            <div class="track"><div class="fill" :style="{ width: Math.max(2, (s.days / longest) * 100) + '%' }" /></div>
            <div v-if="s.notes" class="notes">{{ s.notes }}</div>
          </li>
          <li v-else class="editing">
            <form class="edit-grid" @submit.prevent="saveEdit">
              <label><span>start</span><input v-model="editing.start" type="datetime-local" step="60" /></label>
              <label v-if="!editing.isCurrent"><span>end</span><input v-model="editing.end" type="datetime-local" step="60" /></label>
              <label class="full"><span>notes</span><input v-model="editing.notes" placeholder="optional" /></label>
              <div class="edit-actions">
                <button type="submit" class="primary"><Check :size="14" /> Save</button>
                <button type="button" class="ghost" @click="editing = null"><X :size="14" /> Cancel</button>
              </div>
            </form>
          </li>
        </template>
      </ul>
      <p v-if="history.length > bars.length" class="muted small">+{{ history.length - bars.length }} older</p>
    </template>

    <template v-if="current">
      <button v-if="current.active" type="button" class="reset" :disabled="resetting"
              @pointerdown.prevent="startHold" @pointerup="stopHold" @pointerleave="stopHold" @pointercancel="stopHold"
              @keydown.enter.prevent="keyReset" @keydown.space.prevent="keyReset">
        <span class="hold" :style="{ width: hold * 100 + '%' }" />
        <span class="lbl">{{ resetting ? "Resetting…" : hold > 0 ? "Keep holding…" : "Press & hold to reset" }}</span>
      </button>
      <button v-else type="button" class="reset start" :disabled="resetting" @click="doReset">
        <span class="lbl">{{ resetting ? "Starting…" : "Start counting" }}</span>
      </button>
    </template>
    <p v-if="actionError" class="muted small center">{{ actionError }}</p>
  </NeonPage>
</template>

<style scoped>
.hero { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.days { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 76px; color: #ff3ad8; letter-spacing: -2px; line-height: 1; }
.days.zero { color: var(--rn-mut); font-size: 64px; }
.cap { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); }
.tick { margin-top: 6px; font-family: 'Space Grotesk', monospace; font-size: 16px; color: rgba(236, 236, 245, .85); }
.tick i { font-style: normal; font-size: 11px; color: var(--rn-mut); margin: 0 3px 0 1px; }
.pill { font-size: 12px; font-weight: 600; color: #ff3ad8; padding: 6px 12px; border-radius: 22px;
  background: rgba(255, 58, 216, .12); border: 1px solid rgba(255, 58, 216, .35); }
.since { font-size: 12px; color: var(--rn-mut); text-align: center; }
.muted { color: var(--rn-mut); }
.small { font-size: 12px; }
.center { text-align: center; }
.stale { font-size: 11px; color: var(--rn-mut); margin: 0 0 8px; }
.fail { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 181, 46, .08); border: 1px solid rgba(255, 181, 46, .3); border-radius: 14px; padding: 12px 14px;
  color: var(--rn-mut); font: inherit; font-size: 12px; margin-bottom: 12px; }
.fail strong { color: #ffb52e; font-size: 13px; }
.fail em { font-style: normal; color: #28e6ff; font-weight: 600; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.bars { list-style: none; margin: 0; padding: 14px; background: var(--rn-card); border: 1px solid var(--rn-line);
  border-radius: 18px; display: flex; flex-direction: column; gap: 12px; }
.bar-head { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--rn-mut); }
.when { flex: 1; min-width: 0; }
.len { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 13px; color: rgba(236, 236, 245, .6); }
.now .len { color: var(--rn-ink); }
.track { height: 8px; border-radius: 4px; background: var(--rn-track); margin-top: 4px; overflow: hidden; }
.fill { height: 100%; border-radius: 4px; background: #ff3ad8; opacity: .6; }
.now .fill { opacity: 1; }
.notes { font-size: 11px; color: var(--rn-mut); margin-top: 3px; }
.icon-btn { background: transparent; border: 0; color: var(--rn-mut); cursor: pointer; padding: 4px; min-width: 28px; min-height: 28px;
  display: inline-flex; align-items: center; justify-content: center; opacity: .6; }
.icon-btn:hover { opacity: 1; color: var(--rn-ink); }
.reset { position: relative; overflow: hidden; width: 100%; height: 56px; margin-top: 20px; border-radius: 16px;
  border: 1px solid var(--rn-line); background: transparent; cursor: pointer; font: inherit; touch-action: none; user-select: none; }
.reset.start { border-color: rgba(255, 58, 216, .45); }
.reset:disabled { cursor: default; }
.reset .hold { position: absolute; inset: 0 auto 0 0; background: rgba(111, 123, 255, .30); }
.reset .lbl { position: relative; color: var(--rn-mut); font-size: 15px; font-weight: 500; }
.reset.start .lbl { color: var(--rn-ink); font-weight: 600; }
.reset:focus-visible { outline: 2px solid #28e6ff; outline-offset: 2px; }
.editing { list-style: none; }
.edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.edit-grid label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--rn-mut); text-transform: uppercase; letter-spacing: .05em; }
.edit-grid label.full { grid-column: 1 / -1; }
.edit-grid input { background: var(--rn-bg); color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 8px; padding: 8px; font: inherit; font-size: 14px; }
.edit-actions { grid-column: 1 / -1; display: flex; gap: 8px; justify-content: flex-end; }
.edit-actions button { display: inline-flex; align-items: center; gap: 4px; border-radius: 8px; padding: 8px 14px; cursor: pointer; font: inherit; }
.edit-actions .primary { background: #ff3ad8; color: var(--rn-onacc); border: 0; font-weight: 600; }
.edit-actions .ghost { background: transparent; color: var(--rn-mut); border: 1px solid var(--rn-line); }
</style>
