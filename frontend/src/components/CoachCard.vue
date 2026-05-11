<script setup lang="ts">
/**
 * Consolidated AI / rationale card for the workout page (#WP-13).
 * Replaces the four separate cards (WhyThisWorkout, DeloadBanner,
 * VarietyNudge, FocusCue) with one collapsible card that has four
 * sections, each lazy-loaded on first expand. Status pills surface
 * what each section has to say without forcing a tap.
 *
 *   - Deload   — AI multi-signal recovery judgment (severity chip)
 *   - Focus    — AI pre-workout coaching cue
 *   - Variety  — AI swap suggestions (0-2 chip)
 *   - Why      — deterministic algorithm rationale
 *
 * Deload runs eagerly via the cached /latest endpoint (no Claude
 * call). Other sections POST when opened. refreshKey invalidates
 * cached judgments after a regenerate.
 */
import { onMounted, ref, watch } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";

const props = defineProps<{
  workoutId: number;
  refreshKey?: number;
}>();
const emit = defineEmits<{
  (e: "accept-swap", payload: {
    targetExerciseId: string;
    replacementExerciseId: string;
  }): void;
}>();

type Severity = "none" | "light" | "moderate" | "rest";
type DeloadJ = {
  should_deload: boolean;
  severity: Severity;
  headline: string;
  evidence: string[];
  recommendation: string;
} | null;

const deloadJ = ref<DeloadJ>(null);
const deloadLoading = ref(false);
const deloadError = ref<string | null>(null);

type Swap = {
  target_exercise_id: string;
  replacement_exercise_id: string;
  reason: string;
};
const swaps = ref<Swap[] | null>(null);
const swapsLoading = ref(false);
const swapsError = ref<string | null>(null);
const swapsDismissed = ref<Set<string>>(new Set());

const focusCue = ref<{ headline: string; tone: string; cue: string } | null>(null);
const focusLoading = ref(false);
const focusError = ref<string | null>(null);

const explain = ref<{
  why_split: string;
  why_exercises: string;
  why_targets: string;
} | null>(null);
const explainLoading = ref(false);

const open = ref<{ deload: boolean; focus: boolean; variety: boolean; why: boolean }>({
  deload: false, focus: false, variety: false, why: false,
});

async function loadDeloadLatest() {
  try {
    const r = await api.aiStrengthDeloadLatest();
    if (r) deloadJ.value = r.judgment;
  } catch { /* silent */ }
}

async function refreshDeload() {
  if (deloadLoading.value) return;
  deloadLoading.value = true;
  deloadError.value = null;
  try {
    const r = await api.aiStrengthDeloadCheck();
    deloadJ.value = r.judgment;
  } catch (e) {
    deloadError.value = e instanceof Error ? e.message : String(e);
  } finally { deloadLoading.value = false; }
}

async function loadFocus() {
  if (focusCue.value || focusLoading.value) return;
  focusLoading.value = true;
  focusError.value = null;
  try {
    const r = await api.aiStrengthFocusCue(props.workoutId);
    focusCue.value = r.cue;
  } catch (e) {
    focusError.value = e instanceof Error ? e.message : String(e);
  } finally { focusLoading.value = false; }
}

async function loadSwaps() {
  if (swaps.value !== null || swapsLoading.value) return;
  swapsLoading.value = true;
  swapsError.value = null;
  try {
    const r = await api.aiStrengthNudge(props.workoutId);
    swaps.value = r.nudge?.swaps ?? [];
  } catch (e) {
    swapsError.value = e instanceof Error ? e.message : String(e);
    swaps.value = [];
  } finally { swapsLoading.value = false; }
}

async function loadExplain() {
  if (explain.value || explainLoading.value) return;
  explainLoading.value = true;
  try {
    explain.value = await api.strengthExplain(props.workoutId);
  } catch { /* silent */ }
  finally { explainLoading.value = false; }
}

function dismissSwap(s: Swap) {
  swapsDismissed.value = new Set([...swapsDismissed.value, s.target_exercise_id]);
}

function visibleSwaps(): Swap[] {
  return (swaps.value ?? []).filter(s => !swapsDismissed.value.has(s.target_exercise_id));
}

function toggle(key: "deload" | "focus" | "variety" | "why") {
  open.value[key] = !open.value[key];
  if (open.value[key]) {
    if (key === "focus") loadFocus();
    if (key === "variety") loadSwaps();
    if (key === "why") loadExplain();
  }
}

onMounted(loadDeloadLatest);
watch(() => props.refreshKey, () => {
  // Workout regenerated — drop AI caches and re-pull deload from /latest.
  deloadJ.value = null;
  focusCue.value = null;
  swaps.value = null;
  swapsDismissed.value = new Set();
  explain.value = null;
  loadDeloadLatest();
});
</script>

<template>
  <Card title="Coach" :flat="true" class="coach-card">
    <!-- Deload section -->
    <div :class="['row', `sev-${deloadJ?.severity ?? 'none'}`]">
      <button class="row-head" @click="toggle('deload')">
        <span class="icon">▲</span>
        <span class="title">Deload</span>
        <span v-if="deloadJ && deloadJ.severity !== 'none'" class="pill"
              :class="`pill-${deloadJ.severity}`">
          {{ deloadJ.severity }}
        </span>
        <span v-else-if="deloadJ" class="pill pill-clear">clear</span>
        <span v-else class="pill pill-unloaded">tap to check</span>
        <span class="caret">{{ open.deload ? "−" : "+" }}</span>
      </button>
      <div v-if="open.deload" class="row-body">
        <template v-if="deloadJ">
          <p class="headline">{{ deloadJ.headline }}</p>
          <ul v-if="deloadJ.evidence?.length" class="evidence">
            <li v-for="(e, i) in deloadJ.evidence" :key="i">{{ e }}</li>
          </ul>
          <p class="rec"><strong>What to do:</strong> {{ deloadJ.recommendation }}</p>
        </template>
        <p v-else-if="deloadLoading" class="muted">Thinking…</p>
        <p v-else class="muted small">No judgment cached yet.</p>
        <button class="ghost-btn" :disabled="deloadLoading" @click="refreshDeload">
          {{ deloadLoading ? "Thinking…" : "Re-check" }}
        </button>
        <p v-if="deloadError" class="muted small">AI unavailable. Check Settings → AI.</p>
      </div>
    </div>

    <!-- Focus section -->
    <div class="row">
      <button class="row-head" @click="toggle('focus')">
        <span class="icon">◇</span>
        <span class="title">Focus cue</span>
        <span v-if="focusCue" class="pill pill-ready">ready</span>
        <span v-else class="pill pill-unloaded">tap to load</span>
        <span class="caret">{{ open.focus ? "−" : "+" }}</span>
      </button>
      <div v-if="open.focus" class="row-body">
        <template v-if="focusCue">
          <p class="headline">{{ focusCue.headline }}</p>
          <p class="cue-body">{{ focusCue.cue }}</p>
        </template>
        <p v-else-if="focusLoading" class="muted">Thinking…</p>
        <p v-if="focusError" class="muted small">AI unavailable. Check Settings → AI.</p>
      </div>
    </div>

    <!-- Variety section -->
    <div class="row">
      <button class="row-head" @click="toggle('variety')">
        <span class="icon">✦</span>
        <span class="title">Variety</span>
        <span v-if="swaps !== null && visibleSwaps().length > 0" class="pill pill-suggest">
          {{ visibleSwaps().length }} swap{{ visibleSwaps().length === 1 ? "" : "s" }}
        </span>
        <span v-else-if="swaps !== null" class="pill pill-clear">balanced</span>
        <span v-else class="pill pill-unloaded">tap to check</span>
        <span class="caret">{{ open.variety ? "−" : "+" }}</span>
      </button>
      <div v-if="open.variety" class="row-body">
        <p v-if="swapsLoading" class="muted">Thinking…</p>
        <p v-else-if="swaps === null" class="muted">Tap to load.</p>
        <p v-else-if="visibleSwaps().length === 0 && swaps.length === 0" class="muted small">
          Plan looks balanced — no swaps suggested.
        </p>
        <p v-else-if="visibleSwaps().length === 0" class="muted small">
          All suggestions dismissed.
        </p>
        <ul v-else class="swap-list">
          <li v-for="s in visibleSwaps()" :key="s.target_exercise_id" class="swap-item">
            <div class="swap-row">
              <code class="eid">{{ s.target_exercise_id.replace(/_/g, " ") }}</code>
              <span class="arrow">→</span>
              <code class="eid alt">{{ s.replacement_exercise_id.replace(/_/g, " ") }}</code>
            </div>
            <div class="reason">{{ s.reason }}</div>
            <div class="actions">
              <button class="primary" @click="emit('accept-swap', {
                targetExerciseId: s.target_exercise_id,
                replacementExerciseId: s.replacement_exercise_id,
              })">Accept swap</button>
              <button class="ghost-btn" @click="dismissSwap(s)">Dismiss</button>
            </div>
          </li>
        </ul>
        <p v-if="swapsError" class="muted small">AI unavailable. Check Settings → AI.</p>
      </div>
    </div>

    <!-- Why section -->
    <div class="row">
      <button class="row-head" @click="toggle('why')">
        <span class="icon">?</span>
        <span class="title">Why this workout</span>
        <span class="pill pill-unloaded">{{ explain ? "loaded" : "tap to view" }}</span>
        <span class="caret">{{ open.why ? "−" : "+" }}</span>
      </button>
      <div v-if="open.why" class="row-body">
        <p v-if="explainLoading" class="muted">…</p>
        <template v-else-if="explain">
          <div class="why-section">
            <div class="why-h">Why this split</div>
            <p v-html="explain.why_split"></p>
          </div>
          <div class="why-section">
            <div class="why-h">Why these exercises</div>
            <p v-html="explain.why_exercises"></p>
          </div>
          <div class="why-section">
            <div class="why-h">Why these targets</div>
            <p v-html="explain.why_targets"></p>
          </div>
        </template>
        <p v-else class="muted small">No rationale available.</p>
      </div>
    </div>
  </Card>
</template>

<style scoped>
.coach-card { margin: 0 0 0.7rem; padding: 0.4rem 0.6rem !important;
              border-radius: 10px !important; }
.coach-card :deep(header) { padding: 0.3rem 0.2rem; }
.coach-card :deep(.body) { padding: 0.2rem 0; }
.row { border-top: 1px solid var(--line); }
.row:first-of-type { border-top: none; }
.row.sev-light    { background: rgba(250, 204, 21, 0.06); border-left: 3px solid #facc15; }
.row.sev-moderate { background: rgba(249, 115, 22, 0.07); border-left: 3px solid #f97316; }
.row.sev-rest     { background: rgba(239, 68, 68, 0.08);  border-left: 3px solid #ef4444; }
.row-head {
  width: 100%; display: flex; align-items: center; gap: 0.5rem;
  background: transparent; border: none; padding: 0.5rem 0.4rem;
  cursor: pointer; color: var(--text); text-align: left; min-height: 30px;
}
.icon { font-size: 0.95rem; opacity: 0.8; width: 1rem; text-align: center; }
.title { font-weight: 600; font-size: 0.9rem; flex: 1; }
.pill {
  font-size: 0.7rem; padding: 0.1rem 0.45rem; border-radius: 10px;
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
}
.pill-rest     { background: rgba(239, 68, 68, 0.18); color: #ef4444; }
.pill-moderate { background: rgba(249, 115, 22, 0.18); color: #f97316; }
.pill-light    { background: rgba(250, 204, 21, 0.18); color: #facc15; }
.pill-clear    { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.pill-suggest  { background: rgba(167, 139, 250, 0.18); color: #a78bfa; }
.pill-ready    { background: rgba(56, 189, 248, 0.18); color: #38bdf8; }
.pill-unloaded { background: var(--bg-1); color: var(--muted); }
.caret { color: var(--muted); margin-left: 0.3rem; font-size: 1rem; min-width: 0.6rem; }
.row-body { padding: 0.2rem 0.6rem 0.6rem; }
.headline { font-size: 0.88rem; color: var(--text); margin: 0 0 0.35rem; font-weight: 500; }
.evidence { list-style: disc; padding-left: 1.2rem; margin: 0 0 0.5rem;
            color: var(--text); font-size: 0.82rem; }
.evidence li { margin: 0.15rem 0; }
.rec { color: var(--text); font-size: 0.85rem; margin: 0.3rem 0 0.5rem; }
.cue-body { color: var(--text); font-size: 0.85rem; margin: 0; line-height: 1.4; }
.swap-list { list-style: none; padding: 0; margin: 0; display: flex;
             flex-direction: column; gap: 0.45rem; }
.swap-item { padding: 0.5rem 0.6rem; background: var(--bg-1); border-radius: 6px;
             border: 1px solid var(--line); }
.swap-row { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
            font-size: 0.82rem; }
.eid { font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.78rem;
       color: var(--text); text-transform: capitalize; }
.eid.alt { color: #22c55e; }
.arrow { color: var(--muted); }
.reason { color: var(--muted); font-size: 0.78rem; margin: 0.3rem 0; }
.actions { display: flex; gap: 0.4rem; margin-top: 0.2rem; }
.primary { background: #38bdf8; color: #0f172a; border: none;
           border-radius: 6px; padding: 0.25rem 0.65rem; font-size: 0.78rem;
           cursor: pointer; font-weight: 500; }
.ghost-btn { background: transparent; color: var(--muted);
             border: 1px solid var(--line); border-radius: 6px;
             padding: 0.22rem 0.6rem; font-size: 0.76rem; cursor: pointer; }
.why-section { padding: 0.3rem 0; }
.why-h { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
         color: var(--muted); margin-bottom: 0.2rem; }
.why-section p { margin: 0; color: var(--text); font-size: 0.82rem; line-height: 1.45; }
.muted { color: var(--muted); }
.muted.small { font-size: 0.8rem; }
</style>
