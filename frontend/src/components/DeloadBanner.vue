<script setup lang="ts">
/**
 * AI deload trigger banner. GETs the cached judgment first (free), shows
 * a refresh button that POSTs for a fresh read. Severity colours:
 *   none     — no banner shown
 *   light    — yellow
 *   moderate — orange
 *   rest     — red
 * AI must be enabled in Settings; on error we hide rather than nag.
 */
import { onMounted, ref } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";

type Severity = "none" | "light" | "moderate" | "rest";
type Judgment = {
  should_deload: boolean;
  severity: Severity;
  headline: string;
  evidence: string[];
  recommendation: string;
};

const judgment = ref<Judgment | null>(null);
const generatedAt = ref<string | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const expanded = ref(false);

async function loadLatest() {
  try {
    const r = await api.aiStrengthDeloadLatest();
    if (r) {
      judgment.value = r.judgment;
      generatedAt.value = r.generated_at;
    }
  } catch {
    // silent — banner just stays hidden
  }
}

async function refresh() {
  if (loading.value) return;
  loading.value = true;
  error.value = null;
  try {
    const r = await api.aiStrengthDeloadCheck();
    judgment.value = r.judgment;
    generatedAt.value = r.generated_at;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(loadLatest);

const sevClass = () => {
  const s = judgment.value?.severity ?? "none";
  return `sev-${s}`;
};
</script>

<template>
  <Card v-if="judgment && judgment.severity !== 'none'"
        :flat="true" :class="['deload-card', sevClass()]">
    <button class="deload-toggle" @click="expanded = !expanded">
      <span class="deload-icon">▲</span>
      <span class="deload-title">Deload {{ judgment.severity }}</span>
      <span class="deload-headline">{{ judgment.headline }}</span>
      <span class="deload-hint">{{ expanded ? "−" : "+" }}</span>
    </button>
    <div v-if="expanded" class="deload-body">
      <ul v-if="judgment.evidence?.length" class="deload-evidence">
        <li v-for="(e, i) in judgment.evidence" :key="i">{{ e }}</li>
      </ul>
      <div class="deload-rec"><strong>What to do:</strong> {{ judgment.recommendation }}</div>
      <div class="deload-foot">
        <button class="ghost" :disabled="loading" @click="refresh">
          {{ loading ? "Thinking…" : "Re-check" }}
        </button>
        <span v-if="generatedAt" class="muted">
          {{ new Date(generatedAt).toLocaleString() }}
        </span>
      </div>
      <p v-if="error" class="muted small">AI unavailable. Check Settings → AI.</p>
    </div>
  </Card>
  <Card v-else-if="!judgment" :flat="true" class="deload-card sev-none">
    <button class="deload-toggle" @click="refresh">
      <span class="deload-icon">▲</span>
      <span class="deload-title">Deload check</span>
      <span class="deload-headline muted">{{ loading ? "Reading…" : "Ask AI" }}</span>
    </button>
    <p v-if="error" class="muted small">AI unavailable. Check Settings → AI.</p>
  </Card>
</template>

<style scoped>
.deload-card { margin: 0 0 0.6rem; padding: 0.55rem 0.75rem !important;
               border-radius: 10px !important; border-left-width: 4px !important; }
.deload-card :deep(header) { display: none; }
.deload-card :deep(.body) { display: block; }
.sev-light    { border-left-color: #facc15 !important; background: rgba(250, 204, 21, 0.07); }
.sev-moderate { border-left-color: #f97316 !important; background: rgba(249, 115, 22, 0.08); }
.sev-rest     { border-left-color: #ef4444 !important; background: rgba(239, 68, 68, 0.09); }
.sev-none     { border-left-color: var(--line) !important; }
.deload-toggle {
  width: 100%; display: flex; align-items: center; gap: 0.5rem;
  background: transparent; border: none; padding: 0; cursor: pointer;
  color: var(--text); text-align: left; min-height: 28px;
}
.deload-icon { font-size: 0.8rem; }
.sev-light    .deload-icon { color: #facc15; }
.sev-moderate .deload-icon { color: #f97316; }
.sev-rest     .deload-icon { color: #ef4444; }
.deload-title { font-weight: 600; font-size: 0.9rem; text-transform: capitalize; }
.deload-headline { color: var(--text); font-size: 0.85rem; flex: 1; }
.deload-headline.muted { color: var(--muted); }
.deload-hint { color: var(--muted); font-size: 1rem; }
.deload-body { padding-top: 0.5rem; }
.deload-evidence { list-style: disc; padding-left: 1.2rem; margin: 0 0 0.5rem;
                   color: var(--text); font-size: 0.83rem; }
.deload-evidence li { margin: 0.15rem 0; }
.deload-rec { color: var(--text); font-size: 0.85rem; margin: 0.3rem 0 0.6rem; }
.deload-foot { display: flex; align-items: center; gap: 0.6rem; }
.ghost { background: transparent; color: var(--muted); border: 1px solid var(--line);
         border-radius: 6px; padding: 0.25rem 0.7rem; font-size: 0.78rem;
         cursor: pointer; }
.muted { color: var(--muted); }
.muted.small { font-size: 0.8rem; }
</style>
