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
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import {
  Check, Sparkles, ShoppingCart, RefreshCw, Info, AlertTriangle, Trash2, ClipboardList,
} from "lucide-vue-next";
import { meals, type PrepPlan, type PrepTargets, type PrepMeal } from "@/api/client";
import { toLocalISO } from "@/dates";

const plan = ref<PrepPlan | null>(null);
// A null plan only means "no plan yet" once the server SAID so; a failed
// request used to fall through to the no-plan card (UI-6).
const planKnown = ref(false);
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
      meals.prepTargets().catch(() => null),
    ]);
    plan.value = p;
    planKnown.value = true;
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
    planKnown.value = true;
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

/** Component kind -> colour. Protein is magenta: it was a red that on this
 *  app means crisis, and a chicken breast is not an error. */
const KIND_COLOR: Record<string, string> = {
  protein: "#ff3ad8", grain: "#ffb52e", veg: "#5dff3b", sauce: "#6f7bff", other: "#9b9bb0",
};
const kindColor = (k: string) => KIND_COLOR[k] ?? KIND_COLOR.other;

/** Segmented ring: one arc per component, filled in its kind colour once
 *  ticked. Geometry only — the counts are the plan's own flags. */
const RING = 120, RSW = 10;
const segs = computed(() => {
  const comps = plan.value?.components ?? [];
  const n = Math.max(1, comps.length);
  const r = RING / 2 - RSW / 2 - 4;
  const c = 2 * Math.PI * r;
  const gap = n > 1 ? (10 / 360) * c : 0;
  const len = c / n - gap;
  return comps.map((cp, i) => ({
    id: cp.id, r, c, len,
    offset: -(i * (c / n) + gap / 2),
    color: cp.done ? kindColor(cp.kind) : "#272a3b",
    done: cp.done,
  }));
});

/** Week strip: planned / budget energy per day, both server values. */
function stripFrac(d: PrepPlan["schedule"][number]): number {
  if (d.planned_kcal == null || !d.budget_kcal) return 0;
  return Math.max(0, Math.min(1, d.planned_kcal / d.budget_kcal));
}

/** Per-meal fat verdict colour. Unknown is GREY, never green. */
function verdictColor(v: string | null | undefined): string {
  if (v === "ok") return "#5dff3b";
  if (v === "approaching") return "rgba(255, 181, 46, .7)";
  if (v === "high" || v === "very_high") return "#ffb52e";
  return "#9b9bb0";
}
function verdictText(v: string | null | undefined): string {
  switch (v) {
    case "ok": return "within your per-meal target";
    case "approaching": return "close to your per-meal target";
    case "high": return "over your per-meal target";
    case "very_high": return "well over your per-meal target";
    default: return "can't judge fat yet";
  }
}

function slotLabel(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

onMounted(load);
</script>

<template>
  <NeonPage title="Week prep" back="/meals/today">
    <template #trailing>
      <button class="icon-round" :disabled="loading" title="Refresh" @click="load"><RefreshCw :size="15" /></button>
    </template>

    <!-- Failed with nothing known: say so. Never the "no plan yet" card. -->
    <button v-if="!planKnown && error" class="fail" type="button" @click="load">
      <strong>Couldn't load your prep plan</strong>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>
    <p v-else-if="!planKnown" class="sub">Loading your prep plan…</p>

    <template v-else>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="notice" class="ok-note">{{ notice }}</p>

      <!-- ── No plan yet ──────────────────────────────────────── -->
      <div v-if="!plan" class="card">
        <h2 class="h2">No prep plan yet</h2>
        <p class="sub">
          Pick a few things to batch cook at the weekend and the week assembles
          itself from them. Nothing is fixed — you can skip a meal or eat out and
          the plan tells you what that leaves spare.
        </p>
        <div class="gen-form">
          <div class="seg">
            <button :class="{ on: draftDays === 5 }" @click="draftDays = 5">Mon–Fri</button>
            <button :class="{ on: draftDays === 7 }" @click="draftDays = 7">Mon–Sun</button>
          </div>
          <div class="lbl">Meals to plan</div>
          <div class="chips">
            <label v-for="s in ['breakfast', 'lunch', 'dinner', 'snack']" :key="s" class="chip" :class="{ on: draftSlots.includes(s) }">
              <input v-model="draftSlots" type="checkbox" :value="s" /> {{ slotLabel(s) }}
            </label>
          </div>
          <p class="sub">
            Whatever you leave out stays yours to sort out — the plan says so
            rather than showing the week as short of target.
          </p>
          <button class="primary" :disabled="generating || !draftSlots.length" @click="generate">
            <Sparkles :size="14" /> {{ generating ? "Planning…" : "Plan next week" }}
          </button>
        </div>
      </div>

      <!-- ── The plan ─────────────────────────────────────────── -->
      <template v-else>
        <NeonHero accent="#5dff3b">
          <div class="hero">
            <div class="seg-ring" :style="{ width: RING + 'px', height: RING + 'px' }">
              <svg :width="RING" :height="RING" aria-hidden="true">
                <circle v-if="!segs.length" :cx="RING / 2" :cy="RING / 2" :r="RING / 2 - RSW / 2 - 4" fill="none" stroke="#272a3b" :stroke-width="RSW" />
                <g :transform="`rotate(-90 ${RING / 2} ${RING / 2})`">
                  <circle v-for="s in segs" :key="s.id" :cx="RING / 2" :cy="RING / 2" :r="s.r" fill="none"
                          :stroke="s.color" :stroke-width="RSW" :stroke-dasharray="`${s.len} ${s.c}`"
                          :stroke-dashoffset="s.offset" :style="s.done ? { filter: `drop-shadow(0 0 4px ${s.color})` } : undefined" />
                </g>
              </svg>
              <div class="ring-in">
                <span class="big">{{ doneCount }} / {{ plan.components.length }}</span>
                <span class="cap">cooked</span>
              </div>
            </div>
            <div class="hero-side">
              <h2 class="h2">{{ plan.headline || "This week" }}</h2>
              <p class="sub">Week of {{ prettyDay(plan.start_day) }}</p>
              <div class="strip">
                <div v-for="d in plan.schedule.slice(0, 7)" :key="d.day" class="strip-col" :class="{ today: d.day === todayISO }"
                     :title="`${d.weekday}: ${d.planned_kcal ?? '—'} of ~${d.budget_kcal ?? '—'} kcal`">
                  <div class="strip-bar"><div class="strip-fill" :style="{ height: stripFrac(d) * 100 + '%' }" /></div>
                  <span>{{ d.weekday.slice(0, 1) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Warnings stay out in the open — time-sensitive and actionable. -->
          <p v-for="w in plan.warnings" :key="w" class="warn-line"><AlertTriangle :size="13" /> {{ w }}</p>

          <div class="actions">
            <button class="act cyan" :disabled="generating" @click="buildList"><ShoppingCart :size="14" /> {{ generating ? "Working…" : "Shopping list" }}</button>
            <button v-if="plan.notes || plan.budgets.uncovered_kcal" class="act" @click="showWhy = !showWhy">
              {{ showWhy ? "Hide reasoning" : "Why this plan" }}
            </button>
            <button class="act" @click="discard"><Trash2 :size="14" /> Delete</button>
          </div>
          <template v-if="showWhy">
            <p v-if="plan.budgets.uncovered_kcal" class="sub">
              These meals cover about {{ Math.round(plan.budgets.covered_share * 100) }}% of your day. The
              remaining ~{{ plan.budgets.uncovered_kcal }} kcal is whatever you eat outside them — it is not a shortfall.
            </p>
            <p v-if="plan.notes" class="notes">{{ plan.notes }}</p>
          </template>
        </NeonHero>

        <div class="seg big-seg">
          <button :class="{ on: tab === 'prep' }" @click="tab = 'prep'">Prep day</button>
          <button :class="{ on: tab === 'week' }" @click="tab = 'week'">The week</button>
        </div>

        <!-- ── Prep day ────────────────────────────────────────── -->
        <template v-if="tab === 'prep'">
          <button v-for="c in plan.components" :key="c.id" type="button" class="comp" :class="{ done: c.done }"
                  :style="{ '--k': kindColor(c.kind) }" :disabled="busy === c.id"
                  :aria-pressed="c.done" @click="toggleComponent(c.id, !c.done)">
            <span class="comp-body">
              <span class="kind">{{ c.kind }}</span>
              <b class="comp-name">{{ c.name }}</b>
              <span class="qty">
                {{ amount(c) }} · {{ c.portions }} portion{{ c.portions === 1 ? "" : "s" }}
                <template v-if="c.grams_per_portion"> · {{ Math.round(c.grams_per_portion) }} g each</template>
              </span>
              <span v-if="c.prep_note" class="prep-note">{{ c.prep_note }}</span>
              <span v-if="c.unresolved" class="uncostable">No nutrition for this one — {{ c.unresolved_reason }}.</span>
            </span>
            <span class="tick" :class="{ on: c.done }"><Check :size="15" /></span>
          </button>
          <p v-if="uncostable.length" class="sub">
            {{ uncostable.length }} component{{ uncostable.length === 1 ? "" : "s" }} could not be matched to a food,
            so the calorie and protein totals are partial rather than wrong.
          </p>
        </template>

        <!-- ── The week ────────────────────────────────────────── -->
        <template v-else>
          <div v-if="spares.length || shorts.length" class="card ledger">
            <NeonEyebrow>What is spare</NeonEyebrow>
            <ul>
              <li v-for="c in spares" :key="c.id"><b>{{ c.name }}</b> <span class="n">{{ c.spare }} portion{{ c.spare === 1 ? "" : "s" }} unclaimed</span></li>
              <li v-for="c in shorts" :key="`s${c.id}`" class="short">
                <b>{{ c.name }}</b> <span class="n">short {{ Math.abs(c.spare ?? 0) }} — a meal later in the week has nothing behind it</span>
              </li>
            </ul>
            <p class="sub">Spare portions are not a mistake. Move a meal to a later day, or freeze them.</p>
          </div>

          <div v-for="d in plan.schedule" :key="d.day" class="card day" :class="{ today: d.day === todayISO }">
            <div class="day-head">
              <div><b>{{ d.weekday }}</b><span class="date">{{ shortDay(d.day) }}</span></div>
              <span class="day-kcal">
                {{ d.planned_kcal == null ? "—" : `${d.planned_kcal} kcal` }}
                <small v-if="d.budget_kcal">of ~{{ d.budget_kcal }}</small>
              </span>
            </div>
            <p v-if="!d.meals.length" class="sub">Nothing planned.</p>
            <div v-for="m in d.meals" :key="m.id" class="meal" :class="m.status">
              <div class="meal-head">
                <span class="slot">{{ slotLabel(m.slot) }}</span>
                <b>{{ m.name }}</b>
                <span class="meal-kcal">{{ kcalOf(m) }}</span>
              </div>
              <p v-if="m.assembly_note" class="assembly">{{ m.assembly_note }}</p>
              <p class="macros">
                <span v-if="m.est_protein_g != null">{{ Math.round(m.est_protein_g) }} g protein</span>
                <span v-if="m.unresolved_count" class="partial">partial — {{ m.unresolved_count }} not costed</span>
              </p>
              <!-- The fat verdict on EVERY meal; grey when it can't be judged. -->
              <p class="fat" :style="{ color: verdictColor(m.fat_assessment?.verdict) }">
                <i class="dot" :style="{ background: verdictColor(m.fat_assessment?.verdict) }" />
                {{ m.est_fat_g != null ? `${Math.round(m.est_fat_g)} g fat` : "fat unknown" }} · {{ verdictText(m.fat_assessment?.verdict) }}
              </p>
              <div class="seg">
                <button :class="{ on: m.status === 'accepted' }" :disabled="busy === m.id" @click="setMealStatus(m, 'accepted')">Making this</button>
                <button :class="{ on: m.status === 'eating_out' }" :disabled="busy === m.id" @click="setMealStatus(m, 'eating_out')">Eating out</button>
                <button :class="{ on: m.status === 'skipped' }" :disabled="busy === m.id" @click="setMealStatus(m, 'skipped')">Skip</button>
              </div>
              <button class="act cyan full" :disabled="busy === m.id || !m.uses.length" @click="logMeal(m)">
                <ClipboardList :size="13" /> Log it
              </button>
            </div>
          </div>
        </template>

        <!-- ── Targets ───────────────────────────────────────── -->
        <div v-if="targets" class="card">
          <div v-if="targets.ok">
            <div class="t-main">
              <div class="t-num"><span class="big">{{ targets.override_kcal ?? targets.target_kcal }}</span><small>kcal a day</small></div>
              <div class="t-num"><span class="big">{{ targets.protein_g }}</span><small>g protein</small></div>
              <div v-if="targets.expected_loss_kg_per_week" class="t-num"><span class="big">{{ targets.expected_loss_kg_per_week }}</span><small>kg a week</small></div>
            </div>
            <p v-if="targets.weight_stale" class="warn-line">
              <AlertTriangle :size="13" />
              These are built on your weight from {{ targets.weight_measured_on }} — {{ targets.weight_age_days }} days ago.
              Everything above inherits that drift, and it will look perfectly consistent while being wrong.
            </p>
            <button class="link" @click="showTargets = !showTargets"><Info :size="12" /> {{ showTargets ? "Hide" : "How this was worked out" }}</button>
            <div v-if="showTargets" class="t-detail">
              <p v-if="targets.override_kcal" class="warn-line">
                You set {{ targets.override_kcal }} kcal by hand, so that is what plans are built against. The estimate below is for comparison.
              </p>
              <ul>
                <li><span>Resting burn ({{ targets.method }})</span><b>{{ targets.bmr_kcal }} kcal</b></li>
                <li><span>× {{ targets.activity_factor }} for {{ targets.activity_level }} activity</span><b>{{ targets.tdee_kcal }} kcal</b></li>
                <li v-if="targets.deficit_kcal"><span>− deficit to lose weight</span><b>{{ targets.deficit_kcal }} kcal</b></li>
                <li v-if="targets.protein_range_g">
                  <span>Protein, {{ targets.goal_weight_kg ? "scaled to your goal weight" : "scaled to bodyweight" }}</span>
                  <b>{{ targets.protein_range_g[0] }}–{{ targets.protein_range_g[1] }} g</b>
                </li>
              </ul>
              <p v-if="targets.hit_floor" class="warn-line">
                The full deficit would have taken this below a safe floor, so it was trimmed. The number above is the deficit actually applied.
              </p>
              <p class="caveat">{{ targets.caveat }}</p>
            </div>
          </div>
          <p v-else class="sub">{{ targets.reason }}</p>
        </div>

        <button class="act full" :disabled="generating" @click="generate">
          <Sparkles :size="14" /> {{ generating ? "Planning…" : "Plan a different week" }}
        </button>
        <p class="sub">Replaces the plan for that week. Anything you have already ticked off or logged stays where it is.</p>
      </template>
    </template>
  </NeonPage>
</template>

<style scoped>
.err { color: #ffb52e; font-size: 13px; }
.ok-note { color: #5dff3b; font-size: 13px; }
.sub { margin: 6px 0 0; font-size: 12px; color: var(--rn-mut); line-height: 1.5; }
.caveat { margin: 8px 0 0; font-size: 11px; color: var(--rn-mut); line-height: 1.5; }
.h2 { margin: 0; font-size: 16px; font-weight: 700; }
.card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; margin-bottom: 10px; }
.fail { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 181, 46, .08); border: 1px solid rgba(255, 181, 46, .3); border-radius: 14px; padding: 12px 14px;
  color: var(--rn-mut); font: inherit; font-size: 12px; margin-bottom: 12px; }
.fail strong { color: #ffb52e; font-size: 13px; }
.fail em { font-style: normal; color: #28e6ff; font-weight: 600; }
.icon-round { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--rn-line); background: var(--rn-card); color: var(--rn-ink);
  display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.hero { display: flex; align-items: center; gap: 14px; }
.seg-ring { position: relative; flex: 0 0 auto; }
.seg-ring svg { display: block; overflow: visible; }
.ring-in { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.big { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 22px; color: var(--rn-ink); }
.cap { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); }
.hero-side { flex: 1; min-width: 0; }
.strip { display: flex; gap: 4px; height: 44px; margin-top: 8px; }
.strip-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 9px; color: var(--rn-mut); }
.strip-bar { flex: 1; width: 12px; border-radius: 3px; background: var(--rn-track); display: flex; align-items: flex-end; overflow: hidden; }
.strip-fill { width: 100%; background: rgba(93, 255, 59, .7); }
.strip-col.today { color: #28e6ff; }
.strip-col.today .strip-fill { background: #28e6ff; }
.warn-line { display: flex; align-items: flex-start; gap: 6px; margin: 8px 0 0; font-size: 12px; color: #ffb52e; line-height: 1.5; }
.notes { margin: 8px 0 0; font-size: 12px; color: var(--rn-mut); line-height: 1.55; white-space: pre-line; }
.actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.act { flex: 1; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border-radius: 12px;
  border: 1px solid var(--rn-line); background: transparent; color: var(--rn-mut); font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; padding: 0 10px; }
.act.cyan { color: #28e6ff; border-color: rgba(40, 230, 255, .45); }
.act.full { width: 100%; margin-top: 8px; }
.act:disabled { opacity: .5; cursor: default; }
.seg { display: flex; height: 44px; border: 1px solid var(--rn-line); border-radius: 12px; overflow: hidden; background: var(--rn-card); margin-top: 8px; }
.seg button { flex: 1; border: 0; background: transparent; color: var(--rn-ink); font: inherit; font-size: 12px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--rn-line); }
.seg button.on { background: rgba(93, 255, 59, .14); color: #5dff3b; font-weight: 600; }
.seg button:disabled { color: var(--rn-mut); cursor: default; }
.big-seg { margin: 4px 0 10px; }
.gen-form { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.lbl { font-size: 11px; color: var(--rn-mut); }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { min-height: 44px; display: inline-flex; align-items: center; gap: 6px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--rn-track);
  color: var(--rn-mut); font-size: 12px; cursor: pointer; }
.chip.on { border-color: #5dff3b; color: #5dff3b; }
.chip input { accent-color: #5dff3b; }
.primary { min-height: 48px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 14px;
  background: #28e6ff; color: var(--rn-onacc); font: inherit; font-weight: 700; cursor: pointer; }
.primary:disabled { opacity: .5; cursor: default; }
.link { display: inline-flex; align-items: center; gap: 4px; background: none; border: 0; color: #28e6ff; cursor: pointer; font: inherit;
  font-size: 12px; padding: 0; margin-top: 8px; min-height: 32px; }
.comp { position: relative; display: flex; align-items: flex-start; gap: 10px; width: 100%; min-height: 64px; text-align: left; margin-bottom: 10px;
  background: var(--rn-card); border: 0; border-radius: 18px; padding: 12px 12px 12px 19px; color: var(--rn-ink); font: inherit; cursor: pointer; overflow: hidden; }
.comp::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 5px; background: var(--k); opacity: .55; }
.comp.done::before { opacity: 1; }
.comp:disabled { cursor: default; }
.comp-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.kind { font-size: 9px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--k); }
.comp-name { font-size: 14px; font-weight: 500; }
.comp.done .comp-name { color: var(--rn-mut); }
.qty { font-size: 12px; color: var(--rn-mut); font-variant-numeric: tabular-nums; }
.prep-note { font-size: 12px; line-height: 1.5; margin-top: 2px; }
.uncostable { font-size: 11px; color: #ffb52e; }
.tick { flex: none; width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--rn-track); color: transparent; display: grid; place-items: center; }
.tick.on { background: var(--k); border-color: var(--k); color: var(--rn-onacc); }
.ledger ul { list-style: none; margin: 0; padding: 0; }
.ledger li { display: flex; gap: 8px; align-items: baseline; padding: 3px 0; font-size: 13px; flex-wrap: wrap; }
.ledger .n { color: var(--rn-mut); font-size: 12px; }
.ledger li.short .n { color: #ffb52e; }
.day.today { border-color: #28e6ff; }
.day-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.day.today .day-head b { color: #28e6ff; }
.day-head .date { margin-left: 8px; font-size: 11px; color: var(--rn-mut); }
.day-kcal { font-size: 12px; font-variant-numeric: tabular-nums; }
.day-kcal small { color: var(--rn-mut); font-size: 11px; margin-left: 3px; }
.meal { margin-top: 14px; }
.meal.eating_out .meal-head b, .meal.skipped .meal-head b { color: var(--rn-mut); }
.meal-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.slot { font-size: 9px; text-transform: uppercase; letter-spacing: .08em; color: var(--rn-mut); }
.meal-kcal { margin-left: auto; font-size: 12px; color: var(--rn-mut); font-variant-numeric: tabular-nums; }
.assembly { margin: 4px 0 0; font-size: 12px; line-height: 1.5; color: var(--rn-mut); }
.macros { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 0; font-size: 11px; color: var(--rn-mut); }
.macros .partial { color: #ffb52e; }
.fat { display: flex; align-items: center; gap: 6px; margin: 4px 0 0; font-size: 11px; }
.fat .dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.t-main { display: flex; gap: 24px; flex-wrap: wrap; }
.t-num { display: flex; flex-direction: column; }
.t-num small { font-size: 11px; color: var(--rn-mut); }
.t-detail ul { list-style: none; margin: 8px 0 0; padding: 0; }
.t-detail li { display: flex; justify-content: space-between; gap: 16px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--rn-line); }
.t-detail li span { color: var(--rn-mut); }
</style>
