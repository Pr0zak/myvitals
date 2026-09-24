<script setup lang="ts">
/**
 * SETTINGS-B2 — the status header every data-health-backed integration
 * page leads with: the server's verdict, when it last synced, when it
 * last actually brought something back, and — when it has failed — the
 * server's own action text ("Reconnect this integration…").
 *
 * A failed health request says so (amber, with retry). It never renders
 * as "Not set up": failure is not absence.
 */
import { computed } from "vue";
import type { IntegrationHealth } from "@/api/types";
import NeonHero from "@/components/neon/NeonHero.vue";
import { ageText, statusPill } from "./health";

const props = defineProps<{
  health: IntegrationHealth | null | undefined;
  loading: boolean;
  error: string | null;
}>();
const emit = defineEmits<{ (e: "retry"): void }>();

const pill = computed(() => (props.health ? statusPill(props.health) : null));
const accent = computed(() => {
  if (props.error) return "#ffb52e";
  const s = props.health?.status;
  if (s === "error" || s === "stale") return "#ffb52e";
  if (s === "ok") return "#5dff3b";
  return "#28e6ff";
});
</script>

<template>
  <NeonHero :accent="accent">
    <div v-if="loading && !health" class="skel" aria-busy="true">
      <div class="sk"></div><span class="sr-only">Loading status…</span>
    </div>
    <button v-else-if="error && !health" class="errbar" type="button" @click="emit('retry')">
      <b>Couldn't load status</b><span>{{ error }}</span><em>Tap to retry</em>
    </button>
    <template v-else-if="health">
      <div class="head">
        <span class="pill" :class="pill?.tone">{{ pill?.label }}</span>
      </div>
      <ul class="kv">
        <li><span>Last sync</span><span>{{ health.configured ? ageText(health.age_hours) : "—" }}</span></li>
        <li><span>Newest item imported</span><span>{{ health.last_item_at ? ageText(health.item_age_hours) : "none yet" }}</span></li>
      </ul>
      <p v-if="health.importing_nothing" class="msg info">
        Syncing fine, but nothing new has arrived in a while. That may just be a quiet month.
      </p>
      <p v-if="health.last_error" class="msg warn">{{ health.last_error }}</p>
      <p v-if="health.last_error && health.action" class="msg action">{{ health.action }}</p>
    </template>
    <div class="actions"><slot name="actions" /></div>
  </NeonHero>
</template>

<style scoped src="../settings-forms.css"></style>
<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.msg.action { color: var(--rn-cyan, #28e6ff); font-weight: 600; }
</style>
