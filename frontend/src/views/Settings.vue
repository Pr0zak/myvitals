<script setup lang="ts">
import axios from "axios";
import { onMounted, ref } from "vue";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import type { StravaAppConfigStatus, StravaStatus } from "@/api/types";

const tokenInput = ref(queryToken.value);
const apiBaseInput = ref(apiBase.value);
const status = ref<"idle" | "ok" | "fail">("idle");
const errorMsg = ref<string>("");

const strava = ref<StravaStatus | null>(null);
const stravaConfig = ref<StravaAppConfigStatus | null>(null);
const stravaError = ref<string | null>(null);
const stravaSyncing = ref(false);
const stravaSyncResult = ref<string>("");

// Strava OAuth credential fields (dashboard-editable)
const cidInput = ref("");
const secretInput = ref("");
const callbackInput = ref("");
const credsSaving = ref(false);
const credsResult = ref<string>("");
const editingCreds = ref(false);

const analyticsRunning = ref(false);
const analyticsResult = ref<string>("");

const EXPORT_TABLES = [
  "heartrate", "hrv", "steps", "sleep_stages", "workouts",
  "annotations", "activities", "daily_summary",
];

function exportUrl(table: string, fmt: "csv" | "json"): string {
  const base = (apiBase.value || "/api").replace(/\/$/, "");
  // We can't add Authorization headers to a plain <a> click — use a query
  // param the backend accepts, OR force the user to be on the same origin
  // where Caddy forwards the bearer header... actually our backend requires
  // the Bearer header. Easier: keep the same-origin /api/ proxy (which
  // doesn't do auth either) — so this only works because the user is
  // already on the dashboard on the same host. Token is injected client-side
  // via a fetch + blob trick:
  return `${base}/export/${table}.${fmt}`;
}

async function downloadExport(table: string, fmt: "csv" | "json") {
  const r = await axios.get(exportUrl(table, fmt), {
    headers: { Authorization: `Bearer ${queryToken.value}` },
    responseType: "blob",
  });
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `myvitals-${table}.${fmt}`;
  a.click();
  URL.revokeObjectURL(url);
}

async function runAnalytics() {
  analyticsRunning.value = true;
  analyticsResult.value = "";
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const r = await axios.post(`${base}/analytics/run`, null, {
      headers: { Authorization: `Bearer ${queryToken.value}` },
    });
    analyticsResult.value = `Ran analytics for ${r.data.target_date}.`;
  } catch (e) {
    analyticsResult.value = `Failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    analyticsRunning.value = false;
  }
}

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
  stravaConfig.value = null;
}

async function loadStrava() {
  if (!queryToken.value) return;
  stravaError.value = null;
  try {
    [strava.value, stravaConfig.value] = await Promise.all([
      api.stravaStatus(),
      api.stravaConfig(),
    ]);
    // Default the callback URL field to whatever this dashboard's host is —
    // saves the user from typing it. They can override before saving.
    callbackInput.value = stravaConfig.value.callback_url
      ?? `${window.location.origin}/auth/strava/callback`;
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

async function saveStravaCreds() {
  credsSaving.value = true;
  credsResult.value = "";
  try {
    await api.saveStravaConfig({
      client_id: cidInput.value,
      client_secret: secretInput.value,
      callback_url: callbackInput.value || null,
    });
    credsResult.value = "Saved. You can now Connect Strava.";
    cidInput.value = "";
    secretInput.value = "";
    editingCreds.value = false;
    await loadStrava();
  } catch (e: unknown) {
    credsResult.value = `Save failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    credsSaving.value = false;
  }
}

async function clearStravaCreds() {
  if (!confirm("Clear stored Strava OAuth credentials? Existing connection will stop working.")) return;
  try {
    await api.clearStravaConfig();
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
      <h2>Tools</h2>
      <div class="tools">
        <button class="ghost" @click="runAnalytics" :disabled="analyticsRunning">
          {{ analyticsRunning ? "Running…" : "Run analytics now" }}
        </button>
        <span v-if="analyticsResult" class="hint">{{ analyticsResult }}</span>
      </div>
      <h3 class="sub">Export raw data</h3>
      <div class="exports">
        <button v-for="t in EXPORT_TABLES" :key="t" class="dl" @click="downloadExport(t, 'csv')">{{ t }}.csv</button>
        <button v-for="t in EXPORT_TABLES" :key="`${t}-json`" class="dl json" @click="downloadExport(t, 'json')">{{ t }}.json</button>
      </div>
    </section>

    <section v-if="queryToken">
      <h2>Strava</h2>
      <div v-if="stravaError" class="err">{{ stravaError }}</div>

      <template v-if="strava && stravaConfig">
        <!-- OAuth credentials block -->
        <div class="block">
          <p v-if="!stravaConfig.configured" class="hint">
            Create an app at
            <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer">strava.com/settings/api</a>
            (Authorization Callback Domain = host of this dashboard, no port). Then paste the Client ID + Client Secret.
          </p>
          <p v-else class="muted">
            OAuth app credentials: <code>{{ stravaConfig.client_id_masked }}</code>
            <span class="muted"> · source: {{ stravaConfig.source }}</span><br/>
            <span class="muted">Callback: {{ stravaConfig.callback_url }}</span>
          </p>

          <div v-if="!stravaConfig.configured || editingCreds" class="form">
            <label>
              <span>Client ID</span>
              <input v-model="cidInput" placeholder="e.g. 123456" autocomplete="off"/>
            </label>
            <label>
              <span>Client Secret</span>
              <input v-model="secretInput" type="password" placeholder="40-char hex" autocomplete="off"/>
            </label>
            <label>
              <span>Callback URL <em class="opt">(optional)</em></span>
              <input v-model="callbackInput" placeholder="http://your-server:8080/auth/strava/callback" autocomplete="off"/>
            </label>
            <div class="actions">
              <button class="primary" :disabled="credsSaving" @click="saveStravaCreds">
                {{ credsSaving ? "Saving…" : "Save credentials" }}
              </button>
              <button v-if="editingCreds" class="ghost" @click="editingCreds = false">Cancel</button>
            </div>
            <div v-if="credsResult" class="hint">{{ credsResult }}</div>
          </div>

          <div v-else class="actions">
            <button class="ghost" @click="editingCreds = true">Edit credentials</button>
            <button v-if="stravaConfig.source === 'db'" class="ghost danger" @click="clearStravaCreds">
              Clear stored credentials
            </button>
          </div>
        </div>

        <!-- Connection block (only meaningful once OAuth app is configured) -->
        <div v-if="stravaConfig.configured" class="block">
          <template v-if="strava.connected">
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
            <p class="hint">Authorize myvitals to read your activities (rides, runs, etc.).</p>
            <div class="actions">
              <button class="primary" @click="connectStrava">Connect Strava</button>
            </div>
          </template>
        </div>
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
.block { margin-bottom: 1.5rem; padding-bottom: 1.5rem; border-bottom: 1px solid #1e293b; }
.block:last-child { border-bottom: none; padding-bottom: 0; }
.form { margin: 0.6rem 0; }
.hint { color: #94a3b8; font-size: 0.9rem; margin: 0 0 1.2rem; }
.hint a { color: #38bdf8; }
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
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin-top: 0.6rem; }
.err small { color: #94a3b8; font-family: monospace; }
.muted { color: #94a3b8; font-size: 0.85rem; }
code { background: var(--surface); padding: 0.1rem 0.3rem; border-radius: 3px; font-family: ui-monospace, monospace; font-size: 0.85rem; color: var(--accent); }

.tools { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 1rem; }
h3.sub { font-size: 0.75rem; color: var(--muted-2); text-transform: uppercase; letter-spacing: 0.05em; margin: 1rem 0 0.5rem; font-weight: 500; }
.exports { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.exports .dl {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.3rem 0.6rem; font-size: 0.75rem; cursor: pointer;
  font-family: ui-monospace, monospace;
}
.exports .dl:hover { border-color: var(--accent); color: var(--accent); }
.exports .dl.json { color: var(--muted); }
</style>
