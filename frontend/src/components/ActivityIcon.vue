<script setup lang="ts">
/**
 * Per-activity-type Lucide icon. Falls back to a Dot for unknowns.
 * Covers Strava + Garmin + Health Connect activity-type vocabulary.
 */
import { computed } from "vue";
import {
  Activity, Bike, Dot, Dumbbell, Flame, Footprints, Mountain,
  PersonStanding, Sailboat, Snowflake, TentTree, User, Waves, Wind,
} from "lucide-vue-next";

const props = defineProps<{ type: string; size?: number }>();

const icon = computed(() => {
  const t = props.type.toLowerCase();
  // Cycling family
  if (t.includes("ride") || t.includes("bike") || t === "cycling" || t === "ebikeride")
    return Bike;
  if (t.includes("mountain")) return Mountain;
  // Running / walking
  if (t.includes("trailrun")) return Mountain;
  if (t === "run" || t === "running" || t.includes("trail_run")) return Footprints;
  if (t === "walk" || t === "walking") return PersonStanding;
  if (t === "hike" || t === "hiking") return TentTree;
  // Water
  if (t.includes("swim")) return Waves;
  if (t.includes("kayak") || t.includes("canoe") || t.includes("paddle")) return Sailboat;
  if (t.includes("row")) return Sailboat;
  if (t.includes("surf") || t.includes("sup")) return Waves;
  // Snow
  if (t.includes("ski") || t.includes("snow") || t.includes("snowboard"))
    return Snowflake;
  // Strength / fitness
  if (t.includes("strength") || t.includes("weight") || t.includes("lift"))
    return Dumbbell;
  if (t.includes("hiit") || t.includes("crossfit") || t === "workout")
    return Flame;
  if (t.includes("yoga") || t.includes("pilates") || t.includes("stretch"))
    return User;
  if (t.includes("indoor_cardio") || t.includes("treadmill") || t.includes("elliptical"))
    return Wind;
  if (t.includes("indoor")) return Activity;
  return Dot;
});
</script>

<template>
  <component :is="icon" :size="size ?? 18" :stroke-width="2" />
</template>
