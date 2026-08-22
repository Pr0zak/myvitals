<script setup lang="ts">
import axios from "axios";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Eye, EyeOff, Check, X as XIcon,
  Download, RefreshCw, ExternalLink, AlertCircle,
} from "lucide-vue-next";
import { apiBase, queryToken } from "@/config";
import { api } from "@/api/client";
import { units, weightUnit, weightVal, weightToKg } from "@/units";
import { themeChoice } from "@/theme";
import { fmtDateTime, timeFormat } from "@/format";
import type { StravaAppConfigStatus, StravaStatus } from "@/api/types";
import TileOrderEditor from "@/components/TileOrderEditor.vue";
import DataHealthCard from "@/components/DataHealthCard.vue";

const tokenInput = ref(queryToken.value);
const tokenVisible = ref(false);
const apiBaseInput = ref(apiBase.value);
const status = ref<"idle" | "ok" | "fail">("idle");
const errorMsg = ref<string>("");

// SETTINGS-1: active section is driven by ?tab= in the URL so the
// left-rail "Settings" group in SideNav can deep-link to a specific
// section (and the existing isActive() query-matching makes the
// child glow when it's the live tab). Content panes below use
// v-show so form state survives tab switches.
type SectionKey =
  | "updates" | "access" | "display" | "profile" | "ai"
  | "tools" | "imports" | "trails" | "strava" | "fasting"
  | "ha" | "concept2" | "google";
const SECTION_KEYS: readonly SectionKey[] = [
  "updates", "access", "display", "profile", "ai", "trails",
  "strava", "google", "concept2", "fasting", "ha", "imports", "tools",
];

// TD-7 — the rail this page never had.
//
// activeTab was assigned exactly once, from ?tab=, and there was no in-page
// tab bar. Under the classic shell SideNav supplied the twelve links, but
// theme.ts defaults themeChoice to 'neon', and under neon App.vue renders
// NeonNav instead — so SideNav never mounts, and You.vue offers only four
// settings pills. That left access, ai, tools, imports, trails, fasting, ha
// and concept2 reachable *only* by typing a URL: on the default theme a
// fresh visitor could not get to AI configuration, historical imports, or
// the Home Assistant and Concept2 setup at all.
//
// The labels are derived from SECTION_KEYS rather than kept as a parallel
// list, so adding a section cannot silently omit it from the rail.
// SparkyFitness's own notes flag their hand-maintained 17-entry
// section→tab map as fragile for exactly this reason.
const SECTION_LABELS: Record<SectionKey, string> = {
  updates: "Updates",
  access: "Access",
  display: "Display",
  profile: "Profile",
  ai: "AI",
  trails: "Trails",
  strava: "Strava",
  concept2: "Concept2",
  google: "Google Health",
  fasting: "Fasting",
  ha: "Home Assistant",
  imports: "Imports",
  tools: "Tools",
};

const route = useRoute();
const router = useRouter();

/** Select a pane and record it in the URL, so the rail and any deep link
 *  agree and the browser Back button steps between panes. */
function selectTab(key: SectionKey) {
  activeTab.value = key;
  router.replace({ query: { ...route.query, tab: key } });
}

function tabFromQuery(q: unknown): SectionKey {
  const v = Array.isArray(q) ? q[0] : q;
  if (typeof v === "string" && (SECTION_KEYS as readonly string[]).includes(v)) {
    return v as SectionKey;
  }
  return "updates";
}
const activeTab = ref<SectionKey>(tabFromQuery(route.query.tab));
watch(() => route.query.tab, (t) => { activeTab.value = tabFromQuery(t); });

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

// SCS family — cookie-session ingest. Replaces OAuth path that
// Strava is paywalling 2026-06-30 for Standard Tier developers.
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
}
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
const cookieResult = ref<string>("");
const cookieBulkDays = ref(30);
const cookieBulkLimit = ref<number | null>(null);
const cookieHowtoOpen = ref(false);
const showLegacyOAuth = ref(false);

async function loadCookieStatus() {
  try {
    cookieStatus.value = await api.stravaCookieStatus();
    if (cookieStatus.value?.needs_reconnect) {
      // Prefill the known email so a password user only types the password.
      if (cookieStatus.value.email && !cookieEmailInput.value) {
        cookieEmailInput.value = cookieStatus.value.email;
      }
      // Auto-open the cookie-paste section — it's the reconnect path for
      // Google / email-code accounts that have no Strava password.
      cookieHowtoOpen.value = true;
    }
  } catch (e) {
    cookieResult.value = `Status check failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function saveCookie() {
  const haveRemember = !!cookieRememberInput.value.trim();
  const haveSid = !!cookieSidInput.value.trim();
  const haveBlob = !!cookieBlobInput.value.trim();
  const haveCookie = haveRemember || haveSid || haveBlob;
  const haveCreds = !!cookieEmailInput.value.trim() && !!cookiePasswordInput.value;
  if (!haveCookie && !haveCreds) {
    cookieResult.value = "Paste your Strava cookies (or a cookie/email+password).";
    return;
  }
  cookieSaving.value = true;
  cookieResult.value = "";
  try {
    const body: Parameters<typeof api.stravaCookieSet>[0] = {
      auto_login_enabled: cookieAutoLoginEnabled.value,
    };
    if (haveRemember) body.remember_token = cookieRememberInput.value.trim();
    if (haveSid) body.sid_cookie = cookieSidInput.value.trim();
    if (haveBlob) body.cookie_blob = cookieBlobInput.value.trim();
    if (haveCreds) {
      body.email = cookieEmailInput.value.trim();
      body.password = cookiePasswordInput.value;
    }
    const r = await api.stravaCookieSet(body);
    cookieStatus.value = r;
    // SCS-8 sid-only saves may not resolve the athlete — don't say "null".
    const who = r.athlete_name ?? r.athlete_id ?? "Strava";
    cookieResult.value = haveCreds
      ? `Auto-login OK — connected as ${who}.`
      : `Cookie saved — connected as ${who}.`;
    cookieEditing.value = false;
    cookieRememberInput.value = "";
    cookieSidInput.value = "";
    cookieBlobInput.value = "";
    cookiePasswordInput.value = "";
  } catch (e) {
    cookieResult.value = `Save failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    cookieSaving.value = false;
  }
}

async function refreshCookieNow() {
  cookieRefreshing.value = true;
  cookieResult.value = "";
  try {
    const r = await api.stravaCookieRefresh();
    cookieStatus.value = r;
    cookieResult.value = "Cookie refreshed via auto-login.";
  } catch (e) {
    cookieResult.value = `Refresh failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    cookieRefreshing.value = false;
  }
}

async function disconnectCookie() {
  if (!confirm("Disconnect cookie-mode Strava? Activities already synced stay; the stored cookie is wiped.")) return;
  try {
    await api.stravaCookieDelete();
    await loadCookieStatus();
    cookieResult.value = "Cookie cleared.";
  } catch (e) {
    cookieResult.value = `Disconnect failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function syncCookieNow() {
  cookieSyncing.value = true;
  cookieResult.value = "";
  try {
    const r = await api.stravaCookieSync();
    if (r.error) {
      cookieResult.value = `Sync error: ${r.error}`;
    } else {
      cookieResult.value = `Synced ${r.upserted} ${r.upserted === 1 ? "activity" : "activities"}.`;
    }
    await loadCookieStatus();
  } catch (e) {
    cookieResult.value = `Sync failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    cookieSyncing.value = false;
  }
}

async function syncCookieBulk() {
  cookieSyncing.value = true;
  cookieResult.value = "";
  try {
    const r = await api.stravaCookieBulk(cookieBulkDays.value, cookieBulkLimit.value ?? undefined);
    if (r.error) {
      cookieResult.value = `Bulk import error: ${r.error}`;
    } else {
      cookieResult.value = `Bulk imported ${r.upserted} activities over the last ${cookieBulkDays.value} days.`;
    }
    await loadCookieStatus();
  } catch (e) {
    cookieResult.value = `Bulk import failed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    cookieSyncing.value = false;
  }
}

// UPDATE-1: release check + apply trigger
interface UpdateCheck {
  current: string;
  latest: string | null;
  latest_tag: string | null;
  latest_url: string | null;
  latest_published_at: string | null;
  release_notes: string | null;
  update_available: boolean;
  error: string | null;
}
const updateInfo = ref<UpdateCheck | null>(null);
const updateChecking = ref(false);
const updateApplying = ref(false);
const updateApplyResult = ref<string>("");
const updateApplyError = ref<string | null>(null);

// Live apply progress — populated while the host cron is running the
// auto-update script. The phases map to recognisable lines in the
// auto-update.log so the UI can show a meaningful step-by-step,
// rather than just spinning until /version comes back.
type ApplyPhase = "idle" | "queued" | "pulling" | "recreating" | "verifying" | "done" | "failed";
const applyPhase = ref<ApplyPhase>("idle");
const applyProgress = ref<string[]>([]);   // log tail lines collected during apply
let applyPollHandle: ReturnType<typeof setInterval> | null = null;
let applyDeadline = 0;

interface UpdateStatus {
  log_present: boolean;
  log_modified_at: string | null;
  stale_seconds: number | null;
  cron_healthy: boolean;
  tail: string[];
  trigger_pending: boolean;
}
const updateStatus = ref<UpdateStatus | null>(null);
const updateLogOpen = ref(false);

function relAge(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

async function loadUpdateStatus() {
  try {
    const { data } = await axios.get<UpdateStatus>("/api/update/status", {
      baseURL: apiBase.value || undefined,
      headers: queryToken.value ? { Authorization: `Bearer ${queryToken.value}` } : {},
    });
    updateStatus.value = data;
  } catch {
    updateStatus.value = null;
  }
}

async function checkUpdate() {
  updateChecking.value = true;
  updateApplyResult.value = "";
  updateApplyError.value = null;
  try {
    const { data } = await axios.get<UpdateCheck>("/api/update/check", {
      baseURL: apiBase.value || undefined,
      headers: queryToken.value ? { Authorization: `Bearer ${queryToken.value}` } : {},
    });
    updateInfo.value = data;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string };
    updateInfo.value = {
      current: "?", latest: null, latest_tag: null, latest_url: null,
      latest_published_at: null, release_notes: null,
      update_available: false,
      error: err?.response?.data?.detail ?? err?.message ?? "check failed",
    };
  } finally {
    updateChecking.value = false;
  }
}

function stopApplyPoll() {
  if (applyPollHandle) {
    clearInterval(applyPollHandle);
    applyPollHandle = null;
  }
}

// Walk the log tail lines and pick the latest one that maps to a known
// phase. The auto-update.sh emits specific strings we can match on
// (see deploy/auto-update.sh).
function classifyLogLine(line: string): ApplyPhase | null {
  if (line.includes("update succeeded — now running")) return "done";
  if (line.includes("unhealthy after upgrade") || line.includes("rollback")) return "failed";
  if (line.includes("Health probe") || line.includes("/health")) return "verifying";
  if (line.includes("recreating services") || line.includes("force-recreate")) return "recreating";
  if (line.includes("pulling") || line.includes("Pulling") || line.includes("digest")) return "pulling";
  if (line.includes("triggered by UI request") || line.includes("update detected")) return "queued";
  return null;
}

async function applyUpdate() {
  if (!confirm(
    "Apply the latest release? The backend will restart and the dashboard "
    + "will be unreachable for ~15 seconds.",
  )) return;
  updateApplying.value = true;
  updateApplyResult.value = "";
  updateApplyError.value = null;
  applyPhase.value = "queued";
  applyProgress.value = [];
  const startedAt = Date.now();
  applyDeadline = startedAt + 5 * 60_000;     // give up after 5 min
  const baselineTail = updateStatus.value?.tail?.join("\n") ?? "";

  try {
    const { data } = await axios.post<{
      triggered: boolean; error?: string; hint?: string;
    }>("/api/update/apply", {}, {
      baseURL: apiBase.value || undefined,
      headers: queryToken.value ? { Authorization: `Bearer ${queryToken.value}` } : {},
    });
    if (!data.triggered) {
      applyPhase.value = "failed";
      updateApplyError.value = data.hint ?? data.error ?? "Trigger failed.";
      updateApplying.value = false;
      return;
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string };
    applyPhase.value = "failed";
    updateApplyError.value = err?.response?.data?.detail ?? err?.message ?? "apply failed";
    updateApplying.value = false;
    return;
  }

  // Trigger queued — now poll /update/status until the cron picks it up
  // and the log advances. Show a live tail until we see the terminal
  // "update succeeded" / rollback line.
  applyPollHandle = setInterval(async () => {
    if (Date.now() > applyDeadline) {
      stopApplyPoll();
      applyPhase.value = "failed";
      updateApplyError.value =
        "Update timed out after 5 minutes. Check the log manually on the host.";
      updateApplying.value = false;
      return;
    }
    await loadUpdateStatus();
    const status = updateStatus.value;
    if (!status) return;

    // Only show *new* lines (the ones written after we triggered).
    const tail = status.tail ?? [];
    const joined = tail.join("\n");
    if (joined === baselineTail) return;
    // Find the index where the new tail diverges from the baseline.
    const baselineLines = baselineTail.split("\n");
    const newLines = tail.slice(baselineLines.length);
    if (newLines.length > 0) applyProgress.value = newLines;

    // Walk the newest lines to update phase.
    for (let i = newLines.length - 1; i >= 0; i--) {
      const phase = classifyLogLine(newLines[i]);
      if (phase) { applyPhase.value = phase; break; }
    }

    if (applyPhase.value === "done") {
      stopApplyPoll();
      updateApplyResult.value = "Update complete. Re-checking version…";
      updateApplying.value = false;
      // Give the new backend a moment to come up before polling /version.
      setTimeout(() => checkUpdate(), 1_500);
    } else if (applyPhase.value === "failed") {
      stopApplyPoll();
      const lastLine = newLines[newLines.length - 1] ?? "Update failed.";
      updateApplyError.value = lastLine;
      updateApplying.value = false;
    }
  }, 2_000);
}

// Concept2 (rower) — long-lived personal token from log.concept2.com/developers
type Concept2Status = Awaited<ReturnType<typeof api.concept2Status>>;
const concept2 = ref<Concept2Status | null>(null);
const concept2Error = ref<string | null>(null);
const concept2TokenInput = ref("");
const concept2Saving = ref(false);
const concept2Result = ref<string>("");
const webhookBase = computed(
  () => apiBase.value || window.location.origin,
);

// Fasting preferences — stored as profile.extra.fasting_prefs.
// Drives the default-protocol pre-selection on Fasting.vue,
// notification cadence, and the server's scheduled-mode auto-
// start/end (#FAST-12 fasting_scheduled APScheduler job).
const fastingDefaultProto = ref<string>("16:8");
const fastingScheduledMode = ref<boolean>(false);
const fastingEatStart = ref<number>(12);
const fastingEatEnd = ref<number>(20);
const fastingNotifs = ref<boolean>(true);
const fastingReligiousCal = ref<string>("none");
const fastingSaving = ref(false);
const fastingMsg = ref<string>("");

// Home Assistant — device-status liveness for the Pixel Watch.
// Config (ha_url / ha_token / ha_realtime_enabled) lives in the backend
// .env; this section only surfaces the live status. HR / HRV / SpO2 /
// sleep stay on Health Connect — HA only carries the on-body / battery
// / charger / activity-state signals.
type DeviceStatus = Awaited<ReturnType<typeof api.deviceStatusLatest>>;
const haStatus = ref<DeviceStatus>(null);
const haError = ref<string | null>(null);
const haLoading = ref(false);
const haAgeS = computed<number | null>(() => {
  const ts = haStatus.value?.time;
  if (!ts) return null;
  return Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
});

// HA config form state — token stored in DB, never echoed plaintext.
const haCfgUrl = ref<string>("");
const haCfgToken = ref<string>("");        // user typing field; empty = keep existing
const haCfgEnabled = ref<boolean>(false);
const haCfgMasked = ref<string | null>(null);
const haCfgSaving = ref(false);
const haCfgMsg = ref<string>("");
const haCfgConfigured = ref<boolean>(false);

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
  try {
    aiCfg.value = await api.aiConfig();
    // Seed the editors from the server only when the user has not started
    // typing, so a background refresh cannot discard an unsaved draft.
    if (!aiInstructionsDirty.value || aiInstructions.value === "") {
      aiInstructions.value = aiCfg.value.custom_instructions ?? "";
    }
    if (!aiProviderDirty.value) {
      aiProvider.value = aiCfg.value.provider ?? "anthropic";
      aiBaseUrl.value = aiCfg.value.base_url ?? "";
    }
  } catch { /* ignore */ }
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
// TD-9 — standing instructions handed to every AI surface.
//
// Before this the entire user model the coach had was a three-value tone
// enum: there was no way to say "rehabbing a left shoulder, never suggest
// overhead pressing" or "my fasts are religious, don't read a low HRV as
// overtraining". The text is appended to every system prompt under a fixed
// heading, inside the prefix that already carries the prompt-cache
// breakpoint, so it costs nothing per call once cached.
const aiInstructions = ref("");
const aiInstructionsSaving = ref(false);
const aiInstructionsSaved = ref(false);
const aiInstructionsMax = computed(() => aiCfg.value?.custom_instructions_max ?? 1000);
const aiInstructionsDirty = computed(
  () => aiInstructions.value !== (aiCfg.value?.custom_instructions ?? ""),
);

async function aiSaveInstructions() {
  aiInstructionsSaving.value = true;
  aiInstructionsSaved.value = false;
  try {
    await api.aiUpdateConfig({ custom_instructions: aiInstructions.value.trim() });
    await loadAiCfg();
    aiInstructions.value = aiCfg.value?.custom_instructions ?? "";
    aiInstructionsSaved.value = true;
  } finally {
    aiInstructionsSaving.value = false;
  }
}

// TD-8 — which backend answers.
//
// Everything else in this app is self-hosted; the AI layer was the one part
// that required an external account and a credit card. An OpenAI-compatible
// endpoint pointed at Ollama on the LAN takes the running cost to zero and
// keeps every byte inside the house.
const aiProvider = ref<"anthropic" | "openai_compatible" | "ollama">("anthropic");
const aiBaseUrl = ref("");
const aiProviderSaving = ref(false);
const aiProviderError = ref("");
const aiProviderDirty = computed(
  () => aiProvider.value !== (aiCfg.value?.provider ?? "anthropic")
    || aiBaseUrl.value.trim() !== (aiCfg.value?.base_url ?? ""),
);

async function aiSaveProvider() {
  aiProviderSaving.value = true;
  aiProviderError.value = "";
  try {
    await api.aiUpdateConfig({
      provider: aiProvider.value,
      base_url: aiBaseUrl.value.trim(),
    });
    await loadAiCfg();
  } catch (e: unknown) {
    // The server validates the URL on write precisely so the message lands
    // here, next to the field, rather than surfacing later as a failed card.
    const resp = (e && typeof e === "object" && "response" in e)
      ? (e as { response?: { data?: { detail?: string } } }).response
      : null;
    aiProviderError.value = resp?.data?.detail
      ?? (e instanceof Error ? e.message : String(e));
  } finally {
    aiProviderSaving.value = false;
  }
}

// ── Google Health (GH-1) ──────────────────────────────────────────
//
// A second, phone-independent route to the same watch data. The phone is
// currently the only path in for every stream, and two of them — SpO2 and
// skin temperature — have been dead since a Pixel Watch firmware update.
// Google's API serves both.
const ghStatus = ref<Awaited<ReturnType<typeof api.googleHealthStatus>> | null>(null);
const ghCfg = ref<Awaited<ReturnType<typeof api.googleHealthConfig>> | null>(null);
const ghClientId = ref("");
const ghClientSecret = ref("");
const ghCallback = ref("");
const ghBusy = ref(false);
const ghError = ref("");
const ghResult = ref("");
const ghProbe = ref<Awaited<ReturnType<typeof api.googleHealthProbe>> | null>(null);

async function loadGoogleHealth() {
  if (!queryToken.value) return;
  try {
    ghCfg.value = await api.googleHealthConfig();
    ghStatus.value = await api.googleHealthStatus();
    if (ghCfg.value.client_id && !ghClientId.value) ghClientId.value = ghCfg.value.client_id;
    if (ghCfg.value.callback_url && !ghCallback.value) ghCallback.value = ghCfg.value.callback_url;
    if (!ghCallback.value) {
      // Loopback, deliberately — Google rejects LAN hostnames outright
      // ("must end with a public top-level domain") and localhost is its
      // only exception to the HTTPS rule. Nothing listens on this address;
      // it exists so the authorization code lands somewhere we can read it
      // out of the address bar. See the paste step below.
      ghCallback.value = "http://localhost:8080/api/auth/google-health/callback";
    }
  } catch { /* ignore */ }
}

function ghFail(e: unknown) {
  const resp = (e && typeof e === "object" && "response" in e)
    ? (e as { response?: { data?: { detail?: string } } }).response
    : null;
  ghError.value = resp?.data?.detail ?? (e instanceof Error ? e.message : String(e));
}

async function ghSaveConfig() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  try {
    await api.googleHealthSetConfig({
      client_id: ghClientId.value.trim(),
      client_secret: ghClientSecret.value.trim(),
      callback_url: ghCallback.value.trim(),
    });
    ghClientSecret.value = "";   // never keep it in the DOM after saving
    ghResult.value = "Saved. Now press Connect.";
    await loadGoogleHealth();
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

const ghPasteUrl = ref("");
const ghAuthUrl = ref("");

async function ghConnect() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  // Open the tab SYNCHRONOUSLY, inside the click handler, then point it at
  // the URL once we have it. A window.open() after an await has lost the
  // user-activation that permits it, so browsers block it as a popup — and
  // block it silently, which presents as a button that does nothing.
  const tab = window.open("", "_blank");
  try {
    const { url } = await api.googleHealthAuthorizeUrl();
    ghAuthUrl.value = url;
    if (tab) {
      tab.location.href = url;
    }
    // The link is rendered either way. If the popup was blocked despite the
    // above, the user has somewhere to click rather than a dead button.
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
    ghResult.value = "Connected. Now press \u201cWhat data is available?\u201d.";
    await loadGoogleHealth();
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

async function ghRunProbe() {
  ghBusy.value = true; ghError.value = ""; ghResult.value = ""; ghProbe.value = null;
  try {
    ghProbe.value = await api.googleHealthProbe(7);
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

async function ghSync(days: number) {
  ghBusy.value = true; ghError.value = ""; ghResult.value = "";
  try {
    const r = await api.googleHealthSync(days);
    const total = Object.values(r.written).reduce((a, b) => a + b, 0);
    ghResult.value = total
      ? `Wrote ${Object.entries(r.written).map(([k, v]) => `${v} ${k}`).join(", ")}.`
      : "Connected fine, but Google returned no readings for that window.";
    await loadGoogleHealth();
  } catch (e) { ghFail(e); } finally { ghBusy.value = false; }
}

async function ghTogglePoll(enabled: boolean) {
  try { await api.googleHealthSetPoll(enabled); await loadGoogleHealth(); }
  catch (e) { ghFail(e); }
}

async function ghSetInterval(minutes: number) {
  if (!ghStatus.value) return;
  try {
    await api.googleHealthSetPoll(ghStatus.value.poll_enabled, minutes);
    await loadGoogleHealth();
  } catch (e) { ghFail(e); }
}

async function ghDisconnect() {
  try { await api.googleHealthDisconnect(); ghProbe.value = null; await loadGoogleHealth(); }
  catch (e) { ghFail(e); }
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

// IMPORT-1: strength-log CSV (Strong / Hevy / FitNotes)
const strengthImportBusy = ref(false);
const strengthImportResult = ref<string>("");
const strengthImportError = ref<string>("");
const strengthSource = ref<string>("auto"); // auto | strong | hevy | fitnotes
const strongUnit = ref<string>("kg"); // Strong's weight column has no unit
async function uploadStrength(file: File) {
  strengthImportBusy.value = true;
  strengthImportResult.value = "";
  strengthImportError.value = "";
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const fd = new FormData();
    fd.append("file", file);
    const params: Record<string, string> = { strong_unit: strongUnit.value };
    if (strengthSource.value !== "auto") params.source = strengthSource.value;
    const r = await axios.post(`${base}/import/strength`, fd, {
      params,
      headers: {
        Authorization: `Bearer ${queryToken.value}`,
        "Content-Type": "multipart/form-data",
      },
    });
    const d = r.data;
    let msg = `Imported ${d.workouts} workout${d.workouts === 1 ? "" : "s"} · ${d.sets} sets from ${d.source}.`;
    if (d.skipped_duplicates) msg += ` ${d.skipped_duplicates} duplicate session(s) skipped.`;
    if (d.unmatched_exercises) {
      msg += ` ${d.unmatched_exercises} exercise(s) weren't in the catalog (kept by name).`;
    }
    strengthImportResult.value = msg;
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const r = (e as { response?: { status?: number; data?: { detail?: string } } }).response;
      strengthImportError.value = r?.data?.detail ?? `HTTP ${r?.status ?? "?"}`;
    } else {
      strengthImportError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    strengthImportBusy.value = false;
  }
}
function pickStrengthFile() {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = ".csv,text/csv";
  inp.onchange = () => {
    const f = inp.files?.[0];
    if (f) uploadStrength(f);
  };
  inp.click();
}

// Profile
type Profile = Awaited<ReturnType<typeof api.getProfile>>;
const profile = ref<Profile | null>(null);
const profileSaving = ref(false);
const profileMsg = ref<string>("");
const locating = ref(false);
const locateError = ref<string>("");
const homeQueryInput = ref<string>("");
const geocoding = ref(false);
const geocodedLabel = ref<string>("");

async function useCurrentLocation() {
  if (!navigator.geolocation) {
    locateError.value = "Geolocation not available in this browser.";
    return;
  }
  locating.value = true;
  locateError.value = "";
  geocodedLabel.value = "";
  try {
    const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true, timeout: 10000, maximumAge: 0,
      });
    });
    if (profile.value) {
      profile.value.home_latitude = Math.round(pos.coords.latitude * 1e6) / 1e6;
      profile.value.home_longitude = Math.round(pos.coords.longitude * 1e6) / 1e6;
    }
  } catch (e: any) {
    locateError.value = e?.message ?? "Location denied or unavailable.";
  } finally {
    locating.value = false;
  }
}

async function resolveHomeQuery() {
  const q = homeQueryInput.value.trim();
  if (!q) return;
  geocoding.value = true;
  locateError.value = "";
  geocodedLabel.value = "";
  try {
    const r = await api.geocodeHome(q);
    if (profile.value) {
      profile.value.home_latitude = Math.round(r.latitude * 1e6) / 1e6;
      profile.value.home_longitude = Math.round(r.longitude * 1e6) / 1e6;
    }
    geocodedLabel.value = r.display_name
      ? `Matched: ${r.display_name}`
      : `Resolved via ${r.source}`;
  } catch (e: any) {
    locateError.value = e?.response?.data?.detail
      ?? e?.message ?? "Geocode failed.";
  } finally {
    geocoding.value = false;
  }
}

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
    const fp = (extra.fasting_prefs ?? {}) as Record<string, unknown>;
    fastingDefaultProto.value = (fp.default_protocol as string | undefined) ?? "16:8";
    fastingScheduledMode.value = Boolean(fp.scheduled_mode_enabled);
    fastingEatStart.value = (fp.eating_window_start_h as number | undefined) ?? 12;
    fastingEatEnd.value = (fp.eating_window_end_h as number | undefined) ?? 20;
    fastingNotifs.value = (fp.notifications_enabled as boolean | undefined) ?? true;
    fastingReligiousCal.value = (fp.religious_calendar as string | undefined) ?? "none";
  } catch { /* ignore */ }
}

async function saveFastingPrefs() {
  if (!profile.value) return;
  fastingSaving.value = true;
  fastingMsg.value = "";
  try {
    const extra: Record<string, unknown> = {
      ...(profile.value.extra as Record<string, unknown> | null ?? {}),
    };
    extra.fasting_prefs = {
      default_protocol: fastingDefaultProto.value,
      scheduled_mode_enabled: fastingScheduledMode.value,
      eating_window_start_h: Number(fastingEatStart.value),
      eating_window_end_h: Number(fastingEatEnd.value),
      notifications_enabled: fastingNotifs.value,
      religious_calendar: fastingReligiousCal.value,
    };
    profile.value = await api.putProfile({
      birth_date: profile.value.birth_date,
      sex: profile.value.sex,
      height_cm: profile.value.height_cm,
      weight_goal_kg: profile.value.weight_goal_kg,
      resting_hr_baseline: profile.value.resting_hr_baseline,
      max_hr: profile.value.max_hr,
      activity_level: profile.value.activity_level,
      extra,
      home_latitude: profile.value.home_latitude,
      home_longitude: profile.value.home_longitude,
    }) as typeof profile.value;
    fastingMsg.value = "Saved.";
  } catch (e: unknown) {
    fastingMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    fastingSaving.value = false;
  }
}
async function saveProfile() {
  if (!profile.value) return;
  profileSaving.value = true;
  profileMsg.value = "";
  try {
    const extra: Record<string, unknown> = {
      ...(profile.value.extra as Record<string, unknown> | null ?? {}),
    };
    // Explicit null, not `delete`. PUT /profile now MERGES `extra` so a
    // client that models only some keys cannot erase the rest — the phone
    // was deleting the display block every time the workout reminder was
    // toggled. Under a merge, an absent key means "leave it alone", so
    // clearing a goal has to say so out loud.
    extra.steps_goal =
      stepsGoalInput.value && stepsGoalInput.value > 0
        ? Number(stepsGoalInput.value)
        : null;
    extra.sleep_goal_h =
      sleepGoalInput.value && sleepGoalInput.value > 0
        ? Number(sleepGoalInput.value)
        : null;

    profile.value = await api.putProfile({
      birth_date: profile.value.birth_date,
      sex: profile.value.sex,
      height_cm: profile.value.height_cm,
      weight_goal_kg: profile.value.weight_goal_kg,
      resting_hr_baseline: profile.value.resting_hr_baseline,
      max_hr: profile.value.max_hr,
      activity_level: profile.value.activity_level,
      extra: Object.keys(extra).length ? extra : null,
      home_latitude: profile.value.home_latitude,
      home_longitude: profile.value.home_longitude,
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

type ImportKind = "fitbit" | "fitbit_tracks" | "garmin" | "garmin_tracks";

async function uploadImport(kind: ImportKind, file: File) {
  importBusy.value = kind === "garmin_tracks" ? "garmin"
                   : kind === "fitbit_tracks" ? "fitbit" : kind;
  importResult.value = "";
  importError.value = "";
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const fd = new FormData();
    fd.append("file", file);
    const params: Record<string, string> = {};
    if (kind === "fitbit") params.weight_unit = fitbitWeightUnit.value;
    const path = kind === "garmin_tracks" ? "/import/garmin/tracks"
               : kind === "fitbit_tracks" ? "/import/fitbit/tracks"
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
    if (kind === "garmin_tracks" || kind === "fitbit_tracks") {
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
    await Promise.all([loadStrava(), loadCookieStatus(), loadTrailCfg(), loadConcept2(), loadHaStatus()]);
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

async function loadConcept2() {
  if (!queryToken.value) return;
  concept2Error.value = null;
  try { concept2.value = await api.concept2Status(); }
  catch (e: unknown) {
    concept2Error.value = e instanceof Error ? e.message : String(e);
  }
}

async function loadHaStatus() {
  if (!queryToken.value) return;
  haError.value = null;
  haLoading.value = true;
  try {
    const [status, cfg] = await Promise.all([
      api.deviceStatusLatest(),
      api.haConfigGet(),
    ]);
    haStatus.value = status;
    haCfgUrl.value = cfg.url ?? "";
    haCfgEnabled.value = cfg.realtime_enabled;
    haCfgMasked.value = cfg.token_masked;
    haCfgConfigured.value = cfg.configured;
  } catch (e: unknown) {
    haError.value = e instanceof Error ? e.message : String(e);
  } finally {
    haLoading.value = false;
  }
}

async function saveHaConfig() {
  haCfgSaving.value = true; haCfgMsg.value = "";
  try {
    const body: Record<string, unknown> = {
      url: haCfgUrl.value.trim() || null,
      realtime_enabled: haCfgEnabled.value,
    };
    // Only send token if the user typed something — empty input
    // means "keep what's in the DB". To explicitly clear, the user
    // can type any whitespace and the backend trims it.
    if (haCfgToken.value !== "") body.token = haCfgToken.value;
    await api.haConfigPut(body);
    haCfgToken.value = "";   // never keep it in memory
    haCfgMsg.value = "Saved. Restart the backend to apply (a future iteration will hot-reload).";
    await loadHaStatus();
  } catch (e: unknown) {
    haCfgMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    haCfgSaving.value = false;
  }
}

async function saveConcept2() {
  const token = concept2TokenInput.value.trim();
  if (!token) {
    concept2Result.value = "Paste a token first.";
    return;
  }
  concept2Saving.value = true;
  concept2Result.value = "";
  concept2Error.value = null;
  try {
    const r = await api.concept2Connect(token);
    concept2.value = r as Concept2Status;
    concept2TokenInput.value = "";
    concept2Result.value = r.connected
      ? `Connected as ${r.user_name ?? r.user_id ?? "Concept2 user"}.`
      : "Saved.";
  } catch (e: unknown) {
    concept2Error.value = e instanceof Error ? e.message : String(e);
  } finally { concept2Saving.value = false; }
}

async function disconnectConcept2() {
  if (!confirm("Disconnect Concept2? Stored erg sessions will stay; the token will be wiped.")) return;
  try {
    await api.concept2Disconnect();
    await loadConcept2();
    concept2Result.value = "Disconnected.";
  } catch (e) {
    concept2Error.value = e instanceof Error ? e.message : String(e);
  }
}

async function syncConcept2(full: boolean) {
  concept2Saving.value = true;
  concept2Result.value = "";
  try {
    const r = await api.concept2Sync({ full });
    concept2Result.value = `Pulled ${r.upserted} session(s).`;
    await loadConcept2();
  } catch (e) {
    concept2Error.value = e instanceof Error ? e.message : String(e);
  } finally { concept2Saving.value = false; }
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
  loadCookieStatus();
  loadConcept2();
  loadGoogleHealth();
  loadTrailCfg();
  loadProfile();
  loadAiCfg();
  loadHaStatus();
  startJobPolling();
  checkUpdate();
  loadUpdateStatus();
});
onUnmounted(() => {
  stopJobPolling();
  stopApplyPoll();
});

const APPLY_PHASE_LABEL: Record<ApplyPhase, string> = {
  idle: "",
  queued: "Waiting for host cron to pick up trigger…",
  pulling: "Pulling new images from GHCR…",
  recreating: "Recreating containers…",
  verifying: "Verifying backend health…",
  done: "Update complete.",
  failed: "Update failed.",
};
</script>

<template>
  <div class="settings">
    <h1>Settings</h1>

    <nav class="settings-rail" aria-label="Settings sections">
      <button
        v-for="key in SECTION_KEYS"
        :key="key"
        type="button"
        class="rail-pill"
        :class="{ active: key === activeTab }"
        :aria-current="key === activeTab ? 'page' : undefined"
        @click="selectTab(key)"
      >{{ SECTION_LABELS[key] }}</button>
    </nav>

    <section v-show="activeTab === 'updates'" class="settings-pane">
        <h2>
          Updates
          <span v-if="updateInfo?.update_available" class="badge-new">
            v{{ updateInfo.latest }} available
          </span>
          <span v-else-if="updateInfo && !updateInfo.error" class="badge-ok">
            up to date
          </span>
        </h2>
      <div class="update-row">
        <div class="update-versions">
          <div class="kv">
            <span class="kv-label">Running</span>
            <span class="kv-value mono">{{ updateInfo?.current ?? "—" }}</span>
          </div>
          <div class="kv">
            <span class="kv-label">Latest release</span>
            <span class="kv-value mono">
              {{ updateInfo?.latest ?? "—" }}
              <a v-if="updateInfo?.latest_url" :href="updateInfo.latest_url"
                 target="_blank" rel="noopener" class="release-link">
                <ExternalLink :size="11"/>
              </a>
            </span>
          </div>
          <div v-if="updateInfo?.latest_published_at" class="kv">
            <span class="kv-label">Published</span>
            <span class="kv-value">{{ fmtDateTime(updateInfo.latest_published_at) }}</span>
          </div>
        </div>
        <div class="update-actions">
          <button class="ghost" :disabled="updateChecking" @click="checkUpdate">
            <RefreshCw :size="14" :class="{ spin: updateChecking }"/>
            {{ updateChecking ? "Checking…" : "Check for updates" }}
          </button>
          <button v-if="updateInfo?.update_available"
                  class="primary" :disabled="updateApplying" @click="applyUpdate">
            <Download :size="14"/>
            {{ updateApplying ? "Applying…" : `Apply v${updateInfo.latest}` }}
          </button>
        </div>
      </div>

      <!-- Live apply progress — visible while the host cron is running
           the auto-update script (or while we're waiting for it to
           pick up the trigger). Shows current phase + tail of the
           auto-update.log so the user sees what's actually happening
           instead of staring at a "Applying…" button label. -->
      <div v-if="updateApplying || applyPhase === 'done' || applyPhase === 'failed'"
           class="apply-progress" :class="`phase-${applyPhase}`">
        <div class="apply-head">
          <span class="apply-dot" :class="`phase-${applyPhase}`"/>
          <span class="apply-phase-label">{{ APPLY_PHASE_LABEL[applyPhase] }}</span>
          <RefreshCw v-if="updateApplying" :size="13" class="spin"/>
        </div>
        <ol class="apply-steps">
          <li :class="['done']">Trigger queued</li>
          <li :class="{
                done: ['pulling','recreating','verifying','done'].includes(applyPhase),
                current: applyPhase === 'pulling',
              }">Pull images</li>
          <li :class="{
                done: ['recreating','verifying','done'].includes(applyPhase),
                current: applyPhase === 'recreating',
              }">Recreate containers</li>
          <li :class="{
                done: ['verifying','done'].includes(applyPhase),
                current: applyPhase === 'verifying',
              }">Health check</li>
          <li :class="{
                done: applyPhase === 'done',
                current: applyPhase === 'verifying',
              }">Verify new version</li>
        </ol>
        <pre v-if="applyProgress.length" class="apply-tail">{{ applyProgress.join('\n') }}</pre>
      </div>

      <div v-if="updateInfo?.release_notes" class="release-notes">
        <h3>What's new</h3>
        <pre>{{ updateInfo.release_notes }}</pre>
      </div>

      <!-- Auto-update cron status — only renders when the backend
           has visibility into the host log (i.e. shared volume is
           mounted and the cron has written at least once). -->
      <div v-if="updateStatus?.log_present" class="cron-status">
        <span :class="['cron-dot', updateStatus.cron_healthy ? 'ok' : 'bad']"/>
        <span class="cron-text">
          Auto-update {{ updateStatus.cron_healthy ? 'running' : 'stalled' }}
          <span class="dim">· last activity {{ relAge(updateStatus.stale_seconds) }}</span>
          <span v-if="updateStatus.trigger_pending" class="dim">
            · trigger queued
          </span>
        </span>
        <button class="ghost btn-tiny" @click="updateLogOpen = !updateLogOpen">
          {{ updateLogOpen ? 'Hide' : 'View' }} log
        </button>
      </div>
      <pre v-if="updateLogOpen && updateStatus?.tail?.length"
           class="cron-log">{{ updateStatus.tail.join('\n') }}</pre>

      <div v-if="updateApplyResult" class="ok">
        <Check :size="14"/> {{ updateApplyResult }}
      </div>
      <div v-if="updateApplyError" class="err">
        <AlertCircle :size="14"/> {{ updateApplyError }}
      </div>
      <div v-if="updateInfo?.error" class="hint">
        Couldn't check GitHub: {{ updateInfo.error }}
      </div>
    </section>

    <section v-show="activeTab === 'access'" class="settings-pane">
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
    </section>

    <section v-show="activeTab === 'display'" class="settings-pane">
      <h2>Display</h2>
      <div class="display-grid">
        <div class="lbl">Theme</div>
        <div class="choices">
          <label class="pick"><input type="radio" value="dark" v-model="themeChoice"/> Dark</label>
          <label class="pick"><input type="radio" value="light" v-model="themeChoice"/> Light</label>
          <label class="pick"><input type="radio" value="auto" v-model="themeChoice"/> Auto</label>
          <label class="pick"><input type="radio" value="neon" v-model="themeChoice"/> ✦ Vitality Neon</label>
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

      <h2 style="margin-top:2rem;">Data health</h2>
      <DataHealthCard v-if="queryToken"/>

      <h2 style="margin-top:2rem;">Key metrics</h2>
      <TileOrderEditor v-if="queryToken"/>
      <p v-else class="hint">Set a token under Access to edit tile order.</p>
    </section>

    <section v-show="activeTab === 'profile'" v-if="queryToken && profile" class="settings-pane">
      <h2>Profile</h2>
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
          <span>Max heart rate (bpm)
            <em class="opt" v-if="profile.derived?.max_hr_estimated">
              (estimated {{ profile.derived.max_hr_estimated }} from your age)
            </em>
          </span>
          <input type="number" v-model.number="profile.max_hr"
                 :placeholder="profile.derived?.max_hr_estimated?.toString() ?? 'estimated from age if blank'"
                 min="120" max="230"/>
          <em class="opt">
            Every heart-rate zone in the app is a percentage of this number, so
            a measured value from a ramp test or a hard race gives sharper
            zones than the age formula. Leave blank to keep the estimate.
          </em>
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

      <fieldset class="fieldset">
        <legend>Home location</legend>
        <p class="hint">Used to center the Activities Map. Paste an address, a Google Maps share link, or a lat,lng pair — or click ‘Use current location’.</p>
        <label>
          <span>Address or Google Maps link</span>
          <div style="display:flex; gap:0.4rem;">
            <input type="text"
                   v-model="homeQueryInput"
                   placeholder="123 Main St, Pittsburgh PA · or https://maps.app.goo.gl/…"
                   style="flex:1;"
                   @keyup.enter="resolveHomeQuery"/>
            <button :disabled="geocoding || !homeQueryInput.trim()"
                    @click="resolveHomeQuery">
              {{ geocoding ? 'Resolving…' : 'Resolve' }}
            </button>
          </div>
          <span v-if="geocodedLabel" class="hint" style="color: var(--good, #22c55e);">
            ✓ {{ geocodedLabel }}
          </span>
        </label>
        <div class="grid two">
          <label>
            <span>Latitude</span>
            <input type="number" step="0.000001" min="-90" max="90"
                   v-model.number="profile.home_latitude"
                   placeholder="e.g. 40.4406"/>
          </label>
          <label>
            <span>Longitude</span>
            <input type="number" step="0.000001" min="-180" max="180"
                   v-model.number="profile.home_longitude"
                   placeholder="e.g. -79.9959"/>
          </label>
        </div>
        <div class="actions" style="margin-top: 0.4rem;">
          <button :disabled="locating" @click="useCurrentLocation">
            {{ locating ? 'Locating…' : 'Use current location' }}
          </button>
          <button v-if="profile.home_latitude != null || profile.home_longitude != null"
                  @click="profile.home_latitude = null; profile.home_longitude = null; geocodedLabel = ''">
            Clear
          </button>
          <span v-if="locateError" class="err" style="font-size:0.8rem;">{{ locateError }}</span>
        </div>
      </fieldset>

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
    </section>

    <section v-show="activeTab === 'ai'" v-if="queryToken" class="settings-pane">
      <h2>AI summaries</h2>
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
          <span>Provider:</span>
          <select v-model="aiProvider">
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai_compatible">OpenAI-compatible</option>
            <option value="ollama">Ollama (local)</option>
          </select>
        </label>
        <label v-if="aiProvider !== 'anthropic'" class="ai-instructions">
          <span>Base URL</span>
          <input v-model="aiBaseUrl" type="url" class="add-search"
                 placeholder="http://ollama.lan:11434/v1"/>
          <div class="ai-instructions-foot">
            <span class="muted">
              Anthropic is the only provider with prompt caching, so switching
              away means every call pays full input rate — cheaper per token,
              more tokens billed. Small local models also produce noticeably
              worse structured output, which shows up as a card that renders
              thin or empty rather than as an error.
            </span>
          </div>
        </label>
        <div v-if="aiProviderDirty || aiProviderError" class="actions">
          <button class="ghost" :disabled="aiProviderSaving" @click="aiSaveProvider">
            {{ aiProviderSaving ? 'Saving…' : 'Save provider' }}
          </button>
          <span v-if="aiProviderError" class="err">{{ aiProviderError }}</span>
        </div>
        <label class="ai-instructions">
          <span>Standing instructions</span>
          <textarea
            v-model="aiInstructions"
            :maxlength="aiInstructionsMax"
            rows="4"
            placeholder="e.g. Rehabbing a left shoulder — never suggest overhead pressing. My fasts are religious; don't read a compressed HRV during one as overtraining."
          ></textarea>
          <div class="ai-instructions-foot">
            <span class="muted">
              {{ aiInstructions.length }}/{{ aiInstructionsMax }}
            </span>
            <span class="muted">
              Added to every AI card. Saving invalidates every cached
              summary, so expect one burst of re-billing.
            </span>
            <button class="ghost" :disabled="!aiInstructionsDirty || aiInstructionsSaving"
                    @click="aiSaveInstructions">
              {{ aiInstructionsSaving ? 'Saving…' : 'Save' }}
            </button>
            <span v-if="aiInstructionsSaved && !aiInstructionsDirty" class="saved">saved</span>
          </div>
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
    </section>

    <section v-show="activeTab === 'tools'" v-if="queryToken" class="settings-pane">
      <h2>Tools &amp; exports</h2>
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

    <section v-show="activeTab === 'imports'" v-if="queryToken" class="settings-pane">
      <h2>Historical imports</h2>
      <p class="hint">
        One-shot bulk loads from a downloaded provider archive — useful for back-filling
        years of data the watch doesn't have. Heart rate, sleep, steps and activities
        all get merged into the existing tables (duplicates are skipped).
      </p>
      <div class="imports">
        <div class="import-card">
          <strong>Fitbit / Google Health</strong>
          <p class="muted">
            The Fitbit app became <strong>Google Health</strong> on
            2026-05-19. Request your archive from
            <a href="https://takeout.google.com/" target="_blank" rel="noreferrer">takeout.google.com</a>
            (pick "Fitbit"). Legacy fitbit.com exports still work too.
            Upload the unmodified ZIP.
          </p>
          <div class="unit-row">
            <span class="muted">Weight unit in this archive:</span>
            <label><input type="radio" value="kg" v-model="fitbitWeightUnit"/> kg</label>
            <label><input type="radio" value="lb" v-model="fitbitWeightUnit"/> lb</label>
          </div>
          <button class="ghost" :disabled="!!importBusy" @click="pickImportFile('fitbit')">
            {{ importBusy === 'fitbit' ? 'Uploading…' : 'Upload Fitbit / Google Health ZIP' }}
          </button>
          <button class="ghost" :disabled="!!importBusy" @click="pickImportFile('fitbit_tracks')"
                  style="margin-top: 0.4rem;">
            Upload Fitbit ZIP (GPS maps)
          </button>
          <p class="muted" style="margin-top: 0.4rem; font-size: 0.75rem;">
            The GPS upload reads the Takeout's <code>gps_location</code> CSVs and adds ride maps to your Fitbit activities. Background job, watch progress below.
          </p>
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

        <div class="import-card">
          <strong>Strength log</strong>
          <p class="muted">
            Import lifting history from <em>Strong</em>, <em>Hevy</em>, or
            <em>FitNotes</em> (their CSV export). Sets, reps, weight, warmups and
            RPE come across; re-importing the same file skips duplicates.
            Exercises not in the catalog are kept by name.
          </p>
          <div class="strength-import-opts">
            <label>Format
              <select v-model="strengthSource">
                <option value="auto">Auto-detect</option>
                <option value="strong">Strong</option>
                <option value="hevy">Hevy</option>
                <option value="fitnotes">FitNotes</option>
              </select>
            </label>
            <label v-if="strengthSource === 'strong' || strengthSource === 'auto'">Strong weight unit
              <select v-model="strongUnit">
                <option value="kg">kg</option>
                <option value="lb">lb</option>
              </select>
            </label>
          </div>
          <button class="ghost" :disabled="strengthImportBusy" @click="pickStrengthFile">
            {{ strengthImportBusy ? 'Importing…' : 'Upload strength CSV' }}
          </button>
          <p class="muted" style="margin-top: 0.4rem; font-size: 0.78rem;">
            iPhone / Apple Health: strength workouts export without set data —
            export directly from Strong or Hevy instead.
          </p>
          <p v-if="strengthImportResult" class="ok" style="margin-top: 0.4rem;">{{ strengthImportResult }}</p>
          <p v-if="strengthImportError" class="err" style="margin-top: 0.4rem;"><small>{{ strengthImportError }}</small></p>
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

    <section v-show="activeTab === 'trails'" v-if="queryToken" class="settings-pane">
      <h2>Trail status (RainoutLine)</h2>
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
    </section>

    <section v-show="activeTab === 'strava'" class="settings-pane">
      <h2>Strava</h2>
      <div v-if="stravaError" class="err">{{ stravaError }}</div>

      <!-- Cookie-session ingest (SCS family) — Strava's June 2026
           policy paywalls OAuth API access on 2026-06-30. Cookie
           mode keeps free-tier users working. -->
      <div class="block">
        <!-- ═══ CONNECTED & HEALTHY — calm status, no form ═══ -->
        <template v-if="cookieStatus?.configured && !cookieStatus.needs_reconnect && !cookieEditing">
          <p class="ok-text">
            ✓ Connected as <strong>{{ cookieStatus.athlete_name ?? cookieStatus.athlete_id ?? "Strava" }}</strong><br/>
            <span class="muted">Last sync: {{ cookieStatus.last_sync_at ? fmt(cookieStatus.last_sync_at) : "never" }}</span>
            <span v-if="cookieStatus.auto_login_enabled" class="muted" style="display: block;">
              Auto-login on<span v-if="cookieStatus.last_auto_login_at"> · last refresh {{ fmt(cookieStatus.last_auto_login_at) }}</span>
            </span>
            <span v-if="cookieStatus.last_error" class="err" style="display: block;">
              Last error: {{ cookieStatus.last_error }}
            </span>
          </p>
          <div class="actions">
            <button class="primary" :disabled="cookieSyncing" @click="syncCookieNow">
              {{ cookieSyncing ? "Syncing…" : "Sync now" }}
            </button>
            <button v-if="cookieStatus.auto_login_enabled" class="ghost"
                    :disabled="cookieRefreshing" @click="refreshCookieNow">
              {{ cookieRefreshing ? "Refreshing…" : "Refresh cookie" }}
            </button>
            <button class="ghost" @click="cookieEditing = true">Update cookies</button>
            <button class="ghost danger" @click="disconnectCookie">Disconnect</button>
          </div>

          <details style="margin-top: 1rem;">
            <summary class="muted">Bulk import history</summary>
            <div class="form" style="margin-top: 0.6rem;">
              <label>
                <span>Days back</span>
                <input v-model.number="cookieBulkDays" type="number" min="1" max="3650" />
              </label>
              <label>
                <span>Limit <em class="opt">(blank = no limit)</em></span>
                <input v-model.number="cookieBulkLimit" type="number" min="1" max="1000" placeholder="e.g. 100" />
              </label>
              <div class="actions">
                <button class="primary" :disabled="cookieSyncing" @click="syncCookieBulk">
                  {{ cookieSyncing ? "Importing…" : `Bulk import (${cookieBulkDays}d)` }}
                </button>
              </div>
            </div>
          </details>
        </template>

        <!-- ═══ FRESH / RECONNECT / EDITING — the cookie paste box IS the lead ═══ -->
        <template v-else>
          <div v-if="cookieStatus?.needs_reconnect" class="reconnect-callout">
            <strong>⚠ Strava session expired</strong>
            <span class="muted" style="display:block;">Paste fresh cookies below to reconnect.</span>
            <span v-if="cookieStatus.last_error" class="muted" style="display:block;">{{ cookieStatus.last_error }}</span>
          </div>

          <!-- PRIMARY ACTION — un-nested, the first visible element -->
          <div class="form">
            <label>
              <span>Strava cookies</span>
              <textarea v-model="cookieBlobInput" rows="3"
                        placeholder='[{"name":"strava_remember_token","value":"…"}, {"name":"_strava4_session","value":"…"}]'
                        autocomplete="off" spellcheck="false"></textarea>
            </label>
            <p class="hint">
              Export with the <a href="https://cookie-editor.com/" target="_blank" rel="noreferrer">Cookie-Editor</a>
              extension and paste here — JSON, header string, or Netscape all work. No password needed.
            </p>
          </div>
          <div class="actions">
            <button class="primary" :disabled="cookieSaving" @click="saveCookie">
              {{ cookieSaving ? "Validating…" : "Save & test" }}
            </button>
            <button v-if="cookieEditing" class="ghost" @click="cookieEditing = false">Cancel</button>
          </div>

          <!-- SECONDARY — all collapsed, clearly labeled -->
          <details class="howto" :open="cookieHowtoOpen" @toggle="cookieHowtoOpen = ($event.target as HTMLDetailsElement).open">
            <summary class="muted">How to get your cookies</summary>
            <ol class="howto-steps">
              <li>Install <a href="https://cookie-editor.com/" target="_blank" rel="noreferrer">Cookie-Editor</a> (Chrome / Firefox / Edge / Safari).</li>
              <li>Sign in at <a href="https://www.strava.com/login" target="_blank" rel="noreferrer">strava.com</a> — any method (Google, emailed code, or password) works.</li>
              <li>Click the Cookie-Editor icon → <strong>Export</strong> → <strong>Export as JSON</strong> (copies to your clipboard).</li>
              <li>Paste it above and <strong>Save &amp; test</strong>.</li>
            </ol>
          </details>

          <details>
            <summary class="muted">Paste cookie values by hand (DevTools)</summary>
            <ol class="howto-steps">
              <li>At strava.com open DevTools (<kbd>F12</kbd> or <kbd>Cmd+Opt+I</kbd>) → Application → Cookies → <code>https://www.strava.com</code>.</li>
              <li>Copy <code>strava_remember_token</code> (long-lived), or <code>_strava4_session</code> as a fallback.</li>
            </ol>
            <div class="form">
              <label>
                <span>strava_remember_token <em class="opt">(long-lived)</em></span>
                <input v-model="cookieRememberInput" type="password" placeholder="long base64-ish string" autocomplete="off"/>
              </label>
              <label>
                <span>_strava4_session <em class="opt">(short-lived fallback)</em></span>
                <input v-model="cookieSidInput" type="password" placeholder="session cookie" autocomplete="off"/>
              </label>
            </div>
            <p class="hint">Then hit <strong>Save &amp; test</strong> above.</p>
          </details>

          <details>
            <summary class="muted">Email + password auto-login (password accounts only)</summary>
            <p class="hint" style="margin-top: 0.6rem;">
              Only if you sign in to Strava with an email + password (not Google
              / emailed code). Stored encrypted in your local DB; the backend
              re-runs the login when the cookie expires.
            </p>
            <div class="form">
              <label>
                <span>Strava email</span>
                <input v-model="cookieEmailInput" type="email"
                       placeholder="you@example.com" autocomplete="username"/>
              </label>
              <label>
                <span>Strava password</span>
                <input v-model="cookiePasswordInput" type="password"
                       placeholder="••••••••" autocomplete="current-password"/>
              </label>
              <label class="checkbox">
                <input v-model="cookieAutoLoginEnabled" type="checkbox"/>
                <span>Auto-refresh cookie when it expires</span>
              </label>
            </div>
          </details>

          <details>
            <summary class="muted">Why cookie mode?</summary>
            <p class="hint" style="margin-top: 0.6rem;">
              Strava paywalled its free OAuth API on <strong>2026-06-30</strong>.
              Cookie mode pulls rides straight from <code>strava.com</code> using
              your normal browser login — no subscription, and the chest-strap HR
              in each FIT comes through intact.
            </p>
          </details>
        </template>

        <div v-if="cookieResult" class="hint" style="margin-top: 0.6rem;">{{ cookieResult }}</div>
      </div>

      <!-- Legacy OAuth path — Strava paywalls it 2026-06-30; keep
           reachable for users on a paid Strava sub who prefer it. -->
      <div class="block">
        <details :open="showLegacyOAuth" @toggle="showLegacyOAuth = ($event.target as HTMLDetailsElement).open">
          <summary class="muted">Legacy: Strava OAuth (needs a paid Strava sub)</summary>
          <template v-if="strava && stravaConfig">
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

            <div v-if="stravaConfig.configured" style="margin-top: 0.8rem;">
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
        </details>
      </div>

    </section>

    <!-- ── Fasting preferences ── -->
    <section v-show="activeTab === 'fasting'" class="settings-pane">
      <h2>Fasting</h2>
      <p class="hint">
        Default protocol pre-selects on the Fasting page.
        Scheduled mode auto-starts and ends fasts at your eating-window
        boundaries (server-side, every 5 min). Manual start always wins
        over scheduled — if you start manually it stays active until you
        end it.
      </p>

      <label>
        <span>Default protocol</span>
        <select v-model="fastingDefaultProto">
          <option value="16:8">16:8 (16h fast, 8h eat)</option>
          <option value="18:6">18:6</option>
          <option value="20:4">20:4</option>
          <option value="omad">OMAD (23:1)</option>
          <option value="extended_24">24h fast</option>
          <option value="extended_36">36h fast</option>
          <option value="extended_48">48h fast</option>
          <option value="extended_72">72h fast</option>
        </select>
      </label>

      <label class="row-inline">
        <input type="checkbox" v-model="fastingScheduledMode"/>
        <span>Enable scheduled mode (auto start/end)</span>
      </label>

      <div class="window-row">
        <label>
          <span>Eating window starts</span>
          <select v-model.number="fastingEatStart" :disabled="!fastingScheduledMode">
            <option v-for="h in 24" :key="h-1" :value="h-1">{{ h-1 }}:00</option>
          </select>
        </label>
        <label>
          <span>and ends</span>
          <select v-model.number="fastingEatEnd" :disabled="!fastingScheduledMode">
            <option v-for="h in 24" :key="h" :value="h">{{ h }}:00</option>
          </select>
        </label>
      </div>

      <label class="row-inline">
        <input type="checkbox" v-model="fastingNotifs"/>
        <span>Milestone notifications on phone (ketosis, autophagy, ...)</span>
      </label>

      <label>
        <span>Religious calendar (auto-fasts on tradition dates)</span>
        <select v-model="fastingReligiousCal">
          <option value="none">None</option>
          <option value="ramadan">Ramadan (dawn-to-dusk fasts)</option>
          <option value="lent">Lent (40 days, abstinence-based)</option>
          <option value="yom_kippur">Yom Kippur (single 25h fast)</option>
        </select>
      </label>

      <div class="actions">
        <button class="primary" :disabled="fastingSaving" @click="saveFastingPrefs">
          {{ fastingSaving ? "Saving…" : "Save preferences" }}
        </button>
      </div>
      <div v-if="fastingMsg" class="hint">{{ fastingMsg }}</div>
    </section>

    <!-- ── Home Assistant ── -->
    <section v-show="activeTab === 'ha'" class="settings-pane">
      <h2>Home Assistant (watch status)</h2>
      <p class="hint">
        Pulls the Pixel Watch's on-body / battery / charger / activity
        signals from HA's WebSocket. HR, HRV, SpO2, sleep, skin temp
        all continue to come from Health Connect — the Wear OS
        Companion App's HR sensor publishes too sparsely to replace HC.
      </p>

      <div v-if="haError" class="err">{{ haError }}</div>

      <template v-if="haLoading && !haStatus">
        <p class="hint">Loading…</p>
      </template>

      <template v-else-if="haStatus">
        <p class="ok-text">
          <Check :size="14"/>
          <strong>{{ haStatus.online ? "Connected" : "Disconnected" }}</strong>
          —
          <span v-if="haAgeS !== null && haAgeS < 60">updated just now</span>
          <span v-else-if="haAgeS !== null && haAgeS < 3600">updated {{ Math.floor(haAgeS / 60) }}m ago</span>
          <span v-else-if="haAgeS !== null && haAgeS < 86400">updated {{ Math.floor(haAgeS / 3600) }}h ago</span>
          <span v-else-if="haAgeS !== null">updated {{ Math.floor(haAgeS / 86400) }}d ago</span>
        </p>
        <ul class="kv">
          <li><span>Battery</span><span>{{ haStatus.battery_pct ?? "—" }}%</span></li>
          <li><span>Charger</span><span>{{ haStatus.is_charging === null ? "—" : (haStatus.is_charging ? "Plugged in" : "Not charging") }}</span></li>
          <li><span>On body</span><span>{{ haStatus.is_worn === null ? "—" : (haStatus.is_worn ? "Yes" : "No") }}</span></li>
          <li><span>Activity</span><span>{{ haStatus.activity_state ?? "—" }}</span></li>
          <li><span>Device</span><span><code>{{ haStatus.device_id }}</code></span></li>
        </ul>
        <div class="actions">
          <button class="ghost" :disabled="haLoading" @click="loadHaStatus">
            {{ haLoading ? "Refreshing…" : "Refresh" }}
          </button>
        </div>
      </template>

      <template v-else>
        <p class="hint">
          No device_status rows yet — the WebSocket consumer either
          isn't configured or hasn't connected. Set the URL + token
          below and toggle realtime on.
        </p>
        <div class="actions">
          <button class="ghost" :disabled="haLoading" @click="loadHaStatus">
            {{ haLoading ? "Refreshing…" : "Refresh" }}
          </button>
        </div>
      </template>

      <!-- HA config form — stored in ha_config table, not .env -->
      <h3 class="sub">Config</h3>
      <label>
        <span>HA base URL</span>
        <input v-model="haCfgUrl" type="url" placeholder="http://10.x.x.x:8123" autocomplete="off"/>
      </label>
      <label>
        <span>Long-lived access token
          <span v-if="haCfgMasked" class="muted">(current: <code>{{ haCfgMasked }}</code>)</span>
        </span>
        <input v-model="haCfgToken" type="password"
               :placeholder="haCfgMasked ? 'leave blank to keep, paste to replace' : 'paste HA token'"
               autocomplete="off"/>
      </label>
      <label class="row-inline">
        <input type="checkbox" v-model="haCfgEnabled"/>
        <span>Enable realtime WebSocket consumer</span>
      </label>
      <p class="hint">
        Generate the token in HA → your profile → Security → Long-lived
        access tokens. Stored in the DB (never echoed back). HR / HRV /
        SpO2 / sleep continue to come from Health Connect.
      </p>
      <div class="actions">
        <button class="primary" :disabled="haCfgSaving" @click="saveHaConfig">
          {{ haCfgSaving ? "Saving…" : "Save HA config" }}
        </button>
      </div>
      <div v-if="haCfgMsg" class="hint">{{ haCfgMsg }}</div>
    </section>

    <!-- ── Concept2 ── -->
    <section v-show="activeTab === 'google'" class="settings-pane">
      <h2>
        Google Health
        <span v-if="ghStatus?.connected" class="badge-ok">connected</span>
      </h2>
      <p class="hint">
        A second route to your watch data that doesn't go through the phone.
        Right now the phone is the only path in for every stream, and two of
        them — SpO2 and skin temperature — have been dead since a Pixel Watch
        firmware update. Google's API serves both.
      </p>
      <p class="hint">
        Bring your own OAuth app, the same as Strava: create a project at
        <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">console.cloud.google.com</a>,
        enable the Google Health API, create an OAuth client of type "Web
        application", and add yourself as a test user. No verification is
        needed — that only applies above 100 users.
      </p>
      <p class="hint">
        <strong>Google will not accept a LAN address as the redirect URI.</strong>
        It requires a public domain over HTTPS, and <code>localhost</code> is
        its only exception — which is why the URI below is a loopback address
        that nothing is listening on. That is deliberate: it means this never
        has to be exposed to the internet. Google sends your browser there,
        the page fails to load, and the authorization code is sitting in the
        address bar for you to paste back in step 2.
      </p>

      <label class="ai-instructions">
        <span>Redirect URI (paste this into the Google console, exactly)</span>
        <input v-model="ghCallback" class="add-search" type="url"/>
      </label>
      <label class="ai-instructions">
        <span>Client ID</span>
        <input v-model="ghClientId" class="add-search" type="text"
               placeholder="…apps.googleusercontent.com"/>
      </label>
      <label class="ai-instructions">
        <span>Client secret <em class="opt" v-if="ghCfg?.client_secret_set">(saved — leave blank to keep)</em></span>
        <input v-model="ghClientSecret" class="add-search" type="password"
               autocomplete="off" placeholder="GOCSPX-…"/>
      </label>

      <div class="actions">
        <button class="ghost" :disabled="ghBusy" @click="ghSaveConfig">Save app credentials</button>
        <button class="primary" :disabled="ghBusy || !ghCfg?.configured" @click="ghConnect"
                :title="ghCfg?.configured ? '' : 'Save a client ID and secret first'">
          {{ ghStatus?.connected ? "Reconnect" : "1. Open Google consent" }}
        </button>
        <button class="ghost" :disabled="ghBusy || !ghStatus?.connected" @click="ghRunProbe">
          {{ ghBusy ? "Working…" : "What data is available?" }}
        </button>
        <button class="ghost" :disabled="ghBusy || !ghStatus?.connected" @click="ghSync(7)">Sync 7 days</button>
        <button class="ghost" :disabled="ghBusy || !ghStatus?.connected" @click="ghSync(90)">Backfill 90 days</button>
        <button class="ghost danger" v-if="ghStatus?.connected" @click="ghDisconnect">Disconnect</button>
      </div>

      <!-- Step 2 of the loopback flow. Only shown once the consent screen has
           been opened, so it does not read as a field to fill in first. -->
      <div v-if="ghAuthUrl" class="gh-paste">
        <p class="hint">
          A tab just opened for Google's consent screen. Approve it, then the
          browser will land on a <code>localhost</code> page that
          <strong>fails to load — that is expected</strong>. Copy the whole
          address from that tab's URL bar and paste it here.
        </p>
        <input v-model="ghPasteUrl" class="add-search" type="text"
               placeholder="http://localhost:8080/api/auth/google-health/callback?state=…&amp;code=…"/>
        <div class="actions">
          <button class="primary" :disabled="ghBusy || !ghPasteUrl.trim()" @click="ghFinish">
            2. Finish connecting
          </button>
          <a :href="ghAuthUrl" target="_blank" rel="noopener" class="hint">
            open the consent screen
          </a>
        </div>
        <p class="hint">
          The link expires after 15 minutes. If it does, press
          &ldquo;Open Google consent&rdquo; again for a fresh one.
        </p>
      </div>

      <p v-if="ghCfg && !ghCfg.configured" class="hint">
        <strong>Consent is disabled until a client secret is stored.</strong>
        <span v-if="ghCfg.client_id">
          The client ID is saved but the secret is not — paste it above and
          press Save. Leaving the secret blank on a later save keeps the
          stored one rather than clearing it.
        </span>
      </p>

      <p v-if="ghError" class="err">{{ ghError }}</p>
      <p v-if="ghResult" class="hint">{{ ghResult }}</p>
      <p v-if="ghStatus?.last_error" class="err">Last sync error: {{ ghStatus.last_error }}</p>

      <div v-if="ghStatus?.connected" class="kv">
        <span class="kv-label">Last sync</span>
        <span class="kv-value">{{ ghStatus.last_sync_at ?? "never" }}</span>
      </div>
      <label v-if="ghStatus?.connected" class="ai-toggle">
        <input type="checkbox" :checked="ghStatus.poll_enabled"
               @change="ghTogglePoll(($event.target as HTMLInputElement).checked)"/>
        <span>Pull automatically</span>
      </label>
      <label v-if="ghStatus?.connected && ghStatus.poll_enabled" class="ai-toggle">
        <span>Every:</span>
        <select :value="ghStatus.poll_interval_min"
                @change="ghSetInterval(Number(($event.target as HTMLSelectElement).value))">
          <option :value="15">15 min</option>
          <option :value="30">30 min</option>
          <option :value="60">1 hour</option>
          <option :value="180">3 hours</option>
          <option :value="720">12 hours</option>
        </select>
        <span class="muted" style="font-size:0.72rem">
          Overnight metrics only change once a night, so an hour is plenty
          for SpO2 and skin temperature — tighten it if you want steps to
          keep up. Google rate-limits, so 15 minutes is the floor.
        </span>
      </label>

      <!-- The probe is the honest answer to the one thing the docs can't
           tell us: whether YOUR account's Fitbit-sourced watch data actually
           reaches this API, and for which types. -->
      <div v-if="ghProbe" class="scroll-x">
        <table class="probe-table">
          <thead><tr><th>Data type</th><th>Last 7d</th><th>Status</th></tr></thead>
          <tbody>
            <tr v-for="t in ghProbe.types" :key="t.type">
              <td>
                <code>{{ t.type }}</code>
                <span v-if="t.ingested" class="adhoc-tag">ingested</span>
              </td>
              <td>{{ t.ok ? (t.points ?? 0) : "—" }}</td>
              <td>
                <span v-if="!t.ok" class="err">{{ t.error }}</span>
                <span v-else-if="(t.points ?? 0) > 0" class="ok">available</span>
                <span v-else class="muted">no data</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="ghProbe" class="hint">
        "no data" means Google served the type but your account has none in
        that window — for an overnight metric that usually just means the
        watch wasn't worn. An error here is the interesting case: it normally
        means the scope wasn't granted.
      </p>
    </section>

    <section v-show="activeTab === 'concept2'" class="settings-pane">
      <h2>Concept2 (rower)</h2>
      <div v-if="concept2Error" class="err">{{ concept2Error }}</div>

      <template v-if="concept2">
        <template v-if="concept2.connected">
          <p class="ok-text">
            <Check :size="14"/> Connected as
            <strong>{{ concept2.user_name ?? concept2.user_id }}</strong><br/>
            <span class="muted">Token: <code>{{ concept2.token_masked }}</code></span><br/>
            <span class="muted" v-if="concept2.last_sync_at">
              Last sync: {{ fmt(concept2.last_sync_at) }}
            </span>
            <span class="muted" v-else>Last sync: never</span>
          </p>
          <p v-if="concept2.webhook_path" class="hint">
            Optional — register this URL as a webhook in
            <a href="https://log.concept2.com/developers" target="_blank" rel="noreferrer">
              log.concept2.com/developers</a>
            to push results live (otherwise the cron poll picks them up
            within 30 min).<br/>
            <code>{{ webhookBase }}{{ concept2.webhook_path }}</code>
          </p>
          <div class="actions">
            <button class="primary" :disabled="concept2Saving" @click="syncConcept2(false)">
              {{ concept2Saving ? "Syncing…" : "Sync now" }}
            </button>
            <button class="ghost" :disabled="concept2Saving" @click="syncConcept2(true)">
              Backfill all-time
            </button>
            <button class="ghost danger" @click="disconnectConcept2">Disconnect</button>
          </div>
          <div v-if="concept2Result" class="hint">{{ concept2Result }}</div>
        </template>

        <template v-else>
          <p class="hint">
            Generate a long-lived personal token at
            <a href="https://log.concept2.com/developers" target="_blank" rel="noreferrer">
              log.concept2.com/developers</a>
            (scopes: <code>user:read,results:read</code>) and paste it here.
            Stored in the database, never echoed back.
          </p>
          <label>
            <span>Personal access token</span>
            <input v-model="concept2TokenInput" type="password"
                   placeholder="Concept2 token" autocomplete="off"/>
          </label>
          <div class="actions">
            <button class="primary" :disabled="concept2Saving" @click="saveConcept2">
              {{ concept2Saving ? "Validating…" : "Connect Concept2" }}
            </button>
          </div>
          <div v-if="concept2Result" class="hint">{{ concept2Result }}</div>
        </template>
      </template>

      <div v-else-if="!concept2Error" class="hint">Loading…</div>
    </section>
  </div>
</template>

<style scoped>
.settings { max-width: 800px; }
h1 { margin: 0 0 1rem; }
h2 { font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 1rem; display: flex; align-items: center; gap: 0.5rem; }

/* SETTINGS-1 — section panes; the section navigation lives in the
   main SideNav rail, not inside the Settings page. */
.settings-pane {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.1rem 1.2rem 1.4rem;
  margin-bottom: 1rem;
}
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
.kv { list-style: none; padding: 0; margin: 0.4rem 0; }
.kv li { display: flex; justify-content: space-between; padding: 0.25rem 0; border-bottom: 1px solid rgba(148, 163, 184, 0.1); font-size: 0.9rem; }
.kv li:last-child { border-bottom: none; }
.kv li > span:first-child { color: #94a3b8; }
.row-inline { display: flex; flex-direction: row; align-items: center; gap: 0.5rem; margin-bottom: 0.8rem; }
.row-inline input { width: auto; }
.window-row { display: flex; gap: 0.8rem; margin-bottom: 1rem; }
.window-row label { flex: 1; }
select { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem; font-size: 1rem; font-family: inherit; }
select:disabled { opacity: 0.5; }
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin-top: 0.6rem; }
.err small { color: #94a3b8; font-family: monospace; }
.reconnect-callout {
  padding: 0.6rem 0.8rem; margin-bottom: 0.8rem;
  background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444;
  border-radius: 4px; font-size: 0.9rem;
}
.reconnect-callout strong { color: #ef4444; }
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
.strength-import-opts { display: flex; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
.strength-import-opts label { display: flex; flex-direction: column; gap: 0.2rem;
  font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.strength-import-opts select { font-size: 0.85rem; padding: 0.25rem 0.4rem;
  border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); }
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

/* UPDATE-1: release check + apply controls */
.update-row {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 1rem; flex-wrap: wrap;
  margin-top: 0.4rem;
}
.update-versions {
  display: grid; grid-template-columns: auto auto;
  column-gap: 0.8rem; row-gap: 0.3rem;
  font-size: 0.85rem;
}
.update-versions .kv {
  display: contents; /* let the parent grid space columns */
}
.update-versions .kv-label { color: var(--muted); }
.update-versions .kv-value { color: var(--text); }
.update-versions .mono { font-family: ui-monospace, monospace; }
.release-link { color: #38bdf8; margin-left: 0.4rem; vertical-align: middle; }
.update-actions {
  display: flex; gap: 0.5rem; flex-wrap: wrap;
}
.update-actions button {
  display: inline-flex; align-items: center; gap: 0.35rem;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.release-notes {
  margin-top: 1rem;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.7rem 0.9rem;
}
.release-notes h3 {
  margin: 0 0 0.4rem; font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); font-weight: 600;
}
.release-notes pre {
  margin: 0; white-space: pre-wrap; font-family: inherit;
  font-size: 0.82rem; color: var(--text-soft);
  max-height: 240px; overflow: auto;
}
.badge-new {
  display: inline-block;
  background: rgba(56, 189, 248, 0.18); color: #38bdf8;
  border-radius: 4px;
  padding: 0.1rem 0.5rem;
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
  font-weight: 600;
  margin-left: 0.5rem;
  vertical-align: middle;
}
.badge-ok {
  display: inline-block;
  background: rgba(34, 197, 94, 0.14); color: #22c55e;
  border-radius: 4px;
  padding: 0.1rem 0.5rem;
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
  font-weight: 600;
  margin-left: 0.5rem;
  vertical-align: middle;
}
.cron-status {
  display: flex; align-items: center; gap: 0.5rem;
  margin-top: 1rem; padding-top: 0.7rem;
  border-top: 1px solid var(--border);
  font-size: 0.82rem;
}
.cron-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.cron-dot.ok  { background: #22c55e; box-shadow: 0 0 6px rgba(34, 197, 94, 0.45); }
.cron-dot.bad { background: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.45); }
.cron-text { color: var(--text); flex: 1; }
.cron-text .dim { color: var(--muted); margin-left: 0.25rem; font-size: 0.78rem; }
.cron-log {
  margin-top: 0.5rem; padding: 0.7rem;
  background: rgba(0, 0, 0, 0.25); border: 1px solid var(--border);
  border-radius: 6px;
  font-family: ui-monospace, monospace; font-size: 0.72rem;
  color: var(--text-soft);
  max-height: 280px; overflow: auto;
  white-space: pre-wrap;
}

/* Live apply progress card */
.apply-progress {
  margin-top: 0.9rem;
  padding: 0.9rem 1rem;
  background: rgba(56, 189, 248, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 8px;
}
.apply-progress.phase-done {
  background: rgba(34, 197, 94, 0.08);
  border-color: rgba(34, 197, 94, 0.35);
}
.apply-progress.phase-failed {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.35);
}
.apply-head {
  display: flex; align-items: center; gap: 0.55rem;
  font-size: 0.9rem; color: var(--text);
  margin-bottom: 0.7rem;
}
.apply-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #38bdf8; box-shadow: 0 0 6px rgba(56, 189, 248, 0.55);
  animation: pulse 1.4s ease-in-out infinite;
}
.apply-dot.phase-done { background: #22c55e; box-shadow: 0 0 6px rgba(34, 197, 94, 0.55); animation: none; }
.apply-dot.phase-failed { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.55); animation: none; }
.apply-phase-label { flex: 1; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
.apply-steps {
  list-style: none; padding: 0; margin: 0;
  display: flex; flex-direction: column; gap: 0.3rem;
  font-size: 0.82rem;
}
.apply-steps li {
  position: relative; padding-left: 1.3rem;
  color: var(--muted);
}
.apply-steps li::before {
  content: "○"; position: absolute; left: 0;
  color: #475569;
}
.apply-steps li.done { color: var(--text); }
.apply-steps li.done::before { content: "●"; color: #22c55e; }
.apply-steps li.current { color: #38bdf8; }
.apply-steps li.current::before { content: "●"; color: #38bdf8; }
.apply-tail {
  margin: 0.7rem 0 0; padding: 0.6rem;
  background: rgba(0, 0, 0, 0.3); border: 1px solid var(--border);
  border-radius: 6px;
  font-family: ui-monospace, monospace; font-size: 0.7rem;
  color: var(--text-soft);
  max-height: 180px; overflow: auto;
  white-space: pre-wrap;
}

/* ───────────────────────── Vitality Neon overrides ─────────────────────────
   Scoped to html[data-theme="neon"] so classic light/dark themes are byte-for-
   byte unchanged. Neon palette: cyan #28e6ff, magenta #ff3ad8, lime #5dff3b,
   amber #ffb52e, red #ff5d7a, periwinkle #6f7bff, track #272a3b, card #181b27,
   ink #ececf5, muted #9b9bb0. Reference idiom: Body.vue. */
html[data-theme="neon"] .settings {
  --rn-cyan: #28e6ff; --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-amber: #ffb52e;
  --rn-red: #ff5d7a; --rn-peri: #6f7bff; --rn-track: #272a3b;
  --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 32px 22px 40px;
  max-width: none;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
}
/* re-cap the content column the classic max-width used to give */
html[data-theme="neon"] .settings > * { max-width: 800px; }

/* Rounded neon cards + subtle inset highlight */
html[data-theme="neon"] .settings .settings-pane,
html[data-theme="neon"] .settings .import-card,
html[data-theme="neon"] .settings .release-notes {
  background: var(--rn-card);
  border: 1px solid #21243450;
  border-radius: 18px;
}
html[data-theme="neon"] .settings .settings-pane { box-shadow: inset 0 1px 0 #ffffff08; }

/* Big readouts → Space Grotesk numerics */
html[data-theme="neon"] .settings h1,
html[data-theme="neon"] .settings .update-versions .mono,
html[data-theme="neon"] .settings .derived,
html[data-theme="neon"] .settings .zone {
  font-family: 'Space Grotesk', 'Geist Mono', ui-monospace, monospace;
  letter-spacing: -0.3px;
}

/* Primary accent → cyan with glow */
html[data-theme="neon"] .settings .primary { background: var(--rn-cyan); color: #0f1118; }
html[data-theme="neon"] .settings input:focus,
html[data-theme="neon"] .settings select:focus { border-color: var(--rn-cyan); }
html[data-theme="neon"] .settings .hint a,
html[data-theme="neon"] .settings .release-link { color: var(--rn-cyan); }

/* HR-zone badges z1..z5 → periwinkle / cyan / lime / amber / red */
html[data-theme="neon"] .settings .zone-1 { background: rgba(111, 123, 255, 0.20); color: var(--rn-peri); }
html[data-theme="neon"] .settings .zone-2 { background: rgba(40, 230, 255, 0.18); color: var(--rn-cyan); }
html[data-theme="neon"] .settings .zone-3 { background: rgba(93, 255, 59, 0.18); color: var(--rn-lime); }
html[data-theme="neon"] .settings .zone-4 { background: rgba(255, 181, 46, 0.18); color: var(--rn-amber); }
html[data-theme="neon"] .settings .zone-5 { background: rgba(255, 93, 122, 0.20); color: var(--rn-red); }

/* OK / error state blocks */
html[data-theme="neon"] .settings .ok {
  color: var(--rn-lime); background: rgba(93, 255, 59, 0.10); border-left-color: var(--rn-lime);
}
html[data-theme="neon"] .settings .ok-text { color: var(--rn-lime); }
html[data-theme="neon"] .settings .err {
  color: var(--rn-red); background: rgba(255, 93, 122, 0.10); border-left-color: var(--rn-red);
}
html[data-theme="neon"] .settings .danger { color: var(--rn-red); }

/* Badges — "new" (cyan) / "ok" (lime) */
html[data-theme="neon"] .settings .badge-new { background: rgba(40, 230, 255, 0.18); color: var(--rn-cyan); }
html[data-theme="neon"] .settings .badge-ok  { background: rgba(93, 255, 59, 0.16); color: var(--rn-lime); }

/* Import-job status dots */
html[data-theme="neon"] .settings .dot-running { background: var(--rn-cyan); box-shadow: 0 0 8px var(--rn-cyan); }
html[data-theme="neon"] .settings .dot-done   { background: var(--rn-lime); box-shadow: 0 0 6px rgba(93, 255, 59, 0.55); }
html[data-theme="neon"] .settings .dot-failed { background: var(--rn-red); box-shadow: 0 0 6px rgba(255, 93, 122, 0.55); }
html[data-theme="neon"] .settings tr.job-running { background: rgba(40, 230, 255, 0.04); }
html[data-theme="neon"] .settings tr.job-failed  { background: rgba(255, 93, 122, 0.05); }

/* Cron status dots — ok → lime, bad → amber, both glowing */
html[data-theme="neon"] .settings .cron-dot.ok  { background: var(--rn-lime); box-shadow: 0 0 7px rgba(93, 255, 59, 0.55); }
html[data-theme="neon"] .settings .cron-dot.bad { background: var(--rn-amber); box-shadow: 0 0 7px rgba(255, 181, 46, 0.55); }

/* Live apply progress — phase tints + dots */
html[data-theme="neon"] .settings .apply-progress {
  background: rgba(40, 230, 255, 0.06); border-color: rgba(40, 230, 255, 0.25);
}
html[data-theme="neon"] .settings .apply-progress.phase-done {
  background: rgba(93, 255, 59, 0.08); border-color: rgba(93, 255, 59, 0.35);
}
html[data-theme="neon"] .settings .apply-progress.phase-failed {
  background: rgba(255, 93, 122, 0.08); border-color: rgba(255, 93, 122, 0.35);
}
html[data-theme="neon"] .settings .apply-dot {
  background: var(--rn-cyan); box-shadow: 0 0 6px rgba(40, 230, 255, 0.55);
}
html[data-theme="neon"] .settings .apply-dot.phase-done {
  background: var(--rn-lime); box-shadow: 0 0 6px rgba(93, 255, 59, 0.55);
}
html[data-theme="neon"] .settings .apply-dot.phase-failed {
  background: var(--rn-red); box-shadow: 0 0 6px rgba(255, 93, 122, 0.55);
}
html[data-theme="neon"] .settings .apply-steps li.done::before { color: var(--rn-lime); }
html[data-theme="neon"] .settings .apply-steps li.current,
html[data-theme="neon"] .settings .apply-steps li.current::before { color: var(--rn-cyan); }

/* TD-7 — settings section rail. Horizontal and scrollable rather than a
   second vertical column, because the panes below are already wide forms and
   this page is reached on a phone as often as on a desktop. */
.settings-rail {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 2px 0 10px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border);
  scrollbar-width: thin;
}
.rail-pill {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}
.rail-pill:hover { color: var(--text); }
.rail-pill.active {
  color: var(--accent-text, #0b1018);
  background: var(--accent);
  border-color: var(--accent);
}
.rail-pill:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* TD-9 — standing instructions editor. Full-width rather than the inline
   .ai-toggle row, because this is prose the user needs to read back before
   saving: it goes into every prompt and it is a prompt-injection surface. */
.ai-instructions { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; }
.ai-instructions textarea {
  width: 100%;
  font: inherit;
  font-size: 0.82rem;
  line-height: 1.45;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  resize: vertical;
}
.ai-instructions-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 0.72rem;
}
.ai-instructions-foot .muted:last-of-type { flex: 1 1 18rem; }

/* GH-1 — the probe result table. */
.scroll-x { overflow-x: auto; margin: 10px 0; }
.probe-table { border-collapse: collapse; width: 100%; font-size: 0.78rem; }
.probe-table th {
  text-align: left; color: var(--muted); font-weight: 600;
  padding: 4px 10px 4px 0; border-bottom: 1px solid var(--border);
}
.probe-table td { padding: 5px 10px 5px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
.probe-table .ok { color: var(--good); }

.gh-paste {
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 12px 14px;
  margin: 12px 0;
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}
</style>
