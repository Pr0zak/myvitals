import { ref, watch } from "vue";

/**
 * Centralised time / date formatters. Whether to render times in 12h or
 * 24h is a user preference, persisted in localStorage; "auto" defers to
 * the OS locale. All user-facing time displays go through these helpers.
 */

export type TimeFormat = "auto" | "12h" | "24h";

const KEY = "myvitals.time_format";

function loadInitial(): TimeFormat {
  const v = localStorage.getItem(KEY);
  return v === "12h" || v === "24h" || v === "auto" ? v : "auto";
}

export const timeFormat = ref<TimeFormat>(loadInitial());
watch(timeFormat, (v) => localStorage.setItem(KEY, v));

function hour12(): boolean | undefined {
  // Returning undefined lets toLocale*() defer to the OS locale.
  if (timeFormat.value === "12h") return true;
  if (timeFormat.value === "24h") return false;
  return undefined;
}

function asDate(d: Date | string | number): Date {
  return d instanceof Date ? d : new Date(d);
}

function timeOpts(): Intl.DateTimeFormatOptions {
  return { hour: "numeric", minute: "2-digit", hour12: hour12() };
}

function dateTimeOpts(): Intl.DateTimeFormatOptions {
  return {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: hour12(),
  };
}

function dateTimeWithSecOpts(): Intl.DateTimeFormatOptions {
  return {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", second: "2-digit", hour12: hour12(),
  };
}

/** "7:35 PM" (12h) or "19:35" (24h). */
export function fmtTime(d: Date | string | number): string {
  return asDate(d).toLocaleTimeString([], timeOpts());
}

/** "May 6, 2026, 7:35 PM" (12h) or "May 6, 2026, 19:35" (24h). */
export function fmtDateTime(d: Date | string | number): string {
  return asDate(d).toLocaleString([], dateTimeOpts());
}

/** With seconds — for diagnostic / log views. */
export function fmtDateTimeWithSec(d: Date | string | number): string {
  return asDate(d).toLocaleString([], dateTimeWithSecOpts());
}
