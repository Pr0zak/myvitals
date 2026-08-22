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
import { Sparkles, Clock, ShoppingBasket, Info, CalendarPlus } from "lucide-vue-next";
import { api, meals, type MealSuggestionCard } from "@/api/client";
import { toLocalISO } from "@/dates";

const card = ref<MealSuggestionCard | null>(null);
const generatedAt = ref<string | null>(null);
const model = ref<string | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const planned = ref<Record<string, boolean>>({});

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
    <PageHeader title="Meal ideas">
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
        <p class="headline">{{ card.headline }}</p>
        <p v-if="stamp" class="stamp">
          {{ stamp }}<template v-if="model"> · {{ model }}</template>
        </p>
      </Card>

      <Card v-for="s in card.suggestions" :key="s.name" flat class="sug">
        <div class="head">
          <div class="titles">
            <strong>{{ s.name }}</strong>
            <span class="meta">
              {{ s.slot }}
              <template v-if="s.est_prep_min">
                · <Clock :size="11" /> {{ s.est_prep_min }} min
              </template>
              <template v-if="s.est_kcal">
                · {{ Math.round(s.est_kcal) }} kcal
              </template>
            </span>
          </div>
          <button
            class="ghost"
            :disabled="planned[s.name]"
            @click="addToPlan(s.name, s.slot)"
          >
            <CalendarPlus :size="13" />
            {{ planned[s.name] ? "Planned" : "Plan today" }}
          </button>
        </div>

        <p class="why">{{ s.why }}</p>

        <FatAssessment
          v-if="s.fat_assessment"
          :assessment="s.fat_assessment"
          compact
          class="fat"
        />

        <div v-if="s.uses_from_pantry?.length" class="chips">
          <span class="chip-label"><ShoppingBasket :size="11" /> from pantry</span>
          <span v-for="p in s.uses_from_pantry" :key="p" class="chip have">{{ p }}</span>
        </div>
        <div v-if="s.also_needs?.length" class="chips">
          <span class="chip-label">also needs</span>
          <span v-for="p in s.also_needs" :key="p" class="chip need">{{ p }}</span>
        </div>

        <p v-if="s.based_on_saved_recipe" class="based">
          Based on your saved recipe “{{ s.based_on_saved_recipe }}”.
        </p>
      </Card>

      <Card v-if="card.notes?.length" flat>
        <p v-for="n in card.notes" :key="n" class="note">
          <Info :size="13" /> {{ n }}
        </p>
      </Card>

      <p class="disclaimer">
        Fat and calorie figures on this page are the model's estimates, not
        measured values. The high / in-range verdict beside each one is
        computed from your own target, but the number it judges is a guess —
        check the label if it matters.
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
