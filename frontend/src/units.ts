/**
 * App-wide unit preference + formatters.
 *
 * The backend always stores SI (meters, kg, °C). Everything user-facing
 * goes through these helpers so a single `units` ref flips the entire
 * dashboard between metric and imperial without touching individual
 * components' formatting logic.
 */
import { computed, ref, watch } from "vue";

const KEY = "myvitals.units";
type Units = "metric" | "imperial";

export const units = ref<Units>(
  (localStorage.getItem(KEY) as Units | null) ?? "imperial",
);
watch(units, (v) => localStorage.setItem(KEY, v));

const M_PER_MILE = 1609.344;
const M_PER_FT = 0.3048;
const KG_PER_LB = 0.45359237;

export const isImperial = computed(() => units.value === "imperial");

// ---- Distance ----------------------------------------------------

/** "12.4 km" / "7.7 mi" — nullable input passes through. */
export function fmtDistance(meters: number | null | undefined, digits = 2): string {
  if (meters == null) return "—";
  if (units.value === "imperial") {
    const mi = meters / M_PER_MILE;
    return `${mi.toFixed(digits)} mi`;
  }
  const km = meters / 1000;
  return `${km.toFixed(digits)} km`;
}

/** Numeric distance in user's preferred unit (km or mi). */
export function distanceVal(meters: number | null | undefined): number | null {
  if (meters == null) return null;
  return units.value === "imperial" ? meters / M_PER_MILE : meters / 1000;
}

export const distanceUnit = computed(() => isImperial.value ? "mi" : "km");

// ---- Elevation ---------------------------------------------------

export function fmtElevation(meters: number | null | undefined): string {
  if (meters == null) return "—";
  if (units.value === "imperial") {
    return `${Math.round(meters / M_PER_FT).toLocaleString()} ft`;
  }
  return `${Math.round(meters).toLocaleString()} m`;
}

export const elevationUnit = computed(() => isImperial.value ? "ft" : "m");

export function elevationVal(meters: number | null | undefined): number | null {
  if (meters == null) return null;
  return units.value === "imperial" ? meters / M_PER_FT : meters;
}

// ---- Weight ------------------------------------------------------

export function fmtWeight(kg: number | null | undefined, digits = 1): string {
  if (kg == null) return "—";
  if (units.value === "imperial") {
    const lb = kg / KG_PER_LB;
    return `${lb.toFixed(digits)} lb`;
  }
  return `${kg.toFixed(digits)} kg`;
}

export function weightVal(kg: number | null | undefined): number | null {
  if (kg == null) return null;
  return units.value === "imperial" ? kg / KG_PER_LB : kg;
}

/** Convert a user-entered value (in their preferred unit) BACK to kg for storage. */
export function weightToKg(val: number): number {
  return units.value === "imperial" ? val * KG_PER_LB : val;
}

export const weightUnit = computed(() => isImperial.value ? "lb" : "kg");

// ---- Temperature -------------------------------------------------

export function fmtTempDelta(celsius: number | null | undefined, digits = 2): string {
  if (celsius == null) return "—";
  // Delta semantics: convert magnitude only, not absolute. ΔF = ΔC * 9/5.
  if (units.value === "imperial") {
    return `${(celsius * 1.8).toFixed(digits)} ΔF`;
  }
  return `${celsius.toFixed(digits)} ΔC`;
}

export const tempUnit = computed(() => isImperial.value ? "ΔF" : "ΔC");

// ---- Pace --------------------------------------------------------

/** Returns minutes per km (metric) or minutes per mile (imperial). */
export function fmtPace(meters_per_s: number | null | undefined): string {
  if (meters_per_s == null || meters_per_s <= 0) return "—";
  const secPerUnit = units.value === "imperial"
    ? M_PER_MILE / meters_per_s
    : 1000 / meters_per_s;
  const m = Math.floor(secPerUnit / 60);
  const s = Math.round(secPerUnit % 60);
  return `${m}:${s.toString().padStart(2, "0")} /${distanceUnit.value}`;
}
