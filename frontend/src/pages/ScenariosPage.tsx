import { useMutation, useQuery } from '@tanstack/react-query'
import { CloudRain, Loader2, Play, Waves, Zap } from 'lucide-react'
import { useState } from 'react'
import {
  createScenario,
  fetchEventCatalogue,
  fetchMapOverlay,
  listScenarioEvents,
  listSimulations,
  previewEventImpact,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import type { EventType } from '../types/api'

const EVENT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  FLOOD: Waves,
  HEAVY_MONSOON: CloudRain,
  LANDSLIDE: Zap,
}

function severityFromIntensity(pct: number): 'MILD' | 'MODERATE' | 'SEVERE' {
  if (pct < 34) return 'MILD'
  if (pct < 67) return 'MODERATE'
  return 'SEVERE'
}

export default function ScenariosPage() {
  const { currentHabitationId, activeRunId, setActiveRunId } = useAppContext()

  const runsQuery = useQuery({
    queryKey: ['simulations', currentHabitationId],
    queryFn: () => listSimulations(currentHabitationId),
  })
  const baseRuns = (runsQuery.data ?? []).filter((r) => r.run_type === 'BASE' && r.status === 'COMPLETED')
  const [baseRunId, setBaseRunId] = useState<string | null>(activeRunId)
  const effectiveBaseRunId = baseRunId ?? activeRunId

  const catalogueQuery = useQuery({ queryKey: ['event-catalogue'], queryFn: fetchEventCatalogue })
  const overlayQuery = useQuery({
    queryKey: ['map-overlay', currentHabitationId],
    queryFn: () => fetchMapOverlay(currentHabitationId),
  })

  const eventsQuery = useQuery({
    queryKey: ['scenario-events', effectiveBaseRunId],
    queryFn: () => listScenarioEvents(effectiveBaseRunId as string),
    enabled: !!effectiveBaseRunId,
  })

  const [selectedEventType, setSelectedEventType] = useState<EventType>('FLOOD')
  const [intensity, setIntensity] = useState(50)
  const [durationWeeks, setDurationWeeks] = useState(2)
  const [startMonth, setStartMonth] = useState(6)
  const [useBoundaryArea, setUseBoundaryArea] = useState(true)

  const severity = severityFromIntensity(intensity)
  const durationMonths = Math.max(1, Math.round(durationWeeks / 4.345))

  // The backend wants the raw GeoJSON (Multi)Polygon geometry here, not a
  // Feature wrapper (see EventIn.affected_area's own comment in
  // app/scenario/schemas.py) — overlay.boundary from /map is already that
  // geometry shape.
  const boundaryGeometry = overlayQuery.data?.boundary as Record<string, unknown> | null | undefined

  const previewMutation = useMutation({
    mutationFn: () => {
      if (!boundaryGeometry) throw new Error('No habitation boundary geometry available to preview against')
      return previewEventImpact(effectiveBaseRunId as string, selectedEventType, boundaryGeometry)
    },
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createScenario(
        effectiveBaseRunId as string,
        [
          {
            event_type: selectedEventType,
            start_month: startMonth,
            duration_months: durationMonths,
            recovery_months: 1,
            severity,
            affected_area: useBoundaryArea && boundaryGeometry ? boundaryGeometry : null,
          },
        ],
        `${selectedEventType} scenario (${severity})`,
      ),
    onSuccess: (run) => setActiveRunId(run.id),
  })

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Stress Test &amp; Scenario Studio</h2>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">Base run</span>
          <select
            value={effectiveBaseRunId ?? ''}
            onChange={(e) => setBaseRunId(e.target.value)}
            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
          >
            {!effectiveBaseRunId && <option value="">Select a completed BASE run…</option>}
            {baseRuns.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label ?? r.id.slice(0, 8)} ({new Date(r.created_at).toLocaleDateString()})
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Event Catalog Carousel */}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {(catalogueQuery.data ?? []).map((item) => {
          const Icon = EVENT_ICONS[item.event_type] ?? Zap
          const isSelected = item.event_type === selectedEventType
          return (
            <button
              key={item.event_type}
              type="button"
              onClick={() => setSelectedEventType(item.event_type as EventType)}
              className={`flex w-56 shrink-0 flex-col gap-2 rounded-xl border p-4 text-left transition ${
                isSelected ? 'border-emerald-400 bg-emerald-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'
              }`}
            >
              <Icon className={`h-5 w-5 ${isSelected ? 'text-emerald-600' : 'text-slate-400'}`} />
              <p className="text-sm font-semibold text-slate-800">{item.event_type.replaceAll('_', ' ')}</p>
              <p className="text-xs text-slate-500">{item.effect}</p>
              <p className="text-[10px] uppercase tracking-wide text-slate-400">{item.magnitude_source}</p>
            </button>
          )
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Scenario Builder */}
        <div className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Scenario Builder</h3>

          <label className="flex flex-col gap-1 text-sm">
            <span className="flex justify-between font-medium text-slate-700">
              Severity Intensity <span className="text-emerald-600">{severity} ({intensity}%)</span>
            </span>
            <input type="range" min="0" max="100" value={intensity} onChange={(e) => setIntensity(Number(e.target.value))} className="accent-emerald-600" />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Disruption Duration (weeks)</span>
            <input
              type="number"
              min="1"
              value={durationWeeks}
              onChange={(e) => setDurationWeeks(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Start month (into the 10-year horizon)</span>
            <input
              type="number"
              min="1"
              max="120"
              value={startMonth}
              onChange={(e) => setStartMonth(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={useBoundaryArea} onChange={(e) => setUseBoundaryArea(e.target.checked)} className="h-4 w-4 accent-emerald-600" />
            <span className="text-slate-700">Apply across the full habitation boundary</span>
          </label>
          <p className="text-[11px] text-slate-400">
            (A precise road-segment "mark as severed" map picker isn't wired up — the engine already derives
            spatial impact from whichever GeoJSON area you give it, and the full boundary is a real, honest
            choice when you haven't drawn a smaller one.)
          </p>

          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => previewMutation.mutate()}
              disabled={!effectiveBaseRunId || !boundaryGeometry || previewMutation.isPending}
              className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-sky-300 bg-sky-50 px-4 py-2.5 text-sm font-medium text-sky-700 transition hover:bg-sky-100 disabled:opacity-60"
            >
              {previewMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Preview Impact
            </button>
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={!effectiveBaseRunId || createMutation.isPending}
              className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
            >
              {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run Full Scenario
            </button>
          </div>
          {createMutation.isSuccess && (
            <p className="text-xs text-emerald-600">
              Scenario run started ({createMutation.data.id.slice(0, 8)}…) — now the active run. See it on the Simulation tab.
            </p>
          )}
          {createMutation.isError && <p className="text-xs text-red-600">{(createMutation.error as Error).message}</p>}
        </div>

        {/* Impact Preview */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Impact Preview</h3>
          {!previewMutation.data && !previewMutation.isPending && (
            <p className="text-sm text-slate-400">Run a preview to see instant diff metrics without a full 10-year simulation.</p>
          )}
          {previewMutation.isPending && <Loader2 className="h-5 w-5 animate-spin text-slate-400" />}
          {previewMutation.data && !previewMutation.data.derived && (
            <p className="text-sm text-amber-600">{previewMutation.data.message}</p>
          )}
          {previewMutation.data?.derived && previewMutation.data.derived_impacts && (
            <dl className="grid grid-cols-2 gap-3">
              {Object.entries(previewMutation.data.derived_impacts).map(([key, value]) => (
                <div key={key} className="rounded-lg bg-slate-50 p-3">
                  <dt className="text-[11px] uppercase tracking-wide text-slate-400">{key.replaceAll('_', ' ')}</dt>
                  <dd className="text-sm font-semibold text-slate-800">{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          <h4 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Events already run against this base
          </h4>
          {eventsQuery.data && eventsQuery.data.length === 0 && <p className="text-sm text-slate-400">None yet.</p>}
          <ul className="space-y-1.5 text-sm">
            {(eventsQuery.data ?? []).map((ev) => (
              <li key={ev.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-1.5">
                <span>
                  {ev.event_type.replaceAll('_', ' ')} · {ev.severity}
                </span>
                <span className="text-xs text-slate-400">month {ev.start_month}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
