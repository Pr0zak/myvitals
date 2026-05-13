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
import {
  Star, Ban, ThumbsDown, Play,
  User, Dumbbell, PersonStanding, Activity as ActivityIcon,
} from "lucide-vue-next";
import YogaPoseIcon from "@/components/YogaPoseIcon.vue";
import { api } from "@/api/client";
import { apiBase, queryToken } from "@/config";
import Card from "@/components/Card.vue";
import { muscleIcon, muscleLabel } from "@/utils/muscleIcon";
import type { StrengthEquipment, StrengthExercise } from "@/api/types";

const exercises = ref<StrengthExercise[]>([]);
const equipment = ref<StrengthEquipment | null>(null);
const prefs = ref<Record<string, string>>({});
const statsSummary = ref<Record<string, {
  times_performed: number;
  total_sets: number;
  total_reps: number;
  total_volume_lb: number;
  max_weight_lb: number | null;
  last_performed_date: string | null;
}>>({});
const loading = ref(true);
const error = ref<string>("");
const filter = ref<"available" | "all">("available");
const search = ref("");
const sortBy = ref<"name" | "most_done" | "least_done" | "recent" | "heaviest" | "volume">("name");

// Category filter chips. Multi-select; combine with AND. Empty set = no filter.
type Category =
  | "yoga"
  | "bodyweight"
  | "dumbbell"
  | "bench"
  | "compound"
  | "isolation";
const activeCategories = ref<Set<Category>>(new Set());

const CATEGORIES: Array<{ key: Category; label: string; matches: (e: StrengthExercise) => boolean }> = [
  { key: "yoga",       label: "Yoga / mobility",
    matches: (e) => e.movement_pattern === "mobility" },
  { key: "bodyweight", label: "Bodyweight only",
    matches: (e) => e.equipment.length === 1 && e.equipment[0] === "bodyweight" },
  { key: "dumbbell",   label: "Dumbbell",
    matches: (e) => e.equipment.includes("dumbbell") },
  { key: "bench",      label: "Bench",
    matches: (e) => e.equipment.includes("bench") },
  { key: "compound",   label: "Compound",
    matches: (e) => !!e.is_compound },
  { key: "isolation",  label: "Isolation",
    matches: (e) => !e.is_compound && e.movement_pattern !== "mobility" },
];

function toggleCategory(c: Category) {
  const s = new Set(activeCategories.value);
  if (s.has(c)) s.delete(c); else s.add(c);
  activeCategories.value = s;
}
function categoryActive(c: Category): boolean {
  return activeCategories.value.has(c);
}

// Muscle-group filter — single-select dropdown derived from the
// catalog's distinct primary_muscle values.
const muscleFilter = ref<string>("");
const muscleOptions = computed<string[]>(() => {
  const set = new Set<string>();
  for (const e of exercises.value) {
    if (e.primary_muscle) set.add(e.primary_muscle);
  }
  return Array.from(set).sort();
});

// Lightweight fuzzy match — accepts loose ordering of substrings,
// matches across name/muscle/movement_pattern/equipment fields, and
// scores higher when the query hits the start of the name. Returns
// null when there's no match so the caller can drop the row.
function fuzzyScore(ex: StrengthExercise, q: string): number | null {
  if (!q) return 0;
  const needle = q.toLowerCase().trim();
  if (!needle) return 0;
  const name = ex.name.toLowerCase();
  const haystack = [
    name,
    (ex.primary_muscle ?? "").toLowerCase(),
    (ex.movement_pattern ?? "").toLowerCase().replace(/_/g, " "),
    ex.equipment.join(" ").toLowerCase(),
    (ex.secondary_muscles ?? []).join(" ").toLowerCase(),
  ].join("");

  // Tokenise on whitespace so "incline db" matches "Incline Dumbbell …"
  const tokens = needle.split(/\s+/).filter(Boolean);
  let score = 0;
  for (const tok of tokens) {
    const idx = haystack.indexOf(tok);
    if (idx < 0) {
      // Subsequence fallback — e.g. "rdl" matches "Romanian Deadlift" via r…d…l
      let h = 0;
      for (const ch of tok) {
        const found = haystack.indexOf(ch, h);
        if (found < 0) return null;
        h = found + 1;
      }
      score += 1;
    } else {
      score += 10;
      if (name.startsWith(tok)) score += 30;
      else if (name.includes(tok)) score += 20;
    }
  }
  return score;
}

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const [catRes, eqRes, stats] = await Promise.all([
      api.strengthExercises(),
      api.strengthEquipment(),
      api.strengthExercisesStatsSummary().catch(() => ({})),
    ]);
    exercises.value = catRes.exercises;
    equipment.value = eqRes.payload;
    prefs.value = (eqRes.payload as unknown as { exercise_prefs?: Record<string, string> })
      .exercise_prefs ?? {};
    statsSummary.value = stats;
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
  let base = filter.value === "all" ? exercises.value
    : exercises.value.filter(isAvailable);
  // Category chips combine with AND.
  if (activeCategories.value.size > 0) {
    const matchers = CATEGORIES
      .filter((c) => activeCategories.value.has(c.key))
      .map((c) => c.matches);
    base = base.filter((e) => matchers.every((m) => m(e)));
  }
  if (muscleFilter.value) {
    base = base.filter((e) => e.primary_muscle === muscleFilter.value);
  }
  const q = search.value.trim();
  if (!q) return base;
  // Fuzzy filter + sort by score so the best matches surface first
  // regardless of muscle group.
  const scored: Array<{ ex: StrengthExercise; score: number }> = [];
  for (const ex of base) {
    const s = fuzzyScore(ex, q);
    if (s != null) scored.push({ ex, score: s });
  }
  scored.sort((a, b) => b.score - a.score || a.ex.name.localeCompare(b.ex.name));
  return scored.map((s) => s.ex);
});

function statSortKey(ex: StrengthExercise): number {
  const s = statsSummary.value[ex.id];
  // Never-done exercises have no stats row at all. For 'least_done' we
  // want them to land FIRST in a DESC sort, so return a large positive
  // key. For other stat sorts they go to the bottom (0).
  if (!s) return sortBy.value === "least_done" ? Number.POSITIVE_INFINITY : 0;
  switch (sortBy.value) {
    case "most_done":  return s.times_performed;
    // Negate count so DESC sort surfaces lowest-count first.
    case "least_done": return -s.times_performed;
    case "recent":     return s.last_performed_date
                         ? new Date(s.last_performed_date).getTime() : 0;
    case "heaviest":   return s.max_weight_lb ?? 0;
    case "volume":     return s.total_volume_lb;
    default:           return 0;
  }
}

const groupedByMuscle = computed(() => {
  // When sorting by a stat, return a single flat group so the user
  // sees the global top across all muscles. When sorting by name,
  // keep the per-muscle grouping (the catalog's default rhythm).
  if (sortBy.value !== "name") {
    const sorted = [...visible.value].sort((a, b) => {
      const ka = statSortKey(a), kb = statSortKey(b);
      return kb - ka || a.name.localeCompare(b.name);
    });
    return [["All exercises", sorted]] as Array<[string, StrengthExercise[]]>;
  }
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

function placeholderIcon(ex: StrengthExercise) {
  if (ex.movement_pattern === "mobility") return User;
  if (ex.equipment.includes("dumbbell")) return Dumbbell;
  if (ex.equipment.length === 1 && ex.equipment[0] === "bodyweight") {
    return PersonStanding;
  }
  return ActivityIcon;
}

function videoUrl(query: string): string {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
}

// Click-to-open detail panel
const detailEx = ref<StrengthExercise | null>(null);
const detailStats = ref<Awaited<ReturnType<typeof api.strengthExerciseStats>> | null>(null);
const detailStatsLoading = ref(false);

async function openDetail(ex: StrengthExercise) {
  detailEx.value = ex;
  detailStats.value = null;
  detailStatsLoading.value = true;
  try {
    detailStats.value = await api.strengthExerciseStats(ex.id);
  } catch { /* ignore — stats are non-critical */ }
  finally { detailStatsLoading.value = false; }
}
function closeDetail() {
  detailEx.value = null;
  detailStats.value = null;
}
function fmtRelativeDate(iso: string | null): string {
  if (!iso) return "—";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / (24 * 3600_000));
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

const GROUP_RENAME: Record<string, string> = {
  flexibility: "Yoga & Mobility",
};
function groupLabel(muscle: string): string {
  return GROUP_RENAME[muscle] ?? muscle.replace("_", " ");
}

onMounted(load);
</script>

<template>
  <main class="catalog">
    <header>
      <h1>Workout catalog</h1>
      <div class="filter">
        <label><input type="radio" value="available" v-model="filter"/> Available ({{ counts.total }})</label>
        <label><input type="radio" value="all" v-model="filter"/> All</label>
      </div>
    </header>

    <div class="search-row">
      <input class="search-input" v-model="search" type="search"
             placeholder="Search exercises (name, muscle, pattern, equipment)…"
             autocomplete="off" />
      <button v-if="search" class="clear-btn" @click="search = ''" title="Clear search">×</button>
    </div>

    <div class="filter-row">
      <div class="cat-chips">
        <button v-for="c in CATEGORIES" :key="c.key"
                class="cat-chip" :class="{ on: categoryActive(c.key) }"
                @click="toggleCategory(c.key)">{{ c.label }}</button>
        <button v-if="activeCategories.size > 0"
                class="cat-chip clear" @click="activeCategories = new Set()">
          clear
        </button>
      </div>
      <select v-model="muscleFilter" class="muscle-select">
        <option value="">All muscles</option>
        <option v-for="m in muscleOptions" :key="m" :value="m">
          {{ m === "flexibility" ? "yoga / mobility" : m.replace("_", " ") }}
        </option>
      </select>
      <select v-model="sortBy" class="muscle-select">
        <option value="name">Sort: A-Z by muscle</option>
        <option value="most_done">Sort: most done</option>
        <option value="least_done">Sort: never / least done</option>
        <option value="recent">Sort: recently done</option>
        <option value="heaviest">Sort: heaviest weight</option>
        <option value="volume">Sort: total volume</option>
      </select>
    </div>

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
      <h2>{{ groupLabel(muscle) }} · {{ list.length }}</h2>
      <ul class="list">
        <li v-for="ex in list" :key="ex.id" :class="{
          fav: prefs[ex.id] === 'favorite',
          disabled: prefs[ex.id] === 'disabled',
          avoid: prefs[ex.id] === 'avoid',
          unavailable: !isAvailable(ex),
        }">
          <button class="row-tap" @click="openDetail(ex)">
            <!-- Real demo photo (jpg) → render directly. Generated icon
                 (png from Noun Project) → mask-tint to violet. -->
            <img v-if="image(ex) && /\.jpe?g($|\?)/i.test(image(ex)!)"
                 :src="image(ex) ?? ''" :alt="ex.name" />
            <div v-else-if="image(ex)" class="thumb-mask"
                 :style="`-webkit-mask-image: url('${image(ex)}'); mask-image: url('${image(ex)}')`"
                 :title="ex.name"/>
            <div v-else class="ph"
                 :class="{ 'yoga-ph': ex.movement_pattern === 'mobility' }">
              <YogaPoseIcon v-if="ex.movement_pattern === 'mobility'"
                            :id="ex.id" :size="32"
                            :stroke="'#a78bfa'"/>
              <component v-else :is="placeholderIcon(ex)" :size="22"/>
            </div>
            <div class="meta">
              <strong>{{ ex.name }}
                <span class="done-pill" :class="{ never: !statsSummary[ex.id]?.times_performed }"
                      :title="statsSummary[ex.id]?.times_performed
                        ? `Performed ${statsSummary[ex.id].times_performed} session(s)`
                        : 'Never performed'">
                  {{ statsSummary[ex.id]?.times_performed
                       ? `${statsSummary[ex.id].times_performed}×`
                       : 'never' }}
                </span>
              </strong>
              <span class="tags">
                <span v-if="muscleIcon(ex.primary_muscle)" class="muscle-chip"
                      :title="muscleLabel(ex.primary_muscle)">
                  <span class="muscle-mask"
                        :style="`-webkit-mask-image: url('${muscleIcon(ex.primary_muscle)}'); mask-image: url('${muscleIcon(ex.primary_muscle)}')`"/>
                  {{ muscleLabel(ex.primary_muscle) }}
                </span>
                <span v-else>{{ ex.primary_muscle }}</span>
                · {{ ex.equipment.join(' + ') }}
                · {{ ex.level }}
              </span>
            </div>
          </button>
          <div class="actions">
            <a v-if="ex.youtube_query"
               class="act vid" :href="videoUrl(ex.youtube_query)"
               target="_blank" rel="noreferrer" title="Watch on YouTube">
              <Play :size="14"/>
            </a>
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

    <!-- Exercise detail overlay -->
    <div v-if="detailEx" class="detail-overlay" @click="closeDetail">
      <div class="detail-panel" @click.stop>
        <button class="detail-close" @click="closeDetail" aria-label="Close">×</button>
        <div class="detail-head">
          <img v-if="image(detailEx) && /\.jpe?g($|\?)/i.test(image(detailEx)!)"
               :src="image(detailEx) ?? ''" :alt="detailEx.name"/>
          <div v-else-if="image(detailEx)" class="thumb-mask big"
               :style="`-webkit-mask-image: url('${image(detailEx)}'); mask-image: url('${image(detailEx)}')`"
               :title="detailEx.name"/>
          <div v-else class="ph big"
               :class="{ 'yoga-ph': detailEx.movement_pattern === 'mobility' }">
            <YogaPoseIcon v-if="detailEx.movement_pattern === 'mobility'"
                          :id="detailEx.id" :size="58"
                          :stroke="'#a78bfa'"/>
            <component v-else :is="placeholderIcon(detailEx)" :size="40"/>
          </div>
          <div class="detail-title">
            <h2>{{ detailEx.name }}</h2>
            <div class="detail-tags">
              {{ detailEx.movement_pattern.replace('_', ' ') }}
              · {{ detailEx.equipment.join(' + ') }}
              · {{ detailEx.level }}
            </div>
            <div class="detail-muscles">
              <span v-if="muscleIcon(detailEx.primary_muscle)"
                    class="muscle-mask big"
                    :title="muscleLabel(detailEx.primary_muscle)"
                    :style="`-webkit-mask-image: url('${muscleIcon(detailEx.primary_muscle)}'); mask-image: url('${muscleIcon(detailEx.primary_muscle)}')`"/>
              <strong>{{ muscleLabel(detailEx.primary_muscle) || detailEx.primary_muscle }}</strong>
              <span v-if="detailEx.secondary_muscles?.length">
                ·
                {{ detailEx.secondary_muscles.join(", ") }}
              </span>
            </div>
            <div class="detail-actions">
              <a v-if="detailEx.youtube_query"
                 :href="videoUrl(detailEx.youtube_query)"
                 target="_blank" rel="noreferrer" class="link-btn">
                <Play :size="13"/> Watch on YouTube
              </a>
            </div>
          </div>
        </div>

        <!-- Stats -->
        <section class="detail-section">
          <h3>Your history</h3>
          <p v-if="detailStatsLoading" class="dim">Loading…</p>
          <p v-else-if="!detailStats || detailStats.times_performed === 0" class="dim">
            Not performed yet.
          </p>
          <div v-else class="stats-grid">
            <div class="stat">
              <span class="stat-label">Sessions</span>
              <span class="stat-val mono">{{ detailStats.times_performed }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Last seen</span>
              <span class="stat-val mono">{{ fmtRelativeDate(detailStats.last_performed_date) }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Last weight</span>
              <span class="stat-val mono">{{ detailStats.last_weight_lb ?? "—" }}<span class="unit-s" v-if="detailStats.last_weight_lb"> lb</span></span>
            </div>
            <div class="stat">
              <span class="stat-label">Max weight</span>
              <span class="stat-val mono">{{ detailStats.max_weight_lb ?? "—" }}<span class="unit-s" v-if="detailStats.max_weight_lb"> lb</span></span>
            </div>
            <div class="stat">
              <span class="stat-label">Total reps</span>
              <span class="stat-val mono">{{ detailStats.total_reps.toLocaleString() }}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Volume</span>
              <span class="stat-val mono">{{ Math.round(detailStats.total_volume_lb).toLocaleString() }}<span class="unit-s"> lb</span></span>
            </div>
            <div class="stat" v-if="detailStats.avg_rating != null">
              <span class="stat-label">Avg RPE</span>
              <span class="stat-val mono">{{ detailStats.avg_rating.toFixed(1) }}</span>
            </div>
          </div>
        </section>

        <!-- Instructions -->
        <section v-if="detailEx.instructions?.length" class="detail-section">
          <h3>How to do it</h3>
          <ol class="instructions">
            <li v-for="(line, i) in detailEx.instructions" :key="i">{{ line }}</li>
          </ol>
        </section>
      </div>
    </div>
  </main>
</template>

<style scoped>
.catalog { max-width: 880px; }
header { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; flex-wrap: wrap; gap: 0.6rem; }
header h1 { margin: 0; }
.filter label { margin-left: 0.6rem; font-size: 0.85rem; color: var(--muted); }

.search-row { display: flex; gap: 0.4rem; align-items: stretch; margin-bottom: 0.6rem; }

.filter-row {
  display: flex; gap: 0.6rem; align-items: center;
  flex-wrap: wrap; margin-bottom: 0.8rem;
}
.cat-chips { display: flex; gap: 0.3rem; flex-wrap: wrap; flex: 1; min-width: 0; }
.cat-chip {
  background: var(--bg-2); color: var(--muted);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 0.25rem 0.7rem; font-size: 0.78rem; cursor: pointer;
  font-family: inherit; white-space: nowrap;
}
.cat-chip:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.cat-chip.on {
  background: rgba(239, 68, 68, 0.18); color: var(--accent, #ef4444);
  border-color: rgba(239, 68, 68, 0.5);
}
.cat-chip.clear { color: var(--muted); border-style: dashed; }
.muscle-select {
  background: var(--bg-2); color: var(--text);
  border: 1px solid var(--line); border-radius: 6px;
  padding: 0.32rem 0.55rem; font-size: 0.82rem; font-family: inherit;
  text-transform: capitalize; cursor: pointer;
}
.muscle-select:focus { outline: none; border-color: var(--accent, #ef4444); }
.search-input {
  flex: 1; background: var(--bg-2); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px;
  padding: 0.55rem 0.8rem; font-size: 0.9rem; font-family: inherit;
}
.search-input::placeholder { color: var(--muted); }
.search-input:focus { outline: none; border-color: var(--accent, #38bdf8); }
.clear-btn {
  background: var(--bg-2); color: var(--muted); border: 1px solid var(--line);
  border-radius: 8px; padding: 0 0.85rem; font-size: 1.1rem; cursor: pointer;
}
.clear-btn:hover { color: var(--text); }
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
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 0.7rem;
  padding: 0.5rem 0.7rem;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px;
}
.row-tap {
  display: grid;
  grid-template-columns: 56px 1fr;
  align-items: center;
  gap: 0.7rem;
  background: transparent; border: none; padding: 0;
  text-align: left; cursor: pointer; color: inherit;
  font: inherit; min-width: 0;
}
.row-tap:hover .meta strong { color: var(--accent, #ef4444); }
.list li.fav { border-left: 3px solid #f59e0b; }
.list li.disabled { opacity: 0.5; border-left: 3px solid #ef4444; }
.list li.avoid { opacity: 0.7; border-left: 3px solid #94a3b8; }
.list li.unavailable { opacity: 0.4; }

.list img, .list .ph {
  width: 56px; height: 56px; border-radius: 6px;
  background: #111; object-fit: cover;
}
.list .thumb-mask {
  width: 56px; height: 56px; border-radius: 6px;
  background: var(--accent, #a78bfa);
  -webkit-mask-size: 70%; mask-size: 70%;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  box-shadow: inset 0 0 0 999px rgba(167, 139, 250, 0.10);
  flex-shrink: 0;
}
.detail-head .thumb-mask.big {
  width: 96px; height: 96px; border-radius: 8px;
  background: var(--accent, #a78bfa);
  -webkit-mask-size: 70%; mask-size: 70%;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  box-shadow: inset 0 0 0 999px rgba(167, 139, 250, 0.10);
  flex-shrink: 0;
}
.list .ph {
  background: var(--bg-1); border: 1px dashed var(--line);
  display: flex; align-items: center; justify-content: center;
  color: var(--muted);
}
.list .ph.yoga-ph {
  background: rgba(167, 139, 250, 0.08);
  border: 1px solid rgba(167, 139, 250, 0.25);
  border-radius: 6px;
}
/* Muscle anatomy chip — small violet glyph next to row's muscle label.
   Uses CSS mask-image so the same black PNG renders in any accent. */
.muscle-chip {
  display: inline-flex; align-items: center; gap: 0.25rem;
  vertical-align: middle;
}
.done-pill {
  display: inline-block;
  margin-left: 0.4rem;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  vertical-align: middle;
  background: rgba(34, 197, 94, 0.18);
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.35);
}
.done-pill.never {
  background: rgba(148, 163, 184, 0.15);
  color: var(--muted, #94a3b8);
  border-color: rgba(148, 163, 184, 0.3);
}
.muscle-mask {
  display: inline-block;
  width: 14px; height: 14px;
  background: var(--accent, #a78bfa);
  -webkit-mask-size: contain; mask-size: contain;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center;
  vertical-align: middle;
}
.muscle-mask.big {
  width: 28px; height: 28px;
  margin-right: 0.4rem;
}
.detail-head .ph.big.yoga-ph {
  background: rgba(167, 139, 250, 0.08);
  border: 1px solid rgba(167, 139, 250, 0.25);
}
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
.act.vid { text-decoration: none; }
.act.vid:hover { color: #ef4444; border-color: #ef444466; }
.act.fav.on  { background: rgba(245, 158, 11, 0.18); color: #f59e0b; border-color: #f59e0b66; }
.act.avoid.on { background: rgba(148, 163, 184, 0.2); color: #94a3b8; border-color: #94a3b855; }
.act.dis.on  { background: rgba(239, 68, 68, 0.18); color: #ef4444; border-color: #ef444466; }

/* Detail overlay */
.detail-overlay {
  position: fixed; inset: 0; z-index: 60;
  background: rgba(15, 22, 32, 0.7); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
}
.detail-panel {
  background: var(--surface, #1B2331);
  border: 1px solid var(--line); border-radius: 12px;
  padding: 1.4rem 1.4rem 1.6rem;
  max-width: 640px; width: 100%;
  max-height: 88vh; overflow-y: auto;
  position: relative;
}
.detail-close {
  position: absolute; top: 0.7rem; right: 0.8rem;
  background: transparent; border: none; color: var(--muted);
  font-size: 1.4rem; line-height: 1; cursor: pointer; padding: 0.2rem 0.5rem;
}
.detail-close:hover { color: var(--text); }
.detail-head { display: flex; gap: 1rem; align-items: flex-start; margin-bottom: 1rem; }
.detail-head img, .detail-head .ph.big {
  width: 96px; height: 96px; border-radius: 8px;
  background: #111; object-fit: cover; flex: 0 0 auto;
}
.detail-head .ph.big {
  background: var(--bg-1); border: 1px dashed var(--line);
  display: flex; align-items: center; justify-content: center;
  color: var(--muted);
}
.detail-title { flex: 1; min-width: 0; }
.detail-title h2 { margin: 0 0 0.25rem; font-size: 1.15rem; }
.detail-tags {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 0.78rem; color: var(--muted);
}
.detail-muscles { font-size: 0.85rem; margin-top: 0.3rem; }
.detail-muscles strong { color: var(--text); text-transform: capitalize; }
.detail-actions { margin-top: 0.6rem; }
.link-btn {
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--bg-2); color: var(--text);
  border: 1px solid var(--line); border-radius: 6px;
  padding: 0.32rem 0.6rem; font-size: 0.8rem;
  text-decoration: none; cursor: pointer;
}
.link-btn:hover { color: #ef4444; border-color: #ef444466; }
.detail-section { margin-top: 1rem; }
.detail-section h3 {
  font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; margin: 0 0 0.6rem;
}
.stats-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.6rem;
}
.stat { display: flex; flex-direction: column; gap: 0.2rem;
        padding: 0.6rem 0.7rem;
        background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; }
.stat-label { font-size: 0.7rem; letter-spacing: 0.06em;
              text-transform: uppercase; color: var(--muted); }
.stat-val { font-size: 1.1rem; font-weight: 500; }
.unit-s { font-size: 0.75em; color: var(--muted); margin-left: 2px; }
.dim { color: var(--muted); font-size: 0.85rem; }
.instructions { padding-left: 1.2rem; margin: 0; display: flex;
                flex-direction: column; gap: 0.45rem; }
.instructions li { font-size: 0.88rem; line-height: 1.5; color: var(--text); }
@media (max-width: 540px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
