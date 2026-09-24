<script setup lang="ts">
/**
 * Direction A — Meals is Today, and everything else sits behind one door.
 *
 * The phone twin is `ui/meals/TodayTab.kt`. Everything on this screen is
 * fetched, not derived here: the totals, the per-slot grouping and the
 * per-meal fat verdict come from `/meals/log`, and the energy target from
 * `/meals/prep/targets`.
 *
 * UI-6: the hero is an energy ring beside a per-MEAL fat column. Day-level
 * fat left the hero — fat is judged per meal (without a gall bladder the
 * constraint is how much lands at once). Unknown verdicts are grey, never
 * green; an empty slot is a dashed "+ Log lunch" card.
 */
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import FoodPicker from "@/components/FoodPicker.vue";
import QuantityPicker from "@/components/QuantityPicker.vue";
import { Trash2, ChevronRight, Plus } from "lucide-vue-next";
import {
  meals, type Food, type LogDay, type LogMeal, type PrepTargets, type RecentEntry, type Recipe,
} from "@/api/client";
import { useVisibilityRefresh } from "@/composables/useVisibilityRefresh";
import { toLocalISO } from "@/dates";

const LIME = "#5dff3b";
const SLOTS = ["breakfast", "lunch", "dinner", "snack"] as const;

// Re-read on every load, not frozen at mount (UX-D5).
const today = ref(toLocalISO(new Date()));
const day = ref<LogDay | null>(null);
const targets = ref<PrepTargets | null>(null);
const recents = ref<RecentEntry[]>([]);
const recipes = ref<Recipe[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const actionError = ref<string | null>(null);
const addingFor = ref<string | null>(null);

const draftFood = ref<Food | null>(null);
const draftQty = ref("");
const draftUnit = ref("");
const draftLabel = ref("");
const draftKcal = ref("");
const draftFat = ref("");

async function load() {
  today.value = toLocalISO(new Date());
  try {
    const [d, t, r, rc] = await Promise.all([
      meals.getLog(today.value, 1),
      meals.prepTargets().catch(() => null),
      meals.recentLogEntries(12).catch(() => [] as RecentEntry[]),
      recipes.value.length ? Promise.resolve(recipes.value) : meals.listRecipes().catch(() => [] as Recipe[]),
    ]);
    day.value = d[0] ?? { day: today.value, meals: [], totals: {}, complete: false, note: null, entry_count: 0, unresolved_count: 0 };
    targets.value = t;
    recents.value = r;
    recipes.value = rc;
    error.value = null;
  } catch (e) {
    // A failed load is not "nothing logged": keep what we had and say so.
    error.value = e instanceof Error ? e.message : "load failed";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
useVisibilityRefresh(load);

const targetKcal = () => (targets.value?.ok ? targets.value.target_kcal ?? null : null);
function mealFor(slot: string): LogMeal | null {
  const m = day.value?.meals?.find((x) => x.slot === slot);
  return m && m.entries?.length ? m : null;
}
/** Meal fat: the assessment's figure, else the meal total. Null stays null. */
function mealFat(m: LogMeal | null): number | null {
  return m?.fat_assessment?.fat_g ?? m?.totals?.fat_g ?? null;
}
/** Verdict → colour. Unknown is GREY, never green; high is amber, never rose. */
function verdictColor(v: string | null | undefined): string {
  if (v === "ok") return "#5dff3b";
  if (v === "approaching") return "rgba(255, 181, 46, .7)";
  if (v === "high" || v === "very_high") return "#ffb52e";
  return "#9b9bb0";
}
function verdictText(m: LogMeal): string {
  const fa = m.fat_assessment;
  if (fa?.reason) return fa.reason;
  switch (fa?.verdict) {
    case "very_high": return "well over your per-meal fat target";
    case "high": return "over your per-meal fat target";
    case "approaching": return "close to your per-meal fat target";
    case "ok": return "within your per-meal fat target";
    default: return "no per-meal fat target set";
  }
}

async function logRecent(r: RecentEntry) {
  saving.value = true;
  actionError.value = null;
  try {
    await meals.addLogEntry({
      day: today.value, slot: r.usual_slot,
      food_id: r.food_id, recipe_id: r.recipe_id,
      label: r.food_id || r.recipe_id ? null : r.label,
      quantity: r.quantity, unit: r.unit, servings: r.servings,
      manual_kcal: r.manual_kcal, manual_fat_g: r.manual_fat_g,
    });
    await load();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : "could not log";
  } finally { saving.value = false; }
}

async function repeatYesterday() {
  const d = new Date(`${today.value}T00:00:00`);
  d.setDate(d.getDate() - 1);
  saving.value = true;
  actionError.value = null;
  try {
    await meals.repeatLogDay(toLocalISO(d), today.value);
    await load();
  } catch (e) {
    // Only a 404 means "nothing to copy"; offline or a server fault must
    // not be reported as an empty yesterday.
    const status = (e as { response?: { status?: number } })?.response?.status;
    actionError.value = status === 404
      ? "nothing logged yesterday, so there was nothing to copy"
      : e instanceof Error ? e.message : "could not copy yesterday";
  } finally { saving.value = false; }
}

function resetDraft() {
  draftFood.value = null; draftQty.value = ""; draftUnit.value = "";
  draftLabel.value = ""; draftKcal.value = ""; draftFat.value = "";
}

async function add(slot: string) {
  if (!draftFood.value && !draftLabel.value.trim()) return;
  saving.value = true;
  actionError.value = null;
  try {
    await meals.addLogEntry({
      day: today.value, slot,
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
    actionError.value = e instanceof Error ? e.message : "could not log";
  } finally { saving.value = false; }
}

async function remove(id: number) {
  try {
    await meals.deleteLogEntry(id);
    await load();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : "could not remove";
  }
}

function num(v: number | null | undefined, dp = 0, suffix = "") {
  return v == null ? "—" : v.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  }) + suffix;
}
const dateLabel = new Date().toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
</script>

<template>
  <NeonPage title="Meals" back="/you">
    <template #trailing><span class="dim">{{ dateLabel }}</span></template>

    <p v-if="error && day" class="stale">Showing what we last loaded — refresh failed.</p>
    <button v-if="error && !day" class="fail" type="button" @click="load">
      <strong>Couldn't load today's log</strong>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>

    <NeonHero v-else :accent="LIME">
      <div class="hero">
        <NeonRing :fraction="day && day.totals?.kcal != null && targetKcal() ? day.totals.kcal / targetKcal()! : 0"
                  :color="LIME" :size="112">
          <template v-if="!day"><span class="cap">loading</span></template>
          <template v-else>
            <span class="kcal">{{ num(day.totals?.kcal) }}</span>
            <span class="cap">{{ targetKcal() ? `of ${num(targetKcal())} kcal` : "no target set" }}</span>
          </template>
        </NeonRing>
        <div class="fatcol">
          <div class="fat-h">Fat per meal</div>
          <div v-for="slot in SLOTS" :key="slot" class="fat-row">
            <i class="dot" :style="{ background: mealFor(slot) ? verdictColor(mealFor(slot)!.fat_assessment?.verdict) : '#272a3b' }" />
            <span class="fat-slot">{{ slot }}</span>
            <span v-if="!mealFor(slot)" class="dim">not logged</span>
            <span v-else class="fat-g"
                  :style="{ color: verdictColor(mealFor(slot)!.fat_assessment?.verdict) }">{{ num(mealFat(mealFor(slot)), 0, " g") }}</span>
          </div>
        </div>
      </div>
      <p v-if="day && !targetKcal() && targets" class="dim note">{{ targets.reason ?? "No energy target set — add your profile in Settings." }}</p>
      <p v-if="day?.unresolved_count" class="warn">
        {{ day.unresolved_count }} not costed — this understates the total.
      </p>
    </NeonHero>

    <p v-if="actionError" class="warn">{{ actionError }}</p>

    <template v-if="day">
      <NeonEyebrow>Log again</NeonEyebrow>
      <div class="quick">
        <button class="tile accent" :disabled="saving" @click="repeatYesterday">Same as yesterday</button>
        <button v-for="r in recents" :key="`${r.food_id}-${r.label}-${r.quantity}-${r.unit}`"
                class="tile" :disabled="saving"
                :title="`${r.times}× · last on ${r.last_day} · logs as ${r.usual_slot}`"
                @click="logRecent(r)">
          <span class="tile-l">{{ r.label }}</span>
          <span v-if="r.quantity" class="tile-q">{{ r.quantity }}{{ r.unit ? ` ${r.unit}` : "" }}</span>
        </button>
      </div>

      <NeonEyebrow>Meals</NeonEyebrow>
      <div class="slots">
        <template v-for="slot in SLOTS" :key="slot">
          <div v-if="mealFor(slot)" class="slot" :style="{ '--v': verdictColor(mealFor(slot)!.fat_assessment?.verdict) }">
            <div class="slot-head">
              <strong class="slot-name">{{ slot }}</strong>
              <span class="slot-fat">{{ num(mealFat(mealFor(slot))) }}</span><span class="dim"> g fat</span>
              <button class="icon-btn" :title="`Add to ${slot}`" @click="addingFor = addingFor === slot ? null : slot"><Plus :size="15" /></button>
            </div>
            <ul class="entries">
              <li v-for="e in mealFor(slot)!.entries" :key="e.id">
                <span class="lbl">{{ e.label }}</span>
                <span v-if="e.quantity" class="dim">{{ e.quantity }}{{ e.unit ? ` ${e.unit}` : "" }}</span>
                <span class="spacer" />
                <span class="dim mono">{{ num(e.nutrition?.kcal) }}</span>
                <button class="icon-btn" title="Remove" @click="remove(e.id)"><Trash2 :size="13" /></button>
              </li>
            </ul>
            <div class="slot-foot">
              <span class="dim">{{ mealFor(slot)!.totals?.kcal != null ? `${num(mealFor(slot)!.totals.kcal)} kcal` : "kcal unknown" }}</span>
              <span class="verdict">{{ verdictText(mealFor(slot)!) }}</span>
            </div>
          </div>
          <button v-else class="empty-slot" type="button" @click="addingFor = addingFor === slot ? null : slot">+ Log {{ slot }}</button>

          <div v-if="addingFor === slot" class="adder">
            <FoodPicker v-model="draftFood" />
            <QuantityPicker v-model:quantity="draftQty" v-model:unit="draftUnit" :food="draftFood" />
            <input v-if="!draftFood" v-model="draftLabel" placeholder="or type what you ate" />
            <div class="manual">
              <input v-model="draftKcal" inputmode="decimal" placeholder="kcal (optional)" />
              <input v-model="draftFat" inputmode="decimal" placeholder="fat g (optional)" />
            </div>
            <button class="primary" :disabled="saving" @click="add(slot)">Log to {{ slot }}</button>
          </div>
        </template>
      </div>

      <RouterLink to="/meals/plan" class="door">
        <div>
          <strong>Plan &amp; kitchen</strong>
          <span class="dim">Week, prep, shopping, pantry, recipes</span>
        </div>
        <ChevronRight :size="18" />
      </RouterLink>
    </template>
  </NeonPage>
</template>

<style scoped>
.dim { color: var(--rn-mut); font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
.stale { font-size: 11px; color: var(--rn-mut); margin: 0 0 8px; }
.warn { color: #ffb52e; font-size: 12px; margin: 8px 0 0; }
.note { margin: 10px 0 0; }
.fail { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 181, 46, .08); border: 1px solid rgba(255, 181, 46, .3); border-radius: 14px; padding: 12px 14px;
  color: var(--rn-mut); font: inherit; font-size: 12px; margin-bottom: 12px; }
.fail strong { color: #ffb52e; font-size: 13px; }
.fail em { font-style: normal; color: #28e6ff; font-weight: 600; }
.hero { display: flex; align-items: center; gap: 16px; }
.kcal { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 22px; color: var(--rn-ink); }
.cap { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); }
.fatcol { flex: 1; display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.fat-h { font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); }
.fat-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
.fat-slot { flex: 1; text-transform: capitalize; color: var(--rn-ink); }
.fat-g { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 13px; }
.quick { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.tile { flex: 0 0 auto; max-width: 180px; min-height: 44px; display: flex; flex-direction: column; justify-content: center; align-items: flex-start;
  padding: 6px 12px; border-radius: 14px; border: 1px solid var(--rn-line); background: var(--rn-high); color: var(--rn-ink);
  font: inherit; font-size: 12px; cursor: pointer; text-align: left; }
.tile.accent { color: #28e6ff; }
.tile:disabled { opacity: .5; cursor: default; }
.tile-l { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; font-weight: 500; }
.tile-q { font-size: 10px; color: var(--rn-mut); }
.slots { display: flex; flex-direction: column; gap: 10px; }
.slot { background: var(--rn-card); border-radius: 18px; padding: 12px 14px 12px 18px; position: relative; overflow: hidden; }
.slot::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--v); }
.slot-head { display: flex; align-items: baseline; gap: 4px; }
.slot-name { flex: 1; text-transform: capitalize; font-size: 14px; }
.slot-fat { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 18px; color: var(--v); }
.entries { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.entries li { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--rn-mut); }
.entries .lbl { color: var(--rn-ink); }
.spacer { flex: 1; }
.slot-foot { display: flex; justify-content: space-between; gap: 8px; margin-top: 6px; }
.verdict { font-size: 11px; color: var(--v); text-align: right; }
.icon-btn { background: transparent; border: 0; color: var(--rn-mut); cursor: pointer; min-width: 32px; min-height: 32px;
  display: inline-flex; align-items: center; justify-content: center; }
.icon-btn:hover { color: var(--rn-ink); }
.empty-slot { height: 48px; border-radius: 18px; border: 1.5px dashed var(--rn-track); background: transparent; color: var(--rn-mut);
  font: inherit; font-size: 13px; font-weight: 500; cursor: pointer; text-transform: none; }
.empty-slot:hover { border-color: #5dff3b; color: var(--rn-ink); }
.adder { display: flex; flex-direction: column; gap: 8px; padding: 12px; background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; }
.adder input { background: var(--rn-bg); color: var(--rn-ink); border: 1px solid var(--rn-line); border-radius: 8px; padding: 8px; font: inherit; font-size: 14px; }
.manual { display: flex; gap: 8px; }
.manual input { flex: 1; min-width: 0; }
.primary { min-height: 44px; border-radius: 14px; border: 0; background: #5dff3b; color: var(--rn-onacc); font: inherit; font-weight: 700; cursor: pointer; }
.door { display: flex; align-items: center; gap: 12px; margin-top: 14px; min-height: 56px; padding: 12px 14px; border-radius: 18px;
  background: var(--rn-card); text-decoration: none; color: var(--rn-ink); }
.door div { flex: 1; display: flex; flex-direction: column; gap: 2px; }
</style>
