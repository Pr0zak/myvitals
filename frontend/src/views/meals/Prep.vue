<script setup lang="ts">
/**
 * Weekend prep for the week ahead — MEAL-9.
 *
 * The screen is deliberately two screens in one, because batch cooking
 * has two completely different moments and mixing them helps neither.
 *
 * **Sunday** you are standing in the kitchen with a knife. You want a
 * short checklist of things to cook, in the order a real session runs
 * (protein and grain on first, sauce while they cook), and you want to
 * tick them off without losing your place.
 *
 * **Wednesday** you are hungry and opening the fridge. You want to know
 * what tonight is, what goes in it, and — if you are eating out — to say
 * so in one tap and be told what that leaves spare.
 *
 * So: a Prep tab and a Week tab, and the tab defaults to whichever the
 * date suggests.
 *
 * Nothing on this screen scores adherence. Skipping a meal or eating out
 * are ordinary outcomes that release their portions back into the spare
 * count. A planner that turns red on Wednesday is a planner that gets
 * deleted in week two.
 *
 * Every number rendered here comes from the server. The AI that proposes
 * the week never emits a calorie — see `analytics/prep.py`.
 */
import { computed, onMounted, ref } from "vue";
import PageHeader from "@/components/PageHeader.vue";
import Card from "@/components/Card.vue";
import EmptyState from "@/components/EmptyState.vue";
import {
  ChefHat, Check, Sparkles, ShoppingCart, RefreshCw, Info,
  UtensilsCrossed, CalendarDays, AlertTriangle, Trash2, ClipboardList,
} from "lucide-vue-next";
import { meals, type PrepPlan, type PrepTargets, type PrepMeal } from "@/api/client";
import { toLocalISO } from "@/dates";

const plan = ref<PrepPlan | null>(null);
const targets = ref<PrepTargets | null>(null);
const loading = ref(true);
const showWhy = ref(false);

/** "24 Aug" for a row that already shows the weekday. */
function shortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

/** "Mon 24 Aug", not "2026-08-24". An ISO date is a storage format; it is
 *  not what a week is called when someone is deciding what to cook. */
function prettyDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

const generating = ref(false);
const busy = ref<number | null>(null);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);
const showTargets = ref(false);

const draftDays = ref(5);
const draftSlots = ref<string[]>(["lunch", "dinner"]);

/**
 * Prep on a weekend, eat on a weekday. Guessing from the day of the week
 * gets it right most of the time and costs the user nothing when it is
 * wrong — the other tab is one tap away.
 */
const today = new Date();
const tab = ref<"prep" | "week">(
  today.getDay() === 0 || today.getDay() === 6 ? "prep" : "week",
);

function mondayOf(d: Date): string {
  const copy = new Date(d);
  const shift = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - shift);
  return toLocalISO(copy);
}

/** Next Monday, since a plan made at the weekend is for the week ahead. */
function nextMonday(): string {
  const d = new Date();
  const ahead = (8 - d.getDay()) % 7 || 7;
  d.setDate(d.getDate() + ahead);
  return toLocalISO(d);
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [p, t] = await Promise.all([
      meals.currentPrepPlan(),
      meals.prepTargets(),
    ]);
    plan.value = p;
    targets.value = t;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

async function generate() {
  generating.value = true;
  error.value = null;
  notice.value = null;
  try {
    plan.value = await meals.generatePrepPlan({
      start: nextMonday(),
      days: draftDays.value,
      slots: draftSlots.value,
    });
    tab.value = "prep";
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })
      .response?.data?.detail;
    error.value = detail ?? (e as Error).message;
  } finally {
    generating.value = false;
  }
}

async function toggleComponent(id: number, done: boolean) {
  busy.value = id;
  try {
    plan.value = await meals.updatePrepComponent(id, { done });
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = null;
  }
}

async function setMealStatus(m: PrepMeal, status: string) {
  busy.value = m.id;
  notice.value = null;
  try {
    // Tapping the active status again clears it back to suggested, so
    // "I tapped skip by mistake" is one tap to undo rather than a
    // decision the user is stuck with for the rest of the week.
    const next = m.status === status ? "suggested" : status;
    plan.value = await meals.updatePrepMeal(m.id, { status: next });
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = null;
  }
}

async function logMeal(m: PrepMeal) {
  busy.value = m.id;
  error.value = null;
  try {
    const res = await meals.logPrepMeal(m.id);
    notice.value = `Logged ${res.logged} item${res.logged === 1 ? "" : "s"} to ${res.slot}.`;
    plan.value = await meals.getPrepPlan(plan.value!.id);
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })
      .response?.data?.detail;
    error.value = detail ?? (e as Error).message;
  } finally {
    busy.value = null;
  }
}

async function buildList() {
  if (!plan.value) return;
  generating.value = true;
  error.value = null;
  try {
    const list = await meals.prepShoppingList(plan.value.id);
    notice.value =
      `Shopping list ready — ${list.items.length} item` +
      `${list.items.length === 1 ? "" : "s"} to buy` +
      (list.covered_by_pantry
        ? `, ${list.covered_by_pantry} already in the pantry.`
        : ".");
    plan.value = await meals.getPrepPlan(plan.value.id);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    generating.value = false;
  }
}

async function discard() {
  if (!plan.value) return;
  if (!confirm("Delete this week's plan? The shopping list stays.")) return;
  try {
    await meals.deletePrepPlan(plan.value.id);
    plan.value = null;
  } catch (e) {
    error.value = (e as Error).message;
  }
}

const doneCount = computed(
  () => plan.value?.components.filter((c) => c.done).length ?? 0,
);

/** Only surplus worth acting on. Half a portion of sauce is noise. */
const spares = computed(
  () => (plan.value?.components ?? []).filter((c) => (c.spare ?? 0) >= 1),
);
const shorts = computed(
  () => (plan.value?.components ?? []).filter((c) => c.short),
);

const uncostable = computed(
  () => (plan.value?.components ?? []).filter((c) => c.unresolved),
);

const todayISO = toLocalISO(new Date());

function amount(c: PrepPlan["components"][number]): string {
  if (c.quantity == null) return "—";
  const unit = c.unit ? ` ${c.unit}` : "";
  return `${Number(c.quantity.toFixed(2))}${unit}`;
}

function kcalOf(m: PrepMeal): string {
  return m.est_kcal == null ? "—" : `${Math.round(m.est_kcal)} kcal`;
}

function slotLabel(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

onMounted(load);
</script>

<template>
  <PageHeader title="Week prep" subtitle="Cook once, eat all week">
    <template #actions>
      <button class="ghost" @click="load" :disabled="loading">
        <RefreshCw :size="14" /> Refresh
      </button>
    </template>
  </PageHeader>

  <p v-if="error" class="err">{{ error }}</p>
  <p v-if="notice" class="ok-note">{{ notice }}</p>

  <!-- ── Targets ──────────────────────────────────────────────── -->
  <Card v-if="targets">
    <div v-if="targets.ok" class="targets">
      <div class="t-main">
        <div class="t-num">
          <span class="big">{{ targets.override_kcal ?? targets.target_kcal }}</span>
          <small>kcal a day</small>
        </div>
        <div class="t-num">
          <span class="big">{{ targets.protein_g }}</span>
          <small>g protein</small>
        </div>
        <div v-if="targets.expected_loss_kg_per_week" class="t-num">
          <span class="big">{{ targets.expected_loss_kg_per_week }}</span>
          <small>kg a week</small>
        </div>
      </div>
      <p v-if="targets.weight_stale" class="warn-line">
        <AlertTriangle :size="13" />
        These are built on your weight from {{ targets.weight_measured_on }} —
        {{ targets.weight_age_days }} days ago. Everything above inherits that
        drift, and it will look perfectly consistent while being wrong. Sync or
        add a current weight to refresh it.
      </p>
      <button class="link" @click="showTargets = !showTargets">
        <Info :size="12" /> {{ showTargets ? "Hide" : "How this was worked out" }}
      </button>
      <div v-if="showTargets" class="t-detail">
        <p v-if="targets.override_kcal" class="warn-line">
          You set {{ targets.override_kcal }} kcal by hand, so that is what
          plans are built against. The estimate below is shown for comparison.
        </p>
        <ul>
          <li>
            <span>Resting burn ({{ targets.method }})</span>
            <b>{{ targets.bmr_kcal }} kcal</b>
          </li>
          <li>
            <span>× {{ targets.activity_factor }} for {{ targets.activity_level }} activity</span>
            <b>{{ targets.tdee_kcal }} kcal</b>
          </li>
          <li v-if="targets.deficit_kcal">
            <span>− deficit to lose weight</span>
            <b>{{ targets.deficit_kcal }} kcal</b>
          </li>
          <li v-if="targets.protein_range_g">
            <span>
              Protein, {{ targets.goal_weight_kg ? "scaled to your goal weight" : "scaled to bodyweight" }}
            </span>
            <b>{{ targets.protein_range_g[0] }}–{{ targets.protein_range_g[1] }} g</b>
          </li>
        </ul>
        <p v-if="targets.hit_floor" class="warn-line">
          The full deficit would have taken this below a safe floor, so it
          was trimmed. The number above is the deficit actually applied.
        </p>
        <p class="caveat">{{ targets.caveat }}</p>
      </div>
    </div>
    <div v-else class="targets">
      <p class="sub">{{ targets.reason }}</p>
    </div>
  </Card>

  <!-- ── No plan yet ──────────────────────────────────────────── -->
  <Card v-if="!loading && !plan">
    <EmptyState
      :icon="ChefHat"
      title="No prep plan yet"
      text="Pick a few things to batch cook at the weekend and the week
            assembles itself from them. Nothing is fixed — you can skip a
            meal or eat out and the plan tells you what that leaves spare."
    />
    <div class="gen-form">
      <label>
        Days
        <select v-model.number="draftDays">
          <option :value="5">Mon–Fri</option>
          <option :value="7">Mon–Sun</option>
        </select>
      </label>
      <fieldset>
        <legend>Meals to plan</legend>
        <label v-for="s in ['breakfast', 'lunch', 'dinner', 'snack']" :key="s" class="chk">
          <input type="checkbox" :value="s" v-model="draftSlots" />
          {{ slotLabel(s) }}
        </label>
      </fieldset>
      <p class="sub">
        Whatever you leave out stays yours to sort out — the plan says so
        rather than showing the week as short of target.
      </p>
      <button class="primary" @click="generate" :disabled="generating || !draftSlots.length">
        <Sparkles :size="14" />
        {{ generating ? "Planning…" : "Plan next week" }}
      </button>
    </div>
  </Card>

  <!-- ── The plan ─────────────────────────────────────────────── -->
  <template v-if="plan">
    <Card>
      <div class="plan-head">
        <div>
          <h2>{{ plan.headline || "This week" }}</h2>
          <p class="sub">
            Week of {{ prettyDay(plan.start_day) }} ·
            {{ doneCount }} of {{ plan.components.length }} cooked
          </p>
        </div>
        <div class="head-actions">
          <button class="ghost" @click="buildList" :disabled="generating">
            <ShoppingCart :size="14" /> Shopping list
          </button>
          <button class="ghost danger" @click="discard">
            <Trash2 :size="14" /> Delete
          </button>
        </div>
      </div>

      <!-- Warnings stay out in the open. They are time-sensitive and
           actionable — "this portion is used on day 5, past what cooked
           chicken keeps" is a thing to do on prep day, not commentary. -->
      <p v-for="w in plan.warnings" :key="w" class="warn-line">
        <AlertTriangle :size="13" /> {{ w }}
      </p>

      <!-- The coverage explanation and the model's narrative are both true
           and both worth reading once. Left expanded they filled the whole
           screen, so the things to actually cook — the point of the plan —
           began below the fold. -->
      <button v-if="plan.notes || plan.budgets.uncovered_kcal"
              class="link why" @click="showWhy = !showWhy">
        {{ showWhy ? "Hide the reasoning" : "Why this plan" }}
      </button>

      <template v-if="showWhy">
        <p v-if="plan.budgets.uncovered_kcal" class="sub coverage">
          These meals cover about
          {{ Math.round(plan.budgets.covered_share * 100) }}% of your day. The
          remaining ~{{ plan.budgets.uncovered_kcal }} kcal is whatever you eat
          outside them — it is not a shortfall.
        </p>
        <p v-if="plan.notes" class="notes">{{ plan.notes }}</p>
      </template>

      <div class="tabs">
        <button :class="{ on: tab === 'prep' }" @click="tab = 'prep'">
          <ChefHat :size="14" /> Prep day
        </button>
        <button :class="{ on: tab === 'week' }" @click="tab = 'week'">
          <CalendarDays :size="14" /> The week
        </button>
      </div>
    </Card>

    <!-- ── Prep tab ──────────────────────────────────────────── -->
    <template v-if="tab === 'prep'">
      <Card
        v-for="c in plan.components"
        :key="c.id"
        :class="['comp', c.kind, { done: c.done }]"
      >
        <div class="comp-row">
          <button
            class="tick"
            :class="{ on: c.done }"
            :disabled="busy === c.id"
            @click="toggleComponent(c.id, !c.done)"
            :aria-label="c.done ? 'Mark not done' : 'Mark done'"
          >
            <Check :size="15" />
          </button>
          <div class="comp-body">
            <div class="comp-head">
              <span class="kind">{{ c.kind }}</span>
              <b>{{ c.name }}</b>
            </div>
            <p class="qty">
              {{ amount(c) }}
              <span class="sep">·</span>
              {{ c.portions }} portion{{ c.portions === 1 ? "" : "s" }}
              <template v-if="c.grams_per_portion">
                <span class="sep">·</span>
                {{ Math.round(c.grams_per_portion) }} g each
              </template>
            </p>
            <p v-if="c.prep_note" class="prep-note">{{ c.prep_note }}</p>
            <p v-if="c.unresolved" class="uncostable">
              No nutrition for this one — {{ c.unresolved_reason }}.
            </p>
          </div>
        </div>
      </Card>

      <Card v-if="uncostable.length">
        <p class="sub">
          {{ uncostable.length }} component{{ uncostable.length === 1 ? "" : "s" }}
          could not be matched to a food, so the calorie and protein totals
          below are partial rather than wrong. Edit the amount, or pick the
          food on the Foods page, to fill them in.
        </p>
      </Card>
    </template>

    <!-- ── Week tab ──────────────────────────────────────────── -->
    <template v-else>
      <Card v-if="spares.length || shorts.length" class="ledger">
        <h3><UtensilsCrossed :size="13" /> What is spare</h3>
        <ul>
          <li v-for="c in spares" :key="c.id">
            <b>{{ c.name }}</b>
            <span class="n">{{ c.spare }} portion{{ c.spare === 1 ? "" : "s" }} unclaimed</span>
          </li>
          <li v-for="c in shorts" :key="`s${c.id}`" class="short">
            <b>{{ c.name }}</b>
            <span class="n">
              short {{ Math.abs(c.spare ?? 0) }} — a meal later in the week has
              nothing behind it
            </span>
          </li>
        </ul>
        <p class="sub">
          Spare portions are not a mistake. Move a meal to a later day, or
          freeze them.
        </p>
      </Card>

      <Card
        v-for="d in plan.schedule"
        :key="d.day"
        :class="['day', { today: d.day === todayISO }]"
      >
        <div class="day-head">
          <div>
            <b>{{ d.weekday }}</b>
            <!-- "24 Aug", not "2026-08-24". The weekday sits beside it,
                 so the year is noise. -->
            <span class="date">{{ shortDay(d.day) }}</span>
          </div>
          <span class="day-kcal">
            {{ d.planned_kcal == null ? "—" : `${d.planned_kcal} kcal` }}
            <small v-if="d.budget_kcal">of ~{{ d.budget_kcal }}</small>
          </span>
        </div>

        <p v-if="!d.meals.length" class="sub">Nothing planned.</p>

        <div v-for="m in d.meals" :key="m.id" :class="['meal', m.status]">
          <div class="meal-head">
            <span class="slot">{{ slotLabel(m.slot) }}</span>
            <b>{{ m.name }}</b>
            <span class="meal-kcal">{{ kcalOf(m) }}</span>
          </div>
          <p v-if="m.assembly_note" class="assembly">{{ m.assembly_note }}</p>
          <p class="macros">
            <span v-if="m.est_protein_g">{{ Math.round(m.est_protein_g) }} g protein</span>
            <span v-if="m.est_fat_g">{{ Math.round(m.est_fat_g) }} g fat</span>
            <span
              v-if="m.fat_assessment && ['high', 'very_high'].includes(m.fat_assessment.verdict)"
              class="fat-flag"
            >
              over your per-meal fat target
            </span>
            <span v-if="m.unresolved_count" class="partial">
              partial — {{ m.unresolved_count }} item not costed
            </span>
          </p>
          <div class="meal-actions">
            <button
              :class="{ on: m.status === 'accepted' }"
              :disabled="busy === m.id"
              @click="setMealStatus(m, 'accepted')"
            >
              <Check :size="13" /> Making this
            </button>
            <button
              :class="{ on: m.status === 'eating_out' }"
              :disabled="busy === m.id"
              @click="setMealStatus(m, 'eating_out')"
            >
              Eating out
            </button>
            <button
              :class="{ on: m.status === 'skipped' }"
              :disabled="busy === m.id"
              @click="setMealStatus(m, 'skipped')"
            >
              Skip
            </button>
            <button
              class="log"
              :disabled="busy === m.id || !m.uses.length"
              @click="logMeal(m)"
            >
              <ClipboardList :size="13" /> Log it
            </button>
          </div>
        </div>
      </Card>
    </template>

    <Card>
      <button class="ghost" @click="generate" :disabled="generating">
        <Sparkles :size="14" />
        {{ generating ? "Planning…" : "Plan a different week" }}
      </button>
      <p class="sub">
        Replaces the plan for that week. Anything you have already ticked off
        or logged stays where it is.
      </p>
    </Card>
  </template>
</template>

<style scoped>
.err { color: #f87171; font-size: 0.85rem; }
.ok-note { color: #4ade80; font-size: 0.85rem; }
.sub { margin: 0.4rem 0 0; font-size: 0.78rem; color: var(--muted-2); line-height: 1.5; }
.caveat { margin: 0.6rem 0 0; font-size: 0.74rem; color: var(--muted-2); line-height: 1.5; }
button.ghost {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 8px; padding: 0.35rem 0.6rem; font: inherit; font-size: 0.8rem;
  cursor: pointer;
}
button.ghost.danger { color: #f87171; }
button.primary {
  display: inline-flex; align-items: center; gap: 0.35rem;
  border: 0; background: var(--accent, #38bdf8); color: #06121c;
  border-radius: 8px; padding: 0.5rem 0.9rem; font: inherit; font-weight: 600;
  cursor: pointer;
}
button.primary:disabled { opacity: 0.5; cursor: default; }
.link {
  display: inline-flex; align-items: center; gap: 0.25rem;
  background: none; border: 0; color: var(--accent, #38bdf8);
  cursor: pointer; font: inherit; font-size: 0.76rem; padding: 0; margin-top: 0.5rem;
}

/* targets */
.t-main { display: flex; gap: 1.6rem; flex-wrap: wrap; }
.t-num { display: flex; flex-direction: column; }
.t-num .big {
  font-size: 1.7rem; font-weight: 600; color: var(--fg);
  font-variant-numeric: tabular-nums; line-height: 1.1;
}
.t-num small { font-size: 0.72rem; color: var(--muted-2); }
.t-detail ul { list-style: none; margin: 0.6rem 0 0; padding: 0; }
.t-detail li {
  display: flex; justify-content: space-between; gap: 1rem;
  padding: 0.25rem 0; font-size: 0.8rem; border-bottom: 1px solid var(--line);
}
.t-detail li span { color: var(--muted-2); }
.t-detail li b { font-variant-numeric: tabular-nums; }
.warn-line {
  display: flex; align-items: flex-start; gap: 0.35rem;
  margin: 0.5rem 0 0; font-size: 0.78rem; color: #fbbf24; line-height: 1.5;
}

/* generate form */
.gen-form { display: flex; flex-direction: column; gap: 0.7rem; margin-top: 0.8rem; }
.gen-form label { font-size: 0.8rem; color: var(--muted-2); }
.gen-form select {
  margin-left: 0.4rem; background: var(--bg-2, #111); color: var(--fg);
  border: 1px solid var(--line); border-radius: 6px; padding: 0.25rem 0.4rem;
  font: inherit; font-size: 0.8rem;
}
.gen-form fieldset {
  border: 1px solid var(--line); border-radius: 8px; padding: 0.5rem 0.7rem;
  display: flex; gap: 0.9rem; flex-wrap: wrap;
}
.gen-form legend { font-size: 0.72rem; color: var(--muted-2); padding: 0 0.3rem; }
.chk { display: inline-flex; align-items: center; gap: 0.3rem; }

/* plan header */
.plan-head { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.plan-head h2 { margin: 0; font-size: 1.05rem; }
.head-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.coverage { border-left: 2px solid var(--line); padding-left: 0.6rem; }
.why { display: block; margin-top: 0.7rem; font-size: 0.8rem; }
.notes { margin: 0.7rem 0 0; font-size: 0.8rem; color: var(--muted-2); line-height: 1.55; white-space: pre-line; }
.tabs { display: flex; gap: 0.4rem; margin-top: 0.9rem; }
.tabs button {
  display: inline-flex; align-items: center; gap: 0.3rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 999px; padding: 0.35rem 0.8rem; font: inherit; font-size: 0.8rem;
  cursor: pointer;
}
.tabs button.on { border-color: var(--accent, #38bdf8); color: var(--fg); }

/* components */
.comp { margin-bottom: 0.4rem; border-left: 3px solid var(--line); }
.comp.protein { border-left-color: #f87171; }
.comp.grain { border-left-color: #fbbf24; }
.comp.veg { border-left-color: #4ade80; }
.comp.sauce { border-left-color: #a78bfa; }
.comp.done { opacity: 0.55; }
.comp-row { display: flex; gap: 0.7rem; align-items: flex-start; }
.tick {
  flex: none; width: 26px; height: 26px; border-radius: 7px;
  border: 1px solid var(--line); background: transparent; color: transparent;
  display: grid; place-items: center; cursor: pointer;
}
.tick.on { background: #22c55e; border-color: #22c55e; color: #06121c; }
.comp-body { min-width: 0; flex: 1; }
.comp-head { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.kind {
  font-size: 0.64rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted-2);
}
.qty { margin: 0.2rem 0 0; font-size: 0.8rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.qty .sep { margin: 0 0.3rem; }
.prep-note { margin: 0.35rem 0 0; font-size: 0.8rem; line-height: 1.5; }
.uncostable { margin: 0.3rem 0 0; font-size: 0.74rem; color: #fbbf24; }

/* ledger */
.ledger h3 {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.78rem; color: var(--muted-2); font-weight: 600;
  margin: 0 0 0.4rem; text-transform: uppercase; letter-spacing: 0.04em;
}
.ledger ul { list-style: none; margin: 0; padding: 0; }
.ledger li { display: flex; gap: 0.5rem; align-items: baseline; padding: 0.22rem 0; font-size: 0.84rem; flex-wrap: wrap; }
.ledger .n { color: var(--muted-2); font-size: 0.76rem; }
.ledger li.short .n { color: #fbbf24; }

/* the week */
.day { margin-bottom: 0.4rem; }
.day.today { border-color: var(--accent, #38bdf8); }
.day-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.6rem; }
.day-head .date { margin-left: 0.5rem; font-size: 0.74rem; color: var(--muted-2); }
.day-kcal { font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.day-kcal small { color: var(--muted-2); font-size: 0.72rem; margin-left: 0.2rem; }
.meal { margin-top: 0.7rem; padding-left: 0.6rem; border-left: 2px solid var(--line); }
.meal.accepted { border-left-color: #22c55e; }
.meal.eating_out, .meal.skipped { border-left-color: var(--line); opacity: 0.6; }
.meal-head { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.slot {
  font-size: 0.64rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted-2);
}
.meal-kcal { margin-left: auto; font-size: 0.78rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.assembly { margin: 0.25rem 0 0; font-size: 0.8rem; line-height: 1.5; color: var(--muted-2); }
.macros { display: flex; gap: 0.7rem; flex-wrap: wrap; margin: 0.3rem 0 0; font-size: 0.73rem; color: var(--muted-2); }
.macros .fat-flag { color: #fbbf24; }
.macros .partial { color: #fbbf24; }
.meal-actions { display: flex; gap: 0.35rem; margin-top: 0.45rem; flex-wrap: wrap; }
.meal-actions button {
  display: inline-flex; align-items: center; gap: 0.25rem;
  border: 1px solid var(--line); background: transparent; color: var(--muted-2);
  border-radius: 999px; padding: 0.22rem 0.6rem; font: inherit; font-size: 0.74rem;
  cursor: pointer;
}
.meal-actions button.on { border-color: #22c55e; color: #4ade80; }
.meal-actions button.log { margin-left: auto; }
.meal-actions button:disabled { opacity: 0.4; cursor: default; }
</style>
