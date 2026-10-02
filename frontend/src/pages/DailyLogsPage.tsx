import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, Lock, NotebookPen } from 'lucide-react'
import { useState } from 'react'
import { exportDailyLogsCsv, fetchDailyLogs, upsertDailyLog } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { useCurrentUser } from '../hooks/useCurrentUser'
import type { AnomalyFlag, DailyLogIn } from '../types/api'

const ANOMALY_FLAGS: AnomalyFlag[] = ['NORMAL', 'MONSOON_FLOOD', 'FESTIVAL_SURGE', 'WORKER_STRIKE', 'BREAKDOWN']

const EMPTY_FORM: DailyLogIn = {
  log_date: new Date().toISOString().slice(0, 10),
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

function LogEntryForm({ habitationId }: { habitationId: string }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<DailyLogIn>(EMPTY_FORM)

  const mutation = useMutation({
    mutationFn: (payload: DailyLogIn) => upsertDailyLog(habitationId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-logs', habitationId] })
      setForm((prev) => ({ ...EMPTY_FORM, log_date: prev.log_date }))
    },
  })

  function field<K extends keyof DailyLogIn>(key: K, parser: (raw: string) => DailyLogIn[K]) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: parser(e.target.value) }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    // total_collected_tonnes isn't its own input — a single manual entry
    // states its wet/dry/hazardous splits and the total is their sum,
    // matching how the bulk-CSV importer derives it (app/daily_logs/service.py).
    const total = form.organic_tonnes + form.dry_recyclable_tonnes + (form.hazardous_tonnes ?? 0)
    mutation.mutate({ ...form, total_collected_tonnes: total })
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Record Today's Operations</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Date of entry</span>
          <input
            type="date"
            required
            value={form.log_date}
            onChange={field('log_date', (v) => v)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Wet / organic waste (t)</span>
          <input
            type="number"
            step="0.01"
            min={0}
            required
            value={form.organic_tonnes}
            onChange={field('organic_tonnes', Number)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Dry / recyclable waste (t)</span>
          <input
            type="number"
            step="0.01"
            min={0}
            required
            value={form.dry_recyclable_tonnes}
            onChange={field('dry_recyclable_tonnes', Number)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Hazardous waste (t, optional)</span>
          <input
            type="number"
            step="0.01"
            min={0}
            value={form.hazardous_tonnes ?? ''}
            onChange={field('hazardous_tonnes', (v) => (v === '' ? null : Number(v)))}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Vehicles deployed</span>
          <input
            type="number"
            step="1"
            min={0}
            required
            value={form.vehicles_deployed}
            onChange={field('vehicles_deployed', (v) => parseInt(v || '0', 10))}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Vehicle trips completed</span>
          <input
            type="number"
            step="1"
            min={0}
            required
            value={form.trips_completed}
            onChange={field('trips_completed', (v) => parseInt(v || '0', 10))}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Fuel / diesel consumed (L)</span>
          <input
            type="number"
            step="0.1"
            min={0}
            value={form.diesel_consumed_litres ?? ''}
            onChange={field('diesel_consumed_litres', (v) => (v === '' ? null : Number(v)))}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Collection coverage observed (%)</span>
          <input
            type="number"
            step="0.1"
            min={0}
            max={100}
            value={form.collection_coverage_pct_observed ?? ''}
            onChange={field('collection_coverage_pct_observed', (v) => (v === '' ? null : Number(v)))}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Anomaly flag</span>
          <select
            value={form.anomaly_flag}
            onChange={field('anomaly_flag', (v) => v as AnomalyFlag)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            {ANOMALY_FLAGS.map((flag) => (
              <option key={flag} value={flag}>
                {flag}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium text-slate-600">Operational notes</span>
        <textarea
          rows={2}
          value={form.notes ?? ''}
          onChange={field('notes', (v) => v)}
          placeholder="Anything a planner reviewing this later should know — breakdowns, strikes, flooding, festival surges…"
          className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </label>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <NotebookPen className="h-4 w-4" />}
          Save Log Entry
        </button>
        {mutation.isSuccess && <span className="text-xs text-emerald-600">Saved.</span>}
        {mutation.isError && <span className="text-xs text-red-600">{(mutation.error as Error).message}</span>}
      </div>
    </form>
  )
}

function ExportButton({ habitationId, fromDate, toDate }: { habitationId: string; fromDate: string; toDate: string }) {
  const [isExporting, setIsExporting] = useState(false)

  async function handleExport() {
    setIsExporting(true)
    try {
      const { csv, filename } = await exportDailyLogsCsv(habitationId, {
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
      })
      const blob = new Blob([csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <button
      type="button"
      onClick={handleExport}
      disabled={isExporting}
      className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
    >
      {isExporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
      Export Operational Logs
    </button>
  )
}

export default function DailyLogsPage() {
  const { currentHabitationId } = useAppContext()
  const { isAdmin, isPlanner, isResearcher, isViewer } = useCurrentUser()
  const canLog = isAdmin || isPlanner || isResearcher

  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')

  const logsQuery = useQuery({
    queryKey: ['daily-logs', currentHabitationId, fromDate, toDate],
    queryFn: () =>
      fetchDailyLogs(currentHabitationId, { from_date: fromDate || undefined, to_date: toDate || undefined, page_size: 100 }),
    enabled: !!currentHabitationId,
  })

  if (isViewer) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-slate-200 bg-white p-10 text-center">
        <Lock className="h-5 w-5 text-slate-400" />
        <p className="text-sm font-medium text-slate-600">🔒 Researcher Access Required</p>
        <p className="max-w-sm text-xs text-slate-400">
          Daily operational logs are restricted to Researcher, Planner and Admin accounts. Apply for Researcher
          access from the top navbar to view them.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Daily Operational Logs</h2>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            From
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            To
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs"
            />
          </label>
          {isAdmin && <ExportButton habitationId={currentHabitationId} fromDate={fromDate} toDate={toDate} />}
        </div>
      </div>

      {canLog && <LogEntryForm habitationId={currentHabitationId} />}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <h3 className="border-b border-slate-100 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Field Entries {logsQuery.data ? `(${logsQuery.data.total})` : ''}
        </h3>
        {logsQuery.isLoading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : (logsQuery.data?.items.length ?? 0) === 0 ? (
          <p className="p-8 text-center text-sm text-slate-400">No log entries in this date range yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 text-left text-slate-500">
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 text-right font-medium">Wet (t)</th>
                <th className="px-4 py-2 text-right font-medium">Dry (t)</th>
                <th className="px-4 py-2 text-right font-medium">Trips</th>
                <th className="px-4 py-2 text-right font-medium">Diesel (L)</th>
                <th className="px-4 py-2 font-medium">Anomaly</th>
                <th className="px-4 py-2 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {logsQuery.data?.items.map((log) => (
                <tr key={log.id} className="border-t border-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-700">{log.log_date}</td>
                  <td className="px-4 py-2 text-right">{log.organic_tonnes.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right">{log.dry_recyclable_tonnes.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right">{log.trips_completed}</td>
                  <td className="px-4 py-2 text-right">{log.diesel_consumed_litres?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-2">
                    {log.anomaly_flag === 'NORMAL' ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">{log.anomaly_flag}</span>
                    )}
                  </td>
                  <td className="max-w-xs truncate px-4 py-2 text-slate-500" title={log.notes ?? ''}>
                    {log.notes || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
