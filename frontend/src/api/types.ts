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
