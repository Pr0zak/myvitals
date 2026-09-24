<script setup lang="ts">
/**
 * Settings → Units & display — SETTINGS-B1. Phone twin: `SettingsDisplayScreen.kt`.
 *
 * Theme, units, time format and the Key-metrics order. These AUTOSAVE —
 * they are choices you want to see take effect as you make them — but
 * visibly: each change reports "Saved" or an amber failure. The old pane
 * autosaved in total silence, so a failed sync left the phone on the old
 * units with nothing saying why.
 *
 * On failure the two halves behave differently, on purpose:
 *   - Theme / units / time format stay applied in this browser (they are
 *     local-first — see displayPrefs.ts — and reverting the theme you just
 *     clicked because the network hiccupped would be hostile). The page
 *     says they were not saved to your account and offers Retry.
 *   - The Key-metrics order lives only on the server, so a failed save
 *     puts the list back to the last order the server accepted.
 *
 * The data-health card that used to be buried here moved to Connection,
 * and the weekday step goals moved under the step goal on You.
 */
import { computed, onMounted } from "vue";
import { units } from "@/units";
import { timeFormat } from "@/format";
import { themeChoice } from "@/theme";
import { queryToken } from "@/config";
import { displaySync, retryDisplaySync } from "@/displayPrefs";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import TileOrderEditor from "@/components/TileOrderEditor.vue";
import "@/components/settings/settingsForm.css";

const THEMES = [
  { value: "neon", label: "Vitality Neon" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "auto", label: "Match system" },
] as const;

// A "Saved" left over from an earlier visit says nothing about this one.
onMounted(() => {
  if (displaySync.value.state === "saved") displaySync.value = { state: "idle", error: null, at: 0 };
});

const syncText = computed(() => {
  if (!queryToken.value) return null;
  switch (displaySync.value.state) {
    case "saving": return "Saving…";
    case "saved": return "Saved";
    default: return null;
  }
});
</script>

<template>
  <NeonPage title="Units & display" back="/settings">
    <NeonEyebrow>Appearance</NeonEyebrow>
    <section class="sf-card">
      <fieldset class="sf-choices">
        <legend>Theme</legend>
        <label v-for="t in THEMES" :key="t.value" class="sf-choice">
          <input v-model="themeChoice" type="radio" name="theme" :value="t.value" />
          <span>{{ t.label }}</span>
        </label>
      </fieldset>
    </section>

    <NeonEyebrow>Units</NeonEyebrow>
    <section class="sf-card">
      <fieldset class="sf-choices">
        <legend>Measurements</legend>
        <label class="sf-choice">
          <input v-model="units" type="radio" name="units" value="imperial" />
          <span>Imperial (mi, lb, °F)</span>
        </label>
        <label class="sf-choice">
          <input v-model="units" type="radio" name="units" value="metric" />
          <span>Metric (km, kg, °C)</span>
        </label>
      </fieldset>
      <fieldset class="sf-choices tf">
        <legend>Time format</legend>
        <label class="sf-choice">
          <input v-model="timeFormat" type="radio" name="tf" value="auto" />
          <span>Match system</span>
        </label>
        <label class="sf-choice">
          <input v-model="timeFormat" type="radio" name="tf" value="12h" />
          <span>12-hour (7:35 PM)</span>
        </label>
        <label class="sf-choice">
          <input v-model="timeFormat" type="radio" name="tf" value="24h" />
          <span>24-hour (19:35)</span>
        </label>
      </fieldset>
    </section>

    <div class="sync" aria-live="polite">
      <span v-if="!queryToken" class="sf-mut">
        Saved in this browser. Sign in under Connection to keep these on your account and the phone.
      </span>
      <span v-else-if="syncText" :class="displaySync.state === 'saved' ? 'sf-ok' : 'sf-mut'">{{ syncText }}</span>
      <span v-if="queryToken && displaySync.state === 'failed'" class="sf-err" role="alert">
        Applied here, but not saved to your account, so the phone won't see it
        ({{ displaySync.error }}).
        <button type="button" class="sf-btn" @click="retryDisplaySync">Retry</button>
      </span>
    </div>

    <NeonEyebrow>Key metrics</NeonEyebrow>
    <section class="sf-card">
      <TileOrderEditor v-if="queryToken" />
      <p v-else class="sf-mut">Sign in under Connection to arrange your Key metrics.</p>
    </section>
  </NeonPage>
</template>

<style scoped>
.tf { margin-top: 16px; }
.sync { min-height: 24px; margin: -4px 0 4px; display: flex; flex-direction: column; gap: 6px; }
.sync .sf-err { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
</style>
