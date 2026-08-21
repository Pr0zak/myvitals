<script setup lang="ts">
/**
 * CONS-1 — training consistency, rendered from server-computed numbers.
 *
 * Nothing in here derives a figure. That is the point: the streak and the
 * frequency used to be computed in each client from whatever slice of
 * activities that screen had loaded, which made both of them functions of
 * the date picker rather than of the training. See
 * `backend/src/myvitals/analytics/consistency.py` for the three specific
 * ways the old inline version was wrong.
 */
import { computed } from "vue";
import Card from "@/components/Card.vue";
import type { TrainingConsistency } from "@/api/types";

const props = defineProps<{
  data: TrainingConsistency | null | undefined;
  /** "Sessions" for strength, "Activities" for the cardio feed. */
  noun?: string;
  /** Muscle recency is only meaningful on the strength surface. */
  showMuscles?: boolean;
}>();

const noun = computed(() => props.noun ?? "sessions");

const streakLabel = computed(() => {
  const d = props.data;
  if (!d) return "";
  if (d.current_streak_days === 0) {
    return d.last_active ? `Last ${noun.value.slice(0, -1)} ${d.last_active}` : "No history yet";
  }
  // The distinction the server's `today_pending` flag exists to carry:
  // a streak resting on yesterday is alive but unbanked, and telling the
  // user it is banked would be wrong by one day.
  return d.today_pending ? "Train today to keep it" : "Banked today";
});

/** Muscles sorted most-rested first, which is the order that answers
 *  "what should I train?" — the question the number is actually for. */
const muscles = computed(() => {
  const m = props.data?.days_since_by_muscle;
  if (!m) return [];
  return Object.entries(m).sort((a, b) => b[1] - a[1]);
});

function restClass(days: number): string {
  if (days >= 7) return "rested";
  if (days <= 1) return "fresh";
  return "";
}
</script>

<template>
  <Card title="Consistency">
    <div v-if="!data" class="empty">Not available from this backend.</div>
    <template v-else>
      <div class="grid">
        <div class="stat">
          <div class="num">{{ data.current_streak_days }}<span class="unit">d</span></div>
          <div class="lbl">current streak</div>
          <div class="sub">{{ streakLabel }}</div>
        </div>
        <div class="stat">
          <div class="num">{{ data.longest_streak_days }}<span class="unit">d</span></div>
          <div class="lbl">longest streak</div>
          <div class="sub">
            {{ data.longest_streak_end ? `ended ${data.longest_streak_end}` : "—" }}
          </div>
        </div>
        <div class="stat">
          <div class="num">{{ data.sessions_per_week_actual }}</div>
          <div class="lbl">{{ noun }}/week</div>
          <div class="sub">over {{ data.frequency_window_days }} days</div>
        </div>
        <div class="stat">
          <div class="num">{{ data.sessions_last_28d }}</div>
          <div class="lbl">last 28 days</div>
          <div class="sub">{{ data.sessions_last_7d }} in the last 7</div>
        </div>
      </div>

      <div v-if="showMuscles && muscles.length" class="muscles">
        <h3>Days rested</h3>
        <p class="hint">
          Most-rested first. 28 means nothing logged in the lookback window.
        </p>
        <ul>
          <li v-for="[m, d] in muscles" :key="m" :class="restClass(d)">
            <span class="m">{{ m.replace(/_/g, " ") }}</span>
            <span class="d">{{ d }}d</span>
          </li>
        </ul>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.9rem;
}
.stat { min-width: 0; }
.num { font-size: 1.6rem; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.unit { font-size: 0.9rem; color: var(--muted-2); margin-left: 0.1rem; }
.lbl { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-2); }
.sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }

.muscles { margin-top: 1.2rem; }
.muscles h3 { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-2); margin: 0 0 0.2rem; }
.hint { font-size: 0.75rem; color: var(--muted-2); margin: 0 0 0.6rem; }
.muscles ul { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.35rem; }
.muscles li {
  display: flex; gap: 0.4rem; align-items: baseline;
  padding: 0.25rem 0.5rem; border-radius: 999px;
  border: 1px solid var(--border); font-size: 0.78rem;
}
.muscles li.rested { border-color: var(--good); color: var(--good); }
.muscles li.fresh { color: var(--muted-2); }
.muscles .m { text-transform: capitalize; }
.muscles .d { font-variant-numeric: tabular-nums; color: var(--muted); }
.empty { color: var(--muted-2); padding: 1rem 0; }
</style>
