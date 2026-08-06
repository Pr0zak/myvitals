<script setup lang="ts">
/**
 * Year-at-a-glance activity calendar, colour-coded by activity type.
 * Web twin of `ui/common/ActivityCalendar.kt`.
 *
 * Replaces the old minutes-intensity ramp on Activities.vue: a single-hue
 * ramp answered "how long did I train" but not "what did I do", so a ride
 * and a lift were the same colour. The tooltip still carries the minutes,
 * so nothing that ramp encoded is lost.
 */
import { computed } from "vue";
import VChart from "@/echarts";
import { chartTheme, isNeon } from "@/theme";
import type { Activity } from "@/api/types";
import {
  CATEGORY_BY_INDEX,
  CATEGORY_META,
  categoryColor,
  categoryForSplitFocus,
  categoryForType,
  type ActivityCategoryKey,
} from "@/utils/activityCategory";

interface StrengthLike {
  date: string;
  status?: string | null;
  split_focus?: string | null;
}

const props = withDefaults(defineProps<{
  activities: Activity[];
  workouts?: StrengthLike[];
  /** Inclusive ISO lower bound; days before it are dropped so the range
   *  selector keeps controlling how many year strips render. */
  minDate?: string | null;
  compact?: boolean;
  showLegend?: boolean;
}>(), { workouts: () => [], minDate: null, compact: false, showLegend: true });

/** ISO date -> category. First entry of a day wins; an activity beats a
 *  generated workout on the same date (matches the phone). */
const byDate = computed<Record<string, ActivityCategoryKey>>(() => {
  const m: Record<string, ActivityCategoryKey> = {};
  const minD = props.minDate;
  for (const a of props.activities) {
    if (!a.start_at) continue;
    const d = a.start_at.slice(0, 10);
    if (minD && d < minD) continue;
    if (m[d] === undefined) m[d] = categoryForType(a.type);
  }
  for (const w of props.workouts) {
    if (w.status !== "completed" || !w.date) continue;
    const d = w.date.slice(0, 10);
    if (minD && d < minD) continue;
    if (m[d] === undefined) m[d] = categoryForSplitFocus(w.split_focus);
  }
  return m;
});

/** Minutes per day, tooltip-only — preserves what the old ramp encoded. */
const minsByDate = computed<Record<string, number>>(() => {
  const m: Record<string, number> = {};
  for (const a of props.activities) {
    if (!a.start_at) continue;
    const d = a.start_at.slice(0, 10);
    if (props.minDate && d < props.minDate) continue;
    m[d] = (m[d] ?? 0) + Math.round((a.duration_s ?? 0) / 60);
  }
  return m;
});

const years = computed(() =>
  Array.from(new Set(Object.keys(byDate.value).map((d) => d.slice(0, 4))))
    .sort((a, b) => b.localeCompare(a)),
);

const presentKeys = computed<ActivityCategoryKey[]>(() => {
  const seen = new Set(Object.values(byDate.value));
  return (Object.keys(CATEGORY_META) as ActivityCategoryKey[])
    .filter((k) => seen.has(k));
});

const STRIP_H = computed(() => (props.compact ? 92 : 110));
const TOP_PAD = 8;

export interface Exposed { height: number }
const height = computed(() =>
  years.value.length === 0 ? 0 : TOP_PAD + years.value.length * STRIP_H.value + 12,
);
defineExpose({ height });

const option = computed(() => {
  void chartTheme.value; void isNeon.value;
  const t = chartTheme.value;
  const neon = isNeon.value;
  if (years.value.length === 0) return null;

  const calendars = years.value.map((y, i) => ({
    top: TOP_PAD + i * STRIP_H.value,
    left: 30, right: 10,
    cellSize: ["auto", props.compact ? 10 : 13] as [string, number],
    range: y,
    itemStyle: {
      color: neon ? "#161a24" : "#1a2332",
      borderColor: neon ? "rgba(39,42,59,.9)" : "rgba(148,163,184,.12)",
      borderWidth: 1,
    },
    splitLine: { show: false },
    yearLabel: {
      show: years.value.length > 1, color: t.axisLabel.color,
      fontSize: 11, fontWeight: 600, margin: 14,
    },
    monthLabel: { color: t.axisLabel.color, fontSize: 10 },
    dayLabel: { color: t.axisLabel.color, fontSize: 9 },
  }));

  const series = years.value.map((y, i) => ({
    type: "heatmap" as const,
    coordinateSystem: "calendar" as const,
    calendarIndex: i,
    data: Object.entries(byDate.value)
      .filter(([d]) => d.startsWith(y))
      .map(([d, k]) => [d, CATEGORY_META[k].index]),
  }));

  return {
    tooltip: {
      ...t.tooltip,
      formatter: (p: any) => {
        const key = CATEGORY_BY_INDEX[p.value[1]];
        const label = key ? CATEGORY_META[key].label : "?";
        const mins = minsByDate.value[p.value[0]] ?? 0;
        return mins > 0
          ? `${p.value[0]}: ${label} · ${mins} min`
          : `${p.value[0]}: ${label}`;
      },
    },
    // Legend is rendered in the template so it can be derived from the
    // data and styled with our own tokens; ECharts' own is hidden.
    visualMap: {
      type: "piecewise" as const,
      pieces: presentKeys.value.map((k) => ({
        value: CATEGORY_META[k].index,
        color: categoryColor(k, neon),
        label: CATEGORY_META[k].label,
      })),
      show: false,
    },
    calendar: calendars,
    series,
  };
});
</script>

<template>
  <div v-if="option" class="acal">
    <VChart :option="option" :style="{ height: height + 'px' }" autoresize />
    <div v-if="showLegend" class="acal-legend">
      <span v-for="k in presentKeys" :key="k" class="lg">
        <i :style="{ background: categoryColor(k, isNeon) }"></i>
        {{ CATEGORY_META[k].label }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.acal { width: 100%; }
.acal-legend {
  display: flex; flex-wrap: wrap; gap: 0.55rem;
  margin-top: 0.3rem; color: var(--muted); font-size: 0.68rem;
}
.lg { display: inline-flex; align-items: center; gap: 0.28rem; }
.lg i {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
</style>
