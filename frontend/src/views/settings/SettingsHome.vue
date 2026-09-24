<script setup lang="ts">
/**
 * Settings home — SETTINGS-B1. Phone twin: `SettingsHomeScreen.kt`.
 *
 * The old Settings had no home: it opened on Updates, with thirteen panes
 * behind a pill rail, and every one of them mounted and fetched at once
 * (UX-W9). This page is a status hero plus seven rows, in the same order
 * as the phone:
 *
 *   hero    the server's one-line verdict on whether data is arriving
 *           (`/query/data-health` `overview`), tone decided server-side —
 *           lime when fine, amber when not, never rose — and three tiles:
 *           last phone sync, integrations working, server version
 *   rows    You & goals · Units & display · Connection & sync ·
 *           Integrations · AI · Data & imports · About & updates
 *
 * Each row carries a live one-line summary from data this page already
 * loads cheaply. Failure is not absence: a request that failed renders its
 * summary as a dash and the hero says it could not check — it never says
 * "Everything is arriving" on the strength of a timeout.
 */
import { computed, onMounted, ref } from "vue";
import {
  Database, Info, Link2, Monitor, Sparkles, UserRound, Wifi,
} from "lucide-vue-next";
import { api } from "@/api/client";
import type { DataHealth } from "@/api/types";
import { queryToken } from "@/config";
import { units } from "@/units";
import { timeFormat } from "@/format";
import { themeChoice } from "@/theme";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonHero from "@/components/neon/NeonHero.vue";
import NeonStat from "@/components/neon/NeonStat.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import SettingsRow from "@/components/settings/SettingsRow.vue";
import { relTime, modelLabel } from "./settingsText";
import "@/components/settings/settingsForm.css";

type Profile = Awaited<ReturnType<typeof api.getProfile>>;
type AiCfg = Awaited<ReturnType<typeof api.aiConfig>>;
type UpdateCheck = Awaited<ReturnType<typeof api.updateCheck>>;

// undefined = not answered (yet, or failed — see *Failed flags).
const health = ref<DataHealth | undefined>(undefined);
const version = ref<string | undefined>(undefined);
const update = ref<UpdateCheck | undefined>(undefined);
const ai = ref<AiCfg | undefined>(undefined);
const profile = ref<Profile | undefined>(undefined);
const healthFailed = ref(false);
const loading = ref(false);

async function load() {
  if (!queryToken.value) return;
  loading.value = true;
  healthFailed.value = false;
  const [h, v, u, a, p] = await Promise.allSettled([
    api.dataHealth(), api.version(), api.updateCheck(), api.aiConfig(), api.getProfile(),
  ]);
  if (h.status === "fulfilled") health.value = h.value; else healthFailed.value = true;
  if (v.status === "fulfilled") version.value = v.value.version;
  if (u.status === "fulfilled") update.value = u.value;
  if (a.status === "fulfilled") ai.value = a.value;
  if (p.status === "fulfilled") profile.value = p.value;
  loading.value = false;
}
onMounted(load);

const overview = computed(() => health.value?.overview ?? null);

const hero = computed(() => {
  if (!queryToken.value) {
    return { accent: "#ffb52e", headline: "Not connected to your server yet",
             sub: "Add your server address and access key to start." };
  }
  if (loading.value && !health.value) {
    return { accent: "#28e6ff", headline: "Checking…", sub: null };
  }
  if (healthFailed.value || !overview.value) {
    return { accent: "#ffb52e", headline: "Couldn't check your data right now",
             sub: "Tap to see the connection details and retry." };
  }
  return {
    accent: overview.value.tone === "caution" ? "#ffb52e" : "#5dff3b",
    headline: overview.value.headline,
    sub: overview.value.problem_count
      ? `${overview.value.problem_count} thing${overview.value.problem_count === 1 ? "" : "s"} to look at`
      : null,
  };
});

const phoneSync = computed(() => {
  if (!overview.value) return "—";
  // Compact for the tile: "37m", not "37m ago", which wraps at phone width.
  return overview.value.last_phone_sync_at
    ? relTime(overview.value.last_phone_sync_at).replace(/ ago$/, "") : "never";
});
const integrationsTile = computed(() =>
  overview.value ? `${overview.value.integrations_ok}/${overview.value.integrations_total}` : "—");
const versionTile = computed(() => (version.value ? `v${version.value}` : "—"));
const updateAvailable = computed(() => !!update.value?.update_available);

// ── Row summaries ────────────────────────────────────────────────────
const youSummary = computed<string | null>(() => {
  const p = profile.value;
  if (!p) return null;
  const extra = (p.extra ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (p.derived?.age != null) parts.push(`${p.derived.age} yrs`);
  const steps = extra.steps_goal as number | undefined;
  if (steps) parts.push(`${Number(steps).toLocaleString()} steps`);
  const sleep = extra.sleep_goal_h as number | undefined;
  if (sleep) parts.push(`${sleep}h sleep`);
  return parts.length ? parts.join(" · ") : "Add your details and goals";
});

const THEME_WORD: Record<string, string> = {
  neon: "Neon", dark: "Dark", light: "Light", auto: "Auto", refined: "Neon",
};
const displaySummary = computed(() => {
  const tf = timeFormat.value === "auto" ? "Auto time" : timeFormat.value;
  return `${units.value === "imperial" ? "Imperial" : "Metric"} · ${tf} · ${THEME_WORD[themeChoice.value] ?? themeChoice.value}`;
});

const connectionSummary = computed<string | null>(() => {
  if (!queryToken.value) return "Not signed in";
  if (!health.value) return null;
  if (health.value.phone.permissions_lost) return "Health Connect is blocking reads";
  const at = health.value.phone.last_success;
  return at ? `Phone synced ${relTime(at)}` : "Phone has not synced yet";
});
const connectionAttention = computed(() =>
  !queryToken.value || !!health.value?.phone.permissions_lost);

const integrationsSummary = computed<string | null>(() => {
  const o = overview.value;
  if (!o) return null;
  if (!o.integrations_total) return "None connected";
  return `${o.integrations_ok} of ${o.integrations_total} working`;
});
const integrationsAttention = computed(() => {
  const o = overview.value;
  return !!o && o.integrations_ok < o.integrations_total;
});

const aiSummary = computed<string | null>(() => {
  const a = ai.value;
  if (!a) return null;
  const who = a.provider === "claude_cli" ? `${modelLabel(a.model)} · subscription`
    : a.provider === "anthropic" ? modelLabel(a.model)
      : a.provider === "ollama" ? "Ollama" : "OpenAI-compatible";
  return `${who} · ${a.enabled ? "on" : "off"}`;
});

const aboutSummary = computed<string | null>(() => {
  if (!version.value && !update.value) return null;
  const v = version.value ? `v${version.value}` : "";
  if (update.value?.update_available) return `${v} · v${update.value.latest} available`;
  if (update.value && !update.value.error) return `${v} · up to date`;
  return v || null;
});
</script>

<template>
  <NeonPage title="Settings">
    <RouterLink to="/settings/connection" class="hero-link"
                :aria-label="`Connection and sync status: ${hero.headline}`">
      <NeonHero :accent="hero.accent">
        <div class="hero-head">
          <span class="hero-dot" :style="{ background: hero.accent }" aria-hidden="true"></span>
          <div class="hero-text">
            <div class="hero-h">{{ hero.headline }}</div>
            <div v-if="hero.sub" class="hero-sub">{{ hero.sub }}</div>
          </div>
        </div>
        <div v-if="queryToken" class="hero-stats">
          <NeonStat :value="phoneSync" label="Last phone sync" />
          <NeonStat :value="integrationsTile" label="Integrations OK" />
          <div class="ver-wrap">
            <NeonStat :value="versionTile" label="Server" />
            <span v-if="updateAvailable" class="sf-chip upd">Update available</span>
          </div>
        </div>
      </NeonHero>
    </RouterLink>

    <NeonEyebrow>Sections</NeonEyebrow>
    <nav aria-label="Settings sections">
      <SettingsRow to="/settings/you" :icon="UserRound" tint="#ff3ad8"
                   title="You & goals" :summary="queryToken ? youSummary : 'Sign in first'" />
      <SettingsRow to="/settings/display" :icon="Monitor" tint="#6f7bff"
                   title="Units & display" :summary="displaySummary" />
      <SettingsRow to="/settings/connection" :icon="Wifi" tint="#28e6ff"
                   title="Connection & sync" :summary="connectionSummary"
                   :attention="connectionAttention" />
      <SettingsRow to="/settings/integrations" :icon="Link2" tint="#5dff3b"
                   title="Integrations" :summary="queryToken ? integrationsSummary : 'Sign in first'"
                   :attention="integrationsAttention" />
      <SettingsRow to="/settings/ai" :icon="Sparkles" tint="#ff3ad8"
                   title="AI" :summary="queryToken ? aiSummary : 'Sign in first'" />
      <SettingsRow to="/settings/data" :icon="Database" tint="#ffb52e"
                   title="Data & imports" summary="Imports, exports and maintenance" />
      <SettingsRow to="/settings/about" :icon="Info" tint="#9b9bb0"
                   title="About & updates" :summary="aboutSummary"
                   :attention="updateAvailable" />
    </nav>
    <p v-if="healthFailed && queryToken" class="retry">
      <button type="button" class="sf-btn" @click="load">Retry</button>
    </p>
  </NeonPage>
</template>

<style scoped>
.hero-link { display: block; color: inherit; text-decoration: none; border-radius: 22px; }
.hero-link:focus-visible { outline: 2px solid #28e6ff; outline-offset: 3px; }
.hero-head { display: flex; gap: 12px; align-items: flex-start; }
.hero-dot { width: 12px; height: 12px; border-radius: 50%; margin-top: 7px; flex: 0 0 auto;
  box-shadow: 0 0 10px currentColor; }
.hero-text { min-width: 0; }
.hero-h { font-size: 19px; font-weight: 800; line-height: 1.3; }
.hero-sub { font-size: 13px; color: #9b9bb0; margin-top: 4px; }
.hero-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }
.ver-wrap { position: relative; display: flex; flex-direction: column; }
.ver-wrap > :first-child { flex: 1; }
.upd { position: absolute; left: 50%; transform: translateX(-50%); bottom: -10px; white-space: nowrap;
  font-size: 10.5px; }
.retry { margin-top: 12px; }
</style>
