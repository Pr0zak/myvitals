<script setup lang="ts">
/**
 * TILE-1 — editor for the Key-metrics tile order and visibility.
 *
 * The preference this writes (`user_profile.extra.vitals_order` /
 * `.vitals_hidden`) is read by KeyMetrics.vue and the phone.
 *
 * Reordering uses explicit move buttons rather than HTML5 drag-and-drop.
 * Drag events do not fire on touch without a polyfill, and this is opened
 * from a phone-sized viewport as often as a desktop one — a control that
 * silently does nothing on half the devices is worse than a plainer one
 * that always works. The buttons are also keyboard-operable for free.
 *
 * SETTINGS-B1: AUTOSAVES, visibly. Every move or hide is sent after a
 * short pause (so five taps to move a tile down five places are one
 * request), the result is announced ("Saved" / an amber failure), and a
 * failed save PUTS THE LIST BACK to the last order the server accepted.
 * Leaving the edited order on screen after a failure would show an
 * arrangement the home screen is not using, which is the silent-autosave
 * failure the settings audit found.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { TilePrefOption } from "@/api/types";

const rows = ref<TilePrefOption[]>([]);
/** The last list the server confirmed — what a failure reverts to. */
let confirmed: TilePrefOption[] = [];
const loading = ref(true);
const loadError = ref<string | null>(null);
const state = ref<"idle" | "pending" | "saving" | "saved" | "failed">("idle");
const saveError = ref<string | null>(null);
let timer: ReturnType<typeof setTimeout> | null = null;

const emit = defineEmits<{ (e: "saved"): void }>();

async function load() {
  loading.value = true;
  loadError.value = null;
  try {
    const prefs = await api.getTilePrefs();
    rows.value = prefs.available;
    confirmed = prefs.available;
  } catch {
    loadError.value = "Couldn't load your Key-metrics settings.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
onBeforeUnmount(() => {
  // A change still waiting on its debounce is sent rather than dropped.
  if (timer) { clearTimeout(timer); void persist(); }
});

const visibleCount = computed(() => rows.value.filter((r) => !r.hidden).length);

function schedule() {
  state.value = "pending";
  saveError.value = null;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => { timer = null; void persist(); }, 600);
}

async function persist(reset = false) {
  state.value = "saving";
  const sent = rows.value;
  try {
    const prefs = reset
      ? await api.putTilePrefs([], [])
      : await api.putTilePrefs(
        sent.map((r) => r.key),
        sent.filter((r) => r.hidden).map((r) => r.key),
      );
    confirmed = prefs.available;
    // Only adopt the server's list if nothing changed while in flight.
    if (rows.value === sent || reset) rows.value = prefs.available;
    state.value = timer ? "pending" : "saved";
    emit("saved");
  } catch (e) {
    if (timer) { clearTimeout(timer); timer = null; }
    rows.value = confirmed;
    state.value = "failed";
    saveError.value = `Couldn't save, so the list is back to how it was${
      e instanceof Error && e.message ? ` (${e.message})` : ""}.`;
  }
}

function move(i: number, delta: number) {
  const j = i + delta;
  if (j < 0 || j >= rows.value.length) return;
  const next = [...rows.value];
  [next[i], next[j]] = [next[j], next[i]];
  rows.value = next;
  schedule();
}

function toggle(i: number) {
  // Guarded here as well as server-side: hiding the last tile makes the
  // whole Key metrics section disappear, taking with it the Edit button
  // that leads back to this screen.
  if (!rows.value[i].hidden && visibleCount.value <= 1) return;
  const next = [...rows.value];
  next[i] = { ...next[i], hidden: !next[i].hidden };
  rows.value = next;
  schedule();
}

function reset() {
  // An empty order means "no preference"; the server reconciles that back
  // to the default sequence, so this needs no separate default list here.
  if (timer) { clearTimeout(timer); timer = null; }
  void persist(true);
}

const STATUS: Record<string, string> = {
  idle: "", pending: "Saving…", saving: "Saving…", saved: "Saved", failed: "",
};
</script>

<template>
  <div class="tile-editor">
    <p class="sf-lede">
      Which metrics appear in Key metrics on the home screen, and in what
      order. Changes save as you make them and apply to the phone app too.
    </p>

    <div v-if="loading" class="sf-mut">Loading…</div>
    <div v-else-if="loadError" class="sf-err" role="alert">
      {{ loadError }}
      <button type="button" class="sf-btn" @click="load">Retry</button>
    </div>

    <ul v-else class="tlist">
      <li v-for="(r, i) in rows" :key="r.key" :class="{ off: r.hidden }">
        <span class="grp">{{ r.group }}</span>
        <span class="name">{{ r.label }}<span v-if="r.hidden" class="hid"> · hidden</span></span>
        <div class="ctl">
          <button
            type="button" class="sf-btn icon" :disabled="i === 0"
            :aria-label="`Move ${r.label} up`" @click="move(i, -1)">↑</button>
          <button
            type="button" class="sf-btn icon" :disabled="i === rows.length - 1"
            :aria-label="`Move ${r.label} down`" @click="move(i, 1)">↓</button>
          <button
            type="button" class="sf-btn icon"
            :disabled="!r.hidden && visibleCount <= 1"
            :title="!r.hidden && visibleCount <= 1 ? 'At least one metric must stay visible' : undefined"
            :aria-label="`${r.hidden ? 'Show' : 'Hide'} ${r.label}`"
            :aria-pressed="!r.hidden"
            @click="toggle(i)">{{ r.hidden ? "○" : "●" }}</button>
        </div>
      </li>
    </ul>

    <div class="sf-actions">
      <button type="button" class="sf-btn" :disabled="loading || state === 'saving'" @click="reset">
        Reset to default
      </button>
      <span aria-live="polite" class="status">
        <span v-if="state === 'saved'" class="sf-ok">Saved</span>
        <span v-else-if="STATUS[state]" class="sf-mut">{{ STATUS[state] }}</span>
        <span v-if="state === 'failed'" class="sf-err" role="alert">{{ saveError }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.tlist { list-style: none; padding: 0; margin: 0; }
.tlist li {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas: "name ctl" "grp ctl";
  align-items: center;
  gap: 0 8px;
  padding: 8px 10px;
  border: 1px solid #23263a;
  border-radius: 14px;
  margin-bottom: 6px;
  background: #1e2230;
}
.tlist li.off { opacity: .55; }
.name { grid-area: name; font-size: 14px; color: #ececf5; }
.hid { color: #9b9bb0; font-size: 12px; }
.grp { grid-area: grp; font-size: 11px; color: #9b9bb0; text-transform: uppercase; letter-spacing: .06em; }
.ctl { grid-area: ctl; display: flex; gap: 4px; }
.status { display: inline-flex; flex-wrap: wrap; gap: 8px; }
</style>
