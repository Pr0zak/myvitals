<script setup lang="ts">
/**
 * The myvitals logo: "orbit markers" — three quiet tracks with a fat endpoint
 * bead riding each, sleep (magenta) / move (lime) / recovery (cyan). The bead
 * is the same "today" marker the charts draw, so the logo is made of the app's
 * own vocabulary rather than a generic ring gauge.
 *
 * The beads sit at three different radii AND three different angles, which is
 * what stops the mark reading as a symmetric bullseye — and what lets it
 * survive the monochrome themed-icon variant, where colour is gone.
 *
 * Same mark as the Android adaptive icon (ic_launcher_foreground.xml) and the
 * favicon, so the brand reads identically on phone launcher, browser tab, and
 * dashboard.
 *
 * Two render modes:
 *  - default: rings on transparent (drop into any chip)
 *  - "tile":  rings on an obsidian rounded square — the SideNav brand badge
 */
withDefaults(defineProps<{
  size?: number;
  tile?: boolean;
}>(), { size: 24, tile: false });
</script>

<template>
  <span class="logo-wrap" :class="{ tile }" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" viewBox="0 0 108 108" aria-hidden="true">
      <!-- Quiet dotted tracks: where each bead has BEEN. Dropped from the
           Android launcher icon (VectorDrawable has no stroke-dasharray) and
           from the favicon, where they are sub-pixel. -->
      <path d="M25.36 58.54A29 29 0 0 1 44.56 26.58" fill="none" stroke="#23263A"
            stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0.1 4.2"/>
      <path d="M66.27 69.15A19.5 19.5 0 0 1 41.21 68.72" fill="none" stroke="#23263A"
            stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0.1 4.2"/>
      <path d="M57.58 44.66A10 10 0 0 1 63.82 55.91" fill="none" stroke="#23263A"
            stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0.1 4.2"/>
      <!-- The three orbits: sleep / move / recovery, outer to inner. -->
      <path d="M48.96 25.44A29 29 0 1 1 26.75 63.92" fill="none" stroke="#ff3ad8"
            stroke-width="4" stroke-linecap="round" opacity="0.9"/>
      <path d="M39.06 66.53A19.5 19.5 0 1 1 68.94 66.53" fill="none" stroke="#5dff3b"
            stroke-width="4" stroke-linecap="round" opacity="0.9"/>
      <path d="M63.4 57.42A10 10 0 1 1 55.74 44.15" fill="none" stroke="#28e6ff"
            stroke-width="4" stroke-linecap="round" opacity="0.9"/>
      <!-- The beads: the "today" endpoint marker, haloed like the charts. -->
      <circle cx="26.75" cy="63.92" r="8.6" fill="#ff3ad8" opacity="0.16"/>
      <circle cx="26.75" cy="63.92" r="6" fill="#ff3ad8"/>
      <circle cx="68.94" cy="66.53" r="8.1" fill="#5dff3b" opacity="0.16"/>
      <circle cx="68.94" cy="66.53" r="5.5" fill="#5dff3b"/>
      <circle cx="55.74" cy="44.15" r="7.6" fill="#28e6ff" opacity="0.16"/>
      <circle cx="55.74" cy="44.15" r="5" fill="#28e6ff"/>
    </svg>
  </span>
</template>

<style scoped>
.logo-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.logo-wrap.tile {
  background: #0f1118;
  border-radius: 9px;
}
.logo-wrap.tile svg { transform: scale(0.92); }
</style>
