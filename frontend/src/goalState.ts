/**
 * GOAL-STATE — rendering a goal that has moved the wrong way.
 *
 * A progress bar has one number and three meanings crammed into its zero:
 * "no reading yet", "on the starting line", and "you have gone backwards".
 * The third is the one worth knowing and the only one an empty bar cannot
 * say. A man five pounds heavier than when he set the goal saw the same
 * empty track as a man who set it this morning.
 *
 * `progress_state` and `state_tone` come from the server, and the tone in
 * particular is NOT derived here — for the same reason `analytics/compare.py`
 * owns `better` rather than letting each client decide which direction is
 * good. A client inferring "went down, therefore bad" would eventually
 * paint a broken sobriety streak as a warning.
 *
 * `progress_pct` is unchanged and still authoritative for the bar's width.
 */

export interface GoalStateish {
  progress_state?: string | null;
  state_tone?: string | null;
  delta_value?: number | null;
  baseline_value?: number | null;
  target_unit?: string | null;
}

export type GoalTone = "positive" | "neutral" | "caution" | "unknown";

/** Four tones, and nothing else gets through — an unrecognised value from
 *  a newer server must not become a CSS class that styles nothing. */
export function goalTone(g: GoalStateish): GoalTone {
  const t = g.state_tone;
  return t === "positive" || t === "neutral" || t === "caution" || t === "unknown"
    ? t
    : "neutral";
}

/** True when the goal has moved AWAY from its target by more than noise.
 *  Server-decided; the band is measured there, not guessed here. */
export function goalMovedAway(g: GoalStateish): boolean {
  return g.progress_state === "moved_away" && g.delta_value != null;
}

/**
 * "5.4 lb above start". Says the direction in words rather than leaning on
 * a sign, because a minus glyph in a small mono font is the easiest thing
 * on the screen to miss and the entire message is the direction.
 */
export function goalDeltaLabel(g: GoalStateish): string | null {
  const d = g.delta_value;
  if (d == null) return null;
  const unit = g.target_unit ? ` ${g.target_unit}` : "";
  const mag = Math.abs(d);
  const n = mag >= 10 ? mag.toFixed(0) : mag.toFixed(1);
  if (mag === 0) return `at start`;
  return `${n}${unit} ${d > 0 ? "above" : "below"} start`;
}

/** The short line a compact tile shows in place of a percentage that
 *  cannot distinguish "not started" from "gone backwards". */
export function goalStateNote(g: GoalStateish): string | null {
  switch (g.progress_state) {
    case "moved_away":
      return goalDeltaLabel(g);
    case "at_start":
      return "at your start";
    case "no_data":
      return "no reading yet";
    default:
      return null;
  }
}
