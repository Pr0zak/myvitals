<script setup lang="ts">
/**
 * "Unsaved changes · Discard / Save" — the ONE save model for Settings
 * forms (SETTINGS-B1).
 *
 * The old page had six: per-pane Save buttons, a separate fasting Save,
 * autosave-on-change for display, save-per-field for AI, and a step
 * schedule with its own button beside a base goal saved by a different
 * one. Two edits on one screen could need two different buttons, and an
 * edit you forgot to save was dropped without a word when you navigated.
 *
 * Sticky to the bottom of the viewport so it cannot scroll out of sight,
 * and only present when something is actually dirty. Errors show here, in
 * amber, and the edits stay in place so the save can be retried.
 */
defineProps<{
  saving: boolean;
  error: string | null;
}>();
const emit = defineEmits<{ (e: "save"): void; (e: "discard"): void }>();
</script>

<template>
  <div class="ubar" role="region" aria-label="Unsaved changes">
    <div class="ubar-in">
      <div class="ubar-msg" aria-live="polite">
        <strong>Unsaved changes</strong>
        <span v-if="error" class="ubar-err" role="alert">{{ error }}</span>
      </div>
      <button type="button" class="sf-btn" :disabled="saving" @click="emit('discard')">Discard</button>
      <button type="button" class="sf-btn primary" :disabled="saving" @click="emit('save')">
        {{ saving ? "Saving…" : "Save" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ubar {
  /* Clears the neon floating tab bar on phone widths (App.vue's one
     token for it; 0 on desktop, where the nav is a left rail). */
  position: sticky; bottom: calc(12px + var(--neon-bar-h, 0px)); z-index: 30; margin-top: 16px;
}
.ubar-in {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: #1e2230; border: 1px solid rgba(40, 230, 255, .45); border-radius: 16px;
  padding: 10px 12px; box-shadow: 0 10px 30px rgba(0, 0, 0, .5);
}
.ubar-msg { flex: 1; min-width: 160px; display: flex; flex-direction: column; gap: 2px; font-size: 14px; }
.ubar-err { color: #ffb52e; font-size: 12.5px; }
</style>
