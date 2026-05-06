<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ArrowUp, ArrowDown, Minus, Zap, Flame, AlertTriangle } from "lucide-vue-next";
import { api } from "@/api/client";

interface Badge {
  key: string;
  label: string;
  value: string;
  subtitle: string;
  tone: "good" | "warn" | "bad" | "neutral";
  direction: "up" | "down" | "flat" | "spike" | "streak";
}

const badges = ref<Badge[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    badges.value = await api.aiBadges();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
defineExpose({ refresh: load });

const TONE_COLOR: Record<Badge["tone"], string> = {
  good: "#22c55e",
  warn: "#eab308",
  bad: "#ef4444",
  neutral: "#94a3b8",
};

function iconFor(b: Badge) {
  if (b.direction === "spike") return AlertTriangle;
  if (b.direction === "streak") return b.key === "sober" ? Flame : Zap;
  if (b.direction === "up") return ArrowUp;
  if (b.direction === "down") return ArrowDown;
  return Minus;
}
</script>

<template>
  <div v-if="loading" class="badges-loading">Computing trends…</div>
  <div v-else-if="error" class="badges-err">Couldn't load badges: {{ error }}</div>
  <div v-else-if="badges.length === 0" class="badges-empty">
    Not enough history yet — keep syncing and trends will surface here.
  </div>
  <div v-else class="badges">
    <div v-for="b in badges" :key="b.key" class="badge"
         :style="{ '--tone': TONE_COLOR[b.tone] }">
      <component :is="iconFor(b)" :size="14" class="badge-icon"/>
      <div class="badge-text">
        <div class="badge-head">
          <span class="badge-label">{{ b.label }}</span>
          <span class="badge-value mono">{{ b.value }}</span>
        </div>
        <div class="badge-sub">{{ b.subtitle }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.badges {
  display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.6rem 0 1rem;
}
.badges-loading, .badges-err, .badges-empty {
  color: var(--muted-2); font-size: 0.85rem; padding: 0.4rem 0;
}
.badges-err { color: var(--bad); }

.badge {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.75rem;
  background: color-mix(in srgb, var(--tone) 8%, var(--surface-2));
  border: 1px solid color-mix(in srgb, var(--tone) 35%, transparent);
  border-radius: 10px;
  min-width: 0; max-width: 320px;
}
.badge-icon { color: var(--tone); flex-shrink: 0; }
.badge-text { display: flex; flex-direction: column; min-width: 0; gap: 1px; }
.badge-head { display: flex; gap: 0.4rem; align-items: baseline; }
.badge-label {
  color: var(--text-soft); font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
}
.badge-value {
  color: var(--text); font-size: 0.95rem; font-weight: 600;
  font-feature-settings: "tnum";
}
.badge-sub { color: var(--muted); font-size: 0.72rem; line-height: 1.2; }
</style>
