<script setup lang="ts">
/**
 * AI meal suggestions.
 *
 * What makes this worth having over any generic meal app: it already
 * knows the weight goal and its trend, the training load, the fasting
 * state, the day's planned workout — and the per-meal fat constraint.
 * A generic app starts cold and "healthy" means whatever its editors
 * decided.
 *
 * The fat verdict on each suggestion is NOT the model's opinion. The
 * server re-judges every estimate with the same deterministic function
 * the recipe pages use and overwrites whatever the model thought, so
 * this card cannot disagree with the rest of the app about the one
 * number a cholecystectomy makes matter.
 *
 * Loading is explicit — a button, never on mount. Every call is billed
 * against the user's own Anthropic key, and a page that spends money by
 * being visited is a bad page.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import FatAssessment from "@/components/FatAssessment.vue";
import { Sparkles, Clock, ShoppingBasket, Info, CalendarPlus, BookOpen } from "lucide-vue-next";
import {
  api, meals, type MealSuggestionCard, type SuggestedIngredient,
} from "@/api/client";
import { toLocalISO } from "@/dates";

const card = ref<MealSuggestionCard | null>(null);
const generatedAt = ref<string | null>(null);
const model = ref<string | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const planned = ref<Record<string, boolean>>({});
const savedRecipes = ref<Record<string, boolean>>({});
const savingRecipe = ref<string | null>(null);
const headlineOpen = ref(false);
const expanded = ref<Record<string, boolean>>({});

/**
 * Save a suggestion as a real, costed recipe.
 *
 * Sends terms and amounts only. The server resolves each against the food
 * catalog and computes the nutrition, so nothing the model estimated ever
 * becomes a number on the recipe page — if the two disagree, the catalog
 * is the one that is right.
 */
async function saveAsRecipe(s: {
  name: string; why?: string; servings?: number; method?: string | null;
  est_prep_min?: number | null; ingredients?: SuggestedIngredient[];
}) {
  savingRecipe.value = s.name;
  try {
    await meals.saveSuggestionAsRecipe({
      name: s.name,
      servings: s.servings ?? 1,
      method: s.method ?? null,
      why: s.why ?? null,
      est_prep_min: s.est_prep_min ?? null,
      ingredients: s.ingredients ?? [],
    });
    savedRecipes.value = { ...savedRecipes.value, [s.name]: true };
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not save the recipe";
  } finally {
    savingRecipe.value = null;
  }
}

async function loadCached() {
  try {
    const r = await api.mealSuggestLatest();
    if (r) {
      card.value = r.analysis as unknown as MealSuggestionCard;
      generatedAt.value = r.generated_at ?? null;
      model.value = r.model ?? null;
    }
  } catch {
    // A missing cached card is the normal first-run state, not an error.
  }
}
onMounted(loadCached);

async function generate() {
  loading.value = true;
  error.value = null;
  try {
    const r = await api.mealSuggest();
    card.value = r.analysis as unknown as MealSuggestionCard;
    generatedAt.value = r.generated_at ?? null;
    model.value = r.model ?? null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not generate";
  } finally {
    loading.value = false;
  }
}

/** Drop a suggestion onto today's plan as a note. It is not a saved
 *  recipe, so it goes in as text rather than pretending to be one. */
async function addToPlan(name: string, slot: string) {
  try {
    await meals.addPlanEntry({
      day: toLocalISO(new Date()),
      slot: slot || "dinner",
      note: name,
    });
    planned.value = { ...planned.value, [name]: true };
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not add to plan";
  }
}

const stamp = computed(() => {
  if (!generatedAt.value) return null;
  return new Date(generatedAt.value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
});
</script>

<template>
  <div class="suggest">
    <PageHeader title="Suggest a meal">
      <button class="primary" :disabled="loading" @click="generate">
        <Sparkles :size="14" />
        {{ loading ? "Thinking…" : card ? "Refresh" : "Get suggestions" }}
      </button>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>

    <EmptyState v-if="!card && !loading">
      Suggestions are built from what's in your pantry plus today's
      training load, fasting state and weight goal. Nothing is generated
      until you ask — each run uses your own Anthropic key.
    </EmptyState>

    <template v-if="card">
      <Card flat>
        <!-- Two lines, then "more". Worth reading once; it was six lines
             tall above every visit. -->
        <p class="headline" :class="{ clamped: !headlineOpen }"
           @click="headlineOpen = !headlineOpen">{{ card.headline }}</p>
        <button v-if="!headlineOpen" class="link"
                @click="headlineOpen = true">more</button>
        <p v-if="stamp" class="stamp">
          {{ stamp }}<template v-if="model"> · {{ model }}</template>
        </p>
      </Card>

      <!-- Collapsed by default. One card used to fill a screen — a
           wrapping title with a button beside it, a four-line rationale,
           a fat row and two rows of chips — so comparing four
           suggestions meant scrolling four screens of prose. Everything
           needed to CHOOSE is on the face; everything that explains the
           choice is one click away. -->
      <Card v-for="s in card.suggestions" :key="s.name" flat class="sug">
        <strong class="sug-name">{{ s.name }}</strong>

        <p class="meta">
          {{ s.slot }}
          <template v-if="s.est_prep_min">
            · <Clock :size="11" /> {{ s.est_prep_min }} min
          </template>
          <template v-if="s.est_fat_g">
            ·
            <!-- Coloured by the server's verdict, never a threshold
                 invented here. Grey when it cannot be judged: "unknown"
                 must not borrow the reassurance of "fine". -->
            <span :class="['fat-inline', s.fat_assessment?.verdict ?? 'unknown']">
              {{ Math.round(s.est_fat_g * 10) / 10 }} g fat
            </span>
          </template>
        </p>

        <p
          v-if="s.uses_from_pantry?.length || s.also_needs?.length"
          class="coverage"
          :class="{ all: !s.also_needs?.length }"
        >
          {{ !s.also_needs?.length
             ? "everything from your pantry"
             : `${s.uses_from_pantry?.length ?? 0} from your pantry · ${s.also_needs.length} to buy` }}
        </p>

        <template v-if="expanded[s.name]">
          <p class="why">{{ s.why }}</p>

          <FatAssessment
            v-if="s.fat_assessment"
            :assessment="s.fat_assessment"
            compact
            class="fat"
          />

          <div v-if="s.uses_from_pantry?.length" class="chips">
            <span class="chip-label"><ShoppingBasket :size="11" /> have</span>
            <span v-for="p in s.uses_from_pantry" :key="p" class="chip have">{{ p }}</span>
          </div>
          <div v-if="s.also_needs?.length" class="chips">
            <span class="chip-label">need</span>
            <span v-for="p in s.also_needs" :key="p" class="chip need">{{ p }}</span>
          </div>

          <p v-if="s.based_on_saved_recipe" class="based">
            Based on your saved recipe “{{ s.based_on_saved_recipe }}”.
          </p>
        </template>

        <!-- Both actions together, below the content, as peers. -->
        <div class="card-actions">
          <button
            class="ghost"
            :disabled="planned[s.name]"
            @click="addToPlan(s.name, s.slot)"
          >
            <CalendarPlus :size="13" />
            {{ planned[s.name] ? "Planned" : "Plan today" }}
          </button>
          <!-- Only when the model actually gave ingredients. A card from
               before the schema carried them would otherwise save a
               recipe with no ingredients and so no nutrition — an empty
               recipe wearing a real one's clothes. -->
          <button
            v-if="s.ingredients?.length"
            class="ghost"
            :disabled="savedRecipes[s.name] || savingRecipe === s.name"
            @click="saveAsRecipe(s)"
          >
            <BookOpen :size="13" />
            {{ savedRecipes[s.name] ? "Saved"
               : savingRecipe === s.name ? "Saving…" : "Save as recipe" }}
          </button>
          <button class="link why-toggle"
                  @click="expanded[s.name] = !expanded[s.name]">
            {{ expanded[s.name] ? "Less" : "Why this" }}
          </button>
        </div>
      </Card>

      <Card v-if="card.notes?.length" flat>
        <p v-for="n in card.notes" :key="n" class="note">
          <Info :size="13" /> {{ n }}
        </p>
      </Card>

      <!-- Shortened, not removed. That these numbers are guesses is not
           inferable from a confident-looking figure, and it is the
           category of text this app keeps. -->
      <p class="disclaimer">
        Fat and calorie figures are the model's estimates, not measured
        values.
      </p>
    </template>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 9px; padding: 0.38rem 0.7rem; font: inherit;
  font-size: 0.82rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled, button.ghost:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
.headline { margin: 0; font-size: 0.95rem; line-height: 1.5; }
.stamp { margin: 0.4rem 0 0; font-size: 0.72rem; color: var(--muted-2); }
.sug { margin-bottom: 0.5rem; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.7rem; }
.titles { min-width: 0; }
.meta {
  display: flex; align-items: center; gap: 0.25rem; flex-wrap: wrap;
  font-size: 0.74rem; color: var(--muted-2); margin-top: 0.15rem;
}
.card-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.sug-name { font-size: 1rem; line-height: 1.35; display: block; }
.headline.clamped {
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; cursor: pointer;
}
.coverage { font-size: 0.8rem; color: var(--muted); margin: 0.2rem 0 0; }
.coverage.all { color: #5dff3b; }
.fat-inline.high, .fat-inline.very_high { color: #ff5d7a; }
.fat-inline.approaching { color: #ffb52e; }
.fat-inline.ok { color: #5dff3b; }
.why-toggle { margin-left: auto; }
.why { margin: 0.55rem 0 0; font-size: 0.85rem; line-height: 1.5; color: var(--muted-2); }
.fat { margin-top: 0.6rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; margin-top: 0.55rem; }
.chip-label {
  display: inline-flex; align-items: center; gap: 0.2rem;
  font-size: 0.7rem; color: var(--muted-2); margin-right: 0.15rem;
}
.chip {
  font-size: 0.72rem; border-radius: 999px; padding: 0.1rem 0.45rem;
  border: 1px solid var(--line);
}
.chip.have { color: #22c55e; border-color: #22c55e44; }
.chip.need { color: #fbbf24; border-color: #fbbf2444; }
.based { margin: 0.5rem 0 0; font-size: 0.74rem; color: var(--muted-2); font-style: italic; }
.note {
  display: flex; align-items: flex-start; gap: 0.35rem;
  margin: 0 0 0.4rem; font-size: 0.82rem; color: var(--muted-2); line-height: 1.45;
}
.disclaimer {
  margin: 0.8rem 0 0; font-size: 0.74rem; color: var(--muted-2);
  line-height: 1.5; padding-top: 0.7rem; border-top: 1px solid var(--line);
}
</style>
