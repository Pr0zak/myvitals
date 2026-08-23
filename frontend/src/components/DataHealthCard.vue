<script setup lang="ts">
/**
 * HEALTH-1 — is my data actually arriving?
 *
 * Renders only. Every status here is decided server-side, including what
 * counts as a problem, so this card and the phone's cannot drift.
 *
 * The thing worth understanding before editing: **most of these streams
 * are supposed to be stale.** Body metrics were last written 103 days
 * ago and blood pressure 75; those are facts about how often the user
 * weighs themselves, not faults. They render neutral. Only a stream that
 * is meant to be continuous can go red — otherwise the card is a
 * permanent wall of warnings and gets ignored within a week, which
 * defeats the entire point of having it.
 */
import { computed, onMounted, ref } from "vue";
import Card from "@/components/Card.vue";
import { api } from "@/api/client";
import type { DataHealth, StreamStatus } from "@/api/types";

const data = ref<DataHealth | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    data.value = await api.dataHealth();
  } catch {
    error.value = "Couldn't load data health.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

/** Human age. Deliberately coarse — "3d" is the useful precision for
 *  "when did this last arrive", and minutes would imply a false one. */
function age(hours: number | null): string {
  if (hours == null) return "never";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m`;
  if (hours < 48) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

const TONE: Record<StreamStatus, string> = {
  ok: "ok",
  stale: "bad",
  never: "warn",
  ad_hoc: "neutral",
  not_configured: "muted",
};

/** Streams that can actually be broken, first. */
const problems = computed(() => data.value?.problem_keys ?? []);
</script>

<template>
  <Card title="Data health">
    <div v-if="loading" class="muted">Checking…</div>
    <div v-else-if="error" class="err">{{ error }}</div>

    <template v-else-if="data">
      <p class="summary" :class="data.ok ? 'ok' : 'bad'">
        {{ data.ok
          ? "Everything that should be flowing is flowing."
          : `${problems.length} stream${problems.length === 1 ? '' : 's'} need attention.` }}
      </p>

      <ul class="rows">
        <li v-for="s in data.streams" :key="s.key" :class="TONE[s.status]">
          <span class="dot"></span>
          <span class="name">
            {{ s.label }}
            <!-- Say when a row speaks for one writer among several,
                 rather than implying the whole table is reported. -->
            <span class="src">
              {{ s.source }}{{ s.canonical_source_only ? " · main source only" : "" }}
            </span>
          </span>
          <span class="age">
            {{ s.status === "not_configured" && s.last_at === null
              ? "not set up" : age(s.age_hours) }}
          </span>
        </li>
      </ul>

      <h3>Integrations</h3>
      <ul class="rows">
        <li v-for="i in data.integrations" :key="i.key"
            :class="i.status === 'ok' ? 'ok'
                  : i.status === 'error' ? 'bad'
                  : i.status === 'stale' ? 'warn' : 'muted'">
          <span class="dot"></span>
          <span class="name">
            {{ i.label }}
            <!-- The error text is the whole reason this card exists for
                 Strava: a dead cookie syncs zero rides silently. -->
            <span v-if="i.last_error" class="src err">{{ i.last_error }}</span>
          </span>
          <span class="age">
            {{ i.configured ? age(i.age_hours) : "not connected" }}
            <!-- Polled recently but importing nothing. Shown as a plain
                 statement, not a warning: a quiet month may simply be a
                 quiet month, and the app cannot tell. -->
            <small v-if="i.importing_nothing" class="quiet">
              last import {{ age(i.item_age_hours ?? null) }}
            </small>
          </span>
        </li>
      </ul>

      <p v-if="data.phone.permissions_lost" class="phonewarn">
        Health Connect permissions lost —
        {{ data.phone.perms_granted }}/{{ data.phone.perms_required }} granted.
      </p>
      <p class="foot">
        Neutral rows are recorded when you choose to, not on a schedule, so
        an old reading there is not a fault.
      </p>
    </template>
  </Card>
</template>

<style scoped>
.quiet { display: block; opacity: 0.7; font-size: 0.72em; }
.summary { margin: 0 0 0.8rem; font-size: 0.9rem; }
.summary.ok { color: var(--good); }
.summary.bad { color: var(--bad); }

h3 { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-2); margin: 1.1rem 0 0.4rem; }

.rows { list-style: none; margin: 0; padding: 0; }
.rows li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: baseline;
  gap: 0.55rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--surface-2);
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted-2); }
.rows li.ok .dot { background: var(--good); }
.rows li.bad .dot { background: var(--bad); }
.rows li.warn .dot { background: var(--warn, #f59e0b); }
.rows li.neutral .dot { background: var(--muted); }
.rows li.muted { opacity: 0.55; }

.name { color: var(--text); font-size: 0.88rem; min-width: 0; }
.src { display: block; color: var(--muted-2); font-size: 0.72rem; }
.src.err { color: var(--bad); }
.age { color: var(--muted); font-size: 0.8rem; font-variant-numeric: tabular-nums; }

.phonewarn { color: var(--warn, #f59e0b); font-size: 0.82rem; margin: 0.8rem 0 0; }
.foot { color: var(--muted-2); font-size: 0.75rem; margin: 0.9rem 0 0; }
.muted { color: var(--muted-2); }
.err { color: var(--bad); }
</style>
