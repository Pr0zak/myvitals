<script setup lang="ts">
/**
 * Coach view — multi-card AI surface that synthesizes domain-specific
 * coaching from the user's data. Each card is lazy-loaded on expand
 * to keep AI calls metered. Cards:
 *   - Workout coach (multi-signal: strength + cardio + sleep + HRV)
 *   - Cardio coach (HR zones, polarized ratio, weekly dose)
 *
 * Both endpoints cache by payload-hash server-side — re-asking with
 * no new data returns the same row + cached:true without billing.
 */
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api, type CoachCardOut } from "@/api/client";
import { Activity, Bed, Dumbbell, RefreshCw, Target } from "lucide-vue-next";

interface GoalProgress {
  id: number;
  kind: string;
  title: string;
  target_value: number | null;
  target_unit: string | null;
  current_value: number | null;
  progress_pct: number | null;
}

const goals = ref<GoalProgress[]>([]);
async function loadGoals() {
  try {
    goals.value = await api.aiGoals(true) as unknown as GoalProgress[];
  } catch { /* swallow */ }
}

type CardState = {
  open: boolean;
  loading: boolean;
  data: CoachCardOut | null;
  error: string | null;
};

const cardio = ref<CardState>({ open: false, loading: false, data: null, error: null });
const workout = ref<CardState>({ open: false, loading: false, data: null, error: null });
const sleep = ref<CardState>({ open: false, loading: false, data: null, error: null });

async function preload() {
  try {
    cardio.value.data = await api.coachCardioLatest();
  } catch { /* swallow */ }
  try {
    workout.value.data = await api.coachWorkoutLatest();
  } catch { /* swallow */ }
  try {
    sleep.value.data = await api.coachSleepLatest();
  } catch { /* swallow */ }
}

async function fetchCard(
  card: typeof cardio.value,
  refresh: boolean,
  fetcher: () => Promise<CoachCardOut>,
) {
  card.loading = true;
  card.error = null;
  try {
    card.data = await fetcher();
  } catch (e: unknown) {
    card.error = e instanceof Error ? e.message : String(e);
  } finally {
    card.loading = false;
  }
}

async function toggleCardio() {
  cardio.value.open = !cardio.value.open;
  if (cardio.value.open && cardio.value.data === null) {
    await fetchCard(cardio.value, false, api.coachCardio);
  }
}

async function toggleWorkout() {
  workout.value.open = !workout.value.open;
  if (workout.value.open && workout.value.data === null) {
    await fetchCard(workout.value, false, api.coachWorkout);
  }
}

async function toggleSleep() {
  sleep.value.open = !sleep.value.open;
  if (sleep.value.open && sleep.value.data === null) {
    await fetchCard(sleep.value, false, api.coachSleep);
  }
}

function refreshCardio() { fetchCard(cardio.value, true, api.coachCardio); }
function refreshWorkout() { fetchCard(workout.value, true, api.coachWorkout); }
function refreshSleep() { fetchCard(sleep.value, true, api.coachSleep); }

function tonePill(tone: string | undefined): string {
  return tone || "neutral";
}

/**
 * Claude tool-use occasionally returns array fields as a single string
 * containing `<parameter name="item">…</parameter>` blocks rather than
 * a proper JSON array. Without normalization, Vue's v-for iterates the
 * STRING'S CHARACTERS — one bullet per letter. This helper makes the
 * UI robust regardless of which shape the model emits.
 */
function asLines(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map((v) => String(v));
  }
  if (typeof raw === "string") {
    // Extract <parameter name="item">…</parameter> blocks first; fall
    // back to splitting on newlines if no tags are present.
    const tagMatches = Array.from(raw.matchAll(/<parameter[^>]*>([\s\S]*?)<\/parameter>/g));
    if (tagMatches.length > 0) {
      return tagMatches.map((m) => m[1].trim()).filter((s) => s.length > 0);
    }
    return raw.split(/\r?\n/).map((s) => s.trim()).filter((s) => s.length > 0);
  }
  return [];
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

onMounted(() => { preload(); loadGoals(); });
</script>

<template>
  <div class="coach">
    <header class="hdr">
      <h1>Coach</h1>
      <p class="muted">
        AI cards that synthesize your data into specific guidance.
        Each card lazy-loads on expand — cached server-side so re-opening
        doesn't re-bill.
      </p>
    </header>

    <!-- Workout coach (multi-signal weekly synthesis) -->
    <section class="card" :class="['tone-' + tonePill(workout.data?.analysis?.tone as string | undefined)]">
      <button class="head" @click="toggleWorkout">
        <Dumbbell :size="18"/>
        <span class="title">Workout coach</span>
        <span class="sub">strength + cardio + recovery</span>
        <span class="chev">{{ workout.open ? "▾" : "▸" }}</span>
      </button>

      <div v-if="workout.open" class="body">
        <p v-if="workout.loading" class="hint">Thinking…</p>
        <p v-else-if="workout.error" class="err">{{ workout.error }}</p>
        <template v-else-if="workout.data?.analysis">
          <h3 class="headline">{{ workout.data.analysis.headline }}</h3>
          <div class="grid">
            <div>
              <div class="lbl">What's working</div>
              <p>{{ workout.data.analysis.what_is_working }}</p>
            </div>
            <div>
              <div class="lbl">What to change</div>
              <p>{{ workout.data.analysis.what_to_change }}</p>
            </div>
          </div>
          <div class="lbl">Evidence</div>
          <ul class="bullets">
            <li v-for="(e, i) in asLines(workout.data.analysis.evidence)" :key="i">{{ e }}</li>
          </ul>
          <div class="lbl">This week's plan hint</div>
          <p class="plan">{{ workout.data.analysis.weekly_plan_hint }}</p>
          <div class="footer">
            <span class="muted">{{ fmtTime(workout.data.generated_at) }} · {{ workout.data.model }}
              <span v-if="workout.data.cached">(cached)</span></span>
            <button class="ghost" :disabled="workout.loading" @click="refreshWorkout">
              <RefreshCw :size="13"/> Refresh
            </button>
          </div>
        </template>
        <template v-else>
          <p class="hint">No coach card cached yet — tap to generate.</p>
        </template>
      </div>
    </section>

    <!-- Goals — read-only progress summary (GOALS-5) -->
    <section v-if="goals.length > 0" class="card tone-neutral">
      <div class="head static">
        <Target :size="18"/>
        <span class="title">Goals</span>
        <span class="sub">{{ goals.length }} active</span>
        <RouterLink class="ghost link" to="/goals">Open</RouterLink>
      </div>
      <div class="body goals-body">
        <div v-for="g in goals" :key="g.id" class="goal-row">
          <div class="goal-row-head">
            <span class="goal-kind-pill">{{ g.kind }}</span>
            <span class="goal-title">{{ g.title }}</span>
            <span v-if="g.progress_pct != null" class="goal-pct mono">
              {{ g.progress_pct.toFixed(0) }}%
            </span>
          </div>
          <div class="bar">
            <div class="bar-fill"
                 :class="{ done: (g.progress_pct ?? 0) >= 100 }"
                 :style="{ width: Math.min(100, g.progress_pct ?? 0) + '%' }"/>
          </div>
          <div v-if="g.current_value != null && g.target_value != null"
               class="goal-row-foot mono">
            {{ g.current_value.toFixed(1) }} <span class="muted">/</span>
            {{ g.target_value }} <span class="muted">{{ g.target_unit ?? '' }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Sleep coach (duration + consistency + stages + recovery link) -->
    <section class="card" :class="['tone-' + tonePill(sleep.data?.analysis?.tone as string | undefined)]">
      <button class="head" @click="toggleSleep">
        <Bed :size="18"/>
        <span class="title">Sleep coach</span>
        <span class="sub">duration · consistency · stages · recovery link</span>
        <span class="chev">{{ sleep.open ? "▾" : "▸" }}</span>
      </button>

      <div v-if="sleep.open" class="body">
        <p v-if="sleep.loading" class="hint">Thinking…</p>
        <p v-else-if="sleep.error" class="err">{{ sleep.error }}</p>
        <template v-else-if="sleep.data?.analysis">
          <h3 class="headline">{{ sleep.data.analysis.headline }}</h3>
          <p class="plan supporting">
            <strong>Supporting recovery:</strong>
            {{ sleep.data.analysis.supporting_recovery }}
          </p>
          <div class="grid">
            <div>
              <div class="lbl">Duration</div>
              <p>{{ sleep.data.analysis.duration_assessment }}</p>
            </div>
            <div>
              <div class="lbl">Consistency</div>
              <p>{{ sleep.data.analysis.consistency_assessment }}</p>
            </div>
            <div>
              <div class="lbl">Stages</div>
              <p>{{ sleep.data.analysis.stage_assessment }}</p>
            </div>
            <div>
              <div class="lbl">Recovery link</div>
              <p>{{ sleep.data.analysis.recovery_link }}</p>
            </div>
          </div>
          <div class="lbl">Evidence</div>
          <ul class="bullets">
            <li v-for="(e, i) in asLines(sleep.data.analysis.evidence)" :key="i">{{ e }}</li>
          </ul>
          <div class="lbl">Recommendation</div>
          <p class="plan">{{ sleep.data.analysis.recommendation }}</p>
          <div class="footer">
            <span class="muted">{{ fmtTime(sleep.data.generated_at) }} · {{ sleep.data.model }}
              <span v-if="sleep.data.cached">(cached)</span></span>
            <button class="ghost" :disabled="sleep.loading" @click="refreshSleep">
              <RefreshCw :size="13"/> Refresh
            </button>
          </div>
        </template>
        <template v-else>
          <p class="hint">No coach card cached yet — tap to generate.</p>
        </template>
      </div>
    </section>

    <!-- Cardio coach (HR zones + dose) -->
    <section class="card" :class="['tone-' + tonePill(cardio.data?.analysis?.tone as string | undefined)]">
      <button class="head" @click="toggleCardio">
        <Activity :size="18"/>
        <span class="title">Cardio coach</span>
        <span class="sub">HR zones, weekly dose, polarization</span>
        <span class="chev">{{ cardio.open ? "▾" : "▸" }}</span>
      </button>

      <div v-if="cardio.open" class="body">
        <p v-if="cardio.loading" class="hint">Thinking…</p>
        <p v-else-if="cardio.error" class="err">{{ cardio.error }}</p>
        <template v-else-if="cardio.data?.analysis">
          <h3 class="headline">{{ cardio.data.analysis.headline }}</h3>
          <div class="grid">
            <div>
              <div class="lbl">Polarization</div>
              <p>{{ cardio.data.analysis.polarized_assessment }}</p>
            </div>
            <div>
              <div class="lbl">Volume</div>
              <p>{{ cardio.data.analysis.volume_assessment }}</p>
            </div>
          </div>
          <div class="lbl">Evidence</div>
          <ul class="bullets">
            <li v-for="(e, i) in asLines(cardio.data.analysis.evidence)" :key="i">{{ e }}</li>
          </ul>
          <div class="lbl">Recommendation</div>
          <p class="plan">{{ cardio.data.analysis.recommendation }}</p>
          <div class="footer">
            <span class="muted">{{ fmtTime(cardio.data.generated_at) }} · {{ cardio.data.model }}
              <span v-if="cardio.data.cached">(cached)</span></span>
            <button class="ghost" :disabled="cardio.loading" @click="refreshCardio">
              <RefreshCw :size="13"/> Refresh
            </button>
          </div>
        </template>
        <template v-else>
          <p class="hint">No coach card cached yet — tap to generate.</p>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.coach { max-width: 760px; margin: 0 auto; padding: 1rem; }
.hdr { margin-bottom: 1rem; }
h1 { margin: 0 0 0.4rem; }
.muted { color: var(--muted); font-size: 0.9rem; max-width: 60ch; }
.err { color: #ef4444; background: rgba(239, 68, 68, 0.1); padding: 0.6rem; border-radius: 6px; }
.hint { color: var(--muted); }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 0.8rem; overflow: hidden; }
.card.tone-good { border-left: 3px solid #22c55e; }
.card.tone-warn { border-left: 3px solid #f59e0b; }
.card.tone-bad  { border-left: 3px solid #ef4444; }

.head {
  width: 100%; display: flex; align-items: center; gap: 0.6rem;
  padding: 0.9rem 1rem; background: transparent; border: none;
  color: var(--text); cursor: pointer; text-align: left; font: inherit;
}
.head:hover { background: rgba(56, 189, 248, 0.05); }
.head .title { font-weight: 600; }
.head .sub { color: var(--muted); font-size: 0.78rem; margin-left: 0.5rem; }
.head .chev { margin-left: auto; color: var(--muted); }

.body { padding: 0 1rem 1rem; border-top: 1px solid var(--border); }
.headline { font-size: 1.05rem; margin: 0.8rem 0 0.6rem; color: var(--text); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; margin: 0.8rem 0; }
@media (max-width: 480px) { .grid { grid-template-columns: 1fr; } }
.grid p { margin: 0.2rem 0 0; font-size: 0.9rem; color: var(--text); }
.lbl { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.6rem; }
.bullets { margin: 0.3rem 0 0.6rem 1rem; padding: 0; }
.bullets li { font-size: 0.88rem; color: var(--text); margin-bottom: 0.2rem; }
.plan { background: var(--surface-2); border-radius: 6px; padding: 0.6rem 0.8rem; margin: 0.4rem 0 0; font-size: 0.9rem; }
.footer { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; margin-top: 0.8rem; }
.ghost { background: transparent; color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 0.35rem 0.7rem; cursor: pointer; display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.8rem; }
.ghost:disabled { opacity: 0.5; }

.head.static { cursor: default; }
.head.static:hover { background: transparent; }
.head .ghost.link {
  margin-left: auto; text-decoration: none;
  font-size: 0.78rem; padding: 0.3rem 0.6rem;
}
.card.tone-neutral { border-left: 3px solid #94a3b8; }
.goals-body { padding-top: 0.4rem; }
.goal-row { padding: 0.55rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
.goal-row:last-child { border-bottom: 0; }
.goal-row-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; }
.goal-kind-pill {
  background: rgba(56, 189, 248, 0.12); color: #38bdf8;
  border-radius: 4px; padding: 0.08rem 0.4rem;
  font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em;
  font-weight: 600;
}
.goal-title { color: var(--text); font-size: 0.88rem; flex: 1; }
.goal-pct { color: var(--text); font-size: 0.82rem; }
.bar { height: 4px; background: rgba(255, 255, 255, 0.06); border-radius: 2px; overflow: hidden; }
.bar-fill { height: 100%; background: #38bdf8; transition: width 320ms ease; }
.bar-fill.done { background: #22c55e; }
.goal-row-foot { font-size: 0.74rem; color: var(--text-soft); margin-top: 0.2rem; }
.muted { color: var(--muted); }
</style>
