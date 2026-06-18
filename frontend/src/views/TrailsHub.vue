<script setup lang="ts">
/**
 * Trails — its own section in the Vitality Neon shell. RainoutLine status
 * board for the local MTB network: open / wet-delayed / closed per trail,
 * with a force-refresh and per-trail drill into the full /trails view (map +
 * history + subscribe).
 */
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { api } from "@/api/client";

type Trail = Awaited<ReturnType<typeof api.trails>>["trails"][number];

const router = useRouter();
const loading = ref(true);
const refreshing = ref(false);
const trails = ref<Trail[]>([]);

const openCount = computed(() => trails.value.filter((t) => t.status === "open").length);

const STATUS: Record<string, { label: string; color: string }> = {
  open: { label: "Open", color: "var(--rn-lime)" },
  delayed: { label: "Wet · delayed", color: "var(--rn-amber)" },
  closed: { label: "Closed", color: "var(--rn-bad)" },
  unknown: { label: "Unknown", color: "var(--rn-mut)" },
};
function st(t: Trail) {
  return STATUS[t.status ?? "unknown"] ?? STATUS.unknown;
}
function place(t: Trail): string {
  return [t.city, t.state].filter(Boolean).join(", ") || "—";
}

async function load() {
  const r = await api.trails().catch(() => null);
  if (r) {
    // Open first, then delayed, closed, unknown; subscribed floats up within.
    const rank: Record<string, number> = { open: 0, delayed: 1, closed: 2, unknown: 3 };
    trails.value = [...r.trails].sort((a, b) =>
      (rank[a.status ?? "unknown"] ?? 3) - (rank[b.status ?? "unknown"] ?? 3) ||
      Number(b.subscribed) - Number(a.subscribed));
  }
  loading.value = false;
}
async function refresh() {
  refreshing.value = true;
  try { await api.refreshTrails().catch(() => null); await load(); }
  finally { refreshing.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="trails-view">
    <header class="head">
      <h1>Trails</h1>
      <button class="refresh" :class="{ spin: refreshing }" @click="refresh" aria-label="Refresh trail status">↻</button>
    </header>
    <div class="cap" v-if="!loading">
      {{ openCount }} of {{ trails.length }} open · RainoutLine
    </div>

    <div v-if="loading" class="empty">Loading trails…</div>
    <div v-else-if="trails.length === 0" class="empty">
      No trails configured. Set your RainoutLine DNIS in Settings → Trail status.
    </div>

    <div v-else class="list">
      <button v-for="t in trails" :key="t.id" class="trail" @click="router.push('/trails')">
        <span class="dot" :style="{ background: st(t).color, boxShadow: `0 0 8px ${st(t).color}` }" />
        <span class="meta">
          <span class="nm">
            {{ t.name }}
            <span v-if="t.subscribed" class="star">★</span>
          </span>
          <span class="loc">{{ place(t) }}<template v-if="t.comment"> · {{ t.comment }}</template></span>
        </span>
        <span class="status" :style="{ color: st(t).color }">{{ st(t).label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.trails-view {
  --rn-bg: #0f1118; --rn-card: #181b27; --rn-ink: #ececf5; --rn-mut: #9b9bb0;
  --rn-mag: #ff3ad8; --rn-lime: #5dff3b; --rn-cyan: #28e6ff; --rn-amber: #ffb52e;
  --rn-bad: #ff5d7a; --rn-track: #272a3b;
  min-height: 100vh; margin: -1.25rem -1.5rem; padding: 54px 22px 104px;
  background: radial-gradient(120% 55% at 50% -5%, #161a2c, #0f1118 58%);
  color: var(--rn-ink); font-family: 'Plus Jakarta Sans', 'Geist', system-ui;
}
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.head h1 { font-size: 32px; font-weight: 800; margin: 0; letter-spacing: -0.5px; }
.refresh {
  width: 42px; height: 42px; border-radius: 50%; border: 1px solid var(--rn-track);
  background: var(--rn-card); color: var(--rn-cyan); font-size: 20px; cursor: pointer;
}
.refresh.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.cap {
  font-family: 'Space Grotesk', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 0.06em; color: var(--rn-mut); text-transform: uppercase; margin: 0 0 18px;
}
.empty { color: var(--rn-mut); text-align: center; padding: 3rem 1rem; }
.list { display: flex; flex-direction: column; gap: 11px; }
.trail {
  display: flex; align-items: center; gap: 14px; background: var(--rn-card);
  border: 0; border-radius: 18px; padding: 15px 18px; cursor: pointer; color: inherit;
  text-align: left; transition: transform 0.12s ease;
}
.trail:active { transform: scale(0.985); }
.dot { width: 12px; height: 12px; border-radius: 50%; flex: 0 0 auto; }
.meta { flex: 1; min-width: 0; }
.nm { font-weight: 700; font-size: 16px; display: flex; align-items: center; gap: 6px; }
.star { color: var(--rn-amber); font-size: 13px; }
.loc {
  display: block; color: var(--rn-mut); font-size: 12px; margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.status {
  font-family: 'Space Grotesk', monospace; font-weight: 700; font-size: 13px;
  flex: 0 0 auto; text-align: right;
}
</style>
