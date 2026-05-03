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

  async lastSync(): Promise<{ last_sync: string | null }> {
    const { data } = await http.get<{ last_sync: string | null }>("/query/last-sync");
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
};
