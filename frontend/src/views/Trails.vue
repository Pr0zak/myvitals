<script setup lang="ts">
/**
 * /trails — RainoutLine status board for the user's local trail
 * network. Pull-to-refresh hits POST /trails/refresh; star toggle
 * subscribes for status-flip pings.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Star, RefreshCw, Navigation, Pencil } from "lucide-vue-next";
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

const linking = ref(false);
const linkResult = ref<string>("");
async function linkActivities() {
  linking.value = true;
  linkResult.value = "";
  try {
    const r = await api.linkActivitiesToTrails(2.0, false);
    linkResult.value = `Linked ${r.linked} new · ${r.already_linked_skipped} already · ${r.no_match_within_km} no match · ${r.no_gps} no GPS`;
    await load();
  } catch (e) {
    linkResult.value = e instanceof Error ? e.message : String(e);
  } finally {
    linking.value = false;
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

function openMaps(t: Trail) {
  if (t.latitude == null || t.longitude == null) return;
  const q = encodeURIComponent(`${t.latitude},${t.longitude} (${t.name})`);
  window.open(`https://www.google.com/maps/search/?api=1&query=${q}`, "_blank", "noreferrer");
}

// Edit location modal state
const editTrail = ref<Trail | null>(null);
const editLat = ref<string>("");
const editLon = ref<string>("");
const editCity = ref<string>("");
const editState = ref<string>("");
const editSaving = ref(false);
const editError = ref<string>("");

function openEdit(t: Trail) {
  editTrail.value = t;
  editLat.value = t.latitude?.toString() ?? "";
  editLon.value = t.longitude?.toString() ?? "";
  editCity.value = t.city ?? "";
  editState.value = t.state ?? "";
  editError.value = "";
}
function closeEdit() { editTrail.value = null; }

function useMyLocation() {
  if (!navigator.geolocation) {
    editError.value = "Geolocation not supported in this browser";
    return;
  }
  editError.value = "Locating…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      editLat.value = pos.coords.latitude.toFixed(6);
      editLon.value = pos.coords.longitude.toFixed(6);
      editError.value = "";
    },
    (err) => { editError.value = `Location failed: ${err.message}`; },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 60_000 },
  );
}

function openInMaps() {
  const t = editTrail.value;
  if (!t) return;
  // Pre-zoom to the existing pin if known, else search by trail name.
  const url = (t.latitude != null && t.longitude != null)
    ? `https://www.google.com/maps/@${t.latitude},${t.longitude},15z`
    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(t.name)}`;
  window.open(url, "_blank", "noreferrer");
}

async function saveEdit() {
  if (!editTrail.value) return;
  const lat = parseFloat(editLat.value);
  const lon = parseFloat(editLon.value);
  if (editLat.value && (Number.isNaN(lat) || lat < -90 || lat > 90)) {
    editError.value = "Latitude must be between -90 and 90";
    return;
  }
  if (editLon.value && (Number.isNaN(lon) || lon < -180 || lon > 180)) {
    editError.value = "Longitude must be between -180 and 180";
    return;
  }
  editSaving.value = true;
  try {
    await api.editTrailLocation(editTrail.value.id, {
      latitude: editLat.value ? lat : null,
      longitude: editLon.value ? lon : null,
      city: editCity.value || null,
      state: editState.value || null,
    });
    await load();
    closeEdit();
  } catch (e) {
    editError.value = e instanceof Error ? e.message : String(e);
  } finally {
    editSaving.value = false;
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
      <div class="header-actions">
        <button class="refresh" :disabled="refreshing" @click="refresh">
          <RefreshCw :size="16" :class="{ spinning: refreshing }" />
          {{ refreshing ? "Refreshing…" : "Refresh" }}
        </button>
        <button class="refresh" :disabled="linking" @click="linkActivities"
                title="Auto-link Strava / Garmin activities to trails by GPS proximity">
          🚴 {{ linking ? "Linking…" : "Link activities" }}
        </button>
      </div>
    </header>
    <p v-if="linkResult" class="hint" style="text-align: right">{{ linkResult }}</p>

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
          <article v-for="t in grouped.open" :key="t.id" class="card status-open"
                   :class="{ has_loc: t.latitude != null }"
                   @click="openMaps(t)">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click.stop="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
              <button class="star edit-pin"
                      title="Edit pin location"
                      @click.stop="openEdit(t)">
                <Pencil :size="14" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">
              <span>{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              <span v-if="t.city" class="loc">· {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</span>
              <span v-else-if="t.latitude == null" class="loc nopin">· no pin</span>
              <span v-if="t.visits_30d && t.visits_30d > 0" class="visits">
                · 🚴 {{ t.visits_30d }} visit{{ t.visits_30d === 1 ? '' : 's' }} (30d)
              </span>
              <Navigation v-if="t.latitude != null" :size="12" class="nav-ic" />
            </p>
          </article>
        </div>
      </section>

      <section v-if="grouped.closed.length" class="group group-closed">
        <h2>Closed · {{ grouped.closed.length }}</h2>
        <div class="grid">
          <article v-for="t in grouped.closed" :key="t.id" class="card status-closed"
                   :class="{ has_loc: t.latitude != null }"
                   @click="openMaps(t)">
            <header>
              <span class="dot"></span>
              <strong>{{ t.name }}</strong>
              <button class="star" :class="{ on: t.subscribed }"
                      :title="t.subscribed ? 'Unsubscribe' : 'Subscribe to status flips'"
                      @click.stop="toggleSubscribe(t)">
                <Star :size="16" />
              </button>
              <button class="star edit-pin"
                      title="Edit pin location"
                      @click.stop="openEdit(t)">
                <Pencil :size="14" />
              </button>
            </header>
            <p v-if="t.comment" class="comment">{{ t.comment }}</p>
            <p class="meta">
              <span>{{ fmtAge(t.source_ts || t.fetched_at) }}</span>
              <span v-if="t.city" class="loc">· {{ t.city }}{{ t.state ? ', ' + t.state : '' }}</span>
              <span v-else-if="t.latitude == null" class="loc nopin">· no pin</span>
              <span v-if="t.visits_30d && t.visits_30d > 0" class="visits">
                · 🚴 {{ t.visits_30d }} visit{{ t.visits_30d === 1 ? '' : 's' }} (30d)
              </span>
              <Navigation v-if="t.latitude != null" :size="12" class="nav-ic" />
            </p>
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

    <!-- Edit location modal -->
    <div v-if="editTrail" class="overlay" @click.self="closeEdit">
      <div class="edit-drawer">
        <header>
          <h2>Edit location · {{ editTrail.name }}</h2>
          <button class="close" @click="closeEdit">✕</button>
        </header>
        <p class="hint">
          Decimal degrees. Two quick ways to fill these in:
        </p>
        <div class="quick-actions">
          <button class="ghost" @click="useMyLocation">📍 Use my location</button>
          <button class="ghost" @click="openInMaps">🗺 Open in Google Maps</button>
        </div>
        <p class="hint" style="font-size: 0.7rem; color: var(--muted-2)">
          Or right-click any spot in Google Maps and the lat/lon pair appears
          at the top of the menu — paste below.
        </p>
        <div class="form-grid">
          <label>Latitude<input type="number" step="0.0001" v-model="editLat" placeholder="e.g. 38.9881" /></label>
          <label>Longitude<input type="number" step="0.0001" v-model="editLon" placeholder="e.g. -94.7625" /></label>
          <label>City<input v-model="editCity" placeholder="optional" /></label>
          <label>State<input v-model="editState" placeholder="KS / MO / …" maxlength="8" /></label>
        </div>
        <p v-if="editError" class="err">{{ editError }}</p>
        <div class="actions">
          <button class="primary" :disabled="editSaving" @click="saveEdit">
            {{ editSaving ? "Saving…" : "Save" }}
          </button>
          <button class="ghost" @click="closeEdit">Cancel</button>
        </div>
      </div>
    </div>
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
.card.has_loc { cursor: pointer; transition: border-color 0.12s; }
.card.has_loc:hover { border-color: var(--accent, #ef4444); }
.nav-ic { color: var(--muted-2); margin-left: 0.4rem; vertical-align: middle; }
.loc { color: var(--muted); }
.loc.nopin { color: #f59e0b; }
.visits { color: #22c55e; font-weight: 500; }
.header-actions { display: flex; gap: 0.5rem; }
.edit-pin { color: var(--muted-2); }
.edit-pin:hover { color: var(--accent, #ef4444); }

.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 100;
  display: flex; justify-content: flex-end; }
.edit-drawer {
  width: min(420px, 100%); height: 100%; overflow-y: auto;
  background: var(--bg-1); border-left: 1px solid var(--line);
  padding: 1rem 1.2rem;
}
.edit-drawer header { display: flex; justify-content: space-between; align-items: center; }
.edit-drawer header h2 { margin: 0; font-size: 1rem; color: var(--text); }
.edit-drawer .close { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.1rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; margin-top: 1rem; }
.form-grid label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.78rem; color: var(--muted); }
.form-grid input {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 0.4rem 0.55rem; color: var(--text);
  font-family: inherit;
}
.quick-actions { display: flex; gap: 0.4rem; margin: 0.5rem 0 0.6rem; flex-wrap: wrap; }
.quick-actions .ghost { padding: 0.4rem 0.7rem; font-size: 0.78rem; }

.actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.actions .primary {
  background: var(--accent, #ef4444); color: #fff; border: none;
  padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer;
}
.actions .primary:disabled { opacity: 0.6; cursor: not-allowed; }
.actions .ghost {
  background: transparent; color: var(--muted); border: 1px solid var(--line);
  padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer;
}

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
