<script setup lang="ts">
import { onMounted, ref } from "vue";
import Card from "@/components/Card.vue";
import { Plus, Pencil, Trash2, Check, X as XIcon, Sparkles } from "lucide-vue-next";
import { api } from "@/api/client";
import { renderMarkdown } from "@/markdown";
import { fmtDateTime } from "@/format";

interface Goal {
  id: number;
  kind: string;
  title: string;
  target_value: number | null;
  target_unit: string | null;
  target_date: string | null;
  started_at: string;
  ended_at: string | null;
  notes: string | null;
  current_value?: number | null;
  progress_pct?: number | null;
}

const goals = ref<Goal[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const checking = ref<number | null>(null);
const checks = ref<Record<number, string>>({});

const showCreate = ref(false);
const draftKind = ref<string>("weight");
const draftTitle = ref("");
const draftValue = ref<string>("");
const draftUnit = ref<string>("");
const draftDate = ref<string>("");
const draftNotes = ref<string>("");

const KIND_PRESETS = [
  { id: "weight",      label: "Weight",        unit_default: "kg" },
  { id: "sober",       label: "Sober streak",  unit_default: "days" },
  { id: "sleep",       label: "Sleep",         unit_default: "h/night" },
  { id: "steps",       label: "Daily steps",   unit_default: "steps" },
  { id: "fast_streak", label: "Fasting",       unit_default: "h/week" },
  { id: "custom",      label: "Custom",        unit_default: "" },
];

async function load() {
  loading.value = true; error.value = null;
  try { goals.value = await api.aiGoals(true); }
  catch (e) { error.value = e instanceof Error ? e.message : "load failed"; }
  finally { loading.value = false; }
}

async function createGoal() {
  if (!draftTitle.value.trim()) return;
  try {
    await api.aiCreateGoal({
      kind: draftKind.value,
      title: draftTitle.value.trim(),
      target_value: draftValue.value ? Number(draftValue.value) : undefined,
      target_unit: draftUnit.value || undefined,
      target_date: draftDate.value || undefined,
      notes: draftNotes.value || undefined,
    });
    showCreate.value = false;
    draftTitle.value = ""; draftValue.value = "";
    draftUnit.value = ""; draftDate.value = ""; draftNotes.value = "";
    await load();
  } catch (e) { error.value = e instanceof Error ? e.message : "create failed"; }
}

async function endGoal(g: Goal) {
  if (!confirm(`End the "${g.title}" goal?`)) return;
  try {
    await api.aiUpdateGoal(g.id, { ended_at: new Date().toISOString() });
    await load();
  } catch (e) { error.value = e instanceof Error ? e.message : "update failed"; }
}

async function removeGoal(g: Goal) {
  if (!confirm(`Delete "${g.title}" entirely?`)) return;
  try { await api.aiDeleteGoal(g.id); await load(); }
  catch (e) { error.value = e instanceof Error ? e.message : "delete failed"; }
}

async function checkGoal(g: Goal) {
  checking.value = g.id;
  try {
    const r = await api.aiCheckGoal(g.id);
    checks.value = { ...checks.value, [g.id]: r.content };
  } catch (e) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { data?: { detail?: string } } }).response;
      checks.value = { ...checks.value, [g.id]: `(check failed: ${r?.data?.detail ?? "unknown"})` };
    } else {
      checks.value = { ...checks.value, [g.id]: `(check failed)` };
    }
  } finally { checking.value = null; }
}

function pickKind(kind: string) {
  draftKind.value = kind;
  const preset = KIND_PRESETS.find((k) => k.id === kind);
  if (preset && !draftUnit.value) draftUnit.value = preset.unit_default;
}

onMounted(load);
</script>

<template>
  <div class="goals">
    <header class="head">
      <h1>Goals</h1>
      <button class="primary" @click="showCreate = !showCreate">
        <Plus :size="14"/> {{ showCreate ? "Cancel" : "New goal" }}
      </button>
    </header>
    <p class="hint">
      Set a target. Tap <em>Check</em> on any goal to get an AI coaching read on
      your trajectory and the most useful next-step lever.
    </p>

    <div v-if="error" class="err">{{ error }}</div>

    <Card v-if="showCreate" title="New goal">
      <div class="kind-row">
        <button v-for="k in KIND_PRESETS" :key="k.id" class="kind"
                :class="{ active: draftKind === k.id }" @click="pickKind(k.id)">
          {{ k.label }}
        </button>
      </div>
      <div class="form-grid">
        <label>
          <span>Title</span>
          <input v-model="draftTitle" placeholder="e.g. Lose 5kg by September"/>
        </label>
        <label>
          <span>Target</span>
          <input v-model="draftValue" type="number" placeholder="e.g. 70"/>
        </label>
        <label>
          <span>Unit</span>
          <input v-model="draftUnit" placeholder="kg / days / h …"/>
        </label>
        <label>
          <span>Target date</span>
          <input v-model="draftDate" type="date"/>
        </label>
        <label class="full">
          <span>Notes</span>
          <input v-model="draftNotes" placeholder="optional"/>
        </label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="!draftTitle.trim()" @click="createGoal">
          <Check :size="14"/> Create
        </button>
        <button class="ghost" @click="showCreate = false">
          <XIcon :size="14"/> Cancel
        </button>
      </div>
    </Card>

    <div v-if="loading" class="loading">Loading…</div>
    <div v-else-if="goals.length === 0 && !showCreate" class="empty">
      No active goals. Tap <strong>New goal</strong> to set one.
    </div>

    <Card v-for="g in goals" :key="g.id" :title="g.title"
          :subtitle="g.target_date ? `target ${g.target_date}` : ''">
      <div class="goal-meta">
        <span class="kind-pill">{{ g.kind }}</span>
        <span v-if="g.target_value != null" class="target mono">
          {{ g.target_value }} {{ g.target_unit ?? '' }}
        </span>
        <span class="muted">started {{ fmtDateTime(g.started_at) }}</span>
      </div>
      <div v-if="g.progress_pct != null && g.ended_at == null" class="progress-row">
        <div class="progress-bar">
          <div class="progress-fill"
               :class="{ done: g.progress_pct >= 100 }"
               :style="{ width: Math.min(100, g.progress_pct) + '%' }"/>
        </div>
        <span class="progress-text mono">
          {{ g.current_value != null ? g.current_value.toFixed(1) : '—' }}
          <span class="dim">/ {{ g.target_value }} {{ g.target_unit ?? '' }}</span>
          <span class="dim">·</span>
          {{ g.progress_pct.toFixed(0) }}%
        </span>
      </div>
      <p v-if="g.notes" class="notes">{{ g.notes }}</p>
      <div class="goal-actions">
        <button class="primary" :disabled="checking === g.id" @click="checkGoal(g)">
          <Sparkles :size="14"/>
          {{ checking === g.id ? "Thinking…" : "Coaching check" }}
        </button>
        <button class="ghost" @click="endGoal(g)">Mark complete</button>
        <button class="ghost danger" @click="removeGoal(g)">
          <Trash2 :size="13"/> Delete
        </button>
      </div>
      <div v-if="checks[g.id]" class="check-out" v-html="renderMarkdown(checks[g.id])"/>
    </Card>
  </div>
</template>

<style scoped>
.goals { max-width: 800px; }
.head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem; }
h1 { margin: 0; }
.hint { color: var(--muted); margin: 0 0 1.2rem; font-size: 0.9rem; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
.loading, .empty { color: var(--muted-2); padding: 1.2rem 0; text-align: center; }

.kind-row { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.7rem; }
.kind {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 100px; padding: 0.35rem 0.85rem; cursor: pointer;
  font-family: inherit; font-size: 0.8rem;
}
.kind:hover { border-color: var(--accent); }
.kind.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }

.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.6rem; }
.form-grid .full { grid-column: 1 / -1; }
.form-grid label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.78rem; color: var(--muted); }
.form-grid input {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.5rem 0.6rem; font-family: inherit; font-size: 0.9rem;
}
.actions { display: flex; gap: 0.5rem; margin-top: 0.8rem; }
button { display: inline-flex; align-items: center; gap: 0.35rem; cursor: pointer; font-family: inherit; }
.primary {
  background: var(--accent); color: var(--accent-text); border: 0;
  border-radius: 6px; padding: 0.45rem 0.9rem; font-weight: 600; font-size: 0.85rem;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost {
  background: transparent; color: var(--muted); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.45rem 0.85rem; font-size: 0.85rem;
}
.ghost.danger:hover { color: var(--bad); border-color: var(--bad); }

.goal-meta { display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; font-size: 0.85rem; color: var(--muted); }
.progress-row {
  display: flex; align-items: center; gap: 0.75rem;
  margin: 0.5rem 0 0.2rem;
}
.progress-bar {
  flex: 1; height: 6px;
  background: var(--surface-2, rgba(255, 255, 255, 0.06));
  border-radius: 3px; overflow: hidden;
}
.progress-fill {
  height: 100%; background: var(--accent, #38bdf8);
  transition: width 320ms ease;
}
.progress-fill.done { background: #22c55e; }
.progress-text { font-size: 0.78rem; color: var(--text-soft); white-space: nowrap; }
.progress-text .dim { color: var(--muted); margin: 0 0.25rem; }
.kind-pill {
  background: rgba(56, 189, 248, 0.12); color: var(--accent);
  border-radius: 4px; padding: 0.1rem 0.45rem; text-transform: uppercase;
  font-size: 0.7rem; letter-spacing: 0.05em; font-weight: 600;
}
.target { color: var(--text); font-weight: 500; }
.notes { color: var(--text-soft); font-size: 0.88rem; margin: 0.4rem 0 0.7rem; font-style: italic; }
.goal-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.6rem; }
.check-out {
  margin-top: 0.7rem; padding: 0.7rem 0.9rem;
  background: rgba(167, 139, 250, 0.05);
  border-left: 3px solid var(--violet);
  border-radius: 4px;
  color: var(--text-soft); font-size: 0.88rem; line-height: 1.5;
}
.check-out :deep(p) { margin: 0.25rem 0; }
</style>
