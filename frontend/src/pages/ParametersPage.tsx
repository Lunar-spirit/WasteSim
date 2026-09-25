import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FilePlus, Loader2, Lock, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  commitParameterSet,
  createParameterSet,
  fetchHabitation,
  fetchParameterDefinitions,
  fetchParameterSet,
  upsertParameterCategory,
  upsertWasteBaseline,
  validateParameterSet,
} from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { clearDraftPsid, getDraftPsid, setDraftPsid as persistDraftPsid } from '../lib/history'
import type { ParameterDefinition, ValidationReport } from '../types/api'

const CANONICAL_FRACTIONS = ['organic', 'plastic', 'paper', 'metal', 'glass', 'textile', 'inert', 'ewaste', 'other']

const STRING_ENUMS: Record<string, string[]> = {
  'terrain.soil_type': ['SANDY', 'CLAY', 'LOAMY', 'ROCKY', 'SILTY'],
  'terrain.flood_risk_level': ['LOW', 'MODERATE', 'HIGH'],
  'terrain.landslide_risk_level': ['LOW', 'MODERATE', 'HIGH'],
  'terrain.terrain_type': ['COASTAL_PLAINS', 'HILLY', 'PLAINS'],
}

const CATEGORY_LABELS: Record<string, string> = {
  demography: 'Demographics',
  community_infrastructure: 'Community Infrastructure (Fleet & Facilities)',
  economic_conditions: 'Economics & Labor',
  cultural_context: 'Policy & Cultural Context',
  natural_resources: 'Natural Resources',
  terrain: 'Terrain',
  industrial_activities: 'Industrial Activities',
}

const LEFT_CATEGORIES = ['demography']
const RIGHT_CATEGORIES = ['community_infrastructure', 'economic_conditions']
const MORE_CATEGORIES = ['cultural_context', 'natural_resources', 'terrain', 'industrial_activities']

type CategoryEdits = Record<string, Record<string, unknown>>

function FieldInput({
  def,
  value,
  onChange,
}: {
  def: ParameterDefinition
  value: unknown
  onChange: (v: unknown) => void
}) {
  const path = `${def.category}.${def.param_key}`
  if (def.data_type === 'BOOLEAN') {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-emerald-600"
        />
        <span className="font-medium text-slate-700">{def.display_label}</span>
      </label>
    )
  }
  if (def.data_type === 'STRING' && STRING_ENUMS[path]) {
    return (
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-slate-700">{def.display_label}</span>
        <select
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          <option value="">—</option>
          {STRING_ENUMS[path].map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
    )
  }
  if (def.data_type === 'STRING') {
    return (
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-slate-700">{def.display_label}</span>
        <input
          type="text"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
      </label>
    )
  }
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-700">
        {def.display_label} {def.unit && <span className="text-slate-400">({def.unit})</span>}
      </span>
      <input
        type="number"
        step={def.data_type === 'INTEGER' ? 1 : 'any'}
        min={def.min_value ?? undefined}
        max={def.max_value ?? undefined}
        value={value === undefined || value === null ? '' : (value as number)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
      />
    </label>
  )
}

function CategoryCard({
  category,
  defs,
  edits,
  onFieldChange,
}: {
  category: string
  defs: ParameterDefinition[]
  edits: CategoryEdits
  onFieldChange: (category: string, key: string, value: unknown) => void
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {CATEGORY_LABELS[category] ?? category}
      </h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {defs.map((def) => (
          <FieldInput
            key={def.param_key}
            def={def}
            value={edits[category]?.[def.param_key]}
            onChange={(v) => onFieldChange(category, def.param_key, v)}
          />
        ))}
      </div>
    </div>
  )
}

export default function ParametersPage() {
  const { currentHabitationId } = useAppContext()
  const queryClient = useQueryClient()

  const [draftPsid, setDraftPsidState] = useState<string | null>(() => getDraftPsid(currentHabitationId))
  const [edits, setEdits] = useState<CategoryEdits>({})
  const [compositionEdits, setCompositionEdits] = useState<Record<string, number>>({})
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)

  useEffect(() => {
    setDraftPsidState(getDraftPsid(currentHabitationId))
    setEdits({})
    setCompositionEdits({})
    setValidationReport(null)
  }, [currentHabitationId])

  // Auto-Populate on the GIS Studio page creates/writes into a draft behind
  // the scenes (via the backend's own _resolve_target_parameter_set) and
  // records its id under the same shared key — pick it up live if it
  // changes while this page happens to be mounted, not just on next visit.
  useEffect(() => {
    function handler() {
      setDraftPsidState(getDraftPsid(currentHabitationId))
    }
    window.addEventListener('swms:draft-psid', handler)
    return () => window.removeEventListener('swms:draft-psid', handler)
  }, [currentHabitationId])

  const habitationQuery = useQuery({
    queryKey: ['habitation', currentHabitationId],
    queryFn: () => fetchHabitation(currentHabitationId),
  })

  const definitionsQuery = useQuery({
    queryKey: ['parameter-definitions'],
    queryFn: fetchParameterDefinitions,
    staleTime: Infinity,
  })

  const draftQuery = useQuery({
    queryKey: ['parameter-set', draftPsid],
    queryFn: () => fetchParameterSet(draftPsid as string),
    enabled: !!draftPsid,
  })

  // Seed local edit state from the fetched draft's real stored values, once.
  useEffect(() => {
    if (!draftQuery.data) return
    setEdits(draftQuery.data.categories ?? {})
    const composition = (draftQuery.data.waste_baseline?.composition as Record<string, number> | undefined) ?? {}
    setCompositionEdits(composition)
    setEdits((prev) => ({
      ...prev,
      waste_baseline: {
        per_capita_generation_kg_day: draftQuery.data.waste_baseline?.per_capita_generation_kg_day,
        total_generation_tpd: draftQuery.data.waste_baseline?.total_generation_tpd,
      },
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftQuery.data?.id])

  const createDraftMutation = useMutation({
    mutationFn: async () => {
      const habitation = habitationQuery.data
      let cloneFromVersion: number | undefined
      if (habitation?.active_parameter_set_id) {
        const active = await fetchParameterSet(habitation.active_parameter_set_id)
        cloneFromVersion = active.version_no
      }
      return createParameterSet(currentHabitationId, cloneFromVersion)
    },
    onSuccess: (ps) => {
      persistDraftPsid(currentHabitationId, ps.id)
      setDraftPsidState(ps.id)
      setValidationReport(null)
    },
  })

  function onFieldChange(category: string, key: string, value: unknown) {
    setEdits((prev) => ({ ...prev, [category]: { ...prev[category], [key]: value } }))
  }

  const compositionSum = useMemo(
    () => Object.values(compositionEdits).reduce((sum, v) => sum + (Number(v) || 0), 0),
    [compositionEdits],
  )

  const saveAllMutation = useMutation({
    mutationFn: async () => {
      if (!draftPsid) throw new Error('No draft to save')
      for (const category of Object.keys(edits)) {
        if (category === 'waste_baseline') continue
        const payload = edits[category]
        if (payload && Object.keys(payload).length > 0) {
          await upsertParameterCategory(draftPsid, category, payload)
        }
      }
      const wb = edits.waste_baseline ?? {}
      await upsertWasteBaseline(draftPsid, { ...wb, composition: compositionEdits })
    },
    onSuccess: () => {
      setSaveStatus('All changes saved.')
      queryClient.invalidateQueries({ queryKey: ['parameter-set', draftPsid] })
    },
    onError: (error: Error) => setSaveStatus(`Save failed: ${error.message}`),
  })

  const validateMutation = useMutation({
    mutationFn: () => validateParameterSet(draftPsid as string),
    onSuccess: (report) => setValidationReport(report),
  })

  const commitMutation = useMutation({
    mutationFn: () => commitParameterSet(draftPsid as string),
    onSuccess: () => {
      clearDraftPsid(currentHabitationId)
      setDraftPsidState(null)
      setValidationReport(null)
      queryClient.invalidateQueries({ queryKey: ['habitation', currentHabitationId] })
    },
  })

  const defsByCategory = useMemo(() => {
    const map: Record<string, ParameterDefinition[]> = {}
    for (const def of definitionsQuery.data ?? []) {
      if (def.category === 'waste_baseline') continue
      ;(map[def.category] ??= []).push(def)
    }
    return map
  }, [definitionsQuery.data])

  const wasteBaselineDefs = (definitionsQuery.data ?? []).filter((d) => d.category === 'waste_baseline')

  if (!draftPsid) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <Lock className="h-10 w-10 text-slate-300" />
        <div>
          <h2 className="text-base font-semibold text-slate-800">Parameter Calibration Center</h2>
          <p className="mt-1 max-w-md text-sm text-slate-500">
            {habitationQuery.data?.active_parameter_set_id
              ? 'The active parameter set is committed and read-only. Start a new draft (cloned from it) to edit.'
              : 'This habitation has no parameter set yet. Start a new draft to begin.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => createDraftMutation.mutate()}
          disabled={createDraftMutation.isPending || habitationQuery.isLoading}
          className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
        >
          {createDraftMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus className="h-4 w-4" />}
          Start New Draft
        </button>
        {createDraftMutation.isError && (
          <p className="text-xs text-red-600">{(createDraftMutation.error as Error).message}</p>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6 pb-28">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Parameter Calibration Center</h2>
          <p className="text-xs text-slate-400">
            Editing draft v{draftQuery.data?.version_no ?? '…'} · status {draftQuery.data?.status ?? '…'}
          </p>
        </div>
        {draftQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-emerald-600">
            Auto-Derived Baselines
          </h3>
          {LEFT_CATEGORIES.map((cat) =>
            defsByCategory[cat] ? (
              <CategoryCard key={cat} category={cat} defs={defsByCategory[cat]} edits={edits} onFieldChange={onFieldChange} />
            ) : null,
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Waste Baseline</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {wasteBaselineDefs
                .filter((d) => d.data_type !== 'JSON')
                .map((def) => (
                  <FieldInput
                    key={def.param_key}
                    def={def}
                    value={edits.waste_baseline?.[def.param_key]}
                    onChange={(v) => onFieldChange('waste_baseline', def.param_key, v)}
                  />
                ))}
            </div>
            <div className="mt-3">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="font-medium text-slate-600">Waste composition (%)</span>
                <span className={compositionSum === 100 ? 'text-emerald-600' : 'text-amber-600'}>
                  sum = {compositionSum.toFixed(1)}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                {CANONICAL_FRACTIONS.map((key) => (
                  <label key={key} className="flex flex-col gap-0.5 text-[11px]">
                    <span className="capitalize text-slate-500">{key}</span>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="100"
                      value={compositionEdits[key] ?? ''}
                      onChange={(e) =>
                        setCompositionEdits((prev) => ({ ...prev, [key]: e.target.value === '' ? 0 : Number(e.target.value) }))
                      }
                      className="rounded border border-slate-300 px-1.5 py-1 text-xs"
                    />
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-sky-600">Municipal Overrides</h3>
          {RIGHT_CATEGORIES.map((cat) =>
            defsByCategory[cat] ? (
              <CategoryCard key={cat} category={cat} defs={defsByCategory[cat]} edits={edits} onFieldChange={onFieldChange} />
            ) : null,
          )}
        </div>
      </div>

      <details className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
          More categories (natural resources, terrain, cultural context, industry)
        </summary>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {MORE_CATEGORIES.map((cat) =>
            defsByCategory[cat] ? (
              <CategoryCard key={cat} category={cat} defs={defsByCategory[cat]} edits={edits} onFieldChange={onFieldChange} />
            ) : null,
          )}
        </div>
      </details>

      {validationReport && (
        <div
          className={`rounded-xl border p-4 shadow-sm ${
            validationReport.result === 'PASS' ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'
          }`}
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            {validationReport.result === 'PASS' ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-red-600" />
            )}
            Validation {validationReport.result} · {validationReport.completeness_pct.toFixed(0)}% complete ·{' '}
            {validationReport.error_count} error(s), {validationReport.warning_count} warning(s)
          </div>
          {validationReport.issues.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-slate-600">
              {validationReport.issues.slice(0, 20).map((issue, idx) => (
                <li key={idx}>
                  <span className="font-mono text-[10px] text-slate-400">[{issue.severity}]</span> {issue.field ?? issue.category}:{' '}
                  {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Bottom Action Strip */}
      <div className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-6 py-3 backdrop-blur">
        <p className="text-xs text-slate-500">
          {saveStatus}
          {commitMutation.isError && <span className="text-red-600"> Commit failed: {(commitMutation.error as Error).message}</span>}
          {commitMutation.isSuccess && <span className="text-emerald-600"> Committed as v{commitMutation.data.version_no}.</span>}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => saveAllMutation.mutate()}
            disabled={saveAllMutation.isPending}
            className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
          >
            {saveAllMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Save Changes
          </button>
          <button
            type="button"
            onClick={() => validateMutation.mutate()}
            disabled={validateMutation.isPending}
            className="flex items-center gap-2 rounded-lg border border-sky-300 bg-sky-50 px-4 py-2 text-sm font-medium text-sky-700 transition hover:bg-sky-100 disabled:opacity-60"
          >
            {validateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            Run Validation
          </button>
          <button
            type="button"
            onClick={() => commitMutation.mutate()}
            disabled={commitMutation.isPending || validationReport?.result !== 'PASS'}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            title={validationReport?.result !== 'PASS' ? 'Run a passing validation first' : undefined}
          >
            {commitMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
            Commit Parameter Set
          </button>
        </div>
      </div>
    </div>
  )
}
