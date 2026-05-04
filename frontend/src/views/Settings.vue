<script setup lang="ts">
import axios from "axios";
import { onMounted, onUnmounted, ref } from "vue";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import { units } from "@/units";
import type { StravaAppConfigStatus, StravaStatus } from "@/api/types";

const tokenInput = ref(queryToken.value);
const tokenVisible = ref(false);
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

// Historical imports
const importBusy = ref<"" | "fitbit" | "garmin">("");
const importResult = ref<string>("");
const importError = ref<string>("");
const fitbitWeightUnit = ref<"kg" | "lb">("lb");

// Live job tracker
type ImportJob = Awaited<ReturnType<typeof api.importJobs>>[number];
const jobs = ref<ImportJob[]>([]);
let jobPoll: ReturnType<typeof setInterval> | null = null;

async function refreshJobs() {
  if (!queryToken.value) return;
  try {
    jobs.value = await api.importJobs(20);
  } catch {
    /* ignore polling errors — log shows them in the network tab */
  }
}

function startJobPolling() {
  if (jobPoll) return;
  refreshJobs();
  jobPoll = setInterval(refreshJobs, 3000);
}
function stopJobPolling() {
  if (jobPoll) { clearInterval(jobPoll); jobPoll = null; }
}

function jobAge(j: ImportJob): string {
  const s = Math.round(j.elapsed_s ?? 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

type ImportKind = "fitbit" | "garmin" | "garmin_tracks";

async function uploadImport(kind: ImportKind, file: File) {
  importBusy.value = kind === "garmin_tracks" ? "garmin" : kind;
  importResult.value = "";
  importError.value = "";
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const fd = new FormData();
    fd.append("file", file);
    const params: Record<string, string> = {};
    if (kind === "fitbit") params.weight_unit = fitbitWeightUnit.value;
    const path = kind === "garmin_tracks" ? "/import/garmin/tracks"
               : kind === "fitbit" ? "/import/fitbit"
               : "/import/garmin";
    const r = await axios.post(`${base}${path}`, fd, {
      headers: {
        Authorization: `Bearer ${queryToken.value}`,
        "Content-Type": "multipart/form-data",
      },
      params,
      maxContentLength: 1024 * 1024 * 1024,
      maxBodyLength: 1024 * 1024 * 1024,
    });
    if (kind === "garmin_tracks") {
      importResult.value = `Track parsing started — job ${r.data.job_id}. Watch progress in Recent jobs below.`;
    } else {
      const counts = r.data?.imported ?? {};
      const parts = Object.entries(counts).map(([k, v]) => `${k}: ${v}`);
      importResult.value = parts.length
        ? `Imported from ${kind} — ${parts.join(", ")}.`
        : `Upload accepted but no recognised files were found in the ZIP.`;
    }
    refreshJobs();
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { status?: number; data?: unknown } }).response;
      importError.value = `HTTP ${r?.status ?? "?"} — ${JSON.stringify(r?.data ?? "")}`;
    } else {
      importError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    importBusy.value = "";
  }
}

function pickImportFile(kind: ImportKind) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = ".zip,application/zip";
  inp.onchange = () => {
    const f = inp.files?.[0];
    if (f) uploadImport(kind, f);
  };
  inp.click();
}

const EXPORT_TABLES = [
  "heartrate", "hrv", "steps", "sleep_stages", "workouts",
  "annotations", "activities", "daily_summary",
  "body_metrics", "skin_temp", "blood_pressure",
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

onMounted(() => {
  loadStrava();
  startJobPolling();
});
onUnmounted(stopJobPolling);
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
        <div class="token-row">
          <input v-model="tokenInput" :type="tokenVisible ? 'text' : 'password'"
                 placeholder="paste the QUERY_TOKEN from the backend .env" autocomplete="off"/>
          <button type="button" class="eye" @click="tokenVisible = !tokenVisible"
                  :title="tokenVisible ? 'Hide token' : 'Show token'">
            {{ tokenVisible ? '🙈' : '👁' }}
          </button>
        </div>
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

    <section>
      <h2>Display</h2>
      <label style="flex-direction: row; align-items: center; gap: 0.6rem;">
        <span>Units:</span>
        <label><input type="radio" value="metric" v-model="units"/> metric (km, kg, °C)</label>
        <label><input type="radio" value="imperial" v-model="units"/> imperial (mi, lb, °F)</label>
      </label>
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
      <h2>Historical imports</h2>
      <p class="hint">
        One-shot bulk loads from a downloaded provider archive — useful for back-filling
        years of data the watch doesn't have. Heart rate, sleep, steps and activities
        all get merged into the existing tables (duplicates are skipped).
      </p>
      <div class="imports">
        <div class="import-card">
          <strong>Fitbit</strong>
          <p class="muted">
            Request your archive from
            <a href="https://www.fitbit.com/settings/data/export" target="_blank" rel="noreferrer">fitbit.com/settings/data/export</a>
            (or via Google Takeout if your account migrated). Upload the unmodified ZIP.
          </p>
          <div class="unit-row">
            <span class="muted">Weight unit in this archive:</span>
            <label><input type="radio" value="kg" v-model="fitbitWeightUnit"/> kg</label>
            <label><input type="radio" value="lb" v-model="fitbitWeightUnit"/> lb</label>
          </div>
          <button class="ghost" :disabled="!!importBusy" @click="pickImportFile('fitbit')">
            {{ importBusy === 'fitbit' ? 'Uploading…' : 'Upload Fitbit ZIP' }}
          </button>
        </div>
        <div class="import-card">
          <strong>Garmin Connect</strong>
          <p class="muted">
            Request your archive from
            <a href="https://www.garmin.com/account/datamanagement/exportdata" target="_blank" rel="noreferrer">garmin.com/account/datamanagement/exportdata</a>.
            Upload the ZIP once it arrives by email.
          </p>
          <button class="ghost" :disabled="!!importBusy" @click="pickImportFile('garmin')">
            {{ importBusy === 'garmin' ? 'Uploading…' : 'Upload Garmin ZIP (summary)' }}
          </button>
          <button class="ghost" :disabled="!!importBusy" @click="pickImportFile('garmin_tracks')"
                  style="margin-top: 0.4rem;">
            Upload Garmin ZIP (GPS + tracks)
          </button>
          <p class="muted" style="margin-top: 0.4rem; font-size: 0.75rem;">
            The track upload reads FIT files (~22k for a long history) and attaches GPS polylines to your activities. Background job, watch progress below.
          </p>
        </div>
      </div>
      <div v-if="importResult" class="ok">{{ importResult }}</div>
      <div v-if="importError" class="err"><small>{{ importError }}</small></div>

      <h3 class="sub">Recent jobs</h3>
      <div v-if="jobs.length === 0" class="hint">No imports yet.</div>
      <table v-else class="jobs">
        <thead>
          <tr>
            <th>Kind</th><th>Status</th><th>Elapsed</th><th>Rows</th><th>Streams</th><th>File</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id" :class="`job-${j.status}`">
            <td>{{ j.kind }}</td>
            <td>
              <span class="dot" :class="`dot-${j.status}`"></span>
              {{ j.status }}
            </td>
            <td>{{ jobAge(j) }}</td>
            <td>{{ j.total_rows.toLocaleString() }}</td>
            <td class="counts">
              <span v-for="(n, k) in j.counts" :key="k" class="chip">
                {{ k }}: {{ (n as number).toLocaleString() }}
              </span>
            </td>
            <td class="filename" :title="j.filename ?? ''">
              {{ j.filename ?? '—' }}
              <span v-if="j.size_bytes" class="muted">
                ({{ ((j.size_bytes as number) / 1024 / 1024).toFixed(0) }} MB)
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="jobs.some((j) => j.error)" class="err">
        <small v-for="j in jobs.filter((x) => x.error)" :key="j.id">
          job {{ j.id }} ({{ j.kind }}): {{ (j.error || '').split('\n').slice(-3).join(' / ') }}
        </small>
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
              <button class="ghost" :disabled="stravaSyncing" @click="syncStrava(3650)">Sync all</button>
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
.imports { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; }
@media (max-width: 600px) { .imports { grid-template-columns: 1fr; } }
.import-card {
  border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem 1rem;
  background: var(--surface);
}
.import-card strong { display: block; margin-bottom: 0.3rem; color: var(--text); }
.import-card p { font-size: 0.85rem; margin: 0 0 0.6rem; }
.unit-row { display: flex; gap: 0.6rem; align-items: center; font-size: 0.8rem; margin-bottom: 0.5rem; }
.unit-row label { display: inline-flex; align-items: center; gap: 0.2rem; cursor: pointer; }
.token-row { display: flex; gap: 0.4rem; }
.token-row input { flex: 1; }
.eye {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 0 0.7rem; cursor: pointer; font-size: 1.1rem;
}
.eye:hover { border-color: var(--accent); }

.jobs { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 0.4rem; }
.jobs th { text-align: left; color: var(--muted-2); font-size: 0.7rem; text-transform: uppercase; padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); }
.jobs td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--surface-2); vertical-align: top; }
.jobs .filename { font-family: ui-monospace, monospace; font-size: 0.75rem; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jobs .filename .muted { color: var(--muted); margin-left: 0.3rem; }
.jobs .counts { font-size: 0.7rem; }
.jobs .counts .chip { display: inline-block; background: var(--surface); border: 1px solid var(--border); border-radius: 3px; padding: 0.05rem 0.35rem; margin: 0.05rem 0.15rem 0.05rem 0; font-family: ui-monospace, monospace; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.3rem; vertical-align: middle; }
.dot-running { background: #38bdf8; box-shadow: 0 0 8px #38bdf8; animation: pulse 1.6s ease-in-out infinite; }
.dot-done { background: #22c55e; }
.dot-failed { background: #ef4444; }
@keyframes pulse { 50% { opacity: 0.4; } }
tr.job-running { background: rgba(56, 189, 248, 0.04); }
tr.job-failed { background: rgba(239, 68, 68, 0.05); }
</style>
