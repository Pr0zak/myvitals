<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { RefreshCw, MoreHorizontal } from "lucide-vue-next";

const props = defineProps<{
  date: string;       // pre-formatted "Fri Mar 8"
  loading?: boolean;
  lastSyncIso?: string | null;
}>();
const emit = defineEmits<{ (e: "refresh"): void }>();
const router = useRouter();
const overflow = ref(false);

const syncLabel = computed(() => {
  if (!props.lastSyncIso) return "never synced";
  const ageMs = Date.now() - new Date(props.lastSyncIso).getTime();
  const min = Math.round(ageMs / 60_000);
  if (min < 1) return "synced just now";
  if (min < 60) return `synced ${min} min ago`;
  const h = Math.floor(min / 60);
  return `synced ${h}h ago`;
});
const syncTone = computed<"good" | "warn" | "neutral">(() => {
  if (!props.lastSyncIso) return "neutral";
  const ageMs = Date.now() - new Date(props.lastSyncIso).getTime();
  return ageMs < 30 * 60_000 ? "good" : "warn";
});

const NAV: Array<{ to: string; label: string }> = [
  { to: "/trends", label: "Trends" },
  { to: "/calendar", label: "Calendar" },
  { to: "/goals", label: "Goals" },
  { to: "/compare", label: "Compare" },
];
function go(to: string) {
  overflow.value = false;
  router.push(to);
}
</script>

<template>
  <div class="head">
    <div class="head-l">
      <h1>Today</h1>
      <span class="date-pip">{{ date }}</span>
      <span v-if="lastSyncIso" class="sync-chip" :title="lastSyncIso">
        <span :class="['dot', `dot-${syncTone}`]"/>
        <span class="mono">{{ syncLabel }}</span>
      </span>
    </div>
    <div class="head-r">
      <button class="btn btn-icon" :disabled="loading"
              @click="emit('refresh')" title="Refresh">
        <RefreshCw :size="14"/>
      </button>
      <button class="btn btn-icon" @click="overflow = !overflow" title="More">
        <MoreHorizontal :size="14"/>
      </button>
      <div v-if="overflow" class="overflow">
        <button v-for="n in NAV" :key="n.to" class="ovr-item" @click="go(n.to)">
          {{ n.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head {
  display: flex; align-items: center; justify-content: space-between;
  height: 36px;
}
.head-l { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.3px; line-height: 1; }
.date-pip {
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--on-surface-2); font-weight: 500;
  padding: 3px 8px; border: 1px solid var(--outline);
  border-radius: 6px; background: var(--surface-low);
}
.sync-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--on-surface-2);
}
.head-r { display: flex; align-items: center; gap: 8px; position: relative; }
.overflow {
  position: absolute; top: 36px; right: 0; z-index: 10;
  background: var(--surface); border: 1px solid var(--outline);
  border-radius: 10px; padding: 4px; min-width: 160px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  display: flex; flex-direction: column;
}
.ovr-item {
  background: transparent; border: none;
  width: 100%; text-align: left; padding: 8px 10px;
  font: 500 13px/1 var(--sans);
  color: var(--on-surface); cursor: pointer; border-radius: 6px;
}
.ovr-item:hover { background: var(--surface-low); }
</style>
