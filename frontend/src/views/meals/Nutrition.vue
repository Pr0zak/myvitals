<script setup lang="ts">
/**
 * Diet settings and the standalone fat check.
 *
 * Two jobs, both of which work with zero logging — which is the design
 * floor for this feature. Setting a per-meal fat target needs nothing;
 * checking a number off a package needs nothing.
 *
 * The app never supplies a default fat target. Tolerance after gall
 * bladder removal varies widely between people and commonly improves
 * over months, so a figure this app invented could be wrong in either
 * direction. This screen asks for the number and asks where it came
 * from, and the answer to the second question is rendered next to the
 * first everywhere it is used.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import FatAssessment from "@/components/FatAssessment.vue";
import EmptyState from "@/components/EmptyState.vue";
import { Info } from "lucide-vue-next";
import { meals, type DietProfile, type FatAssessment as FA } from "@/api/client";

const profile = ref<DietProfile | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const saving = ref(false);
const saved = ref(false);

const targetG = ref("");
const targetSource = ref("");
const trackVitamins = ref(true);
const kcalTarget = ref("");

const checkFat = ref("");
const checkResult = ref<FA | null>(null);
const checking = ref(false);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const p = await meals.getDietProfile();
    profile.value = p;
    targetG.value = p.fat_per_meal_target_g?.toString() ?? "";
    targetSource.value = p.fat_target_source ?? "";
    trackVitamins.value = p.track_fat_soluble;
    kcalTarget.value = p.daily_kcal_target?.toString() ?? "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function save() {
  saving.value = true;
  error.value = null;
  saved.value = false;
  try {
    // Empty string clears the target rather than leaving it — sending
    // null explicitly is how the user removes a limit they no longer
    // want the app judging against.
    profile.value = await meals.putDietProfile({
      fat_per_meal_target_g: targetG.value === "" ? null : Number(targetG.value),
      fat_target_source: targetSource.value.trim() || null,
      track_fat_soluble: trackVitamins.value,
      daily_kcal_target: kcalTarget.value === "" ? null : Number(kcalTarget.value),
    });
    saved.value = true;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "save failed";
  } finally {
    saving.value = false;
  }
}

async function runCheck() {
  const v = Number(checkFat.value);
  if (!checkFat.value || Number.isNaN(v) || v < 0) return;
  checking.value = true;
  try {
    checkResult.value = await meals.assessFat(v);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "check failed";
  } finally {
    checking.value = false;
  }
}

/** What the app will judge against right now, said plainly, so the
 *  behaviour is never a surprise when a verdict appears on a recipe. */
const basisNow = computed(() => {
  const p = profile.value;
  if (!p) return null;
  if (p.fat_per_meal_target_g != null) {
    return `Meals are judged against your ${p.fat_per_meal_target_g} g target.`;
  }
  if (p.comparison_meals >= p.comparison_meals_needed) {
    return `No target set, so meals are judged against the median of your ${p.comparison_meals} saved recipes.`;
  }
  return `No target set, and only ${p.comparison_meals} of the ${p.comparison_meals_needed} saved recipes needed to compare against. Meals will show "not enough to judge" until you set a target or add more recipes.`;
});
</script>

<template>
  <div class="nutrition">
    <PageHeader title="Nutrition" />

    <p v-if="error" class="err">{{ error }}</p>
    <EmptyState v-if="loading" message="Loading…" />

    <template v-else>
      <Card flat title="Fat per meal">
        <p class="lead">
          Without a gall bladder, bile drips continuously instead of
          arriving as a bolus, so what matters is how much fat turns up
          <strong>in one sitting</strong> — not the daily total. A day
          totalling 70 g spread across four meals and a day where 60 g of
          it lands at dinner are the same number and a completely
          different experience.
        </p>
        <p class="lead">
          This app will <strong>not</strong> guess a limit for you.
          Tolerance varies a lot between people and usually improves over
          months, so any number here should be one you were actually
          given.
        </p>

        <div class="fields">
          <label>
            <span>Target grams per meal</span>
            <input
              v-model="targetG"
              type="number"
              step="any"
              min="0"
              placeholder="leave blank if you don't have one"
            />
          </label>
          <label class="wide">
            <span>Where did this number come from?</span>
            <input
              v-model="targetSource"
              type="text"
              maxlength="200"
              placeholder="e.g. dietitian, Mar 2026"
            />
          </label>
          <label>
            <span>Daily calorie target</span>
            <input v-model="kcalTarget" type="number" min="0" placeholder="optional" />
          </label>
        </div>

        <label class="toggle">
          <input v-model="trackVitamins" type="checkbox" />
          <span>
            Show fat-soluble vitamins (A, D, E, K) on meals — absorbing
            these depends on absorbing fat
          </span>
        </label>

        <div class="actions">
          <button class="primary" :disabled="saving" @click="save">
            {{ saving ? "Saving…" : "Save" }}
          </button>
          <span v-if="saved" class="ok-note">Saved</span>
        </div>

        <p v-if="basisNow" class="basis">
          <Info :size="13" /> {{ basisNow }}
        </p>
      </Card>

      <Card flat title="Check a meal">
        <p class="lead">
          Read the fat off a package or a menu and see how it compares —
          no recipe or logging needed.
        </p>
        <div class="check-row">
          <input
            v-model="checkFat"
            type="number"
            step="any"
            min="0"
            placeholder="grams of fat"
            @keydown.enter="runCheck"
          />
          <button class="primary" :disabled="checking || !checkFat" @click="runCheck">
            {{ checking ? "Checking…" : "Check" }}
          </button>
        </div>
        <FatAssessment v-if="checkResult" :assessment="checkResult" class="result" />
      </Card>
    </template>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.lead { font-size: 0.85rem; color: var(--muted-2); line-height: 1.55; margin: 0 0 0.7rem; }
.lead strong { color: var(--fg); }
.fields {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.6rem; margin-bottom: 0.7rem;
}
.fields .wide { grid-column: 1 / -1; }
.fields label { display: flex; flex-direction: column; gap: 0.25rem; }
.fields span { font-size: 0.75rem; color: var(--muted-2); }
input {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
.toggle {
  display: flex; align-items: flex-start; gap: 0.45rem;
  font-size: 0.8rem; color: var(--muted-2); line-height: 1.45;
}
.toggle input { width: auto; margin-top: 0.15rem; flex: none; }
.actions { display: flex; align-items: center; gap: 0.7rem; margin-top: 0.9rem; }
button.primary {
  border-radius: 9px; padding: 0.4rem 0.8rem; font: inherit; font-size: 0.85rem;
  cursor: pointer; border: 1px solid transparent;
  background: var(--accent, #38bdf8); color: #04121c;
}
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.ok-note { font-size: 0.8rem; color: #22c55e; }
.basis {
  display: flex; align-items: flex-start; gap: 0.35rem;
  margin: 0.9rem 0 0; padding-top: 0.7rem; border-top: 1px solid var(--line);
  font-size: 0.78rem; color: var(--muted-2); line-height: 1.45;
}
.check-row { display: flex; gap: 0.5rem; align-items: center; }
.check-row input { max-width: 180px; }
.result { margin-top: 0.8rem; }
</style>
