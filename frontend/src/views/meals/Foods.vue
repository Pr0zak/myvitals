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
import PackageScan from "@/components/PackageScan.vue";
import { Plus, Trash2, Pencil, Camera, Loader2 } from "lucide-vue-next";
import { meals, type Food, type MealsStats, type BarcodeHit
} from "@/api/client";

const selected = ref<Food | null>(null);
const barcode = ref("");
const barcodeBusy = ref(false);
const barcodeError = ref<string | null>(null);
const barcodeHit = ref<BarcodeHit | null>(null);

/**
 * Look a pack up by its number. Nothing is saved — the result is shown
 * for the user to check against the thing in their hand, because Open
 * Food Facts is crowd-sourced and its entries are sometimes wrong in
 * ways only they can see.
 */
async function doBarcode() {
  const code = barcode.value.trim();
  if (!code) return;
  barcodeBusy.value = true;
  barcodeError.value = null;
  barcodeHit.value = null;
  try {
    barcodeHit.value = await meals.lookupBarcode(code);
  } catch (e) {
    // Not found is an ordinary outcome with a good next step, so it is
    // not phrased as a failure.
    const msg = e instanceof Error ? e.message : "";
    barcodeError.value = msg.includes("404")
      ? "Nothing found for that barcode. Scan the label below instead — it needs no database."
      : msg || "could not look that up";
  } finally {
    barcodeBusy.value = false;
  }
}

const stats = ref<MealsStats | null>(null);
const error = ref<string | null>(null);
const ingredientsOnly = ref(false);

const editing = ref(false);
// MEAL-8: scan the panel instead of typing thirteen numbers off it.
const scanBusy = ref(false);
const scanNotes = ref<string[]>([]);
const scanUnreadable = ref<string[]>([]);
const scanReason = ref<string | null>(null);
const labelInput = ref<HTMLInputElement | null>(null);

/** Downscale in the browser: the server limit exists to stop a huge
 *  upload being billed, and re-encoding also strips EXIF. Labels are
 *  small text, so 1600px keeps them legible. */
async function downscaleLabel(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bitmap.width * scale);
  c.height = Math.round(bitmap.height * scale);
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("could not process the image");
  ctx.drawImage(bitmap, 0, 0, c.width, c.height);
  bitmap.close?.();
  return c.toDataURL("image/jpeg", 0.85).split(",", 2)[1];
}

async function onLabel(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  if (!files.length) return;
  if (files.length > 4) {
    error.value = "Pick at most 4 photos — the front, the panel and the "
      + "ingredients is all it can use.";
    return;
  }
  scanBusy.value = true;
  error.value = null;
  scanNotes.value = [];
  scanUnreadable.value = [];
  scanReason.value = null;
  try {
    // Send them together: the panel carries the numbers and no product
    // name, the front carries the name and no numbers, and a third photo
    // of the ingredients list is transcribed verbatim.
    const images = await Promise.all(
      files.map(async (f) => ({
        image_base64: await downscaleLabel(f),
        media_type: "image/jpeg",
      })),
    );
    const r = await meals.readLabel(images);
    // Fill the form for confirmation — never save directly. A
    // transcription error written straight into the catalog is a wrong
    // number nobody knows to look for.
    editing.value = true;
    selected.value = null;
    if (r.name) draft.value.name = r.name;
    const n = r.per_100g;
    const put = (k: keyof typeof draft.value, v: number | null | undefined) => {
      if (v != null) (draft.value[k] as string) = String(v);
    };
    put("kcal", n.kcal); put("protein_g", n.protein_g);
    put("carbs_g", n.carbs_g); put("fat_g", n.fat_g);
    put("saturated_fat_g", n.saturated_fat_g); put("fiber_g", n.fiber_g);
    put("sugar_g", n.sugar_g); put("sodium_mg", n.sodium_mg);
    if (r.serving_size_g) draft.value.serving_g = String(r.serving_size_g);
    draft.value.ingredients = r.ingredients ?? "";
    scanNotes.value = r.notes;
    scanUnreadable.value = r.unreadable;
    scanReason.value = r.convertible ? null : r.reason;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not read that label";
  } finally {
    scanBusy.value = false;
  }
}
const saving = ref(false);
const draft = ref({
  name: "", category: "", kcal: "", protein_g: "", carbs_g: "", fat_g: "",
  saturated_fat_g: "", fiber_g: "", sugar_g: "", sodium_mg: "", serving_g: "",
  ingredients: "",
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
    ingredients: "",
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
    ingredients: f.ingredients ?? "",
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
    ingredients: d.ingredients.trim() || null,
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
    <PageHeader title="Food catalog">
      <button class="ghost" :disabled="scanBusy" @click="labelInput?.click()">
        <component :is="scanBusy ? Loader2 : Camera" :size="14"
                   :class="{ spin: scanBusy }" />
        {{ scanBusy ? "Reading…" : "Scan a package" }}
      </button>
      <button class="primary" @click="startNew">
        <Plus :size="14" /> Add a food
      </button>
      <input ref="labelInput" type="file" accept="image/*" multiple
             hidden @change="onLabel" />
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
      <!-- A browser cannot scan a barcode without shipping a decoder,
           and the phone has one. Typing the number is the honest web
           equivalent, and reaches the same lookup. -->
      <Card flat>
        <div class="barcode-row">
          <input
            v-model="barcode"
            inputmode="numeric"
            placeholder="Barcode number"
            @keyup.enter="doBarcode"
          />
          <button class="primary" :disabled="barcodeBusy || !barcode.trim()"
                  @click="doBarcode">
            {{ barcodeBusy ? "Looking up…" : "Look up" }}
          </button>
        </div>
        <p v-if="barcodeError" class="err">{{ barcodeError }}</p>
        <div v-if="barcodeHit" class="barcode-hit">
          <strong>{{ barcodeHit.name }}</strong>
          <span :class="barcodeHit.origin === 'local' ? 'ok' : 'dim'">
            {{ barcodeHit.origin === "local"
               ? "already in your catalog"
               : "from Open Food Facts" }}
            <template v-if="barcodeHit.package_size">
              · {{ barcodeHit.package_size }}
            </template>
          </span>
          <!-- Per 100 g, verbatim. A wrong crowd-sourced entry is usually
               obvious from these, which is why they are shown before
               anything is saved rather than after. -->
          <span class="dim mono">
            {{ [
                 barcodeHit.nutrition.kcal != null
                   ? `${Math.round(barcodeHit.nutrition.kcal)} kcal` : null,
                 barcodeHit.nutrition.fat_g != null
                   ? `${Math.round(barcodeHit.nutrition.fat_g)} g fat` : null,
                 barcodeHit.nutrition.protein_g != null
                   ? `${Math.round(barcodeHit.nutrition.protein_g)} g protein` : null,
               ].filter(Boolean).join(" · ") || "no nutrition published" }}
            per 100 g
          </span>
        </div>
      </Card>

      <PackageScan @saved="loadStats" />
    </Card>

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
      <p v-if="scanReason" class="warn-line">{{ scanReason }}</p>
      <p v-if="scanUnreadable.length" class="warn-line">
        Couldn't read on the label: {{ scanUnreadable.join(", ") }} — left
        blank rather than guessed.
      </p>
      <p v-for="n in scanNotes" :key="n" class="warn-line">{{ n }}</p>
      <p class="hint">
        Photograph the <strong>front of the pack</strong>, the
        <strong>Nutrition Facts panel</strong> and, if you like, the
        <strong>ingredients list</strong> — select them together. The panel
        has the numbers but no product name; the front has the name.
      </p>
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
        <label class="wide">
          <span>Ingredients (as printed)</span>
          <textarea v-model="draft.ingredients" rows="3"
                    placeholder="optional — transcribed from a photo of the ingredients list" />
        </label>
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

      <template v-if="selected.ingredients">
        <h4>Ingredients</h4>
        <p class="ingredients">{{ selected.ingredients }}</p>
      </template>

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
.warn-line { color: #fbbf24; font-size: 0.78rem; margin: 0 0 0.45rem; line-height: 1.45; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
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
input, textarea {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
.actions { display: flex; gap: 0.5rem; margin-top: 0.9rem; }
textarea { font: inherit; font-size: 0.85rem; padding: 0.4rem 0.55rem; resize: vertical; }
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
.ingredients { margin: 0; font-size: 0.8rem; line-height: 1.5; color: var(--muted-2); }
.units { list-style: none; margin: 0; padding: 0; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.units li { display: flex; justify-content: space-between; padding: 0.2rem 0; border-bottom: 1px solid var(--line); }
.barcode-row { display: flex; gap: 0.5rem; }
.barcode-row input { flex: 1; }
.barcode-hit { display: flex; flex-direction: column; gap: 0.2rem; margin-top: 0.7rem; }
.barcode-hit .ok { color: var(--good, #5dff3b); font-size: 0.8rem; }
.barcode-hit .dim { color: var(--muted); font-size: 0.8rem; }
.mono { font-variant-numeric: tabular-nums; }
</style>
