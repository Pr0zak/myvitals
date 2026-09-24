import { onBeforeUnmount, ref } from "vue";

/**
 * A short confirmation ("Saved") that clears itself — SETTINGS-B1.
 * Paired with SettingsToast.vue. Per-view, like `useConfirm`.
 */
export function useToast(ms = 2400) {
  const message = ref<string | null>(null);
  let handle: ReturnType<typeof setTimeout> | null = null;
  function show(text: string) {
    message.value = text;
    if (handle) clearTimeout(handle);
    handle = setTimeout(() => { message.value = null; }, ms);
  }
  onBeforeUnmount(() => { if (handle) clearTimeout(handle); });
  return { message, show };
}
