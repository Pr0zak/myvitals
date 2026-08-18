<script setup lang="ts">
/**
 * Day picker: ‹ [Wed, May 13] ›  with a Today chip when you are not on today.
 *
 * Mirrors `android/.../ui/common/DayNav.kt`, which has been on four phone
 * screens (sleep, heart rate, steps, vitals detail) since it was written
 * while the web had no day navigation at all — a hard parity break that
 * `scripts/parity_check.py` never saw, because there was no web file to pair.
 *
 * The forward arrow stops at today. There is no data in the future, and an
 * enabled control that always returns an empty screen is worse than a
 * disabled one.
 *
 * ## The ambient tint
 *
 * Borrowed from SparkyFitness, and the reason this component sets something
 * outside itself. While the selected day is not today, `data-day-relation`
 * is stamped on `<html>` so the app shell can tint its own chrome. Being
 * quietly parked on last Tuesday and reading the numbers as though they were
 * current is a genuine failure mode, and it is worth more here than in the
 * app the idea came from: myvitals has shipped the UTC-versus-local day bug
 * three separate times, so "which day am I actually looking at" deserves to
 * be impossible to miss rather than a small label in one corner.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";

const props = withDefaults(defineProps<{
  /** Selected day as a local `YYYY-MM-DD` string. */
  modelValue: string;
  /** Stamp `data-day-relation` on <html> so the shell can tint. */
  tintShell?: boolean;
}>(), { tintShell: true });

const emit = defineEmits<{ (e: "update:modelValue", v: string): void }>();

/** Local calendar day as `YYYY-MM-DD`.
 *
 *  Deliberately not `toISOString().slice(0, 10)`: that converts to UTC first,
 *  so west of Greenwich it reports tomorrow for most of the evening. Same
 *  class of bug as the one the backend keeps re-learning. */
function toLocalISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseLocal(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function shift(iso: string, days: number): string {
  const d = parseLocal(iso);
  d.setDate(d.getDate() + days);
  return toLocalISO(d);
}

const today = computed(() => toLocalISO(new Date()));
const isToday = computed(() => props.modelValue === today.value);
const atMax = computed(() => props.modelValue >= today.value);

const label = computed(() => {
  if (isToday.value) return "Today";
  const d = parseLocal(props.modelValue);
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    ...(thisYear ? {} : { year: "numeric" }),
  });
});

const relation = computed(() => (isToday.value ? "today" : props.modelValue < today.value ? "past" : "future"));

function applyTint() {
  if (!props.tintShell) return;
  document.documentElement.dataset.dayRelation = relation.value;
}
function clearTint() {
  delete document.documentElement.dataset.dayRelation;
}
watch(relation, applyTint, { immediate: true });
onBeforeUnmount(clearTint);

const picker = ref<HTMLInputElement | null>(null);
function openPicker() {
  // showPicker() is the only way to open the native calendar from a label
  // click; Firefox and older Safari do not implement it, so fall back to
  // focusing the input, which at least surfaces the browser's own control.
  const el = picker.value;
  if (!el) return;
  if (typeof el.showPicker === "function") el.showPicker();
  else el.focus();
}

function onPick(e: Event) {
  const v = (e.target as HTMLInputElement).value;
  if (v) emit("update:modelValue", v > today.value ? today.value : v);
}
</script>

<template>
  <div class="day-nav" :data-relation="relation" role="group" aria-label="Day">
    <button type="button" class="arrow" aria-label="Previous day"
            @click="emit('update:modelValue', shift(modelValue, -1))">‹</button>

    <button type="button" class="label" @click="openPicker">
      {{ label }}
      <input ref="picker" type="date" class="native"
             :value="modelValue" :max="today" tabindex="-1"
             aria-label="Pick a day" @change="onPick"/>
    </button>

    <button type="button" class="arrow" aria-label="Next day"
            :disabled="atMax"
            @click="emit('update:modelValue', shift(modelValue, 1))">›</button>

    <button v-if="!isToday" type="button" class="today-chip"
            @click="emit('update:modelValue', today)">Today</button>
  </div>
</template>

<style scoped>
.day-nav {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px;
  background: var(--surface);
}
.arrow {
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 1.1rem;
  line-height: 1;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
}
.arrow:hover:not(:disabled) { background: var(--surface-2, rgba(127, 127, 127, 0.12)); }
.arrow:disabled { color: var(--muted-2); cursor: default; }
.label {
  position: relative;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 0.82rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
  min-width: 6.5rem;
}
.label:hover { background: var(--surface-2, rgba(127, 127, 127, 0.12)); }
/* The native input is the picker, not the display: it sits invisibly under
   the label so `showPicker()` anchors the calendar in the right place. */
.native {
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
  width: 100%;
}
.today-chip {
  border: 1px solid var(--accent, #38bdf8);
  color: var(--accent, #38bdf8);
  background: transparent;
  font-size: 0.68rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 3px 9px;
  margin-left: 4px;
  border-radius: 999px;
  cursor: pointer;
}
/* Off-today gets a visible edge on the control itself, in addition to the
   shell tint driven by data-day-relation. */
.day-nav[data-relation="past"] { border-color: color-mix(in srgb, var(--warn, #eab308) 55%, var(--border)); }
.day-nav[data-relation="future"] { border-color: color-mix(in srgb, var(--accent, #38bdf8) 55%, var(--border)); }

button:focus-visible { outline: 2px solid var(--accent, #38bdf8); outline-offset: 2px; }
</style>
