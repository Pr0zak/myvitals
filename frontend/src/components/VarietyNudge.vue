<script setup lang="ts">
/**
 * Lazy-loaded card for the AI variety nudge — POSTs to
 * /ai/strength/nudge/{id}, displays 0-2 suggested swaps with
 * accept/decline buttons. Empty state (zero swaps) is silence —
 * the model returning [] is a valid "the plan is fine" signal.
 *
 * AI must be enabled + an Anthropic key configured for the call to
 * succeed; on failure we hide the card rather than show errors —
 * the variety nudge is a nicety, not core flow.
 */
import { ref } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";

const props = defineProps<{ workoutId: number }>();
const emit = defineEmits<{
  // Caller (StrengthToday.vue) maps target_exercise_id → workout_exercise_id
  // and runs the actual swap so it can refresh the workout afterwards.
  (e: "accept", payload: {
    targetExerciseId: string;
    replacementExerciseId: string;
  }): void;
}>();

type Swap = {
  target_exercise_id: string;
  replacement_exercise_id: string;
  reason: string;
};

const open = ref(false);
const loading = ref(false);
const error = ref<string | null>(null);
const swaps = ref<Swap[]>([]);
const cached = ref(false);
const generatedAt = ref<string | null>(null);
const dismissed = ref<Set<string>>(new Set());

async function loadNudge() {
  if (loading.value) return;
  loading.value = true;
  error.value = null;
  try {
    const r = await api.aiStrengthNudge(props.workoutId);
    swaps.value = r.nudge?.swaps ?? [];
    cached.value = !!r.cached;
    generatedAt.value = r.generated_at;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function toggleOpen() {
  open.value = !open.value;
  if (open.value && swaps.value.length === 0 && !error.value) {
    loadNudge();
  }
}

function decline(s: Swap) {
  dismissed.value = new Set([...dismissed.value, s.target_exercise_id]);
}

// Caller is expected to map target_exercise_id → workout_exercise_id
// (the row id, not the exercise id). We surface only the AI fields;
// the caller does the lookup using its own workout state.
const visibleSwaps = (() => {
  // computed-on-template-render — kept simple since the list is tiny
  return () => swaps.value.filter((s) => !dismissed.value.has(s.target_exercise_id));
})();
</script>

<template>
  <Card :flat="true" class="vn-card">
    <button class="vn-toggle" @click="toggleOpen">
      <span class="vn-icon">✦</span>
      <span class="vn-title">Variety nudge</span>
      <span v-if="!open && swaps.length" class="vn-count">
        {{ visibleSwaps().length }} suggestion{{ visibleSwaps().length === 1 ? "" : "s" }}
      </span>
      <span v-else class="vn-hint">{{ open ? "−" : "+" }}</span>
    </button>

    <div v-if="open" class="vn-body">
      <p v-if="loading" class="muted">Thinking…</p>
      <p v-else-if="error" class="muted small">
        AI nudge unavailable. Check Settings → AI.
      </p>

      <p v-else-if="visibleSwaps().length === 0 && swaps.length === 0" class="muted small">
        Plan looks balanced — no swaps suggested.
      </p>

      <p v-else-if="visibleSwaps().length === 0" class="muted small">
        All suggestions dismissed.
      </p>

      <ul v-else class="vn-list">
        <li v-for="s in visibleSwaps()" :key="s.target_exercise_id" class="vn-item">
          <div class="vn-row">
            <span class="vn-tag">swap</span>
            <code class="vn-eid">{{ s.target_exercise_id.replace(/_/g, " ") }}</code>
            <span class="vn-arrow">→</span>
            <code class="vn-eid alt">{{ s.replacement_exercise_id.replace(/_/g, " ") }}</code>
          </div>
          <div class="vn-reason">{{ s.reason }}</div>
          <div class="vn-actions">
            <button class="primary"
                    @click="emit('accept', {
                      targetExerciseId: s.target_exercise_id,
                      replacementExerciseId: s.replacement_exercise_id,
                    })">
              Accept swap
            </button>
            <button class="ghost" @click="decline(s)">Dismiss</button>
          </div>
        </li>
      </ul>

      <div v-if="generatedAt" class="vn-foot muted">
        {{ cached ? "cached" : "fresh" }} · {{ new Date(generatedAt).toLocaleString() }}
      </div>
    </div>
  </Card>
</template>

<style scoped>
.vn-card { margin-top: 0.5rem; }
.vn-toggle {
  width: 100%; display: flex; align-items: center; gap: 0.5rem;
  background: transparent; border: none; padding: 0.4rem 0; cursor: pointer;
  color: var(--text); text-align: left;
}
.vn-icon { color: #a78bfa; font-size: 0.95rem; }
.vn-title { font-weight: 600; font-size: 0.95rem; }
.vn-count { color: var(--muted); font-size: 0.78rem; margin-left: auto; }
.vn-hint { color: var(--muted); margin-left: auto; font-size: 1rem; }
.vn-body { padding-top: 0.4rem; }
.muted { color: var(--muted); }
.muted.small { font-size: 0.85rem; }
.vn-list { list-style: none; padding: 0; margin: 0; display: flex;
           flex-direction: column; gap: 0.5rem; }
.vn-item { padding: 0.6rem 0.75rem; background: var(--bg-1); border-radius: 8px;
           border: 1px solid var(--line); }
.vn-row { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
          font-size: 0.85rem; }
.vn-tag { background: rgba(167, 139, 250, 0.15); color: #a78bfa;
          padding: 0.05rem 0.4rem; border-radius: 4px;
          font-size: 0.7rem; font-weight: 600;
          text-transform: uppercase; letter-spacing: 0.06em; }
.vn-eid { font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.8rem;
          color: var(--text); text-transform: capitalize; }
.vn-eid.alt { color: #22c55e; }
.vn-arrow { color: var(--muted); }
.vn-reason { color: var(--muted); font-size: 0.8rem; margin: 0.35rem 0 0.4rem; }
.vn-actions { display: flex; gap: 0.4rem; }
.primary { background: #38bdf8; color: #0f172a; border: none;
           border-radius: 6px; padding: 0.3rem 0.7rem; font-size: 0.8rem;
           cursor: pointer; font-weight: 500; }
.ghost { background: transparent; color: var(--muted); border: 1px solid var(--line);
         border-radius: 6px; padding: 0.3rem 0.7rem; font-size: 0.8rem;
         cursor: pointer; }
.vn-foot { font-size: 0.7rem; margin-top: 0.6rem; }
</style>
