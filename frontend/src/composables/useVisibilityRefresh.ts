import { onMounted, onBeforeUnmount } from "vue";

/**
 * Re-runs `refresh()` when the page becomes visible after being hidden
 * for more than `staleAfterMs`. Replaces the "I came back to the tab
 * 2 hours later, why is the data stale" UX. Visible from the start
 * doesn't trigger — initial load is the caller's responsibility (this
 * composable only handles the resume path).
 */
export function useVisibilityRefresh(
  refresh: () => void | Promise<void>,
  staleAfterMs: number = 60_000,
): void {
  let hiddenAt: number | null = null;

  function onVisibilityChange() {
    if (document.visibilityState === "hidden") {
      hiddenAt = Date.now();
      return;
    }
    if (document.visibilityState === "visible" && hiddenAt != null) {
      const elapsed = Date.now() - hiddenAt;
      hiddenAt = null;
      if (elapsed >= staleAfterMs) {
        try { Promise.resolve(refresh()); } catch { /* swallow */ }
      }
    }
  }

  onMounted(() => {
    document.addEventListener("visibilitychange", onVisibilityChange);
  });
  onBeforeUnmount(() => {
    document.removeEventListener("visibilitychange", onVisibilityChange);
  });
}
