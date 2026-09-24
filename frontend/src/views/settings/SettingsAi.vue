<script setup lang="ts">
/**
 * SETTINGS-B2 — AI. Logic moved from the old Settings.vue "ai" pane.
 *
 * Two behaviour changes worth knowing:
 *
 * 1. Only the SELECTED provider's credential is shown. The old pane always
 *    showed the Anthropic API key field, including under `claude_cli`,
 *    where pasting a key there is actively harmful (an API key makes the
 *    CLI bill per token — the thing that provider exists to avoid).
 *    OpenAI-compatible endpoints reuse the stored API key as a bearer, so
 *    that provider shows base URL + key; Ollama shows base URL only.
 *
 * 2. Autosaved controls (on/off, weekly digest, model, tone, daily limit)
 *    are bound to LOCAL state. On a failed save the control reverts to the
 *    server's value and a message says it was not saved. They used to be
 *    `:checked`/`:value` bound to the server object with the error
 *    swallowed, which left the control showing a setting that was never
 *    stored.
 */
import { computed, onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { errText } from "./integrations/health";

type AiCfg = Awaited<ReturnType<typeof api.aiConfig>>;
type Provider = AiCfg["provider"];
type Tone = AiCfg["tone"];

const cfg = ref<AiCfg | null>(null);
const loading = ref(true);
const loadError = ref<string | null>(null);

const PROVIDER_LABEL: Record<Provider, string> = {
  anthropic: "Anthropic (Claude API)",
  claude_cli: "Claude subscription (CLI, no API cost)",
  openai_compatible: "OpenAI-compatible endpoint",
  ollama: "Ollama (local)",
};

// SA-C10: multipliers against current per-token API pricing. `cliSub` is
// shown under claude_cli, where every model bills $0 and the honest
// trade-off is latency / rate-limit budget, not dollars.
const AI_MODELS = [
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5",
    sub: "cheapest, fastest — recommended for structured summaries",
    cliSub: "fastest, lightest on your subscription's rate limit — recommended for structured summaries" },
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6",
    sub: "stronger reasoning, ~3× the cost of Haiku",
    cliSub: "stronger reasoning, a heavier call against your subscription's rate limit than Haiku" },
  { id: "claude-opus-4-7", label: "Opus 4.7",
    sub: "deepest analysis, ~1.7× Sonnet — overkill for daily reads",
    cliSub: "deepest analysis, the heaviest call against your subscription's rate limit — overkill for daily reads" },
];

// ── Autosaved controls — local state, reverted on failure ──
const enabled = ref(false);
const weekly = ref(false);
const model = ref("");
const tone = ref<Tone>("supportive");
const limit = ref<number>(30);
const saving = reactive<Record<string, boolean>>({});
const saveErr = reactive<Record<string, string>>({});

function seedControls(c: AiCfg) {
  enabled.value = c.enabled;
  weekly.value = c.weekly_digest_enabled;
  model.value = c.model;
  tone.value = c.tone;
  limit.value = c.daily_call_limit;
}

// ── Provider (explicit save, with the loaded-snapshot dirty check) ──
const aiProvider = ref<Provider>("anthropic");
const aiBaseUrl = ref("");
const aiProviderSaving = ref(false);
const aiProviderError = ref("");
/** The last provider values the SERVER confirmed. Dirtiness is measured
 *  against this snapshot, taken BEFORE deciding whether to reseed, so a
 *  refresh can neither discard an unsaved draft nor mis-read a fresh load
 *  as dirty (the bug that showed "Anthropic" while the server held
 *  claude_cli, then wrote it back). */
const aiProviderLoaded = ref<{ provider: Provider; base_url: string }>({ provider: "anthropic", base_url: "" });
const aiProviderDirty = computed(
  () => aiProvider.value !== aiProviderLoaded.value.provider
    || aiBaseUrl.value.trim() !== aiProviderLoaded.value.base_url,
);

// ── Standing instructions (TD-9) ──
const aiInstructions = ref("");
const aiInstructionsSaving = ref(false);
const aiInstructionsSaved = ref(false);
const aiInstructionsError = ref("");
const aiInstructionsMax = computed(() => cfg.value?.custom_instructions_max ?? 1000);
const aiInstructionsDirty = computed(() => aiInstructions.value !== (cfg.value?.custom_instructions ?? ""));

async function loadAiCfg(): Promise<void> {
  loadError.value = null;
  try {
    const wasInstrDirty = cfg.value !== null && aiInstructionsDirty.value;
    const wasProviderDirty = cfg.value !== null && aiProviderDirty.value;
    const c = await api.aiConfig();
    cfg.value = c;
    seedControls(c);
    if (!wasInstrDirty) aiInstructions.value = c.custom_instructions ?? "";
    aiProviderLoaded.value = { provider: c.provider ?? "anthropic", base_url: c.base_url ?? "" };
    if (!wasProviderDirty) {
      aiProvider.value = aiProviderLoaded.value.provider;
      aiBaseUrl.value = aiProviderLoaded.value.base_url;
    }
  } catch (e) {
    loadError.value = errText(e);
  } finally {
    loading.value = false;
  }
}

async function autosave(field: string, patch: Parameters<typeof api.aiUpdateConfig>[0]) {
  saving[field] = true;
  saveErr[field] = "";
  try {
    await api.aiUpdateConfig(patch);
    await loadAiCfg();
  } catch (e) {
    if (cfg.value) seedControls(cfg.value);   // put the control back to what is stored
    saveErr[field] = `Couldn't save — ${errText(e)}. The setting was not changed.`;
  } finally {
    saving[field] = false;
  }
}

function saveLimit() {
  const n = limit.value;
  if (!Number.isFinite(n) || n < 1) {
    if (cfg.value) limit.value = cfg.value.daily_call_limit;
    saveErr.limit = "The limit must be at least 1. The setting was not changed.";
    return;
  }
  autosave("limit", { daily_call_limit: Math.floor(n) });
}

function saveModel() {
  const m = model.value.trim();
  if (!m) { if (cfg.value) model.value = cfg.value.model; return; }
  if (m === cfg.value?.model) return;
  autosave("model", { model: m });
}

const modelSub = computed(() => {
  const m = AI_MODELS.find((x) => x.id === cfg.value?.model);
  if (!m) return "";
  return cfg.value?.provider === "claude_cli" ? m.cliSub : m.sub;
});
/** Claude model ids only make sense for the two Claude providers; the
 *  others name whatever model the endpoint serves. */
const claudeModels = computed(() => aiProviderLoaded.value.provider === "anthropic"
  || aiProviderLoaded.value.provider === "claude_cli");
const modelInList = computed(() => AI_MODELS.some((m) => m.id === model.value));

async function aiSaveProvider() {
  aiProviderSaving.value = true;
  aiProviderError.value = "";
  try {
    await api.aiUpdateConfig({ provider: aiProvider.value, base_url: aiBaseUrl.value.trim() });
    // Clear the snapshot guard so the reload reseeds from the server.
    aiProviderLoaded.value = { provider: aiProvider.value, base_url: aiBaseUrl.value.trim() };
    await loadAiCfg();
  } catch (e) {
    // The server validates the URL on write so the message lands here.
    aiProviderError.value = errText(e);
  } finally {
    aiProviderSaving.value = false;
  }
}

// ── API key (anthropic; reused as bearer by OpenAI-compatible) ──
const aiKeyInput = ref("");
const aiKeyVisible = ref(false);
const aiKeyMsg = ref("");
const aiKeyOk = ref(true);
async function aiSaveKey() {
  if (!aiKeyInput.value.trim()) return;
  aiKeyMsg.value = "";
  try {
    await api.aiUpdateConfig({ anthropic_api_key: aiKeyInput.value.trim() });
    aiKeyInput.value = "";
    await loadAiCfg();
    aiKeyMsg.value = "Key saved."; aiKeyOk.value = true;
  } catch (e) { aiKeyMsg.value = `Save failed: ${errText(e)}`; aiKeyOk.value = false; }
}
const confirmClearKey = ref(false);
async function aiClearKey() {
  confirmClearKey.value = false;
  try {
    await api.aiUpdateConfig({ clear_key: true });
    await loadAiCfg();
    aiKeyMsg.value = "Key cleared."; aiKeyOk.value = true;
  } catch (e) { aiKeyMsg.value = `Clear failed: ${errText(e)}`; aiKeyOk.value = false; }
}

// ── CLI OAuth token (claude_cli) — its own save button, never rides along ──
const aiCliToken = ref("");
const aiCliSaving = ref(false);
const aiCliError = ref("");
const aiCliSaved = ref(false);
const confirmClearCli = ref(false);
async function aiSaveCliToken(clear = false) {
  confirmClearCli.value = false;
  aiCliSaving.value = true;
  aiCliError.value = "";
  aiCliSaved.value = false;
  try {
    await api.aiUpdateConfig(clear ? { clear_cli_token: true } : { cli_oauth_token: aiCliToken.value.trim() });
    aiCliToken.value = "";
    await loadAiCfg();
    aiCliSaved.value = true;
    setTimeout(() => (aiCliSaved.value = false), 2500);
  } catch (e) {
    aiCliError.value = errText(e);
  } finally {
    aiCliSaving.value = false;
  }
}

async function aiSaveInstructions() {
  aiInstructionsSaving.value = true;
  aiInstructionsSaved.value = false;
  aiInstructionsError.value = "";
  try {
    await api.aiUpdateConfig({ custom_instructions: aiInstructions.value.trim() });
    const c = await api.aiConfig();
    cfg.value = c;
    aiInstructions.value = c.custom_instructions ?? "";
    aiInstructionsSaved.value = true;
  } catch (e) {
    aiInstructionsError.value = `Save failed: ${errText(e)}. Your text is still here.`;
  } finally {
    aiInstructionsSaving.value = false;
  }
}

// ── Payload preview (web-only) — SA-O1. Must stay in step with
// PREVIEW_SURFACES in backend/src/myvitals/api/ai.py. ──
const AI_PREVIEW_SURFACES: { value: string; label: string }[] = [
  { value: "summary", label: "Weekly / monthly summary" },
  { value: "topic", label: "Topic read (sleep / recovery / sober / anomaly)" },
  { value: "verdict", label: "One-line daily verdict" },
  { value: "ask", label: "Ask a question" },
  { value: "deload", label: "Deload-trigger judgment" },
  { value: "focus_cue", label: "Pre-workout focus cue" },
  { value: "strength_nudge", label: "Variety nudge (exercise swaps)" },
  { value: "strength_review", label: "Post-workout review" },
  { value: "cardio_coach", label: "Cardio coach" },
  { value: "sleep_coach", label: "Sleep coach" },
  { value: "recovery_coach", label: "Recovery coach" },
  { value: "fasting_coach", label: "Fasting coach" },
  { value: "workout_coach", label: "Workout coach" },
  { value: "meal_suggestion", label: "Meal suggestion" },
  { value: "prep_plan", label: "Weekly prep planner" },
  { value: "meals_identify", label: "Pantry photo identify (uploads a photo, not JSON)" },
  { value: "meals_read_label", label: "Nutrition-label scan (uploads a photo, not JSON)" },
];
const aiPreviewSurface = ref("summary");
const aiPreviewRange = ref<"week" | "month">("week");
const aiPreviewTopic = ref<"sleep" | "recovery" | "sober" | "anomaly">("sleep");
const aiPreviewQuestion = ref("");
const aiPreviewing = ref(false);
const aiPreviewJson = ref("");
const aiPreviewNote = ref("");
const aiPreviewError = ref("");

async function aiPreview() {
  aiPreviewing.value = true; aiPreviewJson.value = ""; aiPreviewNote.value = ""; aiPreviewError.value = "";
  try {
    const data = await api.aiPreviewPayload({
      surface: aiPreviewSurface.value,
      range: aiPreviewRange.value,
      topic: aiPreviewTopic.value,
      question: aiPreviewQuestion.value.trim() || undefined,
    });
    if (data && data.is_payload === false) aiPreviewNote.value = (data.note as string) ?? "";
    else aiPreviewJson.value = JSON.stringify(data, null, 2);
  } catch (e) {
    aiPreviewError.value = `Preview failed: ${errText(e)}`;
  } finally { aiPreviewing.value = false; }
}

onMounted(loadAiCfg);
</script>

<template>
  <NeonPage title="AI" back="/settings">
    <p class="sub">Summaries, coach cards and meal suggestions.</p>

    <div v-if="loading && !cfg" class="skel" aria-busy="true">
      <div class="sk tall"></div><div class="sk"></div><div class="sk"></div>
      <span class="sr-only">Loading AI settings…</span>
    </div>
    <button v-else-if="loadError && !cfg" class="errbar" type="button" @click="loading = true; loadAiCfg()">
      <b>Couldn't load AI settings</b><span>{{ loadError }}</span><em>Tap to retry</em>
    </button>

    <template v-else-if="cfg">
      <NeonHero :accent="enabled ? '#28e6ff' : '#9b9bb0'">
        <label class="check big">
          <input v-model="enabled" type="checkbox" :disabled="saving.enabled"
                 @change="autosave('enabled', { enabled })" />
          <span>AI features {{ enabled ? "on" : "off" }}</span>
        </label>
        <p v-if="saveErr.enabled" class="msg warn" role="alert">{{ saveErr.enabled }}</p>
        <div class="stats">
          <NeonStat :value="`${cfg.calls_today} / ${cfg.daily_call_limit}`" label="Calls today" />
          <NeonStat :value="PROVIDER_LABEL[cfg.provider ?? 'anthropic'].split(' (')[0]" label="Provider" />
        </div>
        <p class="hint">
          Claude reads pre-aggregated stats only — no raw heart-rate samples, GPS, or sober history dates leave your
          server. Use the preview at the bottom to see exactly what one surface sends.
        </p>
      </NeonHero>

      <NeonEyebrow>Provider</NeonEyebrow>
      <section class="card">
        <label class="field">
          <span>Which service answers</span>
          <select v-model="aiProvider">
            <option v-for="(label, p) in PROVIDER_LABEL" :key="p" :value="p">{{ label }}</option>
          </select>
        </label>

        <template v-if="aiProvider === 'openai_compatible' || aiProvider === 'ollama'">
          <label class="field">
            <span>Base URL</span>
            <input v-model="aiBaseUrl" type="url" placeholder="http://ollama.lan:11434/v1" />
          </label>
          <p class="hint">
            Anthropic is the only provider with prompt caching, so switching away means every call pays full input
            rate. Small local models also produce noticeably worse structured output, which shows up as a card that
            renders thin or empty rather than as an error.
          </p>
        </template>

        <div v-if="aiProviderDirty || aiProviderError" class="actions">
          <button class="btn primary" type="button" :disabled="aiProviderSaving" @click="aiSaveProvider">
            {{ aiProviderSaving ? "Saving…" : "Save provider" }}
          </button>
          <button v-if="aiProviderDirty" class="btn" type="button" :disabled="aiProviderSaving"
                  @click="aiProvider = aiProviderLoaded.provider; aiBaseUrl = aiProviderLoaded.base_url">Cancel</button>
        </div>
        <p v-if="aiProviderError" class="msg warn" role="alert">{{ aiProviderError }}</p>
        <p v-if="aiProviderDirty" class="msg info">
          Not saved yet — AI calls still go to {{ PROVIDER_LABEL[aiProviderLoaded.provider] }}.
        </p>

        <!-- Only the chosen provider's credential. -->
        <template v-if="aiProvider === 'anthropic' || aiProvider === 'openai_compatible'">
          <label class="field">
            <span>
              {{ aiProvider === "anthropic" ? "Anthropic API key" : "API key (sent as a bearer token; optional)" }}
              <em>{{ cfg.api_key_set ? `saved: ${cfg.api_key_masked}` : "not set" }}</em>
            </span>
            <span class="keyrow">
              <input v-model="aiKeyInput" :type="aiKeyVisible ? 'text' : 'password'" autocomplete="off"
                     :placeholder="aiProvider === 'anthropic' ? 'sk-ant-… (paste a new key to replace)' : 'paste a key to replace'" />
              <button class="btn" type="button" :aria-label="aiKeyVisible ? 'Hide key' : 'Show key'"
                      :aria-pressed="aiKeyVisible" @click="aiKeyVisible = !aiKeyVisible">
                {{ aiKeyVisible ? "Hide" : "Show" }}
              </button>
            </span>
          </label>
          <div class="actions">
            <button class="btn primary" type="button" :disabled="!aiKeyInput.trim()" @click="aiSaveKey">Save key</button>
            <button v-if="cfg.api_key_set" class="btn danger" type="button" @click="confirmClearKey = true">Clear key</button>
          </div>
          <p v-if="aiKeyMsg" class="msg" :class="aiKeyOk ? 'ok' : 'warn'" role="status">{{ aiKeyMsg }}</p>
        </template>

        <template v-else-if="aiProvider === 'claude_cli'">
          <label class="field">
            <span>CLI sign-in token <em>{{ cfg.cli_token_set ? `saved: ${cfg.cli_token_masked}` : "not set" }}</em></span>
            <input v-model="aiCliToken" type="password" autocomplete="off"
                   placeholder="sk-ant-oat01-… (from `claude setup-token`)" />
          </label>
          <p v-if="cfg.cli_token_set && !cfg.cli_token_looks_valid" class="msg warn">
            The stored value does not look like a Claude OAuth token — those begin <code>sk-ant-oat</code>. Anything
            else is rejected with “401 Invalid bearer token” when a card is generated.
          </p>
          <div class="actions">
            <button class="btn primary" type="button" :disabled="aiCliSaving || !aiCliToken.trim()"
                    @click="aiSaveCliToken(false)">{{ aiCliSaving ? "Saving…" : "Save token" }}</button>
            <button v-if="cfg.cli_token_set" class="btn danger" type="button" :disabled="aiCliSaving"
                    @click="confirmClearCli = true">Clear token</button>
          </div>
          <p v-if="aiCliSaved" class="msg ok" role="status">Saved.</p>
          <p v-if="aiCliError" class="msg warn" role="alert">{{ aiCliError }}</p>
          <p class="hint">
            Runs <code>claude -p</code> inside the backend container on your Claude <strong>subscription</strong>, so
            calls cost nothing per token — they draw on the subscription's rate limit instead. Leave the token blank to
            use the credentials mounted from the host's <code>~/.claude</code>. Trade-offs: no schema-constrained
            output (a malformed reply is retried once and can still render a thin card), roughly 14k tokens of agent
            overhead per cold call (quota, not money), and higher latency. Any API key is deliberately withheld from
            it — a key would make it bill per token.
          </p>
        </template>

        <p v-else class="hint">Ollama needs no key.</p>
      </section>

      <NeonEyebrow>How it answers</NeonEyebrow>
      <section class="card">
        <label class="field">
          <span>Model</span>
          <select v-if="claudeModels" v-model="model" :disabled="saving.model" @change="saveModel">
            <option v-if="!modelInList" :value="model">{{ model }}</option>
            <option v-for="m in AI_MODELS" :key="m.id" :value="m.id">{{ m.label }}</option>
          </select>
          <input v-else v-model="model" type="text" :disabled="saving.model" placeholder="e.g. llama3.1:8b"
                 @change="saveModel" />
        </label>
        <p v-if="claudeModels && modelSub" class="hint">{{ modelSub }}</p>
        <p v-if="saveErr.model" class="msg warn" role="alert">{{ saveErr.model }}</p>

        <label class="field">
          <span>Tone</span>
          <select v-model="tone" :disabled="saving.tone" @change="autosave('tone', { tone })">
            <option value="supportive">Supportive</option>
            <option value="blunt">Blunt</option>
            <option value="data-only">Data only</option>
          </select>
        </label>
        <p v-if="saveErr.tone" class="msg warn" role="alert">{{ saveErr.tone }}</p>

        <label class="field">
          <span>Daily call limit <em>used {{ cfg.calls_today }} of {{ cfg.daily_call_limit }} today</em></span>
          <input v-model.number="limit" type="number" min="1" max="200" :disabled="saving.limit" @change="saveLimit" />
        </label>
        <p v-if="saveErr.limit" class="msg warn" role="alert">{{ saveErr.limit }}</p>

        <label class="check">
          <input v-model="weekly" type="checkbox" :disabled="saving.weekly"
                 @change="autosave('weekly', { weekly_digest_enabled: weekly })" />
          <span>Weekly digest (Sunday 22:00)</span>
        </label>
        <p v-if="saveErr.weekly" class="msg warn" role="alert">{{ saveErr.weekly }}</p>
      </section>

      <NeonEyebrow>Standing instructions</NeonEyebrow>
      <section class="card">
        <label class="field">
          <span>Added to every AI card</span>
          <textarea v-model="aiInstructions" :maxlength="aiInstructionsMax" rows="4"
                    placeholder="e.g. Rehabbing a left shoulder — never suggest overhead pressing. My fasts are religious; don't read a compressed HRV during one as overtraining."></textarea>
        </label>
        <p class="hint">
          {{ aiInstructions.length }}/{{ aiInstructionsMax }} · Saving invalidates every cached summary, so expect one
          burst of new calls.
        </p>
        <div class="actions">
          <button class="btn primary" type="button" :disabled="!aiInstructionsDirty || aiInstructionsSaving"
                  @click="aiSaveInstructions">{{ aiInstructionsSaving ? "Saving…" : "Save instructions" }}</button>
          <span v-if="aiInstructionsSaved && !aiInstructionsDirty" class="msg ok" role="status">Saved.</span>
        </div>
        <p v-if="aiInstructionsError" class="msg warn" role="alert">{{ aiInstructionsError }}</p>
      </section>

      <NeonEyebrow>What gets sent</NeonEyebrow>
      <section class="card">
        <label class="field">
          <span>AI surface</span>
          <select v-model="aiPreviewSurface">
            <option v-for="s in AI_PREVIEW_SURFACES" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>
        <label v-if="aiPreviewSurface === 'summary'" class="field">
          <span>Range</span>
          <select v-model="aiPreviewRange">
            <option value="week">Week (7 days)</option>
            <option value="month">Month (30 days)</option>
          </select>
        </label>
        <label v-if="aiPreviewSurface === 'topic'" class="field">
          <span>Topic</span>
          <select v-model="aiPreviewTopic">
            <option value="sleep">Sleep</option>
            <option value="recovery">Recovery</option>
            <option value="sober">Sober</option>
            <option value="anomaly">Anomaly</option>
          </select>
        </label>
        <label v-if="aiPreviewSurface === 'ask'" class="field">
          <span>Question <em>(optional)</em></span>
          <input v-model="aiPreviewQuestion" type="text" placeholder="e.g. How has my sleep trended?" />
        </label>
        <div class="actions">
          <button class="btn" type="button" :disabled="aiPreviewing" @click="aiPreview">
            {{ aiPreviewing ? "Loading…" : "Preview payload" }}
          </button>
        </div>
        <p v-if="aiPreviewError" class="msg warn" role="alert">{{ aiPreviewError }}</p>
        <p v-if="aiPreviewNote" class="hint">{{ aiPreviewNote }}</p>
        <pre v-if="aiPreviewJson" class="preview" tabindex="0" aria-label="Payload preview">{{ aiPreviewJson }}</pre>
      </section>
    </template>

    <ConfirmDialog :open="confirmClearKey" title="Clear the stored API key?"
                   detail="AI cards stop working on this provider until a new key is saved."
                   confirm-label="Clear" @confirm="aiClearKey" @cancel="confirmClearKey = false" />
    <ConfirmDialog :open="confirmClearCli" title="Clear the CLI token?"
                   detail="The CLI falls back to the credentials mounted from the host, if any."
                   confirm-label="Clear" @confirm="aiSaveCliToken(true)" @cancel="confirmClearCli = false" />
  </NeonPage>
</template>

<style scoped src="./settings-forms.css"></style>
<style scoped>
.sub { margin: -12px 0 14px; font-size: 13px; color: #9b9bb0; }
.check.big { font-size: 17px; font-weight: 700; }
.stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
.stats :deep(.ns-v) { font-size: 17px; }
.keyrow { display: flex; gap: 8px; }
.keyrow input { flex: 1; min-width: 0; }
.preview { max-height: 420px; overflow: auto; font-size: 11.5px; line-height: 1.45; background: #0f1118;
  border: 1px solid #23263a; border-radius: 12px; padding: 10px; white-space: pre; }
</style>
