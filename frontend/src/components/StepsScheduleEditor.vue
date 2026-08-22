<script setup lang="ts">
/**
 * DOW-1 — per-weekday step goals.
 *
 * Sparse by design: a blank day means "use the base goal", not zero. That
 * is what lets someone set a lower Saturday without restating the other
 * six, and it is why every input here starts empty rather than
 * pre-filled with the base — a pre-filled field would silently write six
 * overrides the user never asked for.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { StepsSchedule } from "@/api/types";

const data = ref<StepsSchedule | null>(null);
const draft = ref<Record<string, string>>({});
const loading = ref(true);
const saving = ref(false);
const saved = ref(false);
const error = ref<string | null>(null);

const LABELS: Record<string, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu",
  fri: "Fri", sat: "Sat", sun: "Sun",
};

async function load() {
  loading.value = true;
  try {
    const d = await api.getStepsSchedule();
    data.value = d;
    draft.value = Object.fromEntries(
      d.weekdays.map((k) => [k, d.schedule[k] != null ? String(d.schedule[k]) : ""]),
    );
  } catch {
    error.value = "Couldn't load the step schedule.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const anyOverride = computed(() =>
  Object.values(draft.value).some((v) => v.trim() !== ""),
);

async function save() {
  saving.value = true;
  saved.value = false;
  error.value = null;
  try {
    const payload: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(draft.value)) {
      const t = v.trim();
      payload[k] = t === "" ? null : Number(t);
    }
    data.value = await api.putStepsSchedule(payload);
    saved.value = true;
  } catch {
    error.value = "Couldn't save.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="sched">
    <p class="lede">
      Leave a day blank to use your usual goal
      <strong v-if="data">({{ data.base.toLocaleString() }})</strong>.
    </p>

    <div v-if="loading" class="muted">Loading…</div>
    <template v-else-if="data">
      <div class="grid">
        <label v-for="k in data.weekdays" :key="k">
          <span>{{ LABELS[k] ?? k }}</span>
          <input type="number" min="1" step="500"
                 :placeholder="String(data.base)"
                 v-model="draft[k]"/>
        </label>
      </div>
      <div class="actions">
        <button class="primary" :disabled="saving" @click="save">
          {{ saving ? "Saving…" : "Save schedule" }}
        </button>
        <span class="muted">Today: {{ data.effective_today.toLocaleString() }}</span>
        <span v-if="saved" class="ok">Saved</span>
        <span v-if="error" class="err">{{ error }}</span>
        <span v-if="!anyOverride" class="muted">No overrides — every day uses the base goal.</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sched { margin-top: 0.5rem; }
.lede { color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.7rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(88px, 1fr)); gap: 0.5rem; }
.grid label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.75rem; color: #94a3b8; margin: 0; }
.grid input {
  background: transparent; color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 6px; padding: 0.3rem 0.4rem; width: 100%;
  font-variant-numeric: tabular-nums;
}
.actions { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.8rem; flex-wrap: wrap; }
.ok { color: #4ade80; font-size: 0.8rem; }
.err { color: #f87171; font-size: 0.8rem; }
.muted { color: #64748b; font-size: 0.8rem; }
</style>
