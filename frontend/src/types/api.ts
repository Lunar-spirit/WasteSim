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

// The backend's user_role enum spells the fourth role POLICY_VIEWER, not
// VIEWER — kept as-is rather than renamed via a migration against a live
// enum type; "Viewer" is just its label everywhere in this UI.
export type UserRole = 'ADMIN' | 'PLANNER' | 'RESEARCHER' | 'POLICY_VIEWER'

export interface CurrentUser {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
}

// --- Admin access control ---------------------------------------------------

export interface UserAccess {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  habitation_ids: string[]
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

export interface HabitationCreatePayload {
  name: string
  habitation_type: HabitationType
  state: string
  district: string
  country?: string
  centroid_geojson?: Record<string, unknown> | null
  boundary_geojson?: Record<string, unknown> | null
  area_sqkm?: number | null
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
  engine_mode?: EngineMode
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
  // Null only for a run completed before this breakdown existed — see
  // migration 0016; every run since always sets a real value.
  organic_tpy: number | null
  dry_recyclable_tpy: number | null
  inert_tpy: number | null
  landfill_remaining_tonnes: number
  cumulative_landfill_tonnes: number | null
  avg_coverage_pct: number
  peak_vehicle_shortfall: number
  opex_inr: number
  capex_inr: number
  total_cost_inr: number
  discounted_cost_inr: number
  ghg_tco2e: number
  recovery_rate_pct: number
}

// One row per run per month — only the fields the charts actually use
// (app/simulation/models.py's SimulationResult has more; _row_to_dict
// returns all of them, this just types what this app reads).
export interface SimulationMonthly {
  month_index: number
  year_index: number
  calendar_month: number
  waste_total_tpd: number
  organic_pct: number
  plastic_pct: number
  paper_pct: number
}

export interface SimulationResultsResponse {
  aggregate: 'yearly' | 'monthly'
  series: SimulationYearly[]
}

export interface SimulationMonthlyResultsResponse {
  aggregate: 'yearly' | 'monthly'
  series: SimulationMonthly[]
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

// --- Parameters ----------------------------------------------------------

export type ParameterSetStatus = 'DRAFT' | 'VALIDATING' | 'VALIDATED' | 'INVALID' | 'ARCHIVED'

export interface ParameterDefinition {
  category: string
  param_key: string
  display_label: string
  unit: string | null
  data_type: string
  min_value: number | null
  max_value: number | null
  is_required: boolean
  normalization_rule: string | null
}

export interface ParameterSet {
  id: string
  habitation_id: string
  version_no: number
  status: ParameterSetStatus
  cloned_from_id: string | null
  change_note: string | null
  created_by: string
  created_at: string
}

export interface ParameterSetDetail extends ParameterSet {
  categories: Record<string, Record<string, unknown>>
  waste_baseline: Record<string, unknown> | null
}

export interface ValidationIssue {
  code: string
  severity: string
  category: string | null
  field: string | null
  message: string
  [key: string]: unknown
}

export interface ValidationReport {
  report_id: string
  scope: string
  result: 'PASS' | 'FAIL'
  error_count: number
  warning_count: number
  completeness_pct: number
  completeness_by_category: Record<string, number>
  rules_version: string
  issues: ValidationIssue[]
}

export interface CommitResult {
  id: string
  version_no: number
  status: ParameterSetStatus
}

// --- GIS layers (CRUD) -----------------------------------------------------

export interface GISLayer {
  id: string
  habitation_id: string
  layer_name: string
  layer_type: LayerType
  geometry_type: string
  source: string
  source_ref: string | null
  status: 'PROCESSING' | 'READY' | 'FAILED'
  is_visible_default: boolean
  z_index: number
  style: Record<string, unknown>
  feature_count: number
  total_length_km: number | null
  srid_original: number | null
  created_by: string
  created_at: string
  updated_at: string
}

// --- Simulation extras -----------------------------------------------------

export interface RunFinding {
  code: string
  severity: string
  numeric_value: number | null
  year_index: number | null
  message: string
}

export type BudgetKind = 'CAPEX' | 'OPEX'
export type BudgetCategory =
  | 'COLLECTION'
  | 'TRANSPORT'
  | 'TREATMENT'
  | 'DISPOSAL'
  | 'FLEET_PURCHASE'
  | 'INFRASTRUCTURE'
  | 'ADMIN'
  | 'AWARENESS'

export interface BudgetLine {
  year_index: number
  kind: BudgetKind
  category: BudgetCategory
  amount_inr: number
  discounted_inr: number
  note: string | null
}

export interface BudgetSummary {
  run_id: string
  total_opex_inr: number
  total_capex_inr: number
  total_cost_inr: number
  npv_total_cost_inr: number
  by_category: Record<string, number>
}

// --- Scenario --------------------------------------------------------------

export type EventType =
  | 'FLOOD'
  | 'LANDSLIDE'
  | 'HEAVY_MONSOON'
  | 'ROAD_BLOCKAGE'
  | 'POPULATION_SURGE'
  | 'VEHICLE_BREAKDOWN'
  | 'TREATMENT_PLANT_OUTAGE'
  | 'FESTIVAL'
  | 'STRIKE'

export interface EventCatalogueItem {
  event_type: string
  effect: string
  magnitude_source: string
}

// Matches app/scenario/models.py's EventSeverity exactly — a prior 'MILD'
// here (instead of 'LOW') meant every low-intensity "Run Full Scenario"
// click sent a value the backend's Pydantic enum rejected outright (400).
export type EventSeverity = 'LOW' | 'MODERATE' | 'SEVERE'

export interface EventIn {
  event_type: EventType
  start_month: number
  duration_months: number
  recovery_months: number
  severity: EventSeverity
  affected_area?: Record<string, unknown> | null
  impact_params?: Record<string, unknown>
}

export interface ScenarioEvent {
  id: string
  event_type: EventType
  start_month: number
  duration_months: number
  recovery_months: number
  severity: string
  impact_params: Record<string, unknown>
  derived_impacts: Record<string, unknown>
  created_at: string
}

export interface ImpactPreview {
  derived: boolean
  message?: string
  derived_impacts?: Record<string, unknown>
}

// --- Sensitivity -------------------------------------------------------------

export type AnalysisStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface SensitivityPoint {
  id: number
  swept_value: number
  child_run_id: string | null
  indicator_values: Record<string, number>
  elasticity: Record<string, number> | null
  error: string | null
}

export interface SensitivityAnalysis {
  id: string
  habitation_id: string
  base_run_id: string
  param_path: string
  swept_values: number[]
  indicators: string[]
  status: AnalysisStatus
  created_at: string
  completed_at: string | null
  job_id?: string
  points?: SensitivityPoint[]
}

// Ranked by how much the one swept parameter moves each indicator (API-65)
// — NOT one bar per parameter; this analysis only ever sweeps one.
export interface TornadoRow {
  indicator: string
  min_value: number
  max_value: number
  range: number
  max_abs_elasticity: number | null
}

// --- Optimization ------------------------------------------------------------

export type OptObjective = 'MIN_COST' | 'MIN_LANDFILL' | 'MAX_COVERAGE' | 'MAX_RECOVERY' | 'MIN_GHG' | 'MAX_RESILIENCE'

// The POST .../optimizations response shape (app/optimization/router.py's
// create_optimization) — deliberately NOT the same shape as GET
// .../optimizations/{id} (OptimizationRunOut): it uses "optimization_id",
// not "id", and doesn't return every OptimizationRunOut field.
export interface OptimizationCreateResult {
  optimization_id: string
  status: AnalysisStatus
  job_id: string
  decision_space: Record<string, [number, number]>
  notes: string[]
  poll_url: string
}

export interface OptimizationRun {
  id: string
  habitation_id: string
  base_run_id: string
  decision_space: Record<string, [number, number]>
  constraints: Record<string, unknown>
  strategy: string
  candidates_evaluated: number
  status: AnalysisStatus
  best_candidate_id: number | null
  promoted_run_id: string | null
  infeasible_reason: string | null
  created_at: string
  completed_at: string | null
  job_id?: string
  notes?: string[]
}

export interface OptimizationReadinessChecks {
  base_simulation_exists: boolean
  parameters_validated: boolean
  worker_available: boolean
  gis_roads_ready: boolean
}

export interface OptimizationReadiness {
  can_run: boolean
  blocking_reason: string | null
  action_label: string | null
  action_tab: string | null
  checks: OptimizationReadinessChecks
}

export interface OptimizationCandidate {
  id: number
  stage: string
  decision_values: Record<string, number>
  feasible: boolean
  violated_constraints: string[]
  objective_values: Record<string, number>
  normalised_values: Record<string, number>
  score: number | null
  is_pareto: boolean
  capex_total_inr: number | null
}

export interface OptimizationExplanation {
  [key: string]: unknown
}

// --- Comparison ----------------------------------------------------------------

export interface Comparison {
  id: string
  habitation_id: string
  run_ids: string[]
  indicators: string[]
  title: string | null
  created_at: string
}

export interface ComparisonSeriesRow {
  year_index: number
  values: Record<string, number | null>
}

export interface ComparisonSeries {
  run_ids: string[]
  indicators: string[]
  series: Record<string, ComparisonSeriesRow[]>
}

export interface ComparisonDeltaRow {
  year_index: number
  [runId: string]: number | null
}

export interface ComparisonDeltas {
  base_run_id: string
  deltas: Record<string, ComparisonDeltaRow[]>
}

// --- Daily Waste Logs --------------------------------------------------------

export type AnomalyFlag = 'NORMAL' | 'MONSOON_FLOOD' | 'FESTIVAL_SURGE' | 'WORKER_STRIKE' | 'BREAKDOWN'

export interface DailyLog {
  id: string
  habitation_id: string
  logged_by: string
  log_date: string
  total_collected_tonnes: number
  organic_tonnes: number
  dry_recyclable_tonnes: number
  hazardous_tonnes: number | null
  vehicles_deployed: number
  trips_completed: number
  diesel_consumed_litres: number | null
  collection_coverage_pct_observed: number | null
  anomaly_flag: AnomalyFlag
  notes: string | null
  created_at: string
  updated_at: string
}

export interface DailyLogIn {
  log_date: string
  total_collected_tonnes: number
  organic_tonnes: number
  dry_recyclable_tonnes: number
  hazardous_tonnes?: number | null
  vehicles_deployed: number
  trips_completed: number
  diesel_consumed_litres?: number | null
  collection_coverage_pct_observed?: number | null
  anomaly_flag?: AnomalyFlag
  notes?: string | null
}

export interface DailyLogPage {
  items: DailyLog[]
  total: number
  page: number
  page_size: number
}

export interface BulkImportRowError {
  row_number: number
  message: string
}

export interface BulkImportResult {
  total_rows: number
  created_count: number
  updated_count: number
  error_count: number
  errors: BulkImportRowError[]
}

export type ExportPeriodType = 'monthly' | 'yearly' | 'custom'

export interface DailyLogExportParams {
  period_type: ExportPeriodType
  year?: number
  month?: number
  start_date?: string
  end_date?: string
  format?: 'csv' | 'xlsx'
}

// --- Recalibration / DATA_DRIVEN_HYBRID -------------------------------------

export type EngineMode = 'THEORETICAL' | 'DATA_DRIVEN_HYBRID'

export interface MovingAverage {
  window_days: number
  sample_days: number
  avg_total_collected_tpd: number | null
  avg_organic_tpd: number | null
  avg_dry_recyclable_tpd: number | null
  avg_vehicles_deployed: number | null
  avg_coverage_pct_observed: number | null
}

export interface VarianceMetric {
  label: string
  theoretical: number | null
  empirical: number | null
  variance_pct: number | null
}

export interface RecalibrationReport {
  habitation_id: string
  as_of: string
  logged_day_count_90d: number
  moving_average_30d: MovingAverage
  moving_average_90d: MovingAverage
  moving_average_annual: MovingAverage
  total_generation_variance: VarianceMetric
  per_capita_variance: VarianceMetric
  segregation_variance: VarianceMetric
  fleet_efficiency_variance: VarianceMetric
  derived_festival_multiplier: number | null
  notes: string[]
}

// --- Auto-populate -----------------------------------------------------------

export type RoadDiagnosticsStatus = 'SUCCESS' | 'NO_DATA_FOUND' | 'ERROR'

export interface RoadDiagnostics {
  status: RoadDiagnosticsStatus
  reason: string | null
  // [lat, lon] pairs, Overpass's own coordinate order — exactly what was
  // sent to the poly: filter, for spotting a lat/lon-vs-lon/lat mismatch.
  query_boundary_ring: number[][] | null
  overpass_raw_node_count: number | null
  overpass_raw_way_count: number | null
  overpass_raw_relation_count: number | null
  parsed_linestring_count: number | null
  total_length_km: number | null
  gis_layer_id: string | null
}

export interface SkippedCategory {
  category: string
  reason: string
}

export interface AutoPopulateResult {
  parameter_set_id: string
  automated_categories: string[]
  skipped_categories: SkippedCategory[]
  derived_fields: string[]
  manual_fields_remaining: string[]
  gis_layer_id: string | null
  road_diagnostics: RoadDiagnostics
}

// --- Comparative scenario preview --------------------------------------------

export interface ComparativePreviewIn {
  habitation_id: string
  base_run_id: string
  event_type: EventType
  severity_intensity: EventSeverity
  duration_weeks: number
  start_month: number
  apply_full_boundary: boolean
  custom_polygon_geojson?: Record<string, unknown> | null
}

export interface ComparativePreviewPoint {
  month: number
  base_collected_tpd: number
  scenario_collected_tpd: number
  base_opex_inr: number
  scenario_opex_inr: number
  uncollected_backlog_tonnes: number
}

export interface ComparativePreviewResult {
  event_type: EventType
  severity_intensity: EventSeverity
  duration_months: number
  start_month: number
  horizon_months: number
  series: ComparativePreviewPoint[]
  peak_backlog_tonnes: number
  net_financial_penalty_inr: number
  recovery_time_weeks: number | null
  notes: string[]
}
