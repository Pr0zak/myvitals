<script setup lang="ts">
/**
 * The myvitals logo: a heart silhouette with an EKG/heartbeat trace
 * running through it. Same path data as the Android adaptive-icon
 * foreground (drawable/ic_launcher_foreground.xml) so the brand reads
 * the same on phone launcher and dashboard.
 *
 * Two render modes:
 *  - default: white heart on transparent bg (drop into any colored chip)
 *  - "tile":  white heart on the brand sky→violet gradient with rounded
 *             corners — used as the SideNav brand badge.
 */
withDefaults(defineProps<{
  size?: number;
  tile?: boolean;
}>(), { size: 24, tile: false });
</script>

<template>
  <span class="logo-wrap" :class="{ tile }" :style="{ width: size + 'px', height: size + 'px' }">
    <svg viewBox="22 22 64 64" :width="size" :height="size" aria-hidden="true">
      <!-- Heart silhouette (red) -->
      <path
        d="M54,76 C 54,76 30,60 30,46 C 30,38 36,33 43,33 C 49,33 52,36 54,40 C 56,36 59,33 65,33 C 72,33 78,38 78,46 C 78,60 54,76 54,76 Z"
        :fill="tile ? '#ffffff' : '#ef4444'"
      />
      <!-- EKG trace cutting across -->
      <path
        d="M30,52 L42,52 L46,46 L50,58 L54,40 L58,58 L62,46 L66,52 L78,52 L78,55 L66,55 L62,49 L58,61 L54,43 L50,61 L46,49 L42,55 L30,55 Z"
        :fill="tile ? '#0b1018' : '#ffffff'"
      />
    </svg>
  </span>
</template>

<style scoped>
.logo-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #ef4444;
}
.logo-wrap.tile {
  background: linear-gradient(135deg, #ef4444, #b91c1c);
  border-radius: 8px;
}
.logo-wrap.tile svg { transform: scale(1.05); }
</style>
