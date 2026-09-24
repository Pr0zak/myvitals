<script setup lang="ts">
/**
 * SETTINGS-B2 — Trail status (RainoutLine). Logic moved from the old
 * Settings.vue "trails" pane: the organisation's DNIS, a test poll, and
 * Clear (now behind a confirm dialog — clearing stops the trail board
 * updating).
 */
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import { fmtDateTime } from "@/format";
import type { IntegrationHealth } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import { errText } from "./health";

// Trail status is not in /query/data-health; declared so the parent's
// props don't fall through as attributes.
defineProps<{
  health?: IntegrationHealth | null;
  healthLoading?: boolean;
  healthError?: string | null;
}>();

const trailCfg = ref<{ dnis: string | null; configured: boolean; updated_at: string | null } | null>(null);
const loading = ref(true);
const loadError = ref<string | null>(null);
const saving = ref(false);
const testing = ref(false);
const dnisInput = ref("");
const result = ref("");
const resultOk = ref(true);

async function loadTrailCfg(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  try {
    trailCfg.value = await api.trailStatusConfig();
    dnisInput.value = trailCfg.value.dnis ?? "";
  } catch (e) {
    loadError.value = errText(e);
  } finally {
    loading.value = false;
  }
}

async function saveDnis(value: string | null) {
  saving.value = true;
  result.value = "";
  try {
    const r = await api.saveTrailStatusConfig(value);
    trailCfg.value = { ...r, updated_at: new Date().toISOString() };
    dnisInput.value = r.dnis ?? "";
    result.value = r.configured ? "Saved." : "Cleared.";
    resultOk.value = true;
  } catch (e) {
    result.value = `Save failed: ${errText(e)}`;
    resultOk.value = false;
  } finally { saving.value = false; }
}

const confirmClear = ref(false);
async function clearDnis() {
  confirmClear.value = false;
  await saveDnis(null);
}

async function testPoll() {
  testing.value = true;
  result.value = "";
  try {
    const r = await api.refreshTrails();
    result.value = r.skipped
      ? "Skipped — no DNIS saved."
      : `Polled: ${r.fetched} readings, ${r.snapshots} snapshots, ${r.alerts} alerts.`;
    resultOk.value = !r.skipped;
  } catch (e) {
    result.value = `Poll failed: ${errText(e)}`;
    resultOk.value = false;
  } finally { testing.value = false; }
}

onMounted(loadTrailCfg);
</script>

<template>
  <div v-if="loading && !trailCfg" class="skel" aria-busy="true">
    <div class="sk tall"></div><span class="sr-only">Loading trail status settings…</span>
  </div>
  <button v-else-if="loadError && !trailCfg" class="errbar" type="button" @click="loadTrailCfg">
    <b>Couldn't load trail status settings</b><span>{{ loadError }}</span><em>Tap to retry</em>
  </button>

  <template v-else-if="trailCfg">
    <NeonHero :accent="trailCfg.configured ? '#5dff3b' : '#28e6ff'">
      <span class="pill" :class="trailCfg.configured ? 'ok' : 'mut'">
        {{ trailCfg.configured ? "Set up" : "Not set up" }}
      </span>
      <ul class="kv">
        <li><span>Checks</span><span>every 15 minutes</span></li>
        <li v-if="trailCfg.updated_at"><span>Settings saved</span><span>{{ fmtDateTime(trailCfg.updated_at) }}</span></li>
      </ul>
      <div class="actions">
        <button v-if="trailCfg.configured" class="btn primary" type="button" :disabled="testing || saving" @click="testPoll">
          {{ testing ? "Checking…" : "Check now" }}
        </button>
      </div>
    </NeonHero>

    <NeonEyebrow>Your trail organisation</NeonEyebrow>
    <section class="card">
      <p class="hint">
        myvitals checks <a href="https://rainoutline.com/" target="_blank" rel="noreferrer">rainoutline.com</a> for
        trail-open / trail-closed status. Each organisation that uses RainoutLine has a 10-digit phone number (its
        “DNIS” — the number callers dial to hear the recording). Enter yours and the Trails page fills itself in.
      </p>
      <label class="field">
        <span>Organisation phone number <em>(10 digits)</em></span>
        <input v-model="dnisInput" placeholder="e.g. 9135550100" inputmode="numeric" autocomplete="off"
               :disabled="saving" />
      </label>
      <div class="actions">
        <button class="btn primary" type="button" :disabled="saving" @click="saveDnis(dnisInput.trim() || null)">
          {{ saving ? "Saving…" : (trailCfg.configured ? "Update" : "Save") }}
        </button>
        <button v-if="trailCfg.configured" class="btn danger" type="button" :disabled="saving"
                @click="confirmClear = true">Clear</button>
      </div>
    </section>
    <p v-if="result" class="msg" :class="resultOk ? 'ok' : 'warn'" role="status">{{ result }}</p>
  </template>

  <ConfirmDialog :open="confirmClear" title="Clear trail status?"
                 detail="The trail board stops updating until a number is saved again. Past readings stay."
                 confirm-label="Clear" @confirm="clearDnis" @cancel="confirmClear = false" />
</template>

<style scoped src="../settings-forms.css"></style>
