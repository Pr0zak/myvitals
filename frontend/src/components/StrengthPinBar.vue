<script setup lang="ts">
/** Slim one-line bar pinned to the top of the active-workout page while the
 *  NOW hero is scrolled out of view. Pure display: every value is passed in
 *  from the hero's own state, nothing is derived here. No Log button —
 *  logging needs a rating, and the rating lives in the hero. */
import { ChevronUp } from "lucide-vue-next";

defineProps<{
  show: boolean;
  name: string;
  setLabel: string;          // "Set 2 of 4"
  value: string;             // "25 × 10" / "BW × 12" / "40s hold"
  rest: string | null;       // "Rest 0:52" while the rest timer runs
}>();
defineEmits<{ (e: "back"): void }>();
</script>

<template>
  <!-- Zero-height sticky anchor: pins to the column's top edge without
       reserving layout space, so the page never jumps when the bar appears. -->
  <div class="pin-anchor">
    <Transition name="pin">
      <button v-if="show" type="button" class="pin-bar" aria-label="Back to current set"
              @click="$emit('back')">
        <span class="dot" aria-hidden="true" />
        <span class="name">{{ name }}</span>
        <span class="set">{{ setLabel }}</span>
        <span v-if="rest" class="val rest">{{ rest }}</span>
        <span v-else class="val">{{ value }}</span>
        <ChevronUp class="chev" :size="18" aria-hidden="true" />
      </button>
    </Transition>
  </div>
</template>

<style scoped>
.pin-anchor { position: sticky; top: 0; height: 0; z-index: 30; }
.pin-bar {
  position: absolute; top: 0; left: -20px; right: -20px; /* bleed across NeonPage's 20px padding */
  display: flex; align-items: center; gap: 8px;
  height: 48px; padding: 0 16px; box-sizing: border-box;
  background: var(--rn-card, #181b27); color: var(--rn-ink, #ececf5);
  border: 0; border-bottom: 1px solid color-mix(in srgb, var(--rn-cyan, #28e6ff) 55%, transparent);
  border-radius: 0 0 12px 12px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, .35);
  font: inherit; font-size: 14px; text-align: left; cursor: pointer; min-width: 0;
}
.pin-bar:focus-visible { outline: 2px solid var(--rn-cyan, #28e6ff); outline-offset: -2px; }
.dot { flex: none; width: 8px; height: 8px; border-radius: 50%;
  background: var(--rn-cyan, #28e6ff); box-shadow: 0 0 8px var(--rn-cyan, #28e6ff); }
.name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 600; }
.set { flex: none; color: var(--rn-mut, #9b9bb0); font-size: 12px; white-space: nowrap; }
.val { flex: none; white-space: nowrap; font-family: 'Space Grotesk', monospace; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.val.rest { color: var(--rn-cyan, #28e6ff); }
.chev { flex: none; color: var(--rn-mut, #9b9bb0); }

.pin-enter-active, .pin-leave-active { transition: transform .18s ease, opacity .18s ease; }
.pin-enter-from, .pin-leave-to { transform: translateY(-100%); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .pin-enter-active, .pin-leave-active { transition: none; }
}
</style>
