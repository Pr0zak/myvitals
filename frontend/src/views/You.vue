<script setup lang="ts">
/**
 * You — the personal hub. Phone twin: `YouScreen.kt`.
 *
 *   title   "You", with the profile summary as a subtitle
 *   hero    habits: the active fast as a ring (elapsed of target, stage,
 *           when it ends) beside the sober count
 *   goals   up to three small rings, coloured by the SERVER's state_tone
 *   grid    Journal, Coach, Meals, Sober, Fasting, Settings
 *
 * Failure is not absence (UX-F2). Every request is settled separately and
 * a section only makes a claim about the user — "Not fasting", "No active
 * goals yet", "Start counting" — when its own request succeeded. When all
 * of them fail the page says so, with a retry, and shows nothing else but
 * the navigation.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, type FastingSessionOut } from "@/api/client";
import { goalTone, goalStateNote } from "@/goalState";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import {
  Brain, ChefHat, Hourglass, Package, PencilLine, Salad, Settings, Timer, UtensilsCrossed,
} from "lucide-vue-next";

const router = useRouter();
const loading = ref(true);
const error = ref<string | null>(null);

type Sober = Awaited<ReturnType<typeof api.soberCurrent>>;
type Profile = Awaited<ReturnType<typeof api.getProfile>>;

interface GoalProjection {
  per_day: number | null;
  per_week: number | null;
  eta_date: string | null;
  eta_days: number | null;
  confidence: "high" | "medium" | "low" | null;
  is_fallback: boolean;
  fallback_reason: string | null;
  method: string;
}

interface GoalRow {
  id: number;
  kind: string;
  title: string;
  target_value: number | null;
  target_unit: string | null;
  current_value?: number | null;
  /** Server progress, rendered verbatim. Null = no reading, never 0. */
  progress_pct?: number | null;
  /** GOAL-STATE: "achieved" | "advancing" | "at_start" | "moved_away" |
   *  "no_data". A 0% ring cannot tell the last three apart. */
  progress_state?: string | null;
  /** Server-owned tone. Never derived here — see `goalState.ts`. */
  state_tone?: string | null;
  /** Signed, in the goal's own unit; exactly current - baseline. */
  delta_value?: number | null;
  baseline_value?: number | null;
  projection?: GoalProjection | null;
}

// Each section: undefined = never answered; null (fasting) = answered "none".
const fasting = ref<FastingSessionOut | null | undefined>(undefined);
const sober = ref<Sober | undefined>(undefined);
const goals = ref<GoalRow[] | undefined>(undefined);
const profile = ref<Profile | undefined>(undefined);

const today = new Date().toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });

async function load(): Promise<void> {
  loading.value = true;
  const [f, s, g, p] = await Promise.allSettled([
    api.fastingCurrent(), api.soberCurrent(), api.aiGoals(true), api.getProfile(),
  ]);
  if (f.status === "fulfilled") fasting.value = f.value;
  if (s.status === "fulfilled") sober.value = s.value;
  if (g.status === "fulfilled") goals.value = (g.value ?? []) as GoalRow[];
  if (p.status === "fulfilled") profile.value = p.value;
  const allFailed = [f, s, g, p].every((r) => r.status === "rejected");
  error.value = allFailed ? "Couldn't reach the backend." : null;
  loading.value = false;
}
onMounted(load);

const nothingKnown = computed(() =>
  fasting.value === undefined && sober.value === undefined
  && goals.value === undefined && profile.value === undefined,
);

// ── Profile subtitle ────────────────────────────────────────────────────
const profileLine = computed<string | null>(() => {
  const p = profile.value;
  if (!p) return null;
  const parts: string[] = [];
  if (p.derived?.age != null) parts.push(`${p.derived.age} yrs`);
  if (p.sex) parts.push(p.sex[0].toUpperCase() + p.sex.slice(1));
  if (p.height_cm != null) {
    const inches = Math.round(p.height_cm / 2.54);
    parts.push(`${Math.floor(inches / 12)}'${inches % 12}"`);
  }
  if (p.activity_level) parts.push(p.activity_level.replace(/_/g, " "));
  // A sentence, not a " · " string: "41 yrs, male, 5'11", moderately active".
  if (!parts.length) return "Add your details in Settings";
  const line = parts.map((x, i) => (i ? x.toLowerCase() : x)).join(", ");
  return line[0].toUpperCase() + line.slice(1);
});

// ── Fasting ─────────────────────────────────────────────────────────────
const STAGE_LABELS: Record<string, string> = {
  fed: "Fed state", gut_rest: "Gut rest", glycogen_depleting: "Glycogen depleting",
  ketosis: "Ketosis", autophagy: "Autophagy", deep_autophagy: "Deep autophagy",
  extended_36: "36h territory", extended_48: "48h territory", extended_72: "72h+ territory",
};
const activeFast = computed(() => (fasting.value?.is_active ? fasting.value : null));
/** elapsed / target, both from /fasting/current. No target, no fraction —
 *  the ring stays empty rather than assume 16h. */
/** UI-F5: a tick at each server-sent stage threshold inside the target —
 *  the same stages the Fasting ring marks. None without a target. */
const fastTicks = computed<number[]>(() => {
  const f = activeFast.value;
  const t = f?.target_hours;
  if (!f || !t || t <= 0) return [];
  return (f.stages ?? []).map((st) => st.at_h / t).filter((x) => x > 0 && x < 1);
});
const fastFrac = computed(() => {
  const f = activeFast.value;
  return f && f.target_hours ? f.elapsed_h / f.target_hours : 0;
});
function trim(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
const fastEnds = computed<string | null>(() => {
  const f = activeFast.value;
  if (!f || f.target_hours == null) return null;
  const end = new Date(Date.parse(f.started_at) + f.target_hours * 3600_000);
  if (Number.isNaN(end.getTime())) return null;
  const clock = end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return f.elapsed_h >= f.target_hours ? `target reached ${clock}` : `ends ${clock}`;
});
const stageLabel = computed(() => {
  const s = activeFast.value?.current_stage ?? "";
  return STAGE_LABELS[s] ?? s.replace(/_/g, " ");
});

// ── Sober ───────────────────────────────────────────────────────────────
const soberDays = computed<number | null>(() => {
  const s = sober.value;
  if (!s?.active) return null;
  return s.days ?? Math.floor(s.active.days);
});
const soberSince = computed<string | null>(() => {
  const iso = sober.value?.active?.start_at;
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return "since " + d.toLocaleDateString(undefined,
    sameYear ? { month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" });
});

// ── Goals as rings ──────────────────────────────────────────────────────
const topGoals = computed(() => (goals.value ?? []).slice(0, 3));
/**
 * Colour from the server's `state_tone`, NEVER from list position — the
 * old bars cycled cyan/magenta/lime by index, so a regressing goal could
 * wear an achievement colour by sorting first. Fill is `progress_pct`
 * verbatim; null is an empty ring that says so. No current/target
 * fallback: for a weight goal approached from above that ratio exceeds 1
 * and painted a FULL bar on the goal doing worst (GOAL-STATE).
 */
function ringColor(g: GoalRow): string {
  if (g.progress_pct == null) return "#272a3b";
  switch (goalTone(g)) {
    case "positive": return "#5dff3b";
    case "caution": return "#ffb52e";
    case "unknown": return "#272a3b";
    default: return "#9b9bb0";
  }
}
function ringNote(g: GoalRow): string | null {
  return g.progress_pct == null ? "no reading yet" : goalStateNote(g);
}

// ── Navigation ──────────────────────────────────────────────────────────
const TILES = [
  { label: "Journal", icon: PencilLine, tint: "#ff3ad8", to: "/journal" },
  { label: "Coach", icon: Brain, tint: "#6f7bff", to: "/coach" },
  { label: "Meals", icon: UtensilsCrossed, tint: "#5dff3b", to: "/meals" },
  { label: "Sober", icon: Timer, tint: "#ff3ad8", to: "/sober" },
  { label: "Fasting", icon: Hourglass, tint: "#28e6ff", to: "/fasting" },
  { label: "Settings", icon: Settings, tint: "#ffb52e", to: "/settings" },
];
/* SA-R3/SA-R4: these three meal pages are reachable from no other neon
   page (the Meals landing does not link them), so they stay here as small
   chips under the grid rather than disappear with the old pill list. */
const MEAL_LINKS = [
  { label: "Pantry", icon: Package, to: "/meals/pantry" },
  { label: "Cook from pantry", icon: Salad, to: "/meals/can-make" },
  { label: "Weekend prep", icon: ChefHat, to: "/meals/prep" },
];
function go(path: string): void {
  router.push(path);
}
</script>

<template>
  <NeonPage title="You">
    <template #trailing><span class="date">{{ today }}</span></template>
    <p v-if="profileLine" class="sub">{{ profileLine }}</p>

    <template v-if="nothingKnown">
      <div v-if="loading" class="skel" aria-busy="true">
        <div class="sk-row"><div class="sk tall"><span>Fasting</span></div><div class="sk tall mag"><span>Sober</span></div></div>
        <div class="sk-row three"><div class="sk lime"><span>Goals</span></div><div class="sk lime"></div><div class="sk lime"></div></div>
      </div>
      <!-- UX-F2: say it failed — no "Not fasting", no "No active goals". -->
      <button v-else-if="error" class="errbar" @click="load">
        <b>Couldn't load</b><span>{{ error }}</span><em>Tap to retry</em>
      </button>
    </template>

    <template v-else>
      <!-- Hero on the page ground, in the Today brief's language: two
           blocks side by side, separated by space rather than a card. -->
      <section class="habits">
        <button class="half" aria-label="Fasting detail" @click="go('/fasting')">
          <span class="lab"><span class="bar cyanbg" />Fasting</span>
          <NeonRing :fraction="fastFrac" color="#28e6ff" :size="140" :stroke="12" :ticks="fastTicks">
            <template v-if="activeFast">
              <!-- "14.3h" over "of 16h" — never "14:16", which reads as a clock. -->
              <div class="rv">{{ activeFast.elapsed_h.toFixed(1) }}h</div>
              <div class="rc">{{ activeFast.target_hours != null ? `of ${trim(activeFast.target_hours)}h` : "no target" }}</div>
            </template>
            <div v-else class="rv mut">—</div>
          </NeonRing>
          <template v-if="activeFast">
            <span class="stage">{{ stageLabel }}</span>
            <span v-if="fastEnds" class="small">{{ fastEnds[0].toUpperCase() + fastEnds.slice(1) }}</span>
          </template>
          <!-- Only a SUCCESSFUL "no active fast" may say this. -->
          <template v-else-if="fasting === null || (fasting && !fasting.is_active)">
            <span class="small">Not fasting</span>
            <span class="pill">Start a fast</span>
          </template>
          <span v-else class="small">Couldn't load</span>
        </button>
        <button class="half" aria-label="Sober detail" @click="go('/sober')">
          <span class="lab"><span class="bar magbg" />Sober</span>
          <span class="bigbox">
            <template v-if="soberDays != null">
              <!-- Ink, not a warning colour: the count is never a warning,
                   and a reset is never one either. The magenta bar carries
                   the identity. -->
              <b class="big">{{ soberDays }}</b>
              <span class="unit">{{ soberDays === 1 ? "day" : "days" }}</span>
            </template>
            <b v-else class="big mut">—</b>
          </span>
          <span v-if="soberDays != null && soberSince" class="small">{{ soberSince[0].toUpperCase() + soberSince.slice(1) }}</span>
          <span v-else-if="soberDays == null && sober" class="pill">Start counting</span>
          <span v-else-if="soberDays == null" class="small">Couldn't load</span>
        </button>
      </section>

      <div class="ghead">
        <h2 class="sect">Goals</h2>
        <button class="gall" @click="go('/goals')">See all goals</button>
      </div>
      <p v-if="goals === undefined" class="note">Couldn't load goals</p>
      <p v-else-if="!goals.length" class="note">No active goals yet</p>
      <div v-else class="goals">
        <div v-for="g in topGoals" :key="g.id" class="goal">
          <NeonRing :fraction="(g.progress_pct ?? 0) / 100" :color="ringColor(g)" :size="72" :stroke="7">
            <div class="gp" :class="{ mut: g.progress_pct == null }">
              {{ g.progress_pct != null ? Math.round(g.progress_pct) + "%" : "—" }}
            </div>
          </NeonRing>
          <div class="gt">{{ g.title }}</div>
          <div v-if="ringNote(g)" class="gn"
               :class="{ away: goalTone(g) === 'caution' && g.progress_pct != null }">{{ ringNote(g) }}</div>
        </div>
      </div>
    </template>

    <h2 class="sect">More</h2>
    <div class="tiles">
      <button v-for="t in TILES" :key="t.to" class="tile" @click="go(t.to)">
        <span class="ti" :style="{ color: t.tint }">
          <component :is="t.icon" :size="19" />
        </span>
        <span>{{ t.label }}</span>
      </button>
    </div>
    <div class="mlinks">
      <button v-for="m in MEAL_LINKS" :key="m.to" class="mlink" @click="go(m.to)">
        <component :is="m.icon" :size="14" /> {{ m.label }}
      </button>
    </div>
  </NeonPage>
</template>

<style scoped>
.date { color: #9b9bb0; font-weight: 600; font-size: 14px; }
.sub { margin: -12px 0 18px; font-size: 13px; color: rgba(236, 236, 245, .85); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.mut { color: #9b9bb0; }

.habits { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; margin: 4px 0 26px;
  max-width: 640px; }
.half { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
  background: none; border: 0; padding: 0; cursor: pointer; color: inherit; font: inherit; text-align: left;
  border-radius: 12px; }
.half:focus-visible, .tile:focus-visible, .mlink:focus-visible { outline: 2px solid #28e6ff; outline-offset: 3px; }
.lab { display: inline-flex; align-items: center; gap: 8px; font-size: .75rem; color: #9b9bb0; }
.bar { width: 3px; height: 14px; border-radius: 2px; }
.cyanbg { background: #28e6ff; } .magbg { background: #ff3ad8; }
.rv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 500; font-size: 1.7rem;
  letter-spacing: -.5px; color: #ececf5; font-variant-numeric: tabular-nums; text-align: center; }
.rc { font-size: .7rem; color: #9b9bb0; text-align: center; }
.stage { font-size: .9rem; font-weight: 600; max-width: 100%; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.small { font-size: .72rem; color: #9b9bb0; }
.bigbox { display: flex; align-items: baseline; gap: 6px; height: 140px; padding-top: 30px; }
.big { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 500; font-size: 3.6rem; line-height: 1;
  letter-spacing: -2px; color: #ececf5; font-variant-numeric: tabular-nums; }
.unit { font-size: .9rem; color: #9b9bb0; }
.pill { display: inline-block; background: #28e6ff; color: #06121a; font-size: .78rem; font-weight: 600;
  padding: 6px 14px; border-radius: 999px; }

.sect { font-size: 1.1rem; font-weight: 500; color: #ececf5; margin: 0 0 10px; letter-spacing: -.1px; }
.ghead { display: flex; align-items: baseline; justify-content: space-between; }
.gall { font-size: .78rem; font-weight: 500; color: #28e6ff; background: none; border: 0; padding: 0; cursor: pointer; }
.note { color: #9b9bb0; font-size: 13px; margin: 0 0 4px; }
.goals { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 26px; }
.goal { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px;
  background: #181b27; border-radius: 20px; padding: 14px 8px; }
.gp { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 500; font-size: 16px; }
.gt { font-size: 12px; font-weight: 600; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.gn { font-size: 10.5px; color: #9b9bb0; line-height: 1.25; }
.gn.away { color: #ffb52e; }

.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.tile { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 16px 4px;
  background: #181b27; border: 0; border-radius: 20px; cursor: pointer; color: #ececf5;
  font: inherit; font-size: 13px; font-weight: 500; }
.tile:active { transform: scale(.97); }
.ti { width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; }
.mlinks { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.mlink { display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12px; color: #9b9bb0;
  background: #181b27; border: 0; border-radius: 999px; padding: 7px 12px; cursor: pointer; }

.errbar { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 93, 122, .10); border: 1px solid rgba(255, 93, 122, .28); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: inherit; font: inherit; }
.errbar b { color: #ff5d7a; font-size: 13px; }
.errbar span { color: #9b9bb0; font-size: 12px; }
.errbar em { color: #28e6ff; font-size: 12px; font-style: normal; font-weight: 600; }

.skel { display: flex; flex-direction: column; gap: 10px; }
.sk-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.sk-row.three { grid-template-columns: repeat(3, 1fr); }
.sk { height: 140px; border-radius: 20px; position: relative; overflow: hidden;
  --c: rgba(40, 230, 255, .12);
  background: linear-gradient(90deg, rgba(31,41,55,.5), var(--c), rgba(31,41,55,.5));
  background-size: 300% 100%; animation: sweep 1.4s linear infinite; }
.sk.tall { height: 200px; }
.sk.mag { --c: rgba(255, 58, 216, .12); }
.sk.lime { --c: rgba(93, 255, 59, .12); }
.sk span { position: absolute; top: 14px; left: 14px; font-size: 12px; color: #9b9bb0; }
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
