<script setup lang="ts">
/**
 * One row on the Settings home (SETTINGS-B1) — phone twin: the section
 * rows on `SettingsHomeScreen`.
 *
 * Icon, title, a one-line LIVE summary ("Imperial · 12h", "3 of 4
 * connected"), chevron. The summary is what makes the home page worth
 * having: the old Settings had no home at all and opened straight onto
 * Updates, so nothing told you which section needed you.
 *
 * A summary of `null` means "not known" (the request failed or has not
 * answered) and renders as a dash, never as a claim.
 */
import type { Component } from "vue";
import { ChevronRight } from "lucide-vue-next";

defineProps<{
  to: string;
  icon: Component;
  title: string;
  summary: string | null;
  /** Icon tint. */
  tint?: string;
  /** Amber summary — something here wants attention. Never rose. */
  attention?: boolean;
}>();
</script>

<template>
  <RouterLink :to="to" class="srow">
    <span class="srow-ico" :style="{ color: tint ?? '#28e6ff', background: (tint ?? '#28e6ff') + '1f' }"
          aria-hidden="true">
      <component :is="icon" :size="20" />
    </span>
    <span class="srow-text">
      <span class="srow-title">{{ title }}</span>
      <span class="srow-sum" :class="{ attn: attention }">{{ summary ?? "—" }}</span>
    </span>
    <ChevronRight :size="18" class="srow-chev" aria-hidden="true" />
  </RouterLink>
</template>

<style scoped>
.srow {
  display: flex; align-items: center; gap: 12px;
  min-height: 56px; padding: 10px 14px;
  background: #181b27; border: 1px solid #23263a; border-radius: 16px;
  color: #ececf5; text-decoration: none;
}
.srow + .srow { margin-top: 8px; }
.srow:hover { border-color: #33374f; }
.srow:focus-visible { outline: 2px solid #28e6ff; outline-offset: 2px; }
.srow-ico { width: 38px; height: 38px; border-radius: 12px; display: flex; align-items: center;
  justify-content: center; flex: 0 0 auto; }
.srow-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.srow-title { font-size: 15px; font-weight: 700; }
.srow-sum { font-size: 12.5px; color: #9b9bb0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.srow-sum.attn { color: #ffb52e; }
.srow-chev { color: #6b6b80; flex: 0 0 auto; }
</style>
