export interface TimePoint {
  time: string;
  value: number;
}

export interface HeartRateSeries {
  points: TimePoint[];
  avg: number | null;
  min_bpm: number | null;
  max_bpm: number | null;
}

export interface HrvSeries {
  points: TimePoint[];
  avg: number | null;
}

export interface StepsSeries {
  points: TimePoint[];
  total: number;
}

export interface SleepStageBucket {
  stage: string;
  duration_s: number;
}

export interface SleepNight {
  date: string;
  start: string;
  end: string;
  total_s: number;
  stages: SleepStageBucket[];
}

export interface TodaySummary {
  date: string;
  resting_hr: number | null;
  hrv_avg: number | null;
  recovery_score: number | null;
  sleep_duration_s: number | null;
  sleep_score: number | null;
  steps_total: number | null;
  last_sync: string | null;
}

export interface Annotation {
  id: number;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  note: string | null;
}

export interface AnnotationCreate {
  ts?: string;
  type: string;
  payload?: Record<string, unknown>;
  note?: string;
}

export interface AppLog {
  id: number;
  ts: string;
  source: "phone" | "server" | string;
  level: "VERBOSE" | "DEBUG" | "INFO" | "WARN" | "ERROR" | string;
  tag: string | null;
  message: string;
  stack: string | null;
}

export interface StravaStatus {
  connected: boolean;
  configured: boolean;
  athlete_id: number | null;
  athlete_name: string | null;
  expires_at: string | null;
  last_sync_at: string | null;
  scope: string | null;
}

export interface Activity {
  source: string;
  source_id: string;
  type: string;
  name: string | null;
  start_at: string;
  duration_s: number;
  distance_m: number | null;
  elevation_gain_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_power_w: number | null;
  max_power_w: number | null;
  kcal: number | null;
  suffer_score: number | null;
  polyline: string | null;
}
