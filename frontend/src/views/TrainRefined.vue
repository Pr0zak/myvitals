<script setup lang="ts">
/**
 * TrainRefined — the "Neon Refined" (A1) Train tab.
 *
 * Ported from the locked A1 design language (see RingsRefined.vue): disciplined
 * cyan-lead palette, glass cards, Plus Jakarta Sans UI + Space Grotesk numbers.
 * A today's-workout HERO built from the generated strength plan and a "Recent"
 * activities feed. Rendered by Train.vue when the "Neon Refined" theme is active
 * (theme.ts `isRefined`); no bottom nav — the app shell owns navigation.
 *
 * Data comes from the same backend endpoints the classic Train view uses —
 * nothing computed client-side beyond formatting; everything renders as "—"
 * when null. Scoped to `.refined-train`; colours ride the neon CSS vars
 * (--accent/--good/--warn/--violet) live under data-theme="neon".
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import ActivityYearCalendar from "@/components/ActivityYearCalendar.vue";
import type { Activity, StrengthWorkoutDetail } from "@/api/types";

const router = useRouter();
const loading = ref(true);

const workout = ref<StrengthWorkoutDetail | null>(null);
const activities = ref<Activity[]>([]);
const workouts = ref<Array<{ date: string; status?: string | null;
  split_focus?: string | null; started_at?: string | null;
  completed_at?: string | null }>>([]);

/** Jan 1 of LAST year — the YTD pair compares against the same span a year
 *  ago, so the fetch has to reach back that far. Widened from limit=6; the
 *  recent rows are derived from the same list, so it stays one request. */
function ytdSince(): string {
  return new Date(Date.UTC(new Date().getFullYear() - 1, 0, 1)).toISOString();
}

async function load() {
  loading.value = true;
  const [wk, acts, wkts] = await Promise.all([
    api.strengthToday().catch(() => null),
    api.activities({ limit: 2000, since: ytdSince() }).catch(() => null),
    api.strengthWorkouts({ limit: 400 }).catch(() => ({ count: 0, workouts: [] })),
  ]);
  workout.value = wk;
  activities.value = Array.isArray(acts) ? acts : [];
  workouts.value = ((wkts as any)?.workouts ?? [])
    .filter((w: any) => !["regenerated", "planned", "skipped"].includes(w.status))
    // Cardio days auto-completed by an Activity are already in the feed.
    .filter((w: any) => !(w.split_focus === "cardio" && w.completed_by_activity_source));
  loading.value = false;
}

/** Same computation the Activities YTD card performs, including the
 *  strength started_at/completed_at arm — two surfaces disagreeing about
 *  "activities this year" is the bug class the architecture rule warns of. */
const ytd = computed(() => {
  const now = new Date();
  const thisYear = now.getFullYear();
  const lastYear = thisYear - 1;
  const endLast = new Date(Date.UTC(lastYear, now.getMonth(), now.getDate()));
  const a = { n: 0, dist: 0 };
  const b = { n: 0, dist: 0 };
  for (const r of activities.value) {
    if (!r.start_at) continue;
    const d = new Date(r.start_at);
    const t = d.getFullYear() === thisYear && d <= now ? a
      : d.getFullYear() === lastYear && d <= endLast ? b : null;
    if (!t) continue;
    t.n += 1;
    t.dist += r.distance_m ?? 0;
  }
  for (const w of workouts.value) {
    if (w.status !== "completed" || !w.date) continue;
    const d = new Date(w.date + "T00:00:00Z");
    const t = d.getUTCFullYear() === thisYear && d <= now ? a
      : d.getUTCFullYear() === lastYear && d <= endLast ? b : null;
    if (!t) continue;
    t.n += 1;
  }
  const pct = (x: number, y: number) =>
    y === 0 ? (x === 0 ? 0 : 100) : ((x - y) / y) * 100;
  return {
    n: a.n, miles: a.dist / 1609.344,
    pctN: pct(a.n, b.n), pctDist: pct(a.dist, b.dist),
  };
});
onMounted(load);

function go(path: string) {
  router.push(path);
}

// ---- hero copy ----
const workoutTitle = computed(() => {
  const w = workout.value;
  if (!w) return "No workout planned";
  const f = w.split_focus;
  const cap = f.charAt(0).toUpperCase() + f.slice(1);
  return `${cap} day`;
});
const exCount = computed(() => {
  const ex = workout.value?.exercises;
  return Array.isArray(ex) ? ex.length : 0;
});
const workoutSub = computed(() => {
  const w = workout.value;
  if (!w) return "Tap to generate today's plan";
  const n = exCount.value;
  return `${n} exercise${n === 1 ? "" : "s"}`;
});
const deloadNote = computed(() => {
  const df = workout.value?.deload_factor;
  if (df == null || df >= 1) return null;
  return `Load eased ${Math.round((1 - df) * 100)}% for recovery`;
});
const workoutDone = computed(() => workout.value?.status === "completed");

// ---- recent activities feed ----
interface FeedRow {
  key: string;
  name: string;
  sub: string;
  strength: boolean;
  value: string;
  /** Route to this row's own activity. Null when the source/id is missing,
   *  in which case the row falls back to opening the full feed. */
  href: string | null;
}

function classify(type: string | null | undefined): boolean {
  const t = (type ?? "").toLowerCase();
  return t.includes("strength") || t.includes("weight") || t.includes("workout");
}
function titleCase(s: string): string {
  return s
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
function relDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const d = new Date(t);
  const now = new Date();
  const dayMs = 24 * 60 * 60 * 1000;
  const a0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const b0 = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.floor((a0 - b0) / dayMs);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}
function primary(a: Activity): string {
  if (a.distance_m != null && a.distance_m > 0) {
    return `${(a.distance_m / 1609.344).toFixed(1)} mi`;
  }
  if (a.duration_s != null && a.duration_s > 0) {
    return `${Math.round(a.duration_s / 60)}m`;
  }
  return "—";
}

const RECENT_LIMIT = 6;

/** The fetch is deliberately wide (a trailing year, for the YTD pair and
 *  the calendar) but this feed is a preview — cap and sort it explicitly
 *  rather than inheriting whatever order and length the API returned.
 *  Matches RefinedTrainScreen.kt's `sortedByDescending { startAt }.take(6)`. */
const recent = computed<FeedRow[]>(() =>
  [...activities.value]
    .sort((a, b) => (b.start_at ?? "").localeCompare(a.start_at ?? ""))
    .slice(0, RECENT_LIMIT)
    .map((a, i): FeedRow => {
    const strength = classify(a.type);
    const name = a.name?.trim() || (a.type ? titleCase(a.type) : "Activity");
    const day = relDay(a.start_at);
    const sub = [day, strength ? "Strength" : "Cardio"].filter(Boolean).join(" · ");
    return {
      key: `${a.source ?? "x"}-${a.source_id ?? i}`,
      name,
      sub,
      strength,
      value: primary(a),
      href: a.source && a.source_id
        ? `/activity/${a.source}/${a.source_id}`
        : null,
    };
    }),
);
</script>

<template>
  <div class="refined-train">
    <!-- header -->
    <header class="head">
      <div>
        <h1>Train</h1>
        <div class="sub">Today's plan &amp; recent activity</div>
      </div>
      <button class="iconbtn" @click="go('/workout/strength/catalog')" aria-label="Exercise catalog">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <line x1="6.5" y1="6.5" x2="17.5" y2="6.5" />
          <line x1="6.5" y1="12" x2="17.5" y2="12" />
          <line x1="6.5" y1="17.5" x2="17.5" y2="17.5" />
          <circle cx="3.5" cy="6.5" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="3.5" cy="12" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="3.5" cy="17.5" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      </button>
    </header>

    <!-- today's workout hero -->
    <section class="hero card">
      <div class="cap">Today</div>
      <div class="hero-row">
        <span class="wico">
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round">
            <path d="M6.5 6.5v11M17.5 6.5v11M4 9v6M20 9v6M6.5 12h11" />
          </svg>
        </span>
        <div class="wmeta">
          <div class="wt">{{ workoutTitle }}</div>
          <div class="ws">{{ workoutSub }}</div>
        </div>
      </div>
      <div v-if="deloadNote" class="deload">{{ deloadNote }}</div>
      <button class="startbtn" @click="go('/workout/strength/today')">
        {{ workout ? (workoutDone ? "View workout" : "Start workout") : "Generate plan" }}
      </button>
    </section>

    <!-- this year + activity calendar (mirrors the phone Refined Train) -->
    <div class="cap out">This year</div>
    <section class="ytd2">
      <button class="ycell" @click="go('/activities')">
        <span class="ylbl">Activities</span>
        <span class="ynum num">{{ ytd.n }}</span>
        <span class="ydelta" :class="ytd.pctN >= 0 ? 'up' : 'down'">
          {{ ytd.pctN >= 0 ? '↑' : '↓' }} {{ Math.abs(ytd.pctN).toFixed(0) }}%
        </span>
      </button>
      <button class="ycell" @click="go('/activities')">
        <span class="ylbl">Distance</span>
        <span class="ynum num">{{ ytd.miles.toFixed(0) }} <em>mi</em></span>
        <span class="ydelta" :class="ytd.pctDist >= 0 ? 'up' : 'down'">
          {{ ytd.pctDist >= 0 ? '↑' : '↓' }} {{ Math.abs(ytd.pctDist).toFixed(0) }}%
        </span>
      </button>
    </section>

    <div class="cap out">Activity calendar</div>
    <section class="card calcard">
      <ActivityYearCalendar :activities="activities" :workouts="workouts" compact />
    </section>

    <!-- recent activities -->
    <div class="cap out cap-row">
      <span>Recent</span>
      <button v-if="recent.length > 0" class="see-all" @click="go('/activities')">
        See all ›
      </button>
    </div>
    <section class="feed">
      <template v-if="recent.length > 0">
        <button
          v-for="row in recent"
          :key="row.key"
          class="row"
          @click="go(row.href ?? '/activities')"
        >
          <span class="ico" :class="row.strength ? 'good' : 'accent'">
            <svg v-if="row.strength" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M6.5 6.5v11M17.5 6.5v11M4 9v6M20 9v6M6.5 12h11" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="5.5" cy="17.5" r="3.2" />
              <circle cx="18.5" cy="17.5" r="3.2" />
              <path d="M5.5 17.5l4-6h5l3 6M9.5 11.5l3-4h3" />
            </svg>
          </span>
          <span class="rmeta">
            <span class="rn">{{ row.name }}</span>
            <span class="rs">{{ row.sub }}</span>
          </span>
          <span class="rv num" :class="row.strength ? 'good' : 'accent'">{{ row.value }}</span>
          <span class="chev">›</span>
        </button>
      </template>
      <button v-else class="row empty" @click="go('/activities')">
        <span class="ico accent">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="5.5" cy="17.5" r="3.2" />
            <circle cx="18.5" cy="17.5" r="3.2" />
            <path d="M5.5 17.5l4-6h5l3 6M9.5 11.5l3-4h3" />
          </svg>
        </span>
        <span class="rmeta">
          <span class="rn">No recent activity</span>
          <span class="rs">Tap to open your feed</span>
        </span>
        <span class="chev">›</span>
      </button>
    </section>
  </div>
</template>

<style scoped>
.ytd2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 4px; }
.ycell {
  display: flex; flex-direction: column; gap: 4px; text-align: left;
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 15px;
  padding: 12px 14px; cursor: pointer; color: inherit;
}
.ycell:hover { border-color: var(--accent, #28e6ff); }
.ylbl { font-size: .66rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.ynum { font-size: 1.35rem; font-weight: 700; }
.ynum em { font-style: normal; font-size: .8rem; color: var(--muted); }
.ydelta { font-size: .72rem; font-weight: 600; }
.ydelta.up { color: #22c55e; }
.ydelta.down { color: #ef4444; }
.calcard { padding: 12px 14px; }

.cap-row {
  display: flex; align-items: center; justify-content: space-between;
}
.see-all {
  background: none; border: 0; padding: 2px 4px; cursor: pointer;
  color: var(--rn-cyan, #28e6ff);
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
}
.see-all:hover { text-decoration: underline; }

.refined-train {
  --accent: var(--accent, #28e6ff);
  --good: var(--good, #5dff3b);
  --warn: var(--warn, #ffb52e);
  --violet: var(--violet, #ff3ad8);
  --bad: var(--bad, #ff5d7a);
  --ink: var(--text, #f0f0f7);
  --muted-c: var(--muted, #9b9bb0);
  --dim: #7c7d94;
  --glass: rgba(255, 255, 255, 0.04);
  --hair: rgba(155, 155, 176, 0.14);
  --track: #23263a;
  --num: "Space Grotesk", "Geist Mono", monospace;

  margin: -1.25rem -1.5rem;
  padding: 22px 16px 108px;
  min-height: 100vh;
  color: var(--ink);
  font-family: "Plus Jakarta Sans", "Geist", system-ui, sans-serif;
  background: radial-gradient(120% 45% at 50% -6%, #161a2c, #0f1118 60%);
}
.refined-train button { font-family: inherit; color: inherit; cursor: pointer; }
.num { font-family: var(--num); font-variant-numeric: tabular-nums; }

.head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 18px; }
.head h1 { font-size: 26px; font-weight: 800; margin: 0; letter-spacing: -0.02em; }
.head .sub { font-size: 12px; color: var(--muted-c); margin-top: 2px; }
.iconbtn {
  margin-left: auto; width: 38px; height: 38px; border-radius: 12px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: var(--glass); border: 1px solid var(--hair); color: var(--muted-c);
}
.iconbtn svg { width: 19px; height: 19px; }

.card {
  display: block; width: 100%; text-align: left;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.015));
  border: 1px solid var(--hair); border-radius: 18px; padding: 15px 16px;
}

.cap {
  font-family: var(--num);
  font-size: 10px; font-weight: 700; letter-spacing: 0.14em;
  color: var(--muted-c); text-transform: uppercase;
}
.cap.out { margin: 4px 2px 10px; }

.hero { margin-bottom: 18px; }
.hero-row { display: flex; align-items: center; gap: 13px; margin-top: 11px; }
.wico {
  width: 46px; height: 46px; border-radius: 13px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
  background: rgba(40, 230, 255, 0.12); border: 1px solid rgba(40, 230, 255, 0.22);
}
.wico svg { width: 24px; height: 24px; }
.wmeta { flex: 1; min-width: 0; }
.wt { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }
.ws { font-size: 12.5px; color: var(--muted-c); margin-top: 2px; }

.deload {
  margin-top: 12px; padding: 8px 11px; border-radius: 11px;
  font-size: 12px; font-weight: 600;
  color: var(--warn); background: rgba(255, 181, 46, 0.12);
  border: 1px solid rgba(255, 181, 46, 0.22);
}
.startbtn {
  display: block; width: 100%; margin-top: 14px;
  padding: 12px 16px; border: 0; border-radius: 13px;
  font-weight: 800; font-size: 14px; letter-spacing: 0.01em;
  color: #04212a; background: linear-gradient(120deg, var(--accent), #17b9d6);
  box-shadow: 0 0 18px rgba(40, 230, 255, 0.28);
}

.feed { display: flex; flex-direction: column; gap: 10px; }
.row {
  display: flex; align-items: center; gap: 13px; width: 100%; text-align: left;
  background: var(--glass); border: 1px solid var(--hair);
  border-radius: 15px; padding: 12px 14px;
}
.row .ico {
  width: 40px; height: 40px; border-radius: 11px; flex: 0 0 auto;
  display: flex; align-items: center; justify-content: center;
}
.row .ico svg { width: 21px; height: 21px; }
.row .ico.accent { color: var(--accent); background: rgba(40, 230, 255, 0.13); }
.row .ico.good { color: var(--good); background: rgba(93, 255, 59, 0.13); }
.rmeta { flex: 1; min-width: 0; }
.rn { display: block; font-size: 15px; font-weight: 700; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.rs { display: block; font-size: 12px; color: var(--muted-c); margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rv { flex: 0 0 auto; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
.rv.accent { color: var(--accent); }
.rv.good { color: var(--good); }
.chev { flex: 0 0 auto; color: var(--dim); font-size: 18px; }
.row.empty .rn { font-weight: 600; }
</style>
