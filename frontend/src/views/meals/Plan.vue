<script setup lang="ts">
/**
 * The weekly meal plan.
 *
 * There is no household or portion model — single person — so
 * `servings` is a plain multiplier meaning "how many containers of this
 * to make". That is the whole meal-prep story, and it is enough.
 *
 * Day totals come from the server and multiply by planned servings:
 * three containers of something is three meals' worth of energy. A day
 * with nothing costable planned shows "—", never 0, because an unknown
 * total is not an empty one.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import { Plus, Trash2, ChevronLeft, ChevronRight, ShoppingCart } from "lucide-vue-next";
import { meals, type PlanDay, type Recipe } from "@/api/client";
import { toLocalISO } from "@/dates";

const SLOTS = ["breakfast", "lunch", "dinner", "snack", "prep"];

const days = ref<PlanDay[]>([]);
const recipes = ref<Recipe[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const weekStart = ref<string | null>(null);

const addingFor = ref<string | null>(null);
const draftSlot = ref("dinner");
const draftRecipe = ref<number | "">("");
const draftNote = ref("");
const draftServings = ref(1);
const saving = ref(false);

function mondayOf(d: Date): string {
  const copy = new Date(d);
  // getDay() is 0 for Sunday; shift so Monday is the start.
  const shift = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - shift);
  return toLocalISO(copy);
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [d, r] = await Promise.all([
      meals.getPlan(weekStart.value ?? undefined, 7),
      recipes.value.length ? Promise.resolve(recipes.value) : meals.listRecipes(),
    ]);
    days.value = d;
    recipes.value = r;
    if (!weekStart.value && d.length) weekStart.value = d[0].day;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(() => {
  weekStart.value = mondayOf(new Date());
  load();
});

function shiftWeek(delta: number) {
  const d = new Date(`${weekStart.value}T00:00:00`);
  d.setDate(d.getDate() + delta * 7);
  weekStart.value = toLocalISO(d);
  load();
}

function thisWeek() {
  weekStart.value = mondayOf(new Date());
  load();
}

function startAdd(day: string) {
  addingFor.value = addingFor.value === day ? null : day;
  draftSlot.value = "dinner";
  draftRecipe.value = "";
  draftNote.value = "";
  draftServings.value = 1;
}

async function add(day: string) {
  if (draftRecipe.value === "" && !draftNote.value.trim()) return;
  saving.value = true;
  error.value = null;
  try {
    await meals.addPlanEntry({
      day,
      slot: draftSlot.value,
      recipe_id: draftRecipe.value === "" ? null : Number(draftRecipe.value),
      note: draftRecipe.value === "" ? draftNote.value.trim() : null,
      servings: draftServings.value,
    });
    addingFor.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not add";
  } finally {
    saving.value = false;
  }
}

async function remove(id: number) {
  try {
    await meals.deletePlanEntry(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not remove";
  }
}

const rangeLabel = computed(() => {
  if (!days.value.length) return "";
  const fmt = (s: string) =>
    new Date(`${s}T00:00:00`).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  return `${fmt(days.value[0].day)} – ${fmt(days.value[days.value.length - 1].day)}`;
});

const plannedCount = computed(() =>
  days.value.reduce((n, d) => n + d.entries.length, 0),
);

function dayLabel(s: string): string {
  return new Date(`${s}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
  });
}

function isToday(s: string): boolean {
  return s === toLocalISO(new Date());
}

function num(v: number | null, digits = 0, suffix = ""): string {
  return v == null ? "—" : `${v.toFixed(digits)}${suffix}`;
}
</script>

<template>
  <div class="plan">
    <PageHeader title="Meal plan">
      <div class="week-nav">
        <button class="ghost" title="Previous week" @click="shiftWeek(-1)">
          <ChevronLeft :size="15" />
        </button>
        <button class="ghost label" @click="thisWeek">{{ rangeLabel || "…" }}</button>
        <button class="ghost" title="Next week" @click="shiftWeek(1)">
          <ChevronRight :size="15" />
        </button>
        <RouterLink to="/meals/shopping" class="ghost link-btn">
          <ShoppingCart :size="14" /> Shopping
        </RouterLink>
      </div>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>
    <EmptyState v-if="loading && !days.length" message="Loading…" />

    <p v-else-if="!recipes.length" class="hint">
      No recipes yet — add some under
      <RouterLink to="/meals/recipes">Recipes</RouterLink> and they can be
      planned here. You can still plan a note (eating out, leftovers).
    </p>

    <Card v-for="d in days" :key="d.day" flat class="day" :class="{ today: isToday(d.day) }">
      <div class="day-head">
        <strong>{{ dayLabel(d.day) }}</strong>
        <span class="totals">
          {{ num(d.kcal) }} kcal · {{ num(d.fat_g, 1, " g") }} fat
        </span>
        <button class="ghost small" @click="startAdd(d.day)">
          <Plus :size="13" />
        </button>
      </div>

      <ul v-if="d.entries.length" class="entries">
        <li v-for="e in d.entries" :key="e.id">
          <span class="slot">{{ e.slot }}</span>
          <span class="what">
            {{ e.recipe_name ?? e.note }}
            <span v-if="e.servings > 1" class="mult">×{{ e.servings }}</span>
          </span>
          <span v-if="e.kcal_per_serving != null" class="kcal">
            {{ Math.round(e.kcal_per_serving * e.servings) }} kcal
          </span>
          <span
            v-if="e.fat_verdict !== 'unknown'"
            class="dot"
            :class="e.fat_verdict"
            :title="`fat: ${e.fat_verdict.replace('_', ' ')}`"
          />
          <button class="icon-btn" title="Remove" @click="remove(e.id)">
            <Trash2 :size="13" />
          </button>
        </li>
      </ul>
      <p v-else class="nothing">Nothing planned.</p>

      <div v-if="addingFor === d.day" class="adder">
        <select v-model="draftSlot">
          <option v-for="s in SLOTS" :key="s" :value="s">{{ s }}</option>
        </select>
        <select v-model="draftRecipe">
          <option value="">— a note instead —</option>
          <option v-for="r in recipes" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <input
          v-if="draftRecipe === ''"
          v-model="draftNote"
          type="text"
          placeholder="e.g. dinner out"
        />
        <input
          v-else
          v-model.number="draftServings"
          type="number"
          min="1"
          max="100"
          title="How many containers to make"
        />
        <button class="primary" :disabled="saving" @click="add(d.day)">Add</button>
      </div>
    </Card>

    <p v-if="days.length && !plannedCount" class="hint">
      Plan a few meals, then generate a shopping list — it subtracts what
      the pantry already holds.
    </p>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.hint { color: var(--muted-2); font-size: 0.82rem; line-height: 1.5; }
.week-nav { display: flex; align-items: center; gap: 0.35rem; }
button.ghost, .link-btn {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 8px; padding: 0.3rem 0.5rem; font: inherit; font-size: 0.8rem;
  cursor: pointer; text-decoration: none;
}
button.ghost.label { min-width: 130px; justify-content: center; }
button.ghost.small { padding: 0.2rem 0.35rem; }
button.primary {
  border: 1px solid transparent; background: var(--accent, #38bdf8);
  color: #04121c; border-radius: 8px; padding: 0.3rem 0.6rem;
  font: inherit; font-size: 0.8rem; cursor: pointer;
}
.day { margin-bottom: 0.5rem; }
.day.today { border-color: var(--accent, #38bdf8); }
.day-head { display: flex; align-items: center; gap: 0.6rem; }
.day-head strong { font-size: 0.9rem; }
.totals {
  margin-left: auto; font-size: 0.75rem; color: var(--muted-2);
  font-variant-numeric: tabular-nums;
}
.entries { list-style: none; margin: 0.5rem 0 0; padding: 0; }
.entries li {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.25rem 0; border-bottom: 1px solid var(--line); font-size: 0.85rem;
}
.slot {
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted-2); min-width: 62px;
}
.what { flex: 1; min-width: 0; }
.mult { color: var(--muted-2); font-size: 0.78rem; }
.kcal { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.dot.ok { background: #22c55e; }
.dot.approaching { background: #fbbf24; }
.dot.high { background: #fb923c; }
.dot.very_high { background: #f87171; }
.nothing { margin: 0.4rem 0 0; font-size: 0.8rem; color: var(--muted-2); }
.icon-btn {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0.15rem;
}
.icon-btn:hover { color: #f87171; }
.adder {
  display: flex; gap: 0.4rem; margin-top: 0.6rem; flex-wrap: wrap;
  align-items: center;
}
.adder select, .adder input {
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg-1);
  color: var(--fg); font: inherit; font-size: 0.8rem; padding: 0.3rem 0.4rem;
}
.adder input[type="number"] { width: 70px; }
.adder input[type="text"] { flex: 1; min-width: 120px; }
</style>
