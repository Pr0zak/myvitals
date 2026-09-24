<script setup lang="ts">
/**
 * Train — neon training hub (UI-1). Mirrors the phone's `TrainHubScreen.kt`:
 *
 *   1. Session hero: sets ring (outer arc = exercises), split, muscle chips,
 *      a full-width Continue button naming the next slot, Mon–Sun dots.
 *   2. This week's volume as seven columns with last week's same weekday
 *      ghosted behind — totals, change and its direction from `/stats.week`.
 *   3. Working sets per muscle against its MEV–MAV band (`/muscle-volume`).
 *   4. This year, the activity calendar, the recent feed and a tile grid.
 *
 * Every number the page shows about training is the server's. A failed
 * request raises a banner and suppresses the empty states that would
 * otherwise speak for it (UX-F1) — a dead backend is not a rest day.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api, activitiesYtd } from "@/api/client";
import ActivityYearCalendar from "@/components/ActivityYearCalendar.vue";
import ActivityIcon from "@/components/ActivityIcon.vue";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonRing from "@/components/neon/NeonRing.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import { fmtDistance, distanceVal, distanceUnit, fmtElevation } from "@/units";
import type { ActivityYtd, YtdMetric,
  Activity, ActivityStats, StrengthWorkoutDetail, StrengthWeekVolume,
} from "@/api/types";

const router = useRouter();
const loading = ref(true);
const error = ref<string | null>(null);

const LIME = "#5dff3b";
const CYAN = "#28e6ff";

type MuscleRow = { sets: number; mev: number; mav: number;
  status: "untrained" | "under" | "in_range" | "over" };

const workout = ref<StrengthWorkoutDetail | null>(null);
/** CONS-1: server-computed streaks + frequency; see analytics/consistency.py. */
const stats = ref<ActivityStats | null>(null);
const week = ref<StrengthWeekVolume | null>(null);
const strengthSessions7d = ref<number | null>(null);
const muscles = ref<Record<string, MuscleRow> | null>(null);
const muscleWindow = ref(7);
const activities = ref<Activity[]>([]);
const workouts = ref<Array<{ date: string; status?: string | null;
  split_focus?: string | null; completed_at?: string | null }>>([]);
/** OG3-A2: the generator-authoritative forecast, for the week dots. */
const upcoming = ref<Array<{ date: string; split_focus: string;
  exercise_count: number }>>([]);

/** Jan 1 of LAST year — the YTD pair compares against the same span a year
 *  ago, so the fetch has to reach back that far. */
function ytdSince(): string {
  return new Date(Date.UTC(new Date().getFullYear() - 1, 0, 1)).toISOString();
}

const FAILED = Symbol("failed");
async function settle<T>(p: Promise<T>): Promise<T | typeof FAILED> {
  try { return await p; } catch { return FAILED; }
}

async function load(): Promise<void> {
  loading.value = true;
  const [w, acts, wkts, st, up, ss, mv, yt] = await Promise.all([
    settle(api.strengthToday()),
    settle(api.activities({ limit: 2000, since: ytdSince() })),
    settle(api.strengthWorkouts({ limit: 400 })),
    settle(api.activitiesStats(30)),
    settle(api.strengthUpcoming(7, 4)),
    settle(api.strengthStats(30)),
    settle(api.strengthMuscleVolume(7)),
    settle(activitiesYtd()),
  ]);
  const failed: string[] = [];
  if (w === FAILED) failed.push("today's plan"); else workout.value = w ?? null;
  if (acts === FAILED) failed.push("activities");
  else activities.value = Array.isArray(acts) ? acts : [];
  if (wkts === FAILED) failed.push("workouts");
  else workouts.value = ((wkts as any)?.workouts ?? [])
    .filter((x: any) => !["regenerated", "planned", "skipped"].includes(x.status))
    .filter((x: any) => !(x.split_focus === "cardio" && x.completed_by_activity_source));
  if (st !== FAILED) stats.value = st;
  if (up !== FAILED) upcoming.value = up?.upcoming ?? [];
  if (ss === FAILED) failed.push("volume");
  else {
    week.value = ss.week ?? null;
    strengthSessions7d.value = ss.consistency?.sessions_last_7d ?? null;
  }
  if (mv !== FAILED) { muscles.value = mv.muscles; muscleWindow.value = mv.window_days; }
  if (yt !== FAILED) ytdData.value = yt;
  error.value = failed.length ? `Couldn't load ${failed.join(", ")}.` : null;
  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}

function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").split(" ").filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/** The user's LOCAL calendar date for a Date, as YYYY-MM-DD. */
function localISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
/** A plain YYYY-MM-DD as a local Date — never `new Date(iso)`, which is UTC
 *  midnight and names the previous day in Central. */
function parseDay(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

// ── This-week pill (CONS-1: the server's count) ─────────────────────────
const weekCount = computed<number | null>(() => stats.value?.consistency?.sessions_last_7d ?? null);

// ── Hero ────────────────────────────────────────────────────────────────
const isRest = computed(() => workout.value == null || /rest/i.test(workout.value.split_focus ?? ""));
const setsDone = computed(() => workout.value?.sets_done ?? 0);
const setsTotal = computed(() => workout.value?.sets_total ?? 0);
const exDone = computed(() => workout.value?.exercises_done ?? 0);
const exTotal = computed(() => workout.value?.exercises_total ?? 0);

const heroTag = computed(() => {
  const w = workout.value;
  if (w?.status === "completed") return "Today · done";
  if (w?.status === "skipped") return "Today · skipped";
  if (exTotal.value === 1) return "Today · 1 exercise";
  if (exTotal.value > 1) return `Today · ${exTotal.value} exercises`;
  return "Today";
});

/** The plan's muscles: projection rows today's plan adds to. */
const chips = computed<string[]>(() => {
  const p = workout.value?.projected_muscle_volume ?? {};
  return Object.entries(p)
    .filter(([, r]) => (r.sets_planned ?? 0) > 0)
    .sort((a, b) => (b[1].sets_planned ?? 0) - (a[1].sets_planned ?? 0))
    .map(([m]) => m)
    .slice(0, 5);
});

/** OG3-A1 — the button reads the session's own status, never only its
 *  focus, so a finished workout cannot present as outstanding. The next
 *  slot comes from the server's `next_up`, decided by the same predicates
 *  as the progress counters. Mirrors `heroCta` in TrainHubScreen.kt. */
const cta = computed<{ label: string; muted: boolean; name?: string; suffix?: string }>(() => {
  const w = workout.value;
  if (w == null) return { label: "View", muted: true };
  if (w.status === "completed") return { label: "Done · see review", muted: true };
  if (w.status === "skipped") return { label: "Skipped · view", muted: true };
  if (isRest.value) return { label: "View", muted: true };
  const n = w.next_up;
  if (n && n.started) return { label: "Continue", muted: false, name: n.name, suffix: `, set ${n.set_number}` };
  if (n) return { label: "Start", muted: false };
  if (w.status === "in_progress" || w.status === "paused") return { label: "Resume", muted: false };
  return { label: "Start", muted: false };
});

/** Per-muscle accent. Never rose — rose is the crisis colour. */
function muscleColor(m: string): string {
  switch (m.toLowerCase()) {
    case "chest": case "biceps": case "forearms": return "var(--rn-mag)";
    case "back": case "lats": case "middle back": case "lower back": case "traps": return "var(--rn-cyan)";
    case "shoulders": case "abdominals": case "abs": case "core": return "var(--rn-amber)";
    case "triceps": return "var(--rn-peri)";
    case "quadriceps": case "quads": case "hamstrings": case "calves": case "glutes":
    case "adductors": case "abductors": return "var(--rn-lime)";
    default: return "var(--rn-mut)";
  }
}

/** This local Mon–Sun week as dots: done from completed sessions and
 *  activities, planned from `/upcoming` (which omits rest days). */
const dots = computed(() => {
  const now = new Date();
  const todayIso = localISO(now);
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  const done = new Set<string>();
  for (const w of workouts.value) if (w.status === "completed" && w.date) done.add(w.date);
  for (const a of activities.value) if (a.start_at) done.add(localISO(new Date(a.start_at)));
  const planned = new Set(upcoming.value.filter((u) => !/rest/i.test(u.split_focus)).map((u) => u.date));
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
    const iso = localISO(d);
    const today = iso === todayIso;
    const state = today ? (done.has(iso) ? "today-done" : "today")
      : iso < todayIso && done.has(iso) ? "done"
      : iso > todayIso && planned.has(iso) ? "planned" : "empty";
    return {
      iso, state, today,
      label: d.toLocaleDateString(undefined, { weekday: "narrow" }),
      long: d.toLocaleDateString(undefined, { weekday: "long" }),
    };
  });
});
const dotsLabel = computed(() => "This week: " + dots.value
  .map((d) => `${d.long} ${d.state.includes("done") ? "done" : d.state === "today" ? "today"
    : d.state === "planned" ? "planned" : "nothing"}`).join(", "));

// ── Weekly volume chart (all figures from `/stats.week`) ────────────────
const weekMax = computed(() => {
  const w = week.value;
  if (!w) return 1;
  return Math.max(1, ...w.days.map((d) => Math.max(d.volume_lb, d.prev_volume_lb)));
});
const delta = computed<{ text: string; tone: string }>(() => {
  const w = week.value;
  if (!w || w.delta_pct == null) return { text: "no lifting last week", tone: "mut" };
  const pct = Math.abs(w.delta_pct).toFixed(0);
  if (w.direction === "improved") return { text: `▲ ${pct}%`, tone: "lime" };
  if (w.direction === "worse") return { text: `▼ ${pct}%`, tone: "amber" };
  return { text: "≈ same", tone: "mut" };
});
function lb(n: number): string {
  return Math.round(n).toLocaleString();
}
const weekChartLabel = computed(() => !week.value ? "" :
  "Daily volume this week against last week: " + week.value.days.map((d) =>
    `${parseDay(d.date).toLocaleDateString(undefined, { weekday: "long" })} ${lb(d.volume_lb)} lb, last week ${lb(d.prev_volume_lb)}`,
  ).join("; "));

// ── Muscle volume vs MEV–MAV ────────────────────────────────────────────
const trainedMuscles = computed(() => Object.entries(muscles.value ?? {})
  .filter(([, r]) => r.sets > 0).sort((a, b) => b[1].sets - a[1].sets));
const untrainedMuscles = computed(() => Object.entries(muscles.value ?? {})
  .filter(([, r]) => r.sets <= 0).map(([m]) => titleCase(m)));
const muscleScale = computed(() => Math.max(1, ...Object.values(muscles.value ?? {})
  .map((r) => Math.max(r.mav, r.sets))) * 1.1);
function pctOf(n: number): string {
  return `${Math.min(100, Math.max(0, (n / muscleScale.value) * 100))}%`;
}

// ── This year — from the server (UI-F3) ─────────────────────────────────
// `/activities/ytd`, the same response the Activities hero renders. This
// used to be a browser-side loop that invented "+100%" when last year was
// zero and could disagree with Activities about the same year.
const ytdData = ref<ActivityYtd | null>(null);
function ytdMetric(key: string): YtdMetric | null {
  return ytdData.value?.metrics.find((m) => m.key === key) ?? null;
}
/** "↑ 8%", "↓ 10%", "new", "level" — never an invented percentage. */
function ytdDelta(m: YtdMetric): string {
  if (m.note === "new") return "new";
  if (m.pct_change == null || m.direction === "flat") return "level";
  return `${m.pct_change >= 0 ? "↑" : "↓"} ${Math.abs(m.pct_change).toFixed(0)}%`;
}
function ytdTone(m: YtdMetric): string {
  return m.tone === "positive" ? "lime" : m.tone === "caution" ? "amber" : "muted";
}

// ── Recent feed ─────────────────────────────────────────────────────────
interface FeedRow {
  key: string; name: string; sub: string; iconType: string;
  tone: "lime" | "cyan" | "amber" | "mag"; value: string; href: string | null; sortAt: string;
}

/** "Today" / "Yesterday" / "Tue" / "Sep 3" on the user's LOCAL calendar. */
function relDay(d: Date): string {
  const today = new Date();
  const diff = Math.round(
    (new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() -
      new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86_400_000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function hms(duration_s: number | null | undefined): string {
  if (duration_s == null || duration_s <= 0) return "—";
  const total = Math.round(duration_s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}`;
  return `${m}:${String(total % 60).padStart(2, "0")}`;
}

/** OG3-M4 — tone only; the glyph comes from `ActivityIcon`. */
function classifyType(type: string | null | undefined) {
  const t = (type ?? "").toLowerCase();
  const isStrength = t.includes("strength") || t.includes("weight") || t.includes("workout");
  const isTrail = t.includes("trail") || t.includes("hike");
  if (isStrength) return { tone: "lime" as const, isTrail: false };
  if (isTrail) return { tone: "amber" as const, isTrail: true };
  return { tone: "cyan" as const, isTrail: false };
}

const RECENT_LIMIT = 12;
const RECENT_DAYS = 7;

const recent = computed<FeedRow[]>(() => {
  const cutoff = Date.now() - RECENT_DAYS * 86_400_000;
  const wk: FeedRow[] = workouts.value
    .filter((w) => w.status === "completed" && parseDay(w.date).getTime() + 43_200_000 >= cutoff)
    .map((w) => {
      const at = w.completed_at ? new Date(w.completed_at) : new Date(parseDay(w.date).getTime() + 43_200_000);
      return {
        key: `w:${w.date}`, name: `${titleCase(w.split_focus ?? "Strength")} workout`,
        sub: relDay(at), iconType: "strength", tone: "mag", value: "",
        href: `/workout/strength/day/${w.date}`, sortAt: at.toISOString(),
      };
    });
  const acts: FeedRow[] = activities.value
    .filter((a) => a.start_at && Date.parse(a.start_at) >= cutoff)
    .map((a, i) => {
      const cls = classifyType(a.type);
      const at = new Date(a.start_at!);
      const sub = [relDay(at), a.distance_m && a.distance_m > 0 ? fmtDistance(a.distance_m, 1)
        : a.type ? titleCase(a.type) : ""].filter(Boolean).join(" · ");
      const value = cls.isTrail && a.elevation_gain_m && a.elevation_gain_m > 0
        ? fmtElevation(a.elevation_gain_m) : hms(a.duration_s);
      return {
        key: `${a.source ?? "x"}-${a.source_id ?? i}`,
        name: a.name?.trim() || (a.type ? titleCase(a.type) : "Activity"),
        sub, iconType: a.type ?? "", tone: cls.tone, value,
        href: a.source && a.source_id ? `/activity/${a.source}/${a.source_id}` : null,
        sortAt: at.toISOString(),
      };
    });
  return [...acts, ...wk].sort((a, b) => b.sortAt.localeCompare(a.sortAt)).slice(0, RECENT_LIMIT);
});

const tiles = [
  { label: "Activities", icon: "list", tone: "cyan", to: "/activities" },
  { label: "History", icon: "history", tone: "lime", to: "/workout/strength/history" },
  { label: "Charts", icon: "chart", tone: "lime", to: "/workout/strength/charts" },
  { label: "Catalog", icon: "dumbbell", tone: "peri", to: "/workout/strength/catalog" },
  { label: "Preferences", icon: "tune", tone: "peri", to: "/workout/strength/equipment" },
  { label: "Equipment", icon: "tool", tone: "amber", to: "/workout/strength/equipment" },
];
</script>

<template>
  <NeonPage title="Train" class="train-view">
    <template #trailing>
      <button v-if="weekCount != null" class="weekchip" @click="go('/activities')">
        This week · {{ weekCount }}
      </button>
    </template>

    <button v-if="error" class="errbanner" type="button" @click="load">
      <b>Couldn't load Train</b>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </button>

    <!-- 1. Session hero -->
    <NeonHero v-if="loading && !workout" :accent="LIME" class="hero sk-hero" aria-busy="true">
      <div class="hrow">
        <div class="sk sk-ring" />
        <div class="hbody">
          <div class="sk" style="width: 110px; height: 11px" />
          <div class="sk" style="width: 80%; height: 26px; margin-top: 8px" />
          <div class="chips"><div class="sk" style="width: 54px; height: 18px" /><div class="sk" style="width: 64px; height: 18px" /></div>
        </div>
      </div>
      <div class="sk" style="height: 48px; margin-top: 14px; border-radius: 14px" />
      <div class="dots"><div v-for="i in 7" :key="i" class="sk" style="width: 14px; height: 14px; border-radius: 7px" /></div>
    </NeonHero>
    <NeonHero v-else-if="!(error && !workout)" :accent="LIME" class="hero">
      <div class="hrow">
        <NeonRing
          :fraction="setsTotal > 0 ? setsDone / setsTotal : 0"
          :color="LIME" :size="120" :stroke="10"
          :outer="exTotal > 0 ? exDone / exTotal : 0" :outer-color="CYAN"
        >
          <template v-if="setsTotal > 0">
            <b class="rnum lime">{{ setsDone }}/{{ setsTotal }}</b>
            <span class="rcap">Sets</span>
            <span class="rex">{{ exDone }}/{{ exTotal }} ex</span>
          </template>
          <template v-else>
            <b class="rnum mut">—</b>
            <span class="rcap">{{ isRest ? "Rest" : "No sets" }}</span>
          </template>
        </NeonRing>
        <div class="hbody">
          <div class="tag" :class="{ mut: workout?.status === 'completed' }">{{ heroTag }}</div>
          <h2>{{ isRest ? "Rest day" : titleCase(workout!.split_focus) }}</h2>
          <div v-if="chips.length" class="chips">
            <span v-for="m in chips" :key="m" class="chip" :style="{ '--c': muscleColor(m) }">{{ titleCase(m) }}</span>
          </div>
        </div>
      </div>
      <button class="cta" :class="{ muted: cta.muted }" type="button" @click="go('/workout/strength/today')">
        <span class="cl">{{ cta.label }}</span>
        <template v-if="cta.name"><span class="cl">&nbsp;·&nbsp;</span><span class="cn">{{ cta.name }}</span><span class="cl">{{ cta.suffix }}</span></template>
      </button>
      <div class="dots" role="img" :aria-label="dotsLabel">
        <div v-for="d in dots" :key="d.iso" class="dot" :class="d.state">
          <i />
          <span :class="{ lime: d.today }">{{ d.label }}</span>
        </div>
      </div>
    </NeonHero>

    <!-- 2. Weekly volume -->
    <template v-if="week">
      <NeonEyebrow>This week's volume</NeonEyebrow>
      <button class="card vol" type="button" @click="go('/workout/strength/charts')">
        <div class="vhead">
          <span class="vnum">{{ lb(week.total_lb) }}</span><span class="vunit">lb</span>
          <span class="delta" :class="delta.tone">{{ delta.text }}</span>
        </div>
        <div class="vsub">
          vs {{ lb(week.prev_total_lb) }} lb the week before<template v-if="strengthSessions7d != null">
            · {{ strengthSessions7d }} session{{ strengthSessions7d === 1 ? "" : "s" }}</template>
        </div>
        <div class="bars" role="img" :aria-label="weekChartLabel">
          <div v-for="d in week.days" :key="d.date" class="bcol">
            <div class="bstack">
              <div class="ghost" :style="{ height: (d.prev_volume_lb / weekMax) * 100 + '%' }" />
              <div class="bar" :style="{ height: (d.volume_lb / weekMax) * 100 + '%' }" />
            </div>
            <span :class="{ lime: d.date === week.end }">
              {{ parseDay(d.date).toLocaleDateString(undefined, { weekday: "narrow" }) }}
            </span>
          </div>
        </div>
        <div class="legend">
          <span><i class="lg lime-bg" /> This week</span>
          <span><i class="lg track-bg" /> Same day last week</span>
        </div>
        <div v-if="week.unweighted_sets > 0" class="vnote">
          + {{ week.unweighted_sets }} bodyweight set{{ week.unweighted_sets === 1 ? "" : "s" }} not counted in lb
        </div>
      </button>
    </template>

    <!-- 3. Muscle volume vs MEV–MAV -->
    <template v-if="muscles && Object.keys(muscles).length">
      <NeonEyebrow>Sets per muscle · last {{ muscleWindow }} days</NeonEyebrow>
      <button class="card mus" type="button" @click="go('/workout/strength/history')">
        <div v-if="!trainedMuscles.length" class="vsub">No working sets logged in this window.</div>
        <div
          v-for="[m, r] in trainedMuscles" :key="m" class="mrow"
          :aria-label="`${titleCase(m)}: ${r.sets} sets, range ${r.mev} to ${r.mav}, ${r.status.replace('_', ' ')}`"
        >
          <span class="mname">{{ titleCase(m) }}</span>
          <span class="mtrack">
            <span class="mband" :style="{ left: pctOf(r.mev), width: `calc(${pctOf(r.mav)} - ${pctOf(r.mev)})` }" />
            <span class="mdot" :class="r.status" :style="{ left: pctOf(r.sets) }" />
          </span>
          <b class="mval" :class="r.status">{{ r.sets }}</b>
          <span class="mrange">/{{ r.mev }}–{{ r.mav }}</span>
        </div>
        <div class="legend">
          <span><i class="lg peri-bg" /> under</span>
          <span><i class="lg lime-bg" /> in range</span>
          <span><i class="lg amber-bg" /> over</span>
          <span><i class="lg band" /> MEV–MAV</span>
        </div>
        <div v-if="untrainedMuscles.length" class="vnote">Not trained: {{ untrainedMuscles.join(", ") }}</div>
      </button>
    </template>

    <!-- 4. This year + calendar -->
    <template v-if="activities.length || workouts.length">
      <template v-if="ytdData">
        <NeonEyebrow>This year</NeonEyebrow>
        <section class="ytd2">
          <button v-if="ytdMetric('sessions')" class="ycell" @click="go('/activities')">
            <span class="ylbl">Activities</span>
            <span class="ynum num">{{ ytdMetric('sessions')!.current.toFixed(0) }}</span>
            <span class="ydelta" :class="ytdTone(ytdMetric('sessions')!)">{{ ytdDelta(ytdMetric('sessions')!) }} vs last year</span>
          </button>
          <button v-if="ytdMetric('distance_m')" class="ycell" @click="go('/activities')">
            <span class="ylbl">Distance</span>
            <span class="ynum num">{{ (distanceVal(ytdMetric('distance_m')!.current) ?? 0).toFixed(0) }} <em>{{ distanceUnit }}</em></span>
            <span class="ydelta" :class="ytdTone(ytdMetric('distance_m')!)">{{ ytdDelta(ytdMetric('distance_m')!) }} vs last year</span>
          </button>
        </section>
      </template>
      <NeonEyebrow>Activity calendar</NeonEyebrow>
      <section class="card calcard">
        <ActivityYearCalendar :activities="activities" :workouts="workouts" compact />
      </section>
    </template>

    <!-- 5. Recent feed -->
    <div class="caprow">
      <NeonEyebrow>Recent · last 7 days</NeonEyebrow>
      <button class="see-all" @click="go('/activities')">See all ›</button>
    </div>
    <template v-if="loading && !activities.length">
      <div class="sk" style="height: 68px; border-radius: 22px; margin-bottom: 11px" />
      <div class="sk" style="height: 68px; border-radius: 22px; margin-bottom: 11px" />
    </template>
    <template v-else-if="recent.length">
      <button v-for="row in recent" :key="row.key" class="pill" @click="go(row.href ?? '/activities')">
        <span class="pi" :class="`bg-${row.tone}`"><ActivityIcon :type="row.iconType" :size="17" /></span>
        <span class="pn">{{ row.name }}<small>{{ row.sub }}</small></span>
        <span v-if="row.value" class="pv" :class="row.tone"><b>{{ row.value }}</b></span>
        <span class="chev">›</span>
      </button>
    </template>
    <!-- A failed fetch is not a quiet week (UX-F1). -->
    <button v-else-if="!error" class="pill" @click="go('/activities')">
      <span class="pi bg-cyan"><ActivityIcon type="run" :size="17" /></span>
      <span class="pn">No activity in the last 7 days<small>Tap to see your full history</small></span>
      <span class="chev">›</span>
    </button>

    <!-- 6. Tile grid -->
    <NeonEyebrow>More</NeonEyebrow>
    <nav class="tiles">
      <button v-for="t in tiles" :key="t.label" class="tile" type="button"
              :aria-label="`Open ${t.label}`" @click="go(t.to)">
        <span class="ti" :class="`bg-${t.tone} ${t.tone}`">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <template v-if="t.icon === 'list'"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></template>
            <template v-else-if="t.icon === 'history'"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></template>
            <template v-else-if="t.icon === 'chart'"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></template>
            <template v-else-if="t.icon === 'dumbbell'"><path d="M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12" /></template>
            <template v-else-if="t.icon === 'tune'"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></template>
            <template v-else><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" /></template>
          </svg>
        </span>
        <span class="tl">{{ t.label }}</span>
      </button>
    </nav>
  </NeonPage>
</template>

<style scoped>
.weekchip {
  font-family: "Space Grotesk", "Geist Mono", monospace; font-weight: 700; font-size: 13px;
  color: var(--rn-lime); background: rgba(93, 255, 59, 0.12); border: 1px solid rgba(93, 255, 59, 0.25);
  padding: 5px 12px; border-radius: 20px; cursor: pointer;
}
.errbanner {
  display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; cursor: pointer;
  background: rgba(255, 93, 122, 0.10); border: 1px solid rgba(255, 93, 122, 0.28); border-radius: 14px;
  padding: 12px 14px; margin-bottom: 12px; color: var(--rn-mut); font: inherit; font-size: 12px;
}
.errbanner b { color: var(--rn-bad); font-size: 13px; }
.errbanner em { font-style: normal; color: var(--rn-cyan); font-weight: 600; }

/* Hero */
.hrow { display: flex; align-items: center; gap: 16px; }
.hbody { flex: 1; min-width: 0; }
.tag { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 11px; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase; color: var(--rn-lime); }
.tag.mut { color: var(--rn-mut); }
.hero h2 { margin: 4px 0 0; font-size: 26px; line-height: 1.1; font-weight: 800; letter-spacing: -0.5px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chip { font-size: 11px; font-weight: 700; color: var(--c); padding: 3px 8px; border-radius: 10px;
  background: color-mix(in srgb, var(--c) 14%, transparent); border: 1px solid color-mix(in srgb, var(--c) 35%, transparent); }
.rnum { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 22px; font-weight: 700; }
.rcap { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); }
.rex { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 10px; font-weight: 700; color: var(--rn-cyan); }
.cta { display: flex; align-items: center; justify-content: center; width: 100%; height: 48px; margin-top: 14px; border-radius: 14px; cursor: pointer;
  background: var(--rn-lime); border: 1px solid var(--rn-lime); color: var(--rn-onacc);
  font: inherit; font-size: 15px; font-weight: 800; padding: 0 16px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; box-shadow: 0 0 16px rgba(93, 255, 59, 0.35); }
.cta .cl { flex: 0 0 auto; white-space: pre; }
.cta .cn { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cta.muted { background: var(--rn-card); border-color: var(--rn-track); color: var(--rn-mut); box-shadow: none; }
.cta:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.dots { display: flex; justify-content: space-between; margin-top: 14px; }
.dot { width: 32px; display: flex; flex-direction: column; align-items: center; gap: 4px; }
.dot i { width: 10px; height: 10px; border-radius: 50%; background: var(--rn-track); margin: 2px; }
.dot.done i, .dot.today-done i { width: 14px; height: 14px; margin: 0; background: var(--rn-lime); }
.dot.today-done i { box-shadow: 0 0 0 2px var(--rn-bg), 0 0 0 3.5px var(--rn-ink); }
.dot.today i { width: 14px; height: 14px; margin: 0; background: rgba(93, 255, 59, .18); box-shadow: inset 0 0 0 2px var(--rn-lime); }
.dot.planned i { background: var(--rn-peri); }
.dot span { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 10px; font-weight: 700; color: var(--rn-mut); }
.sk { background: linear-gradient(90deg, rgba(31, 41, 55, .5), rgba(93, 255, 59, .18), rgba(31, 41, 55, .5));
  background-size: 200% 100%; animation: sk 1.4s linear infinite; border-radius: 6px; }
.sk-ring { width: 120px; height: 120px; border-radius: 50%; flex: 0 0 auto; }
@keyframes sk { from { background-position: 200% 0; } to { background-position: -200% 0; } }

/* Cards */
.card { display: block; width: 100%; text-align: left; font: inherit; color: inherit; cursor: pointer;
  background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 16px; }
.card:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.vhead { display: flex; align-items: baseline; gap: 4px; }
.vnum { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 26px; font-weight: 700; }
.vunit { color: var(--rn-mut); font-size: 12px; }
.delta { margin-left: auto; font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 12px; font-weight: 700;
  padding: 3px 8px; border-radius: 10px; border: 1px solid currentColor; }
.delta.lime { color: var(--rn-lime); background: rgba(93, 255, 59, .12); }
.delta.amber { color: var(--rn-amber); background: rgba(255, 181, 46, .12); }
.delta.mut { color: var(--rn-mut); background: rgba(155, 155, 176, .10); }
.vsub, .vnote { color: var(--rn-mut); font-size: 12px; }
.vnote { font-size: 11px; margin-top: 6px; }
.bars { display: flex; margin-top: 12px; }
.bcol { flex: 1; display: flex; flex-direction: column; align-items: center; }
.bstack { height: 96px; width: 100%; position: relative; border-bottom: 1px solid var(--rn-line); }
.bstack .ghost, .bstack .bar { position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); border-radius: 4px 4px 0 0; }
.bstack .ghost { width: 62%; background: var(--rn-track); }
.bstack .bar { width: 36%; background: var(--rn-lime); box-shadow: 0 0 8px rgba(93, 255, 59, .35); }
.bcol span { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 10px; font-weight: 700;
  color: var(--rn-mut); padding-top: 6px; transform: translateY(100%); height: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 22px; font-size: 11px; color: var(--rn-mut); }
.mus .legend { margin-top: 10px; }
.lg { display: inline-block; width: 8px; height: 8px; border-radius: 50%; vertical-align: middle; }
.lg.band { width: 14px; height: 6px; border-radius: 3px; background: rgba(93, 255, 59, .28); }
.lime-bg { background: var(--rn-lime); } .track-bg { background: var(--rn-track); }
.peri-bg { background: var(--rn-peri); } .amber-bg { background: var(--rn-amber); }
.mrow { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }
.mname { width: 86px; flex: 0 0 auto; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mtrack { flex: 1; position: relative; height: 6px; border-radius: 3px; background: var(--rn-track); }
.mband { position: absolute; top: 0; bottom: 0; border-radius: 3px; background: rgba(93, 255, 59, .28); }
.mdot { position: absolute; top: 50%; width: 9px; height: 9px; border-radius: 50%; transform: translate(-50%, -50%);
  background: var(--rn-mut); }
.mdot.in_range { background: var(--rn-lime); box-shadow: 0 0 0 3px rgba(93, 255, 59, .3); }
.mdot.under { background: var(--rn-peri); box-shadow: 0 0 0 3px rgba(111, 123, 255, .3); }
.mdot.over { background: var(--rn-amber); box-shadow: 0 0 0 3px rgba(255, 181, 46, .3); }
.mval { width: 22px; font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 13px; text-align: right; }
.mval.in_range { color: var(--rn-lime); } .mval.under { color: var(--rn-peri); } .mval.over { color: var(--rn-amber); }
.mrange { width: 40px; font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 10px; color: var(--rn-mut); }

/* This year */
.ydelta.muted { color: var(--rn-mut, #9b9bb0); }
.ytd2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ycell { display: flex; flex-direction: column; gap: 4px; text-align: left; font: inherit; color: inherit; cursor: pointer;
  background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 14px; padding: 12px 14px; }
.ylbl { font-size: .66rem; letter-spacing: .12em; text-transform: uppercase; color: var(--rn-mut); font-weight: 700; }
.ynum { font-family: "Space Grotesk", "Geist Mono", monospace; font-size: 1.35rem; font-weight: 700; }
.ynum em { font-style: normal; font-size: .8rem; color: var(--rn-mut); }
.ydelta { font-size: .72rem; font-weight: 600; }
.calcard { cursor: default; padding: 12px 14px; }

/* Feed */
.caprow { display: flex; align-items: center; justify-content: space-between; }
.see-all { background: none; border: 0; padding: 2px 4px; cursor: pointer; color: var(--rn-cyan); font-size: 11px; font-weight: 700; }
.pill { display: flex; align-items: center; gap: 14px; width: 100%; background: var(--rn-card); border: 0;
  border-radius: 22px; padding: 14px 16px; margin-bottom: 11px; cursor: pointer; color: inherit; text-align: left; font: inherit; }
.pill .pi { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.pill .pn { flex: 1; min-width: 0; font-weight: 700; font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill .pn small { display: block; color: var(--rn-mut); font-weight: 500; font-size: 12px; margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pill .pv { font-family: "Space Grotesk", "Geist Mono", monospace; font-weight: 700; font-size: 14px; flex: 0 0 auto; }
.pill .chev { color: var(--rn-mut); font-size: 18px; flex: 0 0 auto; }

/* Tiles */
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 8px; }
.tile { min-height: 76px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 12px 6px;
  cursor: pointer; color: var(--rn-ink); font: inherit; }
.tile:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.tile .ti { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.tile .ti svg { width: 18px; height: 18px; }
.tile .tl { font-size: 12px; font-weight: 700; }

.lime { color: var(--rn-lime); } .cyan { color: var(--rn-cyan); } .amber { color: var(--rn-amber); }
.mag { color: var(--rn-mag); } .peri { color: var(--rn-peri); } .mut { color: var(--rn-mut); }
.bg-mag { background: rgba(255, 58, 216, 0.14); } .bg-lime { background: rgba(93, 255, 59, 0.14); }
.bg-cyan { background: rgba(40, 230, 255, 0.14); } .bg-amber { background: rgba(255, 181, 46, 0.14); }
.bg-peri { background: rgba(111, 123, 255, 0.14); }
</style>
