import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, FileText, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { createReport, fetchReport, fetchReportDownloadUrl, listSimulations } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { useHistory } from '../lib/history'
import type { ReportFormat, ReportStatus } from '../types/api'

const POLL_STATUSES: ReportStatus[] = ['QUEUED', 'GENERATING']

export default function ReportsPage() {
  const { currentHabitationId } = useAppContext()

  const runsQuery = useQuery({ queryKey: ['simulations', currentHabitationId], queryFn: () => listSimulations(currentHabitationId) })
  const completedRuns = (runsQuery.data ?? []).filter((r) => r.status === 'COMPLETED')
  const comparisonHistory = useHistory('comparison', currentHabitationId)

  const [scope, setScope] = useState<'run' | 'comparison'>('run')
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [selectedComparisonId, setSelectedComparisonId] = useState<string>('')
  const [format, setFormat] = useState<ReportFormat>('PDF')
  const [reportId, setReportId] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: () =>
      createReport(scope === 'run' ? { runId: selectedRunId } : { comparisonId: selectedComparisonId }, format),
    onSuccess: (report) => setReportId(report.id),
  })

  const reportQuery = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => fetchReport(reportId as string),
    enabled: !!reportId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && POLL_STATUSES.includes(status) ? 2000 : false
    },
  })

  const downloadQuery = useQuery({
    queryKey: ['report-download', reportId],
    queryFn: () => fetchReportDownloadUrl(reportId as string),
    enabled: reportQuery.data?.status === 'READY',
  })

  const canGenerate = scope === 'run' ? !!selectedRunId : !!selectedComparisonId

  return (
    <div className="flex flex-col gap-6 p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Official DPR &amp; Report Center</h2>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Report Configuration</h3>

        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={scope === 'run'} onChange={() => setScope('run')} className="accent-emerald-600" />
            Individual Simulation DPR
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={scope === 'comparison'} onChange={() => setScope('comparison')} className="accent-emerald-600" />
            Multi-Run Comparison Matrix
          </label>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {scope === 'run' ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Run</span>
              <select value={selectedRunId} onChange={(e) => setSelectedRunId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">Select a completed run…</option>
                {completedRuns.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label ?? r.id.slice(0, 8)} ({r.run_type})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Comparison</span>
              <select value={selectedComparisonId} onChange={(e) => setSelectedComparisonId(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">Select a comparison…</option>
                {comparisonHistory.map((id) => (
                  <option key={id} value={id}>
                    {id.slice(0, 8)}…
                  </option>
                ))}
              </select>
              {comparisonHistory.length === 0 && (
                <p className="text-[11px] text-slate-400">No comparisons created yet — build one on the Comparison page first.</p>
              )}
            </label>
          )}

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Format</span>
            <select value={format} onChange={(e) => setFormat(e.target.value as ReportFormat)} className="rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="PDF">PDF (Government DPR format)</option>
              <option value="XLSX">Excel (detailed budget data)</option>
              <option value="CSV">CSV</option>
            </select>
          </label>
        </div>

        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!canGenerate || createMutation.isPending}
          className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
          Generate Report
        </button>
        {createMutation.isError && <p className="mt-2 text-xs text-red-600">{(createMutation.error as Error).message}</p>}
      </div>

      {reportQuery.data && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Generation Lifecycle</h3>
          <div className="flex items-center gap-2 text-sm">
            {(['QUEUED', 'GENERATING', 'READY'] as const).map((stage, idx) => {
              const stages = ['QUEUED', 'GENERATING', 'READY']
              const currentIdx = stages.indexOf(reportQuery.data.status)
              const done = idx <= currentIdx && reportQuery.data.status !== 'FAILED'
              return (
                <div key={stage} className="flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${done ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
                    {stage}
                  </span>
                  {idx < 2 && <span className="text-slate-300">→</span>}
                </div>
              )
            })}
            {reportQuery.data.status !== 'READY' && reportQuery.data.status !== 'FAILED' && (
              <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
            )}
          </div>
          {reportQuery.data.status === 'FAILED' && (
            <p className="mt-2 text-xs text-red-600">Generation failed: {reportQuery.data.error_detail}</p>
          )}

          {reportQuery.data.status === 'READY' && downloadQuery.data && (
            <div className="mt-4 flex flex-col gap-3">
              {format === 'PDF' && (
                <iframe title="DPR preview" src={downloadQuery.data.url} className="h-[600px] w-full rounded-lg border border-slate-200" />
              )}
              <a
                href={downloadQuery.data.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex w-fit items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
              >
                <Download className="h-4 w-4" />
                Download Signed DPR (.{format.toLowerCase()})
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
