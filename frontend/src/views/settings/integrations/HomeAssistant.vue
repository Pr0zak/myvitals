<script setup lang="ts">
/**
 * SETTINGS-B2 — Home Assistant (watch status). Logic moved from the old
 * Settings.vue "ha" pane, with the D3 fix:
 *
 *   `loadHaStatus` fetched `/device-status/latest` and `/ha-config` in one
 *   Promise.all. When the status request failed the whole load failed, the
 *   config never seeded the form, it showed blank — and pressing Save then
 *   wrote that blank form back, including `realtime_enabled: false`,
 *   switching off a working consumer.
 *
 * Now the two load independently. "No rows yet" (a 404 from the status
 * endpoint, surfaced by the client as null) is a neutral "no watch status
 * yet", never an error. Save is only offered once the saved config has
 * actually loaded, and it sends only the fields the user changed. A
 * "Disconnected" state is amber with no check mark next to it.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { IntegrationHealth } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import { errText } from "./health";

// Declared so the shared parent's props don't fall through as attributes;
// Home Assistant is not in /query/data-health, so they are unused here.
defineProps<{
  health?: IntegrationHealth | null;
  healthLoading?: boolean;
  healthError?: string | null;
}>();

type DeviceStatus = Awaited<ReturnType<typeof api.deviceStatusLatest>>;
type HaConfig = Awaited<ReturnType<typeof api.haConfigGet>>;

// Status: undefined = not answered yet, null = answered "no rows yet".
const haStatus = ref<DeviceStatus | undefined>(undefined);
const statusLoading = ref(true);
const statusError = ref<string | null>(null);

const cfg = ref<HaConfig | null>(null);
const cfgLoading = ref(true);
const cfgError = ref<string | null>(null);

const haCfgUrl = ref("");
const haCfgToken = ref("");   // empty = keep existing
const haCfgEnabled = ref(false);
const haCfgSaving = ref(false);
const haCfgMsg = ref("");
const haCfgMsgOk = ref(true);

const haAgeS = computed<number | null>(() => {
  const ts = haStatus.value?.time;
  if (!ts) return null;
  return Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
});
const ageText = computed(() => {
  const s = haAgeS.value;
  if (s === null) return "";
  if (s < 60) return "updated just now";
  if (s < 3600) return `updated ${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `updated ${Math.floor(s / 3600)} h ago`;
  return `updated ${Math.floor(s / 86400)} days ago`;
});

const online = computed(() => haStatus.value?.online ?? null);
const heroAccent = computed(() => {
  if (statusError.value) return "#ffb52e";
  if (online.value === true) return "#5dff3b";
  if (online.value === false) return "#ffb52e";
  return "#28e6ff";
});

async function loadStatus(deviceId?: string): Promise<void> {
  statusLoading.value = true;
  statusError.value = null;
  try {
    haStatus.value = await api.deviceStatusLatest(deviceId);
  } catch (e) {
    statusError.value = errText(e);
  } finally {
    statusLoading.value = false;
  }
}

function seedForm(c: HaConfig) {
  cfg.value = c;
  haCfgUrl.value = c.url ?? "";
  haCfgEnabled.value = c.realtime_enabled;
}

async function loadConfig(): Promise<void> {
  cfgLoading.value = true;
  cfgError.value = null;
  try {
    seedForm(await api.haConfigGet());
  } catch (e) {
    cfgError.value = errText(e);
  } finally {
    cfgLoading.value = false;
  }
}

async function loadAll(): Promise<void> {
  // Independent on purpose — see the header comment.
  await Promise.allSettled([loadConfig(), loadStatus()]);
  // The status call defaults to the stock device id; ask again for a
  // configured one only when it differs.
  const dev = cfg.value?.device_id;
  if (dev && dev !== "pixel_watch_3") await loadStatus(dev);
}

const dirty = computed(() => !!cfg.value && (
  haCfgUrl.value.trim() !== (cfg.value.url ?? "")
  || haCfgToken.value !== ""
  || haCfgEnabled.value !== cfg.value.realtime_enabled
));

async function saveHaConfig() {
  if (!cfg.value) return;   // never save a form that was not seeded from the server
  haCfgSaving.value = true;
  haCfgMsg.value = "";
  try {
    const body: Parameters<typeof api.haConfigPut>[0] = {};
    const url = haCfgUrl.value.trim();
    // Omitting a field keeps the stored value; "" clears it.
    if (url !== (cfg.value.url ?? "")) body.url = url;
    if (haCfgEnabled.value !== cfg.value.realtime_enabled) body.realtime_enabled = haCfgEnabled.value;
    if (haCfgToken.value !== "") body.token = haCfgToken.value;
    await api.haConfigPut(body);
    haCfgToken.value = "";   // never keep it in memory
    haCfgMsg.value = "Saved. The realtime connection restarts with the new settings.";
    haCfgMsgOk.value = true;
    await loadConfig();
    await loadStatus(cfg.value?.device_id);
  } catch (e) {
    haCfgMsg.value = `Save failed: ${errText(e)}`;
    haCfgMsgOk.value = false;
  } finally {
    haCfgSaving.value = false;
  }
}

const confirmClearToken = ref(false);
async function clearToken() {
  confirmClearToken.value = false;
  haCfgSaving.value = true;
  haCfgMsg.value = "";
  try {
    await api.haConfigPut({ token: "" });
    haCfgMsg.value = "Token cleared. Watch status stops updating until a new token is saved.";
    haCfgMsgOk.value = true;
    await loadConfig();
  } catch (e) {
    haCfgMsg.value = `Clear failed: ${errText(e)}`;
    haCfgMsgOk.value = false;
  } finally {
    haCfgSaving.value = false;
  }
}

onMounted(loadAll);
</script>

<template>
  <NeonHero :accent="heroAccent">
    <div v-if="statusLoading && haStatus === undefined" class="skel" aria-busy="true">
      <div class="sk"></div><span class="sr-only">Loading watch status…</span>
    </div>
    <button v-else-if="statusError" class="errbar" type="button" @click="loadStatus(cfg?.device_id)">
      <b>Couldn't load watch status</b><span>{{ statusError }}</span><em>Tap to retry</em>
    </button>
    <template v-else-if="haStatus">
      <div class="head">
        <span class="pill" :class="online === true ? 'ok' : online === false ? 'warn' : 'mut'">
          {{ online === true ? "Connected" : online === false ? "Disconnected" : "Status unknown" }}
        </span>
        <span class="mut small">{{ ageText }}</span>
      </div>
      <div class="stats">
        <NeonStat :value="haStatus.battery_pct != null ? `${haStatus.battery_pct}%` : '—'" label="Battery" />
        <NeonStat :value="haStatus.is_charging === null ? '—' : (haStatus.is_charging ? 'Plugged in' : 'No')" label="Charging" />
        <NeonStat :value="haStatus.is_worn === null ? '—' : (haStatus.is_worn ? 'Yes' : 'No')" label="On wrist" />
      </div>
      <ul class="kv">
        <li><span>Activity</span><span>{{ haStatus.activity_state ?? "—" }}</span></li>
        <li><span>Device</span><span><code>{{ haStatus.device_id }}</code></span></li>
      </ul>
    </template>
    <template v-else>
      <!-- 404 from the status endpoint: nothing recorded yet. Neutral. -->
      <p class="msg info">
        No watch status yet. The realtime connection either isn't set up or hasn't connected — set the URL and token
        below and switch realtime on.
      </p>
    </template>
    <div class="actions">
      <button class="btn" type="button" :disabled="statusLoading" @click="loadStatus(cfg?.device_id)">
        {{ statusLoading ? "Refreshing…" : "Refresh" }}
      </button>
    </div>
  </NeonHero>

  <p class="hint">
    Pulls the Pixel Watch's on-body / battery / charger / activity signals from Home Assistant's WebSocket. Heart
    rate, HRV, SpO2, sleep and skin temperature all keep coming from Health Connect.
  </p>

  <NeonEyebrow>Connection settings</NeonEyebrow>
  <div v-if="cfgLoading && !cfg" class="skel" aria-busy="true">
    <div class="sk tall"></div><span class="sr-only">Loading Home Assistant settings…</span>
  </div>
  <!-- Without the saved config there is no form: saving a blank one is
       exactly how the old page wiped a working setup. -->
  <button v-else-if="cfgError && !cfg" class="errbar" type="button" @click="loadConfig">
    <b>Couldn't load the saved settings</b><span>{{ cfgError }}</span><em>Tap to retry</em>
  </button>
  <section v-else-if="cfg" class="card">
    <label class="field">
      <span>Home Assistant address</span>
      <input v-model="haCfgUrl" type="url" placeholder="http://homeassistant.local:8123" autocomplete="off" />
    </label>
    <label class="field">
      <span>Long-lived access token
        <em v-if="cfg.token_masked">(saved: <code>{{ cfg.token_masked }}</code> — leave blank to keep)</em>
      </span>
      <input v-model="haCfgToken" type="password" autocomplete="off"
             :placeholder="cfg.token_masked ? 'paste to replace' : 'paste token'" />
    </label>
    <label class="check">
      <input v-model="haCfgEnabled" type="checkbox" />
      <span>Realtime connection on</span>
    </label>
    <p class="hint">
      Create the token in Home Assistant → your profile → Security → Long-lived access tokens. Stored in the
      database and never shown again.
    </p>
    <div class="actions">
      <button class="btn primary" type="button" :disabled="haCfgSaving || !dirty" @click="saveHaConfig">
        {{ haCfgSaving ? "Saving…" : "Save" }}
      </button>
      <button v-if="cfg.token_masked" class="btn danger" type="button" :disabled="haCfgSaving"
              @click="confirmClearToken = true">Clear token</button>
    </div>
    <p v-if="haCfgMsg" class="msg" :class="haCfgMsgOk ? 'ok' : 'warn'" role="status">{{ haCfgMsg }}</p>
  </section>

  <ConfirmDialog :open="confirmClearToken" title="Clear the Home Assistant token?"
                 detail="Watch status stops updating until a new token is saved."
                 confirm-label="Clear" @confirm="clearToken" @cancel="confirmClearToken = false" />
</template>

<style scoped src="../settings-forms.css"></style>
<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.small { font-size: 12px; }
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.stats :deep(.ns-v) { font-size: 17px; }
</style>
