import { ref, watch } from "vue";

const TOKEN_KEY = "myvitals.queryToken";
const API_BASE_KEY = "myvitals.apiBase";

export const queryToken = ref<string>(localStorage.getItem(TOKEN_KEY) ?? "");

/** Optional override of the /api base. Defaults to "" (uses Caddy / Vite proxy). */
export const apiBase = ref<string>(localStorage.getItem(API_BASE_KEY) ?? "");

watch(queryToken, (v) => {
  if (v) localStorage.setItem(TOKEN_KEY, v);
  else localStorage.removeItem(TOKEN_KEY);
});

watch(apiBase, (v) => {
  if (v) localStorage.setItem(API_BASE_KEY, v);
  else localStorage.removeItem(API_BASE_KEY);
});

export function isConfigured(): boolean {
  return queryToken.value.length > 0;
}
