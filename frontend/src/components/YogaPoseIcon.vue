<script setup lang="ts">
/**
 * Per-pose symbolic icon for the 15 yoga / mobility entries in the
 * catalog supplement. Each icon is a tiny stylised figure drawn as
 * inline SVG paths — not realistic, but visually distinct from the
 * other poses and from the generic "User" placeholder.
 *
 * Falls back to a generic "person" if the id isn't known.
 */
import { computed } from "vue";

const props = withDefaults(defineProps<{
  id: string;
  size?: number;
  stroke?: string;
}>(), { size: 24, stroke: "currentColor" });

// Each entry is the SVG <path d="..."> body. viewBox is 24×24.
// Minimal stroke-only line art; the parent passes color via stroke.
const PATHS: Record<string, string[]> = {
  // Inverted V — body slopes from feet (bottom-left) up to hips at the
  // peak then down to hands (bottom-right). Hands & feet pinned to floor.
  Downward_Dog: [
    "M3 20 L12 5 L21 20",
    "M3 20 h3", "M18 20 h3",
  ],
  // Knees on floor, body folded forward, arms reaching ahead.
  Childs_Pose: [
    "M4 20 h16",
    "M6 20 c0 -3 3 -8 9 -8",
    "M15 12 c2 0 3 1 4 2",
    "M5 20 a1.5 1.5 0 0 1 -2 0",
  ],
  // Arched-back wave (cat side: rounded; cow side: dipped).
  Cat_Cow: [
    "M4 13 c2 -4 6 -4 8 0 c2 4 6 4 8 0",
    "M4 13 v3", "M20 13 v3",
    "M4 16 h2 M18 16 h2",
  ],
  // Prone, chest lifting — reverse-comma shape.
  Cobra_Pose: [
    "M3 20 h18",
    "M21 20 c-4 0 -8 -2 -10 -4 c-2 -2 -4 -3 -8 -3",
    "M3 20 v-3",
  ],
  // One bent knee forward, body upright, back leg extended.
  Pigeon_Pose: [
    "M3 20 h18",
    "M6 20 l4 -8 l8 8",
    "M10 12 c0 -3 1 -5 3 -6",
  ],
  // Standing, hips hinged forward, head down past knees.
  Forward_Fold: [
    "M12 4 v8",
    "M12 12 c-2 1 -4 3 -5 7",
    "M12 12 c2 1 4 3 5 7",
    "M5 20 h14",
  ],
  // Lunge with arms outstretched horizontally.
  Warrior_2: [
    "M3 20 h18",
    "M9 20 v-7",      // front leg
    "M16 20 l-2 -8",  // back leg
    "M9 13 a2 2 0 1 1 0.1 0",  // head
    "M3 12 h12",      // arms
  ],
  // Front leg bent at right angle, top hand toward floor, bottom hand up.
  Triangle_Pose: [
    "M4 20 L20 20 L12 4 Z",
    "M12 4 v3",
  ],
  // Seated, legs forward, body folded over knees.
  Seated_Forward_Bend: [
    "M3 20 h18",
    "M3 20 c4 -1 8 -2 14 -4",
    "M17 16 c0 -2 -1 -3 -3 -3",
  ],
  // Lying on back, knees pulled across the body.
  Reclined_Spinal_Twist: [
    "M3 17 h18",
    "M5 17 c2 -3 6 -3 8 -1",
    "M13 16 c1 -3 4 -4 6 -3",
    "M19 13 a1.5 1.5 0 1 1 0.1 0",
  ],
  // Arch / bridge — body lifted, shoulders + feet on floor.
  Bridge_Pose: [
    "M3 20 h18",
    "M5 20 c2 -8 12 -8 14 0",
    "M5 20 v-3", "M19 20 v-3",
  ],
  // Low lunge — sharper Pigeon. Front foot wide, hands inside.
  Lizard_Pose: [
    "M3 20 h18",
    "M7 20 l3 -7",
    "M16 20 l-3 -10",
    "M10 13 c0 -2 2 -3 3 -3",
  ],
  // Deeper pigeon — torso folded over front shin.
  Half_Pigeon_Forward_Fold: [
    "M3 20 h18",
    "M5 20 l5 -6 l8 6",
    "M10 14 c-2 1 -3 3 -3 5",
  ],
  // Tabletop, one arm threading under the other shoulder.
  Thread_The_Needle: [
    "M3 17 h18",
    "M7 17 v-5", "M16 17 v-5",
    "M7 12 h9",
    "M9 12 c-1 2 -3 3 -5 4",
  ],
  // Lying on back, holding feet, knees toward armpits.
  Happy_Baby: [
    "M3 18 h18",
    "M6 18 c0 -2 1 -4 3 -4 c0 -3 2 -5 4 -5",
    "M18 18 c0 -2 -1 -4 -3 -4 c0 -3 -2 -5 -4 -5",
  ],
};

const paths = computed(() => PATHS[props.id] ?? null);
</script>

<template>
  <svg
    :width="size" :height="size" viewBox="0 0 24 24"
    fill="none"
    :stroke="stroke" stroke-width="1.6"
    stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true">
    <template v-if="paths">
      <path v-for="(d, i) in paths" :key="i" :d="d"/>
    </template>
    <template v-else>
      <!-- Generic mobility fallback: standing person -->
      <circle cx="12" cy="6" r="2"/>
      <path d="M12 8 v6 M9 14 l3 -2 l3 2 M9 20 l3 -6 l3 6"/>
    </template>
  </svg>
</template>
