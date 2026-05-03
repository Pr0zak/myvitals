<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
import { isConfigured } from "@/config";
</script>

<template>
  <div class="app">
    <nav>
      <RouterLink to="/">Today</RouterLink>
      <RouterLink to="/trends">Trends</RouterLink>
      <RouterLink to="/sleep">Sleep</RouterLink>
      <RouterLink to="/log">Log</RouterLink>
      <span class="spacer" />
      <RouterLink to="/logs" class="settings-link">Logs</RouterLink>
      <RouterLink to="/settings" class="settings-link">Settings</RouterLink>
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
:root {
  font-family: system-ui, sans-serif;
  color-scheme: dark;
  background: #0f172a;
  color: #e2e8f0;
}
body { margin: 0; }
.app { max-width: 1200px; margin: 0 auto; padding: 1rem; }
nav { display: flex; gap: 1rem; padding: 1rem 0; border-bottom: 1px solid #1e293b; align-items: center; }
nav a { color: #94a3b8; text-decoration: none; }
nav a.router-link-active { color: #38bdf8; }
nav .spacer { flex: 1; }
nav .settings-link { font-size: 0.85rem; }
.banner {
  display: block;
  margin: 0.8rem 0 0;
  padding: 0.6rem 0.9rem;
  background: rgba(234, 179, 8, 0.12);
  border-left: 3px solid #eab308;
  color: #fbbf24;
  text-decoration: none;
  font-size: 0.9rem;
  border-radius: 4px;
}
.banner:hover { background: rgba(234, 179, 8, 0.18); }
main { padding: 1rem 0; }
</style>
