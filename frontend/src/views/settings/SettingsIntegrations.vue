<script setup lang="ts">
/**
 * SETTINGS-B2 — Integrations list. One row per integration with a status
 * pill; tap for its page.
 *
 * Strava, Google Health and Concept2 take their status verbatim from
 * `/query/data-health` — status, last sync, and when a sync has failed the
 * SERVER's action text ("Reconnect this integration to restore it."). Home
 * Assistant and Trail status are not in that response, so their rows read
 * their own saved config.
 *
 * Each request settles on its own. A row whose request failed says
 * "Status unavailable" — never "Not set up", which would be a claim about
 * the user the page has no grounds for.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";
import type { DataHealth } from "@/api/types";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import { HEALTH_KEY, INTEGRATIONS, ageText, errText, statusPill, type PillTone } from "./integrations/health";

const router = useRouter();

type HaConfig = Awaited<ReturnType<typeof api.haConfigGet>>;
type TrailCfg = Awaited<ReturnType<typeof api.trailStatusConfig>>;

const loading = ref(true);
const health = ref<DataHealth | null>(null);
const healthErr = ref<string | null>(null);
const ha = ref<HaConfig | null>(null);
const haErr = ref<string | null>(null);
const trail = ref<TrailCfg | null>(null);
const trailErr = ref<string | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  const [h, c, t] = await Promise.allSettled([api.dataHealth(), api.haConfigGet(), api.trailStatusConfig()]);
  if (h.status === "fulfilled") { health.value = h.value; healthErr.value = null; }
  else healthErr.value = errText(h.reason);
  if (c.status === "fulfilled") { ha.value = c.value; haErr.value = null; }
  else haErr.value = errText(c.reason);
  if (t.status === "fulfilled") { trail.value = t.value; trailErr.value = null; }
  else trailErr.value = errText(t.reason);
  loading.value = false;
}
onMounted(load);

interface Row {
  key: string;
  name: string;
  pill: { label: string; tone: PillTone } | null;
  line: string;
  /** Server action text, shown in the accent colour when a person is needed. */
  action: string | null;
}

const rows = computed<Row[]>(() => INTEGRATIONS.map((m) => {
  const hk = HEALTH_KEY[m.key];
  if (hk) {
    const i = health.value?.integrations.find((x) => x.key === hk);
    if (!i) {
      return { key: m.key, name: m.name, pill: null, action: null,
        line: healthErr.value ? "Status unavailable" : m.blurb };
    }
    const parts: string[] = [];
    if (i.configured) parts.push(`Synced ${ageText(i.age_hours)}`);
    if (i.configured && i.last_item_at) parts.push(`newest item ${ageText(i.item_age_hours)}`);
    return {
      key: m.key, name: m.name, pill: statusPill(i),
      line: parts.length ? parts.join(" · ") : m.blurb,
      action: i.last_error ? (i.action ?? i.last_error) : null,
    };
  }
  if (m.key === "homeassistant") {
    if (!ha.value) return { key: m.key, name: m.name, pill: null, action: null,
      line: haErr.value ? "Status unavailable" : m.blurb };
    const pill = !ha.value.configured ? { label: "Not set up", tone: "mut" as const }
      : ha.value.realtime_enabled ? { label: "On", tone: "ok" as const }
      : { label: "Realtime off", tone: "neutral" as const };
    return { key: m.key, name: m.name, pill, line: m.blurb, action: null };
  }
  // trails
  if (!trail.value) return { key: m.key, name: m.name, pill: null, action: null,
    line: trailErr.value ? "Status unavailable" : m.blurb };
  return {
    key: m.key, name: m.name, line: m.blurb, action: null,
    pill: trail.value.configured ? { label: "Set up", tone: "ok" } : { label: "Not set up", tone: "mut" },
  };
}));

const allFailed = computed(() => !loading.value && !health.value && !ha.value && !trail.value);
</script>

<template>
  <NeonPage title="Integrations" back="/settings">
    <p class="sub">Services that send data into myvitals.</p>

    <div v-if="loading && !health && !ha && !trail" class="skel" aria-busy="true">
      <div v-for="i in 5" :key="i" class="sk"></div>
      <span class="sr-only">Loading integrations…</span>
    </div>

    <template v-else>
      <button v-if="allFailed || healthErr" class="errbar" type="button" @click="load">
        <b>{{ allFailed ? "Couldn't load integration status" : "Couldn't load sync status" }}</b>
        <span>{{ healthErr ?? haErr ?? trailErr }}</span>
        <em>Tap to retry</em>
      </button>

      <NeonEyebrow>Connected services</NeonEyebrow>
      <ul class="list">
        <li v-for="r in rows" :key="r.key">
          <button class="row" type="button" :aria-label="`${r.name}${r.pill ? ', ' + r.pill.label : ''}. Open settings`"
                  @click="router.push(`/settings/integrations/${r.key}`)">
            <span class="txt">
              <span class="name">{{ r.name }}</span>
              <span class="line">{{ r.line }}</span>
              <span v-if="r.action" class="act">{{ r.action }}</span>
            </span>
            <span v-if="r.pill" class="pill" :class="r.pill.tone">{{ r.pill.label }}</span>
            <span class="chev" aria-hidden="true">›</span>
          </button>
        </li>
      </ul>
    </template>
  </NeonPage>
</template>

<style scoped src="./settings-forms.css"></style>
<style scoped>
.sub { margin: -12px 0 14px; font-size: 13px; color: #9b9bb0; }
.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.row { width: 100%; min-height: 64px; display: flex; align-items: center; gap: 12px; text-align: left;
  background: #181b27; border: 1px solid #23263a; border-radius: 18px; padding: 12px 14px; cursor: pointer;
  color: #ececf5; font: inherit; }
.row:focus-visible { outline: 2px solid #28e6ff; outline-offset: 2px; }
.row:active { transform: scale(.99); }
.txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.name { font-size: 15px; font-weight: 700; }
.line { font-size: 12px; color: #9b9bb0; }
.act { font-size: 12px; color: #28e6ff; font-weight: 600; }
.chev { color: #9b9bb0; font-size: 20px; flex: 0 0 auto; }
</style>
