<script setup lang="ts">
/**
 * The per-meal fat verdict for one serving.
 *
 * This component's job is as much about what it does NOT say as what it
 * does. The app has no default fat threshold and will not invent one —
 * tolerance after a cholecystectomy varies widely between people and
 * commonly improves over months, so a made-up limit could be wrong in
 * either direction. When the server returns `verdict: "unknown"` this
 * renders the refusal and what would fix it, rather than falling back to
 * a confident-looking colour.
 *
 * `basis` is always shown alongside the verdict, so "high" never appears
 * as a bare fact — it is either "against your 20 g target" or "against
 * the median of your own meals".
 */
import { computed } from "vue";
import { AlertTriangle, CheckCircle2, HelpCircle, Info } from "lucide-vue-next";
import type { FatAssessment } from "@/api/client";

const props = defineProps<{ assessment: FatAssessment; compact?: boolean }>();

const style = computed(() => {
  switch (props.assessment.verdict) {
    case "very_high":
      return { cls: "very-high", icon: AlertTriangle, label: "Well above usual" };
    case "high":
      return { cls: "high", icon: AlertTriangle, label: "High for one meal" };
    case "approaching":
      return { cls: "approaching", icon: Info, label: "Approaching" };
    case "ok":
      return { cls: "ok", icon: CheckCircle2, label: "In range" };
    default:
      // Deliberately neutral, never green. "We cannot judge this" must
      // not read as "this is fine".
      return { cls: "unknown", icon: HelpCircle, label: "Not enough to judge" };
  }
});

const basisLabel = computed(() => {
  const a = props.assessment;
  if (a.basis === "target") {
    return a.target_source
      ? `your ${a.target_g}g target — ${a.target_source}`
      : `your ${a.target_g}g per-meal target`;
  }
  if (a.basis === "history") {
    return `your own ${a.comparison_meals} other meals`;
  }
  return null;
});

const fatLabel = computed(() =>
  props.assessment.fat_g == null ? "—" : `${props.assessment.fat_g.toFixed(1)} g`,
);
</script>

<template>
  <div class="fat" :class="[style.cls, { compact }]">
    <div class="head">
      <component :is="style.icon" :size="15" class="icon" />
      <span class="amount">{{ fatLabel }} fat</span>
      <span class="per">per serving</span>
      <span class="verdict">{{ style.label }}</span>
    </div>
    <p v-if="basisLabel" class="basis">vs {{ basisLabel }}</p>
    <p v-if="!compact && assessment.reason" class="reason">
      {{ assessment.reason }}
    </p>
  </div>
</template>

<style scoped>
.fat {
  border: 1px solid var(--line);
  border-left-width: 3px;
  border-radius: 10px;
  padding: 0.55rem 0.7rem;
  background: var(--bg-1);
}
.fat.compact { padding: 0.4rem 0.6rem; }
.head {
  display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
  font-variant-numeric: tabular-nums;
}
.icon { flex: none; }
.amount { font-size: 0.95rem; font-weight: 600; }
.per { font-size: 0.72rem; color: var(--muted-2); }
.verdict {
  margin-left: auto; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.04em; font-weight: 600;
}
.basis { margin: 0.25rem 0 0; font-size: 0.74rem; color: var(--muted-2); }
.reason {
  margin: 0.4rem 0 0; font-size: 0.78rem; color: var(--muted-2);
  line-height: 1.45;
}

/* Semantic colours, separate from the app accent. Unknown is grey on
 * purpose — an absent judgment must not borrow the reassurance of green. */
.ok { border-left-color: #22c55e; }
.ok .icon, .ok .verdict { color: #22c55e; }
.approaching { border-left-color: #fbbf24; }
.approaching .icon, .approaching .verdict { color: #fbbf24; }
.high { border-left-color: #fb923c; }
.high .icon, .high .verdict { color: #fb923c; }
.very-high { border-left-color: #f87171; }
.very-high .icon, .very-high .verdict { color: #f87171; }
.unknown { border-left-color: var(--line); }
.unknown .icon, .unknown .verdict { color: var(--muted-2); }
</style>
