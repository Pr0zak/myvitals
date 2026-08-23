<script setup lang="ts">
/**
 * Scan a packaged food from photos of its packaging.
 *
 * Lives in two places on purpose, because the same photos serve two
 * different intents:
 *
 *   Foods  — "define this product" (catalog entry, no claim of owning it)
 *   Pantry — "I just bought this"  (define it AND stock it)
 *
 * The taxonomy that puts a product definition in the catalog is right,
 * but making someone scan in Foods and then search for the result in
 * Pantry is two steps for one intent. `stock` collapses that.
 *
 * Send several photos of the SAME pack: the Nutrition Facts panel has
 * the numbers and no product name, the front has the name and no
 * numbers, and a third of the ingredients list is transcribed verbatim.
 *
 * Nothing is saved until the user confirms. A transcription error
 * written straight into the catalog is a wrong number nobody knows to
 * look for.
 */
import { computed, ref } from "vue";
import { Camera, Loader2, AlertTriangle, Check } from "lucide-vue-next";
import { meals, type LabelScan } from "@/api/client";

const props = withDefaults(
  defineProps<{
    /** Also add the created food to the pantry. */
    stock?: boolean;
  }>(),
  { stock: false },
);

const emit = defineEmits<{ (e: "saved", foodId: number): void }>();

const busy = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const scan = ref<LabelScan | null>(null);
const name = ref("");
const servingG = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

/** Downscale in the browser: the server limit exists to stop a huge
 *  upload being billed, and re-encoding also strips EXIF. Labels are
 *  small text, so 1600px keeps them legible. */
async function downscale(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const s = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bitmap.width * s);
  c.height = Math.round(bitmap.height * s);
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("could not process the image");
  ctx.drawImage(bitmap, 0, 0, c.width, c.height);
  bitmap.close?.();
  return c.toDataURL("image/jpeg", 0.85).split(",", 2)[1];
}

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  if (!files.length) return;
  if (files.length > 4) {
    error.value = "Pick at most 4 photos — the front, the panel and the "
      + "ingredients is all it can use.";
    return;
  }
  busy.value = true;
  error.value = null;
  scan.value = null;
  try {
    const images = await Promise.all(
      files.map(async (f) => ({
        image_base64: await downscale(f),
        media_type: "image/jpeg",
      })),
    );
    const r = await meals.readLabel(images);
    scan.value = r;
    name.value = r.name;
    servingG.value = r.serving_size_g ? String(r.serving_size_g) : "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not read those photos";
  } finally {
    busy.value = false;
  }
}

const canSave = computed(
  () => !!scan.value && scan.value.convertible && name.value.trim().length > 0,
);

async function save() {
  const r = scan.value;
  if (!r || !canSave.value) return;
  saving.value = true;
  error.value = null;
  try {
    const food = await meals.createFood({
      name: name.value.trim(),
      ...r.per_100g,
      ingredients: r.ingredients ?? null,
      unit_grams: servingG.value ? { serving: Number(servingG.value) } : null,
    } as never);
    if (props.stock) await meals.quickAddPantry([food.id]);
    scan.value = null;
    name.value = "";
    servingG.value = "";
    emit("saved", food.id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not save";
  } finally {
    saving.value = false;
  }
}

function fmt(v: number | null | undefined, d = 1, s = ""): string {
  return v == null ? "—" : `${v.toFixed(d)}${s}`;
}
</script>

<template>
  <div class="pkg">
    <div class="head">
      <Camera :size="15" />
      <strong>Scan a package</strong>
    </div>
    <p class="sub">
      Photograph the <strong>front</strong>, the <strong>Nutrition Facts
      panel</strong> and, if you like, the <strong>ingredients</strong> —
      select them together. The panel has the numbers but no product name;
      the front has the name.
      <template v-if="stock">
        Saving adds it to your pantry as well as the catalog.
      </template>
    </p>

    <button class="primary" :disabled="busy" @click="fileInput?.click()">
      <component :is="busy ? Loader2 : Camera" :size="14" :class="{ spin: busy }" />
      {{ busy ? "Reading…" : "Choose photos" }}
    </button>
    <input ref="fileInput" type="file" accept="image/*" multiple hidden
           @change="onFiles" />

    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="scan" class="result">
      <label class="field">
        <span>Name</span>
        <input v-model="name" type="text" placeholder="product name" />
      </label>

      <p v-if="!scan.convertible" class="warn">
        <AlertTriangle :size="13" /> {{ scan.reason }}
      </p>

      <table v-else class="nutri">
        <caption>Per 100 g</caption>
        <tbody>
          <tr><th>Calories</th><td>{{ fmt(scan.per_100g.kcal, 0) }}</td></tr>
          <tr class="emph"><th>Fat</th><td>{{ fmt(scan.per_100g.fat_g, 1, " g") }}</td></tr>
          <tr><th>Saturated</th><td>{{ fmt(scan.per_100g.saturated_fat_g, 1, " g") }}</td></tr>
          <tr><th>Protein</th><td>{{ fmt(scan.per_100g.protein_g, 1, " g") }}</td></tr>
          <tr><th>Carbs</th><td>{{ fmt(scan.per_100g.carbs_g, 1, " g") }}</td></tr>
          <tr><th>Fibre</th><td>{{ fmt(scan.per_100g.fiber_g, 1, " g") }}</td></tr>
          <tr><th>Sugar</th><td>{{ fmt(scan.per_100g.sugar_g, 1, " g") }}</td></tr>
          <tr><th>Sodium</th><td>{{ fmt(scan.per_100g.sodium_mg, 0, " mg") }}</td></tr>
        </tbody>
      </table>

      <label class="field">
        <span>Serving (g)</span>
        <input v-model="servingG" type="number" step="any" placeholder="optional" />
      </label>

      <template v-if="scan.ingredients">
        <span class="cap">Ingredients</span>
        <p class="ingredients">{{ scan.ingredients }}</p>
      </template>

      <p v-if="scan.unreadable.length" class="warn">
        <AlertTriangle :size="13" />
        Couldn't read: {{ scan.unreadable.join(", ") }} — left blank rather
        than guessed.
      </p>
      <p v-for="n in scan.notes" :key="n" class="warn">
        <AlertTriangle :size="13" /> {{ n }}
      </p>

      <button class="primary wide" :disabled="saving || !canSave" @click="save">
        <Check :size="14" />
        {{ saving ? "Saving…" : stock ? "Save & add to pantry" : "Save food" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.pkg { display: flex; flex-direction: column; }
.head { display: flex; align-items: center; gap: 0.4rem; }
.sub { margin: 0.35rem 0 0.6rem; font-size: 0.78rem; color: var(--muted-2); line-height: 1.5; }
.sub strong { color: var(--fg); }
button.primary {
  display: inline-flex; align-items: center; gap: 0.35rem; align-self: flex-start;
  border-radius: 9px; padding: 0.38rem 0.7rem; font: inherit; font-size: 0.82rem;
  cursor: pointer; border: 1px solid transparent;
  background: var(--accent, #38bdf8); color: #04121c;
}
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.wide { width: 100%; justify-content: center; margin-top: 0.7rem; align-self: stretch; }
.err { color: #f87171; font-size: 0.8rem; margin: 0.5rem 0 0; }
.result { margin-top: 0.8rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.6rem; }
.field span { font-size: 0.75rem; color: var(--muted-2); }
input {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
.nutri { width: 100%; border-collapse: collapse; font-size: 0.84rem; font-variant-numeric: tabular-nums; margin-bottom: 0.6rem; }
.nutri caption { text-align: left; font-size: 0.72rem; color: var(--muted-2); margin-bottom: 0.3rem; }
.nutri th { text-align: left; font-weight: 400; color: var(--muted-2); padding: 0.24rem 0; }
.nutri td { text-align: right; padding: 0.24rem 0; }
.nutri tr + tr { border-top: 1px solid var(--line); }
.nutri tr.emph th, .nutri tr.emph td { color: var(--fg); font-weight: 600; }
.cap { font-size: 0.72rem; color: var(--muted-2); }
.ingredients { margin: 0.2rem 0 0.5rem; font-size: 0.78rem; line-height: 1.5; color: var(--muted-2); }
.warn { display: flex; align-items: flex-start; gap: 0.3rem; margin: 0.4rem 0 0; font-size: 0.78rem; color: #fbbf24; line-height: 1.45; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
