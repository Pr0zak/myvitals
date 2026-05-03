<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { api } from "@/api/client";
import type { AppLog } from "@/api/types";

const logs = ref<AppLog[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const autoRefresh = ref(true);
const sourceFilter = ref<string>("");      // "" | "phone" | "server"
const levelFilter = ref<string>("DEBUG");  // min level
let pollHandle: number | null = null;

async function load() {
  loading.value = true;
  error.value = null;
  try {
    logs.value = await api.logs({
      source: sourceFilter.value || undefined,
      level: levelFilter.value,
      limit: 500,
    });
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

function startPolling() {
  stopPolling();
  if (autoRefresh.value) pollHandle = window.setInterval(load, 5000);
}
function stopPolling() {
  if (pollHandle !== null) { window.clearInterval(pollHandle); pollHandle = null; }
}

watch([autoRefresh, sourceFilter, levelFilter], () => {
  load();
  if (autoRefresh.value) startPolling(); else stopPolling();
});

onMounted(() => { load(); startPolling(); });
onUnmounted(stopPolling);

const grouped = computed(() => logs.value);

function levelColor(level: string): string {
  switch (level) {
    case "ERROR": return "#ef4444";
    case "WARN":  return "#eab308";
    case "INFO":  return "#38bdf8";
    case "DEBUG": return "#94a3b8";
    default:      return "#64748b";
  }
}

function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3,
  });
}
</script>

<template>
  <div class="logs">
    <header class="head">
      <h1>Logs</h1>
      <div class="controls">
        <select v-model="sourceFilter">
          <option value="">all sources</option>
          <option value="phone">phone</option>
          <option value="server">server</option>
        </select>
        <select v-model="levelFilter">
          <option value="DEBUG">debug+</option>
          <option value="INFO">info+</option>
          <option value="WARN">warn+</option>
          <option value="ERROR">error</option>
        </select>
        <label class="auto"><input type="checkbox" v-model="autoRefresh"/> auto-refresh</label>
        <button @click="load" :disabled="loading">Refresh</button>
      </div>
    </header>

    <div v-if="error" class="err">{{ error }}</div>

    <div class="stream">
      <div v-for="entry in grouped" :key="entry.id" class="row" :class="entry.level.toLowerCase()">
        <span class="ts">{{ fmtTime(entry.ts) }}</span>
        <span class="src" :title="entry.source">{{ entry.source.charAt(0).toUpperCase() }}</span>
        <span class="lvl" :style="{ color: levelColor(entry.level) }">{{ entry.level }}</span>
        <span class="tag">{{ entry.tag ?? "-" }}</span>
        <span class="msg">{{ entry.message }}</span>
        <pre v-if="entry.stack" class="stack">{{ entry.stack }}</pre>
      </div>
      <div v-if="!loading && grouped.length === 0" class="empty">No logs in the last 24h.</div>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 1rem; }
h1 { margin: 0; }
.controls { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; font-size: 0.85rem; }
select, button { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 0.3rem 0.5rem; font-size: 0.8rem; }
button:disabled { opacity: 0.5; }
.auto { color: #94a3b8; display: flex; gap: 0.3rem; align-items: center; }

.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin: 0.6rem 0; }
.empty { color: #64748b; padding: 2rem 0; text-align: center; }

.stream { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.78rem; margin-top: 1rem; }
.row {
  display: grid;
  grid-template-columns: 90px 20px 50px 100px 1fr;
  gap: 0.6rem;
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid #1e293b;
  align-items: baseline;
}
.row.error { background: rgba(239, 68, 68, 0.06); }
.row.warn { background: rgba(234, 179, 8, 0.06); }
.ts { color: #64748b; }
.src { color: #a78bfa; font-weight: 600; }
.lvl { font-weight: 600; }
.tag { color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg { color: #e2e8f0; word-break: break-word; }
.stack { grid-column: 1 / -1; color: #f87171; margin: 0.3rem 0 0.3rem 5.5rem; padding: 0.3rem 0.5rem; background: rgba(0, 0, 0, 0.25); border-radius: 4px; white-space: pre-wrap; font-size: 0.72rem; }
</style>
