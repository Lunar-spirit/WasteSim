import { useMutation, useQueryClient } from '@tanstack/react-query'
import L from 'leaflet'
import { Check, Loader2, MapPin, Plus, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createHabitation } from '../api/endpoints'
import { attachBasemapWithFallback } from '../lib/basemap'
import { searchPlaceBoundaries, type PlaceSearchResult } from '../lib/placeSearch'
import type { HabitationType } from '../types/api'

const HABITATION_TYPES: HabitationType[] = ['VILLAGE', 'WARD', 'TOWN', 'CITY']

interface Props {
  onClose: () => void
  onCreated: (habitationId: string) => void
}

type BoundaryMode = 'search' | 'bbox' | 'geojson' | 'none'

/** Click-and-drag-to-draw-a-rectangle map, so the boundary's four corner
 * coordinates never have to be typed or looked up anywhere — dragging the
 * rectangle just writes lon/lat numbers into the same four fields the
 * "Draw a rectangle" mode already used. */
function BoundaryDrawMap({
  onDrawn,
}: {
  onDrawn: (bounds: { minLon: number; minLat: number; maxLon: number; maxLat: number }) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = L.map(containerRef.current, { center: [13.35, 74.8], zoom: 11 })
    attachBasemapWithFallback(map)
    mapRef.current = map

    let startLatLng: L.LatLng | null = null
    let rectangle: L.Rectangle | null = null

    map.on('mousedown', (e: L.LeafletMouseEvent) => {
      startLatLng = e.latlng
      map.dragging.disable()
      rectangle?.remove()
      rectangle = L.rectangle([e.latlng, e.latlng], { color: '#059669', weight: 2, fillOpacity: 0.12 }).addTo(map)
    })
    map.on('mousemove', (e: L.LeafletMouseEvent) => {
      if (!startLatLng || !rectangle) return
      rectangle.setBounds(L.latLngBounds(startLatLng, e.latlng))
    })
    map.on('mouseup', (e: L.LeafletMouseEvent) => {
      if (!startLatLng) return
      map.dragging.enable()
      // A plain click with no real drag isn't a rectangle — leave it be
      // rather than snapping to a zero-area box.
      if (startLatLng.equals(e.latlng)) {
        startLatLng = null
        return
      }
      const bounds = L.latLngBounds(startLatLng, e.latlng)
      onDrawn({
        minLon: bounds.getWest(),
        minLat: bounds.getSouth(),
        maxLon: bounds.getEast(),
        maxLat: bounds.getNorth(),
      })
      startLatLng = null
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <div ref={containerRef} className="h-56 w-full rounded-lg border border-slate-200" />
}

/** Read-only preview of a real administrative boundary fetched from the
 * place search — just draws the polygon and fits the view to it. */
function PlacePreviewMap({ place }: { place: PlaceSearchResult }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    if (!mapRef.current) {
      mapRef.current = L.map(containerRef.current, { zoomControl: false, dragging: false, scrollWheelZoom: false })
      attachBasemapWithFallback(mapRef.current)
    }
    const map = mapRef.current
    map.eachLayer((layer) => {
      if (layer instanceof L.GeoJSON) map.removeLayer(layer)
    })
    L.geoJSON(place.geojson, { style: { color: '#059669', weight: 2, fillOpacity: 0.15 } }).addTo(map)
    const [minLon, minLat, maxLon, maxLat] = place.boundingBox
    map.fitBounds(
      [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      { padding: [16, 16] },
    )
    return () => {
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [place])

  return <div ref={containerRef} className="h-40 w-full rounded-lg border border-slate-200" />
}

export default function CreateHabitationModal({ onClose, onCreated }: Props) {
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [habitationType, setHabitationType] = useState<HabitationType>('VILLAGE')
  const [state, setState] = useState('')
  const [district, setDistrict] = useState('')
  const [country, setCountry] = useState('India')
  const [areaSqkm, setAreaSqkm] = useState<string>('')

  const [boundaryMode, setBoundaryMode] = useState<BoundaryMode>('search')

  // "Search by place name" mode — a real administrative boundary (state,
  // district, city, ...) looked up by name instead of drawn or typed.
  const [placeQuery, setPlaceQuery] = useState('')
  const [selectedPlace, setSelectedPlace] = useState<PlaceSearchResult | null>(null)
  const searchMutation = useMutation({ mutationFn: searchPlaceBoundaries })

  function selectPlace(place: PlaceSearchResult) {
    setSelectedPlace(place)
    if (!state.trim() && place.state) setState(place.state)
    if (!district.trim() && place.district) setDistrict(place.district)
  }

  // "Draw a rectangle" mode — kept for a precise custom area a named place
  // doesn't cover exactly.
  const [minLon, setMinLon] = useState('')
  const [minLat, setMinLat] = useState('')
  const [maxLon, setMaxLon] = useState('')
  const [maxLat, setMaxLat] = useState('')

  const [geojsonText, setGeojsonText] = useState('')
  const [geojsonError, setGeojsonError] = useState<string | null>(null)

  function buildBoundaryGeojson(): Record<string, unknown> | null {
    if (boundaryMode === 'none') return null

    if (boundaryMode === 'search') {
      return selectedPlace ? (selectedPlace.geojson as unknown as Record<string, unknown>) : null
    }

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
    (boundaryMode === 'search' && selectedPlace != null) ||
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
            <div className="mb-2 flex flex-wrap gap-1">
              {(['search', 'bbox', 'geojson', 'none'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setBoundaryMode(mode)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition ${
                    boundaryMode === mode ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500'
                  }`}
                >
                  {mode === 'search'
                    ? 'Find a district / state'
                    : mode === 'bbox'
                      ? 'Draw a rectangle'
                      : mode === 'geojson'
                        ? 'Paste GeoJSON'
                        : 'Skip for now'}
                </button>
              ))}
            </div>

            {boundaryMode === 'search' && (
              <div className="flex flex-col gap-2">
                <p className="text-[11px] text-slate-500">
                  Search for the real administrative area by name — its actual boundary is used, not a rough rectangle.
                </p>
                <div className="flex gap-1.5">
                  <input
                    type="text"
                    value={placeQuery}
                    onChange={(e) => setPlaceQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && placeQuery.trim()) {
                        e.preventDefault()
                        searchMutation.mutate(placeQuery)
                      }
                    }}
                    placeholder="e.g. Udupi, or Karnataka"
                    className="flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                  <button
                    type="button"
                    onClick={() => searchMutation.mutate(placeQuery)}
                    disabled={!placeQuery.trim() || searchMutation.isPending}
                    className="flex items-center gap-1 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
                  >
                    {searchMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                  </button>
                </div>

                {searchMutation.isError && <p className="text-xs text-red-600">{(searchMutation.error as Error).message}</p>}
                {searchMutation.data?.length === 0 && <p className="text-xs text-slate-400">No matching places found — try a different spelling.</p>}

                {searchMutation.data && searchMutation.data.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {searchMutation.data.map((place) => (
                      <button
                        key={place.osmId}
                        type="button"
                        onClick={() => selectPlace(place)}
                        className={`flex items-center justify-between rounded-md border px-2.5 py-1.5 text-left text-xs transition ${
                          selectedPlace?.osmId === place.osmId ? 'border-emerald-400 bg-emerald-50' : 'border-slate-200 hover:bg-slate-50'
                        }`}
                      >
                        <span>
                          {place.displayName} <span className="text-slate-400">· {place.placeType.replaceAll('_', ' ')}</span>
                        </span>
                        {selectedPlace?.osmId === place.osmId && <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />}
                      </button>
                    ))}
                  </div>
                )}

                {selectedPlace && (
                  <div className="flex flex-col gap-1.5">
                    <p className="text-[11px] text-emerald-700">Using: {selectedPlace.displayName}</p>
                    <PlacePreviewMap place={selectedPlace} />
                  </div>
                )}
              </div>
            )}

            {boundaryMode === 'bbox' && (
              <div className="flex flex-col gap-2">
                <p className="text-[11px] text-slate-500">
                  Click and drag on the map to draw a rectangle over the habitation — no coordinates to type.
                </p>
                <BoundaryDrawMap
                  onDrawn={({ minLon, minLat, maxLon, maxLat }) => {
                    setMinLon(minLon.toFixed(5))
                    setMinLat(minLat.toFixed(5))
                    setMaxLon(maxLon.toFixed(5))
                    setMaxLat(maxLat.toFixed(5))
                  }}
                />
                {minLon && minLat && maxLon && maxLat && (
                  <p className="text-[11px] text-emerald-700">
                    Rectangle set — {minLat}, {minLon} to {maxLat}, {maxLon}. Draw again to adjust.
                  </p>
                )}
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
