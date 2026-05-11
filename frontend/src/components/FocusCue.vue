<script setup lang="ts">
/**
 * Per-workout focus cue. Lazy POST — silent until the user taps the
 * pill to fetch. Cached server-side by payload hash so re-taps with
 * the same plan are free.
 */
import { ref } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";

const props = defineProps<{ workoutId: number }>();

const cue = ref<{ headline: string; cue: string; tone: string } | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const expanded = ref(false);

async function load() {
  if (loading.value) return;
  loading.value = true;
  error.value = null;
  try {
    const r = await api.aiStrengthFocusCue(props.workoutId);
    cue.value = r.cue;
    expanded.value = true;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <Card :flat="true" class="fc-card">
    <button v-if="!cue && !loading" class="fc-toggle" @click="load">
      <span class="fc-icon">◇</span>
      <span class="fc-title">Focus cue</span>
      <span class="fc-hint">Ask AI</span>
    </button>
    <button v-else-if="loading" class="fc-toggle" disabled>
      <span class="fc-icon">◇</span>
      <span class="fc-title">Focus cue</span>
      <span class="fc-hint">Thinking…</span>
    </button>
    <div v-else-if="cue" class="fc-body">
      <button class="fc-toggle" @click="expanded = !expanded">
        <span class="fc-icon">◇</span>
        <span class="fc-title">{{ cue.headline }}</span>
        <span class="fc-hint">{{ expanded ? "−" : "+" }}</span>
      </button>
      <p v-if="expanded" class="fc-cue">{{ cue.cue }}</p>
    </div>
    <p v-if="error" class="muted small">AI focus cue unavailable. Check Settings → AI.</p>
  </Card>
</template>

<style scoped>
.fc-card { margin: 0 0 0.6rem; padding: 0.55rem 0.75rem !important;
           border-radius: 10px !important;
           border-left: 4px solid #a78bfa !important;
           background: rgba(167, 139, 250, 0.06); }
.fc-card :deep(header) { display: none; }
.fc-card :deep(.body) { display: block; }
.fc-toggle {
  width: 100%; display: flex; align-items: center; gap: 0.5rem;
  background: transparent; border: none; padding: 0; cursor: pointer;
  color: var(--text); text-align: left; min-height: 28px;
}
.fc-icon { color: #a78bfa; font-size: 0.95rem; }
.fc-title { font-weight: 600; font-size: 0.9rem; flex: 1; }
.fc-hint { color: var(--muted); font-size: 0.8rem; }
.fc-cue { color: var(--text); font-size: 0.85rem; margin: 0.4rem 0 0; line-height: 1.4; }
.muted { color: var(--muted); }
.muted.small { font-size: 0.8rem; }
</style>
