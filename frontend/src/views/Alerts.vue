<script setup lang="ts">
import axios from "axios";
import { onMounted, ref } from "vue";
import Card from "@/components/Card.vue";
import { apiBase, queryToken } from "@/config";
import { fmtDateTime } from "@/format";

interface Alert {
  id: number;
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
  acknowledged: boolean;
}

const alerts = ref<Alert[]>([]);
const showAcked = ref(false);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const base = (apiBase.value || "/api").replace(/\/$/, "");
    const r = await axios.get<Alert[]>(`${base}/alerts`, {
      headers: { Authorization: `Bearer ${queryToken.value}` },
      params: { acknowledged: showAcked.value ? null : false, limit: 100 },
    });
    alerts.value = r.data;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

async function ack(id: number) {
  const base = (apiBase.value || "/api").replace(/\/$/, "");
  await axios.post(`${base}/alerts/${id}/ack`, null, {
    headers: { Authorization: `Bearer ${queryToken.value}` },
  });
  await load();
}

onMounted(load);
</script>

<template>
  <div>
    <header class="head">
      <h1>Alerts</h1>
      <label class="toggle">
        <input type="checkbox" v-model="showAcked" @change="load"/>
        <span>Show acknowledged</span>
      </label>
    </header>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="alerts.length === 0" class="empty">No alerts.</div>

    <div v-else class="list">
      <Card v-for="a in alerts" :key="a.id"
            :title="a.kind"
            :subtitle="fmtDateTime(a.ts)">
        <pre class="payload">{{ JSON.stringify(a.payload, null, 2) }}</pre>
        <button v-if="!a.acknowledged" class="ack" @click="ack(a.id)">Acknowledge</button>
        <span v-else class="acked">acknowledged</span>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 1rem; }
h1 { margin: 0; }
.toggle { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); font-size: 0.85rem; }

.list { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }
.payload {
  background: var(--surface-2); padding: 0.5rem; border-radius: 4px;
  font-family: ui-monospace, monospace; font-size: 0.75rem;
  color: var(--text-soft); overflow-x: auto; margin: 0 0 0.6rem;
}
.ack {
  background: var(--accent); color: var(--accent-text); border: 0; border-radius: 6px;
  padding: 0.4rem 0.8rem; cursor: pointer; font-weight: 500;
}
.acked { color: var(--good); font-size: 0.85rem; }

.empty { color: var(--muted-2); padding: 2rem 0; text-align: center; }
.err { color: var(--bad); padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--bad); margin: 0.6rem 0; }
</style>
