<script setup lang="ts">
/**
 * Settings → Connection & sync — SETTINGS-B1. Phone twin: `SettingsConnectionScreen.kt`.
 *
 *   sign-in   server address + access key, Save & test, Sign out
 *   phone     the phone's last sync, from `/query/data-health` `phone`
 *   health    the full data-health card, fed from the SAME response
 *
 * What changed from the old Access pane: "Clear" signed you out with no
 * confirmation and no hint that it would; the help text told you to paste
 * "the QUERY_TOKEN from the backend .env", which means nothing to anyone
 * who did not write the backend; and the data-health card was buried
 * under Display.
 *
 * The address and key stay in this browser only (localStorage), exactly
 * as before — nothing here changes where they are kept.
 */
import { computed, onMounted, ref } from "vue";
import { Eye, EyeOff } from "lucide-vue-next";
import { api } from "@/api/client";
import type { DataHealth } from "@/api/types";
import { apiBase, queryToken } from "@/config";
import { fmtDateTime } from "@/format";
import { useConfirm } from "@/useConfirm";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import DataHealthCard from "@/components/DataHealthCard.vue";
import SettingsToast from "@/components/settings/SettingsToast.vue";
import { useToast } from "@/components/settings/useToast";
import { relTime } from "./settingsText";
import "@/components/settings/settingsForm.css";

const keyInput = ref(queryToken.value);
const baseInput = ref(apiBase.value);
const keyVisible = ref(false);
const testing = ref(false);
const result = ref<"ok" | "fail" | null>(null);
const resultMsg = ref("");
const confirm = useConfirm();
const toast = useToast();

const changed = computed(() =>
  keyInput.value.trim() !== queryToken.value || baseInput.value.trim() !== apiBase.value);

const health = ref<DataHealth | null>(null);
const healthError = ref<string | null>(null);
const healthLoading = ref(!!queryToken.value);

async function loadHealth() {
  if (!queryToken.value) return;
  healthLoading.value = true;
  healthError.value = null;
  try {
    health.value = await api.dataHealth();
  } catch (e) {
    healthError.value = `Couldn't load sync status${e instanceof Error ? ` (${e.message})` : ""}.`;
  } finally {
    healthLoading.value = false;
  }
}
onMounted(loadHealth);

async function saveAndTest() {
  queryToken.value = keyInput.value.trim();
  apiBase.value = baseInput.value.trim();
  testing.value = true;
  result.value = null;
  resultMsg.value = "";
  try {
    await api.health();
    // /health is open; this one needs the key, so it proves the key works.
    await api.lastSync();
    result.value = "ok";
    toast.show("Connected");
    await loadHealth();
  } catch (e: unknown) {
    result.value = "fail";
    const r = (e as { response?: { status?: number } })?.response;
    if (r?.status === 401 || r?.status === 403) {
      resultMsg.value = "The server answered, but didn't accept this access key.";
    } else if (r) {
      resultMsg.value = `The server answered with an error (${r.status}).`;
    } else {
      resultMsg.value = "Couldn't reach the server at that address.";
    }
  } finally {
    testing.value = false;
  }
}

async function signOut() {
  const ok = await confirm.ask({
    title: "Sign out of this browser?",
    detail: "The access key and server address are removed from this browser. Nothing on the server "
      + "or your phone changes — you'll need the key again to sign back in.",
    confirmLabel: "Sign out",
  });
  if (!ok) return;
  queryToken.value = "";
  apiBase.value = "";
  keyInput.value = "";
  baseInput.value = "";
  result.value = null;
  health.value = null;
}

const phone = computed(() => health.value?.phone ?? null);
</script>

<template>
  <NeonPage title="Connection & sync" back="/settings">
    <NeonEyebrow>Your server</NeonEyebrow>
    <form class="sf-card" @submit.prevent="saveAndTest">
      <p class="sf-lede">
        Kept in this browser only — nothing here is sent anywhere except your own server.
      </p>
      <label class="sf-field">
        <span class="sf-label">Server address</span>
        <input v-model="baseInput" class="sf-input" type="url" inputmode="url" autocomplete="url"
               placeholder="Optional"
               aria-describedby="base-help" />
        <span id="base-help" class="sf-help">
          Only needed when this dashboard is opened from somewhere other than your server,
          e.g. <span class="sf-mono">http://my-server:8000</span>.
        </span>
      </label>
      <label class="sf-field key">
        <span class="sf-label">Access key</span>
        <span class="sf-inline">
          <input v-model="keyInput" class="sf-input sf-mono" :type="keyVisible ? 'text' : 'password'"
                 autocomplete="off" spellcheck="false" aria-describedby="key-help" />
          <button type="button" class="sf-btn icon" :aria-pressed="keyVisible"
                  :aria-label="keyVisible ? 'Hide access key' : 'Show access key'"
                  @click="keyVisible = !keyVisible">
            <component :is="keyVisible ? EyeOff : Eye" :size="18" aria-hidden="true" />
          </button>
        </span>
        <span id="key-help" class="sf-help">
          The private key your server was set up with. Whoever installed the server chose it and
          put it in the server's configuration; the phone app uses the same key.
        </span>
      </label>
      <div class="sf-actions">
        <button type="submit" class="sf-btn primary" :disabled="testing || !keyInput.trim()">
          {{ testing ? "Testing…" : "Save & test" }}
        </button>
        <button v-if="queryToken" type="button" class="sf-btn danger" @click="signOut">Sign out</button>
        <span v-if="changed && !testing" class="sf-mut">Not saved yet</span>
      </div>
      <p v-if="result === 'ok'" class="sf-ok" aria-live="polite">Connected — the server accepted this key.</p>
      <p v-if="result === 'fail'" class="sf-err" role="alert">{{ resultMsg }}</p>
    </form>

    <template v-if="queryToken">
      <NeonEyebrow>Phone</NeonEyebrow>
      <section class="sf-card" aria-live="polite">
        <div v-if="healthLoading && !health" class="sf-mut">Checking…</div>
        <div v-else-if="!phone" class="sf-err">
          {{ healthError ?? "Couldn't load sync status." }}
          <button type="button" class="sf-btn" @click="loadHealth">Retry</button>
        </div>
        <template v-else>
          <p v-if="phone.permissions_lost" class="sf-err perm" role="alert">
            Health Connect is refusing to share data with the app
            ({{ phone.perms_granted ?? "?" }} of {{ phone.perms_required ?? "?" }} permissions granted).
            On the phone, open Health Connect → App permissions → myvitals and turn each one off and on.
          </p>
          <div class="sf-kv">
            <span>Last successful sync</span>
            <span :title="phone.last_success ? fmtDateTime(phone.last_success) : undefined">
              {{ phone.last_success ? relTime(phone.last_success) : "Never" }}
            </span>
          </div>
          <div class="sf-kv">
            <span>Last attempt</span>
            <span :title="phone.last_attempt ? fmtDateTime(phone.last_attempt) : undefined">
              {{ phone.last_attempt ? relTime(phone.last_attempt) : "Never" }}
            </span>
          </div>
          <div v-if="phone.error_summary" class="sf-kv">
            <span>Last problem</span>
            <span class="sf-err">{{ phone.error_summary }}</span>
          </div>
          <div class="sf-kv">
            <span>Phone app version</span>
            <span class="sf-mono">{{ phone.app_version ?? "—" }}</span>
          </div>
        </template>
      </section>

      <NeonEyebrow>Data arriving</NeonEyebrow>
      <DataHealthCard v-if="health || !healthLoading" :data="health" :error="healthError" />
    </template>

    <SettingsToast :message="toast.message.value" />
    <ConfirmDialog :open="confirm.open.value" :title="confirm.request.value.title"
                   :detail="confirm.request.value.detail"
                   :confirm-label="confirm.request.value.confirmLabel"
                   @confirm="confirm.onConfirm" @cancel="confirm.onCancel" />
  </NeonPage>
</template>

<style scoped>
.key { margin-top: 14px; }
.perm { margin: 0 0 8px; }
.sf-card .sf-err { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
