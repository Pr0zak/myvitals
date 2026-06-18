<script setup lang="ts">
/**
 * Vitality Neon shell navigation — 5 tabs. Bottom glass bar on mobile, a slim
 * left rail on desktop. Replaces the 13-group SideNav when the neon theme is
 * active (see App.vue). Each tab stays highlighted while the user is anywhere
 * in its domain (so drilling Body → Heart rate keeps "Body" lit).
 */
import { computed } from "vue";
import { useRoute, RouterLink } from "vue-router";
import { Target, Heart, Dumbbell, Mountain, Sparkles, User } from "lucide-vue-next";

const route = useRoute();

type Tab = {
  to: string; label: string; color: string;
  icon: typeof Target; match: (p: string) => boolean;
};

const tabs: Tab[] = [
  { to: "/rings", label: "Today", color: "#5dff3b", icon: Target,
    match: (p) => p === "/rings" || p === "/" },
  { to: "/body", label: "Body", color: "#28e6ff", icon: Heart,
    match: (p) => p === "/body" ||
      ["/heart-rate", "/hrv", "/sleep", "/steps", "/blood-pressure", "/weight", "/skin-temp", "/watch"].includes(p) },
  { to: "/train", label: "Train", color: "#5dff3b", icon: Dumbbell,
    match: (p) => p.startsWith("/train") || p.startsWith("/workout") || p.startsWith("/activit") || p === "/calendar" },
  { to: "/trails-hub", label: "Trails", color: "#ffb52e", icon: Mountain,
    match: (p) => p.startsWith("/trails") },
  { to: "/coach-hub", label: "Coach", color: "#ff3ad8", icon: Sparkles,
    match: (p) => p === "/coach-hub" || p === "/coach" || p === "/insights" || p.startsWith("/analytics") },
  { to: "/you", label: "You", color: "#28e6ff", icon: User,
    match: (p) => p === "/you" ||
      ["/sober", "/fasting", "/journal", "/goals"].includes(p) || p.startsWith("/settings") },
];

const activeIndex = computed(() => {
  const p = route.path;
  const i = tabs.findIndex((t) => t.match(p));
  return i >= 0 ? i : 0;
});
</script>

<template>
  <nav class="neon-nav" aria-label="Primary">
    <RouterLink
      v-for="(t, i) in tabs"
      :key="t.to"
      :to="t.to"
      class="tab"
      :class="{ on: i === activeIndex }"
      :style="i === activeIndex ? { color: t.color } : undefined"
      :aria-current="i === activeIndex ? 'page' : undefined"
    >
      <component :is="t.icon" :size="22" :stroke-width="2" />
      <span class="lbl">{{ t.label }}</span>
      <span class="glow" :style="i === activeIndex ? { background: t.color, boxShadow: `0 0 10px ${t.color}` } : undefined" />
    </RouterLink>
  </nav>
</template>

<style scoped>
.neon-nav {
  position: fixed;
  z-index: 50;
  display: flex;
  background: rgba(20, 22, 34, 0.78);
  backdrop-filter: blur(14px);
  border: 1px solid #23263a;
}
.tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #9b9bb0;
  text-decoration: none;
  transition: color 0.15s ease;
}
.tab .glow {
  width: 22px; height: 3px; border-radius: 3px; opacity: 0;
}
.tab.on .glow { opacity: 1; }

/* Mobile: bottom bar */
.neon-nav {
  left: 0; right: 0; bottom: 0;
  justify-content: space-around;
  padding: 12px 4px calc(12px + env(safe-area-inset-bottom));
  border-radius: 22px 22px 0 0;
  border-bottom: 0; border-left: 0; border-right: 0;
}

/* Desktop: left rail */
@media (min-width: 768px) {
  .neon-nav {
    top: 0; bottom: 0; left: 0; right: auto;
    width: 88px;
    flex-direction: column;
    justify-content: flex-start;
    gap: 6px;
    padding: 24px 8px;
    border-radius: 0 22px 22px 0;
    border-top: 0; border-left: 0; border-bottom: 0;
  }
  .tab { padding: 12px 0; width: 100%; }
  .tab .glow {
    width: 3px; height: 20px; position: absolute; left: 0;
  }
  .tab { position: relative; }
}
</style>
