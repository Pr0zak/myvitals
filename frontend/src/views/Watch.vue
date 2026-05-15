<script setup lang="ts">
/**
 * Dedicated Pixel-Watch status view. Renders the WatchStatus tile
 * full-width plus a config-link footer pointing at the HA section
 * in Settings. The tile component itself owns polling + the live
 * "Xm ago" tick.
 */
import { RouterLink } from "vue-router";
import WatchStatus from "@/components/today/WatchStatus.vue";
</script>

<template>
  <div class="watch-view">
    <header class="hdr">
      <h1>Watch</h1>
      <p class="muted">
        Realtime Pixel Watch liveness from Home Assistant — battery,
        on-body, charging, activity state. Heart rate / HRV / sleep
        continue to come from Health Connect (Wear OS Companion App
        publishes HR too sparsely for HA to replace HC).
      </p>
    </header>

    <WatchStatus/>

    <p class="cfg-hint">
      Configure HA URL + token in
      <RouterLink to="/settings">Settings</RouterLink>
      under "Home Assistant (watch status)".
    </p>
  </div>
</template>

<style scoped>
.watch-view { max-width: 720px; margin: 0 auto; padding: 1rem; }
.hdr { margin-bottom: 1rem; }
h1 { margin: 0 0 0.5rem; }
.muted { color: var(--muted); font-size: 0.9rem; max-width: 60ch; }
.cfg-hint { margin-top: 1.5rem; font-size: 0.85rem; color: var(--muted); }
.cfg-hint a { color: #38bdf8; }
</style>
