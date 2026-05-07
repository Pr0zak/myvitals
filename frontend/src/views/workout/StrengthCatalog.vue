<script setup lang="ts">
/**
 * /workout/strength/catalog — every exercise the user can do given
 * their current equipment, with controls to favorite / disable /
 * mark "avoid" (picked only as a last resort).
 *
 * Backed by:
 *   GET  /workout/strength/exercises    — full catalog (~224 entries)
 *   GET  /workout/strength/equipment    — current equipment + prefs
 *   PUT  /workout/strength/exercises/{id}/pref  — toggle a pref
 */
import { computed, onMounted, ref } from "vue";
import { Star, Ban, ThumbsDown } from "lucide-vue-next";
import { api } from "@/api/client";
import { apiBase, queryToken } from "@/config";
import Card from "@/components/Card.vue";
import type { StrengthEquipment, StrengthExercise } from "@/api/types";

const exercises = ref<StrengthExercise[]>([]);
const equipment = ref<StrengthEquipment | null>(null);
const prefs = ref<Record<string, string>>({});
const loading = ref(true);
const error = ref<string>("");
const filter = ref<"available" | "all">("available");

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const [catRes, eqRes] = await Promise.all([
      api.strengthExercises(),
      api.strengthEquipment(),
    ]);
    exercises.value = catRes.exercises;
    equipment.value = eqRes.payload;
    prefs.value = (eqRes.payload as unknown as { exercise_prefs?: Record<string, string> })
      .exercise_prefs ?? {};
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function isAvailable(ex: StrengthExercise): boolean {
  if (!equipment.value) return false;
  const e = equipment.value;
  for (const tag of ex.equipment) {
    if (tag === "bodyweight") continue;
    if (tag === "bench" && !(e.bench.flat || e.bench.incline || e.bench.decline)) return false;
    if (tag === "dumbbell" && e.dumbbells.type === "none") return false;
    if (tag === "barbell" && !e.barbell) return false;
    if (tag === "cable" && !e.cable_stack) return false;
    if (tag === "kettlebell" && e.kettlebells_lb.length === 0) return false;
    if (tag === "bands" && !e.resistance_bands) return false;
  }
  return true;
}

const visible = computed<StrengthExercise[]>(() => {
  if (filter.value === "all") return exercises.value;
  return exercises.value.filter(isAvailable);
});

const groupedByMuscle = computed(() => {
  const groups: Record<string, StrengthExercise[]> = {};
  for (const ex of visible.value) {
    (groups[ex.primary_muscle] ??= []).push(ex);
  }
  for (const list of Object.values(groups)) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }
  return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
});

const counts = computed(() => {
  const total = visible.value.length;
  const fav = visible.value.filter((e) => prefs.value[e.id] === "favorite").length;
  const dis = visible.value.filter((e) => prefs.value[e.id] === "disabled").length;
  const avo = visible.value.filter((e) => prefs.value[e.id] === "avoid").length;
  return { total, fav, dis, avo };
});

async function setPref(exId: string, p: "neutral" | "favorite" | "disabled" | "avoid") {
  const cur = prefs.value[exId];
  // Toggle: clicking the active state sets it back to neutral
  const next = cur === p ? "neutral" : p;
  try {
    await api.setExercisePref(exId, next);
    if (next === "neutral") {
      const copy = { ...prefs.value };
      delete copy[exId];
      prefs.value = copy;
    } else {
      prefs.value = { ...prefs.value, [exId]: next };
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

function image(ex: StrengthExercise): string | null {
  if (!ex.image_front) return null;
  const base = (apiBase.value || "/api").replace(/\/$/, "");
  return `${base}${ex.image_front}`;
}

onMounted(load);
</script>

<template>
  <main class="catalog">
    <header>
      <h1>Strength catalog</h1>
      <div class="filter">
        <label><input type="radio" value="available" v-model="filter"/> Available ({{ counts.total }})</label>
        <label><input type="radio" value="all" v-model="filter"/> All</label>
      </div>
    </header>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load the catalog.</p>
    <p v-else-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <Card v-else :flat="true">
      <p class="hint">
        ⭐ favorite — picked first when filling a slot ·
        🚫 disabled — never picked ·
        👎 avoid — picked only as last resort ·
        neutral (no icon) — default behaviour
      </p>
      <p class="hint">
        <strong>{{ counts.fav }}</strong> favorited ·
        <strong>{{ counts.dis }}</strong> disabled ·
        <strong>{{ counts.avo }}</strong> avoided
        of {{ counts.total }} {{ filter === "available" ? "available" : "total" }}
      </p>
    </Card>

    <section v-for="[muscle, list] in groupedByMuscle" :key="muscle" class="group">
      <h2>{{ muscle.replace('_', ' ') }} · {{ list.length }}</h2>
      <ul class="list">
        <li v-for="ex in list" :key="ex.id" :class="{
          fav: prefs[ex.id] === 'favorite',
          disabled: prefs[ex.id] === 'disabled',
          avoid: prefs[ex.id] === 'avoid',
          unavailable: !isAvailable(ex),
        }">
          <img v-if="image(ex)" :src="image(ex) ?? ''" :alt="ex.name" />
          <div v-else class="ph"></div>
          <div class="meta">
            <strong>{{ ex.name }}</strong>
            <span class="tags">
              {{ ex.movement_pattern.replace('_', ' ') }}
              · {{ ex.equipment.join(' + ') }}
              · {{ ex.level }}
            </span>
          </div>
          <div class="actions">
            <button class="act fav" :class="{ on: prefs[ex.id] === 'favorite' }"
                    @click="setPref(ex.id, 'favorite')" title="Favorite">
              <Star :size="16" />
            </button>
            <button class="act avoid" :class="{ on: prefs[ex.id] === 'avoid' }"
                    @click="setPref(ex.id, 'avoid')" title="Avoid (last resort)">
              <ThumbsDown :size="16" />
            </button>
            <button class="act dis" :class="{ on: prefs[ex.id] === 'disabled' }"
                    @click="setPref(ex.id, 'disabled')" title="Disable (never pick)">
              <Ban :size="16" />
            </button>
          </div>
        </li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.catalog { max-width: 880px; }
header { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem; }
header h1 { margin: 0; }
.filter label { margin-left: 0.6rem; font-size: 0.85rem; color: var(--muted); }
.hint { color: var(--muted); font-size: 0.85rem; margin: 0.3rem 0; }
.hint strong { color: var(--text); }
.err { color: #f87171; }

.group { margin-bottom: 1.4rem; }
.group h2 {
  font-size: 0.78rem; color: var(--muted); letter-spacing: 0.08em;
  margin: 0.6rem 0 0.4rem; font-weight: 600;
  text-transform: capitalize;
}
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column;
  gap: 0.3rem; }
.list li {
  display: grid;
  grid-template-columns: 56px 1fr auto;
  align-items: center;
  gap: 0.7rem;
  padding: 0.5rem 0.7rem;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px;
}
.list li.fav { border-left: 3px solid #f59e0b; }
.list li.disabled { opacity: 0.5; border-left: 3px solid #ef4444; }
.list li.avoid { opacity: 0.7; border-left: 3px solid #94a3b8; }
.list li.unavailable { opacity: 0.4; }

.list img, .list .ph {
  width: 56px; height: 56px; border-radius: 6px;
  background: #111; object-fit: cover;
}
.list .ph { background: var(--bg-1); border: 1px dashed var(--line); }
.meta { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.meta strong { color: var(--text); font-size: 0.92rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tags { color: var(--muted); font-size: 0.74rem;
  font-family: 'Geist Mono', ui-monospace, monospace; }

.actions { display: flex; gap: 0.25rem; }
.act {
  width: 32px; height: 32px; border-radius: 6px;
  background: var(--bg-1); border: 1px solid var(--line);
  color: var(--muted); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
}
.act:hover { color: var(--text); }
.act.fav.on  { background: rgba(245, 158, 11, 0.18); color: #f59e0b; border-color: #f59e0b66; }
.act.avoid.on { background: rgba(148, 163, 184, 0.2); color: #94a3b8; border-color: #94a3b855; }
.act.dis.on  { background: rgba(239, 68, 68, 0.18); color: #ef4444; border-color: #ef444466; }
</style>
