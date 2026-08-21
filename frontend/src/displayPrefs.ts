/**
 * DISP-1 — display preferences, server-persisted.
 *
 * Units, time format and theme were localStorage-only: they did not
 * survive clearing browser data, did not follow the user to another
 * browser, and the phone had no equivalent at all (it hardcoded
 * `/ 1609.34` in twelve places). They now live in
 * `user_profile.extra.display` and both surfaces read the same value.
 *
 * localStorage stays as the FIRST paint. Waiting for a round-trip before
 * knowing the theme would flash the wrong one on every load, and waiting
 * before knowing the units would render kilometres to someone who reads
 * miles for a few hundred milliseconds. So: render from the local cache
 * immediately, fetch in parallel, and reconcile — the same
 * stale-while-revalidate rule the phone follows for everything else.
 *
 * The write is a scoped PUT that merges. `PUT /profile` replaces `extra`
 * wholesale, so saving a preference through it would erase any it did not
 * carry forward.
 */
import { watch } from "vue";
import { api } from "@/api/client";
import { units } from "@/units";
import { timeFormat } from "@/format";
import { themeChoice } from "@/theme";

/** Set while applying a server value, so the watchers below do not treat
 *  a hydration as a user edit and immediately PUT it straight back. */
let hydrating = false;

export interface DisplayPrefs {
  units: "metric" | "imperial";
  time_format: "auto" | "12h" | "24h";
  theme: string;
}

/**
 * Pull the server's preferences and apply them.
 *
 * Deliberately quiet on failure: an unreachable backend, or one older
 * than v0.11.1 that 404s this route, should leave the locally cached
 * preferences exactly as they are rather than resetting them to defaults.
 */
export async function hydrateDisplayPrefs(): Promise<void> {
  let prefs: DisplayPrefs;
  try {
    prefs = await api.getDisplayPrefs();
  } catch {
    return;
  }
  hydrating = true;
  try {
    if (prefs.units && prefs.units !== units.value) units.value = prefs.units;
    if (prefs.time_format && prefs.time_format !== timeFormat.value) {
      timeFormat.value = prefs.time_format;
    }
    if (prefs.theme && prefs.theme !== themeChoice.value) {
      themeChoice.value = prefs.theme as typeof themeChoice.value;
    }
  } finally {
    // Cleared on the next tick rather than immediately: the refs above are
    // watched, and Vue flushes those watchers after this synchronous block.
    // Clearing the flag here would let the hydration echo back as a PUT.
    setTimeout(() => { hydrating = false; }, 0);
  }
}

/** Push a single changed preference. Partial by design — the endpoint
 *  merges, so this cannot clobber a preference set on the phone. */
async function push(patch: Partial<DisplayPrefs>): Promise<void> {
  if (hydrating) return;
  try {
    await api.putDisplayPrefs(patch);
  } catch {
    // The local value already applied; a failed sync must not revert what
    // the user just chose in front of them.
  }
}

/** Call once at app start, after the token is known. */
export function startDisplayPrefsSync(): void {
  watch(units, (v) => push({ units: v }));
  watch(timeFormat, (v) => push({ time_format: v }));
  watch(themeChoice, (v) => push({ theme: v }));
  void hydrateDisplayPrefs();
}
