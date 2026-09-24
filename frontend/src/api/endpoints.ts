import { apiClient, unwrap } from './client'
import type {
  ApiEnvelope,
  ChatMessage,
  ChatSession,
  Habitation,
  MapOverlay,
  ReportDownload,
  ReportResponse,
  SimulationCreatePayload,
  SimulationResultsResponse,
  SimulationRun,
} from '../types/api'

export async function fetchHabitations(): Promise<Habitation[]> {
  const { data } = await apiClient.get<ApiEnvelope<Habitation[]>>('/api/v1/habitations')
  return unwrap(data)
}

export async function createSimulation(
  habitationId: string,
  payload: SimulationCreatePayload,
): Promise<SimulationRun> {
  const { data } = await apiClient.post<ApiEnvelope<SimulationRun>>(
    `/api/v1/habitations/${habitationId}/simulations`,
    payload,
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

export async function autoPopulateHabitation(habitationId: string): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post<ApiEnvelope<Record<string, unknown>>>(
    `/api/v1/habitations/${habitationId}/auto-populate`,
    {},
  )
  return unwrap(data)
}

export async function createReport(runId: string, format: 'PDF' | 'XLSX' | 'CSV' = 'PDF'): Promise<ReportResponse> {
  // CRITICAL: never send comparison_id here — the backend's own schema
  // requires exactly one of run_id/comparison_id, and omitting the key
  // entirely (not even `null`) is the unambiguous way to satisfy that.
  const { data } = await apiClient.post<ApiEnvelope<ReportResponse>>('/api/v1/reports', {
    run_id: runId,
    format,
  })
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

export async function fetchMapOverlay(habitationId: string): Promise<MapOverlay> {
  const { data } = await apiClient.get<ApiEnvelope<MapOverlay>>(`/api/v1/habitations/${habitationId}/map`, {
    params: { limit: 50_000 },
  })
  return unwrap(data)
}

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
