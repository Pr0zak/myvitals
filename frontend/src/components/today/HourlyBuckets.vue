<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  data: number[];
  color?: string;
  height?: number;
  currentHour?: number;
}>(), {
  color: "#94A3B8", height: 16,
  currentHour: () => new Date().getHours(),
});

const max = computed(() => Math.max(1, ...props.data));
</script>

<template>
  <div class="buckets" :style="{ height: `${height}px` }">
    <div v-for="(v, i) in data" :key="i"
         :style="{
           flex: 1,
           height: `${Math.max(1, (v / max) * height)}px`,
           background: i <= currentHour ? color : 'var(--outline)',
           opacity: i <= currentHour ? 0.55 : 0.35,
           borderRadius: '2px',
           minWidth: '2px',
         }"/>
  </div>
</template>

<style scoped>
.buckets { display: flex; align-items: flex-end; gap: 2px; width: 100%; }
</style>
