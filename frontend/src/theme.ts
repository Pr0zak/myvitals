import { computed, ref, watch, watchEffect } from "vue";

export type ThemeChoice = "dark" | "light" | "auto";

const KEY = "myvitals.theme";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export const themeChoice = ref<ThemeChoice>(
  (localStorage.getItem(KEY) as ThemeChoice | null) ?? "dark"
);

/** The actually-applied theme (resolves "auto" against the system). */
export const effectiveTheme = computed<"dark" | "light">(() => {
  if (themeChoice.value === "auto") return systemPrefersDark() ? "dark" : "light";
  return themeChoice.value;
});

watch(themeChoice, (v) => localStorage.setItem(KEY, v));

watchEffect(() => {
  document.documentElement.setAttribute("data-theme", effectiveTheme.value);
});

// Re-evaluate when system preference changes (only matters in "auto" mode).
if (typeof window !== "undefined" && window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (themeChoice.value === "auto") {
      document.documentElement.setAttribute("data-theme", effectiveTheme.value);
    }
  });
}

/**
 * Theme-aware ECharts styling primitives. Read from the same CSS vars so
 * charts re-render with the right colors when the theme flips.
 */
export const chartTheme = computed(() => {
  const isDark = effectiveTheme.value === "dark";
  return {
    axisLabel: { color: isDark ? "#94a3b8" : "#475569", fontSize: 10 },
    splitLine: { lineStyle: { color: isDark ? "#334155" : "#e2e8f0", type: "dashed" as const } },
    tooltip: {
      backgroundColor: isDark ? "#1e293b" : "#ffffff",
      borderColor: isDark ? "#334155" : "#e2e8f0",
      textStyle: { color: isDark ? "#e2e8f0" : "#0f172a" },
    },
    palette: {
      hr: isDark ? "#ef4444" : "#dc2626",
      hrv: isDark ? "#22c55e" : "#16a34a",
      recovery: isDark ? "#a78bfa" : "#7c3aed",
      sleep: isDark ? "#a78bfa" : "#7c3aed",
      violet: isDark ? "#a78bfa" : "#7c3aed",
      steps: isDark ? "#38bdf8" : "#0284c7",
      accent: isDark ? "#38bdf8" : "#0284c7",
      activity: isDark ? "rgba(56, 189, 248, 0.18)" : "rgba(2, 132, 199, 0.15)",
      workout: isDark ? "rgba(239, 68, 68, 0.20)" : "rgba(220, 38, 38, 0.15)",
      annotation: isDark ? "#eab308" : "#ca8a04",
    },
  };
});
