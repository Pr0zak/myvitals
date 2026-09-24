<script setup lang="ts">
/**
 * SETTINGS-B2 — Strava. Logic moved from the old Settings.vue "strava"
 * pane: cookie-session ingest (SCS family, the primary path since Strava
 * paywalled its free OAuth API on 2026-06-30), the scheduled poll
 * (STRAVA-1), bulk history import, and the legacy OAuth path kept for
 * paid-sub users. The legacy block is fetched only when it is opened.
 *
 * Autosaved controls (the poll toggle and interval) are bound to local
 * state and REVERTED with a visible message when the save fails — they
 * used to swallow the error and leave the control showing a setting the
 * server never accepted.
 */
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import { apiBase } from "@/config";
import { fmtDateTime } from "@/format";
import type { IntegrationHealth, StravaAppConfigStatus, StravaStatus } from "@/api/types";
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

interface StravaCookieStatus {
  configured: boolean;
  athlete_id: number | null;
  athlete_name: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  needs_reconnect: boolean;
  auto_login_available: boolean;
  auto_login_enabled: boolean;
  email: string | null;
  last_auto_login_at: string | null;
  poll_enabled: boolean;
  poll_interval_min: number;
  poll_consecutive_failures: number;
  poll_stopped: boolean;
}

const loading = ref(true);
const loadError = ref<string | null>(null);
const cookieStatus = ref<StravaCookieStatus | null>(null);
const cookieRememberInput = ref("");
const cookieSidInput = ref("");
const cookieBlobInput = ref("");
const cookieEmailInput = ref("");
const cookiePasswordInput = ref("");
const cookieAutoLoginEnabled = ref(true);
const cookieEditing = ref(false);
const cookieSaving = ref(false);
const cookieSyncing = ref(false);
const cookieRefreshing = ref(false);
const cookieResult = ref("");
const cookieResultOk = ref(true);
const cookieBulkDays = ref(30);
const cookieBulkLimit = ref<number | null>(null);
const cookieHowtoOpen = ref(false);

// Autosaved poll controls — local state so a failed save can be undone.
const pollEnabled = ref(false);
const pollInterval = ref(360);
const pollSaving = ref(false);
const pollError = ref("");

function applyStatus(s: StravaCookieStatus) {
  cookieStatus.value = s;
  pollEnabled.value = s.poll_enabled;
  pollInterval.value = s.poll_interval_min;
}

function say(msg: string, ok: boolean) { cookieResult.value = msg; cookieResultOk.value = ok; }

async function loadCookieStatus(): Promise<void> {
  loadError.value = null;
  try {
    applyStatus(await api.stravaCookieStatus());
    if (cookieStatus.value?.needs_reconnect) {
      if (cookieStatus.value.email && !cookieEmailInput.value) cookieEmailInput.value = cookieStatus.value.email;
      // The cookie-paste section is the reconnect path for Google / email-code
      // accounts that have no Strava password.
      cookieHowtoOpen.value = true;
    }
  } catch (e) {
    loadError.value = errText(e);
  } finally {
    loading.value = false;
  }
}

async function saveCookie() {
  const haveRemember = !!cookieRememberInput.value.trim();
  const haveSid = !!cookieSidInput.value.trim();
  const haveBlob = !!cookieBlobInput.value.trim();
  const haveCookie = haveRemember || haveSid || haveBlob;
  const haveCreds = !!cookieEmailInput.value.trim() && !!cookiePasswordInput.value;
  if (!haveCookie && !haveCreds) {
    say("Paste your Strava cookies (or a cookie/email+password).", false);
    return;
  }
  cookieSaving.value = true;
  cookieResult.value = "";
  try {
    const body: Parameters<typeof api.stravaCookieSet>[0] = { auto_login_enabled: cookieAutoLoginEnabled.value };
    if (haveRemember) body.remember_token = cookieRememberInput.value.trim();
    if (haveSid) body.sid_cookie = cookieSidInput.value.trim();
    if (haveBlob) body.cookie_blob = cookieBlobInput.value.trim();
    if (haveCreds) {
      body.email = cookieEmailInput.value.trim();
      body.password = cookiePasswordInput.value;
    }
    const r = await api.stravaCookieSet(body);
    applyStatus(r);
    // SCS-8 sid-only saves may not resolve the athlete — don't say "null".
    const who = r.athlete_name ?? r.athlete_id ?? "Strava";
    say(haveCreds ? `Auto-login OK — connected as ${who}.` : `Cookie saved — connected as ${who}.`, true);
    cookieEditing.value = false;
    cookieRememberInput.value = "";
    cookieSidInput.value = "";
    cookieBlobInput.value = "";
    cookiePasswordInput.value = "";
    emit("refresh-health");
  } catch (e) {
    say(`Save failed: ${errText(e)}`, false);
  } finally {
    cookieSaving.value = false;
  }
}

async function refreshCookieNow() {
  cookieRefreshing.value = true;
  cookieResult.value = "";
  try {
    applyStatus(await api.stravaCookieRefresh());
    say("Cookie refreshed via auto-login.", true);
  } catch (e) {
    say(`Refresh failed: ${errText(e)}`, false);
  } finally {
    cookieRefreshing.value = false;
  }
}

const confirmCookieDisconnect = ref(false);
async function disconnectCookie() {
  confirmCookieDisconnect.value = false;
  try {
    await api.stravaCookieDelete();
    await loadCookieStatus();
    say("Disconnected. Activities already synced stay.", true);
    emit("refresh-health");
  } catch (e) {
    say(`Disconnect failed: ${errText(e)}`, false);
  }
}

async function savePoll(patch: { enabled?: boolean; interval_min?: number }) {
  const prevEnabled = cookieStatus.value?.poll_enabled ?? false;
  const prevInterval = cookieStatus.value?.poll_interval_min ?? 360;
  pollSaving.value = true;
  pollError.value = "";
  try {
    applyStatus(await api.stravaCookiePoll(patch));
  } catch (e) {
    pollEnabled.value = prevEnabled;
    pollInterval.value = prevInterval;
    pollError.value = `Couldn't save — ${errText(e)}. The setting was not changed.`;
  } finally {
    pollSaving.value = false;
  }
}

async function syncCookieNow() {
  cookieSyncing.value = true;
  cookieResult.value = "";
  try {
    const r = await api.stravaCookieSync();
    if (r.error) say(`Sync error: ${r.error}`, false);
    else say(`Synced ${r.upserted} ${r.upserted === 1 ? "activity" : "activities"}.`, true);
    await loadCookieStatus();
  } catch (e) {
    say(`Sync failed: ${errText(e)}`, false);
  } finally {
    cookieSyncing.value = false;
    emit("refresh-health");
  }
}

async function syncCookieBulk() {
  cookieSyncing.value = true;
  cookieResult.value = "";
  try {
    const r = await api.stravaCookieBulk(cookieBulkDays.value, cookieBulkLimit.value ?? undefined);
    if (r.error) say(`Bulk import error: ${r.error}`, false);
    else say(`Bulk imported ${r.upserted} activities over the last ${cookieBulkDays.value} days.`, true);
    await loadCookieStatus();
  } catch (e) {
    say(`Bulk import failed: ${errText(e)}`, false);
  } finally {
    cookieSyncing.value = false;
    emit("refresh-health");
  }
}

// ── Legacy OAuth (needs a paid Strava sub) — fetched on first open ──
const legacyOpen = ref(false);
const legacyLoaded = ref(false);
const strava = ref<StravaStatus | null>(null);
const stravaConfig = ref<StravaAppConfigStatus | null>(null);
const stravaError = ref<string | null>(null);
const stravaSyncing = ref(false);
const stravaSyncResult = ref("");
const cidInput = ref("");
const secretInput = ref("");
const callbackInput = ref("");
const credsSaving = ref(false);
const credsResult = ref("");
const editingCreds = ref(false);

async function loadStrava() {
  stravaError.value = null;
  try {
    [strava.value, stravaConfig.value] = await Promise.all([api.stravaStatus(), api.stravaConfig()]);
    callbackInput.value = stravaConfig.value.callback_url ?? `${window.location.origin}/auth/strava/callback`;
    legacyLoaded.value = true;
  } catch (e) {
    stravaError.value = errText(e);
  }
}
function onLegacyToggle(ev: Event) {
  legacyOpen.value = (ev.target as HTMLDetailsElement).open;
  if (legacyOpen.value && !legacyLoaded.value) loadStrava();
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
  } catch (e) {
    stravaSyncResult.value = `Sync failed: ${errText(e)}`;
  } finally {
    stravaSyncing.value = false;
  }
}

const confirmOauthDisconnect = ref(false);
async function disconnectStrava() {
  confirmOauthDisconnect.value = false;
  try {
    await api.stravaDisconnect();
    await loadStrava();
  } catch (e) {
    stravaError.value = errText(e);
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
  } catch (e) {
    credsResult.value = `Save failed: ${errText(e)}`;
  } finally {
    credsSaving.value = false;
  }
}

const confirmClearCreds = ref(false);
async function clearStravaCreds() {
  confirmClearCreds.value = false;
  try {
    await api.clearStravaConfig();
    await loadStrava();
  } catch (e) {
    stravaError.value = errText(e);
  }
}

function fmt(ts: string | null): string {
  return ts ? fmtDateTime(ts) : "never";
}

onMounted(loadCookieStatus);
</script>

<template>
  <IntegrationHero :health="health" :loading="healthLoading" :error="healthError" @retry="emit('refresh-health')">
    <template #actions>
      <button v-if="cookieStatus?.configured && !cookieStatus.needs_reconnect" class="btn primary" type="button"
              :disabled="cookieSyncing" @click="syncCookieNow">
        {{ cookieSyncing ? "Syncing…" : "Sync now" }}
      </button>
    </template>
  </IntegrationHero>

  <div v-if="loading" class="skel" aria-busy="true">
    <div class="sk tall"></div><span class="sr-only">Loading Strava settings…</span>
  </div>
  <button v-else-if="loadError && !cookieStatus" class="errbar" type="button" @click="loading = true; loadCookieStatus()">
    <b>Couldn't load Strava settings</b><span>{{ loadError }}</span><em>Tap to retry</em>
  </button>

  <template v-else>
    <NeonEyebrow>Connection</NeonEyebrow>
    <section class="card">
      <!-- Connected and healthy — calm status, no form. -->
      <template v-if="cookieStatus?.configured && !cookieStatus.needs_reconnect && !cookieEditing">
        <ul class="kv">
          <li><span>Signed in as</span><span>{{ cookieStatus.athlete_name ?? cookieStatus.athlete_id ?? "Strava" }}</span></li>
          <li><span>Last sync</span><span>{{ fmt(cookieStatus.last_sync_at) }}</span></li>
          <li v-if="cookieStatus.auto_login_enabled">
            <span>Auto-login</span>
            <span>On{{ cookieStatus.last_auto_login_at ? ` · refreshed ${fmt(cookieStatus.last_auto_login_at)}` : "" }}</span>
          </li>
        </ul>
        <p v-if="cookieStatus.last_error" class="msg warn">Last error: {{ cookieStatus.last_error }}</p>
        <div class="actions">
          <button v-if="cookieStatus.auto_login_enabled" class="btn" type="button"
                  :disabled="cookieRefreshing" @click="refreshCookieNow">
            {{ cookieRefreshing ? "Refreshing…" : "Refresh cookie" }}
          </button>
          <button class="btn" type="button" @click="cookieEditing = true">Update cookies</button>
          <button class="btn danger" type="button" @click="confirmCookieDisconnect = true">Disconnect</button>
        </div>

        <!-- STRAVA-1: off by default — it reaches Strava on a timer with a
             credential that cannot refresh itself. -->
        <label class="check">
          <input v-model="pollEnabled" type="checkbox" :disabled="pollSaving"
                 @change="savePoll({ enabled: pollEnabled })" />
          <span>Sync automatically</span>
        </label>
        <label v-if="pollEnabled" class="field">
          <span>How often</span>
          <select v-model.number="pollInterval" :disabled="pollSaving"
                  @change="savePoll({ interval_min: pollInterval })">
            <option :value="60">Hourly</option>
            <option :value="360">Every 6 hours</option>
            <option :value="720">Every 12 hours</option>
            <option :value="1440">Daily</option>
          </select>
        </label>
        <p v-if="pollError" class="msg warn" role="alert">{{ pollError }}</p>
        <p v-if="cookieStatus.poll_stopped" class="msg warn">
          Automatic sync stopped after repeated failures — paste a fresh cookie, then switch it back on.
        </p>
        <p v-else-if="cookieStatus.poll_consecutive_failures > 0" class="msg info">
          {{ cookieStatus.poll_consecutive_failures }} recent failure(s); retrying less often until one succeeds.
        </p>

        <details>
          <summary>Import older history</summary>
          <label class="field">
            <span>Days back</span>
            <input v-model.number="cookieBulkDays" type="number" min="1" max="3650" />
          </label>
          <label class="field">
            <span>Limit <em>(blank = no limit)</em></span>
            <input v-model.number="cookieBulkLimit" type="number" min="1" max="1000" placeholder="e.g. 100" />
          </label>
          <div class="actions">
            <button class="btn primary" type="button" :disabled="cookieSyncing" @click="syncCookieBulk">
              {{ cookieSyncing ? "Importing…" : `Import the last ${cookieBulkDays} days` }}
            </button>
          </div>
        </details>
      </template>

      <!-- Fresh / reconnect / editing — the cookie paste box leads. -->
      <template v-else>
        <div v-if="cookieStatus?.needs_reconnect" class="callout">
          <b>Strava session expired</b>
          <span>Paste fresh cookies below to reconnect.</span>
          <span v-if="cookieStatus.last_error">{{ cookieStatus.last_error }}</span>
        </div>

        <label class="field">
          <span>Strava cookies</span>
          <textarea v-model="cookieBlobInput" rows="3" autocomplete="off" spellcheck="false"
                    placeholder='[{"name":"strava_remember_token","value":"…"}, {"name":"_strava4_session","value":"…"}]'></textarea>
        </label>
        <p class="hint">
          Export with the <a href="https://cookie-editor.com/" target="_blank" rel="noreferrer">Cookie-Editor</a>
          extension and paste here — JSON, header string, or Netscape all work. No password needed.
        </p>
        <div class="actions">
          <button class="btn primary" type="button" :disabled="cookieSaving" @click="saveCookie">
            {{ cookieSaving ? "Validating…" : "Save & test" }}
          </button>
          <button v-if="cookieEditing" class="btn" type="button" @click="cookieEditing = false">Cancel</button>
        </div>

        <details :open="cookieHowtoOpen" @toggle="cookieHowtoOpen = ($event.target as HTMLDetailsElement).open">
          <summary>How to get your cookies</summary>
          <ol class="steps">
            <li>Install <a href="https://cookie-editor.com/" target="_blank" rel="noreferrer">Cookie-Editor</a> (Chrome / Firefox / Edge / Safari).</li>
            <li>Sign in at <a href="https://www.strava.com/login" target="_blank" rel="noreferrer">strava.com</a> — any method (Google, emailed code, or password) works.</li>
            <li>Click the Cookie-Editor icon → <strong>Export</strong> → <strong>Export as JSON</strong> (copies to your clipboard).</li>
            <li>Paste it above and <strong>Save &amp; test</strong>.</li>
          </ol>
        </details>

        <details>
          <summary>Paste cookie values by hand (DevTools)</summary>
          <ol class="steps">
            <li>At strava.com open DevTools (<kbd>F12</kbd> or <kbd>Cmd+Opt+I</kbd>) → Application → Cookies → <code>https://www.strava.com</code>.</li>
            <li>Copy <code>strava_remember_token</code> (long-lived), or <code>_strava4_session</code> as a fallback.</li>
          </ol>
          <label class="field">
            <span>strava_remember_token <em>(long-lived)</em></span>
            <input v-model="cookieRememberInput" type="password" placeholder="long base64-ish string" autocomplete="off" />
          </label>
          <label class="field">
            <span>_strava4_session <em>(short-lived fallback)</em></span>
            <input v-model="cookieSidInput" type="password" placeholder="session cookie" autocomplete="off" />
          </label>
          <p class="hint">Then press <strong>Save &amp; test</strong> above.</p>
        </details>

        <details>
          <summary>Email + password auto-login (password accounts only)</summary>
          <p class="hint">
            Only if you sign in to Strava with an email + password (not Google / emailed code). Stored encrypted in
            your local database; the backend re-runs the login when the cookie expires.
          </p>
          <label class="field">
            <span>Strava email</span>
            <input v-model="cookieEmailInput" type="email" placeholder="you@example.com" autocomplete="username" />
          </label>
          <label class="field">
            <span>Strava password</span>
            <input v-model="cookiePasswordInput" type="password" placeholder="••••••••" autocomplete="current-password" />
          </label>
          <label class="check">
            <input v-model="cookieAutoLoginEnabled" type="checkbox" />
            <span>Auto-refresh cookie when it expires</span>
          </label>
        </details>

        <details>
          <summary>Why cookie mode?</summary>
          <p class="hint">
            Strava paywalled its free OAuth API on <strong>2026-06-30</strong>. Cookie mode pulls rides straight from
            <code>strava.com</code> using your normal browser login — no subscription, and the chest-strap HR in each
            FIT file comes through intact.
          </p>
        </details>
      </template>

      <p v-if="cookieResult" class="msg" :class="cookieResultOk ? 'ok' : 'warn'" role="status">{{ cookieResult }}</p>
    </section>

    <!-- Legacy OAuth path — kept reachable for users on a paid Strava sub. -->
    <section class="card">
      <details :open="legacyOpen" @toggle="onLegacyToggle">
        <summary>Legacy: Strava OAuth (needs a paid Strava subscription)</summary>
        <button v-if="stravaError && !legacyLoaded" class="errbar" type="button" @click="loadStrava">
          <b>Couldn't load OAuth settings</b><span>{{ stravaError }}</span><em>Tap to retry</em>
        </button>
        <p v-else-if="!legacyLoaded" class="hint">Loading…</p>
        <template v-else-if="strava && stravaConfig">
          <p v-if="stravaError" class="msg warn">{{ stravaError }}</p>
          <p v-if="!stravaConfig.configured" class="hint">
            Create an app at
            <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer">strava.com/settings/api</a>
            (Authorization Callback Domain = host of this dashboard, no port). Then paste the Client ID + Client Secret.
          </p>
          <ul v-else class="kv">
            <li><span>App credentials</span><span><code>{{ stravaConfig.client_id_masked }}</code> · {{ stravaConfig.source }}</span></li>
            <li><span>Callback</span><span>{{ stravaConfig.callback_url }}</span></li>
          </ul>

          <template v-if="!stravaConfig.configured || editingCreds">
            <label class="field"><span>Client ID</span>
              <input v-model="cidInput" placeholder="e.g. 123456" autocomplete="off" /></label>
            <label class="field"><span>Client Secret</span>
              <input v-model="secretInput" type="password" placeholder="40-char hex" autocomplete="off" /></label>
            <label class="field"><span>Callback URL <em>(optional)</em></span>
              <input v-model="callbackInput" placeholder="http://your-server:8080/auth/strava/callback" autocomplete="off" /></label>
            <div class="actions">
              <button class="btn primary" type="button" :disabled="credsSaving" @click="saveStravaCreds">
                {{ credsSaving ? "Saving…" : "Save credentials" }}
              </button>
              <button v-if="editingCreds" class="btn" type="button" @click="editingCreds = false">Cancel</button>
            </div>
            <p v-if="credsResult" class="msg info">{{ credsResult }}</p>
          </template>
          <div v-else class="actions">
            <button class="btn" type="button" @click="editingCreds = true">Edit credentials</button>
            <button v-if="stravaConfig.source === 'db'" class="btn danger" type="button" @click="confirmClearCreds = true">
              Clear stored credentials
            </button>
          </div>

          <template v-if="stravaConfig.configured">
            <template v-if="strava.connected">
              <ul class="kv">
                <li><span>Connected as</span><span>{{ strava.athlete_name ?? strava.athlete_id }}</span></li>
                <li><span>Scope</span><span>{{ strava.scope }}</span></li>
                <li><span>Last sync</span><span>{{ fmt(strava.last_sync_at) }}</span></li>
              </ul>
              <div class="actions">
                <button class="btn primary" type="button" :disabled="stravaSyncing" @click="syncStrava(90)">
                  {{ stravaSyncing ? "Syncing…" : "Sync last 90 days" }}
                </button>
                <button class="btn" type="button" :disabled="stravaSyncing" @click="syncStrava(30)">Sync 30 days</button>
                <button class="btn" type="button" :disabled="stravaSyncing" @click="syncStrava(365)">Sync 1 year</button>
                <button class="btn" type="button" :disabled="stravaSyncing" @click="syncStrava(3650)">Sync all</button>
                <button class="btn danger" type="button" @click="confirmOauthDisconnect = true">Disconnect</button>
              </div>
              <p v-if="stravaSyncResult" class="msg info">{{ stravaSyncResult }}</p>
            </template>
            <template v-else>
              <p class="hint">Authorize myvitals to read your activities (rides, runs, etc.).</p>
              <div class="actions">
                <button class="btn primary" type="button" @click="connectStrava">Connect Strava</button>
              </div>
            </template>
          </template>
        </template>
      </details>
    </section>
  </template>

  <ConfirmDialog :open="confirmCookieDisconnect" title="Disconnect Strava?"
                 detail="Activities already synced stay. The stored cookie is wiped, so syncing stops until you paste a new one."
                 confirm-label="Disconnect" @confirm="disconnectCookie" @cancel="confirmCookieDisconnect = false" />
  <ConfirmDialog :open="confirmOauthDisconnect" title="Disconnect Strava OAuth?"
                 detail="Stored activities stay; the OAuth tokens are wiped."
                 confirm-label="Disconnect" @confirm="disconnectStrava" @cancel="confirmOauthDisconnect = false" />
  <ConfirmDialog :open="confirmClearCreds" title="Clear Strava app credentials?"
                 detail="The existing OAuth connection stops working until credentials are saved again."
                 confirm-label="Clear" @confirm="clearStravaCreds" @cancel="confirmClearCreds = false" />
</template>

<style scoped src="../settings-forms.css"></style>
<style scoped>
.callout { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; margin-bottom: 8px; border-radius: 12px;
  background: rgba(255, 181, 46, .10); border: 1px solid rgba(255, 181, 46, .32); font-size: 13px; }
.callout b { color: #ffb52e; }
.callout span { color: #9b9bb0; }
</style>
