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
  /** "sleep" or "nap", classified server-side (analytics/events.py). Older
   *  backends omit it; treat a missing value as "sleep". */
  kind?: string;
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
  /** Fields backfilled from an EARLIER day → the date they came from.
   *  Present so a client never states a carried value as today's. */
  carried_from?: Record<string, string>;
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

export interface ReadinessDriver {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  /** z against the 28-day baseline; null for the sleep branches. */
  z: number | null;
  sub_score: number | null;
  weight: number;
  baseline: number | null;
  higher_is_better: boolean;
}

export interface ReadinessDetail {
  date: string;
  score: number | null;
  /** low | moderate | high; null when there's no score. */
  band: "low" | "moderate" | "high" | null;
  /** Why there's no score, when there isn't one. */
  reason: string | null;
  drivers: ReadinessDriver[];
  series: Array<{ date: string; score: number | null }>;
  weights: Record<string, number>;
  bands: Record<string, string>;
}

/** One GPS track from `/activities/map` — simplified, map-rendering only. */
export interface MapTrack {
  source: string;
  source_id: string;
  type: string;
  name: string | null;
  start_at: string;
  duration_s: number;
  distance_m: number | null;
  trail_id: number | null;
  trail_name: string | null;
  /** RDP-simplified; use `activity()` when you need the full track. */
  polyline: string;
}

export interface ActivityMap {
  tracks: MapTrack[];
  /** [south, west, north, east] over every track — the "fit all" extent. */
  bounds: [number, number, number, number] | null;
  /** Bounds of the cluster the user actually trains in. Open on this;
   *  fitting `bounds` lets one holiday ride shrink home to a dot. */
  primary_bounds: [number, number, number, number] | null;
  returned: number;
  source_points: number;
  simplified_points: number;
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
  training_partner?: boolean;  // spotter/partner available → unlocks partner-resistance moves
  cardio_rower?: boolean;
  cardio_bike_indoor?: boolean;
  cardio_mtb_outdoor?: boolean;
  cardio_road_bike?: boolean;
  cardio_treadmill?: boolean;
  exercise_prefs?: Record<string, string>;
  training?: {
    level: "beginner" | "intermediate" | "advanced";
    days_per_week: number;
    split_preference: "auto" | "adaptive" | "full_body" | "upper_lower" | "ppl";
    workout_minutes: number;            // deprecated (WP-17); kept for compat
    exercises_per_workout?: number | null;  // WP-17 — null = auto
    include_mobility?: boolean;
    yoga_on_rest_days?: boolean;
    cardio_days_per_week?: number;
    goal?: "strength" | "hypertrophy" | "general";
    program?: ProgramConfig;  // PROG-1 — opt-in linear-progression mode
  };
}

// PROG-1 — program mode. One core lift under a fixed progression scheme.
export interface ProgramLiftState {
  exercise_id: string;
  scheme: "greyskull" | "linear" | "double";
  current_weight_lb?: number | null;
  increment_lb?: number;
  sets?: number;
  reps_low?: number;
  reps_high?: number;
  amrap_last_set?: boolean;
  rest_s?: number;
  consecutive_fails?: number;
  fails_before_deload?: number;
  deload_pct?: number;
  last_advanced_on?: string | null;
}

export interface ProgramConfig {
  enabled: boolean;
  lifts: ProgramLiftState[];
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
  force?: string | null;  // CAT-1: push / pull / static (free-exercise-db)
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
  set_type?: string;
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
  load_hint?: string | null;  // LOAD-1: "30 lb DB + 2.5 lb wrist" when micro-loaders needed
  program_scheme?: string | null;  // PROG-1: "Greyskull LP · AMRAP last · +5" badge on program lifts
  // LOG-1: previous session's working sets, for a faint "last: 30×8 · 30×8" ghost line.
  last_sets?: { set_number: number; weight_lb: number | null; reps: number | null }[];
  // SKIP-1: the user explicitly declined this slot. Distinct from an empty
  // `sets` array, which means "never touched" — render collapsed with an
  // Undo instead of a live logging table.
  skipped?: boolean;
  // TD-10: the user appended this slot themselves; the generator did not
  // prescribe it. Rendered with a small marker so a session's plan and its
  // improvisations stay distinguishable after the fact.
  added_ad_hoc?: boolean;
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
  paused_at?: string | null;    // ISO datetime while status === "paused"
  total_paused_s?: number;      // accumulated paused seconds (WP-14)
  fasting_context?: {
    active: boolean;
    current_hours: number;
    stage: string;
    modulation: string;       // "normal" | "volume_-20%" | "volume_-30%_cardio_priority"
  } | null;
  // Automatic recovery deload applied to this plan's weights (1.0 = none).
  // < 1.0 → show "load eased for recovery — Use full weight" banner.
  deload_factor?: number;
  deload_reason?: string | null;  // e.g. "low recovery 52"
  // SKIP-1 progress counters, computed server-side. The only source for
  // these numbers on either surface — the clients used to derive them
  // independently and disagreed over whether skipped sets counted.
  exercises_done?: number;
  exercises_total?: number;
  sets_done?: number;
  sets_total?: number;
  exercises: StrengthWorkoutExercise[];
}

/** One tile from GET /summary/tiles. The verdict (`status`) is decided
 *  server-side — see analytics/tiles.py — so both clients agree. */
export interface VitalTilePoint { date: string; value: number | null }
export interface VitalTile {
  key: string;
  label: string;
  unit: string;
  value: number | string | null;
  kind: "baseline" | "target" | "neutral";
  higher_is_better: boolean | null;
  baseline: number | null;
  /** Explicit "your normal" bounds. The rule that produces them is a
   *  health judgement and lives in analytics/tiles.py, not in a client. */
  band_low: number | null;
  band_high: number | null;
  /** Section heading for the Key metrics grid, assigned server-side. */
  group?: string;
  target?: number | null;
  delta: number | null;
  z?: number | null;
  status: "good" | "typical" | "watch" | null;
  status_reason: string | null;
  /** Set for intermittently-measured metrics (weight, BP): the date of the
   *  reading being shown, and how many days old it is. */
  as_of: string | null;
  stale_days: number | null;
  series: VitalTilePoint[];
}
export interface VitalTilesRollup {
  judged: number;
  in_range: number;
  total: number;
}
export interface VitalTilesResponse {
  date: string;
  tiles: VitalTile[];
  /** Health-status roll-up, counted server-side so the surfaces agree. */
  summary?: VitalTilesRollup;
  /** Weekly steps progress for the hero ring, summed server-side against
   *  seven days of the user's own daily goal. */
  week?: { label: string; done: number; goal: number; pct: number };
  /** Section headings in display order. */
  group_order?: string[];
  /** Per-focus-area "N tracked" counts. */
  focus_areas?: Record<string, { tracked: number; total: number }>;
}

/** One card from GET /summary/events. Wording and nap-vs-night
 *  classification are the server's — see analytics/events.py. */
export interface NarrativeSegment {
  start: string;
  stage: string;
  duration_s: number;
}
export interface NarrativeStat {
  label: string;
  value: string;
  chip: string;
  tone: "good" | "typical" | "watch";
}
export interface NarrativeEvent {
  id: string;
  /** Nested stat cards (sleep score / duration). Empty for a nap — it is
   *  not scored and has no goal. */
  stats?: NarrativeStat[];
  /** "up" | "down", or null when the user hasn't voted. */
  feedback: string | null;
  kind: "nap" | "sleep";
  headline: string;
  detail: string;
  start: string;
  end: string;
  duration_s: number;
  title: string | null;
  stages: Array<{ stage: string; duration_s: number }>;
  segments: NarrativeSegment[];
}
export interface NarrativeEventsResponse {
  date: string;
  events: NarrativeEvent[];
}


/** GET /summary/training-load — weekly load against the acute:chronic band.
 *  The band and the verdict are the server's; clients render, never judge. */
export interface TrainingLoad {
  week_load: number;
  target_low: number | null;
  target_high: number | null;
  acwr: number | null;
  band: "under" | "optimal" | "overreaching" | "unknown" | string;
  ctl: number | null;
  atl: number | null;
  daily: Array<{ date: string; load: number }>;
}


/** One HR zone as the server defines it. Boundaries are absolute bpm derived
 *  from the user's max HR, so no client needs its own percentage table. */
export interface HrZone {
  zone: string;          // "Z1".."Z5"
  label: string;         // "Recovery".."VO2 Max"
  lo_pct: number;
  hi_pct: number | null; // null on the open-ended top zone
  lo_bpm: number;
  hi_bpm: number | null;
  seconds: number;
  pct: number;
}

/** GET /activities/{source}/{source_id}/zones */
export interface ActivityZones {
  source: string;
  source_id: string;
  max_hr: number;
  /** Where max_hr came from: a measured profile value, a Tanaka estimate
   *  from the birth date, or the age-40 default when neither exists. The UI
   *  says so, because a zone chart is only as good as its denominator. */
  max_hr_source: "profile" | "estimated" | "default";
  age_used: number | null;
  /** False when there was no HR series and the whole session was attributed
   *  to a single zone from avg_hr. A flat bar then means "coarse", not "even". */
  sampled: boolean;
  total_seconds: number;
  zones: HrZone[];
  series: Array<{ minute: number } & Record<string, number>>;
}

/** GET /activities/zones — rolling time-in-zone across recent cardio. */
export interface CardioZones {
  max_hr: number;
  max_hr_source: "profile" | "estimated" | "default";
  age_used: number | null;
  days: number;
  sessions: number;
  zone_minutes: Record<string, number>;
  polarized_ratio: number | null;
  weekly_zone_minutes: Array<{ week: string } & Record<string, number>>;
  by_type: Record<string, { sessions: number; total_min: number; avg_hr_pct_max: number | null }>;
  bounds: Omit<HrZone, "seconds" | "pct">[];
  zone_labels: Record<string, string>;
}


/** What one finished strength session cost — TD-4.
 *
 *  Every field is computed once, on the server. `net_duration_s` in
 *  particular replaces two client derivations that used gross elapsed time
 *  and so disagreed with the training-load model about the same workout. */
export interface SessionSummary {
  /** Elapsed minus accumulated pause. Null until the session is finished. */
  net_duration_s: number | null;
  working_sets: number;
  total_reps: number;
  total_volume_lb: number;
  avg_hr: number | null;
  max_hr: number | null;
  kcal_est: number | null;
  /** How kcal_est was reached: integrated from the real heart-rate series,
   *  from a compendium MET value scaled by body weight, or not at all
   *  because the profile lacks the inputs. Render it — an estimate shown as
   *  a bare number is indistinguishable from a measurement. */
  kcal_method: "hr" | "met" | "none";
}
