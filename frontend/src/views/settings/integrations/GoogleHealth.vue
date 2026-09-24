<script setup lang="ts">
/**
 * SETTINGS-B2 — Google Health (GH-1). Logic moved from the old
 * Settings.vue "google" pane: bring-your-own OAuth app, the loopback
 * consent + paste-back flow, the availability probe, ranged backfill as a
 * tracked job, and scheduled polling.
 *
 * The backfill job poll is cleared on unmount — it used to keep ticking
 * after you left the page. The poll toggle / interval revert with a
 * message when the save fails instead of showing an unsaved setting.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import type { IntegrationHealth } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import IntegrationHero from "./IntegrationHero.vue";
import { errText } from "./health";

defineProps<{
  health: IntegrationHealth | null | undefined;
  healthLoading: boolean;
  healthError: string | null;
}>();
const emit = defineEmits<{ (e: "refresh-health"): void }>();

const loading = ref(true);
const loadError = ref<string | null>(null);
const ghStatus = ref<Awaited<ReturnType<typeof api.googleHealthStatus>> | null>(null);
const ghCfg = ref<Awaited<ReturnType<typeof api.googleHealthConfig>> | null>(null);
const ghClientId = ref("");
const ghClientSecret = ref("");
const ghCallback = ref("");
const ghBusy = ref(false);
const ghError = ref("");
const ghResult = ref("");
const ghProbe = ref<Awaited<ReturnType<typeof api.googleHealthProbe>> | null>(null);

const pollEnabled = ref(false);
const pollInterval = ref(60);
const pollSaving = ref(false);
const pollError = ref("");

async function loadGoogleHealth(): Promise<void> {
  loadError.value = null;
  try {
    const [cfg, st] = await Promise.all([api.googleHealthConfig(), api.googleHealthStatus()]);
    ghCfg.value = cfg;
    ghStatus.value = st;
    pollEnabled.value = st.poll_enabled;
    pollInterval.value = st.poll_interval_min;
    if (cfg.client_id && !ghClientId.value) ghClientId.value = cfg.client_id;
    if (cfg.callback_url && !ghCallback.value) ghCallback.value = cfg.callback_url;
    if (!ghCallback.value) {
      // Loopback, deliberately — Google rejects LAN hostnames and localhost
      // is its only exception to the HTTPS rule. Nothing listens here; the
      // code lands in the address bar and is pasted back in step 2.
      ghCallback.value = "http://localhost:8080/api/auth/google-health/callback";
    }
  } catch (e) {
    loadError.value = errText(e);
  } finally {
    loading.value = false;
  }
}

function ghFail(e: unknown) { ghError.value = errText(e); }

async function ghSaveConfig() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  try {
    await api.googleHealthSetConfig({
      client_id: ghClientId.value.trim(),
      client_secret: ghClientSecret.value.trim(),
      callback_url: ghCallback.value.trim(),
    });
    ghClientSecret.value = "";   // never keep it in the DOM after saving
    ghResult.value = "Saved. Now open Google consent.";
    await loadGoogleHealth();
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

const ghPasteUrl = ref("");
const ghAuthUrl = ref("");

async function ghConnect() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  // Open the tab SYNCHRONOUSLY inside the click handler, then point it at
  // the URL — a window.open() after an await is silently popup-blocked.
  const tab = window.open("", "_blank");
  try {
    const { url } = await api.googleHealthAuthorizeUrl();
    ghAuthUrl.value = url;
    if (tab) tab.location.href = url;
  } catch (e) {
    tab?.close();
    ghFail(e);
  } finally { ghBusy.value = false; }
}

async function ghFinish() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  try {
    await api.googleHealthExchange(ghPasteUrl.value.trim());
    ghPasteUrl.value = "";
    ghAuthUrl.value = "";
    ghResult.value = "Connected. Now check what data is available.";
    await loadGoogleHealth();
    emit("refresh-health");
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

async function ghRunProbe() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = ""; ghProbe.value = null;
  try {
    ghProbe.value = await api.googleHealthProbe(7);
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

const ghBackfillOpen = ref(false);
const ghSince = ref("");
const ghUntil = ref("");
const ghJobId = ref<number | null>(null);
const ghJob = ref<{ status: string; counts: Record<string, number> | null; error: string | null } | null>(null);
let backfillTick: number | null = null;

function stopBackfillPoll() {
  if (backfillTick !== null) { window.clearInterval(backfillTick); backfillTick = null; }
  ghJobId.value = null;
}

async function startGhBackfill() {
  if (!ghSince.value || !ghUntil.value) return;
  try {
    const r = await api.googleHealthBackfill(ghSince.value, ghUntil.value);
    ghJobId.value = r.job_id;
    ghJob.value = { status: "running", counts: null, error: null };
    // Stops on ANY terminal status, so a partial run ends the poll rather
    // than spinning forever waiting for "done".
    backfillTick = window.setInterval(async () => {
      try {
        const j = await api.importJob(r.job_id);
        ghJob.value = j;
        if (["done", "partial", "failed"].includes(j.status)) {
          stopBackfillPoll();
          emit("refresh-health");
        }
      } catch {
        stopBackfillPoll();
      }
    }, 3000);
  } catch (e) {
    ghJob.value = { status: "failed", counts: null, error: errText(e) };
  }
}

async function ghSync(days: number) {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  try {
    const r = await api.googleHealthSync(days);
    const parts = Object.entries(r.written).filter(([, v]) => v > 0);
    ghResult.value = parts.length
      ? `Wrote ${parts.map(([k, v]) => `${v} ${k}`).join(", ")}.`
      : "Connected fine, but Google returned no readings for that window.";
    await loadGoogleHealth();
  } catch (e) { ghFail(e); } finally {
    ghBusy.value = false;
    emit("refresh-health");
  }
}

async function savePoll(enabled: boolean, minutes?: number) {
  const prevEnabled = ghStatus.value?.poll_enabled ?? false;
  const prevInterval = ghStatus.value?.poll_interval_min ?? 60;
  pollSaving.value = true;
  pollError.value = "";
  try {
    await api.googleHealthSetPoll(enabled, minutes);
    await loadGoogleHealth();
  } catch (e) {
    pollEnabled.value = prevEnabled;
    pollInterval.value = prevInterval;
    pollError.value = `Couldn't save — ${errText(e)}. The setting was not changed.`;
  } finally {
    pollSaving.value = false;
  }
}

const confirmDisconnect = ref(false);
async function ghDisconnect() {
  confirmDisconnect.value = false;
  try {
    await api.googleHealthDisconnect();
    ghProbe.value = null;
    await loadGoogleHealth();
    ghResult.value = "Disconnected. Data already imported stays.";
    emit("refresh-health");
  } catch (e) { ghFail(e); }
}

onMounted(loadGoogleHealth);
onBeforeUnmount(stopBackfillPoll);
</script>

<template>
  <IntegrationHero :health="health" :loading="healthLoading" :error="healthError" @retry="emit('refresh-health')">
    <template #actions>
      <button v-if="ghStatus?.connected" class="btn primary" type="button" :disabled="ghBusy" @click="ghSync(7)">
        {{ ghBusy ? "Working…" : "Sync now (last 7 days)" }}
      </button>
    </template>
  </IntegrationHero>

  <div v-if="loading" class="skel" aria-busy="true">
    <div class="sk tall"></div><span class="sr-only">Loading Google Health settings…</span>
  </div>
  <button v-else-if="loadError && !ghCfg" class="errbar" type="button" @click="loading = true; loadGoogleHealth()">
    <b>Couldn't load Google Health settings</b><span>{{ loadError }}</span><em>Tap to retry</em>
  </button>

  <template v-else>
    <p v-if="ghError" class="msg warn" role="alert">{{ ghError }}</p>
    <p v-if="ghResult" class="msg info" role="status">{{ ghResult }}</p>

    <template v-if="ghStatus?.connected">
      <NeonEyebrow>Syncing</NeonEyebrow>
      <section class="card">
        <ul class="kv">
          <li><span>Last sync</span><span>{{ ghStatus.last_sync_at ? fmtDateTime(ghStatus.last_sync_at) : "never" }}</span></li>
        </ul>
        <p v-if="ghStatus.last_error" class="msg warn">Last sync error: {{ ghStatus.last_error }}</p>
        <label class="check">
          <input v-model="pollEnabled" type="checkbox" :disabled="pollSaving"
                 @change="savePoll(pollEnabled)" />
          <span>Pull automatically</span>
        </label>
        <label v-if="pollEnabled" class="field">
          <span>Every</span>
          <select v-model.number="pollInterval" :disabled="pollSaving"
                  @change="savePoll(true, pollInterval)">
            <option :value="15">15 minutes</option>
            <option :value="30">30 minutes</option>
            <option :value="60">1 hour</option>
            <option :value="180">3 hours</option>
            <option :value="720">12 hours</option>
          </select>
        </label>
        <p v-if="pollError" class="msg warn" role="alert">{{ pollError }}</p>
        <p v-if="pollEnabled" class="hint">
          Overnight metrics only change once a night, so an hour is plenty for SpO2 and skin temperature — tighten it
          if you want steps to keep up. Google rate-limits, so 15 minutes is the floor.
        </p>
        <div class="actions">
          <button class="btn" type="button" :disabled="ghBusy" @click="ghRunProbe">
            {{ ghBusy ? "Working…" : "What data is available?" }}
          </button>
          <button class="btn" type="button" :aria-expanded="ghBackfillOpen" @click="ghBackfillOpen = !ghBackfillOpen">
            Backfill a date range…
          </button>
          <button class="btn danger" type="button" @click="confirmDisconnect = true">Disconnect</button>
        </div>

        <!-- GH-BACKFILL: an explicit range — "90 days" cannot express "the
             fortnight the phone was off". Runs as a tracked job. -->
        <div v-if="ghBackfillOpen" class="inline backfill">
          <label>From <input v-model="ghSince" type="date" aria-label="Backfill from" /></label>
          <label>To <input v-model="ghUntil" type="date" aria-label="Backfill to" /></label>
          <button class="btn primary" type="button" :disabled="!ghSince || !ghUntil || ghJobId !== null"
                  @click="startGhBackfill">Start</button>
        </div>
        <p v-if="ghJob" class="msg" :class="ghJob.status === 'failed' ? 'warn' : 'info'" role="status">
          Backfill {{ ghJob.status }}
          <template v-if="ghJob.counts?._windows_done"> · {{ ghJob.counts._windows_done }} window(s) done</template>
          <template v-if="ghJob.counts?._windows_failed"> · {{ ghJob.counts._windows_failed }} failed</template>
          <template v-if="ghJob.error"> — {{ ghJob.error }}</template>
        </p>

        <!-- The probe answers what the docs can't: whether YOUR account's
             watch data reaches this API, and for which types. -->
        <template v-if="ghProbe">
          <div class="scroll-x">
            <table class="tbl">
              <thead><tr><th>Data type</th><th>Last 7 days</th><th>Status</th></tr></thead>
              <tbody>
                <tr v-for="t in ghProbe.types" :key="t.type">
                  <td><code>{{ t.type }}</code><span v-if="t.ingested" class="tag">ingested</span></td>
                  <td>{{ t.ok ? (t.points ?? "—") : "—" }}</td>
                  <td>
                    <span v-if="!t.ok" class="msg warn">{{ t.error }}</span>
                    <span v-else-if="(t.points ?? 0) > 0" class="ok">available</span>
                    <span v-else class="mut">no data</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="hint">
            “no data” means Google served the type but your account has none in that window — for an overnight
            metric that usually just means the watch wasn't worn. An error is the interesting case: it normally
            means the scope wasn't granted.
          </p>
        </template>
      </section>
    </template>

    <NeonEyebrow>{{ ghStatus?.connected ? "App credentials" : "Set up" }}</NeonEyebrow>
    <section class="card">
      <details :open="!ghStatus?.connected">
        <summary>{{ ghStatus?.connected ? "OAuth app and reconnect" : "How this works" }}</summary>
        <p class="hint">
          A second route to your watch data that doesn't go through the phone. Two streams — SpO2 and skin
          temperature — have been dead on the phone path since a Pixel Watch firmware update; Google's API serves both.
        </p>
        <p class="hint">
          Bring your own OAuth app, the same as Strava: create a project at
          <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">console.cloud.google.com</a>,
          enable the Google Health API, create an OAuth client of type “Web application”, and add yourself as a
          test user. No verification is needed — that only applies above 100 users.
        </p>
        <p class="hint">
          <strong>Google will not accept a LAN address as the redirect URI.</strong> It requires a public domain over
          HTTPS, and <code>localhost</code> is its only exception — which is why the URI below is a loopback address
          nothing listens on. Google sends your browser there, the page fails to load, and the authorization code is
          sitting in the address bar for you to paste back in step 2.
        </p>
        <label class="field">
          <span>Redirect URI (paste this into the Google console, exactly)</span>
          <input v-model="ghCallback" type="url" />
        </label>
        <label class="field">
          <span>Client ID</span>
          <input v-model="ghClientId" type="text" placeholder="…apps.googleusercontent.com" />
        </label>
        <label class="field">
          <span>Client secret <em v-if="ghCfg?.client_secret_set">(saved — leave blank to keep)</em></span>
          <input v-model="ghClientSecret" type="password" autocomplete="off" placeholder="GOCSPX-…" />
        </label>
        <div class="actions">
          <button class="btn" type="button" :disabled="ghBusy" @click="ghSaveConfig">Save app credentials</button>
          <button class="btn primary" type="button" :disabled="ghBusy || !ghCfg?.configured" @click="ghConnect"
                  :title="ghCfg?.configured ? '' : 'Save a client ID and secret first'">
            {{ ghStatus?.connected ? "Reconnect" : "1. Open Google consent" }}
          </button>
        </div>
        <p v-if="ghCfg && !ghCfg.configured" class="hint">
          <strong>Consent is disabled until a client secret is stored.</strong>
          <span v-if="ghCfg.client_id">
            The client ID is saved but the secret is not — paste it above and press Save. Leaving the secret blank on
            a later save keeps the stored one rather than clearing it.
          </span>
        </p>
      </details>

      <!-- Step 2 of the loopback flow, only once consent has been opened. -->
      <div v-if="ghAuthUrl" class="paste">
        <p class="hint">
          A tab just opened for Google's consent screen. Approve it, and the browser lands on a
          <code>localhost</code> page that <strong>fails to load — that is expected</strong>. Copy the whole address
          from that tab's URL bar and paste it here.
        </p>
        <label class="field">
          <span>Address from the failed page</span>
          <input v-model="ghPasteUrl" type="text"
                 placeholder="http://localhost:8080/api/auth/google-health/callback?state=…&amp;code=…" />
        </label>
        <div class="actions">
          <button class="btn primary" type="button" :disabled="ghBusy || !ghPasteUrl.trim()" @click="ghFinish">
            2. Finish connecting
          </button>
          <a :href="ghAuthUrl" target="_blank" rel="noopener" class="btn">Open the consent screen</a>
        </div>
        <p class="hint">The link expires after 15 minutes. If it does, open Google consent again for a fresh one.</p>
      </div>
    </section>
  </template>

  <ConfirmDialog :open="confirmDisconnect" title="Disconnect Google Health?"
                 detail="Data already imported stays. The stored grant is removed, so polling stops until you reconnect."
                 confirm-label="Disconnect" @confirm="ghDisconnect" @cancel="confirmDisconnect = false" />
</template>

<style scoped src="../settings-forms.css"></style>
<style scoped>
.backfill { margin-top: 10px; }
.paste { margin-top: 12px; border-top: 1px solid var(--rn-line, #23263a); padding-top: 8px; }
.tag { margin-left: 6px; font-size: 10px; color: #5dff3b; border: 1px solid currentColor; border-radius: 999px; padding: 0 6px; }
.ok { color: var(--rn-lime, #5dff3b); }
</style>
