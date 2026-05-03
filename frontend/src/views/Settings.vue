<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import type { StravaStatus } from "@/api/types";

const tokenInput = ref(queryToken.value);
const apiBaseInput = ref(apiBase.value);
const status = ref<"idle" | "ok" | "fail">("idle");
const errorMsg = ref<string>("");

const strava = ref<StravaStatus | null>(null);
const stravaError = ref<string | null>(null);
const stravaSyncing = ref(false);
const stravaSyncResult = ref<string>("");

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
    await api.lastSync();
    status.value = "ok";
    await loadStrava();
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
  strava.value = null;
}

async function loadStrava() {
  if (!queryToken.value) return;
  stravaError.value = null;
  try {
    strava.value = await api.stravaStatus();
  } catch (e: unknown) {
    stravaError.value = e instanceof Error ? e.message : String(e);
  }
}

function connectStrava() {
  // Backend returns a 302 to Strava; let the browser follow it (not axios).
  window.location.href = `${apiBase.value || ""}/auth/strava/login`;
}

async function syncStrava(days: number) {
  stravaSyncing.value = true;
  stravaSyncResult.value = "";
  try {
    const r = await api.stravaSync(days);
    stravaSyncResult.value = `Pulled ${r.upserted} activities from the last ${r.days} days.`;
    await loadStrava();
  } catch (e: unknown) {
    stravaSyncResult.value = `Sync failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    stravaSyncing.value = false;
  }
}

async function disconnectStrava() {
  if (!confirm("Disconnect Strava? Stored activities will stay; tokens will be wiped.")) return;
  try {
    await api.stravaDisconnect();
    await loadStrava();
  } catch (e) {
    stravaError.value = e instanceof Error ? e.message : String(e);
  }
}

function fmt(ts: string | null): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString();
}

onMounted(loadStrava);
</script>

<template>
  <div class="settings">
    <h1>Settings</h1>

    <section>
      <h2>Backend access</h2>
      <p class="hint">
        Stored locally in this browser only. They never leave the device, and they're
        not committed anywhere.
      </p>

      <label>
        <span>Query token</span>
        <input v-model="tokenInput" type="password"
               placeholder="paste the QUERY_TOKEN from the backend .env" autocomplete="off"/>
      </label>

      <label>
        <span>API base URL <em class="opt">(optional — leave blank to use the same host)</em></span>
        <input v-model="apiBaseInput"
               placeholder="e.g. http://your-server:8000   (no /api suffix)" autocomplete="off"/>
      </label>

      <div class="actions">
        <button class="primary" @click="test">Save &amp; test</button>
        <button class="ghost" @click="save">Save without testing</button>
        <button class="ghost danger" @click="clearAll">Clear</button>
      </div>

      <div v-if="status === 'ok'" class="ok">✓ Reached the backend with this token.</div>
      <div v-if="status === 'fail'" class="err">
        ✗ Could not authenticate.<br/>
        <small>{{ errorMsg }}</small>
      </div>
    </section>

    <section v-if="queryToken">
      <h2>Strava</h2>
      <div v-if="stravaError" class="err">{{ stravaError }}</div>

      <template v-if="strava">
        <p v-if="!strava.configured" class="warn">
          Backend is missing <code>STRAVA_CLIENT_ID</code> / <code>STRAVA_CLIENT_SECRET</code>.
          Add them to <code>.env</code> on the CT and restart the backend.
        </p>

        <template v-else-if="strava.connected">
          <p class="ok-text">
            ✓ Connected as <strong>{{ strava.athlete_name ?? strava.athlete_id }}</strong>
            <span class="muted"> · scope: {{ strava.scope }}</span><br/>
            <span class="muted">Last sync: {{ fmt(strava.last_sync_at) }}</span>
          </p>
          <div class="actions">
            <button class="primary" :disabled="stravaSyncing" @click="syncStrava(90)">
              {{ stravaSyncing ? "Syncing…" : "Sync last 90 days" }}
            </button>
            <button class="ghost" :disabled="stravaSyncing" @click="syncStrava(30)">Sync 30d</button>
            <button class="ghost" :disabled="stravaSyncing" @click="syncStrava(365)">Sync 1y</button>
            <button class="ghost danger" @click="disconnectStrava">Disconnect</button>
          </div>
          <div v-if="stravaSyncResult" class="hint">{{ stravaSyncResult }}</div>
        </template>

        <template v-else>
          <p class="hint">Pull rides, runs, and other activities directly from Strava (full GPS, splits, suffer score, etc.).</p>
          <div class="actions">
            <button class="primary" @click="connectStrava">Connect Strava</button>
          </div>
        </template>
      </template>

      <div v-else-if="!stravaError" class="hint">Loading…</div>
    </section>
  </div>
</template>

<style scoped>
.settings { max-width: 640px; }
h1 { margin: 0 0 0.4rem; }
h2 { font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin: 1.5rem 0 0.5rem; }
section { margin-bottom: 2rem; }
.hint { color: #94a3b8; font-size: 0.9rem; margin: 0 0 1.2rem; }
label { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 1rem; font-size: 0.85rem; color: #94a3b8; }
.opt { color: #64748b; font-style: italic; font-weight: normal; font-size: 0.8rem; }
input { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem; font-size: 1rem; font-family: inherit; }
input:focus { outline: none; border-color: #38bdf8; }
.actions { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; }
button { border-radius: 6px; padding: 0.55rem 1rem; cursor: pointer; font-weight: 500; border: 1px solid transparent; }
.primary { background: #38bdf8; color: #0f172a; }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost { background: transparent; color: #94a3b8; border-color: #334155; }
.danger { color: #ef4444; }
.ok { color: #22c55e; padding: 0.6rem 0.8rem; background: rgba(34, 197, 94, 0.1); border-left: 3px solid #22c55e; margin-top: 0.6rem; }
.ok-text { color: #22c55e; }
.warn { color: #eab308; padding: 0.6rem 0.8rem; background: rgba(234, 179, 8, 0.1); border-left: 3px solid #eab308; }
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin-top: 0.6rem; }
.err small { color: #94a3b8; font-family: monospace; }
.muted { color: #94a3b8; font-size: 0.85rem; }
code { background: #0f172a; padding: 0.1rem 0.3rem; border-radius: 3px; font-family: ui-monospace, monospace; font-size: 0.85rem; }
</style>
