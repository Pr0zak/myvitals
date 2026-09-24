<script setup lang="ts">
/**
 * Activities feed (UI-5). Phone twin: `ActivitiesScreen.kt`.
 *
 *   hero      year-to-date distance vs the same day last year, with the
 *             cumulative line this year (cyan) over last year (dashed
 *             periwinkle) — all from GET /activities/ytd
 *   calendar  a 3-month strip that expands to the year
 *   feed      grouped by local week or month; headers carry the server's
 *             week / month totals (UI-F2 brought back month grouping, sort
 *             newest / longest / farthest and a grid layout — ordering and
 *             layout only, every number is still the server's)
 *   period    UI-F2: a stats row for exactly the range + chip selected
 *             (GET /activities/stats?since=&category=&include_strength) and
 *             the personal-records card (GET /activities/records). Both used
 *             to be summed in this file from whatever rows had loaded.
 *
 * What changed and why: the YTD card was computed here from a raw 18-month
 * dump — a third copy of a loop the phone and Train had their own versions
 * of — and it printed "↑100%" whenever last year was zero and painted a
 * shortfall red. The server owns the comparison now: a null percentage
 * with a "new" note, and a `tone` that is amber for a shortfall. A failed
 * refresh is an amber banner ABOVE the cached rows, never a replacement.
 */
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { Map as MapIcon, GitCompareArrows, RefreshCw } from "lucide-vue-next";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import ActivityIcon from "@/components/ActivityIcon.vue";
import PolylineThumbnail from "@/components/PolylineThumbnail.vue";
import ActivityYearCalendar from "@/components/ActivityYearCalendar.vue";
import { api, activitiesYtd, activitiesWithRoutes, activitiesRecords, activitiesStatsFor } from "@/api/client";
import type { ActivityFeedWindow } from "@/api/client";
import type {
  Activity, ActivityYtd, YtdMetric, YtdWeek, YtdMonth, SessionSummary,
  ActivityStats, ActivityRecords, ActivityRecord,
} from "@/api/types";
import {
  distanceVal, distanceUnit, elevationVal, elevationUnit, fmtDistance, fmtElevation, fmtPace,
  weightVal, weightUnit,
} from "@/units";
import { fmtActivityType } from "@/format";
import { toLocalISO } from "@/dates";
import { categoryColor, categoryForSplitFocus, categoryForType } from "@/utils/activityCategory";

type RangeKey = "7d" | "30d" | "90d" | "ytd" | "365d" | "all";
const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7d", label: "7d" }, { key: "30d", label: "30d" }, { key: "90d", label: "90d" },
  { key: "ytd", label: "YTD" }, { key: "365d", label: "1y" }, { key: "all", label: "All" },
];

interface Workout {
  id: number; date: string; split_focus: string; status: string;
  started_at?: string | null; completed_at?: string | null;
  completed_by_activity_source?: string | null;
  session_summary?: SessionSummary | null;
}

type FeedItem =
  | { kind: "activity"; key: string; day: string; sort: number; a: Activity }
  | { kind: "strength"; key: string; day: string; sort: number; w: Workout };

function loadPref(key: string, def: string): string {
  try { return localStorage.getItem(`myvitals.activities.${key}`) ?? def; } catch { return def; }
}
function savePref(key: string, val: string) {
  try { localStorage.setItem(`myvitals.activities.${key}`, val); } catch { /* private mode */ }
}

const range = ref<RangeKey>(loadPref("range", "90d") as RangeKey);
const typeFilter = ref<string>(loadPref("type", "all"));
watch(range, (v) => savePref("range", v));
watch(typeFilter, (v) => savePref("type", v));

// UI-F2 — display ordering and layout of the server's rows. New pref keys:
// the pre-UI-5 "sort" pref held different values.
type SortKey = "newest" | "longest" | "farthest";
type GroupKey = "week" | "month";
type ViewMode = "list" | "grid";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "Newest" }, { key: "longest", label: "Longest" }, { key: "farthest", label: "Farthest" },
];
function pick<T extends string>(v: string, ok: readonly T[], def: T): T {
  return (ok as readonly string[]).includes(v) ? (v as T) : def;
}
const sortKey = ref<SortKey>(pick(loadPref("feedSort", "newest"), ["newest", "longest", "farthest"], "newest"));
const groupBy = ref<GroupKey>(pick(loadPref("groupBy", "week"), ["week", "month"], "week"));
const viewMode = ref<ViewMode>(pick(loadPref("feedView", "list"), ["list", "grid"], "list"));
watch(sortKey, (v) => savePref("feedSort", v));
watch(groupBy, (v) => savePref("groupBy", v));
watch(viewMode, (v) => savePref("feedView", v));

const activities = ref<Activity[]>([]);
const workouts = ref<Workout[]>([]);
const ytd = ref<ActivityYtd | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string | null>(null);
const shown = ref(40);

const syncing = ref(false);
const syncToast = ref("");
const cookieNeedsReconnect = ref(false);
const cookieError = ref<string | null>(null);

function sinceFor(r: RangeKey): Date | null {
  const now = new Date();
  switch (r) {
    case "7d": return new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6);
    case "30d": return new Date(now.getFullYear(), now.getMonth(), now.getDate() - 29);
    case "90d": return new Date(now.getFullYear(), now.getMonth(), now.getDate() - 89);
    case "ytd": return new Date(now.getFullYear(), 0, 1);
    case "365d": return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
    default: return null;
  }
}

function errMsg(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  return e instanceof Error ? e.message : "Couldn't reach the backend.";
}

async function load() {
  refreshing.value = true;
  const since = sinceFor(range.value);
  try {
    const [list, sw, y] = await Promise.all([
      // Thumbnails only need the simplified track (UX-X2).
      activitiesWithRoutes({ since: since ?? undefined, limit: 2000, polyline: "simple" }),
      api.strengthWorkouts({ limit: 400 }).catch(() => null),
      activitiesYtd().catch(() => null),
    ]);
    activities.value = list;
    if (sw) {
      workouts.value = sw.workouts
        .filter((w) => w.status !== "regenerated" && w.status !== "planned" && w.status !== "skipped")
        // A cardio day auto-completed by an activity: the activity is
        // already in the feed.
        .filter((w) => !(w.split_focus === "cardio" && w.completed_by_activity_source));
    }
    if (y) ytd.value = y;
    error.value = null;
  } catch (e) {
    // Keep whatever is on screen; the banner says it is stale.
    error.value = errMsg(e);
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function loadCookieStatus() {
  try {
    const s = await api.stravaCookieStatus();
    cookieNeedsReconnect.value = !!s.needs_reconnect;
    cookieError.value = s.last_error;
  } catch { /* the banner just stays hidden */ }
}

async function syncStravaNow() {
  syncing.value = true;
  syncToast.value = "";
  try {
    const r = await api.stravaCookieSync();
    if (r.error) syncToast.value = `Sync error: ${r.error}`;
    else {
      syncToast.value = r.upserted === 0 ? "No new rides since last sync."
        : `Synced ${r.upserted} new ${r.upserted === 1 ? "ride" : "rides"}.`;
      if (r.upserted > 0) await load();
    }
    await loadCookieStatus();
  } catch (e) {
    syncToast.value = `Sync failed: ${errMsg(e)}`;
  } finally {
    syncing.value = false;
    setTimeout(() => { syncToast.value = ""; }, 4000);
  }
}

// ── UI-F2: period stats + personal records for the selected range + chip ──
const stats = ref<ActivityStats | null>(null);
const records = ref<ActivityRecords | null>(null);
const summaryFailed = ref(false);
let summarySeq = 0;

function feedWindow(): ActivityFeedWindow {
  const since = sinceFor(range.value);
  return { since: since ? toLocalISO(since) : null, category: typeFilter.value };
}

async function loadSummary() {
  const seq = ++summarySeq;
  const w = feedWindow();
  // The strength chip is generated workouts only — no Activity rows, so
  // no records to hold.
  const wantRecords = typeFilter.value !== "strength";
  const [st, rec] = await Promise.all([
    activitiesStatsFor(w).then((v) => ({ ok: true as const, v }), () => ({ ok: false as const })),
    wantRecords
      ? activitiesRecords(w).then((v) => ({ ok: true as const, v }), () => ({ ok: false as const }))
      : Promise.resolve({ ok: true as const, v: null }),
  ]);
  if (seq !== summarySeq) return; // a newer selection already answered
  // A failed request keeps the previous figures and says so — it never
  // renders as an empty period.
  if (st.ok) stats.value = st.v;
  if (rec.ok) records.value = rec.v;
  summaryFailed.value = !st.ok || !rec.ok;
}

onMounted(() => { load(); loadCookieStatus(); loadSummary(); });
watch(range, () => { shown.value = 40; load(); loadSummary(); });
watch(typeFilter, () => { shown.value = 40; loadSummary(); });
watch(sortKey, () => { shown.value = 40; });

const shownRecords = computed<ActivityRecord[]>(() =>
  (records.value?.records ?? []).filter((r) => r.value != null && r.activity != null),
);

/** Records can be years old, so the year is always shown. */
function recordDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y!, (m ?? 1) - 1, d ?? 1).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}
function fmtRecord(r: ActivityRecord): string {
  const v = r.value as number;
  switch (r.key) {
    case "longest_distance": return fmtDistance(v, 1);
    case "longest_duration": return fmtHm(v);
    case "most_elevation": return fmtElevation(v);
    case "highest_suffer": return Math.round(v).toString();
    case "fastest":
      if (r.display === "pace") return fmtPace(v);
      return `${(distanceVal(v * 3600) ?? 0).toFixed(1)} ${distanceUnit.value}/h`;
  }
  return String(v);
}

// ── Feed ──
const feed = computed<FeedItem[]>(() => {
  const since = sinceFor(range.value);
  const sinceIso = since ? toLocalISO(since) : null;
  const items: FeedItem[] = [];
  for (const a of activities.value) {
    const d = new Date(a.start_at);
    items.push({ kind: "activity", key: `a-${a.source}-${a.source_id}`, day: toLocalISO(d), sort: +d, a });
  }
  for (const w of workouts.value) {
    if (sinceIso && w.date < sinceIso) continue;
    const t = w.started_at ? +new Date(w.started_at) : +new Date(`${w.date}T12:00:00`);
    items.push({ kind: "strength", key: `s-${w.id}`, day: w.date, sort: t, w });
  }
  return items.sort((x, y) => y.sort - x.sort);
});

const typeChips = computed(() => {
  const present = new Set<string>();
  for (const a of activities.value) present.add(categoryForType(a.type));
  const chips = [{ key: "all", label: "All" }];
  for (const [k, label] of [["ride", "Ride"], ["run", "Run"], ["walk", "Walk / hike"], ["row", "Row"], ["other", "Other"]] as const) {
    if (present.has(k)) chips.push({ key: k, label });
  }
  if (workouts.value.length) chips.push({ key: "strength", label: "Strength" });
  return chips;
});

const filtered = computed(() => feed.value.filter((it) => {
  const t = typeFilter.value;
  if (t === "all") return true;
  if (t === "strength") return it.kind === "strength";
  return it.kind === "activity" && categoryForType(it.a.type) === t;
}));

function mondayOf(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y!, (m ?? 1) - 1, d ?? 1);
  dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
  return toLocalISO(dt);
}
const thisWeek = computed(() => mondayOf(toLocalISO(new Date())));
const thisMonth = computed(() => toLocalISO(new Date()).slice(0, 7) + "-01");
const weekTotals = computed<Record<string, YtdWeek>>(() =>
  Object.fromEntries((ytd.value?.weeks ?? []).map((w) => [w.week_start, w])),
);
const monthTotals = computed<Record<string, YtdMonth>>(() =>
  Object.fromEntries((ytd.value?.months ?? []).map((m) => [m.month_start, m])),
);

/** The value a sort orders by. Null (no distance, an unfinished session)
 *  sorts last — it is unknown, not zero. */
function sortValue(it: FeedItem): number | null {
  if (sortKey.value === "longest") {
    return it.kind === "activity" ? (it.a.duration_s || null) : (it.w.session_summary?.net_duration_s || null);
  }
  return it.kind === "activity" ? (it.a.distance_m || null) : null;
}
const sorted = computed<FeedItem[]>(() => {
  if (sortKey.value === "newest") return filtered.value;
  return [...filtered.value].sort((x, y) => {
    const a = sortValue(x), b = sortValue(y);
    if (a == null && b == null) return y.sort - x.sort;
    if (a == null) return 1;
    if (b == null) return -1;
    return b - a || y.sort - x.sort;
  });
});

interface FeedGroup { key: string; label: string | null; total: { sessions: number; duration_s: number } | null; items: FeedItem[] }
const groups = computed<FeedGroup[]>(() => {
  const page = sorted.value.slice(0, shown.value);
  // A ranked list is one list: headers by date would scatter it.
  if (sortKey.value !== "newest") return [{ key: "ranked", label: null, total: null, items: page }];
  const out: FeedGroup[] = [];
  for (const it of page) {
    const key = groupBy.value === "month" ? it.day.slice(0, 7) + "-01" : mondayOf(it.day);
    const last = out[out.length - 1];
    if (last && last.key === key) last.items.push(it);
    else out.push({
      key,
      label: groupBy.value === "month" ? monthLabel(key) : weekLabel(key),
      total: (groupBy.value === "month" ? monthTotals.value[key] : weekTotals.value[key]) ?? null,
      items: [it],
    });
  }
  return out;
});

function weekLabel(wk: string): string {
  if (wk === thisWeek.value) return "This week";
  const [y, m, d] = wk.split("-").map(Number);
  return "Week of " + new Date(y!, (m ?? 1) - 1, d ?? 1).toLocaleDateString([], { month: "short", day: "numeric" });
}
function monthLabel(mk: string): string {
  if (mk === thisMonth.value) return "This month";
  const [y, m] = mk.split("-").map(Number);
  return new Date(y!, (m ?? 1) - 1, 1).toLocaleDateString([], { month: "long", year: "numeric" });
}

function fmtHm(s: number | null | undefined): string {
  if (!s || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function rowWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y!, (m ?? 1) - 1, d ?? 1).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

const MUSCLES: Record<string, string> = {
  push: "Chest · Shoulders · Triceps", pull: "Back · Biceps", legs: "Quads · Hams · Glutes",
  upper: "Chest · Back · Arms", lower: "Quads · Hams · Glutes", full_body: "Full body",
  yoga: "Mobility flow", cardio: "Z2 effort",
};

function strengthTitle(w: Workout): string {
  if (w.split_focus === "yoga") return "Yoga flow";
  if (w.split_focus === "cardio") return "Cardio day";
  const f = w.split_focus.replace(/_/g, " ");
  return `${f.charAt(0).toUpperCase()}${f.slice(1)} day`;
}
/** Tonnage leads a lifting day; a yoga or cardio day leads with its time.
 *  Unfinished: nothing yet, and a dash would read as zero. */
function strengthPrimary(w: Workout): string {
  const s = w.session_summary;
  if (s && s.total_volume_lb > 0) {
    const v = weightVal(s.total_volume_lb * 0.45359237) ?? 0;
    return `${Math.round(v).toLocaleString()} ${weightUnit.value}`;
  }
  if (s?.net_duration_s) return fmtHm(s.net_duration_s);
  return "";
}
function strengthStatus(w: Workout): { label: string; tone: string } | null {
  if (w.status === "completed") return null;
  if (w.status === "in_progress" || w.status === "paused")
    return { label: w.status === "paused" ? "Paused" : "In progress", tone: "amber" };
  return { label: w.status.replace(/_/g, " "), tone: "muted" };
}
function tint(it: FeedItem): string {
  return categoryColor(it.kind === "activity" ? categoryForType(it.a.type) : categoryForSplitFocus(it.w.split_focus), true);
}

// ── YTD hero ──
const metric = (k: string): YtdMetric | null => ytd.value?.metrics.find((m) => m.key === k) ?? null;
const dist = computed(() => metric("distance_m"));

function deltaText(m: YtdMetric): string {
  if (m.note === "new") return "new";
  if (m.pct_change == null || m.direction === "flat") return "level";
  return `${m.pct_change >= 0 ? "↑" : "↓"} ${Math.abs(m.pct_change).toFixed(0)}%`;
}
const TONE: Record<string, string> = { positive: "#5dff3b", caution: "#ffb52e", neutral: "#9b9bb0" };
function fmtMetric(m: YtdMetric, v: number): string {
  if (m.key === "distance_m") return Math.round(distanceVal(v) ?? 0).toLocaleString();
  if (m.key === "elevation_m") return Math.round(elevationVal(v) ?? 0).toLocaleString();
  if (m.key === "duration_s") return Math.round(v / 3600).toLocaleString();
  return Math.round(v).toLocaleString();
}
function metricUnit(m: YtdMetric): string {
  if (m.key === "distance_m") return distanceUnit.value;
  if (m.key === "elevation_m") return elevationUnit.value;
  if (m.key === "duration_s") return "h";
  return "";
}
const SMALL = ["sessions", "duration_s", "elevation_m"];

const CW = 600, CH = 140;
const chart = computed(() => {
  const c = ytd.value?.cumulative_distance_m;
  if (!c) return null;
  const max = Math.max(1, ...c.this_year, ...c.last_year);
  const toPts = (s: number[]) => s.map((v, i) => `${((i / 364) * CW).toFixed(1)},${(CH - (v / max) * CH).toFixed(1)}`).join(" ");
  const last = c.this_year.length ? c.this_year[c.this_year.length - 1] : null;
  return {
    thisPts: toPts(c.this_year), lastPts: toPts(c.last_year),
    dot: last == null ? null : { x: ((c.this_year.length - 1) / 364) * CW, y: CH - (last / max) * CH },
  };
});

// ── Calendar: 3 months, expandable to the year ──
const calExpanded = ref(false);
const calDays = computed(() => {
  const idx: Record<string, string> = {};
  for (const a of activities.value) {
    const d = toLocalISO(new Date(a.start_at));
    idx[d] ??= categoryColor(categoryForType(a.type), true);
  }
  for (const w of workouts.value) {
    if (w.status !== "completed") continue;
    idx[w.date] ??= categoryColor(categoryForSplitFocus(w.split_focus), true);
  }
  const today = new Date();
  const monday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - ((today.getDay() + 6) % 7));
  const start = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() - 12 * 7);
  const cells: { x: number; y: number; color: string; iso: string }[] = [];
  for (let col = 0; col < 13; col++) {
    for (let row = 0; row < 7; row++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + col * 7 + row);
      if (d > today) continue;
      const iso = toLocalISO(d);
      cells.push({ x: col, y: row, color: idx[iso] ?? "#272a3b", iso });
    }
  }
  return cells;
});
const yearMin = computed(() => `${new Date().getFullYear()}-01-01`);
const calendarActivities = computed(() => activities.value);
</script>

<template>
  <NeonPage title="Activities" back="/train">
    <template #trailing>
      <div class="hdr-actions">
        <RouterLink to="/activities/map" class="icon-btn" title="Activity map" aria-label="Activity map"><MapIcon :size="18" /></RouterLink>
        <RouterLink to="/activities/compare" class="icon-btn" title="Compare two activities" aria-label="Compare"><GitCompareArrows :size="18" /></RouterLink>
        <button class="icon-btn" :disabled="syncing" title="Pull new Strava activities" aria-label="Sync Strava" @click="syncStravaNow">
          <RefreshCw :size="18" :class="{ spin: syncing }" />
        </button>
      </div>
    </template>

    <div v-if="error" class="stale" role="alert" @click="load">
      <strong>{{ feed.length ? "Couldn't refresh — showing saved activities" : "Couldn't load activities" }}</strong>
      <span>{{ error }}</span>
      <em>Tap to retry</em>
    </div>
    <div v-if="cookieNeedsReconnect" class="stale">
      <strong>Strava sync is disconnected</strong>
      <span>{{ cookieError ?? "Reconnect Strava in Settings to resume pulling activities." }}</span>
      <RouterLink to="/settings" class="stale-link">Reconnect →</RouterLink>
    </div>
    <p v-if="syncToast" class="toast">{{ syncToast }}</p>

    <div v-if="ytd" class="pills">
      <span class="pill cyan">This week · {{ ytd.this_week.sessions }}</span>
      <span v-if="ytd.this_week.duration_s > 0" class="pill peri">{{ fmtHm(ytd.this_week.duration_s) }}</span>
    </div>

    <NeonHero v-if="ytd" accent="#28e6ff">
      <NeonEyebrow style="margin-top: 0">{{ ytd.year }} year to date</NeonEyebrow>
      <template v-if="dist">
        <div class="ytd-top">
          <span class="ytd-big">{{ fmtMetric(dist, dist.current) }}</span>
          <span class="ytd-unit">{{ distanceUnit }}</span>
          <span class="ytd-delta" :style="{ color: TONE[dist.tone] }">{{ deltaText(dist) }}</span>
        </div>
        <p class="ytd-vs">vs {{ fmtMetric(dist, dist.prior) }} {{ distanceUnit }} by this day in {{ ytd.prior_year }}</p>
      </template>
      <svg v-if="chart" class="cum" :viewBox="`0 0 ${CW} ${CH}`" preserveAspectRatio="none" role="img"
           :aria-label="`Cumulative distance ${ytd.year} against ${ytd.prior_year}`">
        <line v-for="q in 3" :key="q" :x1="(CW * q) / 4" :x2="(CW * q) / 4" y1="0" :y2="CH" class="grid" />
        <polyline :points="chart.lastPts" class="line-last" vector-effect="non-scaling-stroke" />
        <polyline :points="chart.thisPts" class="line-glow" vector-effect="non-scaling-stroke" />
        <polyline :points="chart.thisPts" class="line-this" vector-effect="non-scaling-stroke" />
      </svg>
      <div class="months"><span>Jan</span><span>Apr</span><span>Jul</span><span>Oct</span></div>
      <div class="legend">
        <span><i class="sw solid" /> {{ ytd.year }}</span>
        <span><i class="sw dashed" /> {{ ytd.prior_year }}</span>
      </div>
      <div class="ytd-small">
        <div v-for="k in SMALL" :key="k">
          <template v-if="metric(k)">
            <div class="ys-v">{{ fmtMetric(metric(k)!, metric(k)!.current) }}<small>{{ metricUnit(metric(k)!) }}</small></div>
            <div class="ys-l">{{ metric(k)!.label }}</div>
            <div class="ys-d" :style="{ color: TONE[metric(k)!.tone] }">{{ deltaText(metric(k)!) }}</div>
          </template>
        </div>
      </div>
    </NeonHero>
    <NeonHero v-else-if="loading" accent="#28e6ff">
      <NeonEyebrow style="margin-top: 0">Year to date</NeonEyebrow>
      <p class="muted">Loading the year…</p>
    </NeonHero>

    <section v-if="feed.length" class="card cal">
      <div class="cal-head">
        <span class="eyebrow">{{ calExpanded ? `${new Date().getFullYear()} calendar` : "Last 3 months" }}</span>
        <button class="link" @click="calExpanded = !calExpanded">{{ calExpanded ? "Show less" : "Show year" }}</button>
      </div>
      <ActivityYearCalendar v-if="calExpanded" :activities="calendarActivities" :workouts="workouts" :min-date="yearMin" compact />
      <svg v-else class="strip" :viewBox="`0 0 ${13 * 17} ${7 * 17}`" role="img" aria-label="Activity over the last 13 weeks">
        <rect v-for="c in calDays" :key="c.iso" :x="c.x * 17" :y="c.y * 17" width="14" height="14" rx="3" :fill="c.color">
          <title>{{ c.iso }}</title>
        </rect>
      </svg>
    </section>

    <div class="chips" role="group" aria-label="Date range">
      <button v-for="r in RANGES" :key="r.key" class="chip" :class="{ on: range === r.key }" @click="range = r.key">{{ r.label }}</button>
    </div>
    <div v-if="typeChips.length > 2" class="chips" role="group" aria-label="Activity type">
      <button v-for="t in typeChips" :key="t.key" class="chip" :class="{ on: typeFilter === t.key }" @click="typeFilter = t.key">{{ t.label }}</button>
    </div>

    <p v-if="summaryFailed" class="stale-note">Couldn't refresh the period totals{{ stats || records ? " — showing the last ones loaded" : "" }}.</p>
    <section v-if="stats && feed.length" class="period" aria-label="Period totals">
      <span class="eyebrow">{{ stats.period_label }}</span>
      <div class="period-grid">
        <NeonStat :value="stats.n_activities.toLocaleString()" :label="stats.n_activities === 1 ? 'session' : 'sessions'" />
        <NeonStat :value="stats.n_with_distance === 0 ? '—' : fmtDistance(stats.total_distance_m, 0)" label="distance" />
        <NeonStat :value="fmtHm(stats.total_duration_s)" label="time" />
        <NeonStat :value="stats.n_with_elevation === 0 ? '—' : fmtElevation(stats.total_elevation_m)" label="climbed" />
        <NeonStat :value="stats.n_with_kcal === 0 ? '—' : Math.round(stats.total_kcal).toLocaleString()" label="kcal" />
      </div>
    </section>

    <section v-if="records && typeFilter !== 'strength' && feed.length" class="card recs" aria-label="Personal records">
      <span class="eyebrow">Personal records · {{ stats?.period_label ?? "selected range" }}</span>
      <p v-if="!shownRecords.length" class="muted">No records in this range yet.</p>
      <div v-else class="rec-grid">
        <RouterLink v-for="r in shownRecords" :key="r.key" class="rec"
                    :to="`/activity/${r.activity!.source}/${r.activity!.source_id}`">
          <NeonStat :value="fmtRecord(r)" :label="r.label" accent="#28e6ff" />
          <span class="rec-name">{{ r.activity!.name || fmtActivityType(r.activity!.type) }}</span>
          <span class="rec-meta">{{ recordDay(r.activity!.date) }}</span>
        </RouterLink>
      </div>
    </section>

    <div v-if="feed.length" class="chips view-bar" role="group" aria-label="Sort and layout">
      <button v-for="o in SORTS" :key="o.key" class="chip" :class="{ on: sortKey === o.key }" @click="sortKey = o.key">{{ o.label }}</button>
      <span class="sep" />
      <template v-if="sortKey === 'newest'">
        <button class="chip" :class="{ on: groupBy === 'week' }" @click="groupBy = 'week'">By week</button>
        <button class="chip" :class="{ on: groupBy === 'month' }" @click="groupBy = 'month'">By month</button>
        <span class="sep" />
      </template>
      <button class="chip" :class="{ on: viewMode === 'list' }" aria-label="List view" @click="viewMode = 'list'">List</button>
      <button class="chip" :class="{ on: viewMode === 'grid' }" aria-label="Grid view" @click="viewMode = 'grid'">Grid</button>
    </div>

    <p v-if="!feed.length && loading" class="muted">Loading activities…</p>
    <!-- A failed load with nothing cached is not "no activities yet". -->
    <template v-else-if="!feed.length && error" />
    <p v-else-if="!feed.length" class="card quiet">No activities yet. Connect Strava in Settings or log a strength workout.</p>
    <p v-else-if="!filtered.length" class="card quiet">No activities match these filters.</p>

    <template v-else>
      <section v-for="g in groups" :key="g.key">
        <div v-if="g.label" class="week-h">
          <span>{{ g.label }}</span>
          <span v-if="g.total">
            {{ g.total.sessions }} session{{ g.total.sessions === 1 ? "" : "s" }} · {{ fmtHm(g.total.duration_s) }}
          </span>
        </div>
        <div :class="viewMode === 'grid' ? 'feed-grid' : 'feed-list'">
        <RouterLink v-for="it in g.items" :key="it.key" class="row"
                    :to="it.kind === 'activity' ? `/activity/${it.a.source}/${it.a.source_id}` : `/workout/strength/day/${it.w.date}`">
          <template v-if="it.kind === 'activity'">
            <PolylineThumbnail v-if="it.a.polyline" class="thumb" :polyline="it.a.polyline" :activity-type="it.a.type" :size="viewMode === 'grid' ? 72 : 44" :stroke="tint(it)" />
            <span v-else class="ic" :style="{ color: tint(it), background: tint(it) + '24' }"><ActivityIcon :type="it.a.type" :size="20" /></span>
            <span class="body">
              <span class="title">{{ it.a.name || fmtActivityType(it.a.type) }}</span>
              <span class="sub">{{ [rowWhen(it.a.start_at), it.a.distance_m ? fmtDistance(it.a.distance_m, 1) : null, it.a.trail_name].filter(Boolean).join(" · ") }}</span>
            </span>
            <span class="primary" :style="{ color: tint(it) }">{{ fmtHm(it.a.duration_s) }}</span>
          </template>
          <template v-else>
            <span class="ic" :style="{ color: tint(it), background: tint(it) + '24' }"><ActivityIcon :type="it.w.split_focus === 'yoga' ? 'yoga' : it.w.split_focus === 'cardio' ? 'ride' : 'strength'" :size="20" /></span>
            <span class="body">
              <span class="title">{{ strengthTitle(it.w) }}</span>
              <span class="sub">{{ [dayLabel(it.w.date), MUSCLES[it.w.split_focus] ?? it.w.split_focus, it.w.session_summary?.working_sets ? `${it.w.session_summary.working_sets} sets` : null].filter(Boolean).join(" · ") }}</span>
            </span>
            <span class="primary-col">
              <span v-if="strengthPrimary(it.w)" class="primary" :style="{ color: tint(it) }">{{ strengthPrimary(it.w) }}</span>
              <span v-if="strengthStatus(it.w)" class="status" :class="strengthStatus(it.w)!.tone">{{ strengthStatus(it.w)!.label }}</span>
            </span>
          </template>
        </RouterLink>
        </div>
      </section>
      <div v-if="sorted.length > shown" class="more">
        <button class="pill cyan" @click="shown += 40">Show {{ Math.min(40, filtered.length - shown) }} more</button>
      </div>
    </template>
  </NeonPage>
</template>

<style scoped>
.hdr-actions { display: flex; gap: 8px; }
.icon-btn { width: 42px; height: 42px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(40, 230, 255, .14); border: 1px solid rgba(40, 230, 255, .45); color: var(--rn-cyan); cursor: pointer; }
.icon-btn:disabled { opacity: .5; cursor: default; }
.icon-btn:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.stale { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; margin-bottom: 12px; border-radius: 14px;
  background: rgba(255, 181, 46, .10); border: 1px solid rgba(255, 181, 46, .32); cursor: pointer; }
.stale strong { color: var(--rn-amber); font-size: 13px; }
.stale span { color: var(--rn-mut); font-size: 12px; }
.stale em { color: var(--rn-cyan); font-size: 12px; font-style: normal; font-weight: 600; }
.stale-link { color: var(--rn-cyan); font-size: 12px; font-weight: 600; text-decoration: none; }
.toast { color: var(--rn-mut); font-size: 12px; margin: 0 0 8px; }
.muted { color: var(--rn-mut); font-size: 13px; }

.pills { display: flex; gap: 8px; margin-bottom: 12px; }
.pill { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 12px; padding: 6px 12px; border-radius: 999px; border: 1px solid; }
.pill.cyan { color: var(--rn-cyan); background: rgba(40, 230, 255, .12); border-color: rgba(40, 230, 255, .4); cursor: pointer; }
.pill.peri { color: var(--rn-peri); background: rgba(111, 123, 255, .12); border-color: rgba(111, 123, 255, .4); }

.ytd-top { display: flex; align-items: baseline; gap: 6px; }
.ytd-big { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 44px; letter-spacing: -1px; color: var(--rn-cyan); line-height: 1; }
.ytd-unit { color: var(--rn-mut); font-size: 15px; }
.ytd-delta { margin-left: auto; font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 15px; }
.ytd-vs { color: var(--rn-mut); font-size: 12px; margin: 4px 0 10px; }
.cum { width: 100%; height: 110px; display: block; }
.cum .grid { stroke: var(--rn-track); stroke-width: 1; vector-effect: non-scaling-stroke; }
.line-last { fill: none; stroke: var(--rn-peri); stroke-width: 1.5; stroke-dasharray: 6 5; opacity: .85; }
.line-glow { fill: none; stroke: var(--rn-cyan); stroke-width: 6; opacity: .25; stroke-linecap: round; }
.line-this { fill: none; stroke: var(--rn-cyan); stroke-width: 2.5; stroke-linecap: round; }
.months { display: grid; grid-template-columns: repeat(4, 1fr); color: var(--rn-mut); font-size: 10px; margin-top: 2px; }
.legend { display: flex; gap: 14px; color: var(--rn-mut); font-size: 11px; margin-top: 4px; }
.sw { display: inline-block; width: 18px; height: 0; border-top: 2px solid var(--rn-cyan); vertical-align: middle; margin-right: 4px; }
.sw.dashed { border-top: 2px dashed var(--rn-peri); }
.ytd-small { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }
.ys-v { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 20px; }
.ys-v small { color: var(--rn-mut); font-size: 11px; margin-left: 3px; font-weight: 500; }
.ys-l { color: var(--rn-mut); font-size: 11px; }
.ys-d { font-size: 11px; font-weight: 600; }

.card { background: var(--rn-card); border: 1px solid var(--rn-line); border-radius: 18px; padding: 14px; margin-bottom: 12px; }
.quiet { color: var(--rn-mut); font-size: 14px; }
.cal-head { display: flex; align-items: center; margin-bottom: 8px; }
.eyebrow { flex: 1; font-family: 'Space Grotesk', monospace; font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: var(--rn-mut); }
.link { background: none; border: 0; color: var(--rn-cyan); font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; min-height: 32px; padding: 0 8px; }
.strip { width: 100%; max-width: 240px; display: block; }

.chips { display: flex; gap: 6px; overflow-x: auto; margin-bottom: 8px; padding-bottom: 2px; }
.chip { min-height: 36px; padding: 0 14px; border-radius: 999px; border: 1px solid var(--rn-line); background: var(--rn-card);
  color: var(--rn-mut); font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }
.chip.on { background: rgba(40, 230, 255, .14); border-color: rgba(40, 230, 255, .45); color: var(--rn-cyan); font-weight: 700; }

.week-h { display: flex; justify-content: space-between; margin: 16px 0 8px; font-family: 'Space Grotesk', monospace;
  font-size: 11px; color: var(--rn-mut); }
.week-h span:first-child { font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; margin-bottom: 8px; border-radius: 18px;
  background: var(--rn-card); border: 1px solid var(--rn-line); color: inherit; text-decoration: none; }
.row:hover { border-color: rgba(40, 230, 255, .45); }
.row:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.ic { width: 40px; height: 40px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.thumb { flex: 0 0 auto; }
.body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.title { font-weight: 600; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub { color: var(--rn-mut); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.primary { font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 16px; white-space: nowrap; }
.primary-col { display: flex; flex-direction: column; align-items: flex-end; }
.status { font-size: 11px; font-weight: 700; }
.status.amber { color: var(--rn-amber); }
.status.muted { color: var(--rn-mut); text-transform: capitalize; }
.more { display: flex; justify-content: center; margin: 8px 0 16px; }

/* UI-F2 */
.stale-note { color: var(--rn-amber); font-size: 12px; margin: 4px 0 8px; }
.period { margin: 8px 0 12px; }
.period .eyebrow { display: block; margin-bottom: 8px; }
.period-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 560px) { .period-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.recs .eyebrow { display: block; margin-bottom: 10px; }
.rec-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.rec { display: flex; flex-direction: column; gap: 4px; color: inherit; text-decoration: none; border-radius: 18px; }
.rec:hover :deep(.neon-stat) { border-color: rgba(40, 230, 255, .45); }
.rec:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.rec-name, .rec-meta { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 4px; }
.rec-name { color: var(--rn-ink, #ececf5); font-size: 12px; }
.rec-meta { color: var(--rn-mut); margin-top: -4px; }
.view-bar { align-items: center; }
.sep { flex: 0 0 1px; align-self: stretch; background: var(--rn-line); margin: 6px 2px; }
.feed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; margin-bottom: 8px; }
.feed-grid .row { margin-bottom: 0; flex-wrap: wrap; align-items: flex-start; }
.feed-grid .row .body { flex: 1 1 100%; order: 3; }
.feed-grid .row .primary, .feed-grid .row .primary-col { margin-left: auto; }
</style>
