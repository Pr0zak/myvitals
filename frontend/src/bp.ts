/**
 * Blood-pressure categorisation — ONE implementation for the whole web app.
 *
 * There were two, and they disagreed. `BloodPressure.vue` had it right;
 * `Body.vue` tested stage 1 as `sys < 140 || dia < 90`, which is true for
 * 139/92 and so labelled a stage 2 reading "Elevated" — two categories low.
 * The phone had the same mistake, and so did the first cut of the backend
 * tiles endpoint.
 *
 * The rule that makes it easy to get wrong: a reading belongs to a category
 * if EITHER number reaches it, so the category is the HIGHER of the two.
 * Testing highest-first makes that structural instead of something you have
 * to reason about at each branch.
 *
 * Published reference ranges (AHA), not a diagnosis.
 */
export type BpCategory = "normal" | "elevated" | "stage1" | "stage2" | "crisis";

export function bpCategory(systolic: number, diastolic: number): BpCategory {
  if (systolic >= 180 || diastolic >= 120) return "crisis";
  if (systolic >= 140 || diastolic >= 90) return "stage2";
  if (systolic >= 130 || diastolic >= 80) return "stage1";
  if (systolic >= 120) return "elevated";
  return "normal";
}

const LABELS: Record<BpCategory, string> = {
  normal: "Normal",
  elevated: "Elevated",
  stage1: "Stage 1",
  stage2: "Stage 2",
  crisis: "Crisis",
};

export function bpCategoryLabel(systolic: number, diastolic: number): string {
  return LABELS[bpCategory(systolic, diastolic)];
}

/** Severity tone, so a stage 2 reading doesn't render in the same colour
 *  as a normal one just because the caller forgot to branch. */
export function bpTone(cat: BpCategory): string {
  switch (cat) {
    case "normal": return "#22c55e";
    case "elevated": return "#eab308";
    case "stage1": return "#f97316";
    case "stage2":
    case "crisis": return "#ef4444";
  }
}
