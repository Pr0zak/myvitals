<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Eye, EyeOff, Check, X as XIcon } from "lucide-vue-next";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import { units, weightUnit, weightVal, weightToKg } from "@/units";
import { themeChoice } from "@/theme";
import { fmtDateTime, timeFormat } from "@/format";
import type { StravaAppConfigStatus, StravaStatus } from "@/api/types";

const tokenInput = ref(queryToken.value);
const tokenVisible = ref(false);
const apiBaseInput = ref(apiBase.value);
const status = ref<"idle" | "ok" | "fail">("idle");
const errorMsg = ref<string>("");

const trailCfg = ref<{ dnis: string | null; configured: boolean; updated_at: string | null } | null>(null);
const trailCfgError = ref<string | null>(null);
const trailCfgSaving = ref(false);
const trailTesting = ref(false);
const trailDnisInput = ref("");
const trailCfgResult = ref("");

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

// ── AI summaries ──────────────────────────────────────────
const aiCfg = ref<Awaited<ReturnType<typeof api.aiConfig>> | null>(null);
const aiKeyInput = ref("");
const aiKeyVisible = ref(false);
const aiPreviewing = ref(false);
const aiPreviewJson = ref<string>("");
const aiResult = ref<string>("");

async function loadAiCfg() {
  if (!queryToken.value) return;
  try { aiCfg.value = await api.aiConfig(); } catch { /* ignore */ }
}
async function aiSaveKey() {
  if (!aiKeyInput.value.trim()) return;
  aiResult.value = "";
  try {
    await api.aiUpdateConfig({ anthropic_api_key: aiKeyInput.value.trim() });
    aiKeyInput.value = "";
    await loadAiCfg();
    aiResult.value = "API key saved.";
  } catch (e) { aiResult.value = `Save failed: ${e instanceof Error ? e.message : String(e)}`; }
}
async function aiClearKey() {
  if (!confirm("Clear stored Anthropic API key?")) return;
  try { await api.aiUpdateConfig({ clear_key: true }); await loadAiCfg(); aiResult.value = "Key cleared."; }
  catch (e) { aiResult.value = `Failed: ${e instanceof Error ? e.message : String(e)}`; }
}
async function aiToggleEnabled(v: boolean) {
  try { await api.aiUpdateConfig({ enabled: v }); await loadAiCfg(); }
  catch { /* swallow */ }
}
async function aiToggleWeekly(v: boolean) {
  try { await api.aiUpdateConfig({ weekly_digest_enabled: v }); await loadAiCfg(); }
  catch { /* swallow */ }
}
async function aiUpdateLimit(n: number) {
  if (!Number.isFinite(n) || n < 1) return;
  try { await api.aiUpdateConfig({ daily_call_limit: Math.floor(n) }); await loadAiCfg(); }
  catch { /* swallow */ }
}
async function aiUpdateModel(model: string) {
  if (!model) return;
  try { await api.aiUpdateConfig({ model }); await loadAiCfg(); }
  catch { /* swallow */ }
}
async function aiUpdateTone(tone: string) {
  if (tone !== "supportive" && tone !== "blunt" && tone !== "data-only") return;
  try { await api.aiUpdateConfig({ tone }); await loadAiCfg(); }
  catch { /* swallow */ }
}

// Available Claude models with their cost / capability profile so the
// picker can show "Haiku (cheapest, fast)" rather than just an ID.
const AI_MODELS = [
  {
    id: "claude-haiku-4-5-20251001",
    label: "Haiku 4.5",
    sub: "cheapest, fastest — recommended for structured summaries",
  },
  {
    id: "claude-sonnet-4-6",
    label: "Sonnet 4.6",
    sub: "stronger reasoning, ~4× the cost of Haiku",
  },
  {
    id: "claude-opus-4-7",
    label: "Opus 4.7",
    sub: "deepest analysis, ~5× Sonnet — overkill for daily reads",
  },
];
async function aiPreview() {
  aiPreviewing.value = true; aiPreviewJson.value = "";
  try {
    const p = await api.aiPreviewPayload("week");
    aiPreviewJson.value = JSON.stringify(p, null, 2);
  } catch (e) { aiResult.value = `Preview failed: ${e instanceof Error ? e.message : String(e)}`; }
  finally { aiPreviewing.value = false; }
}

// Sober-time CSV import (separate from the main importer flow above)
const soberImportBusy = ref(false);
const soberImportResult = ref<string>("");
const soberImportError = ref<string>("");
async function uploadSober(file: File) {
  soberImportBusy.value = true;
  soberImportResult.value = "";
  soberImportError.value = "";
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const fd = new FormData();
    fd.append("file", file);
    const r = await axios.post(`${base}/sober/import`, fd, {
      headers: {
        Authorization: `Bearer ${queryToken.value}`,
        "Content-Type": "multipart/form-data",
      },
    });
    soberImportResult.value = `Imported ${r.data.imported} streaks${
      r.data.started_active_from
        ? `, active streak from ${fmtDateTime(r.data.started_active_from)}`
        : ""
    }.`;
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { status?: number; data?: unknown } }).response;
      soberImportError.value = `HTTP ${r?.status ?? "?"} — ${JSON.stringify(r?.data ?? "")}`;
    } else {
      soberImportError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    soberImportBusy.value = false;
  }
}
function pickSoberFile() {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = ".csv,text/csv";
  inp.onchange = () => {
    const f = inp.files?.[0];
    if (f) uploadSober(f);
  };
  inp.click();
}

// Profile
type Profile = Awaited<ReturnType<typeof api.getProfile>>;
const profile = ref<Profile | null>(null);
const profileSaving = ref(false);
const profileMsg = ref<string>("");

// Weight goal display: stored in kg, shown in user units. Use a computed
// setter so `v-model` works smoothly (typing fires every keystroke; the
// `:value`/`@change` pattern only fires on blur and feels broken).
const weightGoalDisplay = computed({
  get(): string {
    if (!profile.value || profile.value.weight_goal_kg == null) return "";
    const v = weightVal(profile.value.weight_goal_kg);
    return v != null ? String(v.toFixed(1)) : "";
  },
  set(v: string) {
    if (!profile.value) return;
    if (v === "" || v == null) {
      profile.value.weight_goal_kg = null;
      return;
    }
    const num = parseFloat(v);
    profile.value.weight_goal_kg = Number.isFinite(num) ? weightToKg(num) : null;
  },
});

// Goals live in profile.extra so we don't need a schema migration; the
// phone reads them via /profile.extra.{steps_goal,sleep_goal_h}.
const stepsGoalInput = ref<number | null>(null);
const sleepGoalInput = ref<number | null>(null);

async function loadProfile() {
  if (!queryToken.value) return;
  try {
    profile.value = await api.getProfile();
    const extra = (profile.value?.extra ?? {}) as Record<string, unknown>;
    stepsGoalInput.value = (extra.steps_goal as number | undefined) ?? null;
    sleepGoalInput.value = (extra.sleep_goal_h as number | undefined) ?? null;
  } catch { /* ignore */ }
}
async function saveProfile() {
  if (!profile.value) return;
  profileSaving.value = true;
  profileMsg.value = "";
  try {
    const extra: Record<string, unknown> = {
      ...(profile.value.extra as Record<string, unknown> | null ?? {}),
    };
    if (stepsGoalInput.value && stepsGoalInput.value > 0) {
      extra.steps_goal = Number(stepsGoalInput.value);
    } else { delete extra.steps_goal; }
    if (sleepGoalInput.value && sleepGoalInput.value > 0) {
      extra.sleep_goal_h = Number(sleepGoalInput.value);
    } else { delete extra.sleep_goal_h; }

    profile.value = await api.putProfile({
      birth_date: profile.value.birth_date,
      sex: profile.value.sex,
      height_cm: profile.value.height_cm,
      weight_goal_kg: profile.value.weight_goal_kg,
      resting_hr_baseline: profile.value.resting_hr_baseline,
      activity_level: profile.value.activity_level,
      extra: Object.keys(extra).length ? extra : null,
    }) as Profile;
    profileMsg.value = "Saved.";
  } catch (e) {
    profileMsg.value = "Save failed: " + (e instanceof Error ? e.message : String(e));
  } finally { profileSaving.value = false; }
}

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
    await Promise.all([loadStrava(), loadTrailCfg()]);
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

async function loadTrailCfg() {
  if (!queryToken.value) return;
  trailCfgError.value = null;
  try {
    trailCfg.value = await api.trailStatusConfig();
    trailDnisInput.value = trailCfg.value.dnis ?? "";
  } catch (e: unknown) {
    trailCfgError.value = e instanceof Error ? e.message : String(e);
  }
}

async function saveTrailDnis() {
  trailCfgSaving.value = true; trailCfgResult.value = "";
  try {
    const r = await api.saveTrailStatusConfig(trailDnisInput.value.trim() || null);
    trailCfg.value = { ...r, updated_at: new Date().toISOString() };
    trailDnisInput.value = r.dnis ?? "";
    trailCfgResult.value = r.configured ? "Saved." : "Cleared.";
  } catch (e: unknown) {
    trailCfgResult.value = e instanceof Error ? e.message : String(e);
  } finally { trailCfgSaving.value = false; }
}

async function clearTrailDnis() {
  trailDnisInput.value = "";
  await saveTrailDnis();
}

async function testTrailPoll() {
  trailTesting.value = true; trailCfgResult.value = "";
  try {
    const r = await api.refreshTrails();
    trailCfgResult.value = r.skipped
      ? "Skipped (no DNIS configured)"
      : `Polled: ${r.fetched} readings, ${r.snapshots} snapshots, ${r.alerts} alerts.`;
  } catch (e: unknown) {
    trailCfgResult.value = e instanceof Error ? e.message : String(e);
  } finally { trailTesting.value = false; }
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
  return fmtDateTime(ts);
}

onMounted(() => {
  loadStrava();
  loadProfile();
  loadAiCfg();
  startJobPolling();
});
onUnmounted(stopJobPolling);
</script>

<template>
  <div class="settings">
    <h1>Settings</h1>

    <details class="section" open>
      <summary><h2>Backend access</h2></summary>
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
            <component :is="tokenVisible ? EyeOff : Eye" :size="16"/>
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

      <div v-if="status === 'ok'" class="ok"><Check :size="14"/> Reached the backend with this token.</div>
      <div v-if="status === 'fail'" class="err">
        <XIcon :size="14"/> Could not authenticate.<br/>
        <small>{{ errorMsg }}</small>
      </div>
    </details>

    <details class="section" open>
      <summary><h2>Display</h2></summary>
      <div class="display-grid">
        <div class="lbl">Theme</div>
        <div class="choices">
          <label class="pick"><input type="radio" value="dark" v-model="themeChoice"/> Dark</label>
          <label class="pick"><input type="radio" value="light" v-model="themeChoice"/> Light</label>
          <label class="pick"><input type="radio" value="auto" v-model="themeChoice"/> Auto</label>
        </div>

        <div class="lbl">Units</div>
        <div class="choices">
          <label class="pick"><input type="radio" value="metric" v-model="units"/> Metric (km, kg, °C)</label>
          <label class="pick"><input type="radio" value="imperial" v-model="units"/> Imperial (mi, lb, °F)</label>
        </div>

        <div class="lbl">Time format</div>
        <div class="choices">
          <label class="pick"><input type="radio" value="auto" v-model="timeFormat"/> Auto</label>
          <label class="pick"><input type="radio" value="12h" v-model="timeFormat"/> 12-hour <span class="muted">(7:35 PM)</span></label>
          <label class="pick"><input type="radio" value="24h" v-model="timeFormat"/> 24-hour <span class="muted">(19:35)</span></label>
        </div>
      </div>
    </details>

    <details class="section" v-if="queryToken && profile" open>
      <summary><h2>Profile</h2></summary>
      <p class="hint">
        Powers age-adjusted max HR, HR zones, BMI, and (eventually) cohort
        percentile lookups. Single-user app, all stays on your server.
      </p>
      <div class="profile-grid">
        <label>
          <span>Birth date</span>
          <input type="date" v-model="profile.birth_date"/>
        </label>
        <label>
          <span>Sex</span>
          <select v-model="profile.sex">
            <option :value="null">—</option>
            <option value="male">male</option>
            <option value="female">female</option>
            <option value="other">other</option>
          </select>
        </label>
        <label>
          <span>Height (cm)</span>
          <input type="number" v-model.number="profile.height_cm" min="50" max="250" step="0.1"/>
        </label>
        <label>
          <span>Weight goal ({{ weightUnit }})</span>
          <input type="number" v-model="weightGoalDisplay"
                 min="20" max="660" step="0.1" :placeholder="weightUnit"/>
        </label>
        <label>
          <span>Resting HR baseline (bpm)
            <em class="opt" v-if="profile.derived?.resting_hr_baseline_auto">
              (auto: {{ profile.derived.resting_hr_baseline_auto.toFixed(0) }} bpm from last 30d)
            </em>
          </span>
          <input type="number" v-model.number="profile.resting_hr_baseline"
                 :placeholder="profile.derived?.resting_hr_baseline_auto?.toFixed(0) ?? 'auto-derived if blank'"
                 min="30" max="120"/>
        </label>
        <label>
          <span>Activity level</span>
          <select v-model="profile.activity_level">
            <option :value="null">—</option>
            <option value="sedentary">sedentary</option>
            <option value="light">light (1-3×/wk)</option>
            <option value="moderate">moderate (3-5×/wk)</option>
            <option value="active">active (6-7×/wk)</option>
            <option value="athlete">athlete (2×/day)</option>
          </select>
        </label>
        <label>
          <span>Daily steps goal</span>
          <input type="number" min="1000" step="500" v-model.number="stepsGoalInput"
                 placeholder="10000"/>
        </label>
        <label>
          <span>Sleep goal (hours)</span>
          <input type="number" min="4" max="12" step="0.25" v-model.number="sleepGoalInput"
                 placeholder="8"/>
        </label>
      </div>

      <div v-if="profile.derived?.max_hr_estimated" class="derived">
        <strong>Derived:</strong>
        <span class="muted">age {{ profile.derived.age }}</span>
        <span class="muted">· est. max HR {{ profile.derived.max_hr_estimated }} bpm (Tanaka)</span>
        <span v-if="profile.derived.bmi_at_goal" class="muted">· BMI at goal {{ profile.derived.bmi_at_goal }}</span>
      </div>
      <div v-if="profile.derived?.hr_zones" class="zones">
        <span v-for="z in profile.derived.hr_zones" :key="z.zone"
              class="zone" :class="`zone-${z.zone}`">
          Z{{ z.zone }} {{ z.label }} <strong>{{ z.low }}–{{ z.high }}</strong>
        </span>
      </div>

      <div class="actions">
        <button class="primary" :disabled="profileSaving" @click="saveProfile">
          {{ profileSaving ? 'Saving…' : 'Save profile' }}
        </button>
        <span v-if="profileMsg" class="hint">{{ profileMsg }}</span>
      </div>
    </details>

    <details class="section" v-if="queryToken">
      <summary><h2>AI summaries</h2></summary>
      <p class="hint">
        Claude turns your weekly / monthly stats into a plain-English read.
        <strong>Aggregate only</strong> — no raw HR samples, GPS, or sober history dates leave your server.
        Tap <em>Preview payload</em> to see exactly what gets sent.
      </p>
      <label>
        <span>Anthropic API key
          <em class="opt">{{ aiCfg?.api_key_set ? `currently ${aiCfg.api_key_masked}` : "not configured" }}</em>
        </span>
        <div class="token-row">
          <input v-model="aiKeyInput" :type="aiKeyVisible ? 'text' : 'password'"
                 placeholder="sk-ant-…  (paste a new key to update)" autocomplete="off"/>
          <button type="button" class="eye" @click="aiKeyVisible = !aiKeyVisible">
            <component :is="aiKeyVisible ? EyeOff : Eye" :size="16"/>
          </button>
        </div>
      </label>
      <div class="ai-toggles">
        <label class="ai-toggle">
          <input type="checkbox" :checked="!!aiCfg?.enabled" @change="aiToggleEnabled(($event.target as HTMLInputElement).checked)"/>
          <span>Enable AI summaries</span>
        </label>
        <label class="ai-toggle">
          <input type="checkbox" :checked="!!aiCfg?.weekly_digest_enabled"
                 @change="aiToggleWeekly(($event.target as HTMLInputElement).checked)"/>
          <span>Weekly digest (Sunday 22:00)</span>
        </label>
        <label class="ai-toggle">
          <span>Model:</span>
          <select :value="aiCfg?.model ?? 'claude-haiku-4-5-20251001'"
                  @change="aiUpdateModel(($event.target as HTMLSelectElement).value)"
                  style="min-width: 180px;">
            <option v-for="m in AI_MODELS" :key="m.id" :value="m.id">{{ m.label }}</option>
          </select>
          <span class="muted" style="font-size: 0.75rem;">
            {{ AI_MODELS.find((m) => m.id === aiCfg?.model)?.sub ?? '' }}
          </span>
        </label>
        <label class="ai-toggle">
          <span>Tone:</span>
          <select :value="aiCfg?.tone ?? 'supportive'"
                  @change="aiUpdateTone(($event.target as HTMLSelectElement).value)">
            <option value="supportive">Supportive</option>
            <option value="blunt">Blunt</option>
            <option value="data-only">Data-only</option>
          </select>
        </label>
        <label class="ai-toggle">
          <span>Daily call limit:</span>
          <input type="number" min="1" max="200"
                 :value="aiCfg?.daily_call_limit ?? 10"
                 @change="aiUpdateLimit(($event.target as HTMLInputElement).valueAsNumber)"
                 style="width: 80px;"/>
          <span class="muted" v-if="aiCfg">used {{ aiCfg.calls_today }}/{{ aiCfg.daily_call_limit }} today</span>
        </label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="!aiKeyInput.trim()" @click="aiSaveKey">Save API key</button>
        <button class="ghost danger" v-if="aiCfg?.api_key_set" @click="aiClearKey">Clear key</button>
        <button class="ghost" @click="aiPreview">{{ aiPreviewing ? 'Loading…' : 'Preview payload' }}</button>
      </div>
      <pre v-if="aiPreviewJson" class="ai-preview">{{ aiPreviewJson }}</pre>
      <p v-if="aiResult" class="ok">{{ aiResult }}</p>
    </details>

    <details class="section" v-if="queryToken">
      <summary><h2>Tools &amp; exports</h2></summary>
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
    </details>

    <details class="section" v-if="queryToken">
      <summary><h2>Historical imports</h2></summary>
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
        <div class="import-card">
          <strong>Sober time</strong>
          <p class="muted">
            Export from <em>I Am Sober</em> / <em>Sober Time</em> / similar — should have
            columns <code>start, end, days, notes</code>. Replaces existing sober history.
          </p>
          <button class="ghost" :disabled="soberImportBusy" @click="pickSoberFile">
            {{ soberImportBusy ? 'Uploading…' : 'Upload sober CSV' }}
          </button>
          <p v-if="soberImportResult" class="ok" style="margin-top: 0.4rem;">{{ soberImportResult }}</p>
          <p v-if="soberImportError" class="err" style="margin-top: 0.4rem;"><small>{{ soberImportError }}</small></p>
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
    </details>

    <details class="section" v-if="queryToken">
      <summary><h2>Trail status (RainoutLine)</h2></summary>
      <div v-if="trailCfgError" class="err">{{ trailCfgError }}</div>
      <p class="hint">
        myvitals polls
        <a href="https://rainoutline.com/" target="_blank" rel="noreferrer">rainoutline.com</a>
        every 15 minutes for trail-open / trail-closed status. Each
        organisation that uses RainoutLine has a 10-digit DNIS (the
        number callers dial to hear the recording). Paste yours below
        and the trail board on the Trails page populates itself.
      </p>
      <div class="form">
        <label>
          <span>DNIS <em class="opt">(10 digits)</em></span>
          <input
            v-model="trailDnisInput" placeholder="e.g. 9132040204"
            inputmode="numeric" autocomplete="off"
            :disabled="trailCfgSaving"
          />
        </label>
        <div class="actions">
          <button class="primary" :disabled="trailCfgSaving" @click="saveTrailDnis">
            {{ trailCfgSaving ? "Saving…" : (trailCfg?.configured ? "Update" : "Save") }}
          </button>
          <button v-if="trailCfg?.configured" class="ghost" :disabled="trailCfgSaving" @click="testTrailPoll">
            {{ trailTesting ? "Polling…" : "Test poll now" }}
          </button>
          <button v-if="trailCfg?.configured" class="ghost danger" :disabled="trailCfgSaving" @click="clearTrailDnis">
            Clear
          </button>
        </div>
        <div v-if="trailCfgResult" class="hint">{{ trailCfgResult }}</div>
      </div>
    </details>

    <details class="section">
      <summary><h2>Strava</h2></summary>
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
              <Check :size="14"/> Connected as <strong>{{ strava.athlete_name ?? strava.athlete_id }}</strong>
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
    </details>
  </div>
</template>

<style scoped>
.settings { max-width: 640px; }
h1 { margin: 0 0 0.4rem; }
h2 { font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin: 1.5rem 0 0.5rem; }
section, details.section { margin-bottom: 1rem; }
details.section { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem 1rem; }
details.section[open] { padding-bottom: 1.2rem; }
details.section > summary { cursor: pointer; list-style: none; user-select: none; padding: 0.4rem 0; }
details.section > summary::-webkit-details-marker { display: none; }
details.section > summary::before { content: "▸"; color: var(--muted); margin-right: 0.5rem; transition: transform 0.15s; display: inline-block; }
details.section[open] > summary::before { transform: rotate(90deg); }
details.section > summary > h2 { display: inline; margin: 0; }
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

.profile-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.6rem; }
.profile-grid label { margin-bottom: 0; }
.profile-grid select, .profile-grid input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 0.45rem; font-size: 0.9rem; font-family: inherit; }
.derived { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: baseline; margin: 0.6rem 0; font-size: 0.85rem; }
.derived .muted { color: var(--muted); }
.zones { display: flex; gap: 0.3rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
.zone { padding: 0.25rem 0.55rem; border-radius: 4px; font-size: 0.75rem; font-family: ui-monospace, monospace; }
.zone-1 { background: rgba(56, 189, 248, 0.18); color: #38bdf8; }
.zone-2 { background: rgba(34, 197, 94, 0.18); color: #22c55e; }
.zone-3 { background: rgba(234, 179, 8, 0.18); color: #eab308; }
.zone-4 { background: rgba(249, 115, 22, 0.18); color: #f97316; }
.zone-5 { background: rgba(239, 68, 68, 0.20); color: #ef4444; }

.display-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 0.6rem 1rem;
  align-items: center;
  margin-top: 0.4rem;
}
.display-grid .lbl {
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
  text-align: right;
  align-self: center;
}
/* Segmented control — pills look + behave like a single button group.
   Native radio is hidden via opacity:0 + absolute, the whole label is
   the click target. Active state is filled accent. */
.display-grid .choices {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 3px;
}
.display-grid .pick {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem 0.85rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  border-radius: 6px;
  margin: 0;
  white-space: nowrap;
  transition: background-color 0.12s, color 0.12s;
  user-select: none;
  flex-direction: row;
}
.display-grid .pick input[type="radio"] {
  position: absolute;
  opacity: 0;
  pointer-events: none;
  width: 0;
  height: 0;
}
.display-grid .pick:hover { color: var(--text); }
.display-grid .pick:has(input:checked) {
  background: var(--accent);
  color: var(--accent-text);
  font-weight: 600;
}
.display-grid .pick .muted {
  color: inherit; opacity: 0.7;
  margin-left: 0.35rem; font-size: 0.78rem; font-weight: 400;
}
@media (max-width: 520px) {
  .display-grid { grid-template-columns: 1fr; }
  .display-grid .lbl { text-align: left; }
  .display-grid .choices { width: 100%; }
  .display-grid .pick { flex: 1; }
}

.ai-toggles { display: flex; flex-direction: column; gap: 0.5rem; margin: 0.6rem 0 0.4rem; }
.ai-toggle { flex-direction: row; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
.ai-toggle input[type="checkbox"] { margin: 0; }
.ai-preview {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.7rem; max-height: 280px; overflow: auto;
  font-family: ui-monospace, monospace; font-size: 0.75rem;
  color: var(--text-soft); margin-top: 0.5rem; white-space: pre-wrap;
}
</style>
