// Mirrors src/salafleezers/web/schemas.py — keep in sync with the backend.

export interface HealthInfo {
  status: string
  version: string
  auth_required: boolean
  max_upload_bytes: number
}

export interface WsTicket {
  ticket: string
  expires_in: number
}

export interface SessionInfo {
  session_id: string
  created_at: string
  n_files: number
  file_ids: string[]
}

export interface FileOpenRequest {
  // Exactly one of `path` or (`dataset_id` + `relative_path`).
  path?: string | null
  dataset_id?: string | null
  relative_path?: string | null
  session_id?: string | null
}

export interface TraceMetadata {
  file_id: string
  filename: string
  n_samples: number
  sampling_rate_hz: number
  duration_s: number
  channels: string[]
  meta: Record<string, unknown>
}

export interface TracePreview {
  file_id: string
  session_id: string
  time: number[]
  channels: Record<string, number[]>
  n_original: number
  decimate_factor: number
  sampling_rate_hz: number
  filename: string
}

export interface TraceSegment {
  file_id: string
  channel: string
  time: number[]
  data: number[]
  n_original: number
  decimate_factor: number
  t_start: number
  t_end: number
}

export type StepFindAlgorithm = 'kv' | 'hmm'

export interface StepFindRequest {
  session_id: string
  file_id: string
  channel?: string
  algorithm?: StepFindAlgorithm
  pen_factor?: number
  n_states?: number
  t_start?: number | null
  t_end?: number | null
}

export interface StepFindResult {
  session_id: string
  file_id: string
  result_id: string
  algorithm: string
  n_steps: number
  step_positions: number[]
  step_times: number[]
  levels: number[]
  chi2: number | null
  // The range this result was computed over -- downstream consumers
  // (velocity method="steps", kinetics) must re-apply the same range before
  // indexing a time axis with step_positions.
  t_start?: number | null
  t_end?: number | null
}

export type WLCMethod = 'basic' | 'marko_siggia' | 'bouchiat'

export interface WLCFitRequest {
  session_id: string
  file_id: string
  F_channel?: string
  x_channel?: string
  method?: WLCMethod
  P0?: number
  S0?: number
  fit_offsets?: boolean
  t_start?: number | null
  t_end?: number | null
}

export interface WLCFitResult {
  session_id: string
  file_id: string
  P_nm: number
  Lc_nm: number
  S_pN: number
  x_offset_nm: number
  F_offset_pN: number
  chi2: number
  method: string
  F_model: number[]
  x_model: number[]
}

export type VelocityMethod = 'savgol' | 'steps'

export interface VelocityRequest {
  session_id: string
  file_id: string
  channel?: string
  method?: VelocityMethod
  window?: number
  polyorder?: number
  step_result_id?: string | null
  t_start?: number | null
  t_end?: number | null
}

export interface VelocityResult {
  session_id: string
  file_id: string
  v_centers: number[]
  counts: number[]
  mean_velocity_nm_s: number
}

export interface PWDRequest {
  session_id: string
  file_id: string
  channel?: string
  bins?: number
  t_start?: number | null
  t_end?: number | null
}

export interface PWDResult {
  session_id: string
  file_id: string
  bin_centers: number[]
  pwd_counts: number[]
  step_sizes: number[]
  peak_heights: number[]
}

export type KineticsModel = 'exponential' | 'gamma'

export interface KineticsRequest {
  session_id: string
  file_id: string
  dwell_times?: number[] | null
  step_result_id?: string | null
  model?: KineticsModel
  n_components?: number
  n_restarts?: number
}

export interface KineticsResult {
  session_id: string
  file_id: string
  model: string
  n_components: number
  rates: number[] | null
  amplitudes: number[] | null
  shapes: number[] | null
  scales: number[] | null
  log_likelihood: number
  aic: number
  bic: number
}

export interface KDERequest {
  session_id: string
  file_id: string
  channel?: string
  n_points?: number
  bandwidth?: number | string
  t_start?: number | null
  t_end?: number | null
}

export interface KDEResult {
  session_id: string
  file_id: string
  x: number[]
  density: number[]
  bandwidth: number
}

export interface ViolinRequest {
  session_id: string
  file_ids: string[]
  channel?: string
  bandwidth?: number | string
  t_start?: number | null
  t_end?: number | null
}

export interface ViolinGroup {
  label: string
  x: number[]
  density: number[]
  median: number
  quartile_25: number
  quartile_75: number
  whisker_lo: number
  whisker_hi: number
  n: number
}

export interface ViolinResult {
  session_id: string
  channel: string
  groups: ViolinGroup[]
}

export interface MSDRequest {
  session_id: string
  file_id: string
  channel?: string
  max_lag?: number | null
  t_start?: number | null
  t_end?: number | null
}

export interface MSDResult {
  session_id: string
  file_id: string
  lags_s: number[]
  msd: number[]
}

export interface MeasurementResult {
  mean: number
  std: number
  median: number
  min: number
  max: number
  n_pts: number
  t_start: number
  t_end: number
  duration: number
}

// ---------------------------------------------------------------------------
// Uploads (browser-side data intake — see web/workspace.py)
// ---------------------------------------------------------------------------

export type UploadEntryKind = 'trace' | 'sidecar' | 'batch' | 'skipped'

export interface UploadEntry {
  relative_path: string
  size_bytes: number
  kind: UploadEntryKind
  parent: string | null
  sidecars: string[]
  missing_sidecars: string[]
  warning: string | null
}

export interface Dataset {
  dataset_id: string
  name: string
  created_at: string
  finalized: boolean
  total_bytes: number
  entries: UploadEntry[]
}

export interface UploadedFileInfo {
  relative_path: string
  size_bytes: number
}
