<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string; flat?: boolean }>();
</script>

<template>
  <section class="card" :class="{ flat }">
    <header v-if="title || subtitle">
      <h2 v-if="title">{{ title }}</h2>
      <span v-if="subtitle" class="sub">{{ subtitle }}</span>
    </header>
    <div class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  /* Subtle top→bottom gradient on tier-2 → tier-1 (design spec) */
  background: linear-gradient(180deg, var(--bg-2) 0%, var(--bg-1) 100%);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  min-height: 140px;
  margin-bottom: 0.85rem;
}
.card.flat { background: var(--bg-1); }
header {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.6rem; gap: 0.6rem;
}
h2 {
  margin: 0;
  font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
.sub {
  font-size: 11.5px; color: var(--muted-2);
  font-family: 'Geist Mono', ui-monospace, monospace;
  letter-spacing: -0.01em;
}
.body { flex: 1; display: flex; flex-direction: column; }
</style>
