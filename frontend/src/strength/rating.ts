/**
 * WP-16 set rating — the value stored in `StrengthSet.rating`. NOT RPE:
 * 1 Failed, 2 Hard, 3/4 Good, 5 Easy. Shared by StrengthToday (logging) and
 * StrengthDayView (history) so the two never word or colour it differently.
 */
export const RATING_BAD = "#ff5d7a";
export const RATING_AMBER = "#ffb52e";
export const RATING_LIME = "#5dff3b";
export const RATING_CYAN = "#28e6ff";

export function ratingLabel(r: number | null): string {
  if (r == null) return "—";
  return { 1: "Failed", 2: "Hard", 3: "Good", 4: "Good", 5: "Easy" }[r] ?? `RPE ${r}`;
}

export function ratingColor(r: number | null): string {
  if (r == null) return "#9b9bb0";
  return r === 1 ? RATING_BAD : r === 2 ? RATING_AMBER : r === 5 ? RATING_CYAN : RATING_LIME;
}
