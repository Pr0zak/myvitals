<script setup lang="ts">
/**
 * Today.vue dashboard card showing today's strength plan.
 * - Plan exists + planned → "Start workout" CTA
 * - Plan exists + in_progress → "Resume" CTA
 * - Plan exists + completed → quiet "✓ done — N exercises, ratings" line
 * - No plan + recovery blocks → rest-day card with reason + "Force generate"
 * - No plan + recovery doesn't block → "Generate today's plan" CTA
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Dumbbell, Play, RotateCw } from "lucide-vue-next";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import Card from "@/components/Card.vue";
import type { StrengthWorkoutDetail } from "@/api/types";

const router = useRouter();
const workout = ref<StrengthWorkoutDetail | null>(null);
const recovery = ref<Awaited<ReturnType<typeof api.strengthRecovery>> | null>(null);
const loading = ref(true);
const generating = ref(false);

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  try {
    const [w, r] = await Promise.all([
      api.strengthToday().catch(() => null),
      api.strengthRecovery().catch(() => null),
    ]);
    workout.value = w;
    recovery.value = r;
  } finally {
    loading.value = false;
  }
}

async function generate() {
  generating.value = true;
  try {
    workout.value = await api.regenerateStrengthToday(true);
  } finally {
    generating.value = false;
  }
}

function open() {
  router.push("/workout/strength/today");
}

onMounted(load);
</script>

<template>
  <Card v-if="queryToken" title="Strength" :subtitle="workout?.split_focus.replace('_', ' ') ?? 'today'">
    <div v-if="loading" class="hint">Loading…</div>

    <!-- Active workout in progress -->
    <template v-else-if="workout && workout.status === 'in_progress'">
      <p class="big">
        <Dumbbell :size="16" />
        Workout in progress · {{ workout.exercises.length }} exercises
      </p>
      <button class="primary" @click="open">
        <Play :size="14" /> Resume workout
      </button>
    </template>

    <!-- Already completed today -->
    <template v-else-if="workout && workout.status === 'completed'">
      <p class="big done">✓ {{ workout.exercises.length }} exercises completed today</p>
      <button class="ghost" @click="open">View summary</button>
    </template>

    <!-- Plan exists, ready to start -->
    <template v-else-if="workout && workout.status === 'planned'">
      <p class="big">
        {{ workout.exercises.length }} exercises ·
        <span v-if="workout.recovery_score_used != null">
          recovery {{ Math.round(workout.recovery_score_used) }}
        </span>
        <span v-else>recovery integration off</span>
      </p>
      <ul class="preview">
        <li v-for="ex in workout.exercises.slice(0, 3)" :key="ex.id">
          {{ ex.exercise_id.replace(/_/g, ' ') }}
          <small>· {{ ex.target_sets }}×{{ ex.target_reps_low === ex.target_reps_high
            ? ex.target_reps_low : `${ex.target_reps_low}-${ex.target_reps_high}` }}</small>
        </li>
        <li v-if="workout.exercises.length > 3" class="more">+ {{ workout.exercises.length - 3 }} more</li>
      </ul>
      <div class="actions">
        <button class="primary" @click="open"><Play :size="14" /> Start workout</button>
        <button class="ghost" :disabled="generating" @click="generate">
          <RotateCw :size="14" /> Regenerate
        </button>
      </div>
    </template>

    <!-- Recovery blocks → rest day -->
    <template v-else-if="recovery && recovery.rest_day_recommended">
      <p class="big rest">Rest day recommended</p>
      <p class="hint">{{ recovery.rest_day_reason }}.</p>
      <button class="ghost" :disabled="generating" @click="generate">
        Generate anyway
      </button>
    </template>

    <!-- No plan yet, no rest-day block -->
    <template v-else>
      <p class="hint">No plan generated for today yet.</p>
      <button class="primary" :disabled="generating" @click="generate">
        <Dumbbell :size="14" /> Generate today's plan
      </button>
    </template>
  </Card>
</template>

<style scoped>
.big { margin: 0 0 0.4rem; font-size: 0.95rem; }
.big.done { color: var(--good, #22c55e); }
.big.rest { color: var(--warn, #f59e0b); }
.hint { color: var(--muted); font-size: 0.85rem; margin: 0.3rem 0; }
.preview { list-style: none; padding: 0; margin: 0.3rem 0;
  display: flex; flex-direction: column; gap: 0.2rem;
  font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.78rem;
  color: var(--text-soft); }
.preview li { display: flex; gap: 0.4rem; align-items: baseline; }
.preview small { color: var(--muted-2); }
.preview .more { color: var(--muted); font-style: italic; }
.actions { display: flex; gap: 0.4rem; margin-top: 0.7rem; }
button.primary, button.ghost {
  padding: 0.4rem 0.85rem; border-radius: 6px; font-size: 0.85rem;
  cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem;
}
button.primary { background: var(--accent, #ef4444); color: #fff; border: none; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--text-soft); border: 1px solid var(--line); }
button.ghost:hover { color: var(--text); border-color: var(--accent, #ef4444); }
</style>
