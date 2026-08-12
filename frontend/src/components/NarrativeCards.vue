<script setup lang="ts">
/**
 * Narrative event cards — web twin of `ui/common/NarrativeCards.kt`.
 *
 * Structured after the reference:
 *   ☾ 6:29 AM              icon + timestamp, not a pill
 *   Sleep tracked          headline
 *   [Sleep score 88 Good] [Sleep duration 8h 28m Goal met]
 *                          nested stat cards, each with its own chip
 *   hypnogram              one lane per stage, CONNECTED
 *   👍 👎              ⋮   feedback left, overflow right
 *
 * The hypnogram is one lane per stage, each segment a rounded tab placed by
 * WHEN it happened. An earlier version drew hairlines between lanes to join
 * the stages; at a real night's density they stacked into heavy grey bars
 * that were louder than the stages themselves, so they are gone.
 *
 * All wording, classification and the stat chips come from
 * `/summary/events` — see analytics/events.py.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { NarrativeEvent } from "@/api/types";

const events = ref<NarrativeEvent[]>([]);
const loaded = ref(false);
const menuFor = ref<string | null>(null);

const LANES = ["awake", "rem", "light", "deep"] as const;
const LANE_LABEL: Record<string, string> = {
  awake: "Total awake", rem: "REM", light: "Light", deep: "Deep",
  asleep: "Asleep", restless: "Restless", out_of_bed: "Out of bed",
  unmeasurable: "Unmeasurable", unknown: "Unknown",
};
const LANE_TONE: Record<string, string> = {
  awake: "#f48fb1", rem: "#8fd8ff", light: "#7aa7ff", deep: "#a97bdb",
};

async function load() {
  try {
    events.value = (await api.summaryEvents()).events ?? [];
  } catch {
    events.value = [];
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

/** Toggling an active vote clears it — tapping 👍 twice should undo. */
async function vote(e: NarrativeEvent, v: "up" | "down") {
  const prev = e.feedback ?? null;
  const next = prev === v ? null : v;
  e.feedback = next;
  try {
    await api.eventFeedback(e.id, next);
  } catch {
    e.feedback = prev;
  }
}

function mins(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
}

function clock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** The midpoint label the reference puts between start and end. */
function midClock(e: NarrativeEvent): string {
  const a = new Date(e.start).getTime();
  const b = new Date(e.end).getTime();
  return clock(new Date((a + b) / 2).toISOString());
}

/** Header timestamp: the moment the session ENDED, which is when the card
 *  would have appeared. Days other than today are named. */
function stamp(e: NarrativeEvent): string {
  const d = new Date(e.end);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const yesterday = new Date(today.getTime() - 86_400_000).toDateString()
    === d.toDateString();
  const t = clock(e.end);
  if (sameDay) return t;
  if (yesterday) return `Yesterday, ${t}`;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${t}`;
}

/** True once we cross from today's cards into an earlier day, so a
 *  separator can be drawn — the reference's "〰 Yesterday 〰" rule. */
function dayBreakBefore(i: number): string | null {
  if (i === 0) return null;
  const prev = new Date(events.value[i - 1].end).toDateString();
  const cur = new Date(events.value[i].end).toDateString();
  if (prev === cur) return null;
  const today = new Date().toDateString();
  const yest = new Date(Date.now() - 86_400_000).toDateString();
  if (cur === today) return "Today";
  if (cur === yest) return "Yesterday";
  return new Date(events.value[i].end)
    .toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const LANE_H = 26;

/** Geometry for one lane: rounded tabs positioned by time. */
function lane(e: NarrativeEvent, stage: string) {
  const t0 = new Date(e.start).getTime();
  const span = new Date(e.end).getTime() - t0;
  if (span <= 0) return [];
  return e.segments
    .filter((s) => s.stage === stage)
    .map((s) => {
      const left = ((new Date(s.start).getTime() - t0) / span) * 100;
      const width = ((s.duration_s * 1000) / span) * 100;
      return {
        left: `${Math.max(0, Math.min(100, left))}%`,
        // Floor the width so a 30-second stage stays visible instead of
        // collapsing to an invisible sliver.
        width: `${Math.max(1.2, Math.min(100 - left, width))}%`,
      };
    });
}

function lanesFor(e: NarrativeEvent) {
  const seen = new Set(e.stages.map((s) => s.stage));
  // Render whatever the server sent, known stages first. Filtering to a fixed
  // four dropped Fitbit's classic levels (asleep / restless) entirely, so a
  // night recorded in that vocabulary drew an empty hypnogram under a headline
  // that said you slept eight hours.
  const order = [...LANES.filter((l) => seen.has(l) || l === "awake"),
                 ...[...seen].filter((s) => !LANES.includes(s as never)).sort()];
  return order.map((l) => ({
    stage: l,
    label: LANE_LABEL[l] ?? l,
    total: e.stages.find((s) => s.stage === l)?.duration_s ?? 0,
    bars: lane(e, l),
    tone: LANE_TONE[l] ?? "#8d949d",
  }));
}


const shown = computed(() => events.value);
</script>

<template>
  <section v-if="loaded && shown.length" class="nc">
    <template v-for="(e, i) in shown" :key="e.id">
      <div v-if="dayBreakBefore(i)" class="daybreak">
        <span class="wave" />
        <span class="dlabel">{{ dayBreakBefore(i) }}</span>
        <span class="wave" />
      </div>

      <article class="card">
        <div class="stamp">
          <svg class="moon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
          </svg>
          <span>{{ stamp(e) }}</span>
        </div>

        <h3 class="head">{{ e.headline }}</h3>
        <p v-if="e.kind === 'nap'" class="detail">{{ e.detail }}</p>

        <!-- Nested stat cards. A nap has none: it isn't scored and has no
             goal, and a zero there would read as a bad night. -->
        <div v-if="e.stats?.length" class="stats">
          <div v-for="s in e.stats" :key="s.label" class="stat">
            <div class="slabel">{{ s.label }}</div>
            <div class="svalue num">{{ s.value }}</div>
            <span class="schip" :class="s.tone">{{ s.chip }}</span>
          </div>
        </div>

        <div class="hypno">
          <div class="lanes">
          <div v-for="l in lanesFor(e)" :key="l.stage" class="lane">
            <div class="llabel">
              {{ l.label }} <span class="ldur">• {{ mins(l.total) }}</span>
            </div>
            <div class="track">
              <span
                v-for="(b, bi) in l.bars" :key="bi" class="seg"
                :style="{ left: b.left, width: b.width, background: l.tone }"
              />
            </div>
          </div>
          </div>

          <div class="axis">
            <span>{{ clock(e.start) }}</span>
            <span>{{ midClock(e) }}</span>
            <span>{{ clock(e.end) }}</span>
          </div>
        </div>

        <div class="actions">
          <button
            class="thumb" :class="{ on: e.feedback === 'up' }"
            :aria-pressed="e.feedback === 'up'"
            aria-label="This looks right" @click="vote(e, 'up')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M7 22H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1h3zM7 12l4.5-8a2.5 2.5 0 0 1 3.4 3.3L13.5 10H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 21H7z" />
            </svg>
          </button>
          <button
            class="thumb" :class="{ on: e.feedback === 'down' }"
            :aria-pressed="e.feedback === 'down'"
            aria-label="This looks wrong" @click="vote(e, 'down')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17 2h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3zM17 12l-4.5 8a2.5 2.5 0 0 1-3.4-3.3L10.5 14H5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.2 3H17z" />
            </svg>
          </button>

          <div class="spacer" />

          <button
            class="more" aria-label="More"
            @click="menuFor = menuFor === e.id ? null : e.id"
          >⋮</button>
        </div>

        <!-- Only actions that actually exist. A menu that opens onto
             nothing is worse than no menu. -->
        <div v-if="menuFor === e.id" class="menu">
          <RouterLink class="mitem" to="/sleep">Open sleep detail</RouterLink>
        </div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.nc { margin: 18px 0; display: flex; flex-direction: column; gap: 12px; }
.card { background: #1b1c1f; border-radius: 20px; padding: 16px; }

.stamp {
  display: flex; align-items: center; gap: 7px;
  font-size: .78rem; color: #b9bec6; margin-bottom: 8px;
}
.moon { width: 15px; height: 15px; color: #b39ddb; flex: none; }

.head {
  font-size: 1.3rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 4px; letter-spacing: -0.2px;
}
.detail { font-size: .84rem; color: #b9bec6; margin: 0 0 12px; line-height: 1.35; }

.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
.stat { background: #232428; border-radius: 14px; padding: 12px; }
.slabel { font-size: .74rem; color: #b9bec6; }
.svalue {
  font-size: 1.5rem; font-weight: 300; color: #e9edf2;
  line-height: 1.15; margin: 2px 0 8px;
  font-variant-numeric: tabular-nums;
}
.schip {
  display: inline-block; font-size: .66rem; font-weight: 500;
  padding: 3px 9px; border-radius: 999px;
}
.schip.good { color: #7ee2a8; background: rgba(126, 226, 168, .16); }
.schip.typical { color: #c7cbd1; background: rgba(199, 203, 209, .14); }
.schip.watch { color: #e8b661; background: rgba(232, 182, 97, .16); }

.hypno { background: #131417; border-radius: 14px; padding: 12px; }
.lanes { position: relative; }
.lane { margin-bottom: 10px; }
.llabel { font-size: .76rem; color: #e9edf2; margin-bottom: 5px; }
.ldur { color: #8d949d; }
.track {
  position: relative; height: 18px;
  background: #24262b; border-radius: 9px;
}
.seg {
  position: absolute; top: 0; bottom: 0;
  border-radius: 9px;
}

.axis {
  display: flex; justify-content: space-between;
  font-size: .68rem; color: #6f767f; margin-top: 8px;
}

.actions { display: flex; align-items: center; gap: 4px; margin-top: 12px; }
.spacer { flex: 1; }
.thumb {
  background: none; border: 0; cursor: pointer; padding: 6px;
  border-radius: 999px; color: #8d949d; line-height: 0;
}
.thumb svg { width: 19px; height: 19px; }
.thumb.on { color: #7ee2a8; background: rgba(126, 226, 168, .14); }
.more {
  background: none; border: 0; cursor: pointer; color: #8d949d;
  font-size: 1.1rem; padding: 2px 8px; border-radius: 999px;
}

.menu {
  margin-top: 8px; background: #232428; border-radius: 12px; padding: 4px;
}
.mitem {
  display: block; padding: 9px 12px; border-radius: 9px;
  font-size: .82rem; color: #e9edf2; text-decoration: none;
}

.daybreak {
  display: flex; align-items: center; gap: 12px;
  margin: 6px 2px;
}
.wave {
  flex: 1; height: 1px;
  background: repeating-linear-gradient(
    90deg, #3a3d45 0 6px, transparent 6px 10px);
}
.dlabel { font-size: .8rem; color: #b9bec6; }
</style>
