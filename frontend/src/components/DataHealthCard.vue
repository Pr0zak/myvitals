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
 * is meant to be continuous can go amber — otherwise the card is a
 * permanent wall of warnings and gets ignored within a week, which
 * defeats the entire point of having it.
 *
 * SETTINGS-B1: restyled with the neon kit (it lives on Settings →
 * Connection now, not buried under Display), and amber replaces red for
 * a stale feed — rose is reserved for the crisis surfaces.
 */
import { computed, onMounted, ref, watch } from "vue";
import { api } from "@/api/client";
import type { DataHealth, StreamStatus } from "@/api/types";

/**
 * `data` lets a page that already fetched /query/data-health (Connection
 * reads the phone block from the same response) hand it in rather than
 * fetch it twice. Omitted, the card loads its own. `error` is the caller's
 * failure message when its own fetch failed.
 */
const props = defineProps<{ data?: DataHealth | null; error?: string | null }>();

const own = ref<DataHealth | null>(null);
const loading = ref(props.data === undefined);
const ownError = ref<string | null>(null);

async function load() {
  loading.value = true;
  ownError.value = null;
  try {
    own.value = await api.dataHealth();
  } catch {
    ownError.value = "Couldn't load data health.";
  } finally {
    loading.value = false;
  }
}
onMounted(() => { if (props.data === undefined) void load(); });
watch(() => props.data, (d) => { if (d !== undefined) loading.value = false; });

const data = computed(() => (props.data !== undefined ? props.data : own.value));
const error = computed(() => props.error ?? ownError.value);

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
  stale: "warn",
  never: "warn",
  ad_hoc: "neutral",
  not_configured: "muted",
};
const TONE_WORD: Record<string, string> = {
  ok: "arriving",
  warn: "needs attention",
  neutral: "recorded when you choose",
  muted: "not set up",
};

/** Streams that can actually be broken, first. */
const problems = computed(() => data.value?.problem_keys ?? []);
</script>

<template>
  <section class="dh" aria-labelledby="dh-title">
    <h3 id="dh-title" class="dh-title">Data health</h3>
    <div v-if="loading" class="dh-mut">Checking…</div>
    <div v-else-if="error && !data" class="dh-err" role="alert">{{ error }}</div>

    <template v-else-if="data">
      <p class="dh-summary" :class="data.ok ? 'ok' : 'warn'">
        {{ data.ok
          ? "Everything that should be flowing is flowing."
          : `${problems.length} stream${problems.length === 1 ? '' : 's'} need attention.` }}
      </p>

      <ul class="dh-rows">
        <li v-for="s in data.streams" :key="s.key" :class="TONE[s.status]">
          <span class="dot" role="img" :aria-label="TONE_WORD[TONE[s.status]]"></span>
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

      <h4 class="dh-sub">Integrations</h4>
      <ul class="dh-rows">
        <li v-for="i in data.integrations" :key="i.key"
            :class="i.status === 'ok' ? 'ok'
                  : i.status === 'error' || i.status === 'stale' ? 'warn' : 'muted'">
          <span class="dot" role="img"
                :aria-label="i.status === 'ok' ? 'working' : i.configured ? 'needs attention' : 'not connected'"></span>
          <span class="name">
            {{ i.label }}
            <!-- The error text is the whole reason this card exists for
                 Strava: a dead cookie syncs zero rides silently. -->
            <span v-if="i.last_error" class="src err">{{ i.last_error }}</span>
            <!-- OG3-D1: what to DO about it. A revoked grant and a timed-out
                 request are both `status: error` with a message, but only one
                 of them has an action and only one will still be failing in
                 an hour. The Google Health grant sat revoked for eight days
                 here, retried every fifteen minutes, with nothing on any
                 screen saying it needed a person. -->
            <span v-if="i.action && i.last_error"
                  class="src" :class="i.needs_reconnect ? 'act' : 'quiet'">
              {{ i.action }}
            </span>
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

      <p v-if="data.phone.permissions_lost" class="dh-phonewarn">
        Health Connect permissions lost —
        {{ data.phone.perms_granted }}/{{ data.phone.perms_required }} granted.
      </p>
      <p class="dh-foot">
        Grey rows are recorded when you choose to, not on a schedule, so
        an old reading there is not a fault.
      </p>
    </template>
  </section>
</template>

<style scoped>
.dh { background: #181b27; border: 1px solid #23263a; border-radius: 18px; padding: 14px;
  margin-bottom: 12px; color: #ececf5; }
.dh-title { margin: 0 0 8px; font-size: 16px; font-weight: 800; }
.dh-sub { font-family: 'Space Grotesk', 'Geist Mono', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; color: #9b9bb0; margin: 16px 0 6px; }
.dh-summary { margin: 0 0 10px; font-size: 14px; font-weight: 600; }
.dh-summary.ok { color: #5dff3b; }
.dh-summary.warn { color: #ffb52e; }

.dh-rows { list-style: none; margin: 0; padding: 0; }
.dh-rows li {
  display: grid; grid-template-columns: auto 1fr auto; align-items: baseline; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid #23263a;
}
.dh-rows li:last-child { border-bottom: 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #6b6b80; }
.dh-rows li.ok .dot { background: #5dff3b; box-shadow: 0 0 6px rgba(93, 255, 59, .5); }
.dh-rows li.warn .dot { background: #ffb52e; box-shadow: 0 0 6px rgba(255, 181, 46, .5); }
.dh-rows li.neutral .dot { background: #9b9bb0; }
.dh-rows li.muted { opacity: .55; }

.name { font-size: 14px; min-width: 0; }
.src { display: block; color: #9b9bb0; font-size: 12px; overflow-wrap: anywhere; }
.src.err { color: #ffb52e; }
.src.act { color: #28e6ff; font-weight: 600; }
.quiet { display: block; opacity: .75; font-size: 11px; }
.age { color: #9b9bb0; font-size: 13px; font-family: 'Space Grotesk', 'Geist Mono', monospace;
  font-variant-numeric: tabular-nums; text-align: right; }

.dh-phonewarn { color: #ffb52e; font-size: 13px; margin: 12px 0 0; }
.dh-foot { color: #9b9bb0; font-size: 12px; margin: 12px 0 0; }
.dh-mut { color: #9b9bb0; font-size: 13px; }
.dh-err { color: #ffb52e; font-size: 13px; }
</style>
