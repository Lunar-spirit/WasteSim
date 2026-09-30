import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Download, Loader2, Save, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { bulkImportDailyLogsCsv, exportDailyLogs, fetchDailyLogs, upsertDailyLog } from '../api/endpoints'
import CalibrationDiscrepancyCard from '../components/analytics/CalibrationDiscrepancyCard'
import { useAppContext } from '../context/AppContext'
import { useCurrentUser } from '../hooks/useCurrentUser'
import { formatTonnes } from '../lib/format'
import type { AnomalyFlag, BulkImportResult, DailyLogExportParams, DailyLogIn } from '../types/api'

const ANOMALY_OPTIONS: { value: AnomalyFlag; label: string }[] = [
  { value: 'NORMAL', label: 'Normal' },
  { value: 'MONSOON_FLOOD', label: 'Monsoon / flood' },
  { value: 'FESTIVAL_SURGE', label: 'Festival surge' },
  { value: 'WORKER_STRIKE', label: 'Worker strike' },
  { value: 'BREAKDOWN', label: 'Equipment breakdown' },
]

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

const EMPTY_FORM: DailyLogIn = {
  log_date: todayIso(),
  total_collected_tonnes: 0,
  organic_tonnes: 0,
  dry_recyclable_tonnes: 0,
  hazardous_tonnes: null,
  vehicles_deployed: 0,
  trips_completed: 0,
  diesel_consumed_litres: null,
  collection_coverage_pct_observed: null,
  anomaly_flag: 'NORMAL',
  notes: '',
}

function numberField(value: string): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function optionalNumberField(value: string): number | null {
  return value.trim() === '' ? null : Number(value)
}

const MONTH_OPTIONS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

/** Downloads a blob response the way a real `<a download>` click would —
 * needed because the export request has to carry the bearer auth header,
 * so it can't just be a plain anchor href straight at the API URL. */
function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function ExportLogsModal({ habitationId, onClose }: { habitationId: string; onClose: () => void }) {
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState(currentYear)
  const [month, setMonth] = useState<number | 'ALL'>('ALL')

  const exportMutation = useMutation({
    mutationFn: () => {
      const params: DailyLogExportParams =
        month === 'ALL'
          ? { period_type: 'yearly', year, format: 'csv' }
          : { period_type: 'monthly', year, month, format: 'csv' }
      return exportDailyLogs(habitationId, params)
    },
    onSuccess: ({ blob, filename }) => {
      triggerBrowserDownload(blob, filename)
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl">
        <h3 className="text-sm font-semibold text-slate-800">Download logs</h3>
        <p className="mt-1 text-xs text-slate-500">Export the operational log for a year or a single month as CSV.</p>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Year</span>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(numberField(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Month</span>
            <select
              value={month}
              onChange={(e) => setMonth(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <option value="ALL">All year</option>
              {MONTH_OPTIONS.map((name, idx) => (
                <option key={name} value={idx + 1}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {exportMutation.isError && (
          <p className="mt-3 text-xs text-red-600">{(exportMutation.error as Error).message}</p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
          >
            {exportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Download CSV
          </button>
        </div>
      </div>
    </div>
  )
}

export default function DailyWasteTrackerPage() {
  const { currentHabitationId } = useAppContext()
  const { isReadOnly, isAdmin } = useCurrentUser()
  const queryClient = useQueryClient()
  const [showExportModal, setShowExportModal] = useState(false)
  const [form, setForm] = useState<DailyLogIn>(EMPTY_FORM)
  const [bulkResult, setBulkResult] = useState<BulkImportResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const logsQuery = useQuery({
    queryKey: ['daily-logs', currentHabitationId],
    queryFn: () => fetchDailyLogs(currentHabitationId, { page: 1, page_size: 20 }),
  })

  const saveLogMutation = useMutation({
    mutationFn: () => upsertDailyLog(currentHabitationId, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-logs', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['recalibration-report', currentHabitationId] })
      setForm({ ...EMPTY_FORM, log_date: todayIso() })
    },
  })

  const bulkImportMutation = useMutation({
    mutationFn: (file: File) => bulkImportDailyLogsCsv(currentHabitationId, file),
    onSuccess: (result) => {
      setBulkResult(result)
      queryClient.invalidateQueries({ queryKey: ['daily-logs', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['recalibration-report', currentHabitationId] })
    },
  })

  function handleFile(file: File | undefined) {
    if (!file) return
    bulkImportMutation.mutate(file)
  }

  const logs = logsQuery.data?.items ?? []

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Daily Waste Tracker</h2>
          <p className="mt-1 text-sm text-slate-500">
            Field-recorded collection data — what the crew actually collected, separate from the declared
            parameters the simulation starts from.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setShowExportModal(true)}
            className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <Download className="h-4 w-4" />
            Download Logs
          </button>
        )}
      </div>

      {showExportModal && (
        <ExportLogsModal habitationId={currentHabitationId} onClose={() => setShowExportModal(false)} />
      )}

      <CalibrationDiscrepancyCard habitationId={currentHabitationId} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-1">
          <h3 className="text-sm font-semibold text-slate-700">Log a day</h3>
          {isReadOnly ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Researchers have read-only access — logging is limited to an assigned Planner or Admin.
            </p>
          ) : (
            <>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Date</span>
                <input
                  type="date"
                  value={form.log_date}
                  onChange={(e) => setForm({ ...form, log_date: e.target.value })}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Total (t)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.total_collected_tonnes}
                    onChange={(e) => setForm({ ...form, total_collected_tonnes: numberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Organic (t)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.organic_tonnes}
                    onChange={(e) => setForm({ ...form, organic_tonnes: numberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Dry recyclable (t)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.dry_recyclable_tonnes}
                    onChange={(e) => setForm({ ...form, dry_recyclable_tonnes: numberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Hazardous (t)</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.hazardous_tonnes ?? ''}
                    onChange={(e) => setForm({ ...form, hazardous_tonnes: optionalNumberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Vehicles deployed</span>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    value={form.vehicles_deployed}
                    onChange={(e) => setForm({ ...form, vehicles_deployed: numberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Trips completed</span>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    value={form.trips_completed}
                    onChange={(e) => setForm({ ...form, trips_completed: numberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Diesel (L)</span>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={form.diesel_consumed_litres ?? ''}
                    onChange={(e) => setForm({ ...form, diesel_consumed_litres: optionalNumberField(e.target.value) })}
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Coverage observed (%)</span>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="100"
                    value={form.collection_coverage_pct_observed ?? ''}
                    onChange={(e) =>
                      setForm({ ...form, collection_coverage_pct_observed: optionalNumberField(e.target.value) })
                    }
                    className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </label>
              </div>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Anomaly</span>
                <select
                  value={form.anomaly_flag}
                  onChange={(e) => setForm({ ...form, anomaly_flag: e.target.value as AnomalyFlag })}
                  className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  {ANOMALY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Notes</span>
                <textarea
                  value={form.notes ?? ''}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  rows={2}
                  className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
              </label>
              <button
                type="button"
                onClick={() => saveLogMutation.mutate()}
                disabled={saveLogMutation.isPending}
                className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
              >
                {saveLogMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save day
              </button>
              {saveLogMutation.isError && (
                <p className="text-xs text-red-600">{(saveLogMutation.error as Error).message}</p>
              )}
              {saveLogMutation.isSuccess && (
                <p className="text-xs text-emerald-600">
                  {saveLogMutation.data.created ? 'Logged.' : 'Updated existing entry for that date.'}
                </p>
              )}

              <div className="mt-3 border-t border-slate-100 pt-3">
                <h3 className="mb-2 text-sm font-semibold text-slate-700">Or drop a CSV</h3>
                <div
                  onDragOver={(e) => {
                    e.preventDefault()
                    setIsDragging(true)
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setIsDragging(false)
                    handleFile(e.dataTransfer.files[0])
                  }}
                  onClick={() => fileInputRef.current?.click()}
                  className={`flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center text-xs transition ${
                    isDragging ? 'border-emerald-400 bg-emerald-50 text-emerald-700' : 'border-slate-300 text-slate-400 hover:bg-slate-50'
                  }`}
                >
                  {bulkImportMutation.isPending ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Upload className="h-5 w-5" />
                  )}
                  <span>Drop a CSV, or click to choose one</span>
                  <span className="text-[10px] text-slate-400">
                    Columns: log_date, organic_tonnes, dry_recyclable_tonnes, vehicles_deployed, trips_completed
                    required; total_collected_tonnes is derived if omitted.
                  </span>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => handleFile(e.target.files?.[0])}
                />
                {bulkResult && (
                  <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                    <p className="font-medium text-slate-700">
                      {bulkResult.created_count} created · {bulkResult.updated_count} updated ·{' '}
                      {bulkResult.error_count} error(s) of {bulkResult.total_rows} row(s)
                    </p>
                    {bulkResult.errors.length > 0 && (
                      <ul className="mt-1.5 flex flex-col gap-0.5 text-red-600">
                        {bulkResult.errors.slice(0, 8).map((e) => (
                          <li key={e.row_number}>
                            Row {e.row_number}: {e.message}
                          </li>
                        ))}
                        {bulkResult.errors.length > 8 && <li>…and {bulkResult.errors.length - 8} more</li>}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white shadow-sm lg:col-span-2">
          <h3 className="border-b border-slate-100 px-5 py-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Recent logs
          </h3>
          {logsQuery.isLoading && (
            <div className="flex justify-center p-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          )}
          {!logsQuery.isLoading && logs.length === 0 && (
            <p className="p-5 text-sm text-slate-400">No daily logs recorded yet for this habitation.</p>
          )}
          {logs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-5 py-2">Date</th>
                    <th className="px-3 py-2 text-right">Total</th>
                    <th className="px-3 py-2 text-right">Organic</th>
                    <th className="px-3 py-2 text-right">Dry recyc.</th>
                    <th className="px-3 py-2 text-right">Vehicles</th>
                    <th className="px-3 py-2">Anomaly</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id} className="border-b border-slate-50 last:border-0">
                      <td className="px-5 py-2 text-slate-700">{log.log_date}</td>
                      <td className="px-3 py-2 text-right text-slate-700">{formatTonnes(log.total_collected_tonnes)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{formatTonnes(log.organic_tonnes)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{formatTonnes(log.dry_recyclable_tonnes)}</td>
                      <td className="px-3 py-2 text-right text-slate-500">{log.vehicles_deployed}</td>
                      <td className="px-3 py-2">
                        {log.anomaly_flag !== 'NORMAL' && (
                          <span className="flex items-center gap-1 text-xs text-amber-700">
                            <AlertTriangle className="h-3 w-3" />
                            {log.anomaly_flag.replace('_', ' ')}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
