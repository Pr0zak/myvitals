<script setup lang="ts">
/**
 * /trails — RainoutLine status board for the user's local trail
 * network. Pull-to-refresh hits POST /trails/refresh; star toggle
 * subscribes for status-flip pings.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Star, RefreshCw } from "lucide-vue-next";
import { api } from "@/api/client";
import { queryToken } from "@/config";
import Card from "@/components/Card.vue";

type Trail = Awaited<ReturnType<typeof api.trails>>["trails"][number];

const trails = ref<Trail[]>([]);
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string>("");
const tickNow = ref(Date.now());
let tickHandle: number | null = null;

async function load() {
  if (!queryToken.value) { loading.value = false; return; }
  loading.value = trails.value.length === 0;
  error.value = "";
  try {
    const r = await api.trails();
    trails.value = r.trails;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  refreshing.value = true;
  try {
    await api.refreshTrails();
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    refreshing.value = false;
  }
}

async function toggleSubscribe(t: Trail) {
  try {
    if (t.subscribed) {
      await api.unsubscribeTrail(t.id);
    } else {
      await api.subscribeTrail(t.id, "any");
    }
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

function fmtAge(iso: string | null): string {
  if (!iso) return "";
  const ms = tickNow.value - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const grouped = computed(() => {
  const open = trails.value.filter((t) => t.status === "open");
  const closed = trails.value.filter((t) => t.status === "closed");
  const other = trails.value.filter((t) => t.status !== "open" && t.status !== "closed");
  return { open, closed, other };
});

onMounted(() => {
  load();
  tickHandle = window.setInterval(() => { tickNow.value = Date.now(); }, 60000);
});
onUnmounted(() => { if (tickHandle) clearInterval(tickHandle); });
</script>

<template>
  <main class="trails">
    <header>
      <h1>Trails</h1>
      <button class="refresh" :disabled="refreshing" @click="refresh">
        <RefreshCw :size="16" :class="{ spinning: refreshing }" />
        {{ refreshing ? "Refreshing…" : "Refresh now" }}
      </button>
    </header>

    <p v-if="!queryToken" class="hint">Set your query token in Settings to load trails.</p>
    <p v-else-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>
    <Card v-else-if="trails.length === 0" title="No trails seeded yet">
      <p class="hint">
        The trail poller runs on a 15-minute schedule; the first tick
        seeds the catalog. Tap <strong>Refresh now</strong> to trigger
        an immediate poll.
      </p>
    </Card>

    <template v-else>
      <section v-if="grouped.open.length" class="group group-open">
        <h2>Open · {{ grouped.open.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.open" :key="t.id" class="card status-open">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">{{ fmtAge(t.source_ts || t.fetched_at) }}</p>
          </article>
        </div>
      </section>

      <section v-if="grouped.closed.length" class="group group-closed">
        <h2>Closed · {{ grouped.closed.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.closed" :key="t.id" class="card status-closed">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">{{ fmtAge(t.source_ts || t.fetched_at) }}</p>
          </article>
        </div>
      </section>

      <section v-if="grouped.other.length" class="group">
        <h2>Other · {{ grouped.other.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.other" :key="t.id" class="card">
            <header>
              <strong>{{ t.name }}</strong>
              <span class="status-tag">{{ t.status ?? "—" }}</span>
              <button class="star" :class="{ on: t.subscribed }"
                      @click="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
          </article>
        </div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.trails { max-width: 880px; }
header { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1rem; }
header h1 { margin: 0; }
.refresh {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.45rem 0.9rem; background: var(--bg-2);
  border: 1px solid var(--line); border-radius: 6px;
  color: var(--text-soft); cursor: pointer;
}
.refresh:hover { color: var(--text); border-color: var(--accent, #ef4444); }
.refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }

.hint { color: var(--muted); margin: 0.5rem 0; }
.err { color: #f87171; }

.group { margin-bottom: 1.4rem; }
.group h2 {
  font-size: 0.78rem; color: var(--muted); letter-spacing: 0.08em;
  text-transform: uppercase; margin: 0 0 0.6rem; font-weight: 600;
}
.grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.6rem;
}
.card {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 10px; padding: 0.7rem 0.9rem;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.card.status-open { border-left: 3px solid #22c55e; }
.card.status-closed { border-left: 3px solid #ef4444; opacity: 0.85; }

.card header {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 0.2rem;
}
.card header strong { flex: 1; font-size: 0.95rem; color: var(--text); }
.card .dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0;
}
.card.status-open .dot { background: #22c55e; }
.card.status-closed .dot { background: #ef4444; }

.star {
  background: none; border: none; cursor: pointer; padding: 4px;
  color: var(--muted); border-radius: 4px;
}
.star:hover { color: var(--accent, #ef4444); background: var(--bg-1); }
.star.on { color: #f59e0b; }

.status-tag { color: var(--muted); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.06em; }
.comment { color: var(--text-soft); font-size: 0.82rem; margin: 0; }
.meta { color: var(--muted-2); font-size: 0.74rem; margin: 0;
  font-family: 'Geist Mono', ui-monospace, monospace; }
</style>
