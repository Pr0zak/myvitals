<script setup lang="ts">
defineProps<{
  value?: string | number | null;
  unit?: string;
  size?: "xxl" | "xl" | "l" | "m" | "s";
}>();
</script>

<template>
  <span :class="['mono', `num-${size ?? 'l'}`]">
    {{ value ?? "" }}<slot/>
    <span v-if="unit" class="unit">{{ unit }}</span>
  </span>
</template>
