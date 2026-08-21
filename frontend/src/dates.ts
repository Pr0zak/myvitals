/**
 * Local calendar-day helpers.
 *
 * Extracted from DayNav.vue, which had the only correct implementation in
 * the frontend while several other call sites had the broken one.
 *
 * The broken one is `d.toISOString().slice(0, 10)`. That converts to UTC
 * first, so for a `Date` built from local components it reports TOMORROW
 * for anyone west of Greenwich from early evening onward — 7pm Central,
 * in this app's case. It is the exact same class of bug the backend has
 * now shipped four separate times, and it is easy to miss because it is
 * correct for two-thirds of the day and in every UTC development
 * environment.
 *
 * Verified live in `api/client.ts:summaryRange`, where it shifted every
 * chart window forward a day each evening.
 */

/** A `Date` as a LOCAL `YYYY-MM-DD` string. */
export function toLocalISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Today as a local `YYYY-MM-DD` string. */
export function todayISO(): string {
  return toLocalISO(new Date());
}

/** Shift a `YYYY-MM-DD` string by whole days, staying in local time.
 *
 * Parsed via the numeric constructor rather than `new Date("2026-08-21")`,
 * which the spec says to treat as UTC midnight — so the naive version
 * lands on the previous day for negative offsets.
 */
export function addDaysISO(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y!, (m ?? 1) - 1, d ?? 1);
  dt.setDate(dt.getDate() + days);
  return toLocalISO(dt);
}

/** True when the string is a well-formed `YYYY-MM-DD` that names a real date.
 *
 *  Guards route params: `/day/banana` and `/day/2026-02-31` must not be
 *  handed to the API as though they were dates.
 */
export function isValidISODate(s: string | undefined | null): s is string {
  if (!s || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y!, (m ?? 1) - 1, d ?? 1);
  return (
    dt.getFullYear() === y && dt.getMonth() === (m ?? 1) - 1 && dt.getDate() === d
  );
}

/** "Wed, 21 Aug" — the compact form the day header and picker share. */
export function fmtDayLabel(iso: string): string {
  if (!isValidISODate(iso)) return iso;
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y!, (m ?? 1) - 1, d ?? 1).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}
