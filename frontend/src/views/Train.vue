<script setup lang="ts">
/**
 * Train — unified Workout + Cardio + Trails screen of the "Vitality Neon"
 * redesign (mockup: tab_train.html). Mirrors the Rings.vue pattern: scoped
 * neon tokens on the `.train-view` wrapper, onMounted fan-out fetch with
 * per-call `.catch` fallbacks, defensive null handling, and router.push
 * drill-nav into the existing detail views.
 *
 * Real data: today's generated strength workout (hero) + the recent
 * activities feed. Everything is rendered through `—` when null.
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { Activity, StrengthWorkoutDetail } from "@/api/types";

const router = useRouter();
const loading = ref(true);

const workout = ref<StrengthWorkoutDetail | null>(null);
const activities = ref<Activity[]>([]);

const segment = ref<"strength" | "cardio" | "trails">("strength");

const C = 2 * Math.PI * 42; // hero ring circumference

async function load(): Promise<void> {
  loading.value = true;
  const [w, acts] = await Promise.all([
    api.strengthToday().catch(() => null),
    api.activities({ limit: 6 }).catch(() => [] as Activity[]),
  ]);
  workout.value = w ?? null;
  activities.value = Array.isArray(acts) ? acts : [];
  loading.value = false;
}
onMounted(load);

function go(path: string): void {
  router.push(path);
}

// ── This-week pill: activities started within the trailing 7 days ─────
const weekCount = computed<number>(() => {
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  return activities.value.filter((a) => {
    const t = a?.start_at ? Date.parse(a.start_at) : NaN;
    return !Number.isNaN(t) && t >= cutoff;
  }).length;
});

// ── Hero ring: completed exercises / total ────────────────────────────
const totalExercises = computed<number | null>(() => {
  const ex = workout.value?.exercises;
  return Array.isArray(ex) ? ex.length : null;
});

const doneExercises = computed<number>(() => {
  const ex = workout.value?.exercises;
  if (!Array.isArray(ex)) return 0;
  return ex.filter((e) => {
    const sets = e?.sets;
    const target = e?.target_sets ?? 0;
    if (!Array.isArray(sets) || sets.length === 0 || target <= 0) return false;
    // "Done" = every prescribed set is either logged or explicitly skipped.
    const accounted = sets.filter(
      (s) => s?.skipped === true || s?.logged_at != null,
    ).length;
    return accounted >= target;
  }).length;
});

const ringPct = computed<number>(() => {
  const total = totalExercises.value;
  if (total == null || total <= 0) return 0;
  return Math.max(0, Math.min(100, (doneExercises.value / total) * 100));
});

const ringDash = computed<string>(() => {
  const len = (ringPct.value / 100) * C;
  return `${len.toFixed(1)} ${C.toFixed(1)}`;
});

const ringLabel = computed<string>(() => {
  const total = totalExercises.value;
  if (total == null) return "—";
  return `${doneExercises.value}/${total}`;
});

// ── Hero copy ─────────────────────────────────────────────────────────
function titleCase(s: string): string {
  return s
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const splitLabel = computed<string>(() => {
  const sf = workout.value?.split_focus;
  return sf ? titleCase(sf) : "Rest Day";
});

const heroTag = computed<string>(() => {
  const sf = workout.value?.split_focus;
  if (!sf) return "Today";
  const t = titleCase(sf);
  return /day$/i.test(t) ? t : `${t} Day`;
});

const heroMinutes = computed<string>(() => {
  // No prescribed-minutes field on the plan — derive a coarse estimate
  // from exercise count (≈7 min/exercise), else fall back to placeholder.
  const total = totalExercises.value;
  if (total == null || total <= 0) return "—";
  return String(total * 7);
});

const isRest = computed<boolean>(() => {
  const sf = workout.value?.split_focus ?? "";
  return workout.value == null || /rest/i.test(sf);
});

// ── Recent activities feed ────────────────────────────────────────────
interface FeedRow {
  key: string;
  name: string;
  sub: string;
  icon: string;
  tone: "lime" | "cyan" | "amber" | "mag";
  value: string;
  unit: string;
}

function relDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const d = new Date(t);
  const today = new Date();
  const dayMs = 24 * 60 * 60 * 1000;
  const diff = Math.floor(
    (new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() -
      new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) /
      dayMs,
  );
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function miles(distance_m: number | null | undefined): string | null {
  if (distance_m == null || distance_m <= 0) return null;
  return `${(distance_m / 1609.344).toFixed(1)} mi`;
}

function feet(elev_m: number | null | undefined): string | null {
  if (elev_m == null || elev_m <= 0) return null;
  return Math.round(elev_m * 3.28084).toLocaleString();
}

function hms(duration_s: number | null | undefined): string {
  if (duration_s == null || duration_s <= 0) return "—";
  const total = Math.round(duration_s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}`;
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function classifyType(type: string | null | undefined): {
  icon: string;
  tone: FeedRow["tone"];
  isTrail: boolean;
  isStrength: boolean;
} {
  const t = (type ?? "").toLowerCase();
  const isStrength =
    t.includes("strength") || t.includes("weight") || t.includes("workout");
  const isTrail = t.includes("trail") || t.includes("hike") || t.includes("run");
  if (isStrength) return { icon: "🏋", tone: "lime", isTrail: false, isStrength: true };
  if (isTrail) return { icon: "⛰", tone: "amber", isTrail: true, isStrength: false };
  if (t.includes("ride") || t.includes("bike") || t.includes("cycl"))
    return { icon: "🚴", tone: "cyan", isTrail: false, isStrength: false };
  if (t.includes("swim"))
    return { icon: "🏊", tone: "cyan", isTrail: false, isStrength: false };
  if (t.includes("row"))
    return { icon: "🚣", tone: "cyan", isTrail: false, isStrength: false };
  return { icon: "🏃", tone: "cyan", isTrail: false, isStrength: false };
}

const recent = computed<FeedRow[]>(() =>
  activities.value.map((a, i): FeedRow => {
    const cls = classifyType(a?.type);
    const name = a?.name?.trim() || (a?.type ? titleCase(a.type) : "Activity");
    const day = relDay(a?.start_at);
    const dist = miles(a?.distance_m);
    const ft = feet(a?.elevation_gain_m);

    // Sub-line: day · distance (or type detail)
    const subParts = [day];
    if (dist) subParts.push(dist);
    else if (a?.type) subParts.push(titleCase(a.type));
    const sub = subParts.filter(Boolean).join(" · ");

    // Primary value: elevation for trail-ish rows, else duration.
    let value = "—";
    let unit = "";
    if (cls.isTrail && ft) {
      value = ft;
      unit = "ft";
    } else if (cls.isStrength) {
      value = hms(a?.duration_s);
      unit = "";
    } else {
      value = hms(a?.duration_s);
      unit = "";
    }

    return {
      key: `${a?.source ?? "x"}-${a?.source_id ?? i}`,
      name,
      sub,
      icon: cls.icon,
      tone: cls.tone,
      value,
      unit,
    };
  }),
);
</script>

<template>
  <div class="train-view">
    <header class="head">
      <h1>Train</h1>
      <button class="weekchip" @click="go('/activities')">
        This week · {{ weekCount }}
      </button>
    </header>

    <!-- Segment toggle -->
    <div class="seg" role="tablist">
      <button
        class="sp"
        :class="{ on: segment === 'strength' }"
        @click="segment = 'strength'"
      >
        Strength
      </button>
      <button
        class="sp"
        :class="{ on: segment === 'cardio' }"
        @click="segment = 'cardio'"
      >
        Cardio
      </button>
      <button
        class="sp"
        :class="{ on: segment === 'trails' }"
        @click="segment = 'trails'"
      >
        Trails
      </button>
    </div>

    <!-- Hero "Today" workout -->
    <div class="cap">Today</div>
    <button class="hero" @click="go('/workout/strength/today')">
      <div class="ring">
        <svg viewBox="0 0 96 96" width="96" height="96">
          <circle
            cx="48"
            cy="48"
            r="42"
            fill="none"
            stroke="var(--rn-track)"
            stroke-width="8"
          />
          <circle
            cx="48"
            cy="48"
            r="42"
            fill="none"
            stroke="var(--rn-lime)"
            stroke-width="8"
            stroke-linecap="round"
            :stroke-dasharray="ringDash"
            transform="rotate(-90 48 48)"
            style="filter: drop-shadow(0 0 5px var(--rn-lime))"
          />
        </svg>
        <div class="ringtxt">
          <b class="lime">{{ ringLabel }}</b>
          <span>Done</span>
        </div>
      </div>
      <div class="herobody">
        <div class="tag">{{ heroTag }}</div>
        <h2>{{ splitLabel }}</h2>
        <div class="meta">
          <b>{{ heroMinutes }}</b> min · RPE <b>—</b>
        </div>
        <span class="cont">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
          >
            <path d="M5 3l14 9-14 9z" />
          </svg>
          {{ isRest ? "View" : "Continue" }}
        </span>
      </div>
    </button>

    <!-- Recent feed -->
    <div class="cap">Recent</div>

    <template v-if="recent.length > 0">
      <button
        v-for="row in recent"
        :key="row.key"
        class="pill"
        @click="go('/activities')"
      >
        <span class="pi" :class="`bg-${row.tone}`" :style="{ color: 'inherit' }">
          {{ row.icon }}
        </span>
        <span class="pn">
          {{ row.name }}
          <small>{{ row.sub }}</small>
        </span>
        <span class="pv" :class="row.tone">
          <b>{{ row.value }}</b><template v-if="row.unit"> {{ row.unit }}</template>
        </span>
        <span class="chev">›</span>
      </button>
    </template>

    <button v-else class="pill empty" @click="go('/activities')">
      <span class="pi bg-cyan">🏃</span>
      <span class="pn">
        No recent activity
        <small>Tap to open your feed</small>
      </span>
      <span class="chev">›</span>
    </button>

    <!-- Catalog shortcut -->
    <button class="catalog" @click="go('/workout/strength/catalog')">
      <span>Exercise catalog</span>
      <span class="chev">›</span>
    </button>
  </div>
</template>

<style scoped>
.train-view {
  --rn-bg: #0f1118;
  --rn-card: #181b27;
  --rn-ink: #ececf5;
  --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8;
  --rn-lime: #5dff3b;
  --rn-cyan: #28e6ff;
  --rn-amber: #ffb52e;
  --rn-track: #272a3b;
  min-height: 100vh;
  margin: -1.25rem -1.5rem;
  padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink);
  font-family: "Plus Jakarta Sans", "Geist", system-ui;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.head h1 {
  font-size: 30px;
  font-weight: 800;
  margin: 0;
  letter-spacing: -0.5px;
}
.weekchip {
  font-family: "Space Grotesk", "Geist Mono", monospace;
  font-weight: 700;
  font-size: 13px;
  color: var(--rn-lime);
  background: rgba(93, 255, 59, 0.12);
  border: 1px solid rgba(93, 255, 59, 0.25);
  padding: 5px 12px;
  border-radius: 20px;
  cursor: pointer;
  transition: transform 0.12s ease;
}
.weekchip:active {
  transform: scale(0.96);
}

.cap {
  font-family: "Space Grotesk", "Geist Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--rn-mut);
  text-transform: uppercase;
  margin: 6px 0 11px;
}

.seg {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.seg .sp {
  flex: 1;
  text-align: center;
  font-weight: 700;
  font-size: 14px;
  padding: 11px 0;
  border-radius: 16px;
  background: var(--rn-card);
  color: var(--rn-mut);
  border: 1px solid transparent;
  cursor: pointer;
  transition: transform 0.12s ease;
}
.seg .sp:active {
  transform: scale(0.97);
}
.seg .sp.on {
  color: #0f1118;
  background: var(--rn-lime);
  border-color: var(--rn-lime);
  box-shadow: 0 0 18px rgba(93, 255, 59, 0.4);
}

.hero {
  display: flex;
  align-items: center;
  gap: 18px;
  width: 100%;
  text-align: left;
  background: linear-gradient(135deg, #1c2235, #181b27);
  border: 1px solid rgba(93, 255, 59, 0.18);
  border-radius: 24px;
  padding: 18px;
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
  cursor: pointer;
  color: inherit;
  transition: transform 0.12s ease;
}
.hero:active {
  transform: scale(0.99);
}
.hero::after {
  content: "";
  position: absolute;
  top: -40%;
  right: -20%;
  width: 160px;
  height: 160px;
  background: radial-gradient(circle, rgba(93, 255, 59, 0.18), transparent 70%);
  pointer-events: none;
}
.ring {
  position: relative;
  width: 96px;
  height: 96px;
  flex: 0 0 auto;
  filter: drop-shadow(0 0 10px rgba(93, 255, 59, 0.5));
}
.ring svg {
  display: block;
}
.ringtxt {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.ringtxt b {
  font-family: "Space Grotesk", "Geist Mono", monospace;
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}
.ringtxt span {
  font-size: 10px;
  font-weight: 700;
  color: var(--rn-mut);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-top: 2px;
}
.herobody {
  flex: 1;
  min-width: 0;
  position: relative;
  z-index: 1;
}
.herobody .tag {
  font-family: "Space Grotesk", "Geist Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--rn-lime);
  text-transform: uppercase;
}
.herobody h2 {
  margin: 4px 0 5px;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.3px;
}
.herobody .meta {
  color: var(--rn-mut);
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 12px;
}
.herobody .meta b {
  color: var(--rn-ink);
  font-family: "Space Grotesk", "Geist Mono", monospace;
}
.cont {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: var(--rn-lime);
  color: #0f1118;
  font-weight: 800;
  font-size: 13px;
  padding: 9px 16px;
  border-radius: 14px;
  box-shadow: 0 0 16px rgba(93, 255, 59, 0.45);
}
.cont svg {
  width: 15px;
  height: 15px;
}

.pill {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  background: var(--rn-card);
  border: 0;
  border-radius: 20px;
  padding: 14px 16px;
  margin-bottom: 11px;
  cursor: pointer;
  color: inherit;
  text-align: left;
  transition: transform 0.12s ease;
}
.pill:active {
  transform: scale(0.985);
}
.pill .pi {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  font-size: 18px;
}
.pill .pn {
  flex: 1;
  min-width: 0;
  font-weight: 700;
  font-size: 16px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pill .pn small {
  display: block;
  color: var(--rn-mut);
  font-weight: 500;
  font-size: 12px;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pill .pv {
  font-family: "Space Grotesk", "Geist Mono", monospace;
  font-weight: 700;
  font-size: 14px;
  color: var(--rn-mut);
  flex: 0 0 auto;
}
.pill .pv b {
  color: var(--rn-ink);
}
.pill .chev {
  color: var(--rn-mut);
  font-size: 18px;
  flex: 0 0 auto;
}
.pill.empty .pi {
  color: var(--rn-cyan);
}

.lime {
  color: var(--rn-lime);
}
.cyan {
  color: var(--rn-cyan);
}
.amber {
  color: var(--rn-amber);
}
.mag {
  color: var(--rn-mag);
}
.pv.lime b {
  color: var(--rn-lime);
}
.pv.cyan b {
  color: var(--rn-cyan);
}
.pv.amber b {
  color: var(--rn-amber);
}
.pv.mag b {
  color: var(--rn-mag);
}
.bg-mag {
  background: rgba(255, 58, 216, 0.14);
}
.bg-lime {
  background: rgba(93, 255, 59, 0.14);
}
.bg-cyan {
  background: rgba(40, 230, 255, 0.14);
}
.bg-amber {
  background: rgba(255, 181, 46, 0.14);
}

.catalog {
  width: 100%;
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: none;
  border: 1px solid #23263a;
  border-radius: 18px;
  padding: 14px 16px;
  color: var(--rn-mut);
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: transform 0.12s ease;
}
.catalog:active {
  transform: scale(0.985);
}
.catalog .chev {
  font-size: 18px;
}
</style>
