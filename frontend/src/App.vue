<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { Menu as MenuIcon } from "lucide-vue-next";
import { isConfigured } from "@/config";
import { api } from "@/api/client";
import { isNeon } from "@/theme";
import SideNav from "@/components/SideNav.vue";
import NeonNav from "@/components/NeonNav.vue";

const sideNavOpen = ref(false);
const route = useRoute();
const router = useRouter();
watch(() => route.fullPath, () => { sideNavOpen.value = false; });

// Phone-side sync health — surfaced as a top banner when HC perms are
// revoked, so the user knows why the data dried up without having to
// open the side nav status chip.
const permsLost = ref(false);
const permsMissing = ref<string[]>([]);
const alerts = ref<Awaited<ReturnType<typeof api.aiAlerts>>>([]);

// Deep-link target: when a phone notification fires
// `myvitals.local/?alert=<id>`, highlight the matching banner and
// scroll it into view. We clear the query param once we've focused
// so a manual page refresh doesn't keep re-glowing.
const focusedAlertId = computed<number | null>(() => {
  const raw = route.query.alert;
  const v = Array.isArray(raw) ? raw[0] : raw;
  const n = v ? Number.parseInt(v, 10) : NaN;
  return Number.isFinite(n) ? n : null;
});

async function refreshSyncHealth() {
  if (!isConfigured()) return;
  try {
    const s = await api.lastSync();
    permsLost.value = !!s.permissions_lost;
    permsMissing.value = s.perms_missing ?? [];
  } catch { /* ignore */ }
  try { alerts.value = await api.aiAlerts(true); } catch { /* ignore */ }
}
async function ackAlert(id: number) {
  try {
    await api.aiAckAlert(id);
    alerts.value = alerts.value.filter((a) => a.id !== id);
  } catch { /* ignore */ }
}
async function ackAll() {
  try { await api.aiAckAllAlerts(); alerts.value = []; }
  catch { /* ignore */ }
}

// When the deep-link target arrives (or alerts finish loading with one
// queued), scroll the matching banner into view and clear the query
// param after a short delay so the focused border glow has time to
// register before the URL goes back to clean.
async function focusDeepLinkedAlert() {
  const id = focusedAlertId.value;
  if (id == null) return;
  if (!alerts.value.some((a) => a.id === id)) return;
  await nextTick();
  const el = document.querySelector<HTMLElement>(`[data-alert-id="${id}"]`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  // Strip the query param after the glow is visible
  setTimeout(() => {
    const q = { ...route.query };
    delete q.alert;
    router.replace({ path: route.path, query: q, hash: route.hash });
  }, 4_000);
}
watch([focusedAlertId, alerts], focusDeepLinkedAlert);

onMounted(async () => {
  await refreshSyncHealth();
  await focusDeepLinkedAlert();
  setInterval(refreshSyncHealth, 60_000);
});
</script>

<template>
  <div class="app" :class="{ neon: isNeon }">
    <!-- Classic shell: 13-group side rail -->
    <template v-if="!isNeon">
      <SideNav :class="{ open: sideNavOpen }" @navigate="sideNavOpen = false"/>
      <button class="mobile-toggle" aria-label="Toggle navigation"
              @click="sideNavOpen = !sideNavOpen">
        <MenuIcon :size="18"/>
      </button>
      <div v-if="sideNavOpen" class="scrim" @click="sideNavOpen = false"/>
    </template>
    <!-- Vitality Neon shell: 5-tab bottom bar / left rail -->
    <NeonNav v-else />

    <div class="main-col">
      <!-- Deep-linked to the Access pane. This used to point at plain
           /settings, which opens on whichever section is the default —
           so the banner that exists to say "paste your token" dropped the
           user on a page that does not contain the token field. -->
      <RouterLink v-if="!isConfigured()" to="/settings?tab=access" class="banner">
        ⚠ No query token set — open Settings to paste your QUERY_TOKEN.
      </RouterLink>
      <div v-else-if="permsLost" class="banner banner-perms">
        ⚠ Health Connect is denying reads on the phone. Sync attempts are firing but every record type is rejected.
        <span v-if="permsMissing && permsMissing.length" class="muted-mono">
          Missing: {{ permsMissing.join(', ') }}.
        </span>
        <span v-else class="muted-mono">
          The app shows all permissions granted, but Health Connect itself is blocking — usually after an HC update or account change. Fix:
          open the <strong>Health Connect</strong> app (not myvitals), tap <em>App permissions</em> → <em>myvitals</em>, and toggle each permission off then back on.
        </span>
      </div>
      <div v-for="a in alerts" :key="a.id" class="banner banner-alert"
           :class="[`severity-${a.severity}`, { focused: focusedAlertId === a.id }]"
           :data-alert-id="a.id">
        <span class="al-icon">●</span>
        <div class="al-text">
          <strong>{{ a.title }}</strong>
          <span class="al-body">{{ a.body }}</span>
        </div>
        <button class="al-ack" @click="ackAlert(a.id)" title="Dismiss">✕</button>
      </div>
      <div v-if="alerts.length > 1" class="banner-ack-all">
        <button class="ghost" @click="ackAll">Dismiss all alerts</button>
      </div>
      <main>
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style>
/* ── Off-today ambient tint (TD-3) ────────────────────────────────────────
 * DayNav stamps `data-day-relation` on <html> while the selected day is not
 * today, and the whole nav chrome picks it up — a coloured edge plus a faint
 * wash, rather than one small label in a corner.
 *
 * Borrowed from SparkyFitness, where it exists because a date-scoped app
 * makes it very easy to sit on the wrong day and read stale numbers as
 * current. It earns its place here for a sharper reason: this app has
 * shipped the UTC-versus-local day bug three separate times, so "which day
 * am I actually looking at" is a question the UI should answer without being
 * asked.
 *
 * `future` exists for completeness; DayNav caps forward navigation at today,
 * so nothing should reach it in practice. */
:root[data-day-relation="past"] {
  --day-tint: var(--warn, #eab308);
}
:root[data-day-relation="future"] {
  --day-tint: var(--accent, #38bdf8);
}
:root[data-day-relation="past"] .side-nav,
:root[data-day-relation="future"] .side-nav,
:root[data-day-relation="past"] .neon-nav,
:root[data-day-relation="future"] .neon-nav {
  border-color: color-mix(in srgb, var(--day-tint) 55%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--day-tint) 22%, transparent);
}
:root[data-day-relation="past"] .main-col::before,
:root[data-day-relation="future"] .main-col::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: color-mix(in srgb, var(--day-tint) 6%, transparent);
}

:root,
[data-theme="dark"] {
  /* Deeper, design-spec palette */
  --bg-0: #07090e;
  --bg-1: #0d1117;
  --bg-2: #131a24;
  --bg-3: #1a2332;
  --bg: var(--bg-0);
  --surface: var(--bg-1);
  --surface-2: var(--bg-2);
  --line: rgba(148, 163, 184, 0.10);
  --line-2: rgba(148, 163, 184, 0.18);
  --border: var(--line);
  --text: #e2e8f0;
  --text-soft: #cbd5e1;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --accent: #38bdf8;
  --accent-text: #0b1018;
  --good: #22c55e;
  --warn: #eab308;
  --bad: #ef4444;
  --violet: #a78bfa;
  color-scheme: dark;
}

[data-theme="light"] {
  --bg-0: #f1f5f9;
  --bg-1: #ffffff;
  --bg-2: #f8fafc;
  --bg-3: #f1f5f9;
  --bg: var(--bg-0);
  --surface: var(--bg-1);
  --surface-2: var(--bg-2);
  --line: rgba(15, 23, 42, 0.08);
  --line-2: rgba(15, 23, 42, 0.14);
  --border: var(--line);
  --text: #0f172a;
  --text-soft: #1e293b;
  --muted: #475569;
  --muted-2: #64748b;
  --accent: #0284c7;
  --accent-text: #ffffff;
  --good: #16a34a;
  --warn: #ca8a04;
  --bad: #dc2626;
  --violet: #7c3aed;
  color-scheme: light;
}

/* Vitality Neon redesign skin. Maps the global token names to the neon
 * palette so EVERY view picks up the obsidian-on-neon look for free; the
 * dedicated redesign views (Rings/Body/Train/CoachHub/You) add full layouts
 * on top. Domain colour language: cyan=recovery/heart, magenta=sleep/sober,
 * lime=move/exercise, amber=warmth. */
[data-theme="neon"] {
  --bg-0: #0f1118;
  --bg-1: #181b27;
  --bg-2: #1d2030;
  --bg-3: #23263a;
  --bg: var(--bg-0);
  --surface: var(--bg-1);
  --surface-2: var(--bg-2);
  --line: rgba(155, 155, 176, 0.12);
  --line-2: rgba(155, 155, 176, 0.20);
  --border: var(--line);
  --text: #ececf5;
  --text-soft: #cbd5e1;
  --muted: #9b9bb0;
  --muted-2: #6b6e85;
  --accent: #28e6ff;
  --accent-text: #04212a;
  --good: #5dff3b;
  --warn: #ffb52e;
  --bad: #ff5d7a;
  --violet: #ff3ad8;
  color-scheme: dark;
  font-family: 'Plus Jakarta Sans', 'Geist', system-ui, sans-serif;
}

html { background: var(--bg); }
body { margin: 0; }

:root {
  font-family: 'Geist', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  font-feature-settings: 'ss01', 'cv11';
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;

  /* Structural design tokens (theme-independent). These give the app a
   * single spacing/radius/type/elevation vocabulary instead of the magic
   * numbers (0.85rem, 20px 32px, ...) scattered per-view. New/refactored
   * styles should reach for these; existing literals migrate opportunistically. */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;

  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 16px;
  --r-pill: 999px;

  --text-xs: 11px;
  --text-sm: 12.5px;
  --text-md: 14px;
  --text-lg: 18px;
  --text-xl: 24px;
  --text-2xl: 32px;

  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.20);
  --shadow-2: 0 4px 16px rgba(0, 0, 0, 0.28);

  --focus-ring: 2px solid var(--accent);

  --motion-fast: 120ms;
  --motion-base: 200ms;
}

.mono {
  font-family: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-feature-settings: 'ss01', 'cv11';
  letter-spacing: -0.01em;
}

/* Design-system label class — caps, 0.12em tracking, weight 600 */
.label {
  font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
.label-sm {
  font-size: 9.5px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted-2); font-weight: 600;
}
.focus-num { font-variant-numeric: tabular-nums; }

/* ── Accessibility baseline ──────────────────────────────────────────
 * Keyboard focus was invisible app-wide (no :focus-visible anywhere) and
 * the looping alert/skeleton animations ignored reduced-motion. These two
 * global rules fix both without per-component edits. */
:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 2px;
  border-radius: 3px;
}
/* Mouse users keep the clean look; only keyboard focus shows the ring. */
:focus:not(:focus-visible) { outline: none; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

/* Layout shell */
.app {
  display: flex;
  min-height: 100vh;
  align-items: stretch;
}
.main-col {
  flex: 1;
  min-width: 0;          /* lets content scroll inside flex */
  display: flex;
  flex-direction: column;
}
main {
  padding: 1.25rem 1.5rem;
  flex: 1;
  position: relative;
}

/* Neon shell layout: no side rail in flow; NeonNav is fixed (bottom bar on
 * mobile, left rail ≥768px). Offset the content for the desktop rail. The
 * neon views carry their own bottom padding to clear the mobile bottom bar. */
.app.neon .main-col { width: 100%; }
@media (min-width: 768px) {
  .app.neon .main-col { margin-left: 88px; }
}

/* Mobile hamburger */
.mobile-toggle {
  display: none;
  position: fixed; top: 0.6rem; left: 0.6rem; z-index: 60;
  width: 36px; height: 36px;
  background: var(--surface); color: var(--muted);
  border: 1px solid var(--border); border-radius: 8px;
  align-items: center; justify-content: center; cursor: pointer;
}
.scrim {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 40;
}

@media (max-width: 700px) {
  .mobile-toggle { display: flex; }
  .scrim { display: block; }
  main { padding: 3.2rem 0.9rem 1rem; }
}

/* Banner */
/* Matches the card vocabulary rather than shouting above it: rounded, no
   accent rail, and quiet enough that content is still the first thing the
   eye lands on. It is a notice, not an alarm. */
.banner {
  display: block;
  margin: 0.8rem 1.5rem;
  padding: 0.7rem 0.95rem;
  border-radius: 14px;
  background: rgba(232, 182, 97, 0.10);
  border-left: 0;
  color: #e8b661;
  text-decoration: none;
  font-size: 0.9rem;
  border-radius: 8px;
}
.banner:hover { background: rgba(232, 182, 97, 0.16); }
.banner-perms {
  background: rgba(239, 68, 68, 0.12);
  color: #ff8a9b;
  color: var(--bad);
}
.banner-perms .muted-mono {
  font-family: 'Geist Mono', ui-monospace, monospace;
  color: rgba(239, 68, 68, 0.75);
  font-size: 0.78rem;
}
.banner-alert {
  display: flex; gap: 0.7rem; align-items: center;
  border-left-width: 3px;
}
.banner-alert.severity-bad   { background: rgba(239, 68, 68, 0.10); border-left-color: var(--bad); color: var(--bad); }
.banner-alert.severity-warn  { background: rgba(234, 179, 8, 0.10); border-left-color: var(--warn); color: var(--warn); }
.banner-alert.severity-good  { background: rgba(34, 197, 94, 0.08); border-left-color: var(--good); color: var(--good); }
.banner-alert.severity-info  { background: rgba(56, 189, 248, 0.06); border-left-color: var(--accent); color: var(--accent); }
.banner-alert .al-icon { font-size: 0.7rem; flex-shrink: 0; opacity: 0.8; }
.banner-alert .al-text { flex: 1; display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }
.banner-alert .al-body { color: var(--text-soft); font-size: 0.85rem; }
.banner-alert .al-ack {
  background: transparent; border: 0; color: inherit; opacity: 0.6;
  font-size: 0.95rem; cursor: pointer; padding: 0.2rem 0.4rem; line-height: 1;
}
.banner-alert .al-ack:hover { opacity: 1; }
.banner-alert.focused {
  animation: alert-glow 1.2s ease-in-out 2;
  box-shadow: 0 0 0 1px currentColor, 0 0 18px -2px currentColor;
}
@keyframes alert-glow {
  0%, 100% { box-shadow: 0 0 0 1px currentColor, 0 0 18px -2px currentColor; }
  50% { box-shadow: 0 0 0 2px currentColor, 0 0 28px 2px currentColor; }
}
.banner-ack-all {
  margin: 0 1.5rem 0.4rem; text-align: right;
}
.banner-ack-all .ghost {
  background: transparent; border: 1px solid var(--border);
  color: var(--muted); font-size: 0.78rem; padding: 0.25rem 0.7rem;
  border-radius: 6px; cursor: pointer; font-family: inherit;
}

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.2); border-radius: 4px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
