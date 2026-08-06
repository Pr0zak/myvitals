/**
 * One palette for "what kind of activity is this" — the web twin of
 * `android/.../ui/common/ActivityCategory.kt`. Both must agree, or the
 * same ride is blue on one surface and cyan on the other.
 *
 * The neon hexes are not new: `StrengthHistory.vue` already maps
 * strength→magenta, yoga→periwinkle, cardio→cyan in the neon skin. The
 * classic hexes are the ones the old Android calendar drew.
 */
export type ActivityCategoryKey =
  | "strength" | "yoga" | "ride" | "run" | "walk" | "row" | "other";

export interface CategoryMeta {
  label: string;
  /** 1-based, used as the heatmap's numeric bucket for the piecewise visualMap. */
  index: number;
  classic: string;
  neon: string;
}

export const CATEGORY_META: Record<ActivityCategoryKey, CategoryMeta> = {
  strength: { label: "Strength", index: 1, classic: "#ef4444", neon: "#ff3ad8" },
  yoga:     { label: "Yoga",     index: 2, classic: "#a78bfa", neon: "#6f7bff" },
  ride:     { label: "Ride",     index: 3, classic: "#38bdf8", neon: "#28e6ff" },
  run:      { label: "Run",      index: 4, classic: "#22c55e", neon: "#5dff3b" },
  walk:     { label: "Walk",     index: 5, classic: "#f59e0b", neon: "#ffb52e" },
  // Teal, deliberately distinct from ride's cyan at calendar-cell size.
  row:      { label: "Row",      index: 6, classic: "#06b6d4", neon: "#2ee6c5" },
  other:    { label: "Other",    index: 7, classic: "#94a3b8", neon: "#9b9bb0" },
};

export const CATEGORY_BY_INDEX: Record<number, ActivityCategoryKey> =
  Object.fromEntries(
    (Object.keys(CATEGORY_META) as ActivityCategoryKey[])
      .map((k) => [CATEGORY_META[k].index, k]),
  ) as Record<number, ActivityCategoryKey>;

/**
 * Classify a raw activity `type`. Exact matches first (these are the ones
 * the old calendar recognised), then substring fallbacks so Strava's
 * VirtualRide / TrailRun and the MyFitnessPal labels stop landing in
 * "other". "run" is tested before "walk" — several MyFitnessPal labels
 * contain both words.
 */
export function categoryForType(
  type: string | null | undefined,
): ActivityCategoryKey {
  const t = (type ?? "").toLowerCase();
  switch (t) {
    case "ride": case "ebikeride": case "mountain_biking": case "cycling":
      return "ride";
    case "run": case "trailrun": case "running":
      return "run";
    case "hike": case "walk": case "walking":
      return "walk";
    case "rower": case "rowing": case "row":
      return "row";
  }
  if (!t) return "other";
  if (/kayak|row|paddle|canoe/.test(t)) return "row";
  if (/run|jog/.test(t)) return "run";
  if (/hike|walk/.test(t)) return "walk";
  if (/bike|cycl|ride/.test(t)) return "ride";
  if (/strength|weight|lifting/.test(t)) return "strength";
  if (/yoga|pilates|mobility/.test(t)) return "yoga";
  return "other";
}

/**
 * Classify a generated workout by split_focus. Cardio maps to "ride", not
 * "strength" — the feed already draws cardio days with a bike icon.
 */
export function categoryForSplitFocus(
  focus: string | null | undefined,
): ActivityCategoryKey {
  const f = (focus ?? "").toLowerCase();
  if (f === "yoga") return "yoga";
  if (f === "cardio") return "ride";
  return "strength";
}

export function categoryColor(k: ActivityCategoryKey, neon: boolean): string {
  const m = CATEGORY_META[k];
  return neon ? m.neon : m.classic;
}
