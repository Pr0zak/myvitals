/**
 * Muscle-group icon URL resolver.
 *
 * Backend serves 11 anatomical line icons (Noun Project, mostly Rafiico
 * Creative Studio + one Hafiz Nur Lutfianto for hamstrings) at
 * `/exercises/img/muscle/<name>/0.png`.
 *
 * The catalog's `primary_muscle` field has 17 distinct values; this
 * collapses synonyms onto the 11 buckets we actually have icons for.
 * Returns null when no icon is appropriate (e.g. "flexibility" on yoga
 * rows — those use YogaPoseIcon / image_front instead).
 */

const MUSCLE_ALIAS: Record<string, string> = {
  chest: "chest",
  back: "back",
  lats: "back",
  upper_back: "back",
  lower_back: "back",
  traps: "back",
  shoulders: "shoulders",
  neck: "shoulders",
  abs: "abs",
  abdominals: "abs",
  core: "abs",
  obliques: "abs",
  biceps: "biceps",
  triceps: "triceps",
  forearms: "forearms",
  glutes: "glutes",
  quads: "quads",
  quadriceps: "quads",
  hamstrings: "hamstrings",
  calves: "calves",
  // Intentionally NOT mapped — handled by YogaPoseIcon / image_front:
  // flexibility, hips, hip_flexors, balance, spine
};

export function muscleIcon(primary: string | null | undefined): string | null {
  if (!primary) return null;
  const key = MUSCLE_ALIAS[primary.toLowerCase()];
  if (!key) return null;
  // Same-origin: Caddy proxies /exercises/img/* to the backend mount.
  return `/exercises/img/muscle/${key}/0.png`;
}

/** Pretty label for the consolidated muscle bucket (for tooltip / aria). */
export function muscleLabel(primary: string | null | undefined): string {
  if (!primary) return "";
  const key = MUSCLE_ALIAS[primary.toLowerCase()];
  if (!key) return primary;
  return key.charAt(0).toUpperCase() + key.slice(1);
}
