<script setup lang="ts">
/**
 * The shopping list: plan minus pantry.
 *
 * The subtraction happens server-side so this view and the phone cannot
 * disagree about what to buy. Nothing here recomputes a quantity.
 *
 * The list is deliberately noisy in one specific way. An item the pantry
 * holds in an unknown amount ("we have olive oil") stays on the list,
 * flagged, rather than being removed — "some, amount unknown" is not
 * evidence of "enough", and a list that quietly drops something sends
 * you home without it. Only items the pantry demonstrably covered are
 * removed, and the count of those is shown so the subtraction is
 * visible rather than mysterious.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  RefreshCw, Trash2, ExternalLink, HelpCircle, Copy, Check,
} from "lucide-vue-next";
import { meals, type ShoppingList } from "@/api/client";

const lists = ref<ShoppingList[]>([]);
const active = ref<ShoppingList | null>(null);
const loading = ref(true);
const generating = ref(false);
const error = ref<string | null>(null);
const copied = ref(false);
const days = ref(7);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    lists.value = await meals.listShoppingLists();
    active.value = lists.value[0] ?? null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function generate() {
  generating.value = true;
  error.value = null;
  try {
    const created = await meals.generateShoppingList({ days: days.value });
    await load();
    active.value = created;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not generate";
  } finally {
    generating.value = false;
  }
}

async function toggle(itemId: number, checked: boolean) {
  if (!active.value) return;
  const item = active.value.items.find((i) => i.id === itemId);
  if (!item) return;
  // Optimistic: ticking things off while shopping should feel instant.
  item.checked = checked;
  try {
    await meals.checkShoppingItem(active.value.id, itemId, checked);
  } catch (e) {
    item.checked = !checked;
    error.value = e instanceof Error ? e.message : "could not save";
  }
}

async function remove(id: number) {
  try {
    await meals.deleteShoppingList(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not delete";
  }
}

/** Plain text for a phone's notes app or a message. Uncertain items keep
 *  their flag in the text — dropping it there would lose the one caveat
 *  that matters while standing in a shop. */
const asText = computed(() => {
  if (!active.value) return "";
  return active.value.items
    .map((i) => {
      const amount = [i.amount, i.amount_text].filter(Boolean).join(" + ");
      const flag = i.pantry_uncertain ? "  (check pantry)" : "";
      return `- ${i.label}${amount ? ` — ${amount}` : ""}${flag}`;
    })
    .join("\n");
});

async function copyList() {
  try {
    await navigator.clipboard.writeText(asText.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1800);
  } catch {
    error.value = "Clipboard unavailable — select and copy the list manually.";
  }
}

const remaining = computed(
  () => active.value?.items.filter((i) => !i.checked).length ?? 0,
);

function rangeLabel(l: ShoppingList): string {
  if (!l.start_day) return "";
  const fmt = (s: string) =>
    new Date(`${s}T00:00:00`).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  return `${fmt(l.start_day)}${l.end_day ? ` – ${fmt(l.end_day)}` : ""}`;
}
</script>

<template>
  <div class="shopping">
    <PageHeader title="Shopping list">
      <div class="actions">
        <label class="days">
          <span>next</span>
          <input v-model.number="days" type="number" min="1" max="31" />
          <span>days</span>
        </label>
        <button class="primary" :disabled="generating" @click="generate">
          <RefreshCw :size="14" />
          {{ generating ? "Building…" : "Generate" }}
        </button>
      </div>
    </PageHeader>

    <p v-if="error" class="err">{{ error }}</p>
    <EmptyState v-if="loading" message="Loading…" />

    <EmptyState v-else-if="!active">
      No lists yet. Plan some meals, then generate one — it subtracts what
      the pantry already holds.
    </EmptyState>

    <template v-else>
      <Card flat>
        <div class="list-head">
          <div>
            <strong>{{ active.name ?? "Shopping list" }}</strong>
            <span class="sub">
              <!-- What a shopper needs, in the order they need it. "0
                   planned meals" led a list of four real items, because
                   those came from a PREP plan rather than from planned
                   meals — true, and at the top of the screen simply
                   confusing. -->
              {{ rangeLabel(active) }} · {{ active.items.length }}
              item{{ active.items.length === 1 ? "" : "s" }}
              <template v-if="active.items.length">
                · {{ active.items.filter((i) => i.checked).length }} ticked
              </template>
              <template v-if="active.covered_by_pantry">
                · {{ active.covered_by_pantry }} already in the pantry
              </template>
            </span>
          </div>
          <div class="head-actions">
            <button class="ghost" @click="copyList">
              <component :is="copied ? Check : Copy" :size="14" />
              {{ copied ? "Copied" : "Copy" }}
            </button>
            <button class="icon-btn" title="Delete list" @click="remove(active.id)">
              <Trash2 :size="14" />
            </button>
          </div>
        </div>

        <p v-if="!active.items.length" class="nothing">
          <template v-if="!active.planned_meals">
            Nothing was planned for this window, so there is nothing to buy.
          </template>
          <template v-else>
            Everything the plan needs is already in the pantry.
          </template>
        </p>

        <ul v-else class="items">
          <li v-for="i in active.items" :key="i.id" :class="{ done: i.checked }">
            <input
              type="checkbox"
              :checked="i.checked"
              @change="toggle(i.id, ($event.target as HTMLInputElement).checked)"
            />
            <span class="label">{{ i.label }}</span>
            <span class="amount">
              {{ [i.amount, i.amount_text].filter(Boolean).join(" + ") || "—" }}
            </span>
            <span
              v-if="i.pantry_uncertain"
              class="uncertain"
              title="The pantry has some of this but the amount is unknown, so it could not be subtracted."
            >
              <HelpCircle :size="12" /> check pantry
            </span>
            <a
              v-if="i.walmart_url"
              :href="i.walmart_url"
              target="_blank"
              rel="noopener noreferrer"
              class="wm"
              title="Search Walmart for this item"
            >
              <ExternalLink :size="12" />
            </a>
          </li>
        </ul>

        <p v-if="active.items.length" class="foot">
          {{ remaining }} of {{ active.items.length }} left
        </p>
      </Card>

      <Card v-if="lists.length > 1" flat title="Earlier lists">
        <ul class="earlier">
          <li v-for="l in lists.slice(1)" :key="l.id">
            <button class="link" @click="active = l">
              {{ rangeLabel(l) || "list" }} — {{ l.items.length }} items
            </button>
            <button class="icon-btn" title="Delete" @click="remove(l.id)">
              <Trash2 :size="13" />
            </button>
          </li>
        </ul>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.actions { display: flex; align-items: center; gap: 0.5rem; }
.days { display: flex; align-items: center; gap: 0.3rem; font-size: 0.78rem; color: var(--muted-2); }
.days input {
  width: 54px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.8rem; padding: 0.25rem 0.35rem;
}
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 8px; padding: 0.35rem 0.6rem; font: inherit;
  font-size: 0.8rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
.list-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.7rem; }
.sub { display: block; font-size: 0.74rem; color: var(--muted-2); margin-top: 0.15rem; }
.head-actions { display: flex; align-items: center; gap: 0.4rem; flex: none; }
.icon-btn { border: 0; background: transparent; color: var(--muted-2); cursor: pointer; display: flex; padding: 0.2rem; }
.icon-btn:hover { color: #f87171; }
.nothing { margin: 0.7rem 0 0; font-size: 0.85rem; color: var(--muted-2); }
.items { list-style: none; margin: 0.8rem 0 0; padding: 0; }
.items li {
  display: flex; align-items: center; gap: 0.55rem;
  padding: 0.35rem 0; border-bottom: 1px solid var(--line); font-size: 0.86rem;
}
.items li.done .label, .items li.done .amount { opacity: 0.45; text-decoration: line-through; }
.items input[type="checkbox"] { flex: none; }
.label { flex: 1; min-width: 0; }
.amount { font-size: 0.78rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.uncertain {
  display: inline-flex; align-items: center; gap: 0.2rem;
  font-size: 0.7rem; color: #fbbf24; flex: none;
}
.wm { color: var(--muted-2); display: flex; flex: none; }
.wm:hover { color: var(--accent, #38bdf8); }
.foot { margin: 0.7rem 0 0; font-size: 0.78rem; color: var(--muted-2); }
.earlier { list-style: none; margin: 0; padding: 0; }
.earlier li { display: flex; align-items: center; justify-content: space-between; padding: 0.25rem 0; }
.link { background: none; border: 0; color: var(--accent, #38bdf8); cursor: pointer; font: inherit; font-size: 0.82rem; padding: 0; }
</style>
