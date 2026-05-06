<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Pencil, Trash2, X, Check } from "lucide-vue-next";
import { api } from "@/api/client";
import type { Annotation, AnnotationCreate } from "@/api/types";

type LogType = "caffeine" | "alcohol" | "mood" | "food" | "meds" | "note";

interface TypeDef {
  key: LogType;
  label: string;
  emoji: string;
  fields: { name: string; label: string; placeholder?: string; type?: "text" | "number"; default?: string | number }[];
}

const TYPES: TypeDef[] = [
  { key: "caffeine", label: "Caffeine", emoji: "☕",
    fields: [
      { name: "mg", label: "mg", type: "number", placeholder: "100", default: 100 },
      { name: "source", label: "source", placeholder: "coffee" },
    ] },
  { key: "alcohol", label: "Alcohol", emoji: "🍺",
    fields: [
      { name: "drinks", label: "drinks", type: "number", placeholder: "1", default: 1 },
      { name: "type", label: "type", placeholder: "beer" },
    ] },
  { key: "mood", label: "Mood", emoji: "🙂",
    fields: [
      { name: "score", label: "1–10", type: "number", placeholder: "7", default: 7 },
    ] },
  { key: "food", label: "Food", emoji: "🍽️",
    fields: [
      { name: "description", label: "what", placeholder: "lunch — sandwich" },
    ] },
  { key: "meds", label: "Meds", emoji: "💊",
    fields: [
      { name: "name", label: "name", placeholder: "ibuprofen" },
      { name: "dose", label: "dose", placeholder: "200mg" },
    ] },
  { key: "note", label: "Note", emoji: "📝",
    fields: [
      { name: "text", label: "note", placeholder: "anything…" },
    ] },
];

const selected = ref<LogType>("caffeine");
const values = ref<Record<string, Record<string, string | number>>>({});
const noteText = ref<Record<LogType, string>>({} as Record<LogType, string>);
const recent = ref<Annotation[]>([]);
const submitting = ref(false);
const error = ref<string | null>(null);
const justSaved = ref<string | null>(null);

const currentDef = computed(() => TYPES.find((t) => t.key === selected.value)!);

function ensure(type: LogType) {
  if (!values.value[type]) {
    const def = TYPES.find((t) => t.key === type)!;
    values.value[type] = {};
    for (const f of def.fields) values.value[type][f.name] = f.default ?? "";
  }
}

TYPES.forEach((t) => ensure(t.key));

async function loadRecent() {
  try {
    recent.value = await api.listAnnotations({ limit: 20 });
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load recent";
  }
}

async function submit() {
  submitting.value = true;
  error.value = null;
  justSaved.value = null;
  const def = currentDef.value;
  const payload: Record<string, unknown> = { ...values.value[def.key] };
  // Coerce numeric fields
  for (const f of def.fields) if (f.type === "number") payload[f.name] = Number(payload[f.name] ?? 0);
  const body: AnnotationCreate = {
    type: def.key,
    payload,
    note: noteText.value[def.key] || undefined,
  };
  try {
    await api.createAnnotation(body);
    justSaved.value = `${def.emoji} ${def.label} logged`;
    noteText.value[def.key] = "";
    // Reset numeric fields to defaults so the next entry is fresh
    for (const f of def.fields) {
      if (f.default !== undefined) values.value[def.key][f.name] = f.default;
      else values.value[def.key][f.name] = "";
    }
    await loadRecent();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Submit failed";
  } finally {
    submitting.value = false;
  }
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diffMin = Math.round((now.getTime() - d.getTime()) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
  return d.toLocaleDateString();
}

function payloadSummary(a: Annotation): string {
  const t = TYPES.find((x) => x.key === a.type);
  if (!t) return JSON.stringify(a.payload);
  return t.fields.map((f) => `${a.payload[f.name] ?? ""}`).filter(Boolean).join(" · ");
}

// ── Inline edit ─────────────────────────────────────────────
type EditDraft = {
  id: number;
  type: LogType;
  ts: string;          // <input type="datetime-local"> value (yyyy-MM-ddTHH:mm)
  payload: Record<string, string | number>;
  note: string;
};
const editing = ref<EditDraft | null>(null);
const editError = ref<string | null>(null);
const editSaving = ref(false);

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  // YYYY-MM-DDTHH:mm in *local* time, no seconds — what <input type="datetime-local"> wants
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocalInput(s: string): string {
  // Parse the local-clock string and emit ISO UTC
  return new Date(s).toISOString();
}

function startEdit(a: Annotation) {
  editError.value = null;
  const def = TYPES.find((t) => t.key === a.type);
  const payload: Record<string, string | number> = {};
  if (def) {
    for (const f of def.fields) {
      const v = a.payload[f.name];
      payload[f.name] = (typeof v === "string" || typeof v === "number") ? v : "";
    }
  } else {
    Object.assign(payload, a.payload as Record<string, string | number>);
  }
  editing.value = {
    id: a.id,
    type: a.type as LogType,
    ts: toLocalInput(a.ts),
    payload,
    note: a.note ?? "",
  };
}
function cancelEdit() { editing.value = null; editError.value = null; }

async function saveEdit() {
  if (!editing.value) return;
  editSaving.value = true;
  editError.value = null;
  const def = TYPES.find((t) => t.key === editing.value!.type);
  const payload: Record<string, unknown> = { ...editing.value.payload };
  if (def) {
    for (const f of def.fields) if (f.type === "number") payload[f.name] = Number(payload[f.name] ?? 0);
  }
  try {
    await api.updateAnnotation(editing.value.id, {
      ts: fromLocalInput(editing.value.ts),
      payload,
      note: editing.value.note || null,
    });
    editing.value = null;
    await loadRecent();
  } catch (e) {
    editError.value = e instanceof Error ? e.message : "Save failed";
  } finally {
    editSaving.value = false;
  }
}

async function removeEntry(a: Annotation) {
  if (!confirm(`Delete this ${a.type} entry?`)) return;
  try {
    await api.deleteAnnotation(a.id);
    await loadRecent();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Delete failed";
  }
}

function fieldsFor(type: LogType): TypeDef["fields"] {
  return TYPES.find((t) => t.key === type)?.fields ?? [];
}

onMounted(loadRecent);
</script>

<template>
  <div class="log">
    <h1>Log</h1>

    <div class="picker">
      <button
        v-for="t in TYPES" :key="t.key"
        :class="{ active: selected === t.key }"
        @click="selected = t.key"
      >
        <span class="emoji">{{ t.emoji }}</span>
        <span>{{ t.label }}</span>
      </button>
    </div>

    <form class="entry" @submit.prevent="submit">
      <div class="fields">
        <label v-for="f in currentDef.fields" :key="f.name">
          <span>{{ f.label }}</span>
          <input
            v-model="values[selected][f.name]"
            :type="f.type ?? 'text'"
            :placeholder="f.placeholder"
            :inputmode="f.type === 'number' ? 'decimal' : 'text'"
          />
        </label>
      </div>
      <label class="note">
        <span>note (optional)</span>
        <input v-model="noteText[selected]" placeholder="extra context…" />
      </label>
      <button type="submit" :disabled="submitting" class="submit">
        {{ submitting ? "Saving…" : `Log ${currentDef.label.toLowerCase()}` }}
      </button>
      <div v-if="justSaved" class="ok">{{ justSaved }}</div>
      <div v-if="error" class="err">{{ error }}</div>
    </form>

    <h2>Recent</h2>
    <ul class="recent">
      <template v-for="a in recent" :key="a.id">
        <li v-if="editing?.id !== a.id" class="row">
          <span class="when" :title="new Date(a.ts).toLocaleString()">{{ formatTime(a.ts) }}</span>
          <span class="what">
            <strong>{{ a.type }}</strong> {{ payloadSummary(a) }}
          </span>
          <span v-if="a.note" class="note-out">— {{ a.note }}</span>
          <span class="row-actions">
            <button class="icon-btn" title="Edit" @click="startEdit(a)">
              <Pencil :size="14"/>
            </button>
            <button class="icon-btn danger" title="Delete" @click="removeEntry(a)">
              <Trash2 :size="14"/>
            </button>
          </span>
        </li>
        <li v-else class="row editing">
          <form class="edit-grid" @submit.prevent="saveEdit">
            <div class="edit-head">
              <strong>{{ editing.type }}</strong>
              <span class="muted">edit</span>
            </div>
            <label class="edit-field">
              <span>when</span>
              <input v-model="editing.ts" type="datetime-local" step="60"/>
            </label>
            <label v-for="f in fieldsFor(editing.type)" :key="f.name" class="edit-field">
              <span>{{ f.label }}</span>
              <input
                v-model="editing.payload[f.name]"
                :type="f.type ?? 'text'"
                :inputmode="f.type === 'number' ? 'decimal' : 'text'"
                :placeholder="f.placeholder"
              />
            </label>
            <label class="edit-field edit-note">
              <span>note</span>
              <input v-model="editing.note" placeholder="optional"/>
            </label>
            <div class="edit-actions">
              <button type="submit" class="primary" :disabled="editSaving">
                <Check :size="14"/> {{ editSaving ? "Saving…" : "Save" }}
              </button>
              <button type="button" class="ghost" @click="cancelEdit">
                <X :size="14"/> Cancel
              </button>
            </div>
            <div v-if="editError" class="err edit-err">{{ editError }}</div>
          </form>
        </li>
      </template>
      <li v-if="recent.length === 0" class="empty">No entries yet.</li>
    </ul>
  </div>
</template>

<style scoped>
.log { max-width: 640px; }
h1 { margin: 0 0 1rem; }
h2 { font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin: 1.5rem 0 0.5rem; }

.picker { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
.picker button {
  background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
  border-radius: 8px; padding: 0.7rem; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; gap: 0.2rem;
  font-size: 0.85rem; font-weight: 500;
}
.picker button.active { background: #38bdf8; color: #0f172a; border-color: #38bdf8; }
.emoji { font-size: 1.4rem; }

.entry { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1rem; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.6rem; }
label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; color: #94a3b8; }
input { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.5rem; font-size: 1rem; }
input:focus { outline: none; border-color: #38bdf8; }
.note { margin-top: 0.6rem; }
.submit { margin-top: 0.8rem; width: 100%; background: #38bdf8; color: #0f172a; border: 0; border-radius: 8px; padding: 0.7rem; font-weight: 600; cursor: pointer; }
.submit:disabled { opacity: 0.5; cursor: not-allowed; }
.ok { color: #22c55e; margin-top: 0.5rem; font-size: 0.85rem; }
.err { color: #ef4444; margin-top: 0.5rem; font-size: 0.85rem; }

.recent { list-style: none; padding: 0; margin: 0; }
.recent li.row { display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }
.when { color: #64748b; flex-shrink: 0; min-width: 70px; font-size: 0.8rem; }
.what { flex: 1; min-width: 0; }
.what strong { color: #38bdf8; font-weight: 500; text-transform: capitalize; }
.note-out { color: #64748b; font-style: italic; }
.empty { color: #64748b; padding: 1rem 0; text-align: center; border: none; }

.row-actions { display: flex; gap: 0.25rem; opacity: 0.5; transition: opacity 0.15s; flex-shrink: 0; }
.row:hover .row-actions { opacity: 1; }
.icon-btn {
  background: transparent; border: 1px solid transparent;
  border-radius: 6px; padding: 0.25rem; cursor: pointer; color: #94a3b8;
  display: inline-flex; align-items: center; justify-content: center;
}
.icon-btn:hover { color: #e2e8f0; border-color: #334155; }
.icon-btn.danger:hover { color: #ef4444; border-color: rgba(239, 68, 68, 0.3); }

.row.editing {
  background: rgba(56, 189, 248, 0.04);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 8px;
  padding: 0.7rem 0.85rem;
  margin: 0.4rem 0;
  display: block;
}
.edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.6rem; }
.edit-head { grid-column: 1 / -1; display: flex; gap: 0.4rem; align-items: baseline; margin-bottom: -0.2rem; }
.edit-head strong { color: #38bdf8; text-transform: capitalize; }
.edit-head .muted { color: #64748b; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; }
.edit-field { gap: 0.2rem; font-size: 0.75rem; }
.edit-field input {
  background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
  border-radius: 6px; padding: 0.45rem 0.55rem; font-size: 0.9rem;
  font-family: inherit;
}
.edit-note { grid-column: 1 / -1; }
.edit-actions { grid-column: 1 / -1; display: flex; gap: 0.4rem; justify-content: flex-end; margin-top: 0.2rem; }
.edit-actions .primary {
  background: #38bdf8; color: #0f172a; border: 0; border-radius: 6px;
  padding: 0.45rem 0.85rem; font-weight: 600; cursor: pointer;
  display: inline-flex; align-items: center; gap: 0.3rem;
}
.edit-actions .primary:disabled { opacity: 0.5; cursor: not-allowed; }
.edit-actions .ghost {
  background: transparent; color: #94a3b8; border: 1px solid #334155;
  border-radius: 6px; padding: 0.45rem 0.85rem; cursor: pointer;
  display: inline-flex; align-items: center; gap: 0.3rem;
}
.edit-err { grid-column: 1 / -1; }
</style>
