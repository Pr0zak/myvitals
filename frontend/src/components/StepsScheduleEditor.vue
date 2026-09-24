<script setup lang="ts">
/**
 * DOW-1 — per-weekday step goals.
 *
 * Sparse by design: a blank day means "use the base goal", not zero. That
 * is what lets someone set a lower Saturday without restating the other
 * six, and it is why every input here starts empty rather than
 * pre-filled with the base — a pre-filled field would silently write six
 * overrides the user never asked for.
 *
 * SETTINGS-B1: now a CONTROLLED editor with no Save button of its own. It
 * used to sit under Display with its own button, while the base goal it
 * falls back to was on Profile behind a different one — two screens and
 * two saves for one idea. It now sits directly under the base goal on
 * Settings → You and is saved by that page's single Save.
 */
import { computed } from "vue";

const props = defineProps<{
  /** Draft text per weekday key; "" = use the base goal. */
  modelValue: Record<string, string>;
  weekdays: string[];
  /** The base goal as currently entered (unsaved edits included), so the
   *  placeholder always shows what a blank day would fall back to. */
  base: number | null;
  /** Server-resolved goal for today, as last saved. */
  effectiveToday?: number | null;
}>();
const emit = defineEmits<{ (e: "update:modelValue", v: Record<string, string>): void }>();

const LABELS: Record<string, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu",
  fri: "Fri", sat: "Sat", sun: "Sun",
};
const FULL: Record<string, string> = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday",
  fri: "Friday", sat: "Saturday", sun: "Sunday",
};

const anyOverride = computed(() =>
  Object.values(props.modelValue).some((v) => (v ?? "").trim() !== ""),
);

function set(k: string, v: string) {
  emit("update:modelValue", { ...props.modelValue, [k]: v });
}
</script>

<template>
  <fieldset class="sched">
    <legend class="sf-label">Different goal on some days</legend>
    <p class="sf-help">
      Leave a day blank to use your usual goal<template v-if="base != null">
        ({{ base.toLocaleString() }})</template>.
    </p>
    <div class="grid">
      <label v-for="k in weekdays" :key="k" class="day">
        <span aria-hidden="true">{{ LABELS[k] ?? k }}</span>
        <input class="sf-input" type="number" min="1" step="500" inputmode="numeric"
               :aria-label="`${FULL[k] ?? k} step goal`"
               :placeholder="base != null ? String(base) : ''"
               :value="modelValue[k] ?? ''"
               @input="set(k, ($event.target as HTMLInputElement).value)"/>
      </label>
    </div>
    <p class="sf-help foot">
      <span v-if="effectiveToday != null">Today's goal: {{ effectiveToday.toLocaleString() }}. </span>
      <span v-if="!anyOverride">No overrides — every day uses the base goal.</span>
    </p>
  </fieldset>
</template>

<style scoped>
.sched { border: 0; padding: 0; margin: 12px 0 0; min-width: 0; }
.sched legend { padding: 0; margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(76px, 1fr)); gap: 8px; margin-top: 8px; }
.day { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #9b9bb0; margin: 0; }
.day .sf-input { padding: 8px; text-align: center; }
.foot { margin: 8px 0 0; }
</style>
