<script setup lang="ts">
// MMAP-1: schematic front/back muscle map, each region shaded by weekly
// training-volume status (untrained/under/in_range/over) from
// GET /workout/strength/muscle-volume. Original artwork (no external asset).
import { computed } from "vue";
import { isNeon } from "@/theme";

const props = defineProps<{
  muscles: Record<string, { status?: string; sets?: number; mev?: number; mav?: number }>;
}>();

const SIL_FRONT =
  "M49,20 A11,12 0 1 1 71,20 A11,12 0 1 1 49,20 Z M56,34 L64,34 A12,12 0 0 1 76,46 L76,96 A12,12 0 0 1 64,108 L56,108 A12,12 0 0 1 44,96 L44,46 A12,12 0 0 1 56,34 Z M39,46 L39,46 A6,6 0 0 1 45,52 L45,92 A6,6 0 0 1 39,98 L39,98 A6,6 0 0 1 33,92 L33,52 A6,6 0 0 1 39,46 Z M81,46 L81,46 A6,6 0 0 1 87,52 L87,92 A6,6 0 0 1 81,98 L81,98 A6,6 0 0 1 75,92 L75,52 A6,6 0 0 1 81,46 Z M51,106 L52,106 A7,7 0 0 1 59,113 L59,185 A7,7 0 0 1 52,192 L51,192 A7,7 0 0 1 44,185 L44,113 A7,7 0 0 1 51,106 Z M68,106 L69,106 A7,7 0 0 1 76,113 L76,185 A7,7 0 0 1 69,192 L68,192 A7,7 0 0 1 61,185 L61,113 A7,7 0 0 1 68,106 Z";
const SIL_BACK =
  "M169,20 A11,12 0 1 1 191,20 A11,12 0 1 1 169,20 Z M176,34 L184,34 A12,12 0 0 1 196,46 L196,96 A12,12 0 0 1 184,108 L176,108 A12,12 0 0 1 164,96 L164,46 A12,12 0 0 1 176,34 Z M159,46 L159,46 A6,6 0 0 1 165,52 L165,92 A6,6 0 0 1 159,98 L159,98 A6,6 0 0 1 153,92 L153,52 A6,6 0 0 1 159,46 Z M201,46 L201,46 A6,6 0 0 1 207,52 L207,92 A6,6 0 0 1 201,98 L201,98 A6,6 0 0 1 195,92 L195,52 A6,6 0 0 1 201,46 Z M171,106 L172,106 A7,7 0 0 1 179,113 L179,185 A7,7 0 0 1 172,192 L171,192 A7,7 0 0 1 164,185 L164,113 A7,7 0 0 1 171,106 Z M188,106 L189,106 A7,7 0 0 1 196,113 L196,185 A7,7 0 0 1 189,192 L188,192 A7,7 0 0 1 181,185 L181,113 A7,7 0 0 1 188,106 Z";

const REGIONS: { muscle: string; d: string }[] = [
  { muscle: "shoulders", d: "M33,44 A8,7 0 1 0 49,44 A8,7 0 1 0 33,44 Z M71,44 A8,7 0 1 0 87,44 A8,7 0 1 0 71,44 Z" },
  { muscle: "chest", d: "M49,40 L54,40 A4,4 0 0 1 58,44 L58,51 A4,4 0 0 1 54,55 L49,55 A4,4 0 0 1 45,51 L45,44 A4,4 0 0 1 49,40 Z M66,40 L71,40 A4,4 0 0 1 75,44 L75,51 A4,4 0 0 1 71,55 L66,55 A4,4 0 0 1 62,51 L62,44 A4,4 0 0 1 66,40 Z" },
  { muscle: "biceps", d: "M35,50 L36,50 A4,4 0 0 1 40,54 L40,68 A4,4 0 0 1 36,72 L35,72 A4,4 0 0 1 31,68 L31,54 A4,4 0 0 1 35,50 Z M84,50 L85,50 A4,4 0 0 1 89,54 L89,68 A4,4 0 0 1 85,72 L84,72 A4,4 0 0 1 80,68 L80,54 A4,4 0 0 1 84,50 Z" },
  { muscle: "forearms", d: "M33,74 L33,74 A4,4 0 0 1 37,78 L37,92 A4,4 0 0 1 33,96 L33,96 A4,4 0 0 1 29,92 L29,78 A4,4 0 0 1 33,74 Z M87,74 L87,74 A4,4 0 0 1 91,78 L91,92 A4,4 0 0 1 87,96 L87,96 A4,4 0 0 1 83,92 L83,78 A4,4 0 0 1 87,74 Z" },
  { muscle: "abdominals", d: "M55,57 L65,57 A5,5 0 0 1 70,62 L70,92 A5,5 0 0 1 65,97 L55,97 A5,5 0 0 1 50,92 L50,62 A5,5 0 0 1 55,57 Z" },
  { muscle: "quadriceps", d: "M51,112 L52,112 A6,6 0 0 1 58,118 L58,152 A6,6 0 0 1 52,158 L51,158 A6,6 0 0 1 45,152 L45,118 A6,6 0 0 1 51,112 Z M68,112 L69,112 A6,6 0 0 1 75,118 L75,152 A6,6 0 0 1 69,158 L68,158 A6,6 0 0 1 62,152 L62,118 A6,6 0 0 1 68,112 Z" },
  { muscle: "traps", d: "M180,36 L194,44 L190,52 L170,52 L166,44 Z" },
  { muscle: "back", d: "M171,53 L189,53 A4,4 0 0 1 193,57 L193,67 A4,4 0 0 1 189,71 L171,71 A4,4 0 0 1 167,67 L167,57 A4,4 0 0 1 171,53 Z" },
  { muscle: "lats", d: "M163,66 L173,68 L170,90 L162,84 Z M197,66 L198,84 L190,90 L187,68 Z" },
  { muscle: "triceps", d: "M154,50 L155,50 A4,4 0 0 1 159,54 L159,69 A4,4 0 0 1 155,73 L154,73 A4,4 0 0 1 150,69 L150,54 A4,4 0 0 1 154,50 Z M205,50 L206,50 A4,4 0 0 1 210,54 L210,69 A4,4 0 0 1 206,73 L205,73 A4,4 0 0 1 201,69 L201,54 A4,4 0 0 1 205,50 Z" },
  { muscle: "lower_back", d: "M173,73 L187,73 A4,4 0 0 1 191,77 L191,85 A4,4 0 0 1 187,89 L173,89 A4,4 0 0 1 169,85 L169,77 A4,4 0 0 1 173,73 Z" },
  { muscle: "glutes", d: "M170,91 L174,91 A5,5 0 0 1 179,96 L179,103 A5,5 0 0 1 174,108 L170,108 A5,5 0 0 1 165,103 L165,96 A5,5 0 0 1 170,91 Z M186,91 L190,91 A5,5 0 0 1 195,96 L195,103 A5,5 0 0 1 190,108 L186,108 A5,5 0 0 1 181,103 L181,96 A5,5 0 0 1 186,91 Z" },
  { muscle: "hamstrings", d: "M172,110 L173,110 A6,6 0 0 1 179,116 L179,148 A6,6 0 0 1 173,154 L172,154 A6,6 0 0 1 166,148 L166,116 A6,6 0 0 1 172,110 Z M187,110 L188,110 A6,6 0 0 1 194,116 L194,148 A6,6 0 0 1 188,154 L187,154 A6,6 0 0 1 181,148 L181,116 A6,6 0 0 1 187,110 Z" },
  { muscle: "calves", d: "M172,156 L174,156 A5,5 0 0 1 179,161 L179,185 A5,5 0 0 1 174,190 L172,190 A5,5 0 0 1 167,185 L167,161 A5,5 0 0 1 172,156 Z M186,156 L188,156 A5,5 0 0 1 193,161 L193,185 A5,5 0 0 1 188,190 L186,190 A5,5 0 0 1 181,185 L181,161 A5,5 0 0 1 186,156 Z" },
];

// Active-status hues are vivid enough for light + dark; untrained/absent
// falls back to a theme-adaptive CSS var so it recedes into the silhouette.
// computed (not a frozen const) so a runtime theme switch recolors the map.
const ACTIVE = computed<Record<string, string>>(() => isNeon.value
  ? { under: "#ffb52e", in_range: "#5dff3b", over: "#ff5d7a" }
  : { under: "#facc15", in_range: "#22c55e", over: "#ef4444" });

function fillFor(muscle: string): string {
  const st = props.muscles?.[muscle]?.status;
  return (st && ACTIVE.value[st]) || "var(--bm-untrained)";
}
function titleFor(muscle: string): string {
  const m = props.muscles?.[muscle];
  const name = muscle.replace("_", " ");
  if (!m || !m.status || m.status === "untrained" || m.sets == null) return `${name}: untrained`;
  return `${name}: ${m.sets} sets (${m.status.replace("_", " ")})`;
}

const legend = computed(() => [
  { label: "Untrained", color: "var(--bm-untrained)" },
  { label: "Under", color: ACTIVE.value.under },
  { label: "In range", color: ACTIVE.value.in_range },
  { label: "Over", color: ACTIVE.value.over },
]);
</script>

<template>
  <div class="bodymap" :class="{ neon: isNeon }">
    <svg viewBox="0 0 240 200" class="bm-svg">
      <path :d="SIL_FRONT" class="bm-sil" />
      <path :d="SIL_BACK" class="bm-sil" />
      <path v-for="r in REGIONS" :key="r.muscle" :d="r.d"
            :fill="fillFor(r.muscle)" class="bm-region">
        <title>{{ titleFor(r.muscle) }}</title>
      </path>
      <text x="60" y="205" class="bm-label">FRONT</text>
      <text x="180" y="205" class="bm-label">BACK</text>
    </svg>
    <div class="bm-legend">
      <span v-for="l in legend" :key="l.label" class="bm-key">
        <i :style="{ background: l.color }"></i>{{ l.label }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.bodymap {
  --bm-sil: #d8dee9;
  --bm-untrained: #94a3b8;
}
:global(html[data-theme="dark"]) .bodymap,
:global(html.dark) .bodymap { --bm-sil: #2a2f3e; --bm-untrained: #475569; }
.bodymap.neon { --bm-sil: #232838; --bm-untrained: #3a3f52; }

.bm-svg { width: 100%; max-width: 360px; height: auto; display: block; margin: 0 auto; }
.bm-sil { fill: var(--bm-sil); }
.bm-region { stroke: var(--bg, #0f1118); stroke-width: 0.6; transition: fill 0.3s; }
.bm-label {
  fill: var(--muted); font-size: 9px; text-anchor: middle;
  font-family: 'Geist Mono', ui-monospace, monospace; letter-spacing: 0.1em;
}
.bm-legend {
  display: flex; flex-wrap: wrap; gap: 0.5rem 0.9rem; justify-content: center;
  margin-top: 0.5rem; font-size: 0.72rem; color: var(--muted);
}
.bm-key { display: inline-flex; align-items: center; gap: 0.3rem; }
.bm-key i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.bodymap.neon .bm-legend { color: #9b9bb0; }
</style>
