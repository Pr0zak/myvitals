<script setup lang="ts">
/**
 * You — the personal hub. Phone twin: `YouScreen.kt`.
 *
 *   title   "You", with the profile summary as a subtitle
 *   hero    habits: the active fast as a ring (elapsed of target, stage,
 *           when it ends) beside the sober count
 *   goals   up to three small rings, coloured by the SERVER's state_tone
 *   grid    Journal · Coach · Meals · Sober · Fasting · Settings
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
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
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
  return parts.length ? parts.join(" · ") : "Add your details in Settings";
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
      <NeonHero accent="#28e6ff">
        <div class="habits">
          <button class="half" aria-label="Fasting detail" @click="go('/fasting')">
            <span class="eyebrow cyan">Fasting</span>
            <NeonRing :fraction="fastFrac" color="#28e6ff" :size="112" :stroke="9" :ticks="fastTicks">
              <template v-if="activeFast">
                <!-- "14.3h" over "OF 16H" — never "14:16", which reads as a clock. -->
                <div class="rv">{{ activeFast.elapsed_h.toFixed(1) }}h</div>
                <div class="rc">{{ activeFast.target_hours != null ? `of ${trim(activeFast.target_hours)}h` : "no target" }}</div>
              </template>
              <div v-else class="rv mut">—</div>
            </NeonRing>
            <template v-if="activeFast">
              <span class="stage">{{ stageLabel }}</span>
              <span v-if="fastEnds" class="small">{{ fastEnds }}</span>
            </template>
            <!-- Only a SUCCESSFUL "no active fast" may say this. -->
            <span v-else-if="fasting === null || (fasting && !fasting.is_active)" class="cta cyan">Not fasting · Start</span>
            <span v-else class="small">Couldn't load</span>
          </button>
          <div class="divider"></div>
          <button class="half" aria-label="Sober detail" @click="go('/sober')">
            <span class="eyebrow mag">Sober</span>
            <template v-if="soberDays != null">
              <!-- Magenta always: the count is never a warning colour, and a
                   reset is never one either. -->
              <b class="big mag">{{ soberDays }}</b>
              <span class="small">{{ soberDays === 1 ? "day" : "days" }}</span>
              <span v-if="soberSince" class="small since">{{ soberSince }}</span>
            </template>
            <template v-else-if="sober">
              <b class="big mut">—</b>
              <span class="cta">Start counting</span>
            </template>
            <template v-else>
              <b class="big mut">—</b>
              <span class="small">Couldn't load</span>
            </template>
          </button>
        </div>
      </NeonHero>

      <div class="ghead">
        <NeonEyebrow>Goals</NeonEyebrow>
        <button class="gall" @click="go('/goals')">All ›</button>
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

    <NeonEyebrow>More</NeonEyebrow>
    <div class="tiles">
      <button v-for="t in TILES" :key="t.to" class="tile" @click="go(t.to)">
        <span class="ti" :style="{ color: t.tint, background: `color-mix(in srgb, ${t.tint} 14%, transparent)` }">
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
.sub { margin: -12px 0 14px; font-size: 12px; color: #9b9bb0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.cyan { color: #28e6ff; } .mag { color: #ff3ad8; } .mut { color: #9b9bb0; }

.habits { display: flex; align-items: stretch; }
.half { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 6px;
  background: none; border: 0; padding: 0; cursor: pointer; color: inherit; font: inherit; text-align: center; }
.divider { width: 1px; background: #23263a; margin: 6px 12px; }
.eyebrow { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase; margin-bottom: 2px; }
.rv { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 22px; color: #ececf5; }
.rc { font-size: 9px; font-weight: 700; letter-spacing: .12em; color: #9b9bb0; text-transform: uppercase; }
.stage { font-size: 13px; font-weight: 700; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: 11px; color: #9b9bb0; }
.since { margin-top: 6px; }
.cta { font-size: 12px; font-weight: 600; }
.big { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 44px; line-height: 1;
  margin-top: 14px; font-variant-numeric: tabular-nums; }

.ghead { display: flex; align-items: baseline; justify-content: space-between; }
.gall { font-size: 11px; font-weight: 700; color: #28e6ff; background: none; border: 0; padding: 0; cursor: pointer; }
.note { color: #9b9bb0; font-size: 13px; margin: 0 0 4px; }
.goals { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.goal { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px;
  background: #181b27; border: 1px solid #23263a; border-radius: 18px; padding: 12px 8px; }
.gp { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 16px; }
.gt { font-size: 12px; font-weight: 700; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.gn { font-size: 10.5px; color: #9b9bb0; line-height: 1.25; }
.gn.away { color: #ffb52e; }

.tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.tile { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 14px 4px;
  background: #181b27; border: 1px solid #23263a; border-radius: 18px; cursor: pointer; color: #ececf5;
  font: inherit; font-size: 13px; font-weight: 600; }
.tile:active { transform: scale(.97); }
.ti { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.mlinks { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.mlink { display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12px; color: #9b9bb0;
  background: #181b27; border: 1px solid #23263a; border-radius: 999px; padding: 6px 12px; cursor: pointer; }

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
