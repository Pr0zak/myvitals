<script setup lang="ts">
/**
 * Type-ahead search over the food catalog.
 *
 * `ingredientsOnly` decides which half of the catalog is offered. The
 * same table holds whole ingredients and prepared foods — chicken breast
 * and a Big Mac — because a recipe needs the first and a food log needs
 * the second. A recipe picker showing forty restaurant entrees is
 * unusable, and a log that cannot find lunch is pointless, so the caller
 * says which lens it wants.
 *
 * Ranking is the server's job. Do not re-sort results here: the backend
 * already handles USDA's inverted naming ("Oil, olive, salad or
 * cooking") and demotes processed forms, and a second sort in Vue would
 * silently disagree with the phone.
 */
import { ref, watch } from "vue";
import { Search, X } from "lucide-vue-next";
import { meals, type Food } from "@/api/client";

const props = withDefaults(
  defineProps<{
    ingredientsOnly?: boolean;
    placeholder?: string;
    autofocus?: boolean;
  }>(),
  { ingredientsOnly: false, placeholder: "Search foods…", autofocus: false },
);

const emit = defineEmits<{ (e: "pick", food: Food): void }>();

const term = ref("");
const results = ref<Food[]>([]);
const busy = ref(false);
const error = ref<string | null>(null);

let seq = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

async function run(q: string) {
  // Every request carries a sequence number and only the newest one is
  // allowed to write results. Without it a slow early query can land
  // after a fast later one and replace the right answers with stale ones.
  const mine = ++seq;
  busy.value = true;
  error.value = null;
  try {
    const rows = await meals.searchFoods(q, {
      ingredientsOnly: props.ingredientsOnly,
      limit: 20,
    });
    if (mine === seq) results.value = rows;
  } catch (e) {
    if (mine === seq) error.value = e instanceof Error ? e.message : "search failed";
  } finally {
    if (mine === seq) busy.value = false;
  }
}

watch(term, (q) => {
  clearTimeout(timer);
  const trimmed = q.trim();
  if (trimmed.length < 2) {
    results.value = [];
    return;
  }
  timer = setTimeout(() => run(trimmed), 220);
});

function choose(f: Food) {
  emit("pick", f);
  term.value = "";
  results.value = [];
}

function clear() {
  term.value = "";
  results.value = [];
}

/** Rounded kcal for the result row. Null stays "—": a food with unknown
 *  energy is not a food with zero energy. */
function kcalLabel(f: Food): string {
  return f.kcal == null ? "—" : `${Math.round(f.kcal)} kcal`;
}
</script>

<template>
  <div class="picker">
    <div class="input-row">
      <Search :size="15" class="icon" />
      <input
        v-model="term"
        type="search"
        :placeholder="placeholder"
        :autofocus="autofocus"
        @keydown.esc="clear"
      />
      <button v-if="term" class="clear" title="Clear" @click="clear">
        <X :size="14" />
      </button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="busy && !results.length" class="hint">Searching…</p>
    <p v-else-if="term.trim().length === 1" class="hint">Keep typing…</p>
    <p v-else-if="term.trim().length >= 2 && !busy && !results.length" class="hint">
      Nothing matched “{{ term.trim() }}”.
    </p>

    <ul v-if="results.length" class="results">
      <li v-for="f in results" :key="f.id">
        <button class="row" @click="choose(f)">
          <span class="name">
            {{ f.name }}
            <span v-if="f.source !== 'usda'" class="badge">yours</span>
          </span>
          <span class="macros">
            <span class="kcal">{{ kcalLabel(f) }}</span>
            <span v-if="f.fat_g != null" class="fat">{{ f.fat_g.toFixed(1) }}g fat</span>
            <span class="per">per 100 g</span>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.picker { display: flex; flex-direction: column; gap: 0.5rem; }
.input-row {
  display: flex; align-items: center; gap: 0.45rem;
  border: 1px solid var(--line); border-radius: 10px;
  padding: 0.4rem 0.6rem; background: var(--bg-1);
}
.input-row .icon { color: var(--muted-2); flex: none; }
.input-row input {
  flex: 1; border: 0; background: transparent; color: var(--fg);
  font: inherit; outline: none; min-width: 0;
}
.clear {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0.1rem;
}
.clear:hover { color: var(--fg); }
.hint, .err { color: var(--muted-2); font-size: 0.82rem; margin: 0; }
.err { color: #f87171; }
.results {
  list-style: none; margin: 0; padding: 0;
  max-height: 320px; overflow-y: auto;
  border: 1px solid var(--line); border-radius: 10px;
}
.results li + li { border-top: 1px solid var(--line); }
.row {
  width: 100%; text-align: left; background: transparent; border: 0;
  color: var(--fg); font: inherit; cursor: pointer;
  padding: 0.5rem 0.65rem;
  display: flex; flex-direction: column; gap: 0.15rem;
}
.row:hover, .row:focus-visible { background: var(--bg-2); }
.name { font-size: 0.88rem; line-height: 1.3; }
.badge {
  font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.04em;
  border: 1px solid var(--line); border-radius: 5px;
  padding: 0 0.28rem; margin-left: 0.35rem; color: var(--muted-2);
}
.macros {
  display: flex; gap: 0.6rem; font-size: 0.75rem; color: var(--muted-2);
  font-variant-numeric: tabular-nums;
}
.kcal { color: var(--fg); }
</style>
