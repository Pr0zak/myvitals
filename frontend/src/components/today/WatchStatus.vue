<script setup lang="ts">
/**
 * Watch status tile — Pixel Watch liveness from the HA WebSocket
 * consumer's device_status table. Polls /api/device-status/latest every
 * 15s while visible. Renders nothing when there's no row (consumer not
 * yet configured) so it doesn't clutter the dashboard.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "@/api/client";
import { BatteryFull, Plug, Watch, Heart } from "lucide-vue-next";

type DeviceStatus = Awaited<ReturnType<typeof api.deviceStatusLatest>>;

const status = ref<DeviceStatus>(null);
const error = ref<string | null>(null);
const now = ref(Date.now());
let pollTimer: number | null = null;
let tickTimer: number | null = null;

const ageS = computed<number | null>(() => {
  const ts = status.value?.time;
  if (!ts) return null;
  return Math.max(0, Math.round((now.value - new Date(ts).getTime()) / 1000));
});

const ageLabel = computed(() => {
  const s = ageS.value;
  if (s === null) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
});

// "online" requires both: a recent row AND the consumer-set online flag.
// If the row is older than 5 minutes treat it as stale regardless of the
// recorded flag — the consumer may have died without writing offline.
const onlineNow = computed<boolean>(() => {
  if (status.value === null) return false;
  if (status.value.online !== true) return false;
  if (ageS.value !== null && ageS.value > 300) return false;
  return true;
});

async function load() {
  try {
    status.value = await api.deviceStatusLatest();
    error.value = null;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(() => {
  load();
  pollTimer = window.setInterval(load, 15_000);
  tickTimer = window.setInterval(() => { now.value = Date.now(); }, 1_000);
});
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer);
  if (tickTimer !== null) window.clearInterval(tickTimer);
});
</script>

<template>
  <div v-if="status" class="watch-tile" :class="{ offline: !onlineNow }">
    <div class="row">
      <Watch :size="16" class="icon"/>
      <span class="label">Watch</span>
      <span class="dot" :class="{ on: onlineNow }" :title="onlineNow ? 'online' : 'offline'"/>
      <span class="age">{{ ageLabel }}</span>
    </div>
    <div class="row metrics">
      <span v-if="status.battery_pct !== null" class="chip">
        <BatteryFull :size="13"/> {{ status.battery_pct }}%
      </span>
      <span v-if="status.is_charging === true" class="chip charging">
        <Plug :size="13"/> charging
      </span>
      <span v-if="status.is_worn !== null" class="chip" :class="{ worn: status.is_worn }">
        <Heart :size="13"/> {{ status.is_worn ? "on body" : "off body" }}
      </span>
      <span v-if="status.activity_state" class="chip">
        {{ status.activity_state.toLowerCase() }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.watch-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.6rem 0.85rem;
  font-size: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.watch-tile.offline { opacity: 0.7; }
.row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.icon { color: var(--text); }
.label { font-weight: 600; color: var(--text); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }
.dot.on { background: #22c55e; box-shadow: 0 0 6px rgba(34, 197, 94, 0.6); }
.age { color: var(--muted); font-size: 0.78rem; margin-left: auto; }
.metrics { gap: 0.35rem; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.15rem 0.5rem;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 999px;
  font-size: 0.78rem;
  color: var(--muted);
}
.chip.charging { color: #38bdf8; background: rgba(56, 189, 248, 0.12); }
.chip.worn { color: #22c55e; background: rgba(34, 197, 94, 0.12); }
</style>
