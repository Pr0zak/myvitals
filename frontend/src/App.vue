<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { RouterView, useRoute } from "vue-router";
import { Menu as MenuIcon } from "lucide-vue-next";
import { isConfigured } from "@/config";
import { api } from "@/api/client";
import SideNav from "@/components/SideNav.vue";

const sideNavOpen = ref(false);
const route = useRoute();
watch(() => route.fullPath, () => { sideNavOpen.value = false; });

// Phone-side sync health — surfaced as a top banner when HC perms are
// revoked, so the user knows why the data dried up without having to
// open the side nav status chip.
const permsLost = ref(false);
const permsMissing = ref<string[]>([]);
async function refreshSyncHealth() {
  if (!isConfigured()) return;
  try {
    const s = await api.lastSync();
    permsLost.value = !!s.permissions_lost;
    permsMissing.value = s.perms_missing ?? [];
  } catch { /* ignore */ }
}
onMounted(() => { refreshSyncHealth(); setInterval(refreshSyncHealth, 60_000); });
</script>

<template>
  <div class="app">
    <SideNav :class="{ open: sideNavOpen }" @navigate="sideNavOpen = false"/>
    <button class="mobile-toggle" aria-label="Toggle navigation"
            @click="sideNavOpen = !sideNavOpen">
      <MenuIcon :size="18"/>
    </button>
    <div v-if="sideNavOpen" class="scrim" @click="sideNavOpen = false"/>

    <div class="main-col">
      <RouterLink v-if="!isConfigured()" to="/settings" class="banner">
        ⚠ No query token set — go to Settings to paste your QUERY_TOKEN.
      </RouterLink>
      <div v-else-if="permsLost" class="banner banner-perms">
        ⚠ Health Connect permissions lost on the phone — open the myvitals app and re-grant
        <span v-if="permsMissing.length" class="muted-mono"> ({{ permsMissing.join(', ') }})</span>.
        Sync attempts are firing but every read is denied.
      </div>
      <main>
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style>
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

html { background: var(--bg); }
body { margin: 0; }

:root {
  font-family: 'Geist', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  font-feature-settings: 'ss01', 'cv11';
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
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
.banner {
  display: block;
  margin: 0.8rem 1.5rem;
  padding: 0.6rem 0.9rem;
  background: rgba(234, 179, 8, 0.10);
  border-left: 3px solid var(--warn);
  color: var(--warn);
  text-decoration: none;
  font-size: 0.9rem;
  border-radius: 8px;
}
.banner:hover { background: rgba(234, 179, 8, 0.16); }
.banner-perms {
  background: rgba(239, 68, 68, 0.12);
  border-left-color: var(--bad);
  color: var(--bad);
}
.banner-perms .muted-mono {
  font-family: 'Geist Mono', ui-monospace, monospace;
  color: rgba(239, 68, 68, 0.75);
  font-size: 0.78rem;
}

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.2); border-radius: 4px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
