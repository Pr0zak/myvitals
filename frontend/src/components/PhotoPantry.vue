<script setup lang="ts">
/**
 * Add to the pantry from a photograph.
 *
 * Filling a pantry by hand is the friction that stops one being kept
 * current. A photo of a shelf covers in one action what typing covers in
 * fifteen.
 *
 * Three rules this component exists to enforce, all of which are easy to
 * lose to a convenience tweak:
 *
 * 1. NOTHING IS ADDED AUTOMATICALLY. Vision misidentifies confidently,
 *    and a pantry that grows items you did not put there stops being
 *    trustworthy — which makes the shopping list built on it worse than
 *    useless. Everything arrives unticked; low-confidence items stay
 *    unticked even when you tick all.
 * 2. The photo is downscaled HERE before it is sent. A 4 MB phone
 *    photo identifies no better than a 600 KB one and costs more.
 * 3. The user is told, before they choose a file, that the photo goes to
 *    their AI provider. This is the only place in the app that sends an
 *    image anywhere.
 */
import { computed, ref } from "vue";
import { Camera, Loader2, AlertTriangle, Check } from "lucide-vue-next";
import { meals, type IdentifiedFood } from "@/api/client";

const emit = defineEmits<{ (e: "added"): void }>();

const busy = ref(false);
const error = ref<string | null>(null);
const items = ref<IdentifiedFood[]>([]);
const notes = ref<string[]>([]);
const picked = ref<Record<number, boolean>>({});
const adding = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const cameraInput = ref<HTMLInputElement | null>(null);

/** Longest edge after downscaling. Enough for a model to read a label,
 *  small enough that a phone photo stops being a multi-megabyte upload. */
const MAX_EDGE = 1400;
const JPEG_QUALITY = 0.82;

/** Downscale and re-encode to JPEG in the browser.
 *
 *  Done client-side deliberately: the server limit exists to stop a huge
 *  upload being billed, and the honest way to respect it is not to send
 *  the huge upload. Also strips EXIF — including GPS — as a side effect
 *  of re-encoding through a canvas, which is the right default for an
 *  image about to leave the machine.
 */
async function downscale(file: File): Promise<{ b64: string; type: string }> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("could not process the image");
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close?.();
  const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  return { b64: dataUrl.split(",", 2)[1], type: "image/jpeg" };
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;

  busy.value = true;
  error.value = null;
  items.value = [];
  notes.value = [];
  picked.value = {};
  try {
    const { b64, type } = await downscale(file);
    const res = await meals.identifyFoods(b64, type);
    items.value = res.items;
    notes.value = res.notes;
    // Pre-tick only what the model was confident about. A bulk accept
    // must not sweep in guesses.
    const pre: Record<number, boolean> = {};
    res.items.forEach((it, i) => {
      pre[i] = it.confidence === "high" && !it.unmatched;
    });
    picked.value = pre;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not read that photo";
  } finally {
    busy.value = false;
  }
}

const chosen = computed(() =>
  items.value.filter((_, i) => picked.value[i]),
);

async function addChosen() {
  const ids = chosen.value
    .map((i) => i.food_id)
    .filter((v): v is number => v != null);
  if (!ids.length) return;
  adding.value = true;
  error.value = null;
  try {
    await meals.quickAddPantry(ids);
    items.value = [];
    notes.value = [];
    picked.value = {};
    emit("added");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not add";
  } finally {
    adding.value = false;
  }
}

function toggleAll(on: boolean) {
  const next: Record<number, boolean> = {};
  items.value.forEach((it, i) => {
    // Even "select all" leaves guesses alone — that is the point of
    // reporting confidence at all.
    next[i] = on ? it.confidence !== "low" && !it.unmatched : false;
  });
  picked.value = next;
}
</script>

<template>
  <div class="photo">
    <div class="head">
      <Camera :size="15" />
      <strong>Add from a photo</strong>
    </div>
    <!-- "Photograph a shelf, a fridge or a receipt" is what the button
         plainly does, and went. Where the photo GOES stays: it is the one
         thing here nobody can infer from the interface, and it is the
         reason to trust the button. -->
    <p class="sub">
      Sent to your AI provider to be read, then discarded — never stored
      here. Nothing is added until you confirm it.
    </p>

    <div class="buttons">
      <button class="primary" :disabled="busy" @click="cameraInput?.click()">
        <component :is="busy ? Loader2 : Camera" :size="14" :class="{ spin: busy }" />
        {{ busy ? "Reading…" : "Take a photo" }}
      </button>
      <button class="ghost" :disabled="busy" @click="fileInput?.click()">
        Choose a file
      </button>
      <input
        ref="cameraInput"
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        @change="onFile"
      />
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onFile" />
    </div>

    <p v-if="error" class="err">{{ error }}</p>

    <template v-if="items.length">
      <div class="results-head">
        <span>{{ items.length }} found</span>
        <span class="spacer" />
        <button class="link" @click="toggleAll(true)">select likely</button>
        <button class="link" @click="toggleAll(false)">none</button>
      </div>

      <ul class="results">
        <li v-for="(it, i) in items" :key="i" :class="{ dim: it.unmatched }">
          <input
            type="checkbox"
            :checked="!!picked[i]"
            :disabled="it.unmatched"
            @change="picked[i] = ($event.target as HTMLInputElement).checked"
          />
          <span class="name">
            {{ it.concept ?? it.name }}
            <span v-if="it.detail" class="detail">{{ it.detail }}</span>
            <span v-if="it.unmatched" class="detail">
              not in the catalog — add it by hand below
            </span>
          </span>
          <span class="conf" :class="it.confidence">{{ it.confidence }}</span>
        </li>
      </ul>

      <p v-for="n in notes" :key="n" class="note">
        <AlertTriangle :size="12" /> {{ n }}
      </p>

      <button
        class="primary wide"
        :disabled="adding || !chosen.length"
        @click="addChosen"
      >
        <Check :size="14" />
        {{ adding ? "Adding…" : `Add ${chosen.length} to pantry` }}
      </button>
    </template>

    <p v-else-if="notes.length" class="note">
      <AlertTriangle :size="12" /> {{ notes.join(" ") }}
    </p>
  </div>
</template>

<style scoped>
.photo { display: flex; flex-direction: column; }
.head { display: flex; align-items: center; gap: 0.4rem; }
.sub { margin: 0.35rem 0 0.6rem; font-size: 0.78rem; color: var(--muted-2); line-height: 1.5; }
.buttons { display: flex; gap: 0.5rem; flex-wrap: wrap; }
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 9px; padding: 0.38rem 0.7rem; font: inherit;
  font-size: 0.82rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled, button.ghost:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
button.wide { width: 100%; justify-content: center; margin-top: 0.7rem; }
.link { background: none; border: 0; color: var(--accent, #38bdf8); cursor: pointer; font: inherit; font-size: 0.76rem; padding: 0; }
.err { color: #f87171; font-size: 0.8rem; margin: 0.5rem 0 0; }
.results-head {
  display: flex; align-items: center; gap: 0.6rem;
  margin: 0.8rem 0 0.3rem; font-size: 0.76rem; color: var(--muted-2);
}
.spacer { flex: 1; }
.results { list-style: none; margin: 0; padding: 0; }
.results li {
  display: flex; align-items: flex-start; gap: 0.5rem;
  padding: 0.32rem 0; border-bottom: 1px solid var(--line); font-size: 0.85rem;
}
.results li.dim { opacity: 0.6; }
.name { flex: 1; min-width: 0; }
.detail { display: block; font-size: 0.72rem; color: var(--muted-2); }
.conf {
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.03em;
  border-radius: 999px; padding: 0.05rem 0.4rem; border: 1px solid var(--line);
  flex: none;
}
.conf.high { color: #22c55e; border-color: #22c55e55; }
.conf.medium { color: #fbbf24; border-color: #fbbf2455; }
.conf.low { color: var(--muted-2); }
.note {
  display: flex; align-items: flex-start; gap: 0.3rem;
  margin: 0.5rem 0 0; font-size: 0.76rem; color: #fbbf24; line-height: 1.45;
}
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
