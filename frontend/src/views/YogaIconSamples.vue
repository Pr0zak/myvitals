<script setup lang="ts">
/**
 * /yoga-icon-samples — visual audit of the Noun Project icon pack.
 * Shows every catalog exercise with its downloaded thumbnail so you
 * can spot inconsistencies, missing icons, or odd matches at a glance.
 *
 * Data: GET /workout/strength/exercises (full catalog, includes
 * image_front). Each PNG is served from /exercises/img/<id>/0.png.
 */
import { onMounted, ref, computed } from "vue";
import YogaPoseIcon from "@/components/YogaPoseIcon.vue";
import { api } from "@/api/client";
import type { StrengthExercise } from "@/api/types";

const exercises = ref<StrengthExercise[]>([]);
const loading = ref(true);
const error = ref<string>("");
const showOnly = ref<"all" | "yoga" | "strength" | "missing">("all");

onMounted(async () => {
  try {
    const r = await api.strengthExercises();
    exercises.value = r.exercises;
  } catch (e: any) {
    error.value = String(e?.message ?? e);
  } finally {
    loading.value = false;
  }
});

const filtered = computed(() => {
  const list = exercises.value;
  if (showOnly.value === "yoga") {
    return list.filter((e) => e.movement_pattern === "mobility");
  }
  if (showOnly.value === "strength") {
    return list.filter((e) => e.movement_pattern !== "mobility");
  }
  if (showOnly.value === "missing") {
    return list.filter((e) => !e.image_front);
  }
  return list;
});

const grouped = computed(() => {
  const m = new Map<string, StrengthExercise[]>();
  for (const e of filtered.value) {
    const k = e.movement_pattern || "other";
    if (!m.has(k)) m.set(k, []);
    m.get(k)!.push(e);
  }
  return Array.from(m.entries()).sort(([a], [b]) => {
    if (a === "mobility") return -1;
    if (b === "mobility") return 1;
    return a.localeCompare(b);
  });
});

const stats = computed(() => {
  const total = exercises.value.length;
  const have = exercises.value.filter((e) => e.image_front).length;
  return { total, have, missing: total - have };
});

function pretty(s: string): string {
  return s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const muscleNames = [
  "chest", "back", "shoulders", "abs", "biceps", "triceps",
  "forearms", "glutes", "quads", "hamstrings", "calves",
];
function imgUrl(rel: string | null | undefined): string {
  if (!rel) return "";
  // Same-origin: Caddy proxies /exercises/img/* to the backend.
  return rel;
}
</script>

<template>
  <main class="samples">
    <header class="hdr">
      <h1>Exercise icon pack</h1>
      <p class="hint" v-if="!loading && !error">
        {{ stats.have }}/{{ stats.total }} exercises have icons.
        Pack source: <a href="https://thenounproject.com" target="_blank">The Noun Project</a>
        (CC-BY). Yoga poses primarily by <strong>sachan</strong> +
        <strong>monkik</strong>; strength by <strong>Izwar Muis</strong> +
        <strong>SAM Designs</strong>.
      </p>
      <div class="filters">
        <button
          v-for="opt in (['all', 'yoga', 'strength', 'missing'] as const)"
          :key="opt"
          :class="{ active: showOnly === opt }"
          @click="showOnly = opt"
        >{{ opt }}</button>
      </div>
    </header>

    <div v-if="loading" class="empty">Loading catalog…</div>
    <div v-else-if="error" class="empty error">Error: {{ error }}</div>
    <div v-else-if="!filtered.length" class="empty">No exercises match.</div>

    <section v-else v-for="[pat, list] in grouped" :key="pat" class="group">
      <h2>{{ pretty(pat) }} <span class="ct">({{ list.length }})</span></h2>
      <div class="grid">
        <div v-for="ex in list" :key="ex.id" class="cell" :class="{ missing: !ex.image_front }">
          <div class="thumb">
            <div
              v-if="ex.image_front"
              class="masked"
              :style="`-webkit-mask-image: url('${imgUrl(ex.image_front)}'); mask-image: url('${imgUrl(ex.image_front)}')`"
              :title="ex.name"
            />
            <YogaPoseIcon
              v-else-if="ex.movement_pattern === 'mobility'"
              :id="ex.id"
              :size="48"
              :stroke="'#a78bfa'"
            />
            <span v-else class="placeholder">?</span>
          </div>
          <div class="meta">
            <div class="name">{{ ex.name }}</div>
            <div class="id">{{ ex.id }}</div>
          </div>
        </div>
      </div>
    </section>

    <section class="group">
      <h2>Muscle groups <span class="ct">(11)</span></h2>
      <p class="hint" style="margin: 0 0 0.7rem;">
        Anatomical icons (Rafiico Creative Studio + Hafiz Nur Lutfianto for hamstrings)
        served at <code>/exercises/img/muscle/&lt;name&gt;/0.png</code>. Resolver in
        <code>utils/muscleIcon.ts</code> consolidates the catalog's 17
        primary_muscle synonyms onto these 11 buckets.
      </p>
      <div class="grid">
        <div v-for="m in muscleNames" :key="m" class="cell">
          <div class="thumb">
            <div class="masked"
                 :style="`-webkit-mask-image: url('/exercises/img/muscle/${m}/0.png'); mask-image: url('/exercises/img/muscle/${m}/0.png')`"
                 :title="m"/>
          </div>
          <div class="meta">
            <div class="name">{{ m.charAt(0).toUpperCase() + m.slice(1) }}</div>
            <div class="id">muscle/{{ m }}</div>
          </div>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.samples { max-width: 1100px; margin: 0 auto; padding: 1.4rem 1rem 3rem; }
.hdr { margin-bottom: 1.4rem; }
.hdr h1 { margin: 0 0 0.4rem; }
.hint { color: var(--muted); font-size: 0.92rem; margin: 0 0 0.6rem; line-height: 1.5; }
.hint a { color: var(--accent); }
.hint strong { color: var(--text); font-weight: 600; }
.filters { display: flex; gap: 0.3rem; margin-top: 0.6rem; }
.filters button {
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--line);
  background: var(--bg-2);
  color: var(--muted);
  border-radius: 999px;
  font-size: 0.82rem;
  cursor: pointer;
  text-transform: capitalize;
  font-family: inherit;
}
.filters button.active {
  border-color: var(--accent);
  color: var(--text);
  background: rgba(167, 139, 250, 0.12);
}
.group { margin-top: 1.6rem; }
.group h2 {
  font-size: 0.78rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
  margin: 0 0 0.7rem;
}
.group h2 .ct { color: var(--muted); font-weight: 500; opacity: 0.7; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 0.7rem;
}
.cell {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.55rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-1);
}
.cell.missing { border-color: rgba(244, 114, 182, 0.4); background: rgba(244, 114, 182, 0.05); }
.thumb {
  width: 56px; height: 56px; flex: 0 0 56px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(167, 139, 250, 0.10);
  border-radius: 6px;
  overflow: hidden;
}
.thumb img { width: 100%; height: 100%; object-fit: contain; }
.masked {
  width: 100%; height: 100%;
  background: var(--accent, #a78bfa);
  -webkit-mask-size: contain; mask-size: contain;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
}
.placeholder { color: var(--muted); font-size: 1.4rem; }
.meta { min-width: 0; }
.name {
  font-size: 0.86rem;
  color: var(--text);
  font-weight: 500;
  line-height: 1.25;
  word-break: break-word;
}
.id {
  font-size: 0.7rem;
  color: var(--muted);
  font-family: 'Geist Mono', ui-monospace, monospace;
  margin-top: 2px;
}
.empty {
  padding: 2rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
}
.empty.error { color: var(--danger); }
</style>
