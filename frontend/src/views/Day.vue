<script setup lang="ts">
/**
 * DAY-1 — everything about one calendar day, at `/day/:date`.
 *
 * The day is in the URL rather than in component state, so a particular
 * day is linkable and survives a reload. `DayNav` already existed and
 * already tints the shell when you are not on today; this view is the
 * page that navigation was missing.
 *
 * All sections come from one `GET /summary/day` call. Each is
 * independently best-effort server-side, so a broken subsystem arrives as
 * `null` in its slot. That distinction is load-bearing here: null renders
 * as "couldn't load", never as a zero. Showing 0 steps for a day whose
 * step query failed is a lie the user has no way to detect.
 */
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Card from "@/components/Card.vue";
import DayNav from "@/components/DayNav.vue";
import { api } from "@/api/client";
import type { DaySnapshot } from "@/api/types";
import { isValidISODate, todayISO, fmtDayLabel } from "@/dates";
import { fmtDistance, fmtWeight } from "@/units";
import { fmtTime } from "@/format";

const route = useRoute();
const router = useRouter();

const snap = ref<DaySnapshot | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

/** The day from the URL, falling back to today for a missing or malformed
 *  param. `/day/banana` must not be forwarded to the API as a date. */
const day = computed<string>(() => {
  const p = route.params.date;
  const s = Array.isArray(p) ? p[0] : p;
  return isValidISODate(s) ? s : todayISO();
});

function setDay(v: string) {
  if (v !== day.value) router.replace({ name: "day", params: { date: v } });
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    snap.value = await api.summaryDay(day.value);
  } catch {
    error.value = "Couldn't load this day.";
    snap.value = null;
  } finally {
    loading.value = false;
  }
}
watch(day, load, { immediate: true });

const tiles = computed(() => snap.value?.tiles?.tiles ?? []);
const events = computed(() => snap.value?.events?.events ?? []);
const activities = computed(() => snap.value?.activities ?? []);
const annotations = computed(() => snap.value?.annotations ?? []);
const sleepNight = computed(() => {
  const nights = snap.value?.sleep ?? [];
  // The night that ENDED on this day — the server sends the window from
  // the previous evening, so the last entry is the relevant one.
  return nights.length ? nights[nights.length - 1] : null;
});

const stepsTotal = computed<number | null>(() => {
  const s = snap.value?.steps;
  if (!s) return null;                      // section failed — not zero
  if (typeof s.total === "number") return s.total;
  const pts = s.points ?? [];
  return pts.reduce((a, p) => a + (p.count ?? 0), 0);
});

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** A section that failed renders as this, never as an empty state — the
 *  two mean different things and only one is the user's fault. */
function sectionFailed(v: unknown): boolean {
  return v === null;
}
</script>

<template>
  <div class="day">
    <header class="head">
      <h1>{{ fmtDayLabel(day) }}</h1>
      <DayNav :model-value="day" @update:model-value="setDay"/>
    </header>

    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="error" class="err">{{ error }}</p>

    <template v-else-if="snap">
      <Card title="At a glance">
        <div class="glance">
          <div class="g">
            <div class="gv">{{ stepsTotal === null ? "—" : stepsTotal.toLocaleString() }}</div>
            <div class="gl">steps</div>
            <div v-if="sectionFailed(snap.steps)" class="gerr">couldn't load</div>
          </div>
          <div class="g">
            <div class="gv">{{ sleepNight ? fmtDuration(sleepNight.total_s) : "—" }}</div>
            <div class="gl">sleep</div>
            <div v-if="sectionFailed(snap.sleep)" class="gerr">couldn't load</div>
          </div>
          <div class="g">
            <div class="gv">{{ activities.length }}</div>
            <div class="gl">activities</div>
            <div v-if="sectionFailed(snap.activities)" class="gerr">couldn't load</div>
          </div>
          <div class="g">
            <div class="gv">{{ snap.workout ? "1" : "0" }}</div>
            <div class="gl">workout</div>
          </div>
        </div>
      </Card>

      <Card v-if="tiles.length" title="Metrics">
        <ul class="tiles">
          <li v-for="t in tiles" :key="t.key">
            <span class="tk">{{ t.label }}</span>
            <span class="tv">
              {{ t.value == null ? "—" : t.value }}<span v-if="t.unit" class="tu"> {{ t.unit }}</span>
            </span>
          </li>
        </ul>
      </Card>

      <Card v-if="snap.workout" title="Workout">
        <div class="wrow" @click="router.push('/workout/strength/today')">
          <span class="wfocus">{{ snap.workout.split_focus ?? "strength" }}</span>
          <span class="wstatus" :class="snap.workout.status">{{ snap.workout.status }}</span>
        </div>
        <p v-if="snap.workout.notes" class="wnotes">{{ snap.workout.notes }}</p>
      </Card>

      <Card v-if="activities.length" title="Activities">
        <ul class="acts">
          <li v-for="a in activities" :key="`${a.source}-${a.source_id}`"
              @click="router.push(`/activity/${a.source}/${a.source_id}`)">
            <div class="aname">{{ a.name || a.type }}</div>
            <div class="ameta">
              {{ fmtTime(a.start_at) }} · {{ fmtDuration(a.duration_s) }}
              <template v-if="a.distance_m"> · {{ fmtDistance(a.distance_m, 1) }}</template>
            </div>
          </li>
        </ul>
      </Card>

      <Card v-if="events.length" title="What happened">
        <ul class="events">
          <li v-for="(e, i) in events" :key="i">{{ (e as any).text ?? (e as any).title }}</li>
        </ul>
      </Card>

      <Card v-if="annotations.length" title="Journal">
        <ul class="notes">
          <li v-for="(n, i) in annotations" :key="i">
            <span class="ntime">{{ fmtTime((n as any).time) }}</span>
            {{ (n as any).text }}
          </li>
        </ul>
      </Card>

      <Card v-if="snap.weight?.points?.length" title="Body">
        <ul class="notes">
          <li v-for="(p, i) in snap.weight.points" :key="i">
            <span class="ntime">{{ fmtTime(p.time) }}</span>
            {{ fmtWeight(p.weight_kg) }}
          </li>
        </ul>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.day { padding-bottom: 2rem; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
h1 { margin: 0; font-size: 1.3rem; }

.glance { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 1rem; }
.g { min-width: 0; }
.gv { font-size: 1.5rem; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.gl { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted-2); }
/* A failed section is not an empty one. */
.gerr { font-size: 0.7rem; color: var(--warn, #f59e0b); }

.tiles, .acts, .events, .notes { list-style: none; margin: 0; padding: 0; }
.tiles li { display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid var(--surface-2); }
.tk { color: var(--muted); font-size: 0.88rem; }
.tv { color: var(--text); font-variant-numeric: tabular-nums; }
.tu { color: var(--muted-2); font-size: 0.8rem; }

.acts li { padding: 0.55rem 0; border-bottom: 1px solid var(--surface-2); cursor: pointer; }
.aname { color: var(--text); font-size: 0.92rem; }
.ameta { color: var(--muted-2); font-size: 0.78rem; }

.events li, .notes li { padding: 0.35rem 0; color: var(--text); font-size: 0.88rem; }
.ntime { color: var(--muted-2); font-size: 0.78rem; margin-right: 0.5rem; }

.wrow { display: flex; align-items: center; gap: 0.6rem; cursor: pointer; }
.wfocus { color: var(--text); text-transform: capitalize; }
.wstatus { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.1rem 0.4rem; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
.wstatus.completed { color: var(--good); border-color: var(--good); }
.wnotes { color: var(--muted); font-size: 0.85rem; margin: 0.5rem 0 0; }

.muted { color: var(--muted-2); }
.err { color: var(--bad); }
</style>
