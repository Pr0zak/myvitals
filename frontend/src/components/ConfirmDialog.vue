<script setup lang="ts">
/**
 * A confirmation the page draws itself — OG3-M5.
 *
 * `window.confirm` was doing this job at seventeen call sites on web while
 * the phone used a Compose `AlertDialog` at nineteen. Two things are wrong
 * with that, and only one of them is cosmetic.
 *
 * The cosmetic half: a native confirm is rendered by the browser chrome, so
 * it ignores the app's theme entirely and reads as the page having handed
 * the user off to something else.
 *
 * The half that matters: it is a SYNCHRONOUS modal that blocks the whole
 * renderer, it cannot say more than one undifferentiated line, and it gives
 * the destructive action the same visual weight as the cancel. For "delete
 * set 3", which feeds the progression reducer and changes next session's
 * prescription, the consequence deserves to be stated separately from the
 * question — and the button that does it deserves to look like what it is.
 *
 * Deliberately NOT a general replacement. Only four call sites move here:
 * the two set operations that alter the progression history, and the two
 * goal operations that end or delete a goal. The other thirteen confirms
 * guard actions that are trivially reversible, and converting them would
 * grow this into the component library that has already been rejected once
 * for this project.
 */
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from "vue";

const props = withDefaults(defineProps<{
  open: boolean;
  title: string;
  /** The consequence, stated separately from the question. Optional —
   *  a confirm with nothing to add should not invent a second sentence. */
  detail?: string | null;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Renders the confirm button as destructive. Default true: everything
   *  routed here is destructive, and a caller that wants the gentle
   *  treatment has to say so. */
  destructive?: boolean;
}>(), {
  detail: null,
  confirmLabel: "Confirm",
  cancelLabel: "Cancel",
  destructive: true,
});

const emit = defineEmits<{
  (e: "confirm"): void;
  (e: "cancel"): void;
}>();

const cancelBtn = ref<HTMLButtonElement | null>(null);

/** Focus lands on CANCEL, not confirm.
 *
 *  A dialog that opens with the destructive action focused turns a stray
 *  Enter — very likely, since Enter is often what opened it — into the
 *  thing it was built to prevent. */
watch(() => props.open, async (isOpen) => {
  if (!isOpen) return;
  await nextTick();
  cancelBtn.value?.focus();
});

function onKey(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape") {
    e.preventDefault();
    emit("cancel");
  }
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div v-if="open" class="cd-scrim" role="presentation" @click.self="emit('cancel')">
    <div class="cd" role="alertdialog" aria-modal="true"
         :aria-label="title" :aria-describedby="detail ? 'cd-detail' : undefined">
      <h3 class="cd-title">{{ title }}</h3>
      <p v-if="detail" id="cd-detail" class="cd-detail">{{ detail }}</p>
      <div class="cd-actions">
        <button ref="cancelBtn" type="button" class="cd-btn cd-cancel"
                @click="emit('cancel')">
          {{ cancelLabel }}
        </button>
        <button type="button" class="cd-btn"
                :class="destructive ? 'cd-danger' : 'cd-primary'"
                @click="emit('confirm')">
          {{ confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cd-scrim {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(3, 6, 12, 0.62);
}
.cd {
  width: 100%;
  max-width: 380px;
  background: var(--bg-2, #151d29);
  border: 1px solid var(--line, #2a3447);
  border-radius: 16px;
  padding: 20px 20px 16px;
  box-shadow: 0 24px 60px -20px rgba(0, 0, 0, 0.8);
}
.cd-title {
  margin: 0 0 6px;
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.35;
}
.cd-detail {
  margin: 0 0 16px;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--muted, #94a3b8);
}
.cd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.cd-btn {
  border-radius: 10px;
  border: 1px solid transparent;
  padding: 9px 16px;
  font-size: 0.85rem;
  font-weight: 650;
  cursor: pointer;
}
.cd-cancel {
  background: transparent;
  border-color: var(--line, #2a3447);
  color: var(--fg, #e6eaf2);
}
.cd-danger { background: #b4342a; color: #fff; }
.cd-primary { background: var(--accent, #28e6ff); color: #04121a; }
.cd-btn:focus-visible { outline: 2px solid var(--accent, #28e6ff); outline-offset: 2px; }
</style>
