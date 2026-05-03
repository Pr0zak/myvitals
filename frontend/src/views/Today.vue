<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { HeartRateSeries, SleepNight, StepsSeries, TodaySummary } from "@/api/types";

import HeartRateChart from "@/components/charts/HeartRateChart.vue";
import RecoveryCard from "@/components/RecoveryCard.vue";
import SleepCard from "@/components/SleepCard.vue";
import StepsCard from "@/components/StepsCard.vue";

const summary = ref<TodaySummary | null>(null);
const hr = ref<HeartRateSeries | null>(null);
const sleep = ref<SleepNight | null>(null);
const steps = ref<StepsSeries | null>(null);
const error = ref<string | null>(null);
const loading = ref(true);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const since = new Date(Date.now() - 24 * 3600 * 1000);
    const [s, h, sl, st] = await Promise.all([
      api.todaySummary(),
      api.heartRate({ since }),
      api.lastSleep(),
      api.steps({ since }),
    ]);
    summary.value = s;
    hr.value = h;
    sleep.value = sl;
    steps.value = st;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : "Failed to load";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="today">
    <header class="head">
      <h1>Today</h1>
      <button @click="load" :disabled="loading">{{ loading ? "Loading…" : "Refresh" }}</button>
    </header>

    <div v-if="error" class="err">{{ error }}</div>

    <div v-if="!loading" class="grid">
      <RecoveryCard
        :score="summary?.recovery_score ?? null"
        :rhr="summary?.resting_hr ?? null"
        :hrv="summary?.hrv_avg ?? null"
      />
      <StepsCard :total="summary?.steps_total ?? steps?.total ?? 0" />
      <SleepCard :sleep="sleep" />
      <HeartRateChart :series="hr" />
    </div>

    <div v-if="summary?.last_sync" class="footer">
      Last sync: {{ new Date(summary.last_sync).toLocaleString() }}
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: baseline; }
.head h1 { margin: 0; }
button { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 0.4rem 0.8rem; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}
.err { color: #ef4444; padding: 0.6rem 0.8rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid #ef4444; margin: 0.6rem 0; }
.footer { margin-top: 1.5rem; color: #64748b; font-size: 0.8rem; text-align: right; }
</style>
