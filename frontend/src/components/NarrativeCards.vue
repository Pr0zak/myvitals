<script setup lang="ts">
/**
 * Narrative event cards — web twin of `ui/common/NarrativeCards.kt`.
 *
 * "We tracked a nap · It looks like you took a nap at 12:45 PM for 52 min",
 * with the hypnogram underneath: one lane per stage, each segment placed by
 * WHEN it happened rather than as a summed bar. A stacked total would say
 * "26 min light" without showing that it came in two blocks either side of
 * the deep phase, which is the part worth seeing.
 *
 * All wording and classification come from `/summary/events` — the phrasing
 * is server-side so both clients say the same sentence, and the nap-vs-night
 * rule is a judgement that belongs with the data (see analytics/events.py).
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { NarrativeEvent } from "@/api/types";

const events = ref<NarrativeEvent[]>([]);
const loaded = ref(false);

/** Toggling an active vote clears it — tapping 👍 twice should undo, not
 *  re-affirm. Optimistic: the card reflects the tap immediately and the
 *  write follows; a failed write reverts rather than leaving the UI
 *  claiming a vote the server never took. */
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

/** Lane order top-to-bottom, matching the reference: lightest sleep first. */
const LANES = ["awake", "rem", "light", "deep"] as const;
const LANE_LABEL: Record<string, string> = {
  awake: "Total awake", rem: "REM", light: "Light", deep: "Deep",
};
const LANE_TONE: Record<string, string> = {
  awake: "#f48fb1", rem: "#4dd0e1", light: "#7aa7ff", deep: "#9575cd",
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

/** Segments for one lane, positioned as percentages across the session. */
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
        width: `${Math.max(1.5, Math.min(100 - left, width))}%`,
      };
    });
}

/** Only lanes the session actually has. Rendering an empty "REM · 0 min"
 *  lane is honest but the reference shows it, so keep known-zero lanes and
 *  drop only stages the data never mentions. */
function lanesFor(e: NarrativeEvent) {
  const seen = new Set(e.stages.map((s) => s.stage));
  return LANES.filter((l) => seen.has(l) || l === "awake").map((l) => ({
    stage: l,
    label: LANE_LABEL[l],
    total: e.stages.find((s) => s.stage === l)?.duration_s ?? 0,
    bars: lane(e, l),
    tone: LANE_TONE[l],
  }));
}

const shown = computed(() => events.value);
</script>

<template>
  <section v-if="loaded && shown.length" class="nc">
    <article v-for="e in shown" :key="e.id" class="card">
      <div class="pill" :class="e.kind">
        {{ e.kind === "nap" ? "Nap" : "Sleep" }}
      </div>

      <h3 class="head">{{ e.headline }}</h3>
      <p class="detail">{{ e.detail }}</p>

      <div class="hypno">
        <div v-for="l in lanesFor(e)" :key="l.stage" class="lane">
          <div class="llabel">
            {{ l.label }} <span class="ldur">· {{ mins(l.total) }}</span>
          </div>
          <div class="track">
            <span v-for="(b, i) in l.bars" :key="i" class="seg"
                  :style="{ left: b.left, width: b.width, background: l.tone }" />
          </div>
        </div>

        <div class="axis">
          <span>{{ clock(e.start) }}</span>
          <span>{{ clock(e.end) }}</span>
        </div>
      </div>

      <div class="feedback">
        <button class="thumb" :class="{ on: e.feedback === 'up' }"
                :aria-pressed="e.feedback === 'up'"
                aria-label="This looks right" @click="vote(e, 'up')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 22H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1h3zM7 12l4.5-8a2.5 2.5 0 0 1 3.4 3.3L13.5 10H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 21H7z" />
          </svg>
        </button>
        <button class="thumb" :class="{ on: e.feedback === 'down' }"
                :aria-pressed="e.feedback === 'down'"
                aria-label="This looks wrong" @click="vote(e, 'down')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 2h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3zM17 12l-4.5 8a2.5 2.5 0 0 1-3.4-3.3L10.5 14H5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.2 3H17z" />
          </svg>
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.nc { margin: 18px 0; display: flex; flex-direction: column; gap: 12px; }
.card { background: #1b1c1f; border-radius: 20px; padding: 16px; }

.pill {
  display: inline-block; font-size: .68rem; font-weight: 500;
  padding: 3px 10px; border-radius: 999px; margin-bottom: 10px;
  color: #d7c9ff; background: rgba(149, 117, 205, .22);
}
.pill.nap { color: #ffd7a1; background: rgba(232, 182, 97, .2); }

.head {
  font-size: 1.25rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 4px; letter-spacing: -0.2px;
}
.detail { font-size: .84rem; color: #b9bec6; margin: 0 0 14px; line-height: 1.35; }

.hypno { background: #131417; border-radius: 14px; padding: 12px; }
.lane { margin-bottom: 10px; }
.llabel { font-size: .74rem; color: #e9edf2; margin-bottom: 4px; }
.ldur { color: #8d949d; }
.track {
  position: relative; height: 14px;
  background: #24262b; border-radius: 7px; overflow: hidden;
}
.seg { position: absolute; top: 0; bottom: 0; border-radius: 7px; }

.axis {
  display: flex; justify-content: space-between;
  font-size: .66rem; color: #6f767f; margin-top: 8px;
}

.feedback { display: flex; gap: 4px; margin-top: 12px; }
.thumb {
  background: none; border: 0; cursor: pointer; padding: 6px;
  border-radius: 999px; color: #8d949d; line-height: 0;
}
.thumb svg { width: 18px; height: 18px; }
.thumb.on { color: #7ee2a8; background: rgba(126, 226, 168, .14); }
.thumb:hover { color: #b9bec6; }
</style>
