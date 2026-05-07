<script setup lang="ts">
/**
 * Expandable "Why this workout?" card. Lazy-loads the rules-based
 * rationale from /workout/strength/explain/{id} on first open. Mirrors
 * the phone affordance shipped in v0.7.55.
 */
import { ref } from "vue";
import { ChevronRight, ChevronDown } from "lucide-vue-next";
import { api } from "@/api/client";

const props = defineProps<{ workoutId: number }>();

const open = ref(false);
const loading = ref(false);
const explain = ref<{
  workout_id: number; split_focus: string;
  why_split: string; why_exercises: string; why_targets: string;
} | null>(null);

async function toggle() {
  open.value = !open.value;
  if (open.value && explain.value === null && !loading.value) {
    loading.value = true;
    try {
      explain.value = await api.strengthExplain(props.workoutId);
    } catch { /* swallow */ }
    finally { loading.value = false; }
  }
}

const sections = (e: typeof explain.value) => {
  if (!e) return [] as Array<[string, string]>;
  return [
    ["Why this split", e.why_split],
    ["Why these exercises", e.why_exercises],
    ["Why these targets", e.why_targets],
  ] as Array<[string, string]>;
};
</script>

<template>
  <div class="why-card">
    <button class="head" @click="toggle">
      <component :is="open ? ChevronDown : ChevronRight" :size="18" />
      <span>Why this workout?</span>
    </button>
    <div v-if="open" class="body">
      <p v-if="loading" class="dim">…</p>
      <template v-else-if="explain">
        <div v-for="([h, body], i) in sections(explain)" :key="i" class="section">
          <div class="micro">{{ h }}</div>
          <p v-html="body"></p>
        </div>
      </template>
      <p v-else class="dim">No rationale available.</p>
    </div>
  </div>
</template>

<style scoped>
.why-card {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 12px;
  margin: 0.4rem 0 0.6rem;
}
.head {
  width: 100%;
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.7rem 0.85rem;
  background: transparent; border: none; cursor: pointer;
  color: var(--text); font-size: 0.85rem; font-weight: 500;
  text-align: left;
}
.body { padding: 0 0.85rem 0.85rem 2.4rem;
        display: flex; flex-direction: column; gap: 0.7rem; }
.section .micro { font-size: 0.7rem; letter-spacing: 0.1em;
                  color: var(--muted); font-weight: 700;
                  text-transform: uppercase; margin-bottom: 0.25rem; }
.section p { margin: 0; color: var(--muted); font-size: 0.82rem; line-height: 1.55; }
.dim { color: var(--muted); }
</style>
