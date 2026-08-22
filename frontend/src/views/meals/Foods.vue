<script setup lang="ts">
/**
 * Browse the food catalog and add anything it does not have.
 *
 * The catalog is a bundled USDA extract — ingredients, prepared dishes
 * and named restaurant menu items. Adding your own matters because
 * roughly half of what this user eats is packaged, and a package label
 * is the only source for it.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import { Plus, Trash2, Pencil } from "lucide-vue-next";
import { meals, type Food, type MealsStats } from "@/api/client";

const selected = ref<Food | null>(null);
const stats = ref<MealsStats | null>(null);
const error = ref<string | null>(null);
const ingredientsOnly = ref(false);

const editing = ref(false);
const saving = ref(false);
const draft = ref({
  name: "", category: "", kcal: "", protein_g: "", carbs_g: "", fat_g: "",
  saturated_fat_g: "", fiber_g: "", sugar_g: "", sodium_mg: "", serving_g: "",
});

async function loadStats() {
  try {
    stats.value = await meals.stats();
  } catch {
    // The counts are decoration on this page; a failure here must not
    // stop the search working.
    stats.value = null;
  }
}
onMounted(loadStats);

function resetDraft() {
  draft.value = {
    name: "", category: "", kcal: "", protein_g: "", carbs_g: "", fat_g: "",
    saturated_fat_g: "", fiber_g: "", sugar_g: "", sodium_mg: "", serving_g: "",
  };
}

function startNew() {
  resetDraft();
  editing.value = true;
  selected.value = null;
}

function startEdit(f: Food) {
  draft.value = {
    name: f.name,
    category: f.category ?? "",
    kcal: f.kcal?.toString() ?? "",
    protein_g: f.protein_g?.toString() ?? "",
    carbs_g: f.carbs_g?.toString() ?? "",
    fat_g: f.fat_g?.toString() ?? "",
    saturated_fat_g: f.saturated_fat_g?.toString() ?? "",
    fiber_g: f.fiber_g?.toString() ?? "",
    sugar_g: f.sugar_g?.toString() ?? "",
    sodium_mg: f.sodium_mg?.toString() ?? "",
    serving_g: f.unit_grams?.serving?.toString() ?? "",
  };
  editing.value = true;
}

/** Blank means unknown, not zero. Sending 0 for a field the user left
 *  empty would assert a fact the label never gave. */
function orNull(v: string): number | null {
  const t = v.trim();
  return t === "" ? null : Number(t);
}

async function save() {
  if (!draft.value.name.trim()) return;
  saving.value = true;
  error.value = null;
  const d = draft.value;
  const body: Record<string, unknown> = {
    name: d.name.trim(),
    category: d.category.trim() || null,
    kcal: orNull(d.kcal),
    protein_g: orNull(d.protein_g),
    carbs_g: orNull(d.carbs_g),
    fat_g: orNull(d.fat_g),
    saturated_fat_g: orNull(d.saturated_fat_g),
    fiber_g: orNull(d.fiber_g),
    sugar_g: orNull(d.sugar_g),
    sodium_mg: orNull(d.sodium_mg),
    unit_grams: orNull(d.serving_g) ? { serving: Number(d.serving_g) } : null,
  };
  try {
    const saved = selected.value
      ? await meals.updateFood(selected.value.id, body as never)
      : await meals.createFood(body as never);
    selected.value = saved;
    editing.value = false;
    await loadStats();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "save failed";
  } finally {
    saving.value = false;
  }
}

async function remove(f: Food) {
  error.value = null;
  try {
    await meals.deleteFood(f.id);
    selected.value = null;
    await loadStats();
  } catch (e) {
    // The backend refuses to delete bundled rows, because the seeder
    // would put them straight back on the next restart.
    error.value = e instanceof Error ? e.message : "delete failed";
  }
}

const rows = computed(() => {
  const f = selected.value;
  if (!f) return [];
  return [
    ["Calories", f.kcal, 0, ""],
    ["Fat", f.fat_g, 1, " g"],
    ["Saturated fat", f.saturated_fat_g, 1, " g"],
    ["Protein", f.protein_g, 1, " g"],
    ["Carbs", f.carbs_g, 1, " g"],
    ["Fibre", f.fiber_g, 1, " g"],
    ["Sugar", f.sugar_g, 1, " g"],
    ["Sodium", f.sodium_mg, 0, " mg"],
  ] as Array<[string, number | null, number, string]>;
});

function fmt(v: number | null, digits: number, suffix: string): string {
  return v == null ? "—" : `${v.toFixed(digits)}${suffix}`;
}
</script>

<template>
  <div class="foods">
    <PageHeader title="Foods">
      <button class="primary" @click="startNew">
        <Plus :size="14" /> Add a food
      </button>
    </PageHeader>

    <p class="purpose">
      A reference catalog — look up what a food contains, or add one the
      catalog doesn't have. Adding a food here does <strong>not</strong>
      mean you have it; that's the
      <RouterLink to="/meals/pantry">Pantry</RouterLink>.
    </p>

    <p v-if="stats" class="counts">
      {{ stats.foods.toLocaleString() }} foods in the catalog
      <template v-if="stats.user_foods">
        · {{ stats.user_foods }} added by you
      </template>
    </p>

    <p v-if="error" class="err">{{ error }}</p>

    <Card flat>
      <label class="toggle">
        <input v-model="ingredientsOnly" type="checkbox" />
        <span>Ingredients only (hide prepared and restaurant foods)</span>
      </label>
      <FoodPicker
        :ingredients-only="ingredientsOnly"
        placeholder="Search 11,000+ foods…"
        @pick="(f) => { selected = f; editing = false; }"
      />
    </Card>

    <Card v-if="editing" flat :title="selected ? 'Edit food' : 'Add a food'">
      <p class="hint">
        Enter the figures <strong>per 100 g</strong>, the way a label's
        nutrition panel gives them. Leave anything the label does not
        state blank — blank means unknown, which is not the same as zero.
      </p>
      <div class="grid">
        <label class="wide">
          <span>Name</span>
          <input v-model="draft.name" type="text" placeholder="e.g. Trader Joe's chili crisp" />
        </label>
        <label class="wide">
          <span>Category</span>
          <input v-model="draft.category" type="text" placeholder="optional" />
        </label>
        <label><span>Calories</span><input v-model="draft.kcal" type="number" step="any" /></label>
        <label><span>Fat (g)</span><input v-model="draft.fat_g" type="number" step="any" /></label>
        <label><span>Saturated (g)</span><input v-model="draft.saturated_fat_g" type="number" step="any" /></label>
        <label><span>Protein (g)</span><input v-model="draft.protein_g" type="number" step="any" /></label>
        <label><span>Carbs (g)</span><input v-model="draft.carbs_g" type="number" step="any" /></label>
        <label><span>Fibre (g)</span><input v-model="draft.fiber_g" type="number" step="any" /></label>
        <label><span>Sugar (g)</span><input v-model="draft.sugar_g" type="number" step="any" /></label>
        <label><span>Sodium (mg)</span><input v-model="draft.sodium_mg" type="number" step="any" /></label>
        <label><span>Serving (g)</span><input v-model="draft.serving_g" type="number" step="any" placeholder="optional" /></label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="saving || !draft.name.trim()" @click="save">
          {{ saving ? "Saving…" : "Save" }}
        </button>
        <button class="ghost" @click="editing = false">Cancel</button>
      </div>
    </Card>

    <Card v-if="selected && !editing" flat>
      <div class="head">
        <div>
          <strong>{{ selected.concept
            ? selected.concept.charAt(0).toUpperCase() + selected.concept.slice(1)
            : selected.name }}</strong>
          <span v-if="selected.concept" class="cat">{{ selected.name }}</span>
          <span v-if="selected.category" class="cat">{{ selected.category }}</span>
        </div>
        <div class="head-actions">
          <button class="icon-btn" title="Edit" @click="startEdit(selected)">
            <Pencil :size="14" />
          </button>
          <button
            v-if="selected.source !== 'usda'"
            class="icon-btn"
            title="Delete"
            @click="remove(selected)"
          >
            <Trash2 :size="14" />
          </button>
        </div>
      </div>

      <table class="nutri">
        <caption>Per 100 g</caption>
        <tbody>
          <tr v-for="[label, v, d, sfx] in rows" :key="label" :class="{ emph: label === 'Fat' }">
            <th>{{ label }}</th>
            <td>{{ fmt(v, d, sfx) }}</td>
          </tr>
        </tbody>
      </table>

      <template v-if="selected.unit_grams && Object.keys(selected.unit_grams).length">
        <h4>Measures</h4>
        <ul class="units">
          <li v-for="(g, u) in selected.unit_grams" :key="u">
            <span>1 {{ u }}</span><span>{{ g }} g</span>
          </li>
        </ul>
      </template>
    </Card>

    <EmptyState v-else-if="!editing">
      Search for a food to see its nutrition, or add one the catalog does
      not have.
    </EmptyState>
  </div>
</template>

<style scoped>
.counts { color: var(--muted-2); font-size: 0.8rem; margin: -0.2rem 0 0.8rem; }
.purpose {
  color: var(--muted-2); font-size: 0.8rem; line-height: 1.5;
  margin: -0.4rem 0 0.5rem;
}
.purpose strong { color: var(--fg); }
.err { color: #f87171; font-size: 0.85rem; }
.hint { color: var(--muted-2); font-size: 0.8rem; margin: 0 0 0.7rem; line-height: 1.45; }
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 9px; padding: 0.4rem 0.7rem; font: inherit;
  font-size: 0.85rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
.toggle {
  display: flex; align-items: center; gap: 0.45rem;
  font-size: 0.8rem; color: var(--muted-2); margin-bottom: 0.6rem;
}
.toggle input { width: auto; }
.grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.6rem;
}
.grid .wide { grid-column: 1 / -1; }
.grid label { display: flex; flex-direction: column; gap: 0.25rem; }
.grid span { font-size: 0.75rem; color: var(--muted-2); }
input {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
.actions { display: flex; gap: 0.5rem; margin-top: 0.9rem; }
.head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 0.7rem; margin-bottom: 0.7rem;
}
.cat { display: block; font-size: 0.75rem; color: var(--muted-2); margin-top: 0.15rem; }
.head-actions { display: flex; gap: 0.3rem; flex: none; }
.icon-btn {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0.2rem;
}
.icon-btn:hover { color: var(--fg); }
.nutri { width: 100%; border-collapse: collapse; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
.nutri caption { text-align: left; font-size: 0.74rem; color: var(--muted-2); margin-bottom: 0.35rem; }
.nutri th { text-align: left; font-weight: 400; color: var(--muted-2); padding: 0.28rem 0; }
.nutri td { text-align: right; padding: 0.28rem 0; }
.nutri tr + tr { border-top: 1px solid var(--line); }
.nutri tr.emph th, .nutri tr.emph td { color: var(--fg); font-weight: 600; }
h4 { font-size: 0.78rem; color: var(--muted-2); margin: 0.9rem 0 0.35rem; font-weight: 600; }
.units { list-style: none; margin: 0; padding: 0; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.units li { display: flex; justify-content: space-between; padding: 0.2rem 0; border-bottom: 1px solid var(--line); }
</style>
