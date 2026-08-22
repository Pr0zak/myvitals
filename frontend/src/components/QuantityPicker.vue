<script setup lang="ts">
/**
 * Quantity + unit for a chosen food, offering the food's OWN measures.
 *
 * This exists because asking for a free-text unit makes the user guess at
 * something the app already knows. Raw chicken breast carries
 * `{oz: 28.25, package: 926, piece: 272}` from USDA — so "1 piece" is one
 * breast — but a blank box gives no hint that "piece" is a word this food
 * understands, and a plausible guess like "breast" or "each" resolves to
 * nothing.
 *
 * Every option shows what it weighs, and the live total underneath
 * confirms the conversion actually landed. A unit that cannot be
 * converted is never offered in the first place.
 */
import { computed } from "vue";
import type { Food } from "@/api/client";

const props = defineProps<{
  food: Food | null;
  quantity: string;
  unit: string;
}>();

const emit = defineEmits<{
  (e: "update:quantity", v: string): void;
  (e: "update:unit", v: string): void;
}>();

/** Mass units that are correct for any food, offered as a fallback for
 *  anyone who weighs things. Volume is deliberately absent: a cup of
 *  flour and a cup of honey differ by more than a factor of two, so a
 *  generic "cup" would be a wrong answer dressed as a convenience. */
const GENERIC: Array<[string, number]> = [
  ["g", 1],
  ["oz", 28.3495],
  ["lb", 453.592],
  ["kg", 1000],
];

const options = computed(() => {
  const own = Object.entries(props.food?.unit_grams ?? {})
    .sort((a, b) => a[1] - b[1])
    .map(([name, grams]) => ({
      value: name,
      label: `${name} — ${grams >= 1000 ? `${(grams / 1000).toFixed(2)} kg` : `${Math.round(grams)} g`}`,
      own: true,
    }));
  const ownNames = new Set(own.map((o) => o.value));
  const generic = GENERIC.filter((g) => !ownNames.has(g[0])).map(([name]) => ({
    value: name,
    label: name,
    own: false,
  }));
  return { own, generic };
});

/** What the current choice actually resolves to, mirroring the server's
 *  conversion. Shown so a mistyped or unmatched unit is visible before
 *  saving rather than turning into an unresolved line later. */
const preview = computed(() => {
  const qty = Number(props.quantity);
  if (!props.quantity || Number.isNaN(qty) || qty <= 0 || !props.unit) return null;
  const own = props.food?.unit_grams ?? {};
  const per = own[props.unit] ?? GENERIC.find((g) => g[0] === props.unit)?.[1];
  if (per == null) return null;
  const grams = qty * per;
  return grams >= 1000 ? `${(grams / 1000).toFixed(2)} kg` : `${Math.round(grams)} g`;
});
</script>

<template>
  <div class="qp">
    <div class="row">
      <input
        class="qty"
        type="number"
        step="any"
        min="0"
        placeholder="qty"
        :value="quantity"
        @input="emit('update:quantity', ($event.target as HTMLInputElement).value)"
      />
      <select
        class="unit"
        :value="unit"
        @change="emit('update:unit', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">unit…</option>
        <optgroup v-if="options.own.length" label="This food">
          <option v-for="o in options.own" :key="o.value" :value="o.value">
            {{ o.label }}
          </option>
        </optgroup>
        <optgroup label="By weight">
          <option v-for="o in options.generic" :key="o.value" :value="o.value">
            {{ o.label }}
          </option>
        </optgroup>
      </select>
    </div>
    <p v-if="preview" class="preview">= {{ preview }}</p>
    <p v-else-if="quantity && unit" class="unresolved">
      This food has no conversion for “{{ unit }}” — pick another unit or
      enter it by weight.
    </p>
  </div>
</template>

<style scoped>
.qp { display: flex; flex-direction: column; gap: 0.2rem; }
.row { display: flex; gap: 0.4rem; align-items: center; }
.qty { width: 84px; }
.unit { min-width: 150px; }
input, select {
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg-1);
  color: var(--fg); font: inherit; font-size: 0.82rem; padding: 0.32rem 0.4rem;
}
.preview { margin: 0; font-size: 0.74rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.unresolved { margin: 0; font-size: 0.74rem; color: #fbbf24; line-height: 1.4; }
</style>
