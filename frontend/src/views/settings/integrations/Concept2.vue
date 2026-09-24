<script setup lang="ts">
/**
 * SETTINGS-B2 — Concept2 (rower). Logic moved from the old Settings.vue
 * "concept2" pane: personal token connect, sync, all-time backfill,
 * webhook hint, disconnect (now behind a confirm dialog).
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { apiBase } from "@/config";
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

type Concept2Status = Awaited<ReturnType<typeof api.concept2Status>>;
const loading = ref(true);
const loadError = ref<string | null>(null);
const concept2 = ref<Concept2Status | null>(null);
const concept2Error = ref<string | null>(null);
const concept2TokenInput = ref("");
const concept2Saving = ref(false);
const concept2Result = ref("");
const webhookBase = computed(() => apiBase.value || window.location.origin);

async function loadConcept2(): Promise<void> {
  loadError.value = null;
  try { concept2.value = await api.concept2Status(); }
  catch (e) { loadError.value = errText(e); }
  finally { loading.value = false; }
}

async function saveConcept2() {
  const token = concept2TokenInput.value.trim();
  if (!token) { concept2Result.value = "Paste a token first."; return; }
  concept2Saving.value = true;
  concept2Result.value = "";
  concept2Error.value = null;
  try {
    const r = await api.concept2Connect(token);
    concept2.value = r as Concept2Status;
    concept2TokenInput.value = "";
    concept2Result.value = r.connected ? `Connected as ${r.user_name ?? r.user_id ?? "Concept2 user"}.` : "Saved.";
    emit("refresh-health");
  } catch (e) {
    concept2Error.value = errText(e);
  } finally { concept2Saving.value = false; }
}

const confirmDisconnect = ref(false);
async function disconnectConcept2() {
  confirmDisconnect.value = false;
  concept2Error.value = null;
  try {
    await api.concept2Disconnect();
    await loadConcept2();
    concept2Result.value = "Disconnected. Erg sessions already imported stay.";
    emit("refresh-health");
  } catch (e) {
    concept2Error.value = errText(e);
  }
}

async function syncConcept2(full: boolean) {
  concept2Saving.value = true;
  concept2Result.value = "";
  concept2Error.value = null;
  try {
    const r = await api.concept2Sync({ full });
    concept2Result.value = `Pulled ${r.upserted} session(s).`;
    await loadConcept2();
  } catch (e) {
    concept2Error.value = errText(e);
  } finally {
    concept2Saving.value = false;
    emit("refresh-health");
  }
}

onMounted(loadConcept2);
</script>

<template>
  <IntegrationHero :health="health" :loading="healthLoading" :error="healthError" @retry="emit('refresh-health')">
    <template #actions>
      <button v-if="concept2?.connected" class="btn primary" type="button" :disabled="concept2Saving"
              @click="syncConcept2(false)">
        {{ concept2Saving ? "Syncing…" : "Sync now" }}
      </button>
    </template>
  </IntegrationHero>

  <div v-if="loading" class="skel" aria-busy="true">
    <div class="sk tall"></div><span class="sr-only">Loading Concept2 settings…</span>
  </div>
  <button v-else-if="loadError && !concept2" class="errbar" type="button" @click="loading = true; loadConcept2()">
    <b>Couldn't load Concept2 settings</b><span>{{ loadError }}</span><em>Tap to retry</em>
  </button>

  <template v-else-if="concept2">
    <p v-if="concept2Error" class="msg warn" role="alert">{{ concept2Error }}</p>
    <p v-if="concept2Result" class="msg info" role="status">{{ concept2Result }}</p>

    <template v-if="concept2.connected">
      <NeonEyebrow>Connection</NeonEyebrow>
      <section class="card">
        <ul class="kv">
          <li><span>Connected as</span><span>{{ concept2.user_name ?? concept2.user_id }}</span></li>
          <li><span>Token</span><span><code>{{ concept2.token_masked }}</code></span></li>
          <li><span>Last sync</span><span>{{ concept2.last_sync_at ? fmtDateTime(concept2.last_sync_at) : "never" }}</span></li>
        </ul>
        <div class="actions">
          <button class="btn" type="button" :disabled="concept2Saving" @click="syncConcept2(true)">
            Backfill all-time history
          </button>
          <button class="btn danger" type="button" @click="confirmDisconnect = true">Disconnect</button>
        </div>
        <p v-if="concept2.webhook_path" class="hint">
          Optional — register this URL as a webhook in
          <a href="https://log.concept2.com/developers" target="_blank" rel="noreferrer">log.concept2.com/developers</a>
          to push results live (otherwise the scheduled poll picks them up within 30 minutes).<br />
          <code>{{ webhookBase }}{{ concept2.webhook_path }}</code>
        </p>
      </section>
    </template>

    <template v-else>
      <NeonEyebrow>Set up</NeonEyebrow>
      <section class="card">
        <p class="hint">
          Generate a long-lived personal token at
          <a href="https://log.concept2.com/developers" target="_blank" rel="noreferrer">log.concept2.com/developers</a>
          (scopes: <code>user:read,results:read</code>) and paste it here. Stored in the database, never echoed back.
        </p>
        <label class="field">
          <span>Personal access token</span>
          <input v-model="concept2TokenInput" type="password" placeholder="Concept2 token" autocomplete="off" />
        </label>
        <div class="actions">
          <button class="btn primary" type="button" :disabled="concept2Saving" @click="saveConcept2">
            {{ concept2Saving ? "Validating…" : "Connect Concept2" }}
          </button>
        </div>
      </section>
    </template>
  </template>

  <ConfirmDialog :open="confirmDisconnect" title="Disconnect Concept2?"
                 detail="Erg sessions already imported stay; the token is wiped, so syncing stops until you paste a new one."
                 confirm-label="Disconnect" @confirm="disconnectConcept2" @cancel="confirmDisconnect = false" />
</template>

<style scoped src="../settings-forms.css"></style>
