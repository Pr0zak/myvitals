<script setup lang="ts">
/**
 * What can I cook right now?
 *
 * The deterministic counterpart to the AI suggestion card: free, offline,
 * and answering a question the AI cannot — which of *your own saved
 * recipes* can you make tonight from what is actually in the house.
 *
 * Two things this screen is careful about:
 *
 * Staples are assumed, and it says so. Nearly every savoury recipe lists
 * salt and oil, so a strict test answers "no" to everything — but a user
 * who cannot see the assumption cannot tell why a recipe claims to be
 * cookable.
 *
 * A recipe with an ingredient the app could not identify is shown as
 * "probably", never as cookable, and sorted below the verified ones.
 * Putting the least certain recipe at the top is exactly where it would
 * do the most damage.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  ChefHat, ShoppingBasket, HelpCircle, Sparkles, RefreshCw,
} from "lucide-vue-next";
import { meals, type CanMake } from "@/api/client";

const data = ref<CanMake | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const showStaples = ref(false);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    data.value = await meals.canMake();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const cookable = computed(() => data.value?.recipes.filter((r) => r.cookable) ?? []);
const nearly = computed(
  () => data.value?.recipes.filter((r) => !r.cookable && r.missing.length === 1) ?? [],
);
const uncertain = computed(() => data.value?.recipes.filter((r) => r.uncertain) ?? []);
const rest = computed(
  () => data.value?.recipes.filter(
    (r) => !r.cookable && !r.uncertain && r.missing.length > 1,
  ) ?? [],
);
</script>

<template>
  <div class="canmake">
    <PageHeader title="Cook from pantry">
      <button class="ghost" :disabled="loading" @click="load">
        <RefreshCw :size="14" /> Refresh
      </button>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>
    <EmptyState v-if="loading && !data" message="Checking the pantry…" />

    <template v-else-if="data">
      <!-- An empty state that names the fix should also offer it. -->
      <EmptyState v-if="!data.summary.total_recipes">
        Nothing to check yet. Save a recipe and this screen tells you which
        ones your pantry already covers.
        <br />
        <RouterLink to="/meals/recipes">Go to Recipes</RouterLink>
      </EmptyState>

      <template v-else>
        <Card flat class="head">
          <div class="counts">
            <span class="big">{{ data.summary.cookable_now }}</span>
            <span>cookable now</span>
            <span class="sep">·</span>
            <span class="big">{{ data.summary.missing_one }}</span>
            <span>one item away</span>
          </div>
          <p class="sub">
            From {{ data.pantry_concepts }} thing{{ data.pantry_concepts === 1 ? "" : "s" }}
            in your pantry, across {{ data.summary.total_recipes }} recipes.
            <button class="link" @click="showStaples = !showStaples">
              {{ showStaples ? "hide" : "what's assumed?" }}
            </button>
          </p>
          <p v-if="showStaples" class="staples">
            These are assumed to be in the house and never block a match:
            {{ data.staples_assumed.join(", ") }}. Butter is deliberately
            not among them — half a stick is 46&nbsp;g of fat, which would
            silently vanish from a per-meal total.
          </p>
        </Card>

        <Card v-if="data.unlock.length" flat class="unlock">
          <div class="unlock-head">
            <ShoppingBasket :size="15" />
            <strong>Buy one thing</strong>
          </div>
          <ul>
            <li v-for="u in data.unlock" :key="u.item">
              <span class="item">{{ u.item }}</span>
              <span class="n">unlocks {{ u.unlocks }}</span>
              <span class="which">{{ u.recipes.join(", ") }}</span>
            </li>
          </ul>
        </Card>

        <template v-if="cookable.length">
          <h3><ChefHat :size="15" /> Cook now</h3>
          <Card v-for="r in cookable" :key="r.recipe_id" flat class="row ok">
            <div class="row-head">
              <strong>{{ r.name }}</strong>
              <span class="serves">{{ r.servings }} serving{{ r.servings === 1 ? "" : "s" }}</span>
            </div>
            <p v-if="r.from_staples.length" class="assumed">
              assuming you have {{ r.from_staples.join(", ") }}
            </p>
          </Card>
        </template>

        <template v-if="nearly.length">
          <h3>One item away</h3>
          <Card v-for="r in nearly" :key="r.recipe_id" flat class="row near">
            <div class="row-head">
              <strong>{{ r.name }}</strong>
              <span class="need">needs {{ r.missing[0] }}</span>
            </div>
          </Card>
        </template>

        <template v-if="uncertain.length">
          <h3><HelpCircle :size="15" /> Probably — one ingredient unrecognised</h3>
          <Card v-for="r in uncertain" :key="r.recipe_id" flat class="row maybe">
            <div class="row-head">
              <strong>{{ r.name }}</strong>
            </div>
            <p class="assumed">
              couldn't identify: {{ r.unknown.join(", ") }} — edit the recipe
              to pick a catalog food and this becomes a definite yes
            </p>
          </Card>
        </template>

        <template v-if="rest.length">
          <h3>Further off</h3>
          <Card v-for="r in rest" :key="r.recipe_id" flat class="row far">
            <div class="row-head">
              <strong>{{ r.name }}</strong>
              <span class="cov">{{ Math.round(r.coverage * 100) }}%</span>
            </div>
            <p class="assumed">needs {{ r.missing.join(", ") }}</p>
          </Card>
        </template>

        <p class="footer">
          <Sparkles :size="12" />
          This page costs nothing to run. For ideas beyond your saved
          recipes, see <RouterLink to="/meals/ideas">Meal ideas</RouterLink>.
        </p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
button.ghost {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 8px; padding: 0.3rem 0.55rem; font: inherit; font-size: 0.8rem;
  cursor: pointer;
}
.link { background: none; border: 0; color: var(--accent, #38bdf8); cursor: pointer; font: inherit; font-size: 0.78rem; padding: 0; }
.counts { display: flex; align-items: baseline; gap: 0.4rem; flex-wrap: wrap; font-size: 0.85rem; color: var(--muted-2); }
.counts .big { font-size: 1.5rem; font-weight: 600; color: var(--fg); font-variant-numeric: tabular-nums; }
.counts .sep { margin: 0 0.35rem; }
.sub { margin: 0.5rem 0 0; font-size: 0.78rem; color: var(--muted-2); }
.staples { margin: 0.5rem 0 0; font-size: 0.76rem; color: var(--muted-2); line-height: 1.5; }
.unlock-head { display: flex; align-items: center; gap: 0.4rem; color: #fbbf24; margin-bottom: 0.5rem; }
.unlock ul { list-style: none; margin: 0; padding: 0; }
.unlock li { display: flex; align-items: baseline; gap: 0.5rem; padding: 0.25rem 0; font-size: 0.84rem; flex-wrap: wrap; }
.unlock .item { font-weight: 600; }
.unlock .n { color: #fbbf24; font-size: 0.76rem; }
.unlock .which { color: var(--muted-2); font-size: 0.74rem; flex: 1; min-width: 0; }
h3 {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.8rem; color: var(--muted-2); font-weight: 600;
  margin: 1.1rem 0 0.4rem; text-transform: uppercase; letter-spacing: 0.04em;
}
.row { margin-bottom: 0.4rem; border-left: 3px solid var(--line); }
.row.ok { border-left-color: #22c55e; }
.row.near { border-left-color: #fbbf24; }
.row.maybe { border-left-color: var(--muted-2); }
.row.far { border-left-color: var(--line); }
.row-head { display: flex; align-items: baseline; gap: 0.6rem; }
.row-head strong { font-size: 0.9rem; flex: 1; min-width: 0; }
.serves, .cov { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.need { font-size: 0.78rem; color: #fbbf24; }
.assumed { margin: 0.25rem 0 0; font-size: 0.75rem; color: var(--muted-2); line-height: 1.45; }
.footer {
  display: flex; align-items: center; gap: 0.3rem;
  margin-top: 1.2rem; padding-top: 0.7rem; border-top: 1px solid var(--line);
  font-size: 0.76rem; color: var(--muted-2);
}
</style>
