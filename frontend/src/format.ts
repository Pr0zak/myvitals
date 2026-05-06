/**
 * Centralised time / date formatters. All user-facing time displays go
 * through these so the 12-hour preference is consistent and we don't have
 * to chase `hour12: true` flags across every component.
 */

const TIME_OPTS: Intl.DateTimeFormatOptions = {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
};

const DATETIME_OPTS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
};

const DATETIME_WITH_SEC_OPTS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
  hour12: true,
};

function asDate(d: Date | string | number): Date {
  return d instanceof Date ? d : new Date(d);
}

/** "7:35 PM" */
export function fmtTime(d: Date | string | number): string {
  return asDate(d).toLocaleTimeString([], TIME_OPTS);
}

/** "May 6, 2026, 7:35 PM" */
export function fmtDateTime(d: Date | string | number): string {
  return asDate(d).toLocaleString([], DATETIME_OPTS);
}

/** "May 6, 2026, 7:35:42 PM" — for diagnostic / log views */
export function fmtDateTimeWithSec(d: Date | string | number): string {
  return asDate(d).toLocaleString([], DATETIME_WITH_SEC_OPTS);
}
