<script setup lang="ts">
/**
 * Recipes the user owns.
 *
 * The app never ships or scrapes third-party recipes; everything here is
 * entered by the user into their own private install.
 *
 * Every nutrition number rendered below comes from the server. Scaling,
 * unit conversion and the unresolved-line accounting all happen in
 * `api/meals.py`, and re-deriving any of it here is how the web and the
 * phone end up disagreeing about how much fat is in dinner.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import FatAssessment from "@/components/FatAssessment.vue";
import {
  Plus, Trash2, ChevronDown, ChevronRight, AlertCircle, Pencil, X as XIcon,
} from "lucide-vue-next";
import {
  meals, type Food, type IngredientInput, type Recipe,
} from "@/api/client";

const recipes = ref<Recipe[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const open = ref<Record<number, boolean>>({});
/** Per-recipe serving override for the scale control. */
const scaleTo = ref<Record<number, number>>({});

const editing = ref<number | "new" | null>(null);
const saving = ref(false);

const draftName = ref("");
const draftServings = ref(1);
const draftPrep = ref("");
const draftCook = ref("");
const draftMethod = ref("");
const draftLines = ref<
  Array<IngredientInput & { food_name?: string | null }>
>([]);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    recipes.value = await meals.listRecipes();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function startNew() {
  editing.value = "new";
  draftName.value = "";
  draftServings.value = 1;
  draftPrep.value = "";
  draftCook.value = "";
  draftMethod.value = "";
  draftLines.value = [];
}

function startEdit(r: Recipe) {
  editing.value = r.id;
  draftName.value = r.name;
  draftServings.value = r.servings;
  draftPrep.value = r.prep_min?.toString() ?? "";
  draftCook.value = r.cook_min?.toString() ?? "";
  draftMethod.value = r.method ?? "";
  draftLines.value = r.ingredients.map((i) => ({
    food_id: i.food_id,
    food_name: i.food_name,
    raw_text: i.raw_text,
    quantity: i.quantity,
    unit: i.unit,
  }));
}

function addLine(f: Food) {
  draftLines.value.push({
    food_id: f.id,
    food_name: f.name,
    quantity: null,
    unit: null,
    raw_text: null,
  });
}

function addFreeLine() {
  draftLines.value.push({
    food_id: null, food_name: null, quantity: null, unit: null, raw_text: "",
  });
}

function dropLine(idx: number) {
  draftLines.value.splice(idx, 1);
}

async function save() {
  if (!draftName.value.trim()) return;
  saving.value = true;
  error.value = null;
  const body = {
    name: draftName.value.trim(),
    servings: Number(draftServings.value) || 1,
    prep_min: draftPrep.value ? Number(draftPrep.value) : null,
    cook_min: draftCook.value ? Number(draftCook.value) : null,
    method: draftMethod.value.trim() || null,
    ingredients: draftLines.value.map((l) => ({
      food_id: l.food_id ?? null,
      raw_text: l.raw_text ?? null,
      quantity: l.quantity == null || l.quantity === ("" as unknown) ? null : Number(l.quantity),
      unit: l.unit || null,
    })),
  };
  try {
    if (editing.value === "new") await meals.createRecipe(body);
    else if (typeof editing.value === "number") {
      await meals.updateRecipe(editing.value, body);
    }
    editing.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "save failed";
  } finally {
    saving.value = false;
  }
}

async function remove(r: Recipe) {
  try {
    await meals.deleteRecipe(r.id);
    recipes.value = recipes.value.filter((x) => x.id !== r.id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "delete failed";
  }
}

function toggle(id: number) {
  open.value = { ...open.value, [id]: !open.value[id] };
}

/** A nutrient the data does not have renders as "—", never as 0. */
const VIT_LABELS: Record<string, string> = {
  vitamin_a_ug: "Vitamin A",
  vitamin_d_ug: "Vitamin D",
  vitamin_e_mg: "Vitamin E",
  vitamin_k_ug: "Vitamin K",
};
const VIT_UNITS: Record<string, string> = {
  vitamin_a_ug: "µg",
  vitamin_d_ug: "µg",
  vitamin_e_mg: "mg",
  vitamin_k_ug: "µg",
};

function num(v: number | null | undefined, digits = 0, suffix = ""): string {
  if (v == null) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

function lineLabel(i: Recipe["ingredients"][number]): string {
  const qty = i.quantity != null ? `${i.quantity}${i.unit ? ` ${i.unit}` : ""} ` : "";
  return `${qty}${i.food_name ?? i.raw_text ?? "—"}`;
}

/** Factor applied to the displayed totals when the user scales a recipe.
 *  The per-serving figures are unaffected by design — that is the point
 *  of scaling: more servings, same plate. */
function factorFor(r: Recipe): number {
  const target = scaleTo.value[r.id];
  if (!target || target === r.servings) return 1;
  return target / Math.max(r.servings, 1);
}

function scaled(r: Recipe, v: number | null | undefined): number | null {
  if (v == null) return null;
  return v * factorFor(r);
}
</script>

<template>
  <div class="recipes">
    <PageHeader title="Recipes">
      <button class="primary" @click="editing === null ? startNew() : (editing = null)">
        <Plus :size="14" /> New recipe
      </button>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="editing !== null" flat :title="editing === 'new' ? 'New recipe' : 'Edit recipe'">
      <div class="fields">
        <label class="wide">
          <span>Name</span>
          <input v-model="draftName" type="text" placeholder="e.g. Sheet-pan chicken" />
        </label>
        <label>
          <span>Servings</span>
          <input v-model.number="draftServings" type="number" min="1" max="100" />
        </label>
        <label>
          <span>Prep (min)</span>
          <input v-model="draftPrep" type="number" min="0" placeholder="optional" />
        </label>
        <label>
          <span>Cook (min)</span>
          <input v-model="draftCook" type="number" min="0" placeholder="optional" />
        </label>
      </div>

      <h3 class="sub">Ingredients</h3>
      <ul v-if="draftLines.length" class="draft-lines">
        <li v-for="(l, idx) in draftLines" :key="idx">
          <input
            v-model.number="l.quantity"
            class="qty-in"
            type="number"
            step="any"
            min="0"
            placeholder="qty"
          />
          <input v-model="l.unit" class="unit-in" type="text" placeholder="unit" />
          <input
            v-if="l.food_id == null"
            v-model="l.raw_text"
            class="free-in"
            type="text"
            placeholder="ingredient"
          />
          <span v-else class="line-name">{{ l.food_name }}</span>
          <button class="icon-btn" title="Remove" @click="dropLine(idx)">
            <XIcon :size="14" />
          </button>
        </li>
      </ul>
      <p v-else class="hint">No ingredients yet.</p>

      <FoodPicker
        ingredients-only
        placeholder="Add an ingredient…"
        @pick="addLine"
      />
      <button class="link" @click="addFreeLine">
        + add a line the catalog does not have
      </button>

      <label class="method">
        <span>Method</span>
        <textarea v-model="draftMethod" rows="5" placeholder="Steps, one per line…" />
      </label>

      <div class="actions">
        <button class="primary" :disabled="saving || !draftName.trim()" @click="save">
          {{ saving ? "Saving…" : "Save recipe" }}
        </button>
        <button class="ghost" @click="editing = null">Cancel</button>
      </div>
    </Card>

    <EmptyState v-if="loading" message="Loading…" />
    <EmptyState v-else-if="!recipes.length && editing === null">
      No recipes yet. Add one and its nutrition is worked out from the
      ingredients.
    </EmptyState>

    <Card v-for="r in recipes" :key="r.id" flat class="recipe">
      <div class="head" @click="toggle(r.id)">
        <button class="chev" :aria-expanded="!!open[r.id]">
          <component :is="open[r.id] ? ChevronDown : ChevronRight" :size="16" />
        </button>
        <div class="titles">
          <strong>{{ r.name }}</strong>
          <span class="meta">
            {{ r.servings }} serving{{ r.servings === 1 ? "" : "s" }}
            <template v-if="r.prep_min || r.cook_min">
              · {{ (r.prep_min ?? 0) + (r.cook_min ?? 0) }} min
            </template>
            · {{ num(r.per_serving.kcal) }} kcal/serving
          </span>
        </div>
        <span
          v-if="r.fat_assessment && r.fat_assessment.verdict !== 'unknown'"
          class="fat-pill"
          :class="r.fat_assessment.verdict"
          :title="r.fat_assessment.reason ?? ''"
        >
          {{ num(r.per_serving.fat_g, 1) }}g fat
        </span>
        <div class="head-actions" @click.stop>
          <button class="icon-btn" title="Edit" @click="startEdit(r)">
            <Pencil :size="14" />
          </button>
          <button class="icon-btn" title="Delete" @click="remove(r)">
            <Trash2 :size="14" />
          </button>
        </div>
      </div>

      <div v-if="open[r.id]" class="detail">
        <div v-if="r.unresolved_count" class="warn">
          <AlertCircle :size="14" />
          <span>
            {{ r.unresolved_count }} ingredient{{ r.unresolved_count === 1 ? "" : "s" }}
            could not be costed, so these totals are an underestimate.
          </span>
        </div>

        <FatAssessment
          v-if="r.fat_assessment"
          :assessment="r.fat_assessment"
          class="fat-block"
        />

        <div v-if="r.energy_split && r.energy_split.kcal_from_macros" class="split">
          <span class="split-label">Energy from</span>
          <span
            v-for="k in (['protein','carbs','fat'] as const)"
            :key="k"
            class="split-part"
            :class="k"
          >
            {{ k }}
            {{ r.energy_split.percent[k] == null ? "—" : r.energy_split.percent[k] + "%" }}
          </span>
          <span v-if="r.energy_split.incomplete" class="split-warn">
            partial — a macro is unknown
          </span>
        </div>

        <div class="scale-row">
          <label>
            <span>Make</span>
            <input
              :value="scaleTo[r.id] ?? r.servings"
              type="number"
              min="1"
              max="100"
              @input="scaleTo[r.id] = Number(($event.target as HTMLInputElement).value)"
            />
            <span>servings</span>
          </label>
          <button
            v-if="factorFor(r) !== 1"
            class="link"
            @click="scaleTo[r.id] = r.servings"
          >
            reset
          </button>
        </div>

        <table class="nutri">
          <thead>
            <tr>
              <th></th>
              <th>Per serving</th>
              <th>Whole recipe</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Calories</th>
              <td>{{ num(r.per_serving.kcal) }}</td>
              <td>{{ num(scaled(r, r.totals.kcal)) }}</td>
            </tr>
            <tr class="emph">
              <th>Fat</th>
              <td>{{ num(r.per_serving.fat_g, 1, " g") }}</td>
              <td>{{ num(scaled(r, r.totals.fat_g), 1, " g") }}</td>
            </tr>
            <tr>
              <th>Saturated</th>
              <td>{{ num(r.per_serving.saturated_fat_g, 1, " g") }}</td>
              <td>{{ num(scaled(r, r.totals.saturated_fat_g), 1, " g") }}</td>
            </tr>
            <tr>
              <th>Protein</th>
              <td>{{ num(r.per_serving.protein_g, 1, " g") }}</td>
              <td>{{ num(scaled(r, r.totals.protein_g), 1, " g") }}</td>
            </tr>
            <tr>
              <th>Carbs</th>
              <td>{{ num(r.per_serving.carbs_g, 1, " g") }}</td>
              <td>{{ num(scaled(r, r.totals.carbs_g), 1, " g") }}</td>
            </tr>
            <tr>
              <th>Fibre</th>
              <td>{{ num(r.per_serving.fiber_g, 1, " g") }}</td>
              <td>{{ num(scaled(r, r.totals.fiber_g), 1, " g") }}</td>
            </tr>
            <tr>
              <th>Sodium</th>
              <td>{{ num(r.per_serving.sodium_mg, 0, " mg") }}</td>
              <td>{{ num(scaled(r, r.totals.sodium_mg), 0, " mg") }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="r.fat_soluble && !r.fat_soluble.no_data">
          <h4>Fat-soluble vitamins (per serving)</h4>
          <ul class="vits">
            <li v-for="(v, k) in r.fat_soluble.present" :key="k">
              <span>{{ VIT_LABELS[k] ?? k }}</span>
              <span>{{ v.toFixed(1) }} {{ VIT_UNITS[k] ?? "" }}</span>
            </li>
          </ul>
          <p v-if="r.fat_soluble.missing.length" class="vit-note">
            {{ r.fat_soluble.missing.length }} not known for these
            ingredients — absent, not zero.
          </p>
        </template>

        <h4>Ingredients</h4>
        <ul class="ings">
          <li v-for="i in r.ingredients" :key="i.id" :class="{ unresolved: i.unresolved_reason }">
            <span>{{ lineLabel(i) }}</span>
            <span v-if="i.unresolved_reason" class="why">{{ i.unresolved_reason }}</span>
            <span v-else-if="i.grams != null" class="g">{{ i.grams.toFixed(0) }} g</span>
          </li>
        </ul>

        <template v-if="r.method">
          <h4>Method</h4>
          <p class="method-text">{{ r.method }}</p>
        </template>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.hint { color: var(--muted-2); font-size: 0.82rem; margin: 0 0 0.5rem; }
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 9px; padding: 0.4rem 0.7rem; font: inherit;
  font-size: 0.85rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
.link {
  background: none; border: 0; color: var(--accent, #38bdf8);
  cursor: pointer; font: inherit; font-size: 0.8rem; padding: 0.3rem 0;
}
.fields {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.6rem;
}
.fields .wide { grid-column: 1 / -1; }
.fields label, .method { display: flex; flex-direction: column; gap: 0.25rem; }
.fields span, .method span { font-size: 0.75rem; color: var(--muted-2); }
input, textarea {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
textarea { resize: vertical; }
.method { margin-top: 0.8rem; }
h3.sub { font-size: 0.8rem; color: var(--muted-2); margin: 1rem 0 0.4rem; font-weight: 600; }
.draft-lines { list-style: none; margin: 0 0 0.5rem; padding: 0; }
.draft-lines li {
  display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.35rem;
}
.qty-in { width: 72px; flex: none; }
.unit-in { width: 88px; flex: none; }
.free-in { flex: 1; }
.line-name { flex: 1; font-size: 0.85rem; }
.actions { display: flex; gap: 0.5rem; margin-top: 0.9rem; }
.head {
  display: flex; align-items: center; gap: 0.55rem; cursor: pointer;
}
.chev {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0; flex: none;
}
.titles { display: flex; flex-direction: column; gap: 0.12rem; flex: 1; min-width: 0; }
.meta { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.head-actions { display: flex; gap: 0.3rem; flex: none; }
.icon-btn {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0.2rem;
}
.icon-btn:hover { color: var(--fg); }
.detail { margin-top: 0.85rem; }
.warn {
  display: flex; align-items: flex-start; gap: 0.4rem; color: #fbbf24;
  font-size: 0.8rem; margin-bottom: 0.7rem;
}
.scale-row { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.7rem; }
.scale-row label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; color: var(--muted-2); }
.scale-row input { width: 70px; }
.nutri {
  width: 100%; border-collapse: collapse; font-size: 0.82rem;
  font-variant-numeric: tabular-nums; margin-bottom: 0.9rem;
}
.nutri th, .nutri td { text-align: right; padding: 0.28rem 0.4rem; }
.nutri thead th { color: var(--muted-2); font-weight: 500; font-size: 0.74rem; }
.nutri tbody th { text-align: left; font-weight: 400; color: var(--muted-2); }
.nutri tbody tr + tr { border-top: 1px solid var(--line); }
.nutri tr.emph td, .nutri tr.emph th { color: var(--fg); font-weight: 600; }
h4 { font-size: 0.78rem; color: var(--muted-2); margin: 0.8rem 0 0.35rem; font-weight: 600; }
.ings { list-style: none; margin: 0; padding: 0; font-size: 0.84rem; }
.ings li {
  display: flex; justify-content: space-between; gap: 0.6rem;
  padding: 0.22rem 0; border-bottom: 1px solid var(--line);
}
.ings li.unresolved { color: var(--muted-2); }
.why { font-size: 0.74rem; color: #fbbf24; flex: none; }
.g { font-size: 0.76rem; color: var(--muted-2); font-variant-numeric: tabular-nums; flex: none; }
.fat-pill {
  flex: none; font-size: 0.72rem; font-weight: 600;
  border-radius: 999px; padding: 0.12rem 0.5rem;
  border: 1px solid var(--line); font-variant-numeric: tabular-nums;
}
.fat-pill.ok { color: #22c55e; border-color: #22c55e55; }
.fat-pill.approaching { color: #fbbf24; border-color: #fbbf2455; }
.fat-pill.high { color: #fb923c; border-color: #fb923c55; }
.fat-pill.very_high { color: #f87171; border-color: #f8717155; }
.fat-block { margin-bottom: 0.8rem; }
.split {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
  font-size: 0.76rem; margin-bottom: 0.8rem;
}
.split-label { color: var(--muted-2); }
.split-part { text-transform: capitalize; font-variant-numeric: tabular-nums; }
.split-part.protein { color: #38bdf8; }
.split-part.carbs { color: #a78bfa; }
.split-part.fat { color: #fb923c; }
.split-warn { color: #fbbf24; }
.vits { list-style: none; margin: 0; padding: 0; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.vits li { display: flex; justify-content: space-between; padding: 0.2rem 0; border-bottom: 1px solid var(--line); }
.vit-note { margin: 0.35rem 0 0; font-size: 0.74rem; color: var(--muted-2); }
.method-text { white-space: pre-wrap; font-size: 0.85rem; line-height: 1.5; margin: 0; }
</style>
