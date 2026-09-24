<script setup lang="ts">
/** A number over a label — phone `NeonStatTile`. */
defineProps<{ value: string; label: string; accent?: string }>();
</script>

<template>
  <div class="neon-stat">
    <div class="ns-v" :style="accent ? { color: accent } : undefined">{{ value }}</div>
    <div class="ns-l">{{ label }}</div>
  </div>
</template>

<style scoped>
.neon-stat { background: #181b27; border: 1px solid #23263a; border-radius: 18px; padding: 12px 8px; text-align: center; }
.ns-v { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-weight: 700; font-size: 22px; letter-spacing: -0.02em;
  color: #ececf5; font-variant-numeric: tabular-nums; }
.ns-l { font-size: 11px; color: #9b9bb0; }
</style>
