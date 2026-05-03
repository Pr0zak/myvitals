<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <section class="card">
    <header>
      <h2>{{ title }}</h2>
      <span v-if="subtitle" class="sub">{{ subtitle }}</span>
    </header>
    <div class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  min-height: 160px;
}
header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.5rem; }
h2 { margin: 0; font-size: 0.95rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
.sub { font-size: 0.8rem; color: #64748b; }
.body { flex: 1; display: flex; flex-direction: column; }
</style>
