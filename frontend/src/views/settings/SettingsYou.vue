<script setup lang="ts">
/**
 * Settings → You & goals — SETTINGS-B1. Phone twin: `SettingsYouScreen.kt`.
 *
 * Everything about the person in one place: body, heart, goals, home
 * location and fasting. Before this, the base step goal was on Profile
 * while its per-weekday overrides were under Display, fasting had its own
 * pane with its own Save, and the sleep goal field wrote a key analytics
 * never read (fixed server-side in d22c3dd).
 *
 * ONE save model. Every field edits a local draft; a sticky "Unsaved
 * changes · Discard / Save" bar appears while the draft differs from what
 * was loaded; Save sends ONLY what changed (PUT /profile applies only the
 * fields it is sent, since d22c3dd — so a field this page does not model,
 * like the weekly fasting target, can no longer be erased by saving it).
 * Success is a "Saved" toast; failure is amber text in the bar and the
 * edits stay put. Navigating away with edits asks first (UX-W8), and so
 * does closing the tab.
 *
 * Height is entered in the user's units (feet + inches under imperial)
 * and stored in centimetres, as before.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { api } from "@/api/client";
import type { StepsSchedule } from "@/api/types";
import { isImperial, units, weightToKg, weightUnit, weightVal } from "@/units";
import { useConfirm } from "@/useConfirm";
import NeonPage from "@/components/neon/NeonPage.vue";
import NeonEyebrow from "@/components/neon/NeonEyebrow.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import StepsScheduleEditor from "@/components/StepsScheduleEditor.vue";
import UnsavedBar from "@/components/settings/UnsavedBar.vue";
import SettingsToast from "@/components/settings/SettingsToast.vue";
import { useToast } from "@/components/settings/useToast";
import "@/components/settings/settingsForm.css";

type Profile = Awaited<ReturnType<typeof api.getProfile>>;

interface FastingPrefs {
  default_protocol: string;
  scheduled_mode_enabled: boolean;
  eating_window_start_h: number;
  eating_window_end_h: number;
  notifications_enabled: boolean;
  religious_calendar: string;
}

/** The editable shape. Profile columns + the three `extra` keys this page
 *  owns + the weekday schedule, flattened so one comparison finds every
 *  change. */
interface Form {
  birth_date: string | null;
  sex: string | null;
  height_cm: number | null;
  activity_level: string | null;
  max_hr: number | null;
  resting_hr_baseline: number | null;
  weight_goal_kg: number | null;
  steps_goal: number | null;
  sleep_goal_h: number | null;
  home_latitude: number | null;
  home_longitude: number | null;
  fasting: FastingPrefs;
  schedule: Record<string, string>;
}

const PROFILE_FIELDS = [
  "birth_date", "sex", "height_cm", "activity_level", "max_hr",
  "resting_hr_baseline", "weight_goal_kg", "home_latitude", "home_longitude",
] as const;

const profile = ref<Profile | null>(null);
const schedule = ref<StepsSchedule | null>(null);
const loadError = ref<string | null>(null);
const scheduleError = ref<string | null>(null);
const loading = ref(true);
const saving = ref(false);
const saveError = ref<string | null>(null);

const orig = ref<Form | null>(null);
const draft = reactive<Form>(emptyForm());
const toast = useToast();
const confirm = useConfirm();

function emptyForm(): Form {
  return {
    birth_date: null, sex: null, height_cm: null, activity_level: null,
    max_hr: null, resting_hr_baseline: null, weight_goal_kg: null,
    steps_goal: null, sleep_goal_h: null, home_latitude: null, home_longitude: null,
    fasting: {
      default_protocol: "16:8", scheduled_mode_enabled: false,
      eating_window_start_h: 12, eating_window_end_h: 20,
      notifications_enabled: true, religious_calendar: "none",
    },
    schedule: {},
  };
}

/** `v-model.number` leaves "" in an emptied number box; that means null. */
function n(v: unknown): number | null {
  if (v === "" || v == null) return null;
  const x = typeof v === "number" ? v : Number(v);
  return Number.isFinite(x) ? x : null;
}
function s(v: unknown): string | null {
  return v === "" || v == null ? null : String(v);
}

function normalized(f: Form): Form {
  return {
    birth_date: s(f.birth_date),
    sex: s(f.sex),
    height_cm: n(f.height_cm),
    activity_level: s(f.activity_level),
    max_hr: n(f.max_hr),
    resting_hr_baseline: n(f.resting_hr_baseline),
    weight_goal_kg: n(f.weight_goal_kg),
    steps_goal: n(f.steps_goal),
    sleep_goal_h: n(f.sleep_goal_h),
    home_latitude: n(f.home_latitude),
    home_longitude: n(f.home_longitude),
    fasting: {
      default_protocol: f.fasting.default_protocol,
      scheduled_mode_enabled: !!f.fasting.scheduled_mode_enabled,
      eating_window_start_h: Number(f.fasting.eating_window_start_h),
      eating_window_end_h: Number(f.fasting.eating_window_end_h),
      notifications_enabled: !!f.fasting.notifications_enabled,
      religious_calendar: f.fasting.religious_calendar,
    },
    schedule: Object.fromEntries(
      Object.entries(f.schedule).map(([k, v]) => [k, String(v ?? "").trim()]),
    ),
  };
}

function formFrom(p: Profile, sch: StepsSchedule | null): Form {
  const extra = (p.extra ?? {}) as Record<string, unknown>;
  const fp = (extra.fasting_prefs ?? {}) as Record<string, unknown>;
  return normalized({
    birth_date: p.birth_date, sex: p.sex, height_cm: p.height_cm,
    activity_level: p.activity_level, max_hr: p.max_hr,
    resting_hr_baseline: p.resting_hr_baseline, weight_goal_kg: p.weight_goal_kg,
    steps_goal: (extra.steps_goal as number | undefined) ?? null,
    sleep_goal_h: (extra.sleep_goal_h as number | undefined)
      ?? (extra.sleep_target_h as number | undefined) ?? null,
    home_latitude: p.home_latitude, home_longitude: p.home_longitude,
    fasting: {
      default_protocol: (fp.default_protocol as string | undefined) ?? "16:8",
      scheduled_mode_enabled: Boolean(fp.scheduled_mode_enabled),
      eating_window_start_h: (fp.eating_window_start_h as number | undefined) ?? 12,
      eating_window_end_h: (fp.eating_window_end_h as number | undefined) ?? 20,
      notifications_enabled: (fp.notifications_enabled as boolean | undefined) ?? true,
      religious_calendar: (fp.religious_calendar as string | undefined) ?? "none",
    },
    schedule: sch
      ? Object.fromEntries(sch.weekdays.map((k) => [k, sch.schedule[k] != null ? String(sch.schedule[k]) : ""]))
      : {},
  });
}

function adopt(f: Form) {
  orig.value = JSON.parse(JSON.stringify(f));
  Object.assign(draft, JSON.parse(JSON.stringify(f)));
  syncUnitText();
}

async function load() {
  loading.value = true;
  loadError.value = null;
  scheduleError.value = null;
  const [p, sch] = await Promise.allSettled([api.getProfile(), api.getStepsSchedule()]);
  if (p.status === "rejected") {
    loadError.value = p.reason instanceof Error ? p.reason.message : "Couldn't load your profile.";
    loading.value = false;
    return;
  }
  profile.value = p.value;
  if (sch.status === "fulfilled") schedule.value = sch.value;
  else scheduleError.value = "Couldn't load the weekday step goals, so they can't be edited right now.";
  adopt(formFrom(p.value, schedule.value));
  loading.value = false;
}
onMounted(load);

const current = computed(() => normalized(draft));
function same(a: unknown, b: unknown) { return JSON.stringify(a) === JSON.stringify(b); }
const dirty = computed(() => !!orig.value && !same(current.value, orig.value));

// ── Unit-aware inputs ────────────────────────────────────────────────
// Weight goal (stored kg) and height (stored cm) are typed in the user's
// units. Each box keeps its OWN text while you type and converts on input;
// deriving the box from the stored value on every keystroke would rewrite
// "2" as "2.0" under the cursor. The text is refreshed from the stored
// value only on load, discard and a units change, so merely viewing the
// page can never make it dirty.
const weightGoalText = ref("");
const heightFtText = ref("");
const heightInText = ref("");
const heightCmText = ref("");

function syncUnitText() {
  const w = weightVal(n(draft.weight_goal_kg));
  weightGoalText.value = w != null ? w.toFixed(1) : "";
  const cm = n(draft.height_cm);
  heightCmText.value = cm != null ? String(cm) : "";
  if (cm == null) {
    heightFtText.value = "";
    heightInText.value = "";
  } else {
    const total = Math.round((cm / 2.54) * 2) / 2;   // nearest half inch
    const ft = Math.floor(total / 12);
    heightFtText.value = String(ft);
    heightInText.value = String(total - ft * 12);
  }
}
watch(units, syncUnitText);

function val(e: Event): string { return (e.target as HTMLInputElement).value; }

function onWeightGoal(e: Event) {
  weightGoalText.value = val(e);
  const x = n(weightGoalText.value);
  draft.weight_goal_kg = x == null ? null : Math.round(weightToKg(x) * 1000) / 1000;
}
function onHeightCm(e: Event) {
  heightCmText.value = val(e);
  draft.height_cm = n(heightCmText.value);
}
function onHeightImperial(part: "ft" | "in", e: Event) {
  if (part === "ft") heightFtText.value = val(e); else heightInText.value = val(e);
  const ft = n(heightFtText.value);
  const inch = n(heightInText.value);
  if (ft == null && inch == null) { draft.height_cm = null; return; }
  draft.height_cm = Math.round(((ft ?? 0) * 12 + (inch ?? 0)) * 2.54 * 10) / 10;
}

// ── Heart zones (server-derived, read-only) ──────────────────────────
const zones = computed(() => profile.value?.derived?.hr_zones ?? []);
const heartEdited = computed(() =>
  !!orig.value && (current.value.max_hr !== orig.value.max_hr
    || current.value.birth_date !== orig.value.birth_date));
const ZONE_COLOR = ["#6f7bff", "#28e6ff", "#5dff3b", "#ffb52e", "#ff3ad8"];

// ── Home location ────────────────────────────────────────────────────
const homeQuery = ref("");
const geocoding = ref(false);
const locating = ref(false);
const locateError = ref<string | null>(null);
const geocodedLabel = ref<string | null>(null);

async function resolveHomeQuery() {
  const q = homeQuery.value.trim();
  if (!q) return;
  geocoding.value = true;
  locateError.value = null;
  geocodedLabel.value = null;
  try {
    const r = await api.geocodeHome(q);
    draft.home_latitude = Math.round(r.latitude * 1e6) / 1e6;
    draft.home_longitude = Math.round(r.longitude * 1e6) / 1e6;
    geocodedLabel.value = r.display_name ? `Matched: ${r.display_name}` : "Location found";
  } catch (e) {
    locateError.value = e instanceof Error ? e.message : "Couldn't find that place.";
  } finally {
    geocoding.value = false;
  }
}

async function useCurrentLocation() {
  if (!navigator.geolocation) {
    locateError.value = "This browser can't share its location.";
    return;
  }
  locating.value = true;
  locateError.value = null;
  geocodedLabel.value = null;
  try {
    const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true, timeout: 10000, maximumAge: 0,
      });
    });
    draft.home_latitude = Math.round(pos.coords.latitude * 1e6) / 1e6;
    draft.home_longitude = Math.round(pos.coords.longitude * 1e6) / 1e6;
  } catch (e) {
    locateError.value = (e as { message?: string })?.message ?? "Location denied or unavailable.";
  } finally {
    locating.value = false;
  }
}

function clearHome() {
  draft.home_latitude = null;
  draft.home_longitude = null;
  geocodedLabel.value = null;
}

// ── Save / discard ───────────────────────────────────────────────────
async function save() {
  if (!orig.value || !profile.value || !dirty.value || saving.value) return;
  saving.value = true;
  saveError.value = null;
  const now = current.value;
  const was = orig.value;
  try {
    const body: Record<string, unknown> = {};
    for (const f of PROFILE_FIELDS) {
      if (!same(now[f], was[f])) body[f] = now[f];
    }
    // `extra` merges server-side: send only the keys that changed, and an
    // explicit null to clear one (an absent key means "leave it alone").
    const extra: Record<string, unknown> = {};
    if (now.steps_goal !== was.steps_goal) {
      extra.steps_goal = now.steps_goal && now.steps_goal > 0 ? now.steps_goal : null;
    }
    if (now.sleep_goal_h !== was.sleep_goal_h) {
      extra.sleep_goal_h = now.sleep_goal_h && now.sleep_goal_h > 0 ? now.sleep_goal_h : null;
    }
    if (!same(now.fasting, was.fasting)) {
      // The merge is shallow, so fasting_prefs travels whole — on top of
      // whatever it held already, so a key the phone added survives.
      const prior = ((profile.value.extra ?? {}) as Record<string, unknown>).fasting_prefs;
      extra.fasting_prefs = { ...((prior ?? {}) as Record<string, unknown>), ...now.fasting };
    }
    if (Object.keys(extra).length) body.extra = extra;

    if (Object.keys(body).length) {
      profile.value = (await api.putProfile(body)) as Profile;
      // The profile half landed: record it, so a schedule failure below
      // leaves only the schedule unsaved.
      orig.value = { ...now, schedule: was.schedule };
    }
    if (schedule.value && !same(now.schedule, was.schedule)) {
      const payload: Record<string, number | null> = {};
      for (const [k, v] of Object.entries(now.schedule)) payload[k] = v === "" ? null : Number(v);
      schedule.value = await api.putStepsSchedule(payload);
    }
    adopt(formFrom(profile.value, schedule.value));
    toast.show("Saved");
  } catch (e) {
    saveError.value = `Couldn't save: ${e instanceof Error ? e.message : String(e)}. Your edits are still here.`;
  } finally {
    saving.value = false;
  }
}

function discard() {
  if (!orig.value) return;
  Object.assign(draft, JSON.parse(JSON.stringify(orig.value)));
  syncUnitText();
  saveError.value = null;
  geocodedLabel.value = null;
  locateError.value = null;
}

// ── Dirty guard (UX-W8) ──────────────────────────────────────────────
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true;
  return await confirm.ask({
    title: "Leave without saving?",
    detail: "You have changes on this page that haven't been saved.",
    confirmLabel: "Discard changes",
    cancelLabel: "Keep editing",
  });
});
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!dirty.value) return;
  e.preventDefault();
  e.returnValue = "";
}
onMounted(() => window.addEventListener("beforeunload", onBeforeUnload));
onBeforeUnmount(() => window.removeEventListener("beforeunload", onBeforeUnload));

const scheduleModel = computed<Record<string, string>>({
  get: () => draft.schedule,
  set: (v) => { draft.schedule = v; },
});
</script>

<template>
  <NeonPage title="You & goals" back="/settings">
    <div v-if="loading" class="sf-mut">Loading…</div>

    <div v-else-if="loadError" class="sf-card" role="alert">
      <p class="sf-err">Couldn't load your profile: {{ loadError }}</p>
      <button type="button" class="sf-btn" @click="load">Retry</button>
    </div>

    <form v-else class="you" novalidate @submit.prevent="save">
      <!-- ── Body ─────────────────────────────────────────── -->
      <NeonEyebrow>Body</NeonEyebrow>
      <section class="sf-card">
        <p class="sf-lede">
          Used for your age-based heart-rate estimate, BMI and calorie targets.
          It stays on your own server.
        </p>
        <div class="sf-grid">
          <label class="sf-field">
            <span class="sf-label">Birth date</span>
            <input v-model="draft.birth_date" class="sf-input" type="date" />
          </label>
          <label class="sf-field">
            <span class="sf-label">Sex</span>
            <select v-model="draft.sex" class="sf-select">
              <option :value="null">Not set</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
          </label>
          <div v-if="isImperial" class="sf-field">
            <span id="height-lbl" class="sf-label">Height</span>
            <div class="sf-inline" role="group" aria-labelledby="height-lbl">
              <label class="sf-unit">
                <input :value="heightFtText" class="sf-input" type="number" min="3" max="8" step="1"
                       inputmode="numeric" aria-label="Height, feet" @input="onHeightImperial('ft', $event)" />
                <span>ft</span>
              </label>
              <label class="sf-unit">
                <input :value="heightInText" class="sf-input" type="number" min="0" max="11.5" step="0.5"
                       inputmode="decimal" aria-label="Height, inches" @input="onHeightImperial('in', $event)" />
                <span>in</span>
              </label>
            </div>
          </div>
          <label v-else class="sf-field">
            <span class="sf-label">Height</span>
            <span class="sf-unit">
              <input :value="heightCmText" class="sf-input" type="number" min="50" max="250"
                     step="0.1" inputmode="decimal" @input="onHeightCm" />
              <span>cm</span>
            </span>
          </label>
          <label class="sf-field">
            <span class="sf-label">Activity level</span>
            <select v-model="draft.activity_level" class="sf-select">
              <option :value="null">Not set</option>
              <option value="sedentary">Sedentary</option>
              <option value="light">Light (1–3× a week)</option>
              <option value="moderate">Moderate (3–5× a week)</option>
              <option value="active">Active (6–7× a week)</option>
              <option value="athlete">Athlete (twice a day)</option>
            </select>
          </label>
        </div>
      </section>

      <!-- ── Heart ────────────────────────────────────────── -->
      <NeonEyebrow>Heart</NeonEyebrow>
      <section class="sf-card">
        <div class="sf-grid">
          <label class="sf-field">
            <span class="sf-label">Max heart rate</span>
            <span class="sf-unit">
              <input v-model.number="draft.max_hr" class="sf-input" type="number" min="120" max="230"
                     inputmode="numeric"
                     :placeholder="profile?.derived?.max_hr_estimated != null
                       ? `about ${profile.derived.max_hr_estimated} from your age` : 'estimated from age'" />
              <span>bpm</span>
            </span>
            <span class="sf-help">
              Every heart-rate zone is a percentage of this. A number measured in a
              hard effort beats the age estimate; leave blank to keep the estimate.
            </span>
          </label>
          <label class="sf-field">
            <span class="sf-label">Resting heart rate</span>
            <span class="sf-unit">
              <input v-model.number="draft.resting_hr_baseline" class="sf-input" type="number" min="30"
                     max="120" inputmode="numeric"
                     :placeholder="profile?.derived?.resting_hr_baseline_auto != null
                       ? `about ${profile.derived.resting_hr_baseline_auto.toFixed(0)} from the last 30 days`
                       : 'worked out from your data'" />
              <span>bpm</span>
            </span>
            <span class="sf-help">Leave blank to use the value worked out from your watch.</span>
          </label>
        </div>

        <div v-if="zones.length" class="zones" aria-label="Heart-rate zones">
          <div class="sf-label">Your zones</div>
          <ul>
            <li v-for="z in zones" :key="z.zone" :style="{ '--zc': ZONE_COLOR[z.zone - 1] ?? '#9b9bb0' }">
              <span class="zn">Z{{ z.zone }}</span>
              <span class="zl">{{ z.label }}</span>
              <span class="zr sf-mono">{{ z.low }}–{{ z.high }}</span>
            </li>
          </ul>
          <p class="sf-help">
            <template v-if="heartEdited">These are from your saved values — save to update them.</template>
            <template v-else-if="profile?.derived?.max_hr_source === 'estimated'">
              Based on the age estimate of your max heart rate.
            </template>
            <template v-else>Based on the max heart rate you entered.</template>
          </p>
        </div>
      </section>

      <!-- ── Goals ────────────────────────────────────────── -->
      <NeonEyebrow>Goals</NeonEyebrow>
      <section class="sf-card">
        <div class="sf-grid">
          <label class="sf-field">
            <span class="sf-label">Weight goal</span>
            <span class="sf-unit">
              <input :value="weightGoalText" class="sf-input" type="number" min="20" max="660" step="0.1"
                     inputmode="decimal" @input="onWeightGoal" />
              <span>{{ weightUnit }}</span>
            </span>
          </label>
          <label class="sf-field">
            <span class="sf-label">Sleep goal</span>
            <span class="sf-unit">
              <input v-model.number="draft.sleep_goal_h" class="sf-input" type="number" min="4" max="12"
                     step="0.25" inputmode="decimal" placeholder="8" />
              <span>hours</span>
            </span>
          </label>
          <label class="sf-field">
            <span class="sf-label">Daily steps goal</span>
            <input v-model.number="draft.steps_goal" class="sf-input" type="number" min="1000" step="500"
                   inputmode="numeric" :placeholder="schedule ? String(schedule.base) : '10000'" />
          </label>
        </div>
        <StepsScheduleEditor
          v-if="schedule"
          v-model="scheduleModel"
          :weekdays="schedule.weekdays"
          :base="current.steps_goal ?? schedule.base"
          :effective-today="schedule.effective_today" />
        <p v-else-if="scheduleError" class="sf-err">{{ scheduleError }}</p>
      </section>

      <!-- ── Home ─────────────────────────────────────────── -->
      <NeonEyebrow>Home location</NeonEyebrow>
      <section class="sf-card">
        <p class="sf-lede">
          Centres the activities map. Type an address, paste a Google Maps link or a
          “latitude, longitude” pair, or use where you are now.
        </p>
        <label class="sf-field">
          <span class="sf-label">Address or map link</span>
          <span class="sf-inline">
            <input v-model="homeQuery" class="sf-input" type="text" autocomplete="street-address"
                   @keydown.enter.prevent="resolveHomeQuery" />
            <button type="button" class="sf-btn" :disabled="geocoding || !homeQuery.trim()"
                    @click="resolveHomeQuery">
              {{ geocoding ? "Finding…" : "Find" }}
            </button>
          </span>
        </label>
        <p v-if="geocodedLabel" class="sf-ok" aria-live="polite">{{ geocodedLabel }}</p>
        <div class="sf-grid coords">
          <label class="sf-field">
            <span class="sf-label">Latitude</span>
            <input v-model.number="draft.home_latitude" class="sf-input" type="number" step="0.000001"
                   min="-90" max="90" inputmode="decimal" />
          </label>
          <label class="sf-field">
            <span class="sf-label">Longitude</span>
            <input v-model.number="draft.home_longitude" class="sf-input" type="number" step="0.000001"
                   min="-180" max="180" inputmode="decimal" />
          </label>
        </div>
        <div class="sf-actions">
          <button type="button" class="sf-btn" :disabled="locating" @click="useCurrentLocation">
            {{ locating ? "Locating…" : "Use current location" }}
          </button>
          <button v-if="current.home_latitude != null || current.home_longitude != null"
                  type="button" class="sf-btn" @click="clearHome">Clear</button>
          <span v-if="locateError" class="sf-err" role="alert">{{ locateError }}</span>
        </div>
      </section>

      <!-- ── Fasting ──────────────────────────────────────── -->
      <NeonEyebrow>Fasting</NeonEyebrow>
      <section class="sf-card">
        <p class="sf-lede">
          Your usual protocol is pre-selected on the Fasting page. Scheduled mode starts
          and ends fasts at your eating-window edges automatically; starting one by hand
          always wins.
        </p>
        <div class="sf-grid">
          <label class="sf-field">
            <span class="sf-label">Usual protocol</span>
            <select v-model="draft.fasting.default_protocol" class="sf-select">
              <option value="16:8">16:8 (16h fast, 8h eating)</option>
              <option value="18:6">18:6</option>
              <option value="20:4">20:4</option>
              <option value="omad">One meal a day (23:1)</option>
              <option value="extended_24">24-hour fast</option>
              <option value="extended_36">36-hour fast</option>
              <option value="extended_48">48-hour fast</option>
              <option value="extended_72">72-hour fast</option>
            </select>
          </label>
          <label class="sf-field">
            <span class="sf-label">Religious calendar</span>
            <select v-model="draft.fasting.religious_calendar" class="sf-select">
              <option value="none">None</option>
              <option value="ramadan">Ramadan (dawn-to-dusk fasts)</option>
              <option value="lent">Lent (40 days, abstinence-based)</option>
              <option value="yom_kippur">Yom Kippur (single 25h fast)</option>
            </select>
            <span class="sf-help">Adds fasts automatically on that tradition's dates.</span>
          </label>
        </div>
        <label class="sf-check">
          <input v-model="draft.fasting.scheduled_mode_enabled" type="checkbox" />
          <span>Start and end fasts on a schedule</span>
        </label>
        <div class="sf-grid">
          <label class="sf-field">
            <span class="sf-label">Eating window opens</span>
            <select v-model.number="draft.fasting.eating_window_start_h" class="sf-select"
                    :disabled="!draft.fasting.scheduled_mode_enabled">
              <option v-for="h in 24" :key="h - 1" :value="h - 1">{{ h - 1 }}:00</option>
            </select>
          </label>
          <label class="sf-field">
            <span class="sf-label">Eating window closes</span>
            <select v-model.number="draft.fasting.eating_window_end_h" class="sf-select"
                    :disabled="!draft.fasting.scheduled_mode_enabled">
              <option v-for="h in 24" :key="h" :value="h">{{ h }}:00</option>
            </select>
          </label>
        </div>
        <label class="sf-check">
          <input v-model="draft.fasting.notifications_enabled" type="checkbox" />
          <span>Milestone notifications on the phone (ketosis, autophagy…)</span>
        </label>
      </section>

      <UnsavedBar v-if="dirty" :saving="saving" :error="saveError" @save="save" @discard="discard" />
    </form>

    <SettingsToast :message="toast.message.value" />
    <ConfirmDialog :open="confirm.open.value" :title="confirm.request.value.title"
                   :detail="confirm.request.value.detail"
                   :confirm-label="confirm.request.value.confirmLabel"
                   :cancel-label="confirm.request.value.cancelLabel"
                   @confirm="confirm.onConfirm" @cancel="confirm.onCancel" />
  </NeonPage>
</template>

<style scoped>
.zones { margin-top: 14px; }
.zones ul { list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 6px; }
.zones li { display: grid; grid-template-columns: 38px 1fr auto; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 12px; background: color-mix(in srgb, var(--zc) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--zc) 30%, transparent); }
.zn { font-weight: 800; color: var(--zc); font-family: 'Space Grotesk', 'Geist Mono', monospace; }
.zl { font-size: 13.5px; }
.zr { font-size: 13.5px; color: #ececf5; }
.coords { margin-top: 10px; }
</style>
