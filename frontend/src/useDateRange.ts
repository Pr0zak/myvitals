/**
 * RANGE-1 — one range vocabulary, and the range in the URL.
 *
 * Before this, ten views each declared their own `type RangeKey` and
 * `const RANGES`, and they disagreed. Seven spelled a year `"1y"` and
 * three spelled it `"365d"` — the same window under two names, so a
 * saved or shared value from one screen meant nothing on another. Others
 * varied on whether "all" existed at all.
 *
 * The range also lived only in component state, so it reset on reload and
 * a link to a chart never carried what you were looking at.
 *
 * ## Scope
 *
 * This is deliberately phase 1 of the backlog item. The original entry
 * proposed arbitrary start/end dates with a picker on both surfaces, on
 * the premise that the backend was already ready for it. It is not:
 * `list_activities` has no `until` parameter, and activities_stats, the
 * cardio zone endpoints, `/ai/correlate` and `/ai/discoveries` are all
 * `days: int` anchored to now. That is four reworked endpoints and a new
 * control on two surfaces, for an app that already has seven presets and
 * a day picker. The presets are the part that was actually broken.
 */
import { computed, ref, watch, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";

/** The canonical vocabulary. Every view uses these keys. */
export type RangeKey = "24h" | "7d" | "30d" | "90d" | "1y" | "ytd" | "all";

export interface RangeOption {
  key: RangeKey;
  label: string;
  /** Trailing window length. `null` means unbounded or computed (ytd/all). */
  days: number | null;
}

export const RANGE_OPTIONS: Readonly<Record<RangeKey, RangeOption>> = {
  "24h": { key: "24h", label: "24h", days: 1 },
  "7d": { key: "7d", label: "7d", days: 7 },
  "30d": { key: "30d", label: "30d", days: 30 },
  "90d": { key: "90d", label: "90d", days: 90 },
  "1y": { key: "1y", label: "1y", days: 365 },
  "ytd": { key: "ytd", label: "YTD", days: null },
  "all": { key: "all", label: "All", days: null },
};

/**
 * Aliases from the vocabularies this replaces.
 *
 * Kept rather than removed: a bookmarked `?range=365d`, or a value some
 * other surface still writes, should resolve rather than silently fall
 * back to the default and show the user a different window than the one
 * they linked to.
 */
const ALIASES: Record<string, RangeKey> = {
  "365d": "1y",
  "1yr": "1y",
  "year": "1y",
  "1d": "24h",
  "today": "24h",
  "week": "7d",
  "month": "30d",
  "quarter": "90d",
};

/** Normalise any historical spelling to a canonical key, or null. */
export function normaliseRange(raw: unknown): RangeKey | null {
  if (typeof raw !== "string") return null;
  const k = raw.trim().toLowerCase();
  if (k in RANGE_OPTIONS) return k as RangeKey;
  return ALIASES[k] ?? null;
}

/** Build the option list for a view, in the order given. */
export function rangeOptions(keys: readonly RangeKey[]): RangeOption[] {
  return keys.map((k) => RANGE_OPTIONS[k]);
}

/** The `since` Date for a range, or null when unbounded.
 *
 *  Uses local midnight rather than "now minus N×86 400 000": a "7d"
 *  window that starts at 14:32 last Tuesday silently drops half of that
 *  Tuesday, and the boundary moves every time the page is opened.
 */
export function rangeSince(key: RangeKey, now: Date = new Date()): Date | null {
  const opt = RANGE_OPTIONS[key];
  if (key === "ytd") return new Date(now.getFullYear(), 0, 1);
  if (opt.days == null) return null;
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  // days-1 so a "7d" window is seven calendar days INCLUDING today, which
  // is what the label means to a reader.
  d.setDate(d.getDate() - (opt.days - 1));
  return d;
}

/**
 * A range that lives in the URL.
 *
 * `?range=30d` makes the window linkable and survive a reload. Uses
 * `router.replace` rather than `push`, so flipping between presets does
 * not fill the back stack with states the back button then walks through
 * one at a time.
 */
export function useDateRange(
  allowed: readonly RangeKey[],
  fallback: RangeKey,
  param = "range",
): {
  range: Ref<RangeKey>;
  options: RangeOption[];
  since: Ref<Date | null>;
  days: Ref<number | null>;
} {
  const route = useRoute();
  const router = useRouter();

  const initial =
    normaliseRange(route.query[param]) ?? fallback;
  const range = ref<RangeKey>(
    allowed.includes(initial) ? initial : fallback,
  ) as Ref<RangeKey>;

  watch(range, (v) => {
    if (route.query[param] === v) return;
    router.replace({ query: { ...route.query, [param]: v } });
  });

  // Back/forward navigation changes the query without touching the ref.
  watch(
    () => route.query[param],
    (v) => {
      const k = normaliseRange(v);
      if (k && allowed.includes(k) && k !== range.value) range.value = k;
    },
  );

  return {
    range,
    options: rangeOptions(allowed),
    since: computed(() => rangeSince(range.value)),
    days: computed(() => RANGE_OPTIONS[range.value].days),
  };
}
