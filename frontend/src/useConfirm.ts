import { ref } from "vue";

/**
 * A promise-returning confirmation, so `ConfirmDialog` can replace
 * `window.confirm` without restructuring the call sites — OG3-M5.
 *
 * The native confirm is synchronous: `if (!confirm(...)) return;` reads
 * top-to-bottom, and every call site in this app is written that way.
 * A rendered dialog is inherently asynchronous, and rewriting each caller
 * into a pair of callbacks would turn a presentational change into a
 * control-flow change across four functions — including `logFailed`, which
 * returns a boolean its own callers branch on so a timed-hold overlay can
 * keep its timer running when the user backs out.
 *
 * So the shape is preserved and only the `await` is added:
 *
 *     if (!(await ask({ title: "…", detail: "…" }))) return;
 *
 * Deliberately per-view rather than a global singleton. Two dialogs open at
 * once is not a state this app can reach, and a module-level instance would
 * need teardown on unmount to avoid a dialog outliving the view that asked
 * the question.
 */
export interface ConfirmRequest {
  title: string;
  /** The consequence, stated separately from the question. */
  detail?: string | null;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

export function useConfirm() {
  const open = ref(false);
  const request = ref<ConfirmRequest>({ title: "" });
  let resolver: ((ok: boolean) => void) | null = null;

  function ask(req: ConfirmRequest): Promise<boolean> {
    // A second ask while one is pending resolves the first as declined.
    // Unreachable in practice, but leaving a promise permanently unsettled
    // would hang the caller's `await` forever, which is a worse failure
    // than an extra "no".
    if (resolver) resolver(false);
    request.value = req;
    open.value = true;
    return new Promise<boolean>((resolve) => {
      resolver = resolve;
    });
  }

  function settle(ok: boolean) {
    open.value = false;
    const r = resolver;
    resolver = null;
    r?.(ok);
  }

  return {
    open,
    request,
    ask,
    onConfirm: () => settle(true),
    onCancel: () => settle(false),
  };
}
