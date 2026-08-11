<script setup lang="ts">
/**
 * Today hero — web twin of `ui/common/TodayHero.kt`.
 *
 * The reference opens with a big progress ring beside a stack of saturated
 * chips, then an action row. Structure:
 *
 *   ⟳ Weekly steps        [Steps      1,100 ]
 *     17%                 [Readiness  58    ]
 *     67 of 390           [Sleep      8h 28m]
 *   [ + Log ]  [ Start ]
 *
 * The chips are FILLED rather than outlined — that saturation against the
 * dark ground is what makes the reference's hero read as a hero instead of
 * three more cards. Everything below it stays quiet by comparison.
 *
 * All three chips reuse tiles from `/summary/tiles`, and the ring's weekly
 * progress is summed server-side against seven days of the user's own daily
 * goal — not an invented weekly target.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { VitalTile } from "@/api/types";

const router = useRouter();
const tiles = ref<VitalTile[]>([]);
const week = ref<{ label: string; done: number; goal: number; pct: number } | null>(null);
const loaded = ref(false);

async function load() {
  try {
    const r = await api.summaryTiles();
    tiles.value = r.tiles ?? [];
    week.value = r.week ?? null;
  } catch {
    tiles.value = [];
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

function tile(key: string): VitalTile | undefined {
  return tiles.value.find((t) => t.key === key);
}

function display(key: string): string {
  const t = tile(key);
  if (!t || t.value == null) return "—";
  if (key === "steps" && typeof t.value === "number") return t.value.toLocaleString();
  if (key === "sleep_duration" && typeof t.value === "number") {
    const h = Math.floor(t.value);
    const m = Math.round((t.value - h) * 60);
    return `${h}h ${m}m`;
  }
  return String(t.value);
}

/** Readiness isn't a tile — it has its own endpoint — so the hero reads it
 *  from the roll-up the Health status section already fetched. */
const readiness = ref<number | null>(null);
onMounted(async () => {
  try {
    readiness.value = (await api.readinessDetail()).score ?? null;
  } catch { /* the chip shows a dash */ }
});

const CHIPS = computed(() => [
  { key: "steps", label: "Steps", value: display("steps"),
    bg: "#0f4f45", fg: "#7fe6d2", route: "/steps" },
  { key: "readiness", label: "Readiness",
    value: readiness.value == null ? "—" : String(Math.round(readiness.value)),
    bg: "#123c56", fg: "#8fd0f5", route: "/heart-rate" },
  { key: "sleep_duration", label: "Sleep", value: display("sleep_duration"),
    bg: "#3d2a5c", fg: "#c9adf5", route: "/sleep" },
]);

/** Inset so the stroke (plus its round cap) clears the card's corner
 *  radius — at r=52 with a 12px stroke the arc touched the card edge. */
const R = 44;
const C = 2 * Math.PI * R;
const dash = computed(() => {
  const pct = Math.max(0, Math.min(100, week.value?.pct ?? 0));
  return C * (1 - pct / 100);
});
</script>

<template>
  <section v-if="loaded" class="hero">
    <div class="top">
      <button class="ring" @click="router.push('/steps')" aria-label="Weekly steps">
        <svg viewBox="0 0 120 120">
          <circle cx="60" cy="60" :r="R" fill="none" stroke="#2a2d34" stroke-width="11" />
          <circle
            cx="60" cy="60" :r="R" fill="none" stroke="#5b8cff" stroke-width="11"
            stroke-linecap="round" :stroke-dasharray="C.toFixed(1)"
            :stroke-dashoffset="dash.toFixed(1)" transform="rotate(-90 60 60)"
          />
        </svg>
        <div class="rtext">
          <div class="rlabel">{{ week?.label ?? "Weekly steps" }}</div>
          <div class="rpct num">{{ Math.round(week?.pct ?? 0) }}%</div>
          <div class="rsub num">
            {{ (week?.done ?? 0).toLocaleString() }} of
            {{ (week?.goal ?? 0).toLocaleString() }}
          </div>
        </div>
      </button>

      <div class="chips">
        <button
          v-for="c in CHIPS" :key="c.key" class="chip"
          :style="{ background: c.bg, color: c.fg }"
          @click="router.push(c.route)"
        >
          <span class="clabel">{{ c.label }}</span>
          <span class="cvalue num">{{ c.value }}</span>
        </button>
      </div>
    </div>

    <!-- Both go somewhere real: Log opens the journal, Start opens today's
         workout. No decorative buttons. -->
    <div class="actions">
      <button class="act" @click="router.push('/journal')">
        <span class="plus">+</span> Log
      </button>
      <button class="act" @click="router.push('/workout/strength/today')">
        Start
      </button>
    </div>
  </section>
</template>

<style scoped>
.hero { margin: 4px 0 18px; max-width: 640px; }
.top { display: flex; gap: 12px; align-items: stretch; }

/* Height comes from the row, not a fixed number: the chips column grew to
   172px and the ring stopped at 168, leaving a visible 4px step. */
.ring {
  position: relative; flex: none; width: 168px; min-height: 168px;
  background: #1b1c1f; border: 0; border-radius: 22px;
  cursor: pointer; padding: 0; color: inherit;
}
.ring svg { width: 100%; height: 100%; display: block; }
.top > .ring { align-self: stretch; }
.rtext {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 1px;
}
.rlabel { font-size: .62rem; color: #b9bec6; }
.rpct { font-size: 1.7rem; font-weight: 300; color: #e9edf2; line-height: 1.1; }
.rsub { font-size: .64rem; color: #8d949d; }

.chips { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.chip {
  flex: 1; display: flex; flex-direction: column; justify-content: center;
  gap: 1px; border: 0; border-radius: 18px; padding: 10px 14px;
  cursor: pointer; text-align: left; min-width: 0;
}
.clabel { font-size: .72rem; opacity: .85; }
.cvalue {
  font-size: 1.25rem; font-weight: 400; color: #fff;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.actions { display: flex; gap: 10px; margin-top: 12px; }
.act {
  flex: 1; border: 0; border-radius: 999px; padding: 11px 0;
  background: #143a52; color: #cfe6f7; font-size: .9rem;
  cursor: pointer; font-weight: 500;
}
.plus { font-weight: 400; margin-right: 2px; }
</style>
