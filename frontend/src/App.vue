<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
import { isConfigured } from "@/config";
import { themeChoice } from "@/theme";

function cycleTheme() {
  const order: Array<"dark" | "light" | "auto"> = ["dark", "light", "auto"];
  const i = order.indexOf(themeChoice.value);
  themeChoice.value = order[(i + 1) % order.length];
}
</script>

<template>
  <div class="app">
    <nav>
      <RouterLink to="/">Today</RouterLink>
      <RouterLink to="/trends">Trends</RouterLink>
      <RouterLink to="/sleep">Sleep</RouterLink>
      <RouterLink to="/log">Log</RouterLink>
      <RouterLink to="/activities">Activities</RouterLink>
      <RouterLink to="/calendar">Calendar</RouterLink>
      <RouterLink to="/compare">Compare</RouterLink>
      <span class="spacer" />
      <button class="theme-btn" @click="cycleTheme" :title="`Theme: ${themeChoice} (click to cycle)`">
        {{ themeChoice === "dark" ? "🌙" : themeChoice === "light" ? "☀️" : "🌓" }}
      </button>
      <RouterLink to="/insights" class="nav-secondary">Insights</RouterLink>
      <RouterLink to="/alerts" class="nav-secondary">Alerts</RouterLink>
      <RouterLink to="/logs" class="nav-secondary">Logs</RouterLink>
      <RouterLink to="/settings" class="nav-secondary">Settings</RouterLink>
    </nav>
    <RouterLink v-if="!isConfigured()" to="/settings" class="banner">
      ⚠ No query token set — go to Settings to paste your QUERY_TOKEN.
    </RouterLink>
    <main>
      <RouterView />
    </main>
  </div>
</template>

<style>
:root,
[data-theme="dark"] {
  --bg: #0f172a;
  --surface: #1e293b;
  --surface-2: #334155;
  --border: #334155;
  --text: #e2e8f0;
  --text-soft: #cbd5e1;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --accent: #38bdf8;
  --accent-text: #0f172a;
  --good: #22c55e;
  --warn: #eab308;
  --bad: #ef4444;
  --violet: #a78bfa;
  color-scheme: dark;
}

[data-theme="light"] {
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface-2: #f1f5f9;
  --border: #e2e8f0;
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

:root {
  font-family: system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
}

body { margin: 0; }
.app { max-width: 1200px; margin: 0 auto; padding: 1rem; }

nav { display: flex; gap: 1rem; padding: 1rem 0; border-bottom: 1px solid var(--border); align-items: center; flex-wrap: wrap; }
nav a { color: var(--muted); text-decoration: none; }
nav a.router-link-active { color: var(--accent); }
nav .spacer { flex: 1; }
nav .nav-secondary { font-size: 0.85rem; }
.theme-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  border-radius: 6px;
  cursor: pointer;
  font-size: 1rem;
  padding: 0.2rem 0.5rem;
  line-height: 1;
}
.theme-btn:hover { color: var(--text); border-color: var(--accent); }

.banner {
  display: block;
  margin: 0.8rem 0 0;
  padding: 0.6rem 0.9rem;
  background: rgba(234, 179, 8, 0.12);
  border-left: 3px solid var(--warn);
  color: var(--warn);
  text-decoration: none;
  font-size: 0.9rem;
  border-radius: 4px;
}
.banner:hover { background: rgba(234, 179, 8, 0.18); }
main { padding: 1rem 0; }
</style>
