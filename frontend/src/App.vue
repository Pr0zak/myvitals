<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <div class="app">
    <nav>
      <RouterLink to="/">Today</RouterLink>
      <RouterLink to="/trends">Trends</RouterLink>
      <RouterLink to="/sleep">Sleep</RouterLink>
      <RouterLink to="/log">Log</RouterLink>
    </nav>
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
nav { display: flex; gap: 1rem; padding: 1rem 0; border-bottom: 1px solid #1e293b; }
nav a { color: #94a3b8; text-decoration: none; }
nav a.router-link-active { color: #38bdf8; }
main { padding: 1rem 0; }
</style>
