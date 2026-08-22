<script setup lang="ts">
/**
 * The food log.
 *
 * Intermittent logging is the design assumption, not a failure mode, and
 * that shapes everything here. There is deliberately no streak, no
 * completion percentage and no nagging — a tracker that turns red the
 * moment you stop is a tracker you stop opening. A day with no entries
 * is shown as an ordinary empty day, not a gap to feel bad about.
 *
 * Completeness is declared, never inferred. The app cannot tell "I
 * stopped logging" from "I stopped eating", so the user says, and
 * anything derived counts only the days they marked.
 *
 * Fat is assessed per MEAL, because a meal is the unit that matters
 * after a cholecystectomy — a day totalling 70 g across four meals and a
 * day where 60 g of it lands at dinner are the same daily number and a
 * completely different experience.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import FatAssessment from "@/components/FatAssessment.vue";
import {
  Plus, Trash2, ChevronLeft, ChevronRight, Check, Info,
} from "lucide-vue-next";
import {
  meals, type Food, type LogDay, type LogStats, type Recipe,
} from "@/api/client";
import { toLocalISO } from "@/dates";

const SLOTS = ["breakfast", "lunch", "dinner", "snack"];

const days = ref<LogDay[]>([]);
const stats = ref<LogStats | null>(null);
const recipes = ref<Recipe[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const anchor = ref<string>(toLocalISO(new Date()));
const window = 7;

const addingFor = ref<string | null>(null);
const draftSlot = ref("dinner");
const draftFood = ref<Food | null>(null);
const draftRecipe = ref<number | "">("");
const draftQty = ref("");
const draftUnit = ref("");
const draftServings = ref("1");
const draftLabel = ref("");
const draftKcal = ref("");
const draftFat = ref("");
const saving = ref(false);

function startOfWindow(end: string): string {
  const d = new Date(`${end}T00:00:00`);
  d.setDate(d.getDate() - (window - 1));
  return toLocalISO(d);
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [d, st, r] = await Promise.all([
      meals.getLog(startOfWindow(anchor.value), window),
      meals.logStats(30),
      recipes.value.length ? Promise.resolve(recipes.value) : meals.listRecipes(),
    ]);
    // Newest first — you log what you just ate, not what you ate a week ago.
    days.value = [...d].reverse();
    stats.value = st;
    recipes.value = r;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function shift(delta: number) {
  const d = new Date(`${anchor.value}T00:00:00`);
  d.setDate(d.getDate() + delta * window);
  anchor.value = toLocalISO(d);
  load();
}

function resetDraft() {
  draftFood.value = null;
  draftRecipe.value = "";
  draftQty.value = "";
  draftUnit.value = "";
  draftServings.value = "1";
  draftLabel.value = "";
  draftKcal.value = "";
  draftFat.value = "";
}

function startAdd(day: string) {
  addingFor.value = addingFor.value === day ? null : day;
  draftSlot.value = "dinner";
  resetDraft();
}

async function add(day: string) {
  const hasSomething =
    draftFood.value || draftRecipe.value !== "" || draftLabel.value.trim();
  if (!hasSomething) return;
  saving.value = true;
  error.value = null;
  try {
    await meals.addLogEntry({
      day,
      slot: draftSlot.value,
      food_id: draftFood.value?.id ?? null,
      recipe_id: draftRecipe.value === "" ? null : Number(draftRecipe.value),
      label: draftFood.value || draftRecipe.value !== "" ? null : draftLabel.value.trim(),
      quantity: draftQty.value ? Number(draftQty.value) : null,
      unit: draftUnit.value.trim() || null,
      servings: draftRecipe.value !== "" ? Number(draftServings.value) || 1 : null,
      // Blank stays null — a meal whose calories you don't know is not a
      // meal with zero calories.
      manual_kcal: draftKcal.value ? Number(draftKcal.value) : null,
      manual_fat_g: draftFat.value ? Number(draftFat.value) : null,
    });
    addingFor.value = null;
    resetDraft();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not log";
  } finally {
    saving.value = false;
  }
}

async function remove(id: number) {
  try {
    await meals.deleteLogEntry(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not remove";
  }
}

async function toggleComplete(d: LogDay) {
  try {
    await meals.markLogDay(d.day, { complete: !d.complete });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not save";
  }
}

function dayLabel(s: string): string {
  const d = new Date(`${s}T00:00:00`);
  if (s === toLocalISO(new Date())) return "Today";
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function num(v: number | null | undefined, digits = 0, suffix = ""): string {
  return v == null ? "—" : `${v.toFixed(digits)}${suffix}`;
}

const rangeLabel = computed(() => {
  if (!days.value.length) return "";
  const fmt = (s: string) =>
    new Date(`${s}T00:00:00`).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  return `${fmt(days.value[days.value.length - 1].day)} – ${fmt(days.value[0].day)}`;
});
</script>

<template>
  <div class="log">
    <PageHeader title="Food log">
      <div class="nav">
        <button class="ghost" title="Earlier" @click="shift(-1)">
          <ChevronLeft :size="15" />
        </button>
        <span class="range">{{ rangeLabel }}</span>
        <button class="ghost" title="Later" @click="shift(1)">
          <ChevronRight :size="15" />
        </button>
      </div>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="stats" flat class="stats">
      <div v-if="stats.reason" class="refusal">
        <Info :size="14" />
        <span>{{ stats.reason }}</span>
      </div>
      <div v-else class="avgs">
        <span><strong>{{ num(stats.avg_kcal) }}</strong> kcal/day</span>
        <span><strong>{{ num(stats.avg_fat_g, 1) }}</strong> g fat/day</span>
        <span class="from">from {{ stats.complete_days }} complete days</span>
      </div>
      <p v-if="stats.meals_counted" class="meal-fat">
        Per meal over the last 30 days: median
        <strong>{{ num(stats.median_meal_fat_g, 1) }} g</strong> fat,
        highest <strong>{{ num(stats.max_meal_fat_g, 1) }} g</strong>
        ({{ stats.meals_counted }} meals).
      </p>
      <p v-if="stats.partial_days" class="partial">
        {{ stats.partial_days }} partly-logged day{{ stats.partial_days === 1 ? "" : "s" }}
        excluded from the averages — counting them would read as eating
        less than you did.
      </p>
    </Card>

    <EmptyState v-if="loading && !days.length" message="Loading…" />

    <Card v-for="d in days" :key="d.day" flat class="day">
      <div class="day-head">
        <strong>{{ dayLabel(d.day) }}</strong>
        <span class="totals">
          {{ num(d.totals.kcal) }} kcal · {{ num(d.totals.fat_g, 1, " g") }} fat
        </span>
        <button
          class="mark"
          :class="{ on: d.complete }"
          :title="d.complete ? 'Marked complete' : 'Mark this day complete'"
          @click="toggleComplete(d)"
        >
          <Check :size="12" /> {{ d.complete ? "complete" : "partial" }}
        </button>
        <button class="ghost small" @click="startAdd(d.day)">
          <Plus :size="13" />
        </button>
      </div>

      <p v-if="d.unresolved_count" class="warn">
        {{ d.unresolved_count }} entr{{ d.unresolved_count === 1 ? "y" : "ies" }}
        could not be costed, so these totals are an underestimate.
      </p>

      <div v-for="m in d.meals" :key="m.slot" class="meal">
        <div class="meal-head">
          <span class="slot">{{ m.slot }}</span>
          <span class="meal-totals">
            {{ num(m.totals.kcal) }} kcal · {{ num(m.totals.fat_g, 1, " g") }} fat
          </span>
        </div>
        <FatAssessment
          v-if="m.fat_assessment && m.fat_assessment.verdict !== 'unknown'"
          :assessment="m.fat_assessment"
          compact
          class="meal-fat-card"
        />
        <ul class="entries">
          <li v-for="e in m.entries" :key="e.id">
            <span class="what">
              {{ e.label }}
              <span v-if="e.quantity" class="qty">
                {{ e.quantity }}{{ e.unit ? ` ${e.unit}` : "" }}
              </span>
              <span v-else-if="e.servings" class="qty">×{{ e.servings }}</span>
            </span>
            <span v-if="e.source === 'manual'" class="src" title="Typed in by hand">
              typed
            </span>
            <span v-if="e.unresolved_reason" class="why">{{ e.unresolved_reason }}</span>
            <span v-else class="kcal">{{ num(e.nutrition.kcal) }} kcal</span>
            <button class="icon-btn" title="Remove" @click="remove(e.id)">
              <Trash2 :size="12" />
            </button>
          </li>
        </ul>
      </div>

      <p v-if="!d.entry_count" class="nothing">Nothing logged.</p>

      <div v-if="addingFor === d.day" class="adder">
        <select v-model="draftSlot">
          <option v-for="s in SLOTS" :key="s" :value="s">{{ s }}</option>
        </select>

        <div v-if="draftFood" class="chosen">
          {{ draftFood.name }}
          <button class="link" @click="draftFood = null">change</button>
        </div>
        <FoodPicker
          v-else-if="draftRecipe === '' && !draftLabel"
          placeholder="Search a food…"
          @pick="(f) => (draftFood = f)"
        />

        <select v-if="!draftFood" v-model="draftRecipe">
          <option value="">— or one of your recipes —</option>
          <option v-for="r in recipes" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>

        <template v-if="draftFood">
          <input v-model="draftQty" type="number" step="any" min="0" placeholder="qty" />
          <input v-model="draftUnit" type="text" placeholder="unit" />
        </template>
        <input
          v-else-if="draftRecipe !== ''"
          v-model="draftServings"
          type="number"
          step="any"
          min="0"
          placeholder="servings"
        />
        <template v-else>
          <input v-model="draftLabel" type="text" placeholder="e.g. lunch out" />
          <input v-model="draftKcal" type="number" min="0" placeholder="kcal" />
          <input v-model="draftFat" type="number" step="any" min="0" placeholder="fat g" />
        </template>

        <button class="primary" :disabled="saving" @click="add(d.day)">Log</button>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.nav { display: flex; align-items: center; gap: 0.4rem; }
.range { font-size: 0.8rem; color: var(--muted-2); min-width: 120px; text-align: center; }
button.ghost, button.primary {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 8px; padding: 0.3rem 0.5rem; font: inherit; font-size: 0.8rem;
  cursor: pointer;
}
button.ghost.small { padding: 0.2rem 0.35rem; }
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.link { background: none; border: 0; color: var(--accent, #38bdf8); cursor: pointer; font: inherit; font-size: 0.78rem; padding: 0; }
.stats { margin-bottom: 0.7rem; }
.refusal { display: flex; align-items: flex-start; gap: 0.4rem; font-size: 0.82rem; color: var(--muted-2); line-height: 1.5; }
.avgs { display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
.avgs .from { color: var(--muted-2); font-size: 0.78rem; }
.meal-fat, .partial { margin: 0.6rem 0 0; font-size: 0.78rem; color: var(--muted-2); line-height: 1.5; }
.day { margin-bottom: 0.5rem; }
.day-head { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; }
.day-head strong { font-size: 0.9rem; }
.totals { margin-left: auto; font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.mark {
  display: inline-flex; align-items: center; gap: 0.2rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 999px; padding: 0.1rem 0.45rem; font: inherit; font-size: 0.7rem;
  cursor: pointer;
}
.mark.on { color: #22c55e; border-color: #22c55e55; }
.warn { margin: 0.4rem 0 0; font-size: 0.76rem; color: #fbbf24; }
.meal { margin-top: 0.6rem; }
.meal-head { display: flex; align-items: baseline; gap: 0.5rem; }
.slot { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-2); }
.meal-totals { margin-left: auto; font-size: 0.72rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.meal-fat-card { margin: 0.35rem 0; }
.entries { list-style: none; margin: 0.25rem 0 0; padding: 0; }
.entries li { display: flex; align-items: center; gap: 0.5rem; padding: 0.2rem 0; font-size: 0.83rem; }
.what { flex: 1; min-width: 0; }
.qty { color: var(--muted-2); font-size: 0.76rem; }
.src { font-size: 0.66rem; color: var(--muted-2); border: 1px solid var(--line); border-radius: 4px; padding: 0 0.25rem; }
.kcal { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.why { font-size: 0.72rem; color: #fbbf24; }
.nothing { margin: 0.5rem 0 0; font-size: 0.8rem; color: var(--muted-2); }
.icon-btn { border: 0; background: transparent; color: var(--muted-2); cursor: pointer; display: flex; padding: 0.15rem; }
.icon-btn:hover { color: #f87171; }
.adder { display: flex; gap: 0.4rem; margin-top: 0.7rem; flex-wrap: wrap; align-items: center; }
.adder select, .adder input {
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg-1);
  color: var(--fg); font: inherit; font-size: 0.8rem; padding: 0.3rem 0.4rem;
}
.adder input { width: 92px; }
.adder .chosen { font-size: 0.82rem; display: flex; align-items: center; gap: 0.4rem; }
</style>
