<script setup lang="ts">
/**
 * SETTINGS-B2 — Avinox (e-bike ride tracker).
 *
 * Direct integration with Avinox server (CT 246):
 * - Live push webhook: Avinox pushes completed rides directly into myvitals.
 * - On-demand sync / backfill: pull rides directly from Avinox API.
 * - Ingests e-bike metrics: motor power, cadence, assist levels, battery, torque.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { apiBase } from "@/config";
import { fmtDateTime } from "@/format";
import type { IntegrationHealth, AvinoxStatus } from "@/api/types";
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
const status = ref<AvinoxStatus | null>(null);

const serverUrlInput = ref("http://avinox.lan:8000");
const queryTokenInput = ref("");
const autoSync = ref(true);
const savingConfig = ref(false);
const syncInProgress = ref(false);
const actionResult = ref("");
const actionOk = ref(true);

const webhookUrl = computed(() => {
  const base = apiBase.value || window.location.origin;
  return `${base}/integrations/avinox/push`;
});

async function loadStatus(): Promise<void> {
  loadError.value = null;
  try {
    const s = await api.avinoxStatus();
    status.value = s;
    if (s.server_url) serverUrlInput.value = s.server_url;
    if (s.auto_sync_enabled !== undefined) autoSync.value = s.auto_sync_enabled;
  } catch (e) {
    loadError.value = errText(e);
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  savingConfig.value = true;
  actionResult.value = "";
  try {
    const s = await api.avinoxConfig({
      server_url: serverUrlInput.value.trim() || undefined,
      query_token: queryTokenInput.value.trim() || undefined,
      auto_sync_enabled: autoSync.value,
    });
    status.value = s;
    actionResult.value = "Settings saved.";
    actionOk.value = true;
    emit("refresh-health");
  } catch (e) {
    actionResult.value = `Failed to save: ${errText(e)}`;
    actionOk.value = false;
  } finally {
    savingConfig.value = false;
  }
}

async function syncNow(full: boolean = false) {
  syncInProgress.value = true;
  actionResult.value = "";
  try {
    const res = await api.avinoxSync({ full });
    actionResult.value = `Sync complete: scanned ${res.scanned}, upserted ${res.upserted} ride(s).`;
    actionOk.value = true;
    await loadStatus();
    emit("refresh-health");
  } catch (e) {
    actionResult.value = `Sync failed: ${errText(e)}`;
    actionOk.value = false;
  } finally {
    syncInProgress.value = false;
  }
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text);
  actionResult.value = "Copied to clipboard.";
  actionOk.value = true;
}

onMounted(loadStatus);
</script>

<template>
  <IntegrationHero :health="health" :loading="healthLoading" :error="healthError" @retry="emit('refresh-health')">
    <template #actions>
      <button class="btn primary" type="button" :disabled="syncInProgress" @click="syncNow(false)">
        {{ syncInProgress ? "Syncing…" : "Sync now" }}
      </button>
      <button class="btn ghost" type="button" :disabled="syncInProgress" @click="syncNow(true)">
        Backfill all
      </button>
    </template>
  </IntegrationHero>

  <p v-if="actionResult" class="notice" :class="actionOk ? 'ok' : 'err'" role="status">
    {{ actionResult }}
  </p>

  <section class="card">
    <NeonEyebrow style="margin-top: 0">Avinox server sync</NeonEyebrow>
    <p class="hint">
      Avinox tracks rides directly from your phone through wireless debugging and stores full e-bike telemetry.
      Configure the Avinox server URL on your home network to pull rides on demand.
    </p>

    <div class="form-row">
      <label class="field-label" for="avinox-url">Server address</label>
      <input id="avinox-url" v-model="serverUrlInput" type="text" class="input" placeholder="http://avinox.lan:8000" />
    </div>

    <div class="form-row">
      <label class="field-label" for="avinox-token">X-Query-Token (optional)</label>
      <input id="avinox-token" v-model="queryTokenInput" type="password" class="input" placeholder="Leave empty if query token is disabled" />
    </div>

    <div class="row-actions">
      <button class="btn primary" type="button" :disabled="savingConfig" @click="saveConfig">
        {{ savingConfig ? "Saving…" : "Save configuration" }}
      </button>
    </div>
  </section>

  <section class="card">
    <NeonEyebrow style="margin-top: 0">Live push webhook</NeonEyebrow>
    <p class="hint">
      When a ride finishes uploading on your Avinox server, it can push immediately to myvitals.
      Set <code>MYVITALS_URL</code> on your Avinox server to enable push:
    </p>

    <div class="webhook-box">
      <span class="mono">{{ webhookUrl }}</span>
      <button class="btn small ghost" type="button" @click="copyToClipboard(webhookUrl)">Copy</button>
    </div>

    <div class="stats-grid">
      <div class="stat-box">
        <span class="dim">Total rides</span>
        <span class="big-num mono">{{ status?.total_rides ?? 0 }}</span>
      </div>
      <div class="stat-box">
        <span class="dim">Last push</span>
        <span class="mono">{{ status?.last_push_at ? fmtDateTime(status.last_push_at) : "None" }}</span>
      </div>
      <div class="stat-box">
        <span class="dim">Last pull</span>
        <span class="mono">{{ status?.last_sync_at ? fmtDateTime(status.last_sync_at) : "None" }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hint { color: var(--text-dim); font-size: 0.9rem; margin-bottom: 1rem; line-height: 1.4; }
.form-row { margin-bottom: 1rem; display: flex; flex-direction: column; gap: 0.4rem; }
.field-label { font-size: 0.85rem; color: var(--text-dim); }
.input {
  background: var(--surface-2, #1a1e2e);
  border: 1px solid var(--line, #2d3548);
  border-radius: 6px;
  color: var(--text, #f0f4fc);
  padding: 0.6rem 0.8rem;
  font-family: inherit;
  font-size: 0.95rem;
}
.row-actions { margin-top: 1rem; }
.notice {
  padding: 0.75rem 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}
.notice.ok { background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.4); color: #4ade80; }
.notice.err { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #f87171; }
.webhook-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface-2, #1a1e2e);
  border: 1px solid var(--line, #2d3548);
  padding: 0.6rem 0.8rem;
  border-radius: 6px;
  margin-bottom: 1.2rem;
  word-break: break-all;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}
.stat-box {
  background: var(--surface-2, #1a1e2e);
  padding: 0.8rem;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.big-num { font-size: 1.4rem; font-weight: bold; color: var(--text); }
</style>
