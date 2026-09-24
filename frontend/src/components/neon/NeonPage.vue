<script setup lang="ts">
/**
 * UI-refresh page scaffold — the web half of the phone's `NeonScreen`.
 * Obsidian radial background, the big title, an optional back link, and a
 * trailing slot. Full-bleed by cancelling `main`'s own inset through the
 * `--main-pt` / `--main-px` variables App.vue exposes, so it can never
 * over-cancel the phone inset and scroll sideways (UX-W1).
 *
 * A view reached from another one (detail screens, Meals, Fasting, Sober)
 * passes `back` so it gets a back arrow instead of building its own header.
 */
import { useRouter } from "vue-router";

const props = defineProps<{
  title: string;
  /** Route to go back to; `true` means browser history. */
  back?: string | boolean;
}>();
const router = useRouter();
function goBack() {
  if (typeof props.back === "string") router.push(props.back);
  else router.back();
}
</script>

<template>
  <div class="neon-page">
    <header class="np-head">
      <button v-if="back" class="np-back" type="button" aria-label="Back" @click="goBack">←</button>
      <h1 :class="{ sub: !!back }">{{ title }}</h1>
      <div class="np-trail"><slot name="trailing" /></div>
    </header>
    <slot />
  </div>
</template>

<style scoped>
.neon-page {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-high: #1e2230; --rn-track: #272a3b;
  --rn-line: #23263a; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-cyan: #28e6ff; --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-amber: #ffb52e;
  --rn-bad: #ff5d7a; --rn-peri: #6f7bff; --rn-onacc: #06121a;
  min-height: 100vh;
  margin: calc(-1 * var(--main-pt, 1.25rem)) calc(-1 * var(--main-px, 1.5rem)) 0;
  padding: 28px 20px 24px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink);
  font-family: 'Plus Jakarta Sans', 'Geist', system-ui, sans-serif;
  box-sizing: border-box;
}
.np-head { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
.np-head h1 { flex: 1; min-width: 0; margin: 0; font-size: 32px; font-weight: 800; letter-spacing: -0.5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.np-head h1.sub { font-size: 27px; }
.np-back { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--rn-line); background: var(--rn-card);
  color: var(--rn-ink); font-size: 18px; cursor: pointer; flex: 0 0 auto; }
.np-back:focus-visible { outline: 2px solid var(--rn-cyan); outline-offset: 2px; }
.np-trail { flex: 0 0 auto; }
@media (min-width: 900px) { .neon-page { padding-inline: 32px; } .neon-page > * { max-width: 760px; } }
</style>
