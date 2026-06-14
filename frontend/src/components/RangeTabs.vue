<script setup lang="ts" generic="T extends string | number">
/**
 * Accessible time-range selector pill row. Replaces the per-view hand-rolled
 * `<button v-for=... :class="{ active: range === r.key }">` blocks (each detail
 * view had its own copy with a different container class — .hdr / .head /
 * .ranges / .seg). One styled, keyboard-accessible source of truth.
 *
 * Generic over the key type so v-model stays type-safe whether a view keys its
 * ranges by string ('24h') or number (7 | 30 | 90).
 *
 * Usage:
 *   <RangeTabs v-model="range" :options="RANGES" aria-label="Heart-rate range" />
 *
 * `before` / `after` slots cover the cases where a view tucks an extra control
 * into the same row (e.g. HeartRate's PatternsLink).
 */
defineProps<{
  modelValue: T;
  options: ReadonlyArray<{ key: T; label: string }>;
  ariaLabel?: string;
  /** Greys out + disables the whole row (e.g. Weight's year-over-year mode,
   *  where the range pills don't apply). */
  disabled?: boolean;
}>();
defineEmits<{ (e: "update:modelValue", v: T): void }>();
</script>

<template>
  <div class="range-tabs" role="group" :aria-label="ariaLabel ?? 'Time range'">
    <slot name="before" />
    <button
      v-for="o in options"
      :key="String(o.key)"
      type="button"
      class="range-pill"
      :class="{ active: o.key === modelValue, dim: disabled }"
      :aria-pressed="o.key === modelValue"
      :disabled="disabled"
      @click="$emit('update:modelValue', o.key)"
    >{{ o.label }}</button>
    <slot name="after" />
  </div>
</template>

<style scoped>
.range-tabs { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
.range-pill {
  background: var(--surface); color: var(--muted);
  border: 1px solid var(--border); border-radius: var(--r-pill, 999px);
  padding: 0.3rem 0.85rem; cursor: pointer; font-size: 0.8rem;
  transition: background var(--motion-fast, 120ms), color var(--motion-fast, 120ms),
              border-color var(--motion-fast, 120ms);
}
.range-pill:hover { color: var(--text); }
.range-pill.active {
  background: var(--accent); color: var(--surface); border-color: var(--accent);
}
.range-pill.dim { opacity: 0.45; cursor: not-allowed; }
.range-pill.dim:hover { color: var(--muted); }
</style>
