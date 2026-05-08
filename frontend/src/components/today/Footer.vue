<script setup lang="ts">
import { RouterLink } from "vue-router";

defineProps<{ version: string }>();
</script>

<template>
  <div class="foot">
    <div class="mono">myvitals · v{{ version }}</div>
    <RouterLink to="/logs" class="diag">Diagnostics</RouterLink>
  </div>
</template>

<style scoped>
.foot {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; color: var(--dim); padding: 8px 4px;
}
.diag {
  color: var(--on-surface-2); text-decoration: none;
  border-bottom: 1px dashed var(--outline-strong);
}
</style>
