<script setup lang="ts">
/**
 * Collapsible left side navigation, modelled on the design handed off
 * via Claude Design (XwME6vq9CVxd8SITRhPxeg).
 *
 * - 232px expanded, 60px collapsed (state persisted in localStorage)
 * - Brand row with gradient logo + live backend pulse
 * - Optional ⌘K search row when expanded
 * - Workspace section with grouped items (Vitals / Activity expand inline)
 * - Sub-rail children show live values in their status colors
 * - Footer user/server card (collapsed mode hides it)
 * - Mobile (<= 700px): hidden by default, toggled via a hamburger handled
 *   by the parent App shell.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import {
  Activity, AlertTriangle, BarChart3, Bed, Calendar, ChevronDown,
  ChevronRight, Droplets, Edit3, Footprints, Github, GitCompare,
  Heart, Home, List, Map, Menu, RotateCcw, Scale, Search, Settings, Sparkles,
  Terminal, Thermometer, TrendingUp, type LucideIcon,
} from "lucide-vue-next";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import { fmtWeight, fmtDistance, weightVal, distanceUnit } from "@/units";
import AppLogo from "@/components/AppLogo.vue";

type Child = {
  to: string;
  icon: LucideIcon;
  label: string;
  sub?: string | null;
  subColor?: string;
};
type Group = {
  id: string;
  to?: string;
  icon: LucideIcon;
  label: string;
  badge?: string;
  badgeColor?: string;
  children?: Child[];
};

const COLLAPSED_KEY = "myvitals.sidenav.collapsed";
const EXPANDED_GROUPS_KEY = "myvitals.sidenav.expanded";

const collapsed = ref<boolean>(localStorage.getItem(COLLAPSED_KEY) === "1");
const expanded = ref<Record<string, boolean>>(
  JSON.parse(localStorage.getItem(EXPANDED_GROUPS_KEY) || '{"vitals":true}'),
);
watch(collapsed, (v) => localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0"));
watch(expanded, (v) => localStorage.setItem(EXPANDED_GROUPS_KEY, JSON.stringify(v)),
  { deep: true });

const route = useRoute();

// ── Live values for sub-rails / badges ──────────────────────────
const summary = ref<Awaited<ReturnType<typeof api.todaySummary>> | null>(null);
const activitiesCount = ref<number | null>(null);
const activitiesDistanceM = ref<number | null>(null);
const discoveriesCount = ref<number | null>(null);
const alertsCount = ref<number | null>(null);
const backendOk = ref<boolean | null>(null);
const lastSyncAt = ref<Date | null>(null);
const lastAttemptAt = ref<Date | null>(null);
const permissionsLost = ref(false);
const permsMissing = ref<string[] | null>(null);
const soberDays = ref<number | null>(null);
const backendVersion = ref<string | null>(null);
const nowTick = ref(Date.now());

async function refreshSidebarData() {
  try {
    const [s, stats, disc, sync, sober] = await Promise.all([
      api.todaySummary().catch(() => null),
      api.activitiesStats(365).catch(() => null),
      api.discoveries(90).catch(() => []),
      api.lastSync().catch(() => null),
      api.soberCurrent().catch(() => null),
    ]);
    summary.value = s;
    if (stats) {
      activitiesCount.value = stats.n_activities;
      activitiesDistanceM.value = stats.total_distance_m;
    }
    discoveriesCount.value = disc?.length ?? 0;
    soberDays.value = sober?.days ?? null;
    lastSyncAt.value = sync?.last_sync ? new Date(sync.last_sync) : null;
    lastAttemptAt.value = sync?.last_attempt ? new Date(sync.last_attempt) : null;
    permissionsLost.value = !!sync?.permissions_lost;
    permsMissing.value = sync?.perms_missing ?? null;
    backendOk.value = true;
  } catch {
    backendOk.value = false;
  }
}

function relTime(d: Date | null, now: number): string {
  if (!d) return "no data";
  const s = Math.max(0, Math.floor((now - d.getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days}d ago`;
}
// Show "last attempt" rather than "newest vital" so the chip means the
// same thing as the phone app's status pill ("phone tried X ago").
// Falls back to lastSync if heartbeats aren't yet flowing (older APK).
const lastSyncLabel = computed(() =>
  relTime(lastAttemptAt.value ?? lastSyncAt.value, nowTick.value)
);

// Sync-health derivation. Three buckets:
//  - "ok"     — recent attempt + no perms issue (green)
//  - "perms"  — phone tried but HC perms revoked (amber/red)
//  - "stale"  — phone hasn't checked in for >30 min (amber)
//  - "off"    — backend unreachable from this browser (red)
type SyncStatus = "ok" | "perms" | "stale" | "off";
const syncStatus = computed<SyncStatus>(() => {
  if (backendOk.value === false) return "off";
  if (permissionsLost.value) return "perms";
  // If we never received a heartbeat, fall back to the data-freshness signal.
  const ts = lastAttemptAt.value ?? lastSyncAt.value;
  if (!ts) return "stale";
  const ageMin = (nowTick.value - ts.getTime()) / 60000;
  if (ageMin > 30) return "stale";
  return "ok";
});

const syncChipText = computed(() => {
  if (backendOk.value === false) return "offline";
  if (permissionsLost.value) return "perms lost";
  return `synced ${lastSyncLabel.value}`;
});

const syncChipTitle = computed(() => {
  const lines: string[] = [];
  if (lastSyncAt.value) lines.push(`Last data: ${fmtDateTime(lastSyncAt.value)}`);
  if (lastAttemptAt.value) lines.push(`Last attempt: ${fmtDateTime(lastAttemptAt.value)}`);
  if (permsMissing.value?.length) lines.push(`Missing perms: ${permsMissing.value.join(", ")}`);
  if (lines.length === 0) return "No sync data yet";
  return lines.join("\n");
});

let pollHandle: ReturnType<typeof setInterval> | null = null;
let tickHandle: ReturnType<typeof setInterval> | null = null;
onMounted(() => {
  refreshSidebarData();
  // /version is stable per deploy — fetch once, no need to poll.
  api.version().then((v) => { backendVersion.value = v.version; }).catch(() => {});
  pollHandle = setInterval(refreshSidebarData, 60_000);
  tickHandle = setInterval(() => { nowTick.value = Date.now(); }, 30_000);
});
onUnmounted(() => {
  if (pollHandle) clearInterval(pollHandle);
  if (tickHandle) clearInterval(tickHandle);
});

// Format last-night sleep h+m
function fmtSleep(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

const groups = computed<Group[]>(() => {
  const sleepStr = fmtSleep(summary.value?.sleep_duration_s);
  const bpStr = summary.value?.bp_systolic_avg && summary.value?.bp_diastolic_avg
    ? `${Math.round(summary.value.bp_systolic_avg)}/${Math.round(summary.value.bp_diastolic_avg)}`
    : "—";
  const weightStr = summary.value?.weight_kg != null
    ? `${(weightVal(summary.value.weight_kg) ?? 0).toFixed(0)}` : "—";
  const hrStr = summary.value?.resting_hr ? `${Math.round(summary.value.resting_hr)}` : "—";
  const tempStr = summary.value?.skin_temp_delta_avg != null
    ? `${summary.value.skin_temp_delta_avg.toFixed(2)}` : "—";
  const distStr = activitiesDistanceM.value != null
    ? fmtDistance(activitiesDistanceM.value, 0) : "—";
  return [
    { id: "today",   to: "/",        icon: Home,        label: "Today" },
    { id: "trends",  to: "/trends",  icon: TrendingUp,  label: "Trends" },
    {
      id: "vitals", icon: Heart, label: "Vitals", children: [
        { to: "/sleep",          icon: Bed,         label: "Sleep",          sub: sleepStr,   subColor: "#a78bfa" },
        { to: "/blood-pressure", icon: Droplets,    label: "Blood pressure", sub: bpStr,      subColor: "#fb923c" },
        { to: "/weight",         icon: Scale,       label: "Weight",         sub: weightStr,  subColor: "#38bdf8" },
        { to: "/trends#rhr",       icon: Heart,       label: "Resting HR", sub: hrStr,   subColor: "#ef4444" },
        { to: "/trends#skin-temp", icon: Thermometer, label: "Skin Δ",     sub: tempStr, subColor: "#94a3b8" },
      ],
    },
    {
      id: "activity", icon: Activity, label: "Activity", children: [
        { to: "/activities",         icon: List,        label: "List",     sub: activitiesCount.value?.toString() ?? null },
        { to: "/activities/map",     icon: Map,         label: "Map",      sub: distStr },
        { to: "/activities/compare", icon: GitCompare,  label: "Compare" },
        { to: "/calendar",           icon: Calendar,    label: "Calendar" },
      ],
    },
    {
      id: "insights", to: "/insights", icon: Sparkles, label: "Insights",
      badge: discoveriesCount.value && discoveriesCount.value > 0
        ? `${discoveriesCount.value} new` : undefined,
      badgeColor: "#a78bfa",
    },
    { id: "log",     to: "/log",     icon: Edit3,         label: "Log" },
    {
      id: "sober",   to: "/sober",   icon: RotateCcw,     label: "Sober time",
      badge: soberDays.value != null ? `${Math.floor(soberDays.value)}d` : undefined,
      badgeColor: "#22c55e",
    },
    {
      id: "alerts",  to: "/alerts",  icon: AlertTriangle, label: "Alerts",
      badge: alertsCount.value && alertsCount.value > 0
        ? `${alertsCount.value}` : undefined,
      badgeColor: "#ef4444",
    },
    { id: "compare", to: "/compare", icon: BarChart3,     label: "Compare" },
    { id: "logs",    to: "/logs",    icon: Terminal,      label: "Debug logs" },
    { id: "settings",to: "/settings",icon: Settings,      label: "Settings" },
  ];
});

function toggle(id: string) { expanded.value[id] = !expanded.value[id]; }

function isActive(to: string): boolean {
  return route.path === to;
}
function isGroupActive(g: Group): boolean {
  if (g.to && isActive(g.to)) return true;
  return g.children?.some((c) => isActive(c.to)) ?? false;
}

// Mobile: emit close so the App shell can hide overlay after navigation.
const emit = defineEmits<{ (e: "navigate"): void }>();
</script>

<template>
  <aside class="side-nav" :class="{ collapsed }">
    <!-- Brand row -->
    <div class="brand">
      <template v-if="!collapsed">
        <AppLogo :size="28" tile/>
        <div class="brand-id">
          <div class="brand-name">myvitals</div>
          <div class="last-sync" :class="`status-${syncStatus}`" :title="syncChipTitle">
            <span class="dot"/>
            <span>{{ syncChipText }}</span>
          </div>
        </div>
      </template>
      <button class="collapse-btn" :title="collapsed ? 'Expand' : 'Collapse'"
              @click="collapsed = !collapsed">
        <Menu :size="14"/>
      </button>
    </div>

    <!-- Search -->
    <div class="search-row" v-if="!collapsed">
      <Search :size="12" class="search-icon"/>
      <span class="search-placeholder">Search…</span>
      <span class="kbd">⌘K</span>
    </div>

    <!-- Groups -->
    <nav class="groups">
      <div class="section-label" v-if="!collapsed">Workspace</div>
      <div class="group" v-for="g in groups" :key="g.id">
        <component
          :is="g.children ? 'button' : 'RouterLink'"
          class="group-btn"
          :class="{ active: isGroupActive(g) }"
          :to="g.to"
          :title="collapsed ? g.label : undefined"
          @click="g.children ? toggle(g.id) : emit('navigate')">
          <component :is="g.icon" :size="14" class="group-icon"/>
          <template v-if="!collapsed">
            <span class="group-label">{{ g.label }}</span>
            <span v-if="g.badge" class="badge"
                  :style="{ color: g.badgeColor, background: `${g.badgeColor}15`, borderColor: `${g.badgeColor}40` }">
              {{ g.badge }}
            </span>
            <component v-if="g.children" class="chevron"
                       :is="expanded[g.id] ? ChevronDown : ChevronRight" :size="11"/>
          </template>
        </component>
        <!-- Sub-rail -->
        <div v-if="!collapsed && g.children && expanded[g.id]" class="sub-rail">
          <RouterLink v-for="c in g.children" :key="c.label + c.to" :to="c.to"
                      class="sub-link" :class="{ active: isActive(c.to) }"
                      @click="emit('navigate')">
            <component :is="c.icon" :size="11" class="sub-icon"/>
            <span class="sub-label">{{ c.label }}</span>
            <span v-if="c.sub" class="sub-val mono"
                  :style="{ color: c.subColor || '#64748b' }">{{ c.sub }}</span>
          </RouterLink>
        </div>
      </div>
    </nav>

    <!-- Footer (compact rail in collapsed mode) -->
    <div class="footer-rail" v-if="collapsed">
      <a href="https://github.com/Pr0zak/myvitals" target="_blank" rel="noreferrer"
         class="footer-link" title="View source on GitHub">
        <Github :size="14"/>
      </a>
      <RouterLink to="/settings" class="footer-link" title="Settings"
                  @click="emit('navigate')">
        <Settings :size="14"/>
      </RouterLink>
    </div>

    <!-- Footer user card -->
    <div class="footer" v-if="!collapsed">
      <div class="user-card">
        <div class="avatar">myv</div>
        <div class="user-meta">
          <div class="username">myvitals</div>
          <div class="endpoint mono">
            {{ backendOk === false ? 'offline' : 'self-host · ok' }}
            <span v-if="backendVersion" class="ver">· v{{ backendVersion }}</span>
          </div>
        </div>
        <a href="https://github.com/Pr0zak/myvitals" target="_blank" rel="noreferrer"
           class="footer-link" title="View source on GitHub">
          <Github :size="12"/>
        </a>
        <RouterLink to="/settings" class="footer-link" @click="emit('navigate')" title="Settings">
          <Settings :size="12"/>
        </RouterLink>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.side-nav {
  width: 232px;
  height: 100vh;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #0a0e15;
  border-right: 1px solid rgba(148, 163, 184, 0.10);
  position: sticky;
  top: 0;
  transition: width 0.18s ease;
}
.side-nav.collapsed { width: 60px; }

/* ── Brand ─────────────────────────────────────── */
.brand {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0 0.85rem; height: 56px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.10);
}
.brand-id { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
.brand-name { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.1; }
.last-sync {
  font-size: 10px; font-family: 'Geist Mono', ui-monospace, monospace;
  display: inline-flex; align-items: center; gap: 0.3rem; color: #22c55e;
  letter-spacing: 0.01em;
}
.last-sync.status-ok    { color: #22c55e; }
.last-sync.status-stale { color: #eab308; }
.last-sync.status-perms { color: #ef4444; }
.last-sync.status-off   { color: #ef4444; opacity: 0.85; }
.last-sync .dot {
  width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.collapse-btn {
  background: transparent; border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 6px; color: #64748b; cursor: pointer; padding: 0.25rem;
  display: flex; align-items: center; justify-content: center;
}
.collapse-btn:hover { color: #cbd5e1; border-color: rgba(148, 163, 184, 0.3); }
.side-nav.collapsed .collapse-btn { margin: 0 auto; }

/* ── Search ────────────────────────────────────── */
.search-row {
  display: flex; align-items: center; gap: 0.5rem;
  margin: 0.6rem 0.7rem 0;
  padding: 0.4rem 0.6rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(148, 163, 184, 0.10);
  border-radius: 6px;
  color: #475569;
}
.search-icon { flex-shrink: 0; }
.search-placeholder { font-size: 12px; flex: 1; }
.kbd {
  font-family: ui-monospace, monospace; font-size: 10px;
  padding: 0.05rem 0.3rem; border-radius: 3px;
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(148, 163, 184, 0.12);
}

/* ── Groups ────────────────────────────────────── */
.groups {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem 0.4rem 0.75rem;
}
.section-label {
  font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
  color: #64748b; font-weight: 600;
  padding: 0.25rem 0.5rem 0.4rem;
}
.group { margin-bottom: 1px; }
.group-btn {
  display: flex; align-items: center; gap: 0.55rem;
  width: 100%;
  padding: 0.4rem 0.55rem;
  border-radius: 6px;
  background: transparent; border: none; cursor: pointer;
  font-size: 13px; font-family: inherit;
  color: #cbd5e1; text-decoration: none;
}
.group-btn:hover { background: rgba(255, 255, 255, 0.03); }
.group-btn.active {
  background: rgba(56, 189, 248, 0.10);
  color: #7dd3fc;
}
.group-btn.active .group-icon { color: #38bdf8; }
.group-icon { color: #64748b; flex-shrink: 0; }
.group-label { flex: 1; text-align: left; }
.badge {
  font-family: ui-monospace, monospace; font-size: 9.5px; font-weight: 600;
  padding: 0.05rem 0.35rem; border-radius: 3px;
  border: 1px solid;
}
.chevron { color: #475569; flex-shrink: 0; }

/* Collapsed: hide labels + everything except icon */
.side-nav.collapsed .group-btn {
  justify-content: center; padding: 0.5rem 0;
}

/* Sub-rail */
.sub-rail {
  margin: 0.15rem 0 0.25rem 0.55rem;
  padding-left: 0.6rem;
  border-left: 1px solid rgba(148, 163, 184, 0.08);
  display: flex; flex-direction: column; gap: 1px;
}
.sub-link {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.25rem 0.4rem;
  border-radius: 5px;
  font-size: 12px;
  color: #94a3b8; text-decoration: none;
}
.sub-link:hover { background: rgba(255, 255, 255, 0.03); color: #cbd5e1; }
.sub-link.active { background: rgba(255, 255, 255, 0.05); color: white; }
.sub-icon { color: #64748b; flex-shrink: 0; }
.sub-label { flex: 1; }
.sub-val { font-size: 10px; font-family: ui-monospace, monospace; letter-spacing: -0.01em; }

/* ── Footer ───────────────────────────────────── */
.footer {
  padding: 0.6rem 0.7rem;
  border-top: 1px solid rgba(148, 163, 184, 0.10);
}
.user-card {
  display: flex; align-items: center; gap: 0.55rem;
  padding: 0.5rem;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(148, 163, 184, 0.08);
  border-radius: 8px;
}
.avatar {
  width: 28px; height: 28px; border-radius: 6px;
  background: linear-gradient(135deg, #a78bfa, #38bdf8);
  color: #0b1018; font-family: ui-monospace, monospace;
  font-weight: 600; font-size: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.user-meta { flex: 1; min-width: 0; }
.username { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.endpoint { font-size: 9.5px; color: #64748b; }
.endpoint .ver { color: #94a3b8; font-weight: 500; }
.footer-link {
  color: #64748b; display: flex;
  padding: 0.2rem; border-radius: 4px;
}
.footer-link:hover { color: #cbd5e1; background: rgba(255, 255, 255, 0.04); }
.footer-rail {
  margin-top: auto;
  padding: 0.6rem;
  border-top: 1px solid rgba(148, 163, 184, 0.10);
  display: flex; flex-direction: column; gap: 0.4rem;
  align-items: center;
}

/* Mobile */
@media (max-width: 700px) {
  .side-nav {
    position: fixed; left: 0; top: 0; bottom: 0; z-index: 50;
    transform: translateX(-100%); transition: transform 0.2s ease;
  }
  .side-nav.open { transform: translateX(0); }
}
</style>
