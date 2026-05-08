<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { RefreshCw, MoreHorizontal } from "lucide-vue-next";

const props = defineProps<{
  date: string;       // pre-formatted "Fri Mar 8"
  loading?: boolean;
}>();
const emit = defineEmits<{ (e: "refresh"): void }>();
const router = useRouter();
const overflow = ref(false);

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
.head-l { display: flex; align-items: baseline; gap: 14px; }
h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.3px; }
.date-pip {
  font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--on-surface-2); font-weight: 500;
  padding: 3px 8px; border: 1px solid var(--outline);
  border-radius: 6px; background: var(--surface-low);
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
