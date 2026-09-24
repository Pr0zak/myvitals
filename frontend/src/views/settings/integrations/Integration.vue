<script setup lang="ts">
/**
 * SETTINGS-B2 — one integration's page, `/settings/integrations/:key`.
 *
 * Reads the key from the route (a prop literally named `key` would be
 * swallowed by Vue as the vnode key). Fetches `/query/data-health` only
 * for the three integrations it reports on; Home Assistant and Trail
 * status carry their own status, so their pages ask nothing extra.
 */
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api/client";
import type { IntegrationHealth } from "@/api/types";
import NeonPage from "@/components/neon/NeonPage.vue";
import Strava from "./Strava.vue";
import GoogleHealth from "./GoogleHealth.vue";
import Concept2 from "./Concept2.vue";
import HomeAssistant from "./HomeAssistant.vue";
import Trails from "./Trails.vue";
import { HEALTH_KEY, INTEGRATIONS, errText } from "./health";

const route = useRoute();
const key = computed(() => {
  const k = route.params.key;
  return Array.isArray(k) ? k[0] : (k ?? "");
});
const meta = computed(() => INTEGRATIONS.find((i) => i.key === key.value) ?? null);

const CHILD = { strava: Strava, google: GoogleHealth, concept2: Concept2, homeassistant: HomeAssistant, trails: Trails } as const;
const child = computed(() => CHILD[key.value as keyof typeof CHILD] ?? null);

const health = ref<IntegrationHealth | null | undefined>(undefined);
const healthLoading = ref(false);
const healthError = ref<string | null>(null);

async function loadHealth(): Promise<void> {
  const hk = HEALTH_KEY[key.value];
  if (!hk) { health.value = undefined; return; }
  healthLoading.value = true;
  healthError.value = null;
  try {
    const d = await api.dataHealth();
    health.value = d.integrations.find((i) => i.key === hk) ?? null;
    if (health.value === null) healthError.value = "The server did not report on this integration.";
  } catch (e) {
    healthError.value = errText(e);
  } finally {
    healthLoading.value = false;
  }
}
watch(key, () => { health.value = undefined; loadHealth(); }, { immediate: true });
</script>

<template>
  <NeonPage :title="meta?.name ?? 'Integration'" back="/settings/integrations">
    <p v-if="meta" class="blurb">{{ meta.blurb }}</p>
    <component
      :is="child"
      v-if="child"
      :health="health"
      :health-loading="healthLoading"
      :health-error="healthError"
      @refresh-health="loadHealth"
    />
    <p v-else class="blurb">No integration called “{{ key }}”.</p>
  </NeonPage>
</template>

<style scoped>
.blurb { margin: -10px 0 14px; font-size: 13px; color: #9b9bb0; }
</style>
