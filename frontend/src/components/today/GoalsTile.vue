<script setup lang="ts">
/**
 * Today Goals tile (TODAY-1 / GOALS-3). Compact horizontal list of
 * active goals with direction-aware progress bars. No AI call — pure
 * data render of /ai/goals, which carries pre-computed
 * `current_value` + `progress_pct` (GOALS-3, v0.7.212).
 *
 * Empty state intentionally renders nothing; the tile collapses when
 * the user has no active goals so it doesn't visual-noise the page.
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { Target } from "lucide-vue-next";

interface GoalProgress {
  id: number;
  kind: string;
  title: string;
  target_value: number | null;
  target_unit: string | null;
  current_value: number | null;
  progress_pct: number | null;
}

const props = defineProps<{ goals: GoalProgress[] }>();
const visible = computed(() => props.goals.slice(0, 4));
</script>

<template>
  <div v-if="goals.length > 0" class="card goals-card">
    <div class="head-row">
      <Target :size="14"/>
      <span class="card-title">Goals</span>
      <span class="dim count">{{ goals.length }} active</span>
      <RouterLink class="btn btn-tiny open-btn" to="/goals">Open</RouterLink>
    </div>
    <div class="rows">
      <div v-for="g in visible" :key="g.id" class="row">
        <div class="row-head">
          <span class="kind-pill">{{ g.kind }}</span>
          <span class="row-title">{{ g.title }}</span>
          <span v-if="g.progress_pct != null" class="pct mono">
            {{ g.progress_pct.toFixed(0) }}%
          </span>
        </div>
        <div class="bar">
          <div class="bar-fill"
               :class="{ done: (g.progress_pct ?? 0) >= 100 }"
               :style="{ width: Math.min(100, g.progress_pct ?? 0) + '%' }"/>
        </div>
        <div v-if="g.current_value != null && g.target_value != null"
             class="row-foot mono dim">
          {{ g.current_value.toFixed(1) }} / {{ g.target_value }} {{ g.target_unit ?? '' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.goals-card { padding: 14px 16px; }
.head-row {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 10px;
}
.head-row :deep(svg) { color: var(--on-surface-2); }
.head-row .card-title { margin: 0; }
.count { font-size: 11px; }
.open-btn { margin-left: auto; text-transform: none; letter-spacing: 0; text-decoration: none; }
.rows { display: flex; flex-direction: column; gap: 10px; }
.row {
  padding: 6px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.row:first-child { border-top: 0; padding-top: 0; }
.row-head {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 4px;
}
.kind-pill {
  background: rgba(56, 189, 248, 0.12); color: #38bdf8;
  border-radius: 4px; padding: 1px 6px;
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
  font-weight: 600;
}
.row-title { color: var(--on-surface); font-size: 12px; flex: 1; }
.pct { color: var(--on-surface); font-size: 12px; }
.bar {
  height: 4px; background: rgba(255, 255, 255, 0.06);
  border-radius: 2px; overflow: hidden;
}
.bar-fill {
  height: 100%; background: #38bdf8;
  transition: width 320ms ease;
}
.bar-fill.done { background: #22c55e; }
.row-foot { font-size: 11px; margin-top: 3px; }
.dim { color: var(--on-surface-2); }
</style>
