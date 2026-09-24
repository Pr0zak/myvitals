/**
 * SETTINGS-B1 — small wording helpers shared by the settings pages.
 * Formatting only: no number a user reads is computed here.
 */

/** "just now" / "12m ago" / "3h ago" / "2d ago" from an ISO timestamp. */
export function relTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** "claude-haiku-4-5-20251001" → "Claude Haiku". Unknown ids pass through. */
export function modelLabel(model: string | null | undefined): string {
  if (!model) return "—";
  const m = model.toLowerCase();
  if (m.includes("haiku")) return "Claude Haiku";
  if (m.includes("sonnet")) return "Claude Sonnet";
  if (m.includes("opus")) return "Claude Opus";
  return model;
}
