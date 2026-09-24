<script setup lang="ts">
/**
 * SETTINGS-B2 — Data & imports. Logic moved from the old Settings.vue
 * "imports" and "tools" panes.
 *
 * - This page is the ONLY place that polls `/import/jobs`, and only while
 *   it is mounted AND the tab is visible (UX-W9: the old page mounted
 *   every pane and polled every 3 s even when deep-linked to Profile).
 *   It polls quickly while a job is running and slowly otherwise.
 * - Exports carry human names ("Heart rate samples"), not table names.
 *   A failed download now says so — it used to be an unhandled rejection.
 * - "Run analytics now" is "Recompute today's summary", which is what the
 *   endpoint actually does, behind a confirm.
 * - The sober CSV REPLACES existing sober history, so it asks first.
 */
import axios from "axios";
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { apiBase, queryToken } from "@/config";
import { fmtDateTime } from "@/format";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { errText } from "./integrations/health";

const base = () => (apiBase.value || "/api").replace(/\/$/, "");
const authHeaders = () => ({ Authorization: `Bearer ${queryToken.value}` });

function pickFile(accept: string, onPick: (f: File) => void) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = accept;
  inp.onchange = () => {
    const f = inp.files?.[0];
    if (f) onPick(f);
  };
  inp.click();
}

// ── Archive imports (Fitbit / Google Health, Garmin; summary + GPS) ──
type ImportKind = "fitbit" | "fitbit_tracks" | "garmin" | "garmin_tracks";
const importBusy = ref<ImportKind | "">("");
const importResult = ref("");
const importError = ref("");
const fitbitWeightUnit = ref<"kg" | "lb">("lb");

const KIND_PATH: Record<ImportKind, string> = {
  fitbit: "/import/fitbit",
  fitbit_tracks: "/import/fitbit/tracks",
  garmin: "/import/garmin",
  garmin_tracks: "/import/garmin/tracks",
};
const KIND_NAME: Record<ImportKind, string> = {
  fitbit: "Fitbit / Google Health",
  fitbit_tracks: "Fitbit GPS maps",
  garmin: "Garmin",
  garmin_tracks: "Garmin GPS tracks",
};

async function uploadImport(kind: ImportKind, file: File) {
  importBusy.value = kind;
  importResult.value = "";
  importError.value = "";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const params: Record<string, string> = {};
    if (kind === "fitbit") params.weight_unit = fitbitWeightUnit.value;
    const r = await axios.post(`${base()}${KIND_PATH[kind]}`, fd, {
      headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
      params,
      maxContentLength: 1024 * 1024 * 1024,
      maxBodyLength: 1024 * 1024 * 1024,
    });
    if (kind === "garmin_tracks" || kind === "fitbit_tracks") {
      importResult.value = `${KIND_NAME[kind]}: started in the background. Progress shows in Recent jobs below.`;
    } else {
      const counts: Record<string, number> = r.data?.imported ?? {};
      const parts = Object.entries(counts).map(([k, v]) => `${k}: ${v}`);
      importResult.value = parts.length
        ? `Imported from ${KIND_NAME[kind]} — ${parts.join(", ")}.`
        : "Upload accepted, but no recognised files were found in the ZIP.";
    }
    refreshJobs();
  } catch (e) {
    importError.value = `${KIND_NAME[kind]} import failed: ${errText(e)}`;
  } finally {
    importBusy.value = "";
  }
}

// ── Sober CSV — replaces history, so it confirms first ──
const confirmSober = ref(false);
const soberBusy = ref(false);
const soberResult = ref("");
const soberError = ref("");
function startSoberImport() {
  confirmSober.value = false;
  pickFile(".csv,text/csv", uploadSober);
}
async function uploadSober(file: File) {
  soberBusy.value = true;
  soberResult.value = "";
  soberError.value = "";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await axios.post(`${base()}/sober/import`, fd, {
      headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
    });
    soberResult.value = `Imported ${r.data.imported} streaks${
      r.data.started_active_from ? `, active streak from ${fmtDateTime(r.data.started_active_from)}` : ""
    }.`;
  } catch (e) {
    soberError.value = `Sober import failed: ${errText(e)}`;
  } finally {
    soberBusy.value = false;
  }
}

// ── Strength log CSV (IMPORT-1: Strong / Hevy / FitNotes) ──
const strengthBusy = ref(false);
const strengthResult = ref("");
const strengthError = ref("");
const strengthSource = ref("auto");
const strongUnit = ref("kg");   // Strong's weight column has no unit
async function uploadStrength(file: File) {
  strengthBusy.value = true;
  strengthResult.value = "";
  strengthError.value = "";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const params: Record<string, string> = { strong_unit: strongUnit.value };
    if (strengthSource.value !== "auto") params.source = strengthSource.value;
    const r = await axios.post(`${base()}/import/strength`, fd, {
      params,
      headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
    });
    const d = r.data;
    let msg = `Imported ${d.workouts} workout${d.workouts === 1 ? "" : "s"} · ${d.sets} sets from ${d.source}.`;
    if (d.skipped_duplicates) msg += ` ${d.skipped_duplicates} duplicate session(s) skipped.`;
    if (d.unmatched_exercises) msg += ` ${d.unmatched_exercises} exercise(s) weren't in the catalog (kept by name).`;
    strengthResult.value = msg;
    refreshJobs();
  } catch (e) {
    strengthError.value = `Strength import failed: ${errText(e)}`;
  } finally {
    strengthBusy.value = false;
  }
}

// ── Recent jobs — polled only while mounted and visible ──
type ImportJob = Awaited<ReturnType<typeof api.importJobs>>[number];
const jobs = ref<ImportJob[] | null>(null);
const jobsError = ref<string | null>(null);
let jobTimer: number | null = null;
let alive = true;

const JOB_KIND_NAME: Record<string, string> = {
  fitbit: "Fitbit / Google Health archive",
  garmin: "Garmin archive",
  garmin_fit_tracks: "Garmin GPS tracks",
  fitbit_gps_tracks: "Fitbit GPS maps",
  google_health: "Google Health backfill",
  strength_strong: "Strength log (Strong)",
  strength_hevy: "Strength log (Hevy)",
  strength_fitnotes: "Strength log (FitNotes)",
};
function jobName(kind: string): string {
  return JOB_KIND_NAME[kind] ?? kind.replace(/_/g, " ");
}
function jobAge(j: ImportJob): string {
  if (j.elapsed_s == null) return "—";
  const s = Math.round(j.elapsed_s);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

async function refreshJobs(): Promise<void> {
  try {
    jobs.value = await api.importJobs(20);
    jobsError.value = null;
  } catch (e) {
    jobsError.value = errText(e);
  }
}
function scheduleJobs() {
  if (jobTimer !== null) window.clearTimeout(jobTimer);
  jobTimer = null;
  if (!alive || document.visibilityState !== "visible") return;
  const running = (jobs.value ?? []).some((j) => j.status === "running");
  jobTimer = window.setTimeout(async () => {
    await refreshJobs();
    scheduleJobs();
  }, running ? 3000 : 20000);
}
function onVisibility() {
  if (document.visibilityState === "visible") refreshJobs().then(scheduleJobs);
  else if (jobTimer !== null) { window.clearTimeout(jobTimer); jobTimer = null; }
}

// ── Exports ──
const EXPORTS: { table: string; name: string }[] = [
  { table: "heartrate", name: "Heart rate samples" },
  { table: "hrv", name: "Heart rate variability (HRV)" },
  { table: "steps", name: "Steps" },
  { table: "sleep_stages", name: "Sleep stages" },
  { table: "workouts", name: "Workouts (Health Connect)" },
  { table: "activities", name: "Activities (rides, runs, rows)" },
  { table: "daily_summary", name: "Daily summaries" },
  { table: "body_metrics", name: "Weight and body composition" },
  { table: "blood_pressure", name: "Blood pressure" },
  { table: "skin_temp", name: "Skin temperature" },
  { table: "annotations", name: "Journal notes and annotations" },
];
// EXPORT-1: empty = the server default, the trailing 90 days.
const exportSince = ref("");
const exportUntil = ref("");
const exportBusy = ref("");
const exportError = ref("");

async function downloadExport(table: string, fmt: "csv" | "json") {
  exportBusy.value = `${table}.${fmt}`;
  exportError.value = "";
  try {
    const qs = new URLSearchParams();
    if (exportSince.value) qs.set("since", exportSince.value);
    if (exportUntil.value) qs.set("until", exportUntil.value);
    const q = qs.toString();
    // A plain <a> can't carry the bearer header, so fetch as a blob.
    const r = await axios.get(`${base()}/export/${table}.${fmt}${q ? `?${q}` : ""}`, {
      headers: authHeaders(),
      responseType: "blob",
    });
    const url = URL.createObjectURL(r.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `myvitals-${table}.${fmt}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    const name = EXPORTS.find((x) => x.table === table)?.name ?? table;
    exportError.value = `Couldn't download ${name}: ${errText(e)}`;
  } finally {
    exportBusy.value = "";
  }
}

// ── Recompute today's summary ──
const confirmRecompute = ref(false);
const recomputing = ref(false);
const recomputeResult = ref("");
const recomputeOk = ref(true);
async function recompute() {
  confirmRecompute.value = false;
  recomputing.value = true;
  recomputeResult.value = "";
  try {
    const r = await axios.post(`${base()}/analytics/run`, null, { headers: authHeaders() });
    recomputeResult.value = `Recomputed the summary for ${r.data.target_date}.`;
    recomputeOk.value = true;
  } catch (e) {
    recomputeResult.value = `Recompute failed: ${errText(e)}`;
    recomputeOk.value = false;
  } finally {
    recomputing.value = false;
  }
}

onMounted(async () => {
  document.addEventListener("visibilitychange", onVisibility);
  await refreshJobs();
  scheduleJobs();
});
onBeforeUnmount(() => {
  alive = false;
  document.removeEventListener("visibilitychange", onVisibility);
  if (jobTimer !== null) window.clearTimeout(jobTimer);
});
</script>

<template>
  <NeonPage title="Data & imports" back="/settings">
    <p class="sub">Bring history in, take your data out.</p>

    <NeonEyebrow>Import history</NeonEyebrow>
    <p class="hint">
      One-shot bulk loads from a downloaded archive — useful for back-filling years of data the watch doesn't have.
      Everything merges into the existing records; duplicates are skipped.
    </p>

    <section class="card">
      <h3>Fitbit / Google Health</h3>
      <p class="hint">
        The Fitbit app became <strong>Google Health</strong> on 2026-05-19. Request your archive from
        <a href="https://takeout.google.com/" target="_blank" rel="noreferrer">takeout.google.com</a> (pick
        “Fitbit”). Legacy fitbit.com exports still work. Upload the unmodified ZIP.
      </p>
      <fieldset class="inline radios">
        <legend>Weight unit in this archive</legend>
        <label><input v-model="fitbitWeightUnit" type="radio" value="kg" /> kg</label>
        <label><input v-model="fitbitWeightUnit" type="radio" value="lb" /> lb</label>
      </fieldset>
      <div class="actions">
        <button class="btn primary" type="button" :disabled="!!importBusy"
                @click="pickFile('.zip,application/zip', (f) => uploadImport('fitbit', f))">
          {{ importBusy === "fitbit" ? "Uploading…" : "Upload archive ZIP" }}
        </button>
        <button class="btn" type="button" :disabled="!!importBusy"
                @click="pickFile('.zip,application/zip', (f) => uploadImport('fitbit_tracks', f))">
          {{ importBusy === "fitbit_tracks" ? "Uploading…" : "Upload ZIP for GPS maps" }}
        </button>
      </div>
      <p class="hint">
        The GPS upload reads the archive's <code>gps_location</code> files and adds ride maps to your Fitbit
        activities. It runs in the background.
      </p>
    </section>

    <section class="card">
      <h3>Garmin Connect</h3>
      <p class="hint">
        Request your archive from
        <a href="https://www.garmin.com/account/datamanagement/exportdata" target="_blank" rel="noreferrer">garmin.com/account/datamanagement/exportdata</a>
        and upload the ZIP once it arrives by email.
      </p>
      <div class="actions">
        <button class="btn primary" type="button" :disabled="!!importBusy"
                @click="pickFile('.zip,application/zip', (f) => uploadImport('garmin', f))">
          {{ importBusy === "garmin" ? "Uploading…" : "Upload summary ZIP" }}
        </button>
        <button class="btn" type="button" :disabled="!!importBusy"
                @click="pickFile('.zip,application/zip', (f) => uploadImport('garmin_tracks', f))">
          {{ importBusy === "garmin_tracks" ? "Uploading…" : "Upload ZIP for GPS tracks" }}
        </button>
      </div>
      <p class="hint">
        The track upload reads FIT files (~22k for a long history) and attaches GPS routes to your activities. It
        runs in the background.
      </p>
    </section>
    <p v-if="importResult" class="msg ok" role="status">{{ importResult }}</p>
    <p v-if="importError" class="msg warn" role="alert">{{ importError }}</p>

    <section class="card">
      <h3>Sober time</h3>
      <p class="hint">
        Export from <em>I Am Sober</em>, <em>Sober Time</em> or similar — columns <code>start, end, days, notes</code>.
        <strong>Replaces your existing sober history.</strong> The file is read on your server only.
      </p>
      <div class="actions">
        <button class="btn" type="button" :disabled="soberBusy" @click="confirmSober = true">
          {{ soberBusy ? "Uploading…" : "Upload sober CSV" }}
        </button>
      </div>
      <p v-if="soberResult" class="msg ok" role="status">{{ soberResult }}</p>
      <p v-if="soberError" class="msg warn" role="alert">{{ soberError }}</p>
    </section>

    <section class="card">
      <h3>Strength log</h3>
      <p class="hint">
        Lifting history from <em>Strong</em>, <em>Hevy</em> or <em>FitNotes</em> (their CSV export). Sets, reps,
        weight, warm-ups and RPE come across; re-importing the same file skips duplicates. Exercises not in the
        catalog are kept by name.
      </p>
      <label class="field">
        <span>Format</span>
        <select v-model="strengthSource">
          <option value="auto">Detect automatically</option>
          <option value="strong">Strong</option>
          <option value="hevy">Hevy</option>
          <option value="fitnotes">FitNotes</option>
        </select>
      </label>
      <label v-if="strengthSource === 'strong' || strengthSource === 'auto'" class="field">
        <span>Strong weight unit</span>
        <select v-model="strongUnit">
          <option value="kg">kg</option>
          <option value="lb">lb</option>
        </select>
      </label>
      <div class="actions">
        <button class="btn" type="button" :disabled="strengthBusy"
                @click="pickFile('.csv,text/csv', uploadStrength)">
          {{ strengthBusy ? "Importing…" : "Upload strength CSV" }}
        </button>
      </div>
      <p class="hint">
        iPhone / Apple Health exports strength workouts without set data — export from Strong or Hevy instead.
      </p>
      <p v-if="strengthResult" class="msg ok" role="status">{{ strengthResult }}</p>
      <p v-if="strengthError" class="msg warn" role="alert">{{ strengthError }}</p>
    </section>

    <NeonEyebrow>Recent jobs</NeonEyebrow>
    <div v-if="jobs === null && !jobsError" class="skel" aria-busy="true">
      <div class="sk"></div><span class="sr-only">Loading recent jobs…</span>
    </div>
    <button v-else-if="jobsError && jobs === null" class="errbar" type="button" @click="refreshJobs().then(scheduleJobs)">
      <b>Couldn't load recent jobs</b><span>{{ jobsError }}</span><em>Tap to retry</em>
    </button>
    <template v-else-if="jobs">
      <p v-if="jobsError" class="msg warn">Couldn't refresh ({{ jobsError }}) — showing the last list.</p>
      <p v-if="jobs.length === 0" class="hint">No imports yet.</p>
      <section v-else class="card scroll-x">
        <table class="tbl">
          <thead><tr><th>Import</th><th>Status</th><th>Took</th><th>Rows</th><th>File</th></tr></thead>
          <tbody>
            <tr v-for="j in jobs" :key="j.id">
              <td>{{ jobName(j.kind) }}</td>
              <td>
                <span class="pill" :class="j.status === 'done' ? 'ok' : j.status === 'running' ? 'neutral' : 'warn'">
                  {{ j.status }}
                </span>
              </td>
              <td>{{ jobAge(j) }}</td>
              <td>
                {{ j.total_rows.toLocaleString() }}
                <span v-for="(n, k) in j.counts" :key="k" class="chip">{{ k }}: {{ Number(n).toLocaleString() }}</span>
              </td>
              <td class="file" :title="j.filename ?? ''">
                {{ j.filename ?? "—" }}
                <span v-if="j.size_bytes" class="mut">({{ (j.size_bytes / 1024 / 1024).toFixed(0) }} MB)</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-for="j in jobs.filter((x) => x.error)" :key="`e${j.id}`" class="msg warn">
          {{ jobName(j.kind) }}: {{ (j.error || "").split("\n").slice(-3).join(" / ") }}
        </p>
      </section>
    </template>

    <NeonEyebrow>Export</NeonEyebrow>
    <section class="card">
      <div class="inline">
        <label>From <input v-model="exportSince" type="date" aria-label="Export from date" /></label>
        <label>To <input v-model="exportUntil" type="date" aria-label="Export to date" /></label>
        <button v-if="exportSince || exportUntil" class="btn" type="button"
                @click="exportSince = ''; exportUntil = ''">Reset</button>
      </div>
      <p class="hint">{{ exportSince || exportUntil ? "Custom range." : "No range set — exports cover the last 90 days." }}</p>
      <ul class="exports">
        <li v-for="x in EXPORTS" :key="x.table">
          <span class="xname">{{ x.name }}</span>
          <button class="btn" type="button" :disabled="!!exportBusy" :aria-label="`Download ${x.name} as CSV`"
                  @click="downloadExport(x.table, 'csv')">{{ exportBusy === `${x.table}.csv` ? "…" : "CSV" }}</button>
          <button class="btn" type="button" :disabled="!!exportBusy" :aria-label="`Download ${x.name} as JSON`"
                  @click="downloadExport(x.table, 'json')">{{ exportBusy === `${x.table}.json` ? "…" : "JSON" }}</button>
        </li>
      </ul>
      <p v-if="exportError" class="msg warn" role="alert">{{ exportError }}</p>
    </section>

    <NeonEyebrow>Maintenance</NeonEyebrow>
    <section class="card">
      <p class="hint">
        Today's summary normally recomputes itself when new sleep or HRV data arrives. Use this if a number on the
        Today screen looks out of date.
      </p>
      <div class="actions">
        <button class="btn" type="button" :disabled="recomputing" @click="confirmRecompute = true">
          {{ recomputing ? "Recomputing…" : "Recompute today's summary" }}
        </button>
      </div>
      <p v-if="recomputeResult" class="msg" :class="recomputeOk ? 'ok' : 'warn'" role="status">{{ recomputeResult }}</p>
    </section>

    <ConfirmDialog :open="confirmSober" title="Replace your sober history?"
                   detail="Importing a sober CSV replaces every existing sober streak with the file's contents."
                   confirm-label="Choose file" @confirm="startSoberImport" @cancel="confirmSober = false" />
    <ConfirmDialog :open="confirmRecompute" title="Recompute today's summary?"
                   detail="Rebuilds today's summary row from the raw data. Nothing is deleted."
                   confirm-label="Recompute" :destructive="false" @confirm="recompute" @cancel="confirmRecompute = false" />
  </NeonPage>
</template>

<style scoped src="./settings-forms.css"></style>
<style scoped>
.sub { margin: -12px 0 14px; font-size: 13px; color: #9b9bb0; }
.radios { border: 0; padding: 0; margin: 6px 0; }
.radios legend { font-size: 13px; color: #9b9bb0; margin-bottom: 4px; }
.radios label { min-height: 44px; padding-right: 10px; }
.radios input { width: 18px; height: 18px; accent-color: #28e6ff; }
.chip { display: inline-block; margin: 2px 4px 0 0; font-size: 11px; color: #9b9bb0; background: #1e2230;
  border-radius: 999px; padding: 1px 7px; }
.file { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.exports { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.exports li { display: flex; align-items: center; gap: 8px; }
.xname { flex: 1; min-width: 0; font-size: 14px; }
.exports .btn { min-width: 64px; padding: 0 10px; }
</style>
