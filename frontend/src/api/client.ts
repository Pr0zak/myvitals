import axios from "axios";
import { apiBase, queryToken } from "@/config";
import type {
  Annotation,
  AnnotationCreate,
  HeartRateSeries,
  HrvSeries,
  SleepNight,
  StepsSeries,
  TodaySummary,
} from "./types";

const http = axios.create({ baseURL: "/api" });

// Inject the bearer token from the user's saved settings on every request.
// Reading from the ref means token changes take effect without reload.
http.interceptors.request.use((cfg) => {
  if (queryToken.value) {
    cfg.headers.Authorization = `Bearer ${queryToken.value}`;
  }
  if (apiBase.value) {
    cfg.baseURL = apiBase.value.replace(/\/$/, "");
  }
  return cfg;
});

interface RangeParams {
  since?: Date | string;
  until?: Date | string;
}

function rangeToQuery(p: RangeParams): Record<string, string> {
  const out: Record<string, string> = {};
  if (p.since) out.since = p.since instanceof Date ? p.since.toISOString() : p.since;
  if (p.until) out.until = p.until instanceof Date ? p.until.toISOString() : p.until;
  return out;
}

export const api = {
  async heartRate(p: RangeParams = {}): Promise<HeartRateSeries> {
    const { data } = await http.get<HeartRateSeries>("/query/heartrate", { params: rangeToQuery(p) });
    return data;
  },

  async hrv(p: RangeParams = {}): Promise<HrvSeries> {
    const { data } = await http.get<HrvSeries>("/query/hrv", { params: rangeToQuery(p) });
    return data;
  },

  async steps(p: RangeParams = {}): Promise<StepsSeries> {
    const { data } = await http.get<StepsSeries>("/query/steps", { params: rangeToQuery(p) });
    return data;
  },

  async lastSleep(): Promise<SleepNight | null> {
    const { data } = await http.get<SleepNight | null>("/query/sleep/last");
    return data;
  },

  async sleepRange(since: Date | string, until?: Date | string): Promise<SleepNight[]> {
    const params: Record<string, string> = {
      since: since instanceof Date ? since.toISOString() : since,
    };
    if (until) params.until = until instanceof Date ? until.toISOString() : until;
    const { data } = await http.get<SleepNight[]>("/query/sleep/range", { params });
    return data;
  },

  async weight(p: RangeParams = {}): Promise<{
    points: { time: string; weight_kg: number | null; body_fat_pct: number | null; bmi: number | null; lean_mass_kg: number | null; source: string }[];
    latest_kg: number | null; min_kg: number | null; max_kg: number | null; avg_kg: number | null;
  }> {
    const { data } = await http.get("/query/weight", { params: rangeToQuery(p) });
    return data;
  },

  async skinTemp(p: RangeParams = {}): Promise<{ points: { time: string; value: number }[] }> {
    const { data } = await http.get("/query/skin-temp", { params: rangeToQuery(p) });
    return data;
  },

  async bloodPressure(p: RangeParams = {}): Promise<{
    points: { time: string; systolic: number; diastolic: number; pulse_bpm: number | null; source: string; notes: string | null }[];
    latest: { time: string; systolic: number; diastolic: number; pulse_bpm: number | null; source: string; notes: string | null } | null;
    avg_sys: number | null; avg_dia: number | null;
  }> {
    const { data } = await http.get("/query/blood-pressure", { params: rangeToQuery(p) });
    return data;
  },

  async logBloodPressure(body: { systolic: number; diastolic: number; pulse_bpm?: number | null; notes?: string | null; time?: string }): Promise<{ status: string; time: string }> {
    const { data } = await http.post("/query/blood-pressure", body);
    return data;
  },

  async sleepRaw(since?: Date | string, until?: Date | string): Promise<{ time: string; stage: string; duration_s: number }[]> {
    const params: Record<string, string> = {};
    if (since) params.since = since instanceof Date ? since.toISOString() : since;
    if (until) params.until = until instanceof Date ? until.toISOString() : until;
    const { data } = await http.get<{ time: string; stage: string; duration_s: number }[]>("/query/sleep/raw", { params });
    return data;
  },

  async lastSync(): Promise<{
    last_sync: string | null;
    last_attempt: string | null;
    last_success: string | null;
    permissions_lost: boolean;
    perms_granted: number | null;
    perms_required: number | null;
    perms_missing: string[] | null;
    error_summary: string | null;
    app_version: string | null;
  }> {
    const { data } = await http.get("/query/last-sync");
    return data;
  },

  async todaySummary(): Promise<TodaySummary> {
    const { data } = await http.get<TodaySummary>("/summary/today");
    return data;
  },

  async summaryRange(since: Date | string, until?: Date | string): Promise<TodaySummary[]> {
    const params: Record<string, string> = {
      since: since instanceof Date ? since.toISOString().slice(0, 10) : since,
    };
    if (until) params.until = until instanceof Date ? until.toISOString().slice(0, 10) : until;
    const { data } = await http.get<TodaySummary[]>("/summary/range", { params });
    return data;
  },

  async listAnnotations(opts: { since?: Date | string; type?: string; limit?: number } = {}): Promise<Annotation[]> {
    const params: Record<string, string | number> = {};
    if (opts.since) params.since = opts.since instanceof Date ? opts.since.toISOString() : opts.since;
    if (opts.type) params.type = opts.type;
    if (opts.limit) params.limit = opts.limit;
    const { data } = await http.get<Annotation[]>("/log", { params });
    return data;
  },

  async createAnnotation(body: AnnotationCreate): Promise<Annotation> {
    const { data } = await http.post<Annotation>("/log", body);
    return data;
  },

  async updateAnnotation(id: number, body: {
    ts?: string;
    payload?: Record<string, unknown>;
    note?: string | null;
  }): Promise<Annotation> {
    const { data } = await http.patch<Annotation>(`/log/${id}`, body);
    return data;
  },

  async deleteAnnotation(id: number): Promise<void> {
    await http.delete(`/log/${id}`);
  },

  // ── Sober tracking ─────────────────────────────────────────
  async soberCurrent(): Promise<{
    active: { id: number; addiction: string; start_at: string; end_at: string | null; notes: string | null; days: number } | null;
    addiction: string;
    now?: string;
    elapsed_seconds?: number;
    days?: number;
    hours?: number;
    minutes?: number;
  }> {
    const { data } = await http.get("/sober/current");
    return data;
  },

  async soberHistory(limit = 500): Promise<Array<{
    id: number; addiction: string; start_at: string; end_at: string | null; notes: string | null; days: number;
  }>> {
    const { data } = await http.get("/sober/history", { params: { limit } });
    return data;
  },

  async soberStats(): Promise<{
    addiction: string;
    total_resets: number;
    longest_days: number;
    avg_days: number;
    current_days: number;
    current_started_at: string | null;
    first_started_at: string | null;
    total_tracked_days: number;
  }> {
    const { data } = await http.get("/sober/stats");
    return data;
  },

  async soberReset(notes?: string): Promise<{ ok: boolean; current_id: number; started_at?: string; noop?: boolean }> {
    const { data } = await http.post("/sober/reset", { notes });
    return data;
  },

  async soberUpdate(id: number, body: { start_at?: string; end_at?: string | null; notes?: string | null }) {
    const { data } = await http.patch(`/sober/streak/${id}`, body);
    return data;
  },

  async soberDelete(id: number): Promise<void> {
    await http.delete(`/sober/streak/${id}`);
  },

  async health(): Promise<{ status: string }> {
    const { data } = await http.get<{ status: string }>("/health");
    return data;
  },

  async logs(opts: { since?: Date | string; source?: string; level?: string; limit?: number } = {}): Promise<import("./types").AppLog[]> {
    const params: Record<string, string | number> = {};
    if (opts.since) params.since = opts.since instanceof Date ? opts.since.toISOString() : opts.since;
    if (opts.source) params.source = opts.source;
    if (opts.level) params.level = opts.level;
    if (opts.limit) params.limit = opts.limit;
    const { data } = await http.get<import("./types").AppLog[]>("/debug/logs", { params });
    return data;
  },

  async stravaStatus(): Promise<import("./types").StravaStatus> {
    const { data } = await http.get<import("./types").StravaStatus>("/strava/status");
    return data;
  },

  async stravaConfig(): Promise<import("./types").StravaAppConfigStatus> {
    const { data } = await http.get<import("./types").StravaAppConfigStatus>("/strava/config");
    return data;
  },

  async saveStravaConfig(body: { client_id: string; client_secret: string; callback_url?: string | null }): Promise<{ status: string }> {
    const { data } = await http.post<{ status: string }>("/strava/config", body);
    return data;
  },

  async clearStravaConfig(): Promise<{ status: string }> {
    const { data } = await http.delete<{ status: string }>("/strava/config");
    return data;
  },

  async stravaSync(days = 90): Promise<{ upserted: number; days: number }> {
    const { data } = await http.post<{ upserted: number; days: number }>("/strava/sync", null, { params: { days } });
    return data;
  },

  async stravaDisconnect(): Promise<{ status: string }> {
    const { data } = await http.delete<{ status: string }>("/strava");
    return data;
  },

  async activities(opts: { since?: Date | string; type?: string; limit?: number } = {}): Promise<import("./types").Activity[]> {
    const params: Record<string, string | number> = {};
    if (opts.since) params.since = opts.since instanceof Date ? opts.since.toISOString() : opts.since;
    if (opts.type) params.type = opts.type;
    if (opts.limit) params.limit = opts.limit;
    const { data } = await http.get<import("./types").Activity[]>("/activities", { params });
    return data;
  },

  async activity(source: string, sourceId: string): Promise<import("./types").Activity> {
    const { data } = await http.get<import("./types").Activity>(`/activities/${source}/${sourceId}`);
    return data;
  },

  async activitiesStats(days = 30): Promise<import("./types").ActivityStats> {
    const { data } = await http.get<import("./types").ActivityStats>("/activities/stats", { params: { days } });
    return data;
  },

  async updateActivityNotes(source: string, sourceId: string, body: { notes?: string | null; tags?: string[] | null }): Promise<{ status: string }> {
    const { data } = await http.post<{ status: string }>(`/activities/${source}/${sourceId}/notes`, body);
    return data;
  },

  async getProfile(): Promise<{
    id: number; birth_date: string | null; sex: string | null;
    height_cm: number | null; weight_goal_kg: number | null;
    resting_hr_baseline: number | null; activity_level: string | null;
    extra: Record<string, unknown> | null; updated_at: string | null;
    derived: { age?: number; max_hr_estimated?: number; bmi_at_goal?: number;
               resting_hr_baseline_auto?: number | null;
               hr_zones?: { zone: number; label: string; low: number; high: number }[] };
  }> {
    const { data } = await http.get("/profile");
    return data;
  },

  async discoveries(days = 90): Promise<{ x_metric: string; y_metric: string; n: number; pearson_r: number }[]> {
    const { data } = await http.get("/analytics/discoveries", { params: { days } });
    return data;
  },

  async backfillHrRecovery(): Promise<{ considered: number; computed: number }> {
    const { data } = await http.post("/analytics/hr-recovery-backfill");
    return data;
  },

  async putProfile(body: {
    birth_date?: string | null; sex?: string | null; height_cm?: number | null;
    weight_goal_kg?: number | null; resting_hr_baseline?: number | null;
    activity_level?: string | null; extra?: Record<string, unknown> | null;
  }): Promise<unknown> {
    const { data } = await http.put("/profile", body);
    return data;
  },

  async importJobs(limit = 20): Promise<{
    id: number; kind: string; filename: string | null; size_bytes: number | null;
    status: string; started_at: string; finished_at: string | null;
    elapsed_s: number | null; counts: Record<string, number>; total_rows: number;
    error: string | null;
  }[]> {
    const { data } = await http.get("/import/jobs", { params: { limit } });
    return data;
  },
};
