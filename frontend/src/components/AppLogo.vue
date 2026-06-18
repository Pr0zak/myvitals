<script setup lang="ts">
/**
 * The myvitals logo: three concentric "vitality" rings — sleep (magenta),
 * move (lime), recovery (cyan) — the same trio the Today/rings home draws.
 * Same mark as the Android adaptive icon (ic_launcher_foreground.xml) and
 * the favicon, so the brand reads identically on phone launcher, browser
 * tab, and dashboard.
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
      <g fill="none" stroke-linecap="round" stroke-width="9" transform="rotate(-90 54 54)">
        <circle cx="54" cy="54" r="38" stroke="#ff3ad8" stroke-dasharray="181 999"
          style="filter: drop-shadow(0 0 2px rgba(255,58,216,.55))" />
        <circle cx="54" cy="54" r="26.5" stroke="#5dff3b" stroke-dasharray="117 999"
          style="filter: drop-shadow(0 0 2px rgba(93,255,59,.55))" />
        <circle cx="54" cy="54" r="15" stroke="#28e6ff" stroke-dasharray="77 999"
          style="filter: drop-shadow(0 0 2px rgba(40,230,255,.55))" />
      </g>
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
