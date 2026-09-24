<script setup lang="ts">
/**
 * Settings → About & updates — SETTINGS-B1. Phone twin: `SettingsAboutScreen.kt`.
 *
 * The old Updates pane, moved: running version, check for a release,
 * apply it (now behind a themed confirmation instead of `window.confirm`),
 * live apply phases read from the host's auto-update log, release notes,
 * and the auto-update cron's own log.
 *
 * It used to be the DEFAULT pane — so every visit to Settings called
 * GitHub, whatever you had come to change. It now loads only here.
 */
import { onMounted, onUnmounted, ref } from "vue";
import { AlertCircle, Check, Download, ExternalLink, RefreshCw } from "lucide-vue-next";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import { fmtDateTime } from "@/format";
import { useConfirm } from "@/useConfirm";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import "@/components/settings/settingsForm.css";

type UpdateCheck = Awaited<ReturnType<typeof api.updateCheck>>;
type UpdateStatus = Awaited<ReturnType<typeof api.updateStatus>>;
type Version = Awaited<ReturnType<typeof api.version>>;

const version = ref<Version | null>(null);
const updateInfo = ref<UpdateCheck | null>(null);
const updateChecking = ref(false);
const updateApplying = ref(false);
const updateApplyResult = ref("");
const updateApplyError = ref<string | null>(null);
const updateStatus = ref<UpdateStatus | null>(null);
const updateLogOpen = ref(false);
const confirm = useConfirm();

// Live apply progress — populated while the host cron is running the
// auto-update script. The phases map to recognisable lines in the
// auto-update.log so the UI can show a meaningful step-by-step,
// rather than just spinning until /version comes back.
type ApplyPhase = "idle" | "queued" | "pulling" | "recreating" | "verifying" | "done" | "failed";
const applyPhase = ref<ApplyPhase>("idle");
const applyProgress = ref<string[]>([]);
let applyPollHandle: ReturnType<typeof setInterval> | null = null;
let applyDeadline = 0;

const APPLY_PHASE_LABEL: Record<ApplyPhase, string> = {
  idle: "",
  queued: "Waiting for the server to pick up the update…",
  pulling: "Downloading the new version…",
  recreating: "Restarting with the new version…",
  verifying: "Checking the server came back healthy…",
  done: "Update complete.",
  failed: "Update failed.",
};
const STEPS: { key: ApplyPhase; label: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "pulling", label: "Download" },
  { key: "recreating", label: "Restart" },
  { key: "verifying", label: "Health check" },
  { key: "done", label: "Done" },
];
const ORDER: ApplyPhase[] = ["queued", "pulling", "recreating", "verifying", "done"];
function stepState(k: ApplyPhase): "done" | "current" | "todo" {
  const cur = ORDER.indexOf(applyPhase.value);
  const i = ORDER.indexOf(k);
  if (applyPhase.value === "done" || i < cur) return "done";
  return i === cur ? "current" : "todo";
}

function relAge(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

async function loadVersion() {
  try { version.value = await api.version(); } catch { version.value = null; }
}

async function loadUpdateStatus() {
  try {
    updateStatus.value = await api.updateStatus();
  } catch {
    updateStatus.value = null;
  }
}

async function checkUpdate() {
  updateChecking.value = true;
  updateApplyResult.value = "";
  updateApplyError.value = null;
  try {
    updateInfo.value = await api.updateCheck();
  } catch (e: unknown) {
    updateInfo.value = {
      current: version.value?.version ?? "?", latest: null, latest_tag: null, latest_url: null,
      latest_published_at: null, release_notes: null, update_available: false,
      error: e instanceof Error ? e.message : "check failed",
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
// phase. deploy/auto-update.sh emits these strings.
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
  const ok = await confirm.ask({
    title: `Apply v${updateInfo.value?.latest ?? "latest"}?`,
    detail: "The server restarts to install it, so the dashboard and phone sync are unavailable "
      + "for about 15 seconds. It rolls back on its own if the new version doesn't come up healthy.",
    confirmLabel: "Apply update",
    destructive: false,
  });
  if (!ok) return;
  updateApplying.value = true;
  updateApplyResult.value = "";
  updateApplyError.value = null;
  applyPhase.value = "queued";
  applyProgress.value = [];
  applyDeadline = Date.now() + 5 * 60_000;     // give up after 5 min
  const baselineTail = updateStatus.value?.tail?.join("\n") ?? "";

  try {
    const data = await api.updateApply();
    if (!data.triggered) {
      applyPhase.value = "failed";
      updateApplyError.value = data.hint ?? data.error ?? "The server didn't accept the update request.";
      updateApplying.value = false;
      return;
    }
  } catch (e: unknown) {
    applyPhase.value = "failed";
    updateApplyError.value = e instanceof Error ? e.message : "apply failed";
    updateApplying.value = false;
    return;
  }

  applyPollHandle = setInterval(async () => {
    if (Date.now() > applyDeadline) {
      stopApplyPoll();
      applyPhase.value = "failed";
      updateApplyError.value = "Timed out after 5 minutes. Check the update log on the server.";
      updateApplying.value = false;
      return;
    }
    await loadUpdateStatus();
    const status = updateStatus.value;
    if (!status) return;
    const tail = status.tail ?? [];
    if (tail.join("\n") === baselineTail) return;
    // Only the lines written after the trigger.
    const newLines = tail.slice(baselineTail.split("\n").length);
    if (newLines.length > 0) applyProgress.value = newLines;
    for (let i = newLines.length - 1; i >= 0; i--) {
      const phase = classifyLogLine(newLines[i]);
      if (phase) { applyPhase.value = phase; break; }
    }
    if (applyPhase.value === "done") {
      stopApplyPoll();
      updateApplyResult.value = "Update complete. Re-checking the version…";
      updateApplying.value = false;
      setTimeout(() => { void loadVersion(); void checkUpdate(); }, 1_500);
    } else if (applyPhase.value === "failed") {
      stopApplyPoll();
      updateApplyError.value = newLines[newLines.length - 1] ?? "Update failed.";
      updateApplying.value = false;
    }
  }, 2_000);
}

onMounted(() => {
  if (!queryToken.value) return;
  void loadVersion();
  void checkUpdate();
  void loadUpdateStatus();
});
onUnmounted(stopApplyPoll);
</script>

<template>
  <NeonPage title="About & updates" back="/settings">
    <p v-if="!queryToken" class="sf-mut">Sign in under Connection to see the server version.</p>

    <template v-else>
      <NeonHero :accent="updateInfo?.update_available ? '#28e6ff' : '#5dff3b'">
        <div class="ver-head">
          <div>
            <div class="ver-l">Server version</div>
            <div class="ver-v sf-mono">{{ version ? `v${version.version}` : updateInfo?.current ?? "—" }}</div>
          </div>
          <span v-if="updateInfo?.update_available" class="sf-chip">v{{ updateInfo.latest }} available</span>
          <span v-else-if="updateInfo && !updateInfo.error" class="sf-chip lime">Up to date</span>
        </div>
        <div v-if="version" class="sf-help build">
          Build {{ version.git_sha?.slice(0, 7) || "—" }}
          <template v-if="version.build_time"> · {{ version.build_time }}</template>
        </div>
      </NeonHero>

      <section class="sf-card">
        <div class="sf-kv">
          <span>Latest release</span>
          <span class="sf-mono">
            {{ updateInfo?.latest ? `v${updateInfo.latest}` : "—" }}
            <a v-if="updateInfo?.latest_url" :href="updateInfo.latest_url" target="_blank" rel="noopener"
               class="rel-link" aria-label="Open the release page on GitHub">
              <ExternalLink :size="13" aria-hidden="true" />
            </a>
          </span>
        </div>
        <div v-if="updateInfo?.latest_published_at" class="sf-kv">
          <span>Published</span>
          <span>{{ fmtDateTime(updateInfo.latest_published_at) }}</span>
        </div>
        <div class="sf-actions">
          <button type="button" class="sf-btn" :disabled="updateChecking" @click="checkUpdate">
            <RefreshCw :size="16" :class="{ spin: updateChecking }" aria-hidden="true" />
            {{ updateChecking ? "Checking…" : "Check for updates" }}
          </button>
          <button v-if="updateInfo?.update_available" type="button" class="sf-btn primary"
                  :disabled="updateApplying" @click="applyUpdate">
            <Download :size="16" aria-hidden="true" />
            {{ updateApplying ? "Applying…" : `Apply v${updateInfo.latest}` }}
          </button>
        </div>
        <p v-if="updateInfo?.error" class="sf-err" role="alert">
          Couldn't check for a new release: {{ updateInfo.error }}
        </p>
      </section>

      <section v-if="applyPhase !== 'idle'" class="sf-card apply" aria-live="polite"
               :class="`phase-${applyPhase}`">
        <div class="apply-head">
          <strong>{{ APPLY_PHASE_LABEL[applyPhase] }}</strong>
          <RefreshCw v-if="updateApplying" :size="15" class="spin" aria-hidden="true" />
        </div>
        <ol class="steps">
          <li v-for="st in STEPS" :key="st.key" :class="stepState(st.key)"
              :aria-current="stepState(st.key) === 'current' ? 'step' : undefined">{{ st.label }}</li>
        </ol>
        <pre v-if="applyProgress.length" class="sf-pre">{{ applyProgress.join('\n') }}</pre>
        <p v-if="updateApplyResult" class="sf-ok"><Check :size="14" aria-hidden="true" /> {{ updateApplyResult }}</p>
        <p v-if="updateApplyError" class="sf-err" role="alert">
          <AlertCircle :size="14" aria-hidden="true" /> {{ updateApplyError }}
        </p>
      </section>

      <template v-if="updateInfo?.release_notes">
        <NeonEyebrow>What's new</NeonEyebrow>
        <section class="sf-card">
          <pre class="notes">{{ updateInfo.release_notes }}</pre>
        </section>
      </template>

      <!-- Only when the backend can see the host's auto-update log. -->
      <template v-if="updateStatus?.log_present">
        <NeonEyebrow>Automatic updates</NeonEyebrow>
        <section class="sf-card">
          <div class="cron">
            <span class="cron-dot" :class="updateStatus.cron_healthy ? 'ok' : 'warn'" aria-hidden="true"></span>
            <span>
              {{ updateStatus.cron_healthy ? "Running" : "Stalled" }}
              <span class="sf-mut">· last activity {{ relAge(updateStatus.stale_seconds) }}</span>
              <span v-if="updateStatus.trigger_pending" class="sf-mut"> · update queued</span>
            </span>
            <button type="button" class="sf-btn" :aria-expanded="updateLogOpen" aria-controls="cron-log"
                    @click="updateLogOpen = !updateLogOpen">
              {{ updateLogOpen ? "Hide log" : "View log" }}
            </button>
          </div>
          <pre v-if="updateLogOpen && updateStatus.tail?.length" id="cron-log"
               class="sf-pre">{{ updateStatus.tail.join('\n') }}</pre>
        </section>
      </template>
    </template>

    <ConfirmDialog :open="confirm.open.value" :title="confirm.request.value.title"
                   :detail="confirm.request.value.detail"
                   :confirm-label="confirm.request.value.confirmLabel"
                   :destructive="confirm.request.value.destructive ?? true"
                   @confirm="confirm.onConfirm" @cancel="confirm.onCancel" />
  </NeonPage>
</template>

<style scoped>
.ver-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.ver-l { font-size: 12px; color: #9b9bb0; }
.ver-v { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; }
.build { margin-top: 6px; }
.rel-link { color: #28e6ff; margin-left: 6px; display: inline-flex; min-width: 24px; min-height: 24px;
  align-items: center; justify-content: center; }
.rel-link:focus-visible { outline: 2px solid #28e6ff; border-radius: 6px; }
.apply-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.apply.phase-done { border-color: rgba(93, 255, 59, .4); }
.apply.phase-failed { border-color: rgba(255, 181, 46, .45); }
.steps { list-style: none; padding: 0; margin: 12px 0 0; display: flex; flex-wrap: wrap; gap: 6px; }
.steps li { font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid #23263a; color: #9b9bb0; }
.steps li.done { color: #5dff3b; border-color: rgba(93, 255, 59, .35); }
.steps li.current { color: #28e6ff; border-color: rgba(40, 230, 255, .5); }
.notes { white-space: pre-wrap; word-break: break-word; font: inherit; font-size: 13.5px; line-height: 1.55;
  margin: 0; color: #ececf5; }
.cron { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 14px; }
.cron > span:nth-child(2) { flex: 1; min-width: 160px; }
.cron-dot { width: 9px; height: 9px; border-radius: 50%; }
.cron-dot.ok { background: #5dff3b; box-shadow: 0 0 7px rgba(93, 255, 59, .55); }
.cron-dot.warn { background: #ffb52e; box-shadow: 0 0 7px rgba(255, 181, 46, .55); }
.sf-ok, .sf-err { display: flex; align-items: center; gap: 6px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
