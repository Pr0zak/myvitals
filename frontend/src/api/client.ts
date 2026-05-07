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

  async version(): Promise<{ version: string; git_sha: string; build_time: string }> {
    const { data } = await http.get<{ version: string; git_sha: string; build_time: string }>("/version");
    return data;
  },

  // ── AI summaries ───────────────────────────────────────────
  async aiConfig(): Promise<{
    enabled: boolean;
    api_key_set: boolean;
    api_key_masked: string | null;
    model: string;
    daily_call_limit: number;
    calls_today: number;
    weekly_digest_enabled: boolean;
    tone: "supportive" | "blunt" | "data-only";
  }> {
    const { data } = await http.get("/ai/config");
    return data;
  },

  async aiUpdateConfig(body: {
    enabled?: boolean;
    anthropic_api_key?: string;
    clear_key?: boolean;
    model?: string;
    daily_call_limit?: number;
    weekly_digest_enabled?: boolean;
    tone?: "supportive" | "blunt" | "data-only";
  }) {
    const { data } = await http.post("/ai/config", body);
    return data;
  },

  async aiPreviewPayload(range: "week" | "month" = "week") {
    const { data } = await http.get("/ai/preview-payload", { params: { range } });
    return data;
  },

  async aiExplain(range: "week" | "month" = "week"): Promise<{
    content: string;
    generated_at: string;
    model: string;
    cached: boolean;
    input_tokens?: number;
    output_tokens?: number;
  }> {
    const { data } = await http.post("/ai/explain", null, { params: { range } });
    return data;
  },

  async aiLatest(range: "week" | "month" = "week"): Promise<{
    content: string; generated_at: string; model: string;
  } | null> {
    const { data } = await http.get("/ai/latest", { params: { range } });
    return data;
  },

  async aiBadges(): Promise<Array<{
    key: string; label: string; value: string; subtitle: string;
    tone: "good" | "warn" | "bad" | "neutral";
    direction: "up" | "down" | "flat" | "spike" | "streak";
  }>> {
    const { data } = await http.get("/ai/badges");
    return data;
  },

  async aiExplainTopic(topic: "week" | "month" | "sleep" | "recovery" | "sober" | "anomaly"): Promise<{
    headline: string;
    tone: "good" | "warn" | "bad" | "neutral";
    evidence: string[];
    suggestion: string;
    generated_at: string;
    model: string;
    cached: boolean;
  }> {
    const { data } = await http.post(`/ai/explain/${topic}`);
    return data;
  },

  async aiVerdict(): Promise<{ content: string; generated_at: string; model: string; cached: boolean }> {
    const { data } = await http.post("/ai/verdict");
    return data;
  },

  async aiVerdictLatest(): Promise<{ content: string; generated_at: string; model: string } | null> {
    const { data } = await http.get("/ai/verdict/latest");
    return data;
  },

  async aiPreWorkout(): Promise<{ content: string; generated_at: string; model: string }> {
    const { data } = await http.post("/ai/pre-workout");
    return data;
  },

  async aiAsk(question: string): Promise<{ content: string; generated_at: string; model: string; input_tokens: number; output_tokens: number }> {
    const { data } = await http.post("/ai/ask", { question });
    return data;
  },

  async aiExplainDiscovery(x_metric: string, y_metric: string): Promise<{ content: string; generated_at: string; model: string }> {
    const { data } = await http.post("/ai/explain-discovery", { x_metric, y_metric });
    return data;
  },

  async aiAlerts(unackedOnly = true): Promise<Array<{
    id: number; created_at: string; kind: string; severity: string;
    title: string; body: string; metric: string | null; z_score: number | null;
    acked_at: string | null;
  }>> {
    const { data } = await http.get("/ai/alerts", { params: { unacked_only: unackedOnly } });
    return data;
  },

  async aiAckAlert(id: number) { await http.post(`/ai/alerts/${id}/ack`); },
  async aiAckAllAlerts() { await http.post("/ai/alerts/ack-all"); },

  async aiGoals(activeOnly = true): Promise<Array<{
    id: number; kind: string; title: string;
    target_value: number | null; target_unit: string | null;
    target_date: string | null; started_at: string;
    ended_at: string | null; notes: string | null;
  }>> {
    const { data } = await http.get("/ai/goals", { params: { active_only: activeOnly } });
    return data;
  },

  async aiCreateGoal(body: {
    kind: string; title: string; target_value?: number;
    target_unit?: string; target_date?: string; notes?: string;
  }) {
    const { data } = await http.post("/ai/goals", body);
    return data;
  },

  async aiUpdateGoal(id: number, body: Record<string, unknown>) {
    const { data } = await http.patch(`/ai/goals/${id}`, body);
    return data;
  },

  async aiDeleteGoal(id: number) { await http.delete(`/ai/goals/${id}`); },

  async aiCheckGoal(id: number): Promise<{ content: string; model: string; generated_at: string }> {
    const { data } = await http.post(`/ai/goals/${id}/check`);
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

  async linkActivityToTrail(source: string, sourceId: string, trailId: number | null): Promise<{
    source: string; source_id: string; trail_id: number | null;
  }> {
    const { data } = await http.post(
      `/activities/${source}/${sourceId}/link-trail`, { trail_id: trailId },
    );
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

  // ── Strength training ─────────────────────────────────────
  async strengthEquipment(): Promise<{
    id: number;
    payload: import("./types").StrengthEquipment;
    unit: "lb" | "kg";
    updated_at: string | null;
  }> {
    const { data } = await http.get("/workout/strength/equipment");
    return data;
  },

  async putStrengthEquipment(body: {
    payload: import("./types").StrengthEquipment;
    unit: "lb" | "kg";
  }): Promise<unknown> {
    const { data } = await http.put("/workout/strength/equipment", body);
    return data;
  },

  async strengthToday(): Promise<import("./types").StrengthWorkoutDetail | null> {
    const { data } = await http.get("/workout/strength/today");
    return data;
  },

  async regenerateStrengthToday(force = false): Promise<import("./types").StrengthWorkoutDetail> {
    const { data } = await http.post("/workout/strength/today/regenerate", { force });
    return data;
  },

  async strengthRecovery(): Promise<{
    date: string;
    recovery_aware: boolean;
    recovery_score: number | null;
    readiness_score: number | null;
    sleep_h: number | null;
    deload_factor: number;
    rest_day_recommended: boolean;
    rest_day_reason: string | null;
  }> {
    const { data } = await http.get("/workout/strength/recovery");
    return data;
  },

  async strengthExercises(opts: {
    muscle?: string;
    movement?: string;
    equipment?: string;
    level?: string;
  } = {}): Promise<{ count: number; exercises: import("./types").StrengthExercise[] }> {
    const { data } = await http.get("/workout/strength/exercises", { params: opts });
    return data;
  },

  async strengthWorkouts(opts: { limit?: number; status?: string } = {}): Promise<{
    count: number;
    workouts: Array<{
      id: number; date: string; split_focus: string; status: string;
      started_at: string | null; completed_at: string | null; generated_at: string;
    }>;
  }> {
    const { data } = await http.get("/workout/strength/workouts", { params: opts });
    return data;
  },

  async strengthWorkout(id: number): Promise<import("./types").StrengthWorkoutDetail> {
    const { data } = await http.get(`/workout/strength/workouts/${id}`);
    return data;
  },

  async createStrengthWorkout(body: {
    date: string;
    split_focus: string;
    seed?: string;
    notes?: string;
    exercises?: Array<{
      exercise_id: string;
      order_index: number;
      superset_id?: string | null;
      target_sets: number;
      target_reps_low: number;
      target_reps_high: number;
      target_weight_lb?: number | null;
      target_rest_s?: number;
      notes?: string | null;
    }>;
  }): Promise<import("./types").StrengthWorkoutDetail> {
    const { data } = await http.post("/workout/strength/workouts", body);
    return data;
  },

  async patchStrengthWorkout(id: number, body: {
    status?: "planned" | "in_progress" | "completed" | "skipped";
    started_at?: string | null;
    completed_at?: string | null;
    notes?: string | null;
  }): Promise<import("./types").StrengthWorkoutDetail> {
    const { data } = await http.patch(`/workout/strength/workouts/${id}`, body);
    return data;
  },

  async deleteStrengthWorkout(id: number): Promise<void> {
    await http.delete(`/workout/strength/workouts/${id}`);
  },

  async logStrengthSet(body: {
    workout_exercise_id: number;
    set_number: number;
    target_weight_lb?: number | null;
    target_reps: number;
    actual_weight_lb?: number | null;
    actual_reps?: number | null;
    rating?: number | null;
    rest_seconds_taken?: number | null;
    skipped?: boolean;
    logged_at?: string;
  }): Promise<unknown> {
    const { data } = await http.post("/workout/strength/sets", body);
    return data;
  },

  async deleteStrengthSet(id: number): Promise<void> {
    await http.delete(`/workout/strength/sets/${id}`);
  },

  async setExercisePref(
    exerciseId: string,
    pref: "neutral" | "disabled" | "favorite" | "avoid",
  ): Promise<{ exercise_id: string; pref: string }> {
    const { data } = await http.put(
      `/workout/strength/exercises/${exerciseId}/pref`, { pref },
    );
    return data;
  },

  async swapStrengthExercise(
    workoutExerciseId: number, newExerciseId: string,
  ): Promise<import("./types").StrengthWorkoutExercise> {
    const { data } = await http.post(
      `/workout/strength/workout-exercises/${workoutExerciseId}/swap`,
      { exercise_id: newExerciseId },
    );
    return data;
  },

  async strengthUpcoming(days = 7, perDayCount = 4): Promise<{
    count: number;
    upcoming: Array<{
      date: string;
      is_today: boolean;
      split_focus: string;
      preview_exercises: string[];
      exercise_count: number;
    }>;
  }> {
    const { data } = await http.get("/workout/strength/upcoming", {
      params: { days, per_day_count: perDayCount },
    });
    return data;
  },

  // ── Trails (RainoutLine status) ───────────────────────────
  async trails(): Promise<{
    count: number;
    trails: Array<{
      id: number; extension: number; name: string; slug: string;
      last_seen_at: string;
      latitude: number | null; longitude: number | null;
      city: string | null; state: string | null;
      subscribed: boolean; notify_on: string | null;
      status: "open" | "closed" | "pending" | "unknown" | null;
      comment: string | null;
      source_ts: string | null;
      fetched_at: string | null;
      visits_30d?: number;
      visits_total?: number;
      last_visit_at?: string | null;
    }>;
  }> {
    const { data } = await http.get("/trails");
    return data;
  },

  async trailHistory(id: number, days = 30): Promise<{
    trail_id: number; name: string;
    snapshots: Array<{
      fetched_at: string; status: string;
      comment: string | null; source_ts: string | null;
    }>;
  }> {
    const { data } = await http.get(`/trails/${id}/history`, { params: { days } });
    return data;
  },

  async subscribeTrail(id: number, notify_on: "any" | "open_only" | "close_only" = "any") {
    const { data } = await http.post(`/trails/${id}/subscribe`, { notify_on });
    return data;
  },

  async unsubscribeTrail(id: number): Promise<void> {
    await http.delete(`/trails/${id}/subscribe`);
  },

  async refreshTrails(): Promise<{ fetched: number; snapshots: number; alerts: number }> {
    const { data } = await http.post("/trails/refresh");
    return data;
  },

  async trailAlerts(unackedOnly = false): Promise<Array<{
    id: number; trail_id: number; trail_name: string | null;
    from_status: string | null; to_status: string;
    source_ts: string | null; created_at: string;
    phone_notified_at: string | null; acked_at: string | null;
  }>> {
    const { data } = await http.get("/trails/alerts", { params: { unacked_only: unackedOnly } });
    return data;
  },

  async ackTrailAlert(id: number) { await http.post(`/trails/alerts/${id}/ack`); },

  async resolveTrailLink(url: string): Promise<{ resolved_url: string }> {
    const { data } = await http.get("/trails/resolve-link", { params: { url } });
    return data;
  },

  async editTrailLocation(id: number, body: {
    latitude?: number | null; longitude?: number | null;
    city?: string | null; state?: string | null;
  }): Promise<unknown> {
    const { data } = await http.put(`/trails/${id}/location`, body);
    return data;
  },

  async linkActivitiesToTrails(maxKm = 2.0, relink = false): Promise<{
    scanned: number; linked: number; already_linked_skipped: number;
    no_match_within_km: number; no_gps: number; max_km: number;
  }> {
    const { data } = await http.post("/trails/link-activities", null, {
      params: { max_km: maxKm, relink },
    });
    return data;
  },

  async trailVisits(id: number, days = 365): Promise<{
    trail_id: number; name: string; count: number;
    visits: Array<{
      source: string; source_id: string; type: string; name: string | null;
      start_at: string; duration_s: number;
      distance_m: number | null; avg_hr: number | null; kcal: number | null;
    }>;
  }> {
    const { data } = await http.get(`/trails/${id}/visits`, { params: { days } });
    return data;
  },

  async aiStrengthReview(workoutId: number): Promise<{
    review: {
      headline: string;
      tone: "good" | "warn" | "bad" | "neutral";
      highlights: string[];
      concerns?: string[];
      next_session_suggestion: string;
    };
    generated_at: string;
    model: string;
    cached: boolean;
    input_tokens: number;
    output_tokens: number;
  }> {
    const { data } = await http.post(`/ai/strength/review/${workoutId}`);
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
