/**
 * Keep the screen on while a workout is running — OG2-A8.
 *
 * The web had no wake lock at all, so the browser slept between sets and the
 * phone had to be unlocked to log the next one. The Compose app has held the
 * screen since it shipped, which made this a parity gap nobody had written
 * down: the same session behaved differently depending on which surface you
 * ran it from.
 *
 * The awkward part of the browser API, and the reason this is a module rather
 * than four lines in a component: **the browser releases the lock on its own
 * whenever the document stops being visible** — a tab switch, the app going
 * to the background, the screen being locked by hand. A one-shot `request()`
 * therefore works exactly once and then dies silently, which looks identical
 * to never having worked. So the INTENT is kept here and the lock is
 * re-acquired on every `visibilitychange` for as long as the intent stands.
 *
 * Refusals are swallowed deliberately. iOS declines in Low Power Mode and
 * some browsers decline on a low battery; there is nothing to do about it and
 * nothing the user could act on, so it stays quiet and tries again the next
 * time the document becomes visible.
 */

let sentinel: WakeLockSentinel | null = null;
let wanted = false;
/** A request is in flight. Without this, two quick calls stack two locks and
 *  releasing once leaves the screen pinned on. */
let pending = false;

export function wakeLockSupported(): boolean {
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
}

async function acquire(): Promise<void> {
  if (!wanted || sentinel || pending || !wakeLockSupported()) return;
  // `request()` rejects outright on a hidden document, so do not even ask.
  if (document.visibilityState !== "visible") return;
  pending = true;
  try {
    const s = await navigator.wakeLock.request("screen");
    if (!wanted) {
      // Released while the request was in flight. Holding it now would pin
      // the screen on with nothing left to turn it off.
      void s.release().catch(() => {});
      return;
    }
    sentinel = s;
    s.addEventListener("release", () => {
      if (sentinel === s) sentinel = null;
    });
  } catch {
    sentinel = null;
  } finally {
    pending = false;
  }
}

function onVisible(): void {
  if (document.visibilityState === "visible") void acquire();
}

export function requestWakeLock(): void {
  if (wanted) return;
  wanted = true;
  document.addEventListener("visibilitychange", onVisible);
  void acquire();
}

export function releaseWakeLock(): void {
  wanted = false;
  document.removeEventListener("visibilitychange", onVisible);
  const s = sentinel;
  sentinel = null;
  if (s) void s.release().catch(() => {});
}
