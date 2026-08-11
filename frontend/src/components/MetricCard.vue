<script setup lang="ts">
/**
 * The metric card — one vocabulary, repeated.
 *
 * Modelled on Google Health's "Key metrics" card, the reference this project
 * is working to. The point is that EVERY metric uses this exact shape, so the
 * eye learns one layout and then reads the whole screen at a glance:
 *
 *   name          small, quiet
 *   VALUE unit    large, LIGHT weight — the thing you came for
 *   qualifier     "Today", "Today • 9,038 to go", or a date when carried
 *   chart         7 days, full card width, weekday letters, today emphasised
 *   [chip]        "In range" / "Goal not met" — filled, not outlined
 *
 * Stacked vertically rather than value-beside-chart: in a 2-up grid a fixed
 * chart column collides with the value as soon as the card narrows, and the
 * reference stacks these too.
 *
 * Details from the reference that are easy to drop and matter:
 *   - Missing data renders as a LARGE "No data" in the value slot, not a
 *     dash. It reads as a state, not as a failed render.
 *   - The weekday axis is always present, so the chart is anchored in time
 *     instead of being an abstract squiggle.
 *
 * Values, status and range all come from the server (`/summary/tiles`);
 * nothing here decides what counts as good.
 */
import { computed } from "vue";

const props = withDefaults(defineProps<{
  name: string;
  /** Null renders the large "No data" state. */
  value: number | string | null;
  unit?: string;
  qualifier?: string;
  /** Server verdict: good | typical | watch, or null for no chip. */
  status?: string | null;
  statusLabel?: string | null;
  /** Oldest-first daily points; nulls are gaps. */
  series?: Array<{ date: string; value: number | null }>;
  /** Shaded "your normal" band, as explicit bounds from the server. The
   *  rule that produces them is a health judgement and lives in
   *  analytics/tiles.py, not here. */
  bandLow?: number | null;
  bandHigh?: number | null;
  /** Dotted goal line. */
  target?: number | null;
  chart?: "line" | "bar";
  accent?: string;
}>(), {
  unit: "", qualifier: "Today", status: null, statusLabel: null,
  series: () => [], bandLow: null, bandHigh: null, target: null, chart: "line",
  accent: "#7ee2a8",
});

const WEEK = 7;
const W = 132;
const H = 40;

/** Last 7 points — the reference always shows a week. */
const week = computed(() => (props.series ?? []).slice(-WEEK));

const hasData = computed(() => props.value !== null && props.value !== undefined);

const CHIP: Record<string, { fg: string; bg: string; text: string }> = {
  good: { fg: "#7ee2a8", bg: "rgba(126,226,168,.14)", text: "In range" },
  typical: { fg: "#c7cbd1", bg: "rgba(199,203,209,.12)", text: "In range" },
  watch: { fg: "#e8b661", bg: "rgba(232,182,97,.14)", text: "Out of range" },
};

const NO_DATA_CHIP = { fg: "#8d949d", bg: "rgba(141,148,157,.12)", text: "No data" };

/** Every card carries a chip. The reference does this — an empty metric
 *  shows "No data" rather than nothing — and it is also what keeps the two
 *  cards in a grid row the same height instead of one leaving dead space. */
const chip = computed(() => {
  if (!hasData.value) return NO_DATA_CHIP;
  if (!props.status) return null;
  const base = CHIP[props.status];
  if (!base) return null;
  return { ...base, text: props.statusLabel ?? base.text };
});

const days = computed(() =>
  week.value.map((p) => {
    const d = new Date(p.date + "T00:00:00");
    return Number.isNaN(d.getTime())
      ? "" : ["S", "M", "T", "W", "T", "F", "S"][d.getDay()];
  }),
);

const todayIdx = computed(() => week.value.length - 1);

const scale = computed(() => {
  const vals = week.value.map((p) => p.value).filter((v): v is number => v != null);
  const extra = [props.bandLow, props.bandHigh, props.target]
    .filter((v): v is number => v != null);
  const all = [...vals, ...extra];
  if (!all.length) return null;
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.18;
  lo -= pad; hi += pad;
  const stepX = week.value.length > 1 ? W / (week.value.length - 1) : W;
  return {
    x: (i: number) => i * stepX,
    y: (v: number) => H - ((v - lo) / (hi - lo)) * H,
  };
});

const linePath = computed(() => {
  const s = scale.value;
  if (!s) return "";
  let d = "";
  let started = false;
  week.value.forEach((p, i) => {
    if (p.value == null) { started = false; return; }
    d += `${started ? "L" : "M"}${s.x(i).toFixed(1)} ${s.y(p.value).toFixed(1)} `;
    started = true;
  });
  return d.trim();
});

const points = computed(() => {
  const s = scale.value;
  if (!s) return [];
  return week.value
    .map((p, i) => (p.value == null ? null : { x: s.x(i), y: s.y(p.value), i }))
    .filter((p): p is { x: number; y: number; i: number } => p != null);
});

const bars = computed(() => {
  const s = scale.value;
  if (!s) return [];
  const bw = Math.max(4, W / (week.value.length * 2));
  return week.value.map((p, i) => ({
    i,
    x: s.x(i) - bw / 2,
    w: bw,
    y: p.value == null ? H : s.y(p.value),
    h: p.value == null ? 0 : H - s.y(p.value),
  }));
});

/** The shaded "your normal" band, drawn from the server's bounds. */
const band = computed(() => {
  const s = scale.value;
  if (!s || props.bandLow == null || props.bandHigh == null) return null;
  const top = s.y(props.bandHigh);
  const bot = s.y(props.bandLow);
  return { y: Math.min(top, bot), h: Math.abs(bot - top) };
});

const targetY = computed(() => {
  const s = scale.value;
  return s && props.target != null ? s.y(props.target) : null;
});

const plottable = computed(
  () => week.value.filter((p) => p.value != null).length >= 1,
);
</script>

<template>
  <div class="mc">
    <div class="name">{{ name }}</div>

    <div v-if="hasData" class="value">
      {{ value }}<span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <div v-else class="value nodata">No data</div>

    <div v-if="qualifier" class="qual">{{ qualifier }}</div>

    <div class="chartwrap">
      <svg class="spark" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none">
        <rect
          v-if="band" x="0" :y="band.y" :width="W" :height="band.h"
          :fill="accent" opacity="0.10"
        />
        <line
          v-if="targetY != null" x1="0" :y1="targetY" :x2="W" :y2="targetY"
          :stroke="accent" stroke-width="1" stroke-dasharray="2 3"
          opacity="0.55" vector-effect="non-scaling-stroke"
        />
        <g v-if="chart === 'bar' && plottable">
          <rect
            v-for="b in bars" :key="b.i" :x="b.x" :y="b.y"
            :width="b.w" :height="b.h" rx="2"
            :fill="accent" :opacity="b.i === todayIdx ? 1 : 0.45"
          />
        </g>
        <g v-else-if="plottable">
          <path
            :d="linePath" fill="none" :stroke="accent" stroke-width="1.6"
            stroke-linecap="round" stroke-linejoin="round"
            vector-effect="non-scaling-stroke"
          />
          <circle
            v-for="p in points" :key="p.i" :cx="p.x" :cy="p.y"
            :r="p.i === todayIdx ? 3.2 : 2.2" :fill="accent"
            :opacity="p.i === todayIdx ? 1 : 0.75"
          />
        </g>
      </svg>

      <div class="days">
        <span
          v-for="(d, i) in days" :key="i"
          :class="{ today: i === todayIdx }"
        >{{ d }}</span>
      </div>
    </div>

    <span
      v-if="chip" class="chip"
      :style="{ color: chip.fg, background: chip.bg }"
    >{{ chip.text }}</span>
  </div>
</template>

<style scoped>
.mc {
  background: var(--mc-surface, #1b1c1f);
  border-radius: 20px;
  padding: 14px 14px 12px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.name {
  font-size: .78rem;
  color: #b9bec6;
  line-height: 1.25;
  margin-bottom: 6px;
}

/* Light weight and large — the reference's most recognisable trait. A bold
   value here makes the whole grid read as a spreadsheet. */
.value {
  font-size: 1.9rem;
  font-weight: 300;
  color: #e9edf2;
  line-height: 1.1;
  letter-spacing: -0.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.value.nodata { font-size: 1.45rem; }
.unit { font-size: .85rem; font-weight: 400; color: #b9bec6; margin-left: 4px; }
.qual { font-size: .7rem; color: #8d949d; margin-top: 2px; }

.chartwrap { margin-top: 10px; }
.spark { width: 100%; height: 40px; display: block; }
.days {
  display: flex;
  justify-content: space-between;
  font-size: .58rem;
  color: #6f767f;
  margin-top: 3px;
}
.days .today {
  color: #0d0f12;
  background: #b9bec6;
  border-radius: 999px;
  padding: 0 4px;
  font-weight: 600;
}

.chip {
  align-self: flex-start;
  font-size: .66rem;
  font-weight: 500;
  margin-block-start: 10px;
  padding: 3px 9px;
  border-radius: 999px;
  white-space: nowrap;
}
</style>
