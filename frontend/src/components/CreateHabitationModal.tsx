import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, MapPin, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { createHabitation } from '../api/endpoints'
import type { HabitationType } from '../types/api'

const HABITATION_TYPES: HabitationType[] = ['VILLAGE', 'WARD', 'TOWN', 'CITY']

interface Props {
  onClose: () => void
  onCreated: (habitationId: string) => void
}

type BoundaryMode = 'none' | 'bbox' | 'geojson'

export default function CreateHabitationModal({ onClose, onCreated }: Props) {
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [habitationType, setHabitationType] = useState<HabitationType>('VILLAGE')
  const [state, setState] = useState('')
  const [district, setDistrict] = useState('')
  const [country, setCountry] = useState('India')
  const [areaSqkm, setAreaSqkm] = useState<string>('')

  const [boundaryMode, setBoundaryMode] = useState<BoundaryMode>('bbox')
  const [minLon, setMinLon] = useState('')
  const [minLat, setMinLat] = useState('')
  const [maxLon, setMaxLon] = useState('')
  const [maxLat, setMaxLat] = useState('')
  const [geojsonText, setGeojsonText] = useState('')
  const [geojsonError, setGeojsonError] = useState<string | null>(null)

  function buildBoundaryGeojson(): Record<string, unknown> | null {
    if (boundaryMode === 'none') return null

    if (boundaryMode === 'bbox') {
      const nums = [minLon, minLat, maxLon, maxLat].map(Number)
      if (nums.some((n) => Number.isNaN(n)) || minLon === '' || minLat === '' || maxLon === '' || maxLat === '') {
        return null
      }
      const [w, s, e, n] = nums
      return {
        type: 'Polygon',
        coordinates: [
          [
            [w, s],
            [e, s],
            [e, n],
            [w, n],
            [w, s],
          ],
        ],
      }
    }

    // 'geojson'
    try {
      const parsed = JSON.parse(geojsonText)
      setGeojsonError(null)
      return parsed
    } catch {
      setGeojsonError('Not valid JSON')
      return null
    }
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createHabitation({
        name,
        habitation_type: habitationType,
        state,
        district,
        country: country || 'India',
        boundary_geojson: buildBoundaryGeojson(),
        area_sqkm: areaSqkm === '' ? null : Number(areaSqkm),
      }),
    onSuccess: (habitation) => {
      queryClient.invalidateQueries({ queryKey: ['habitations'] })
      onCreated(habitation.id)
      onClose()
    },
  })

  const boundaryReady =
    boundaryMode === 'none' ||
    (boundaryMode === 'bbox' && minLon !== '' && minLat !== '' && maxLon !== '' && maxLat !== '') ||
    (boundaryMode === 'geojson' && geojsonText.trim() !== '')

  const canSubmit = name.trim() && state.trim() && district.trim() && boundaryReady && !createMutation.isPending

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-bold text-slate-900">
            <MapPin className="h-5 w-5 text-emerald-600" />
            New Habitation
          </h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Name *</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Kotekar"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">Habitation type *</span>
            <select
              value={habitationType}
              onChange={(e) => setHabitationType(e.target.value as HabitationType)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {HABITATION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">State *</span>
              <input
                type="text"
                value={state}
                onChange={(e) => setState(e.target.value)}
                placeholder="e.g. Karnataka"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">District *</span>
              <input
                type="text"
                value={district}
                onChange={(e) => setDistrict(e.target.value)}
                placeholder="e.g. Udupi"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Country</span>
              <input
                type="text"
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-slate-700">Area (km²)</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={areaSqkm}
                onChange={(e) => setAreaSqkm(e.target.value)}
                placeholder="auto from boundary"
                className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </label>
          </div>

          <div className="rounded-lg border border-slate-200 p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Boundary geometry (needed for GIS Studio, Auto-Populate, and scenario map picking)
            </p>
            <div className="mb-2 flex gap-1">
              {(['bbox', 'geojson', 'none'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setBoundaryMode(mode)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition ${
                    boundaryMode === mode ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500'
                  }`}
                >
                  {mode === 'bbox' ? 'Bounding box' : mode === 'geojson' ? 'Paste GeoJSON' : 'Skip for now'}
                </button>
              ))}
            </div>

            {boundaryMode === 'bbox' && (
              <div className="grid grid-cols-2 gap-2">
                <input type="number" step="any" placeholder="Min longitude (west)" value={minLon} onChange={(e) => setMinLon(e.target.value)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs" />
                <input type="number" step="any" placeholder="Min latitude (south)" value={minLat} onChange={(e) => setMinLat(e.target.value)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs" />
                <input type="number" step="any" placeholder="Max longitude (east)" value={maxLon} onChange={(e) => setMaxLon(e.target.value)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs" />
                <input type="number" step="any" placeholder="Max latitude (north)" value={maxLat} onChange={(e) => setMaxLat(e.target.value)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs" />
                <p className="col-span-2 text-[11px] text-slate-400">
                  A simple rectangle covering the habitation — find these on{' '}
                  <a href="https://boundingbox.klokantech.com" target="_blank" rel="noopener noreferrer" className="underline">
                    boundingbox.klokantech.com
                  </a>{' '}
                  if unsure. Precise data can be uploaded later on the GIS Studio page.
                </p>
              </div>
            )}
            {boundaryMode === 'geojson' && (
              <div>
                <textarea
                  value={geojsonText}
                  onChange={(e) => setGeojsonText(e.target.value)}
                  placeholder='{"type": "Polygon", "coordinates": [[[74.79,13.34], ...]]}'
                  rows={4}
                  className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-xs"
                />
                {geojsonError && <p className="mt-1 text-xs text-red-600">{geojsonError}</p>}
              </div>
            )}
            {boundaryMode === 'none' && (
              <p className="text-[11px] text-slate-400">
                You can add a boundary later, but Auto-Populate and the GIS map won't work until one exists.
              </p>
            )}
          </div>
        </div>

        {createMutation.isError && (
          <p className="mt-3 text-xs text-red-600">
            {(createMutation.error as Error & { code?: string }).code === 'HABITATION_DUPLICATE'
              ? 'A habitation with this name already exists in that state/district.'
              : (createMutation.error as Error).message}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={!canSubmit}
            className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create Habitation
          </button>
        </div>
      </div>
    </div>
  )
}
