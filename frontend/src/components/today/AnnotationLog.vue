<script setup lang="ts">
/**
 * Horizontal scroll of annotation chips with quick-add buttons.
 *
 * Quick-add: tap a kind button → POST /journal with sensible defaults.
 * The full Journal page is one tap away via the "More…" affordance for
 * anything that needs free-text or a non-default value.
 */
import { computed, ref } from "vue";
import {
  Coffee, Wine, Utensils, Smile, Pill, FileText, Activity, MoreHorizontal,
} from "lucide-vue-next";
import { api } from "@/api/client";

type Chip = {
  id: number;
  kind: string;
  label: string;
  whenLabel: string;
};

const props = defineProps<{ chips: Chip[] }>();
const emit = defineEmits<{
  (e: "log"): void;
  (e: "added"): void;
}>();

function iconFor(kind: string) {
  if (kind === "caffeine") return Coffee;
  if (kind === "alcohol") return Wine;
  if (kind === "food") return Utensils;
  if (kind === "mood") return Smile;
  if (kind === "meds") return Pill;
  if (kind === "note") return FileText;
  return Activity;
}

const visible = computed(() => props.chips.slice(0, 12));

// Quick-add definitions — payloads match Journal.vue's field shape so
// later edits round-trip cleanly. Notes/food carry an empty description
// (just a timestamped marker); user opens Journal to fill in text.
const QUICK_ADD: { kind: string; label: string; payload: Record<string, unknown> }[] = [
  { kind: "caffeine", label: "Caffeine", payload: { mg: 100, source: "coffee" } },
  { kind: "alcohol",  label: "Alcohol",  payload: { drinks: 1, type: "beer" } },
  { kind: "food",     label: "Food",     payload: { description: "" } },
  { kind: "mood",     label: "Mood",     payload: { score: 7 } },
  { kind: "meds",     label: "Meds",     payload: { name: "", dose: "" } },
];

const busy = ref<string | null>(null);
const flash = ref<string | null>(null);
const error = ref<string | null>(null);

async function quickAdd(kind: string, payload: Record<string, unknown>) {
  if (busy.value) return;
  busy.value = kind;
  error.value = null;
  try {
    await api.createAnnotation({ type: kind, payload });
    flash.value = kind;
    emit("added");
    // Clear the success flash after a moment so repeated taps still feel responsive.
    setTimeout(() => { if (flash.value === kind) flash.value = null; }, 1400);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed";
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div class="card log-card">
    <div class="head-row">
      <span class="card-title">Log</span>
      <button class="btn btn-tiny btn-more" @click="emit('log')"
              title="Open Journal for full edit / history">
        <MoreHorizontal :size="13"/> More…
      </button>
    </div>
    <div class="quick-row">
      <button
        v-for="q in QUICK_ADD" :key="q.kind"
        class="quick-btn"
        :class="{ 'is-flash': flash === q.kind, 'is-busy': busy === q.kind }"
        :disabled="busy !== null"
        :title="`Quick log: ${q.label}`"
        @click="quickAdd(q.kind, q.payload)"
      >
        <component :is="iconFor(q.kind)" :size="14"/>
        <span class="quick-label">{{ q.label }}</span>
      </button>
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <div class="no-scrollbar chips">
      <div v-for="c in visible" :key="c.id" class="chip">
        <component :is="iconFor(c.kind)" :size="12" class="chip-icon"/>
        <span class="chip-label">{{ c.label }}</span>
        <span class="mono dim chip-when">{{ c.whenLabel }}</span>
      </div>
      <div v-if="visible.length === 0" class="dim empty">
        Tap a quick-add above, or "More…" for full options.
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-card { padding: 14px 16px; }
.head-row {
  display: flex; align-items: center; gap: 12px;
  justify-content: space-between; margin-bottom: 10px;
}
.head-row .card-title { margin: 0; }
.quick-row {
  display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px;
}
.quick-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 10px; height: 28px;
  border: 1px solid var(--outline);
  background: var(--surface-low);
  color: var(--on-surface);
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  transition: background-color 120ms ease, border-color 120ms ease,
              transform 120ms ease;
}
.quick-btn:hover:not(:disabled) {
  background: var(--surface);
  border-color: var(--outline-strong);
}
.quick-btn:active:not(:disabled) { transform: scale(0.97); }
.quick-btn:disabled { opacity: 0.55; cursor: progress; }
.quick-btn.is-flash {
  background: rgba(34, 197, 94, 0.16);
  border-color: rgba(34, 197, 94, 0.55);
}
.quick-btn.is-busy { opacity: 0.7; }
.quick-label { line-height: 1; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
.chip { flex: 0 0 auto; height: 30px; padding: 0 12px; }
.chip-icon { color: var(--on-surface-2); }
.chip-label { color: var(--on-surface); font-size: 12px; }
.chip-when { font-size: 11px; margin-left: 4px; }
.dim { color: var(--on-surface-2); }
.empty { font-size: 12px; padding: 4px 0; }
.btn-tiny { text-transform: none; letter-spacing: 0; }
.btn-more { gap: 4px; }
.err { color: #ef4444; font-size: 11px; margin-bottom: 6px; }
</style>
