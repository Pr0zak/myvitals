<script setup lang="ts">
/**
 * Direction A — Meals is Today, and everything else sits behind one door.
 *
 * The phone twin is `ui/meals/TodayTab.kt`. This replaced a ten-item
 * flat list in which the one task done twice a day had the same weight
 * as nine that are weekly or occasional. Everything on this screen is
 * fetched, not derived here: the totals, the per-slot grouping and the
 * per-meal fat verdict come from `/meals/log`, and the energy target
 * from `/meals/prep/targets`.
 */
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import QuantityPicker from "@/components/QuantityPicker.vue";
import FatAssessment from "@/components/FatAssessment.vue";
import { Plus, Trash2, ChevronRight } from "lucide-vue-next";
import {
  meals, type Food, type LogDay, type PrepTargets, type RecentEntry, type Recipe,
} from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import { toLocalISO } from "@/dates";

const SLOTS = ["breakfast", "lunch", "dinner", "snack"] as const;

const today = toLocalISO(new Date());
const day = ref<LogDay | null>(null);
const targets = ref<PrepTargets | null>(null);
const recents = ref<RecentEntry[]>([]);
const recipes = ref<Recipe[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const addingFor = ref<string | null>(null);

const draftFood = ref<Food | null>(null);
const draftQty = ref("");
const draftUnit = ref("");
const draftLabel = ref("");
const draftKcal = ref("");
const draftFat = ref("");

async function load() {
  error.value = null;
  try {
    const [d, t, r, rc] = await Promise.all([
      meals.getLog(today, 1),
      meals.prepTargets().catch(() => null),
      meals.recentLogEntries(12).catch(() => [] as RecentEntry[]),
      recipes.value.length ? Promise.resolve(recipes.value) : meals.listRecipes(),
    ]);
    day.value = d[0] ?? null;
    targets.value = t;
    recents.value = r;
    recipes.value = rc;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useVisibilityRefresh(load);

const kcal = computed(() => day.value?.totals?.kcal ?? null);
const fat = computed(() => day.value?.totals?.fat_g ?? null);
const targetKcal = computed(() => (targets.value?.ok ? targets.value.target_kcal ?? null : null));
/** Capped at 100% so an over-target day fills the bar rather than overflowing it. */
const pct = computed(() => {
  if (kcal.value == null || !targetKcal.value) return null;
  return Math.min(100, Math.round((kcal.value / targetKcal.value) * 100));
});

function mealFor(slot: string) {
  return day.value?.meals?.find((m) => m.slot === slot) ?? null;
}

async function logRecent(r: RecentEntry) {
  saving.value = true;
  try {
    await meals.addLogEntry({
      day: today, slot: r.usual_slot,
      food_id: r.food_id, recipe_id: r.recipe_id,
      label: r.food_id || r.recipe_id ? null : r.label,
      quantity: r.quantity, unit: r.unit, servings: r.servings,
      manual_kcal: r.manual_kcal, manual_fat_g: r.manual_fat_g,
    });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not log";
  } finally { saving.value = false; }
}

async function repeatYesterday() {
  const d = new Date(`${today}T00:00:00`);
  d.setDate(d.getDate() - 1);
  saving.value = true;
  try {
    await meals.repeatLogDay(toLocalISO(d), today);
    await load();
  } catch {
    error.value = "nothing logged yesterday, so there was nothing to copy";
  } finally { saving.value = false; }
}

function resetDraft() {
  draftFood.value = null; draftQty.value = ""; draftUnit.value = "";
  draftLabel.value = ""; draftKcal.value = ""; draftFat.value = "";
}

async function add(slot: string) {
  if (!draftFood.value && !draftLabel.value.trim()) return;
  saving.value = true;
  try {
    await meals.addLogEntry({
      day: today, slot,
      food_id: draftFood.value?.id ?? null,
      recipe_id: null,
      label: draftFood.value ? null : draftLabel.value.trim(),
      quantity: draftQty.value ? Number(draftQty.value) : null,
      unit: draftUnit.value.trim() || null,
      servings: null,
      // Blank stays null — a meal whose calories you don't know is not a
      // meal with zero calories.
      manual_kcal: draftKcal.value ? Number(draftKcal.value) : null,
      manual_fat_g: draftFat.value ? Number(draftFat.value) : null,
    });
    addingFor.value = null;
    resetDraft();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "could not log";
  } finally { saving.value = false; }
}

async function remove(id: number) {
  await meals.deleteLogEntry(id);
  await load();
}

function num(v: number | null | undefined, dp = 0, suffix = "") {
  return v == null ? "—" : v.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  }) + suffix;
}
</script>

<template>
  <main class="today">
    <PageHeader title="Today" :subtitle="new Date().toLocaleDateString([], {
      weekday: 'long', day: 'numeric', month: 'long' })" />

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="loading" class="hint">Loading…</p>

    <!-- Energy so far against the target, when there is one. With no
         target the figure stands alone: an invented denominator would make
         a real number look like progress toward something nobody set. -->
    <Card>
      <div v-if="kcal == null" class="empty-total">
        <strong>Nothing logged yet today</strong>
        <span class="dim">{{ targetKcal
          ? `Target ${num(targetKcal)} kcal`
          : "No energy target set — add your profile in Settings" }}</span>
      </div>
      <div v-else class="totals">
        <div>
          <div class="big mono">{{ num(kcal) }}</div>
          <div class="dim">{{ targetKcal ? `of ${num(targetKcal)} kcal` : "kcal — no target set" }}</div>
        </div>
        <div class="fat">
          <div class="big mono amber">{{ num(fat, 0, " g") }}</div>
          <div class="dim">fat today</div>
        </div>
      </div>
      <div v-if="pct != null" class="bar"><div class="fill" :style="{ width: `${pct}%` }"></div></div>
      <p v-if="day?.unresolved_count" class="warn">
        {{ day.unresolved_count }} entr{{ day.unresolved_count === 1 ? "y" : "ies" }}
        could not be costed, so this total is an underestimate.
      </p>
    </Card>

    <!-- One tap logs the food AND the portion. Repeat leads the row so it
         is never the item that scrolls off. -->
    <div class="quick">
      <button class="chip accent" :disabled="saving" @click="repeatYesterday">
        Same as yesterday
      </button>
      <button v-for="r in recents" :key="`${r.food_id}-${r.label}-${r.quantity}-${r.unit}`"
              class="chip" :disabled="saving"
              :title="`${r.times}× · last on ${r.last_day} · logs as ${r.usual_slot}`"
              @click="logRecent(r)">
        {{ r.label }}
        <span v-if="r.quantity" class="chip-qty">{{ r.quantity }}{{ r.unit ? ` ${r.unit}` : "" }}</span>
      </button>
    </div>

    <!-- All four slots, always. An empty slot shown as empty distinguishes
         "I have not eaten lunch" from "lunch is not a thing I log". -->
    <Card v-for="slot in SLOTS" :key="slot" class="slot">
      <div class="slot-head">
        <strong class="slot-name">{{ slot }}</strong>
        <span v-if="!mealFor(slot)?.entries?.length" class="dim">not logged</span>
        <span v-else class="mono dim">{{ num(mealFor(slot)?.totals?.kcal) }} kcal</span>
        <span class="spacer"></span>
        <button class="ghost small" @click="addingFor = addingFor === slot ? null : slot">
          <Plus :size="13" />
        </button>
      </div>

      <ul v-if="mealFor(slot)?.entries?.length" class="entries">
        <li v-for="e in mealFor(slot)!.entries" :key="e.id">
          <span class="lbl">{{ e.label }}</span>
          <span v-if="e.quantity" class="dim mono">{{ e.quantity }}{{ e.unit ? ` ${e.unit}` : "" }}</span>
          <span class="spacer"></span>
          <span class="mono dim">{{ num(e.nutrition?.kcal) }}</span>
          <button class="icon-btn" title="Remove" @click="remove(e.id)"><Trash2 :size="13" /></button>
        </li>
      </ul>

      <FatAssessment v-if="mealFor(slot)?.fat_assessment" compact
                     :assessment="mealFor(slot)!.fat_assessment" />

      <div v-if="addingFor === slot" class="adder">
        <FoodPicker v-model="draftFood" />
        <QuantityPicker v-model:quantity="draftQty" v-model:unit="draftUnit" :food="draftFood" />
        <input v-if="!draftFood" v-model="draftLabel" placeholder="or type what you ate" />
        <div class="manual">
          <input v-model="draftKcal" inputmode="decimal" placeholder="kcal (optional)" />
          <input v-model="draftFat" inputmode="decimal" placeholder="fat g (optional)" />
        </div>
        <button class="primary" :disabled="saving" @click="add(slot)">Log</button>
      </div>
    </Card>

    <RouterLink to="/meals/plan" class="door">
      <div>
        <strong>Plan &amp; kitchen</strong>
        <span class="dim">Week, shopping, pantry, recipes</span>
      </div>
      <ChevronRight :size="18" />
    </RouterLink>
  </main>
</template>

<style scoped>
.today { display: flex; flex-direction: column; gap: 0.75rem; }
.err { color: var(--bad); font-size: 0.85rem; }
.hint { color: var(--muted); font-size: 0.85rem; }
.mono { font-variant-numeric: tabular-nums; }
.dim { color: var(--muted); font-size: 0.8rem; }
.empty-total { display: flex; flex-direction: column; gap: 0.3rem; }
.empty-total strong { font-size: 1.05rem; }
.totals { display: flex; align-items: flex-end; gap: 1rem; }
.totals .fat { margin-left: auto; text-align: right; }
.big { font-size: 2rem; font-weight: 700; line-height: 1; }
.amber { color: #ffb52e; font-size: 1.25rem; }
.bar { height: 6px; border-radius: 999px; background: var(--border); margin-top: 0.9rem; overflow: hidden; }
.fill { height: 100%; background: var(--accent); }
.warn { color: #ffb52e; font-size: 0.75rem; margin: 0.6rem 0 0; }
.quick { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip {
  display: inline-flex; align-items: baseline; gap: 0.35rem;
  font-size: 0.8rem; padding: 0.3rem 0.6rem;
  border: 1px solid var(--border); border-radius: 999px;
  background: transparent; color: var(--fg); cursor: pointer;
}
.chip.accent { color: var(--accent); border-color: var(--accent); }
.chip:hover:not(:disabled) { border-color: var(--accent); }
.chip:disabled { opacity: 0.5; cursor: default; }
.chip-qty { color: var(--muted); font-size: 0.72rem; }
.slot-head { display: flex; align-items: center; gap: 0.55rem; }
.slot-name { text-transform: capitalize; font-size: 0.9rem; min-width: 5.5rem; }
.spacer { flex: 1; }
.entries { list-style: none; margin: 0.6rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.entries li { display: flex; align-items: baseline; gap: 0.5rem; font-size: 0.85rem; }
.adder { display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.7rem; }
.manual { display: flex; gap: 0.5rem; }
.door {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.9rem 1rem; border: 1px solid var(--border); border-radius: 12px;
  text-decoration: none; color: var(--fg);
}
.door:hover { border-color: var(--accent); }
.door div { display: flex; flex-direction: column; gap: 0.15rem; }
</style>
