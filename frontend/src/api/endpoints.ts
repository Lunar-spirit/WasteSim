import { apiClient, unwrap } from './client'
import type {
  ApiEnvelope,
  AutoPopulateResult,
  BudgetLine,
  BudgetSummary,
  BulkImportResult,
  ChatHistoryTurn,
  ChatMessage,
  ChatMessageReply,
  ChatSession,
  CommitResult,
  ComparativePreviewIn,
  ComparativePreviewResult,
  Comparison,
  ComparisonDeltas,
  ComparisonSeries,
  CurrentUser,
  DailyLog,
  DailyLogExportParams,
  DailyLogIn,
  DailyLogPage,
  EventCatalogueItem,
  EventIn,
  GISLayer,
  Habitation,
  HabitationCreatePayload,
  ImpactPreview,
  LayerType,
  MapOverlay,
  OptimizationCandidate,
  OptimizationCreateResult,
  OptimizationExplanation,
  OptimizationReadiness,
  OptimizationRun,
  ParameterDefinition,
  ParameterSet,
  ParameterSetDetail,
  RecalibrationReport,
  ReportDownload,
  ReportResponse,
  RunFinding,
  ScenarioEvent,
  SensitivityAnalysis,
  SimulationCreatePayload,
  SimulationMonthlyResultsResponse,
  SimulationResultsResponse,
  SimulationRun,
  TornadoRow,
  UserAccess,
  UserRole,
  ValidationReport,
} from '../types/api'

// --- Current user ------------------------------------------------------------

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const { data } = await apiClient.get<ApiEnvelope<CurrentUser>>('/api/v1/auth/me')
  return unwrap(data)
}

// --- Admin access control ---------------------------------------------------

export async function fetchUsersWithAccess(): Promise<UserAccess[]> {
  const { data } = await apiClient.get<ApiEnvelope<UserAccess[]>>('/api/v1/admin/access/users')
  return unwrap(data)
}

export async function assignPlanner(userId: string, habitationId: string): Promise<void> {
  const { data } = await apiClient.post<ApiEnvelope<unknown>>('/api/v1/admin/access/assign', {
    user_id: userId,
    habitation_id: habitationId,
  })
  unwrap(data)
}

export async function unassignPlanner(userId: string, habitationId: string): Promise<void> {
  const { data } = await apiClient.delete<ApiEnvelope<unknown>>('/api/v1/admin/access/unassign', {
    data: { user_id: userId, habitation_id: habitationId },
  })
  unwrap(data)
}

export async function changeUserRole(userId: string, role: UserRole): Promise<CurrentUser> {
  const { data } = await apiClient.patch<ApiEnvelope<CurrentUser>>(`/api/v1/admin/access/users/${userId}/role`, {
    role,
  })
  return unwrap(data)
}

export async function fetchHabitations(): Promise<Habitation[]> {
  const { data } = await apiClient.get<ApiEnvelope<Habitation[]>>('/api/v1/habitations')
  return unwrap(data)
}

export async function fetchHabitation(habitationId: string): Promise<Habitation> {
  const { data } = await apiClient.get<ApiEnvelope<Habitation>>(`/api/v1/habitations/${habitationId}`)
  return unwrap(data)
}

export async function createHabitation(payload: HabitationCreatePayload): Promise<Habitation> {
  const { data } = await apiClient.post<ApiEnvelope<Habitation>>('/api/v1/habitations', payload)
  return unwrap(data)
}

// --- Simulation --------------------------------------------------------------

export async function createSimulation(
  habitationId: string,
  payload: SimulationCreatePayload & { parameter_set_id?: string; run_type?: string },
): Promise<SimulationRun> {
  const { data } = await apiClient.post<ApiEnvelope<SimulationRun>>(
    `/api/v1/habitations/${habitationId}/simulations`,
    payload,
  )
  return unwrap(data)
}

export async function listSimulations(habitationId: string): Promise<SimulationRun[]> {
  const { data } = await apiClient.get<ApiEnvelope<SimulationRun[]>>(
    `/api/v1/habitations/${habitationId}/simulations`,
  )
  return unwrap(data)
}

export async function fetchSimulationRun(runId: string): Promise<SimulationRun> {
  const { data } = await apiClient.get<ApiEnvelope<SimulationRun>>(`/api/v1/simulations/${runId}`)
  return unwrap(data)
}

export async function fetchSimulationResults(runId: string): Promise<SimulationResultsResponse> {
  const { data } = await apiClient.get<ApiEnvelope<SimulationResultsResponse>>(
    `/api/v1/simulations/${runId}/results`,
    { params: { aggregate: 'yearly' } },
  )
  return unwrap(data)
}

export async function fetchSimulationMonthlyResults(runId: string): Promise<SimulationMonthlyResultsResponse> {
  const { data } = await apiClient.get<ApiEnvelope<SimulationMonthlyResultsResponse>>(
    `/api/v1/simulations/${runId}/results`,
    { params: { aggregate: 'monthly' } },
  )
  return unwrap(data)
}

export async function fetchSimulationFindings(runId: string): Promise<RunFinding[]> {
  const { data } = await apiClient.get<ApiEnvelope<RunFinding[]>>(`/api/v1/simulations/${runId}/findings`)
  return unwrap(data)
}

export async function fetchBudgetLines(runId: string): Promise<BudgetLine[]> {
  const { data } = await apiClient.get<ApiEnvelope<BudgetLine[]>>(`/api/v1/simulations/${runId}/budget/lines`)
  return unwrap(data)
}

export async function fetchBudgetSummary(runId: string): Promise<BudgetSummary> {
  const { data } = await apiClient.get<ApiEnvelope<BudgetSummary>>(`/api/v1/simulations/${runId}/budget/summary`)
  return unwrap(data)
}

export async function autoPopulateHabitation(habitationId: string): Promise<AutoPopulateResult> {
  const { data } = await apiClient.post<ApiEnvelope<AutoPopulateResult>>(
    `/api/v1/habitations/${habitationId}/auto-populate`,
    {},
  )
  return unwrap(data)
}

// --- Reports -----------------------------------------------------------------

export async function createReport(
  target: { runId: string } | { comparisonId: string },
  format: 'PDF' | 'XLSX' | 'CSV' = 'PDF',
): Promise<ReportResponse> {
  // CRITICAL: send exactly one of run_id/comparison_id — the backend's own
  // schema requires exactly one, and omitting the other key entirely (not
  // even `null`) is the unambiguous way to satisfy that.
  const body =
    'runId' in target ? { run_id: target.runId, format } : { comparison_id: target.comparisonId, format }
  const { data } = await apiClient.post<ApiEnvelope<ReportResponse>>('/api/v1/reports', body)
  return unwrap(data)
}

export async function fetchReport(reportId: string): Promise<ReportResponse> {
  const { data } = await apiClient.get<ApiEnvelope<ReportResponse>>(`/api/v1/reports/${reportId}`)
  return unwrap(data)
}

export async function fetchReportDownloadUrl(reportId: string): Promise<ReportDownload> {
  const { data } = await apiClient.get<ApiEnvelope<ReportDownload>>(`/api/v1/reports/${reportId}/download`)
  return unwrap(data)
}

// --- GIS -----------------------------------------------------------------------

export async function fetchMapOverlay(habitationId: string): Promise<MapOverlay> {
  const { data } = await apiClient.get<ApiEnvelope<MapOverlay>>(`/api/v1/habitations/${habitationId}/map`, {
    params: { limit: 50_000 },
  })
  return unwrap(data)
}

export async function fetchLayers(habitationId: string): Promise<GISLayer[]> {
  const { data } = await apiClient.get<ApiEnvelope<GISLayer[]>>(`/api/v1/habitations/${habitationId}/layers`)
  return unwrap(data)
}

export async function patchLayer(
  layerId: string,
  payload: { is_visible_default?: boolean; style?: Record<string, unknown>; z_index?: number; layer_name?: string },
): Promise<GISLayer> {
  const { data } = await apiClient.patch<ApiEnvelope<GISLayer>>(`/api/v1/layers/${layerId}`, payload)
  return unwrap(data)
}

export async function createLayer(
  habitationId: string,
  payload: { layer_name: string; layer_type: LayerType; geojson: Record<string, unknown> },
): Promise<GISLayer> {
  const { data } = await apiClient.post<ApiEnvelope<GISLayer>>(
    `/api/v1/habitations/${habitationId}/layers`,
    payload,
  )
  return unwrap(data)
}

// --- Parameters ----------------------------------------------------------------

export async function fetchParameterDefinitions(): Promise<ParameterDefinition[]> {
  const { data } = await apiClient.get<ApiEnvelope<ParameterDefinition[]>>('/api/v1/parameter-definitions')
  return unwrap(data)
}

export async function createParameterSet(
  habitationId: string,
  cloneFromVersion?: number,
): Promise<ParameterSet> {
  const { data } = await apiClient.post<ApiEnvelope<ParameterSet>>(
    `/api/v1/habitations/${habitationId}/parameter-sets`,
    { clone_from_version: cloneFromVersion ?? null },
  )
  return unwrap(data)
}

export async function fetchParameterSet(psid: string): Promise<ParameterSetDetail> {
  const { data } = await apiClient.get<ApiEnvelope<ParameterSetDetail>>(`/api/v1/parameter-sets/${psid}`)
  return unwrap(data)
}

export async function upsertParameterCategory(
  psid: string,
  category: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.put<ApiEnvelope<Record<string, unknown>>>(
    `/api/v1/parameter-sets/${psid}/categories/${category}`,
    payload,
  )
  return unwrap(data)
}

export async function upsertWasteBaseline(
  psid: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.put<ApiEnvelope<Record<string, unknown>>>(
    `/api/v1/parameter-sets/${psid}/waste-baseline`,
    payload,
  )
  return unwrap(data)
}

export async function validateParameterSet(psid: string): Promise<ValidationReport> {
  const { data } = await apiClient.post<ApiEnvelope<ValidationReport>>(`/api/v1/parameter-sets/${psid}/validate`)
  return unwrap(data)
}

export async function commitParameterSet(psid: string): Promise<CommitResult> {
  const { data } = await apiClient.post<ApiEnvelope<CommitResult>>(`/api/v1/parameter-sets/${psid}/commit`)
  return unwrap(data)
}

// --- Scenario --------------------------------------------------------------

export async function fetchEventCatalogue(): Promise<EventCatalogueItem[]> {
  const { data } = await apiClient.get<ApiEnvelope<EventCatalogueItem[]>>('/api/v1/event-types')
  return unwrap(data)
}

export async function createScenario(
  baseRunId: string,
  events: EventIn[],
  label?: string,
): Promise<SimulationRun> {
  const { data } = await apiClient.post<ApiEnvelope<SimulationRun>>(
    `/api/v1/simulations/${baseRunId}/scenarios`,
    { label, events },
  )
  return unwrap(data)
}

export async function listScenarioEvents(runId: string): Promise<ScenarioEvent[]> {
  const { data } = await apiClient.get<ApiEnvelope<ScenarioEvent[]>>(`/api/v1/simulations/${runId}/events`)
  return unwrap(data)
}

export async function previewEventImpact(
  runId: string,
  eventType: string,
  affectedArea: Record<string, unknown>,
): Promise<ImpactPreview> {
  const { data } = await apiClient.post<ApiEnvelope<ImpactPreview>>(
    `/api/v1/simulations/${runId}/events/preview`,
    { event_type: eventType, affected_area: affectedArea },
  )
  return unwrap(data)
}

export async function previewComparativeImpact(payload: ComparativePreviewIn): Promise<ComparativePreviewResult> {
  const { data } = await apiClient.post<ApiEnvelope<ComparativePreviewResult>>('/api/v1/scenarios/preview', payload)
  return unwrap(data)
}

// --- Sensitivity -------------------------------------------------------------

export async function createSensitivitySweep(
  habitationId: string,
  baseRunId: string,
  paramPath: string,
  values: number[],
  indicators: string[] = [],
): Promise<SensitivityAnalysis> {
  const { data } = await apiClient.post<ApiEnvelope<SensitivityAnalysis>>(
    `/api/v1/habitations/${habitationId}/sensitivity`,
    { base_run_id: baseRunId, param_path: paramPath, values, indicators },
  )
  return unwrap(data)
}

export async function fetchSensitivityAnalysis(analysisId: string): Promise<SensitivityAnalysis> {
  const { data } = await apiClient.get<ApiEnvelope<SensitivityAnalysis>>(`/api/v1/sensitivity/${analysisId}`)
  return unwrap(data)
}

export async function fetchSensitivityTornado(analysisId: string): Promise<TornadoRow[]> {
  const { data } = await apiClient.get<ApiEnvelope<TornadoRow[]>>(`/api/v1/sensitivity/${analysisId}/tornado`)
  return unwrap(data)
}

// --- Optimization ------------------------------------------------------------

export async function fetchOptimizationReadiness(habitationId: string): Promise<OptimizationReadiness> {
  const { data } = await apiClient.get<ApiEnvelope<OptimizationReadiness>>(
    `/api/v1/habitations/${habitationId}/optimization/readiness`,
  )
  return unwrap(data)
}

export async function createOptimization(
  habitationId: string,
  baseRunId: string,
  objectives: Record<string, number>,
  constraints: Record<string, unknown> = {},
  maxEvaluations = 200,
): Promise<OptimizationCreateResult> {
  const { data } = await apiClient.post<ApiEnvelope<OptimizationCreateResult>>(
    `/api/v1/habitations/${habitationId}/optimizations`,
    { base_run_id: baseRunId, objectives, constraints, max_evaluations: maxEvaluations },
  )
  return unwrap(data)
}

export async function fetchOptimization(optimizationId: string): Promise<OptimizationRun> {
  const { data } = await apiClient.get<ApiEnvelope<OptimizationRun>>(`/api/v1/optimizations/${optimizationId}`)
  return unwrap(data)
}

export async function fetchOptimizationCandidates(optimizationId: string): Promise<OptimizationCandidate[]> {
  const { data } = await apiClient.get<ApiEnvelope<OptimizationCandidate[]>>(
    `/api/v1/optimizations/${optimizationId}/candidates`,
  )
  return unwrap(data)
}

export async function fetchParetoFront(optimizationId: string): Promise<OptimizationCandidate[]> {
  const { data } = await apiClient.get<ApiEnvelope<OptimizationCandidate[]>>(
    `/api/v1/optimizations/${optimizationId}/pareto`,
  )
  return unwrap(data)
}

export async function promoteOptimizationCandidate(
  optimizationId: string,
  candidateId?: number,
): Promise<SimulationRun> {
  const { data } = await apiClient.post<ApiEnvelope<SimulationRun>>(
    `/api/v1/optimizations/${optimizationId}/promote`,
    { candidate_id: candidateId ?? null },
  )
  return unwrap(data)
}

export async function fetchOptimizationExplanation(optimizationId: string): Promise<OptimizationExplanation> {
  const { data } = await apiClient.get<ApiEnvelope<OptimizationExplanation>>(
    `/api/v1/optimizations/${optimizationId}/explanation`,
  )
  return unwrap(data)
}

// --- Comparison ----------------------------------------------------------------

export async function createComparison(runIds: string[], title?: string): Promise<Comparison> {
  const { data } = await apiClient.post<ApiEnvelope<Comparison>>('/api/v1/comparisons', {
    run_ids: runIds,
    title,
  })
  return unwrap(data)
}

export async function fetchComparison(comparisonId: string): Promise<ComparisonSeries> {
  const { data } = await apiClient.get<ApiEnvelope<ComparisonSeries>>(`/api/v1/comparisons/${comparisonId}`)
  return unwrap(data)
}

export async function fetchComparisonDeltas(comparisonId: string): Promise<ComparisonDeltas> {
  const { data } = await apiClient.get<ApiEnvelope<ComparisonDeltas>>(
    `/api/v1/comparisons/${comparisonId}/deltas`,
  )
  return unwrap(data)
}

// --- Chat ------------------------------------------------------------------

export async function createChatSession(habitationId: string): Promise<ChatSession> {
  const { data } = await apiClient.post<ApiEnvelope<ChatSession>>('/api/v1/chat/sessions', {
    habitation_id: habitationId,
  })
  return unwrap(data)
}

export async function sendChatQuery(
  sessionId: string,
  message: string,
  runId: string | null,
): Promise<ChatMessage> {
  const { data } = await apiClient.post<ApiEnvelope<ChatMessage>>(`/api/v1/chat/sessions/${sessionId}/query`, {
    message,
    run_id: runId,
  })
  return unwrap(data)
}

/** The floating copilot's stateless endpoint — no session, no server-side
 * persistence; the caller resends its own running `history` every call. */
export async function sendFloatingChatMessage(
  habitationId: string | null,
  message: string,
  history: ChatHistoryTurn[],
): Promise<ChatMessageReply> {
  const { data } = await apiClient.post<ApiEnvelope<ChatMessageReply>>('/api/v1/chat/message', {
    habitation_id: habitationId,
    message,
    history,
  })
  return unwrap(data)
}

// --- Daily Waste Logs --------------------------------------------------------

export async function fetchDailyLogs(
  habitationId: string,
  params: { from_date?: string; to_date?: string; page?: number; page_size?: number } = {},
): Promise<DailyLogPage> {
  const { data } = await apiClient.get<ApiEnvelope<DailyLogPage>>(
    `/api/v1/habitations/${habitationId}/daily-logs`,
    { params },
  )
  return unwrap(data)
}

export async function upsertDailyLog(
  habitationId: string,
  payload: DailyLogIn,
): Promise<DailyLog & { created: boolean }> {
  const { data } = await apiClient.post<ApiEnvelope<DailyLog & { created: boolean }>>(
    `/api/v1/habitations/${habitationId}/daily-logs`,
    payload,
  )
  return unwrap(data)
}

export async function bulkImportDailyLogsCsv(habitationId: string, file: File): Promise<BulkImportResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<ApiEnvelope<BulkImportResult>>(
    `/api/v1/habitations/${habitationId}/daily-logs/bulk-csv`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return unwrap(data)
}

/** The export endpoint returns a raw file (CSV/XLSX), not the usual
 * {success, data} envelope, so this bypasses `unwrap` and reads the
 * filename straight off the Content-Disposition header the backend sets. */
export async function exportDailyLogs(
  habitationId: string,
  params: DailyLogExportParams,
): Promise<{ blob: Blob; filename: string }> {
  const response = await apiClient.get(`/api/v1/habitations/${habitationId}/daily-logs/export`, {
    params,
    responseType: 'blob',
  })
  const disposition = (response.headers['content-disposition'] as string | undefined) ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const fallbackExt = params.format === 'xlsx' ? 'xlsx' : 'csv'
  const filename = match?.[1] ?? `daily_logs.${fallbackExt}`
  return { blob: response.data as Blob, filename }
}

// --- Recalibration -----------------------------------------------------------

export async function fetchRecalibrationReport(habitationId: string): Promise<RecalibrationReport> {
  const { data } = await apiClient.get<ApiEnvelope<RecalibrationReport>>(
    `/api/v1/habitations/${habitationId}/recalibration-report`,
  )
  return unwrap(data)
}
