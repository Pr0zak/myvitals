<script setup lang="ts">
import polylineDecoder from "@mapbox/polyline";
import { computed } from "vue";

const props = withDefaults(defineProps<{
  polyline: string | null | undefined;
  size?: number;
  stroke?: string;
  strokeWidth?: number;
}>(), {
  size: 80,
  stroke: "var(--accent)",
  strokeWidth: 2,
});

const path = computed(() => {
  if (!props.polyline) return null;
  let coords: [number, number][];
  try {
    coords = polylineDecoder.decode(props.polyline) as [number, number][];
  } catch {
    return null;
  }
  if (coords.length < 2) return null;

  // Find bounding box
  const lats = coords.map((c) => c[0]);
  const lngs = coords.map((c) => c[1]);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  // Mercator-ish: latitude needs scaling so the aspect ratio looks right.
  const latSpan = maxLat - minLat;
  const lngSpan = maxLng - minLng;
  // Scale to fit a unit square with 5% padding.
  const span = Math.max(latSpan, lngSpan, 1e-6);
  const padding = 0.05;
  const scale = (1 - 2 * padding) / span;

  // Centre offsets so the route is centred when one axis is shorter
  const xOffset = padding + (1 - 2 * padding - lngSpan * scale) / 2;
  const yOffset = padding + (1 - 2 * padding - latSpan * scale) / 2;

  const pts = coords.map(([lat, lng]) => {
    const x = xOffset + (lng - minLng) * scale;
    // Flip Y because SVG origin is top-left
    const y = 1 - (yOffset + (lat - minLat) * scale);
    return `${(x * props.size).toFixed(2)},${(y * props.size).toFixed(2)}`;
  });
  return `M${pts.join(" L")}`;
});

const startEnd = computed(() => {
  if (!path.value) return null;
  // Extract first and last points from the path string for start/end markers.
  const m = path.value.match(/M([\d.]+),([\d.]+).*?([\d.]+),([\d.]+)$/);
  if (!m) return null;
  return {
    start: { x: +m[1], y: +m[2] },
    end: { x: +m[3], y: +m[4] },
  };
});
</script>

<template>
  <svg
    v-if="path"
    :width="size" :height="size"
    :viewBox="`0 0 ${size} ${size}`"
    class="poly-thumb"
    aria-hidden="true"
  >
    <path :d="path!" :stroke="stroke" :stroke-width="strokeWidth" fill="none"
          stroke-linecap="round" stroke-linejoin="round"/>
    <circle v-if="startEnd" :cx="startEnd.start.x" :cy="startEnd.start.y" r="3" fill="#22c55e"/>
    <circle v-if="startEnd" :cx="startEnd.end.x" :cy="startEnd.end.y" r="3" fill="#ef4444"/>
  </svg>
  <div v-else class="poly-thumb empty" :style="{ width: size + 'px', height: size + 'px' }">—</div>
</template>

<style scoped>
.poly-thumb {
  background: var(--surface-2);
  border-radius: 6px;
  display: block;
  flex-shrink: 0;
}
.poly-thumb.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted-2);
  font-size: 0.8rem;
}
</style>
