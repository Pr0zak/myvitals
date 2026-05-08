<script setup lang="ts">
/**
 * AI insights — vertical topic pills + structured response card.
 * Wires into the existing askTopic / aiTopicResult / refreshTopic state
 * from the parent view; this component is purely presentational.
 */
import { computed } from "vue";
import {
  Sparkles, RefreshCw, Moon, Shield, Droplet, CalendarDays,
  Calendar, AlertTriangle,
} from "lucide-vue-next";
import { fmtDateTime } from "@/format";

// Aligned with server's /ai/explain-topic supported topics so the
// component can call the API directly without a translation layer.
export type AiTopicId = "sleep" | "recovery" | "sober" | "week" | "month" | "anomaly";
export type AiTone = "good" | "warn" | "bad" | "neutral";
export type AiTopicResult = {
  headline: string;
  evidence: string[];
  suggestion?: string | null;
  tone: AiTone;
  cached: boolean;
  model: string;
  generated_at: string;
};

const props = withDefaults(defineProps<{
  enabled: boolean;
  active: AiTopicId | null;
  busy?: boolean;
  result: AiTopicResult | null;
  error?: string | null;
  mobile?: boolean;
}>(), { busy: false, error: null, mobile: false });

const emit = defineEmits<{
  (e: "select", id: AiTopicId): void;
  (e: "refresh"): void;
}>();

const TOPICS: Array<{ id: AiTopicId; label: string; icon: any }> = [
  { id: "sleep",    label: "Sleep",    icon: Moon },
  { id: "recovery", label: "Recovery", icon: Shield },
  { id: "sober",    label: "Sober",    icon: Droplet },
  { id: "week",     label: "Week",     icon: Calendar },
  { id: "month",    label: "Month",    icon: CalendarDays },
  { id: "anomaly",  label: "Anomaly",  icon: AlertTriangle },
];

const toneColor = computed(() => {
  const t = props.result?.tone ?? "neutral";
  if (t === "good") return "#22C55E";
  if (t === "warn") return "#EAB308";
  if (t === "bad") return "#EF4444";
  return "#94A3B8";
});
const toneBg = computed(() => {
  const t = props.result?.tone ?? "neutral";
  if (t === "good") return "rgba(34,197,94,0.06)";
  if (t === "warn") return "rgba(234,179,8,0.06)";
  if (t === "bad")  return "rgba(239,68,68,0.06)";
  return "rgba(148,163,184,0.06)";
});
</script>

<template>
  <div class="card ai-card" :class="{ mobile }">
    <div class="head">
      <div class="head-l">
        <Sparkles :size="14" class="muted"/>
        <span class="eyebrow">AI Insights</span>
      </div>
      <span class="chip status-chip">
        <span :class="['dot', enabled ? 'dot-good' : 'dot-neutral']"/>
        {{ enabled ? "AI enabled" : "AI off" }}
      </span>
    </div>

    <div class="body" :class="{ mobile }">
      <!-- Topic list -->
      <div class="topics no-scrollbar" :class="{ mobile }">
        <button v-for="t in TOPICS" :key="t.id"
                :class="['topic-pill', { active: t.id === active }]"
                :disabled="!enabled"
                @click="emit('select', t.id)">
          <component :is="t.icon" :size="12"/>
          {{ t.label }}
        </button>
      </div>

      <!-- Response -->
      <div class="response">
        <p v-if="!enabled" class="dim small">
          Enable AI in Settings to use insights.
        </p>
        <p v-else-if="busy" class="muted small">Thinking…</p>
        <p v-else-if="error" class="dim small">{{ error }}</p>
        <p v-else-if="!active" class="dim small">
          Pick a topic above for a focused, structured read of your data.
        </p>
        <p v-else-if="!result" class="dim small">No response yet — pick a topic.</p>
        <template v-else>
          <div class="headline-block"
               :style="{ background: toneBg, borderLeftColor: toneColor }">
            {{ result.headline }}
          </div>
          <div class="bullets">
            <div v-for="(b, i) in result.evidence" :key="i" class="bullet">
              <span class="bullet-dot" :style="{ color: toneColor }">·</span>
              <span class="mono bullet-txt">{{ b }}</span>
            </div>
          </div>
          <div v-if="result.suggestion" class="dim suggestion">
            {{ result.suggestion }}
          </div>
        </template>
      </div>
    </div>

    <div v-if="enabled" class="foot">
      <div class="foot-l">
        <span :class="['chip', 'fresh-chip', { fresh: result?.cached === false }]">
          <span :class="['dot', result?.cached === false ? 'dot-good' : 'dot-neutral']"/>
          {{ result?.cached === false ? "fresh" : (result?.cached ? "cached" : "—") }}
        </span>
        <span class="mono small" v-if="result">{{ result.model.replace(/-\d{8}$/, "") }}</span>
      </div>
      <div class="foot-r">
        <span class="mono small" v-if="result">
          generated {{ fmtDateTime(result.generated_at) }}
        </span>
        <button class="btn btn-icon mini" title="Refresh"
                :disabled="busy" @click="emit('refresh')">
          <RefreshCw :size="11"/>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-card { padding: 0; }
.head {
  padding: 14px 16px 8px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--outline);
}
.head-l { display: flex; align-items: center; gap: 8px; }
.muted { color: var(--on-surface-2); }
.status-chip { height: 22px; font-size: 11px; padding: 0 8px; }

.body {
  display: grid;
  grid-template-columns: 136px 1fr;
  min-height: 200px;
}
.body.mobile { grid-template-columns: 1fr; }

.topics {
  padding: 12px;
  display: flex; flex-direction: column; gap: 4px;
  border-right: 1px solid var(--outline);
}
.topics.mobile {
  flex-direction: row; overflow: auto;
  border-right: none; border-bottom: 1px solid var(--outline);
}

.topic-pill {
  display: flex; align-items: center; gap: 8px;
  height: 30px; padding: 0 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--on-surface-2);
  border-radius: 999px;
  font-size: 12px; font-weight: 500;
  cursor: pointer;
  white-space: nowrap; text-align: left;
  font-family: inherit;
  transition: background .15s, border-color .15s, color .15s;
  flex-shrink: 0;
}
.topic-pill.active {
  border-color: var(--outline-strong);
  background: var(--surface-low);
  color: var(--on-surface);
}
.topic-pill:disabled { opacity: 0.5; cursor: not-allowed; }

.response {
  padding: 16px;
  display: flex; flex-direction: column; gap: 12px;
}
.headline-block {
  border-left: 2px solid;
  padding: 8px 12px;
  border-radius: 0 8px 8px 0;
  font-size: 14px; font-weight: 600; color: var(--on-surface);
  line-height: 1.4;
}
.bullets { display: flex; flex-direction: column; gap: 6px; }
.bullet { display: flex; align-items: flex-start; gap: 8px; }
.bullet-dot { margin-top: 6px; }
.bullet-txt {
  font-size: 12px; color: var(--on-surface); line-height: 1.5;
}
.suggestion { font-size: 12px; line-height: 1.5; }

.foot {
  padding: 10px 16px;
  border-top: 1px solid var(--outline);
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; color: var(--dim);
}
.foot-l, .foot-r { display: flex; align-items: center; gap: 8px; }
.fresh-chip { height: 20px; padding: 0 7px; font-size: 10px; }
.fresh-chip.fresh {
  color: var(--good); border-color: rgba(34,197,94,0.3);
}
.small { font-size: 11px; }
.btn.mini { width: 22px; height: 22px; }
.dim { color: var(--dim); }
</style>
