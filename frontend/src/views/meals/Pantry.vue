<script setup lang="ts">
/**
 * What is in the house.
 *
 * Quantities are optional on purpose. "We have olive oil" is a useful
 * fact without knowing how much, and demanding a number is the friction
 * that stops a pantry being kept up to date at all.
 *
 * `days_to_expiry` comes from the server. Deriving it here would compute
 * it against the browser's clock — which is right for this user but
 * would disagree with the phone and with every other date in the app,
 * all of which resolve in the configured timezone.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import { Plus, Trash2, AlertTriangle } from "lucide-vue-next";
import { meals, type Food, type PantryItem } from "@/api/client";

const items = ref<PantryItem[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

const adding = ref(false);
const draftFood = ref<Food | null>(null);
const draftLabel = ref("");
const draftQty = ref("");
const draftUnit = ref("");
const draftExpires = ref("");
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    items.value = await meals.listPantry();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const expiring = computed(() =>
  items.value.filter((i) => i.days_to_expiry != null && i.days_to_expiry <= 3),
);

function pick(f: Food) {
  draftFood.value = f;
  draftLabel.value = "";
}

function resetDraft() {
  draftFood.value = null;
  draftLabel.value = "";
  draftQty.value = "";
  draftUnit.value = "";
  draftExpires.value = "";
}

async function add() {
  if (!draftFood.value && !draftLabel.value.trim()) return;
  saving.value = true;
  error.value = null;
  try {
    await meals.addPantry({
      food_id: draftFood.value?.id ?? null,
      label: draftFood.value ? null : draftLabel.value.trim(),
      quantity: draftQty.value ? Number(draftQty.value) : null,
      unit: draftUnit.value.trim() || null,
      expires_on: draftExpires.value || null,
    });
    resetDraft();
    adding.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not add";
  } finally {
    saving.value = false;
  }
}

async function remove(item: PantryItem) {
  try {
    await meals.deletePantry(item.id);
    items.value = items.value.filter((i) => i.id !== item.id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not remove";
  }
}

function title(i: PantryItem): string {
  return i.food_name ?? i.label ?? "Untitled";
}

function amount(i: PantryItem): string | null {
  if (i.quantity == null) return i.unit || null;
  return `${i.quantity}${i.unit ? ` ${i.unit}` : ""}`;
}

/** Expiry phrased the way a person would say it. Absent stays absent —
 *  an item with no date is not an item expiring today. */
function expiryLabel(i: PantryItem): string | null {
  const d = i.days_to_expiry;
  if (d == null) return null;
  if (d < 0) return `expired ${Math.abs(d)}d ago`;
  if (d === 0) return "expires today";
  if (d === 1) return "expires tomorrow";
  return `${d}d left`;
}

function expiryClass(i: PantryItem): string {
  const d = i.days_to_expiry;
  if (d == null) return "";
  if (d < 0) return "past";
  if (d <= 3) return "soon";
  return "";
}
</script>

<template>
  <div class="pantry">
    <PageHeader title="Pantry">
      <button class="primary" @click="adding = !adding">
        <Plus :size="14" /> Add item
      </button>
    </PageHeader>

    <Card v-if="adding" flat title="Add to pantry">
      <FoodPicker
        v-if="!draftFood"
        placeholder="Search the food catalog…"
        @pick="pick"
      />
      <div v-else class="chosen">
        <span>{{ draftFood.name }}</span>
        <button class="link" @click="draftFood = null">change</button>
      </div>

      <p v-if="!draftFood" class="or">
        …or just name it, if it is not in the catalog:
      </p>
      <input
        v-if="!draftFood"
        v-model="draftLabel"
        class="text"
        type="text"
        placeholder="e.g. leftover chilli"
      />

      <div class="fields">
        <label>
          <span>Quantity</span>
          <input v-model="draftQty" type="number" step="any" min="0" placeholder="optional" />
        </label>
        <label>
          <span>Unit</span>
          <input v-model="draftUnit" type="text" placeholder="g / cup / can" />
        </label>
        <label>
          <span>Use by</span>
          <input v-model="draftExpires" type="date" />
        </label>
      </div>

      <div class="actions">
        <button
          class="primary"
          :disabled="saving || (!draftFood && !draftLabel.trim())"
          @click="add"
        >
          {{ saving ? "Adding…" : "Add" }}
        </button>
        <button class="ghost" @click="adding = false; resetDraft()">Cancel</button>
      </div>
    </Card>

    <p v-if="error" class="err">{{ error }}</p>

    <Card v-if="expiring.length" flat class="alert">
      <div class="alert-head">
        <AlertTriangle :size="15" />
        <strong>{{ expiring.length }} item{{ expiring.length === 1 ? "" : "s" }} to use up</strong>
      </div>
      <p class="alert-body">
        {{ expiring.map(title).join(", ") }}
      </p>
    </Card>

    <EmptyState v-if="loading" message="Loading…" />
    <EmptyState v-else-if="!items.length">
      Nothing in the pantry yet. Add what you have and recipes can be
      matched against it.
    </EmptyState>

    <ul v-else class="list">
      <li v-for="i in items" :key="i.id" :class="expiryClass(i)">
        <div class="main">
          <span class="name">{{ title(i) }}</span>
          <span v-if="amount(i)" class="qty">{{ amount(i) }}</span>
        </div>
        <div class="right">
          <span v-if="expiryLabel(i)" class="exp" :class="expiryClass(i)">
            {{ expiryLabel(i) }}
          </span>
          <button class="icon-btn" title="Remove" @click="remove(i)">
            <Trash2 :size="14" />
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
button.primary, button.ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border-radius: 9px; padding: 0.4rem 0.7rem; font: inherit;
  font-size: 0.85rem; cursor: pointer; border: 1px solid var(--line);
}
button.primary { background: var(--accent, #38bdf8); border-color: transparent; color: #04121c; }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.ghost { background: transparent; color: var(--muted-2); }
.link {
  background: none; border: 0; color: var(--accent, #38bdf8);
  cursor: pointer; font: inherit; font-size: 0.8rem; padding: 0;
}
.chosen {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.6rem; font-size: 0.88rem;
  border: 1px solid var(--line); border-radius: 9px; padding: 0.45rem 0.6rem;
}
.or { color: var(--muted-2); font-size: 0.8rem; margin: 0.6rem 0 0.35rem; }
.text, .fields input {
  width: 100%; border: 1px solid var(--line); border-radius: 9px;
  background: var(--bg-1); color: var(--fg); font: inherit;
  font-size: 0.85rem; padding: 0.4rem 0.55rem; outline: none;
}
.fields {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 0.6rem; margin-top: 0.7rem;
}
.fields label { display: flex; flex-direction: column; gap: 0.25rem; }
.fields span { font-size: 0.75rem; color: var(--muted-2); }
.actions { display: flex; gap: 0.5rem; margin-top: 0.8rem; }
.alert-head { display: flex; align-items: center; gap: 0.4rem; color: #fbbf24; }
.alert-body { margin: 0.35rem 0 0; font-size: 0.85rem; color: var(--muted-2); }
.list { list-style: none; margin: 0; padding: 0; }
.list li {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.8rem; padding: 0.6rem 0.7rem;
  border: 1px solid var(--line); border-radius: 10px; margin-bottom: 0.4rem;
  background: var(--bg-1);
}
.main { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.name { font-size: 0.9rem; }
.qty { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.right { display: flex; align-items: center; gap: 0.6rem; flex: none; }
.exp { font-size: 0.75rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.exp.soon { color: #fbbf24; }
.exp.past { color: #f87171; }
.icon-btn {
  border: 0; background: transparent; color: var(--muted-2);
  cursor: pointer; display: flex; padding: 0.2rem;
}
.icon-btn:hover { color: #f87171; }
</style>
