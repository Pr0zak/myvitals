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
  weight_kg: number | null;
  body_fat_pct: number | null;
  bp_systolic_avg: number | null;
  bp_diastolic_avg: number | null;
  skin_temp_delta_avg: number | null;
  readiness_score: number | null;
  training_stress_score: number | null;
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
  sleep_consistency_score: number | null;
  sleep_debt_h: number | null;
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

export interface ActivityStats {
  period_label: string;
  n_activities: number;
  total_distance_m: number;
  total_duration_s: number;
  total_elevation_m: number;
  total_kcal: number;
  by_type: Record<string, number>;
  streak_days: number;
  period_pct_vs_prev: Record<string, number>;
}

export interface StravaStatus {
  connected: boolean;
  configured: boolean;
  config_source: "db" | "env" | null;
  athlete_id: number | null;
  athlete_name: string | null;
  expires_at: string | null;
  last_sync_at: string | null;
  scope: string | null;
}

export interface StravaAppConfigStatus {
  configured: boolean;
  source: "db" | "env" | null;
  client_id_masked: string | null;
  callback_url: string | null;
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
  notes?: string | null;
  tags?: string[] | null;
  trail_id?: number | null;
  trail_name?: string | null;
}

export interface StrengthEquipment {
  dumbbells: {
    type: "fixed_pairs" | "adjustable" | "none";
    pairs_lb: number[];
    min_lb: number | null;
    max_lb: number | null;
    increment_lb: number | null;
  };
  wrist_weights_lb: number[];
  bench: { flat: boolean; incline: boolean; decline: boolean };
  barbell: boolean;
  barbell_plates_lb: number[];
  squat_rack: boolean;
  pull_up_bar: boolean;
  cable_stack: boolean;
  cable_increment_lb: number | null;
  kettlebells_lb: number[];
  resistance_bands: boolean;
  bodyweight: boolean;
  cardio_rower?: boolean;
  cardio_bike_indoor?: boolean;
  cardio_mtb_outdoor?: boolean;
  cardio_road_bike?: boolean;
  cardio_treadmill?: boolean;
  exercise_prefs?: Record<string, string>;
  training?: {
    level: "beginner" | "intermediate" | "advanced";
    days_per_week: number;
    split_preference: "auto" | "full_body" | "upper_lower" | "ppl";
    workout_minutes: number;
    include_mobility?: boolean;
    yoga_on_rest_days?: boolean;
    cardio_days_per_week?: number;
    goal?: "strength" | "hypertrophy" | "general";
  };
}

export interface StrengthExercise {
  id: string;
  name: string;
  primary_muscle: string;
  secondary_muscles: string[];
  equipment: string[];
  is_compound: boolean;
  movement_pattern: string;
  level: string;
  mechanic: string;
  instructions: string[];
  image_front: string | null;
  image_side: string | null;
  youtube_query: string;
  // Mobility-only flags (mirrors backend supplement). Bilateral means
  // sets=2 with R/L semantics; is_timed=false means rep-based mobility
  // (Thread-the-Needle, Cat-Cow, Pilates rep work) and the UI shows
  // the rep-entry row instead of a hold timer.
  is_bilateral?: boolean;
  is_timed?: boolean;
}

export interface StrengthSet {
  id: number;
  workout_exercise_id: number;
  set_number: number;
  target_weight_lb: number | null;
  target_reps: number;
  actual_weight_lb: number | null;
  actual_reps: number | null;
  rating: number | null;
  rest_seconds_taken: number | null;
  logged_at: string | null;
  skipped: boolean;
}

export interface StrengthWorkoutExercise {
  id: number;
  workout_id: number;
  exercise_id: string;
  order_index: number;
  superset_id: string | null;
  target_sets: number;
  target_reps_low: number;
  target_reps_high: number;
  target_weight_lb: number | null;
  target_rest_s: number;
  is_timed?: boolean;     // backend flag — target_reps_* are hold seconds
  notes: string | null;
  sets: StrengthSet[];
}

export interface StrengthWorkoutDetail {
  id: number;
  date: string;
  generated_at: string;
  split_focus: string;
  status: string;
  seed: string;
  recovery_score_used: number | null;
  readiness_score_used: number | null;
  sleep_h_used: number | null;
  started_at: string | null;
  completed_at: string | null;
  notes: string | null;
  recovery_stale?: boolean;
  exercises: StrengthWorkoutExercise[];
}
