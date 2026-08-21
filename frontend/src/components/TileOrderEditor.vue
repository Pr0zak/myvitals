<script setup lang="ts">
/**
 * TILE-1 — editor for the Key-metrics tile order and visibility.
 *
 * The preference this writes (`user_profile.extra.vitals_order` /
 * `.vitals_hidden`) has been read by KeyMetrics.vue and the phone for a
 * long time; nothing could set it. The "Edit" button on the Key metrics
 * header already routed here, to a Display pane that had no editor.
 *
 * Reordering uses explicit move buttons rather than HTML5 drag-and-drop.
 * Drag events do not fire on touch without a polyfill, and this pane is
 * opened from a phone-sized viewport as often as a desktop one — a
 * control that silently does nothing on half the devices is worse than a
 * plainer one that always works. The buttons are also keyboard-operable
 * for free.
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { TilePrefOption } from "@/api/types";

const rows = ref<TilePrefOption[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);
const savedAt = ref<number | null>(null);

const emit = defineEmits<{ (e: "saved"): void }>();

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const prefs = await api.getTilePrefs();
    rows.value = prefs.available;
  } catch {
    error.value = "Couldn't load tile settings.";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const visibleCount = computed(() => rows.value.filter((r) => !r.hidden).length);

function move(i: number, delta: number) {
  const j = i + delta;
  if (j < 0 || j >= rows.value.length) return;
  const next = [...rows.value];
  [next[i], next[j]] = [next[j], next[i]];
  rows.value = next;
}

function toggle(i: number) {
  // Guarded here as well as server-side: hiding the last tile makes the
  // whole Key metrics section disappear, taking with it the Edit button
  // that leads back to this screen.
  if (!rows.value[i].hidden && visibleCount.value <= 1) return;
  const next = [...rows.value];
  next[i] = { ...next[i], hidden: !next[i].hidden };
  rows.value = next;
}

async function save() {
  saving.value = true;
  error.value = null;
  try {
    const prefs = await api.putTilePrefs(
      rows.value.map((r) => r.key),
      rows.value.filter((r) => r.hidden).map((r) => r.key),
    );
    rows.value = prefs.available;
    savedAt.value = Date.now();
    emit("saved");
  } catch {
    error.value = "Couldn't save. Your changes are still here — try again.";
  } finally {
    saving.value = false;
  }
}

async function reset() {
  // An empty order means "no preference"; the server reconciles that back
  // to the default sequence, so this needs no separate default list here.
  saving.value = true;
  try {
    const prefs = await api.putTilePrefs([], []);
    rows.value = prefs.available;
    savedAt.value = Date.now();
    emit("saved");
  } catch {
    error.value = "Couldn't reset.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="tile-editor">
    <p class="lede">
      Which metrics appear in Key metrics on the home screen, and in what
      order. Applies to the phone app too.
    </p>

    <div v-if="loading" class="muted">Loading…</div>
    <div v-else-if="error && !rows.length" class="err">{{ error }}</div>

    <ul v-else class="tlist">
      <li v-for="(r, i) in rows" :key="r.key" :class="{ off: r.hidden }">
        <span class="grp">{{ r.group }}</span>
        <span class="name">{{ r.label }}</span>
        <div class="ctl">
          <button
            class="ico" :disabled="i === 0" title="Move up"
            :aria-label="`Move ${r.label} up`" @click="move(i, -1)">↑</button>
          <button
            class="ico" :disabled="i === rows.length - 1" title="Move down"
            :aria-label="`Move ${r.label} down`" @click="move(i, 1)">↓</button>
          <button
            class="ico eye"
            :disabled="!r.hidden && visibleCount <= 1"
            :title="r.hidden ? 'Show' : visibleCount <= 1 ? 'At least one metric must stay visible' : 'Hide'"
            :aria-label="`${r.hidden ? 'Show' : 'Hide'} ${r.label}`"
            @click="toggle(i)">{{ r.hidden ? "○" : "●" }}</button>
        </div>
      </li>
    </ul>

    <div class="actions">
      <button class="primary" :disabled="saving || loading" @click="save">
        {{ saving ? "Saving…" : "Save order" }}
      </button>
      <button :disabled="saving || loading" @click="reset">Reset to default</button>
      <span v-if="savedAt" class="ok">Saved</span>
      <span v-if="error && rows.length" class="err">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.tile-editor { margin-top: 0.5rem; }
.lede { color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.8rem; }
.tlist { list-style: none; padding: 0; margin: 0; }
.tlist li {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas: "name ctl" "grp ctl";
  align-items: center;
  gap: 0 0.5rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 8px;
  margin-bottom: 0.4rem;
  background: rgba(148, 163, 184, 0.04);
}
.tlist li.off { opacity: 0.45; }
.name { grid-area: name; font-size: 0.9rem; color: #e2e8f0; }
.grp { grid-area: grp; font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em; }
.ctl { grid-area: ctl; display: flex; gap: 0.25rem; }
.ico {
  width: 2rem; height: 2rem; border-radius: 6px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: transparent; color: #cbd5e1; cursor: pointer; font-size: 0.9rem;
}
.ico:disabled { opacity: 0.3; cursor: not-allowed; }
.ico:hover:not(:disabled) { background: rgba(148, 163, 184, 0.12); }
.ico:focus-visible { outline: 2px solid #38bdf8; outline-offset: 1px; }
.actions { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.9rem; flex-wrap: wrap; }
.ok { color: #4ade80; font-size: 0.8rem; }
.err { color: #f87171; font-size: 0.8rem; }
.muted { color: #64748b; font-size: 0.85rem; }
</style>
