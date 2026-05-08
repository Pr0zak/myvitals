<script setup lang="ts">
/**
 * Three cells: last cardio activity, last strength workout, last erg row.
 * Each cell is a RouterLink to its detail screen. Caller computes the
 * latest of each from the existing /activities + /workout/strength feeds.
 */
import { RouterLink } from "vue-router";
import { Activity, Dumbbell, Anchor, ChevronRight } from "lucide-vue-next";

export type CardioCell = {
  title: string;
  whenLabel: string;
  miles: string | null;
  duration: string | null;
  avgHr: number | null;
  source: string;
  sourceId: string;
} | null;
export type StrengthCell = {
  title: string;
  whenLabel: string;
  setCount: number | null;
  avgRpe: number | null;
  status: string;
  workoutDate: string;
} | null;
export type ErgCell = {
  title: string;
  whenLabel: string;
  meters: string | null;
  pace500: string | null;
  avgWatts: number | null;
  source: string;
  sourceId: string;
} | null;

defineProps<{
  cardio: CardioCell;
  strength: StrengthCell;
  erg: ErgCell;
  mobile?: boolean;
}>();

function statusTone(s: string): "good" | "warn" | "neutral" {
  if (s === "completed") return "good";
  if (s === "in_progress") return "warn";
  return "neutral";
}
</script>

<template>
  <div class="card act-card" :class="{ mobile }">
    <div class="title-row">
      <span class="card-title">Today's activity</span>
    </div>

    <div class="grid" :class="{ mobile }">
      <!-- Cardio -->
      <RouterLink v-if="cardio"
                  :to="`/activity/${cardio.source}/${cardio.sourceId}`"
                  class="cell linkable">
        <div class="cell-head">
          <div class="lbl"><Activity :size="14"/><span>Last activity</span></div>
          <ChevronRight :size="14" class="chev"/>
        </div>
        <div>
          <div class="title">{{ cardio.title }}</div>
          <div class="dim when">{{ cardio.whenLabel }}</div>
        </div>
        <div class="stats">
          <div v-if="cardio.miles" class="stat">
            <span class="mono">{{ cardio.miles }}</span><span class="unit-s">mi</span>
          </div>
          <div v-if="cardio.duration" class="stat">
            <span class="mono">{{ cardio.duration }}</span>
          </div>
          <div v-if="cardio.avgHr != null" class="stat">
            <span class="mono">{{ Math.round(cardio.avgHr) }}</span>
            <span class="unit-s">avg bpm</span>
          </div>
        </div>
      </RouterLink>
      <div v-else class="cell empty">
        <div class="lbl"><Activity :size="14"/><span>Last activity</span></div>
        <span class="dim">No activity logged today</span>
      </div>

      <!-- Strength -->
      <RouterLink v-if="strength"
                  :to="`/workout/strength/day/${strength.workoutDate}`"
                  class="cell linkable">
        <div class="cell-head">
          <div class="lbl"><Dumbbell :size="14"/><span>Last strength</span></div>
          <ChevronRight :size="14" class="chev"/>
        </div>
        <div>
          <div class="title">{{ strength.title }}</div>
          <div class="dim when">{{ strength.whenLabel }}</div>
        </div>
        <div class="stats">
          <div v-if="strength.setCount != null" class="stat">
            <span class="mono">{{ strength.setCount }}</span>
            <span class="unit-s">sets</span>
          </div>
          <div v-if="strength.avgRpe != null" class="stat">
            <span class="mono">{{ strength.avgRpe.toFixed(1) }}</span>
            <span class="unit-s">avg RPE</span>
          </div>
          <span :class="['chip', `tone-${statusTone(strength.status)}`]">
            <span :class="['dot', `dot-${statusTone(strength.status)}`]"/>
            {{ strength.status }}
          </span>
        </div>
      </RouterLink>
      <div v-else class="cell empty">
        <div class="lbl"><Dumbbell :size="14"/><span>Last strength</span></div>
        <span class="dim">No strength session today</span>
      </div>

      <!-- Erg (rower/skierg/bikeerg). Hidden when no row in window. -->
      <RouterLink v-if="erg"
                  :to="`/activity/${erg.source}/${erg.sourceId}`"
                  class="cell linkable">
        <div class="cell-head">
          <div class="lbl"><Anchor :size="14"/><span>Last erg</span></div>
          <ChevronRight :size="14" class="chev"/>
        </div>
        <div>
          <div class="title">{{ erg.title }}</div>
          <div class="dim when">{{ erg.whenLabel }}</div>
        </div>
        <div class="stats">
          <div v-if="erg.meters" class="stat">
            <span class="mono">{{ erg.meters }}</span><span class="unit-s">m</span>
          </div>
          <div v-if="erg.pace500" class="stat">
            <span class="mono">{{ erg.pace500 }}</span><span class="unit-s">/500m</span>
          </div>
          <div v-if="erg.avgWatts != null" class="stat">
            <span class="mono">{{ erg.avgWatts }}</span><span class="unit-s">W avg</span>
          </div>
        </div>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.act-card { padding: 0; }
.title-row { padding: 14px 16px 0; }
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  border-top: 1px solid var(--outline);
}
.grid.mobile { grid-template-columns: 1fr; }
.cell {
  padding: 14px 16px;
  border-right: 1px solid var(--outline);
  display: flex; flex-direction: column; gap: 8px; min-width: 0;
  text-decoration: none; color: inherit; cursor: pointer;
}
.cell:last-child { border-right: none; }
.grid.mobile .cell {
  border-right: none; border-bottom: 1px solid var(--outline);
}
.grid.mobile .cell:last-child { border-bottom: none; }
.cell-head {
  display: flex; align-items: center; justify-content: space-between;
}
.lbl {
  display: flex; align-items: center; gap: 8px;
  color: var(--on-surface-2);
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
}
.chev { color: var(--dim); }
.title { font-size: 14px; font-weight: 500; color: var(--on-surface); }
.when { font-size: 11px; margin-top: 2px; }
.stats { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 2px; }
.stat { display: flex; align-items: baseline; gap: 4px; }
.stat .mono { font-size: 14px; font-weight: 500; }
.unit-s { color: var(--dim); font-size: 10px; }
.cell.empty { cursor: default; gap: 14px; }
.cell.empty .dim { font-size: 12px; }
.chip { height: 22px; font-size: 11px; padding: 0 8px; }
.chip.tone-good { color: var(--good); border-color: rgba(34,197,94,0.3); }
.chip.tone-warn { color: var(--warn); border-color: rgba(234,179,8,0.3); }
.chip.tone-neutral { color: var(--on-surface-2); }
.dim { color: var(--on-surface-2); }
</style>
