<script setup lang="ts">
/**
 * Body — the shared metric cards, nothing bespoke.
 *
 * This screen used to declare its own card language: gradient-tinted tiles
 * with uppercase labels, showing the same seven metrics as Key metrics in a
 * different visual vocabulary, plus a client-side blood-pressure verdict
 * that ignored the staleness the server had deliberately disclosed. All of
 * it is deleted.
 *
 * `KeyMetrics` fetches `/summary/tiles` itself, so this view carries no data
 * layer of its own — which is the point: there is one implementation of
 * "show the user their metrics", and every surface renders it.
 */
import KeyMetrics from "@/components/KeyMetrics.vue";
</script>

<template>
  <div class="body-view">
    <header class="head">
      <h1>Body</h1>
    </header>

    <!-- The Recovery header ring is gone too: Body showed Recovery twice,
         once as a ring and once as a card. -->
    <KeyMetrics />
  </div>
</template>

<style scoped>
.body-view {
  min-height: 100vh;
  margin: -1.25rem -1.5rem;
  padding: 54px 22px 32px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: #ececf5;
}
.head { margin-bottom: 6px; }
.head h1 {
  font-size: 2rem;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.5px;
}
</style>
