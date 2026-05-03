<script setup lang="ts">
import { ref } from "vue";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";

const tokenInput = ref(queryToken.value);
const apiBaseInput = ref(apiBase.value);
const status = ref<"idle" | "ok" | "fail">("idle");
const errorMsg = ref<string>("");

function save() {
  queryToken.value = tokenInput.value.trim();
  apiBase.value = apiBaseInput.value.trim();
  status.value = "idle";
  errorMsg.value = "";
}

async function test() {
  save();
  errorMsg.value = "";
  try {
    await api.health();
    // /health doesn't require auth; check a token-protected endpoint to validate the bearer.
    await api.lastSync();
    status.value = "ok";
  } catch (e: unknown) {
    status.value = "fail";
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { status?: number; data?: unknown } }).response;
      errorMsg.value = `HTTP ${r?.status ?? "?"} — ${JSON.stringify(r?.data ?? "")}`;
    } else {
      errorMsg.value = e instanceof Error ? e.message : String(e);
    }
  }
}

function clearAll() {
  queryToken.value = "";
  apiBase.value = "";
  tokenInput.value = "";
  apiBaseInput.value = "";
  status.value = "idle";
  errorMsg.value = "";
}
</script>

<template>
  <div class="settings">
    <h1>Settings</h1>
    <p class="hint">
      Stored locally in this browser only. They never leave the device, and they're
      not committed anywhere.
    </p>

    <label>
      <span>Query token</span>
      <input
        v-model="tokenInput"
        type="password"
        placeholder="paste the QUERY_TOKEN from the backend .env"
        autocomplete="off"
      />
    </label>

    <label>
      <span>API base URL <em class="opt">(optional — leave blank to use the same host)</em></span>
      <input
        v-model="apiBaseInput"
        placeholder="e.g. http://10.0.0.82:8000   (no /api suffix)"
        autocomplete="off"
      />
    </label>

    <div class="actions">
      <button class="primary" @click="test">Save & test</button>
      <button class="ghost" @click="save">Save without testing</button>
      <button class="ghost danger" @click="clearAll">Clear</button>
    </div>

    <div v-if="status === 'ok'" class="ok">✓ Reached the backend with this token.</div>
    <div v-if="status === 'fail'" class="err">
      ✗ Could not authenticate.<br/>
      <small>{{ errorMsg }}</small>
    </div>
  </div>
</template>

<style scoped>
.settings { max-width: 560px; }
h1 { margin: 0 0 0.4rem; }
.hint { color: #94a3b8; font-size: 0.9rem; margin: 0 0 1.2rem; }
label { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 1rem; font-size: 0.85rem; color: #94a3b8; }
.opt { color: #64748b; font-style: italic; font-weight: normal; font-size: 0.8rem; }
input { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem; font-size: 1rem; font-family: inherit; }
input:focus { outline: none; border-color: #38bdf8; }
.actions { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; }
button { border-radius: 6px; padding: 0.55rem 1rem; cursor: pointer; font-weight: 500; border: 1px solid transparent; }
.primary { background: #38bdf8; color: #0f172a; }
.ghost { background: transparent; color: #94a3b8; border-color: #334155; }
.danger { color: #ef4444; }
.ok { color: #22c55e; padding: 0.6rem 0.8rem; background: rgba(34, 197, 94, 0.1); border-left: 3px solid #22c55e; margin-top: 0.6rem; }
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin-top: 0.6rem; }
.err small { color: #94a3b8; font-family: monospace; }
</style>
