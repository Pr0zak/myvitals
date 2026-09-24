/**
 * SETTINGS-B2 — rendering helpers for integration status.
 *
 * Every verdict here (status, error kind, the action text, "importing
 * nothing") is decided by the SERVER in `analytics/data_health.py`. These
 * helpers only map a server value to a label and a pill colour; none of
 * them decides whether something is broken.
 */
import type { IntegrationHealth } from "@/api/types";

/** Route key (`/settings/integrations/:key`) → the data-health key.
 *  Home Assistant and Trail status are not in `/query/data-health`, so
 *  their pages report their own status instead. */
export const HEALTH_KEY: Record<string, string | undefined> = {
  strava: "strava",
  google: "google_health",
  concept2: "concept2",
};

export interface IntegrationMeta {
  key: string;
  name: string;
  blurb: string;
}

/** Plain-language names — "Trail status", not "DNIS". */
export const INTEGRATIONS: IntegrationMeta[] = [
  { key: "strava", name: "Strava", blurb: "Rides and runs, with GPS maps" },
  { key: "google", name: "Google Health", blurb: "Watch data straight from Google, including SpO2 and skin temperature" },
  { key: "concept2", name: "Concept2", blurb: "Rowing machine sessions" },
  { key: "homeassistant", name: "Home Assistant", blurb: "Watch battery, charger and on-body status" },
  { key: "trails", name: "Trail status", blurb: "Open / closed status for your local trails" },
];

export type PillTone = "ok" | "warn" | "neutral" | "mut";

export function statusPill(h: IntegrationHealth): { label: string; tone: PillTone } {
  switch (h.status) {
    case "ok": return { label: "Connected", tone: "ok" };
    case "stale": return { label: "Stale", tone: "warn" };
    // Amber, never rose: a failed sync needs a person, it is not a crisis.
    case "error": return { label: h.needs_reconnect ? "Reconnect" : "Needs attention", tone: "warn" };
    case "never": return { label: "Not synced yet", tone: "neutral" };
    default: return { label: "Not set up", tone: "mut" };
  }
}

/** Coarse human age from the server's hours. "never" for null — an
 *  absent timestamp is not an age of zero. */
export function ageText(hours: number | null | undefined): string {
  if (hours == null) return "never";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min ago`;
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** The server's `detail` when there is one, else the error's message. */
export function errText(e: unknown): string {
  const resp = (e && typeof e === "object" && "response" in e)
    ? (e as { response?: { status?: number; data?: { detail?: unknown } } }).response
    : null;
  const d = resp?.data?.detail;
  if (typeof d === "string" && d) return d;
  if (d != null) return JSON.stringify(d);
  if (resp?.status) return `HTTP ${resp.status}`;
  return e instanceof Error ? e.message : String(e);
}
