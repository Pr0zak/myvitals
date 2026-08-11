<script setup lang="ts">
/**
 * "Focus areas" — the reference's navigation grid.
 *
 * Replaces the neon home's pill list (Fasting / Sober / Steps / Workout),
 * which was yet another card style and mixed live values into what is
 * really navigation. Here each tile is a destination with a count of what
 * it holds, so the home stops trying to be both a dashboard and a menu.
 *
 * Counts come from data the home already loads; nothing extra is fetched
 * just to populate a label.
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";

const router = useRouter();

/** "3 tracked" per area, counted server-side from the tiles that actually
 *  have a value today — a constant subtitle would be decoration. */
const counts = ref<Record<string, { tracked: number; total: number }>>({});
onMounted(async () => {
  try {
    counts.value = (await api.summaryTiles()).focus_areas ?? {};
  } catch { /* the grid is still navigable without its counts */ }
});

function subtitle(key: string): string {
  const c = counts.value[key];
  return c ? `${c.tracked} tracked` : "Open";
}

/** Inline SVG paths rather than text glyphs. Half the glyphs (⬛, ⛰, ◐)
 *  fall back to a box or an emoji depending on the platform font, which is
 *  exactly the kind of inconsistency this redesign is meant to remove. */
const AREAS: Array<{
  key: string; label: string; d: string; route: string; tone: string;
// Tones follow the shell domain palette so a tile agrees with the chart it
// opens onto. Phone twin: the AREAS table in FocusAreas.kt.
}> = [
  { key: "heart", label: "Heart", route: "/heart-rate", tone: "#28e6ff",
    d: "M12 20s-7-4.6-7-9.5A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 7 3.5C19 15.4 12 20 12 20z" },
  { key: "sleep", label: "Sleep", route: "/sleep", tone: "#ff3ad8",
    d: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" },
  { key: "fitness", label: "Fitness", route: "/activities", tone: "#28e6ff",
    d: "M4 18l5-7 4 4 3-4 4 7z" },
  { key: "strength", label: "Training", route: "/workout/strength/today", tone: "#ff5d7a",
    d: "M4 9v6M7 7v10M17 7v10M20 9v6M7 12h10" },
  { key: "vitals", label: "Vitals", route: "/body", tone: "#28e6ff",
    d: "M3 12h4l2-5 3 10 2-6 2 3h5" },
  { key: "habits", label: "Habits", route: "/fasting", tone: "#ffb52e",
    d: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 3v5l3 2" },
  { key: "trails", label: "Trails", route: "/trails", tone: "#5dff3b",
    d: "M3 19l5-8 3.5 5L15 9l6 10z" },
  { key: "journal", label: "Journal", route: "/journal", tone: "#9b9bb0",
    d: "M5 4h9l5 5v11H5zM14 4v5h5M8 13h8M8 16h6" },
];
</script>

<template>
  <section class="fa">
    <h2 class="sect">Focus areas</h2>
    <div class="grid">
      <button v-for="a in AREAS" :key="a.key" class="area"
              @click="router.push(a.route)">
        <svg class="ico" viewBox="0 0 24 24" :style="{ color: a.tone }"
             fill="none" stroke="currentColor" stroke-width="1.7"
             stroke-linecap="round" stroke-linejoin="round">
          <path :d="a.d" />
        </svg>
        <span class="meta">
          <span class="lab">{{ a.label }}</span>
          <span class="sub">{{ subtitle(a.key) }}</span>
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.fa { margin: 18px 0; }
.sect {
  font-size: 1.35rem; font-weight: 400; color: #e9edf2;
  margin: 0 0 12px; letter-spacing: -0.2px;
}
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 10px;
}
.area {
  display: flex; align-items: center; gap: 10px;
  background: #1b1c1f; border: 0; border-radius: 18px;
  padding: 14px; cursor: pointer; text-align: left; min-width: 0;
}
.ico { width: 20px; height: 20px; flex: none; }
.meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.lab {
  font-size: .88rem; color: #e9edf2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sub { font-size: .7rem; color: #8d949d; }
</style>
