// Types mirror the FastAPI backend's real response shapes exactly (field
// names, nullability, envelope). See app/*/schemas.py and app/*/router.py
// in the SWMS backend for the source of truth each of these was checked
// against directly.

export interface ApiSuccess<T> {
  success: true
  data: T
}

export interface ApiErrorBody {
  code: string
  message: string
  details: unknown
  request_id: string
  timestamp: string
}

export interface ApiFailure {
  success: false
  error: ApiErrorBody
}

export type ApiEnvelope<T> = ApiSuccess<T> | ApiFailure

// --- Auth ------------------------------------------------------------------

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

// --- Habitations -------------------------------------------------------------

export type HabitationStatus = 'DRAFT' | 'READY' | 'ARCHIVED'
export type HabitationType = 'VILLAGE' | 'WARD' | 'TOWN' | 'CITY'

export interface Habitation {
  id: string
  name: string
  habitation_type: HabitationType
  state: string
  district: string
  country: string
  area_sqkm: number | null
  status: HabitationStatus
  active_parameter_set_id: string | null
  created_by: string
  created_at: string
}

// --- Simulation runs ---------------------------------------------------------

export type RunStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
export type RunType = 'BASE' | 'SCENARIO' | 'SENSITIVITY' | 'OPTIMIZED'

export interface SimulationRun {
  id: string
  habitation_id: string
  parameter_set_id: string
  coefficient_set_id: string
  engine_version: string
  run_type: RunType
  parent_run_id: string | null
  label: string | null
  horizon_years: number
  status: RunStatus
  param_overrides: Record<string, unknown>
  config: Record<string, unknown>
  job_id: string | null
  progress_pct: number
  error_detail: string | null
  created_by: string
  started_at: string | null
  completed_at: string | null
  created_at: string
  // Only present on the POST .../simulations create response, not on GET.
  poll_url?: string
  reused?: boolean
}

export interface SimulationCreatePayload {
  horizon_years?: number
  label?: string
  param_overrides?: Record<string, number | string>
}

// One row of simulation_yearly — exact lowercase column names, per the
// dashboard spec's own "critical naming rule".
export interface SimulationYearly {
  year_index: number
  population_end: number
  waste_total_tpy: number
  waste_collected_tpy: number
  waste_uncollected_tpy: number
  treated_tpy: number
  recovered_tpy: number
  landfilled_tpy: number
  landfill_remaining_tonnes: number
  avg_coverage_pct: number
  peak_vehicle_shortfall: number
  opex_inr: number
  capex_inr: number
  total_cost_inr: number
  discounted_cost_inr: number
  ghg_tco2e: number
  recovery_rate_pct: number
}

export interface SimulationResultsResponse {
  aggregate: 'yearly' | 'monthly'
  series: SimulationYearly[]
}

// --- Reports -----------------------------------------------------------------

export type ReportFormat = 'PDF' | 'XLSX' | 'CSV'
export type ReportStatus = 'QUEUED' | 'GENERATING' | 'READY' | 'FAILED'

export interface ReportResponse {
  id: string
  habitation_id: string
  run_id: string | null
  comparison_id: string | null
  format: ReportFormat
  status: ReportStatus
  error_detail: string | null
  expires_at: string | null
  created_at: string
  job_id?: string
  poll_url?: string
}

export interface ReportDownload {
  url: string
  expires_at: string | null
}

// --- GIS -----------------------------------------------------------------------

export type LayerType =
  | 'ROAD'
  | 'SETTLEMENT'
  | 'INDUSTRIAL_ZONE'
  | 'WATER_BODY'
  | 'TERRAIN_CONTOUR'
  | 'ECO_SENSITIVE'
  | 'ADMIN_BOUNDARY'
  | 'FACILITY_TREATMENT'
  | 'FACILITY_LANDFILL'
  | 'COLLECTION_ZONE'

export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection'
  features: GeoJSON.Feature[]
}

export interface MapLayer {
  layer_id: string
  layer_type: LayerType
  layer_name: string
  z_index: number
  style: Record<string, unknown>
  feature_count: number
  mode: 'geojson' | 'tiles'
  features?: GeoJsonFeatureCollection
  tile_url?: string
}

export interface MapOverlay {
  habitation_id: string
  bbox: [number, number, number, number] | null
  boundary: GeoJSON.Geometry | null
  layers: MapLayer[]
  cache: { hit: boolean; ttl_seconds: number }
}

// --- Chat ------------------------------------------------------------------

export interface ChatSession {
  id: string
  habitation_id: string
  user_id: string
  title: string | null
  created_at: string
  last_active_at: string
}

export type ChatRole = 'USER' | 'ASSISTANT' | 'SYSTEM'

export interface ChatCitation {
  run_id?: string
  year_index?: number
  month_index?: number
  indicator?: string
  field?: string
  job_id?: string
  [key: string]: unknown
}

export interface ChatMessage {
  id: number
  role: ChatRole
  content: string
  citations: ChatCitation[]
  latency_ms: number | null
  created_at: string
}
