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
/* Material 3 Expressive button group.
   M3 Expressive replaced the row-of-equal-outlined-chips pattern with button
   groups, whose defining behaviour is that the SELECTED item widens and its
   neighbours yield. This control sits at the top of every detail view and is
   the most-clicked thing in the app; four identical pills make the current
   range something you read rather than see.
   The widening uses a slightly overshooting curve rather than a linear ease —
   M3 Expressive swapped easing/duration for a motion-physics model, and the
   overshoot is what makes the control feel like it has weight. */
.range-tabs {
  display: flex; gap: 0.25rem; align-items: center;
  background: var(--bg, #0f1118); padding: 0.25rem;
  border-radius: var(--r-pill, 999px);
}
.range-pill {
  flex: 1 1 0; min-width: 0;
  background: transparent; color: var(--muted);
  border: 0; border-radius: var(--r-pill, 999px);
  padding: 0.42rem 0.6rem; cursor: pointer; font-size: 0.8rem;
  white-space: nowrap; text-overflow: clip;
  transition: flex-grow 320ms cubic-bezier(.2, .9, .24, 1.15),
              background var(--motion-fast, 140ms),
              color var(--motion-fast, 140ms);
}
.range-pill:hover { color: var(--text); }
.range-pill.active {
  flex-grow: 2.1;
  background: var(--accent); color: var(--surface);
  font-weight: 600;
}
.range-pill.dim { opacity: 0.45; cursor: not-allowed; }
.range-pill.dim:hover { color: var(--muted); }

/* Slotted extras (e.g. HeartRate's PatternsLink) must not be stretched by the
   flex distribution the pills rely on. */
.range-tabs > :not(.range-pill) { flex: 0 0 auto; }

@media (prefers-reduced-motion: reduce) {
  .range-pill { transition: background 140ms, color 140ms; }
}
</style>
