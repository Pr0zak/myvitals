<script setup lang="ts">
/**
 * Unified analytics surface (ANALYTICS-1). Four tabbed lenses on the
 * same data, replacing what used to be four standalone SideNav routes:
 *
 *   /trends   → "Over time"
 *   /insights → "Patterns"
 *   /compare  → "Vs last period"
 *   /coach    → "Coach"
 *
 * The legacy routes still exist so existing bookmarks / deep links
 * keep working — this page just adds a single entry point that the
 * SideNav collapse (NAV-1) can use.
 *
 * Tab state is mirrored to the URL (`?tab=trends|patterns|compare|coach`)
 * so a refresh, share, or bookmark preserves the selected lens. Only
 * the active tab's component is mounted at a time — ECharts setup is
 * heavy enough that keeping all four hot would noticeably hurt the
 * first paint of whichever tab was clicked.
 */
import { computed, defineAsyncComponent, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  LineChart, BarChart3, GitCompareArrows, Sparkles,
} from "lucide-vue-next";

const Trends   = defineAsyncComponent(() => import("./Trends.vue"));
const Insights = defineAsyncComponent(() => import("./Insights.vue"));
const Compare  = defineAsyncComponent(() => import("./Compare.vue"));
const Coach    = defineAsyncComponent(() => import("./Coach.vue"));

type TabKey = "trends" | "patterns" | "compare" | "coach";

const TABS: { key: TabKey; label: string; icon: any; help: string }[] = [
  { key: "trends",   label: "Over time",      icon: LineChart,
    help: "Daily/weekly trends — readiness, RHR, HRV, sleep, weight." },
  { key: "patterns", label: "Patterns",       icon: BarChart3,
    help: "Distributions, day-of-week effects, correlations." },
  { key: "compare",  label: "Vs last period", icon: GitCompareArrows,
    help: "This window vs the prior matching window — direction + magnitude." },
  { key: "coach",    label: "Coach",          icon: Sparkles,
    help: "AI synthesis across vitals, training, and recovery signals." },
];

const VALID = new Set<TabKey>(TABS.map((t) => t.key));

const route = useRoute();
const router = useRouter();

const tab = computed<TabKey>(() => {
  const q = route.query.tab;
  const v = Array.isArray(q) ? q[0] : q;
  return (v && VALID.has(v as TabKey)) ? (v as TabKey) : "trends";
});

function setTab(next: TabKey) {
  if (next === tab.value) return;
  router.replace({ query: { ...route.query, tab: next } });
}

// Keep the document title in sync — small thing but it makes the
// browser-history list usable when several Analytics tabs are open.
watch(tab, (v) => {
  const t = TABS.find((x) => x.key === v);
  if (t) document.title = `Analytics · ${t.label} — myvitals`;
}, { immediate: true });
</script>

<template>
  <div class="analytics">
    <header class="hdr">
      <h1>Analytics</h1>
      <p class="muted">
        Four lenses on the same data — pick whichever angle is most
        useful right now. Each old route still works as a deep link.
      </p>
    </header>

    <nav class="tabs" aria-label="Analytics views">
      <button
        v-for="t in TABS" :key="t.key"
        class="tab"
        :class="{ active: tab === t.key }"
        :title="t.help"
        :aria-current="tab === t.key ? 'page' : undefined"
        @click="setTab(t.key)"
      >
        <component :is="t.icon" :size="14"/>
        <span>{{ t.label }}</span>
      </button>
    </nav>

    <main class="panel">
      <Trends   v-if="tab === 'trends'"/>
      <Insights v-else-if="tab === 'patterns'"/>
      <Compare  v-else-if="tab === 'compare'"/>
      <Coach    v-else-if="tab === 'coach'"/>
    </main>
  </div>
</template>

<style scoped>
.analytics {
  padding: 1rem 1.25rem 2rem;
  max-width: 1400px;
  margin: 0 auto;
}
.hdr { margin-bottom: 1rem; }
h1 { margin: 0 0 0.4rem; }
.muted { color: var(--muted); font-size: 0.9rem; max-width: 70ch; }

.tabs {
  display: flex; gap: 4px;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--outline);
  overflow-x: auto;
}
.tab {
  display: inline-flex; align-items: center; gap: 6px;
  appearance: none; border: 0; background: transparent;
  padding: 8px 14px;
  font-size: 0.85rem; font-weight: 500;
  color: var(--on-surface-2);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 120ms ease, border-color 120ms ease;
  white-space: nowrap;
}
.tab:hover { color: var(--on-surface); }
.tab.active {
  color: var(--on-surface);
  border-bottom-color: #38bdf8;
}

.panel {
  /* The mounted view brings its own outer padding via its scoped CSS,
     so we don't add extra here — the goal is for "Over time" to look
     identical to /trends apart from the new tab bar above it. */
}
</style>
