import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MapPinOff, Mountain, Route, Sparkles } from 'lucide-react'
// maplibre-gl v6 ships ESM with only named exports — there is no default
// export (`import maplibregl from 'maplibre-gl'` fails at runtime with
// "does not provide an export named 'default'", found live while first
// building this workspace).
import { Map as MaplibreMap, NavigationControl, type StyleSpecification } from 'maplibre-gl'
import { useEffect, useMemo, useRef, useState } from 'react'
import { autoPopulateHabitation, fetchHabitation, fetchLayers, fetchMapOverlay, fetchParameterSet } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { setDraftPsid } from '../lib/history'
import type { LayerType, MapOverlay } from '../types/api'

const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    'osm-raster': {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm-raster-layer', type: 'raster', source: 'osm-raster' }],
}

const BOUNDARY_SOURCE_ID = 'habitation-boundary'
const LAYER_SOURCE_PREFIX = 'gis-layer-'

const LAYER_COLOURS: Record<string, string> = {
  ROAD: '#334155',
  SETTLEMENT: '#f97316',
  INDUSTRIAL_ZONE: '#a855f7',
  WATER_BODY: '#0ea5e9',
  TERRAIN_CONTOUR: '#84cc16',
  ECO_SENSITIVE: '#22c55e',
  ADMIN_BOUNDARY: '#64748b',
  FACILITY_TREATMENT: '#ec4899',
  FACILITY_LANDFILL: '#dc2626',
  COLLECTION_ZONE: '#eab308',
}

const LAYER_TOGGLES: { type: LayerType; label: string }[] = [
  { type: 'ADMIN_BOUNDARY', label: 'Administrative Boundaries' },
  { type: 'ROAD', label: 'Roads' },
  { type: 'WATER_BODY', label: 'Waterways / Flood Lowlands' },
  { type: 'COLLECTION_ZONE', label: 'Collection Depots / Zones' },
  { type: 'FACILITY_LANDFILL', label: 'Current Dumpsite' },
  { type: 'FACILITY_TREATMENT', label: 'Treatment Facilities' },
  { type: 'SETTLEMENT', label: 'Settlements' },
  { type: 'TERRAIN_CONTOUR', label: 'Terrain Contours' },
  { type: 'ECO_SENSITIVE', label: 'Eco-Sensitive Zones' },
  { type: 'INDUSTRIAL_ZONE', label: 'Industrial Zones' },
]

function addFeatureCollectionLayers(
  map: MaplibreMap,
  sourceId: string,
  featureCollection: GeoJSON.FeatureCollection,
  colour: string,
) {
  map.addSource(sourceId, { type: 'geojson', data: featureCollection })
  map.addLayer({
    id: `${sourceId}-fill`,
    type: 'fill',
    source: sourceId,
    filter: ['==', ['geometry-type'], 'Polygon'],
    paint: { 'fill-color': colour, 'fill-opacity': 0.15 },
  })
  map.addLayer({
    id: `${sourceId}-line`,
    type: 'line',
    source: sourceId,
    filter: ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'LineString']],
    paint: { 'line-color': colour, 'line-width': 2 },
  })
  map.addLayer({
    id: `${sourceId}-point`,
    type: 'circle',
    source: sourceId,
    filter: ['==', ['geometry-type'], 'Point'],
    paint: { 'circle-radius': 6, 'circle-color': colour, 'circle-stroke-width': 1.5, 'circle-stroke-color': '#ffffff' },
  })
}

function renderOverlay(map: MaplibreMap, overlay: MapOverlay, visibleTypes: Set<LayerType>) {
  const staleLayers =
    map.getStyle().layers?.filter((l) => l.id.startsWith(LAYER_SOURCE_PREFIX) || l.id.startsWith(BOUNDARY_SOURCE_ID)) ?? []
  for (const layer of staleLayers) {
    if (map.getLayer(layer.id)) map.removeLayer(layer.id)
  }
  for (const sourceId of Object.keys(map.getStyle().sources ?? {})) {
    if (sourceId.startsWith(LAYER_SOURCE_PREFIX) || sourceId === BOUNDARY_SOURCE_ID) {
      if (map.getSource(sourceId)) map.removeSource(sourceId)
    }
  }

  if (overlay.boundary && visibleTypes.has('ADMIN_BOUNDARY')) {
    addFeatureCollectionLayers(
      map,
      BOUNDARY_SOURCE_ID,
      { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: overlay.boundary }] },
      '#16a34a',
    )
  }

  for (const layer of overlay.layers) {
    if (layer.mode !== 'geojson' || !layer.features) continue
    if (!visibleTypes.has(layer.layer_type)) continue
    const colour = LAYER_COLOURS[layer.layer_type] ?? '#0ea5e9'
    addFeatureCollectionLayers(map, `${LAYER_SOURCE_PREFIX}${layer.layer_id}`, layer.features, colour)
  }

  if (overlay.bbox) {
    const [minLon, minLat, maxLon, maxLat] = overlay.bbox
    map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 48, duration: 400 })
  }
}

export default function GisStudioPage() {
  const { currentHabitationId } = useAppContext()
  const queryClient = useQueryClient()
  const mapContainerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MaplibreMap | null>(null)
  const isStyleLoadedRef = useRef(false)

  const [visibleTypes, setVisibleTypes] = useState<Set<LayerType>>(() => new Set(LAYER_TOGGLES.map((t) => t.type)))
  const [autoPopulateStatus, setAutoPopulateStatus] = useState<string | null>(null)

  const overlayQuery = useQuery({
    queryKey: ['map-overlay', currentHabitationId],
    queryFn: () => fetchMapOverlay(currentHabitationId),
  })

  const layersQuery = useQuery({
    queryKey: ['gis-layers', currentHabitationId],
    queryFn: () => fetchLayers(currentHabitationId),
  })

  const habitationQuery = useQuery({
    queryKey: ['habitation', currentHabitationId],
    queryFn: () => fetchHabitation(currentHabitationId),
  })

  const parameterSetQuery = useQuery({
    queryKey: ['parameter-set', habitationQuery.data?.active_parameter_set_id],
    queryFn: () => fetchParameterSet(habitationQuery.data!.active_parameter_set_id as string),
    enabled: !!habitationQuery.data?.active_parameter_set_id,
  })

  const autoPopulateMutation = useMutation({
    mutationFn: () => autoPopulateHabitation(currentHabitationId),
    onSuccess: (result) => {
      const automated = (result.automated_categories as string[] | undefined) ?? []
      const skipped = (result.skipped_categories as { category: string }[] | undefined) ?? []
      setAutoPopulateStatus(
        `Auto-populated ${automated.length} field(s)` +
          (skipped.length ? `, skipped ${skipped.length} (external service unavailable)` : ''),
      )
      // Auto-populate writes into a real draft parameter set behind the
      // scenes (creating one if the habitation had none) — record it so
      // the Parameters page reuses this draft instead of starting a blank
      // second one that would orphan everything just fetched.
      const psid = result.parameter_set_id as string | undefined
      if (psid) {
        setDraftPsid(currentHabitationId, psid)
        // The Parameters page may already have this exact parameter set
        // cached from an earlier visit (before auto-populate wrote into
        // it) — without this, it would keep showing pre-populate values
        // until something else happens to refetch it.
        queryClient.invalidateQueries({ queryKey: ['parameter-set', psid] })
      }
      queryClient.invalidateQueries({ queryKey: ['map-overlay', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['gis-layers', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['habitation', currentHabitationId] })
    },
    onError: (error: Error) => setAutoPopulateStatus(`Auto-populate failed: ${error.message}`),
  })

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return
    const map = new MaplibreMap({
      container: mapContainerRef.current,
      style: BASE_STYLE,
      center: [74.8, 13.35],
      zoom: 12,
      attributionControl: { compact: true },
    })
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.on('load', () => {
      isStyleLoadedRef.current = true
      if (overlayQuery.data) renderOverlay(map, overlayQuery.data, visibleTypes)
    })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      isStyleLoadedRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !overlayQuery.data || !isStyleLoadedRef.current) return
    renderOverlay(map, overlayQuery.data, visibleTypes)
  }, [overlayQuery.data, visibleTypes])

  function toggleLayer(type: LayerType) {
    setVisibleTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const inspector = useMemo(() => {
    const layers = layersQuery.data ?? []
    const totalRoadKm = layers
      .filter((l) => l.layer_type === 'ROAD')
      .reduce((sum, l) => sum + (l.total_length_km ?? 0), 0)
    const totalFeatures = layers.reduce((sum, l) => sum + l.feature_count, 0)
    return { totalRoadKm, totalFeatures, layerCount: layers.length }
  }, [layersQuery.data])

  // Numeric parameter-category values pass through the backend as a raw
  // dict (not a typed Pydantic response model), so a Numeric/Decimal
  // column can arrive JSON-encoded as a string rather than a number —
  // coerce defensively rather than assume the JS typeof.
  const terrainRaw = parameterSetQuery.data?.categories?.terrain as
    | { avg_slope_pct?: unknown; terrain_type?: string; coastal_buffer_zone_meters?: unknown }
    | undefined
  const terrain = terrainRaw
    ? { ...terrainRaw, avg_slope_pct: terrainRaw.avg_slope_pct != null ? Number(terrainRaw.avg_slope_pct) : undefined }
    : undefined

  return (
    <div className="relative flex h-full flex-col gap-3 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Studio &amp; GIS Digital Twin</h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => autoPopulateMutation.mutate()}
            disabled={autoPopulateMutation.isPending}
            className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-sm font-medium text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-60"
          >
            {autoPopulateMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            Auto-Populate
          </button>
          {overlayQuery.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
        </div>
      </div>
      {autoPopulateStatus && <p className="text-xs text-slate-500">{autoPopulateStatus}</p>}

      <div className="flex flex-wrap gap-2">
        {LAYER_TOGGLES.map(({ type, label }) => {
          const present = overlayQuery.data?.layers.some((l) => l.layer_type === type) ?? (type === 'ADMIN_BOUNDARY')
          const checked = visibleTypes.has(type)
          return (
            <label
              key={type}
              className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition ${
                checked ? 'border-slate-300 bg-white text-slate-700' : 'border-slate-100 bg-slate-50 text-slate-400'
              } ${!present ? 'opacity-40' : ''}`}
            >
              <input type="checkbox" checked={checked} onChange={() => toggleLayer(type)} className="h-3 w-3 accent-emerald-600" />
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: LAYER_COLOURS[type] }} />
              {label}
            </label>
          )
        })}
      </div>

      <div className="relative min-h-[480px] flex-1 overflow-hidden rounded-xl border border-slate-200 shadow-sm">
        <div ref={mapContainerRef} className="absolute inset-0" />
        {overlayQuery.isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        )}
        {overlayQuery.isError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white/90 text-slate-500">
            <MapPinOff className="h-8 w-8" />
            <p className="text-sm">Could not load GIS layers for this habitation.</p>
          </div>
        )}

        {/* Floating GIS Inspector Card */}
        <div className="absolute bottom-4 left-4 w-64 rounded-xl border border-slate-200 bg-white/95 p-4 text-xs shadow-lg backdrop-blur">
          <h3 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            <Route className="h-3.5 w-3.5" /> GIS Inspector
          </h3>
          <dl className="space-y-1.5">
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Total road length</dt>
              <dd className="font-medium text-slate-800">{inspector.totalRoadKm.toFixed(2)} km</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">GIS layers</dt>
              <dd className="font-medium text-slate-800">{inspector.layerCount}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Total features</dt>
              <dd className="font-medium text-slate-800">{inspector.totalFeatures}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Habitation area</dt>
              <dd className="font-medium text-slate-800">{habitationQuery.data?.area_sqkm?.toFixed(2) ?? '—'} km²</dd>
            </div>
          </dl>
          {terrain && (
            <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-slate-50 px-2 py-1.5">
              <Mountain className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-slate-600">
                {terrain.terrain_type ?? 'Terrain unknown'}
                {terrain.avg_slope_pct != null ? ` · ${terrain.avg_slope_pct.toFixed(1)}% avg slope` : ''}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
