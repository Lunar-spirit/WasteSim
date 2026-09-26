import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Factory, Loader2, MapPin, MapPinOff, Mountain, Route, Sparkles, Trash2, X } from 'lucide-react'
import L from 'leaflet'
import { useEffect, useMemo, useRef, useState } from 'react'
import { autoPopulateHabitation, createLayer, fetchHabitation, fetchLayers, fetchMapOverlay, fetchParameterSet } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import { attachBasemapWithFallback } from '../lib/basemap'
import { setDraftPsid } from '../lib/history'
import type { LayerType, MapOverlay } from '../types/api'

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

// The three kinds of point a planner can drop a pin for, with the exact
// same plain-language names used everywhere else on this page (the layer
// toggles above) so the same thing is never called two different names.
const PLACEABLE_POINT_TYPES: { type: LayerType; label: string; icon: typeof MapPin }[] = [
  { type: 'COLLECTION_ZONE', label: 'Collection Point', icon: MapPin },
  { type: 'FACILITY_TREATMENT', label: 'Treatment Facility', icon: Factory },
  { type: 'FACILITY_LANDFILL', label: 'Dumpsite', icon: Trash2 },
]

// A plain inline-SVG pin, not Leaflet's default marker image (whose asset
// path breaks under most bundlers unless specially configured) — no
// external file dependency either way.
function pinIcon(colour: string): L.DivIcon {
  return L.divIcon({
    className: '',
    html: `<svg width="28" height="36" viewBox="0 0 28 36" xmlns="http://www.w3.org/2000/svg">
      <path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 22 14 22s14-11.5 14-22c0-7.7-6.3-14-14-14z" fill="${colour}" stroke="white" stroke-width="2"/>
      <circle cx="14" cy="14" r="5" fill="white"/>
    </svg>`,
    iconSize: [28, 36],
    iconAnchor: [14, 36],
  })
}

function renderOverlay(map: L.Map, overlayLayerGroup: L.LayerGroup, overlay: MapOverlay | undefined, visibleTypes: Set<LayerType>) {
  overlayLayerGroup.clearLayers()
  if (!overlay) return

  if (overlay.boundary && visibleTypes.has('ADMIN_BOUNDARY')) {
    L.geoJSON(overlay.boundary, {
      style: { color: '#16a34a', weight: 2, fillOpacity: 0.08 },
    }).addTo(overlayLayerGroup)
  }

  for (const layer of overlay.layers) {
    if (layer.mode !== 'geojson' || !layer.features) continue
    if (!visibleTypes.has(layer.layer_type)) continue
    const colour = LAYER_COLOURS[layer.layer_type] ?? '#0ea5e9'
    L.geoJSON(layer.features, {
      style: { color: colour, weight: 2, fillOpacity: 0.15 },
      pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 6, color: '#ffffff', weight: 1.5, fillColor: colour, fillOpacity: 1 }),
    }).addTo(overlayLayerGroup)
  }

  if (overlay.bbox) {
    const [minLon, minLat, maxLon, maxLat] = overlay.bbox
    map.fitBounds(
      [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      { padding: [48, 48] },
    )
  }
}

interface PendingPoint {
  lng: number
  lat: number
}

export default function GisStudioPage() {
  const { currentHabitationId } = useAppContext()
  const queryClient = useQueryClient()
  const mapContainerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const overlayLayerGroupRef = useRef<L.LayerGroup | null>(null)
  const markerRef = useRef<L.Marker | null>(null)

  const [visibleTypes, setVisibleTypes] = useState<Set<LayerType>>(() => new Set(LAYER_TOGGLES.map((t) => t.type)))
  const [autoPopulateStatus, setAutoPopulateStatus] = useState<string | null>(null)

  // --- Click-to-place point picker ------------------------------------------
  const [isPicking, setIsPicking] = useState(false)
  const [pendingPoint, setPendingPoint] = useState<PendingPoint | null>(null)
  const [pendingType, setPendingType] = useState<LayerType>('COLLECTION_ZONE')
  const [chipPixel, setChipPixel] = useState<{ x: number; y: number } | null>(null)
  const [placeError, setPlaceError] = useState<string | null>(null)

  // Refs so the map's permanently-registered event handlers (below) always
  // see the latest values without needing to re-subscribe on every render.
  const isPickingRef = useRef(isPicking)
  const pendingPointRef = useRef(pendingPoint)
  useEffect(() => {
    isPickingRef.current = isPicking
  }, [isPicking])
  useEffect(() => {
    pendingPointRef.current = pendingPoint
  }, [pendingPoint])

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
      const psid = result.parameter_set_id as string | undefined
      if (psid) {
        setDraftPsid(currentHabitationId, psid)
        queryClient.invalidateQueries({ queryKey: ['parameter-set', psid] })
      }
      queryClient.invalidateQueries({ queryKey: ['map-overlay', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['gis-layers', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['habitation', currentHabitationId] })
    },
    onError: (error: Error) => setAutoPopulateStatus(`Auto-populate failed: ${error.message}`),
  })

  function clearPin() {
    markerRef.current?.remove()
    markerRef.current = null
    setPendingPoint(null)
    setChipPixel(null)
    setPlaceError(null)
  }

  function stopPicking() {
    setIsPicking(false)
    clearPin()
  }

  const placePointMutation = useMutation({
    mutationFn: (point: PendingPoint & { layerType: LayerType }) => {
      const label = PLACEABLE_POINT_TYPES.find((t) => t.type === point.layerType)?.label ?? point.layerType
      return createLayer(currentHabitationId, {
        layer_name: `${label} — ${new Date().toLocaleString()}`,
        layer_type: point.layerType,
        geojson: {
          type: 'FeatureCollection',
          features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [point.lng, point.lat] } }],
        },
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gis-layers', currentHabitationId] })
      queryClient.invalidateQueries({ queryKey: ['map-overlay', currentHabitationId] })
      stopPicking()
    },
    onError: (error: Error) => setPlaceError(error.message),
  })

  // --- Map lifecycle: created once, a plain Leaflet map (regular <img>
  // tiles + SVG overlays) rather than a WebGL canvas — found live that this
  // environment's browser can execute WebGL draw calls correctly but never
  // actually presents the composited frame on screen, so a WebGL map (the
  // previous MapLibre GL JS build of this page) rendered real pixel data
  // into its own buffer yet stayed visibly blank no matter what tile
  // provider it used. Regular DOM/SVG content doesn't have that problem.
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return
    const map = L.map(mapContainerRef.current, { center: [13.35, 74.8], zoom: 12, zoomControl: true })
    attachBasemapWithFallback(map)
    const overlayLayerGroup = L.layerGroup().addTo(map)
    overlayLayerGroupRef.current = overlayLayerGroup

    function updateChipPixel(latlng: L.LatLng) {
      const point = map.latLngToContainerPoint(latlng)
      setChipPixel({ x: point.x, y: point.y })
    }

    map.on('move', () => {
      if (pendingPointRef.current) {
        updateChipPixel(L.latLng(pendingPointRef.current.lat, pendingPointRef.current.lng))
      }
    })

    map.on('click', (e: L.LeafletMouseEvent) => {
      if (!isPickingRef.current) return
      const point = { lng: e.latlng.lng, lat: e.latlng.lat }
      if (markerRef.current) {
        markerRef.current.setLatLng(e.latlng)
      } else {
        const marker = L.marker(e.latlng, { draggable: true, icon: pinIcon('#059669') }).addTo(map)
        marker.on('drag', () => updateChipPixel(marker.getLatLng()))
        marker.on('dragend', () => {
          const latlng = marker.getLatLng()
          const dragged = { lng: latlng.lng, lat: latlng.lat }
          pendingPointRef.current = dragged
          setPendingPoint(dragged)
          updateChipPixel(latlng)
        })
        markerRef.current = marker
      }
      pendingPointRef.current = point
      setPendingPoint(point)
      setPlaceError(null)
      updateChipPixel(e.latlng)
    })

    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      overlayLayerGroupRef.current = null
      markerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const overlayLayerGroup = overlayLayerGroupRef.current
    if (!map || !overlayLayerGroup || !overlayQuery.data) return
    renderOverlay(map, overlayLayerGroup, overlayQuery.data, visibleTypes)
  }, [overlayQuery.data, visibleTypes])

  // Crosshair cursor only while actively placing a point.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const container = map.getContainer()
    container.style.cursor = isPicking ? 'crosshair' : ''
  }, [isPicking])

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
            onClick={() => (isPicking ? stopPicking() : setIsPicking(true))}
            title={isPicking ? 'Stop placing a point' : 'Click the map to drop a point (collection point, treatment facility, or dumpsite)'}
            aria-pressed={isPicking}
            className={`flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition ${
              isPicking ? 'border-emerald-400 bg-emerald-600 text-white' : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            <MapPin className="h-4 w-4" />
          </button>
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
      {isPicking && !pendingPoint && (
        <p className="flex items-center gap-1.5 text-xs text-emerald-700">
          <MapPin className="h-3.5 w-3.5" /> Click anywhere on the map to drop a point. Drag it afterwards to fine-tune the spot.
        </p>
      )}

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
          <div className="absolute inset-0 z-[500] flex items-center justify-center bg-white/70">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        )}
        {overlayQuery.isError && (
          <div className="absolute inset-0 z-[500] flex flex-col items-center justify-center gap-2 bg-white/90 text-slate-500">
            <MapPinOff className="h-8 w-8" />
            <p className="text-sm">Could not load GIS layers for this habitation.</p>
          </div>
        )}

        {/* Floating confirm/cancel chip, glued to the pin being placed */}
        {pendingPoint && chipPixel && (
          <div
            className="absolute z-[600] flex -translate-x-1/2 -translate-y-full flex-col items-center gap-1.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg"
            style={{ left: chipPixel.x, top: chipPixel.y - 14 }}
          >
            <div className="flex items-center gap-1">
              {PLACEABLE_POINT_TYPES.map(({ type, label, icon: Icon }) => (
                <button
                  key={type}
                  type="button"
                  title={label}
                  onClick={() => setPendingType(type)}
                  className={`flex h-7 w-7 items-center justify-center rounded-lg border transition ${
                    pendingType === type ? 'border-emerald-400 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                </button>
              ))}
              <span className="mx-0.5 h-5 w-px bg-slate-200" />
              <button
                key="confirm"
                type="button"
                title={`Save as: ${PLACEABLE_POINT_TYPES.find((t) => t.type === pendingType)?.label}`}
                onClick={() => placePointMutation.mutate({ ...pendingPoint, layerType: pendingType })}
                disabled={placePointMutation.isPending}
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-600 text-white transition hover:bg-emerald-700 disabled:opacity-60"
              >
                {placePointMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              </button>
              <button
                key="cancel"
                type="button"
                title="Discard this point"
                onClick={stopPicking}
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            {placeError && <p className="max-w-[220px] text-center text-[10px] text-red-600">{placeError}</p>}
          </div>
        )}

        {/* Floating GIS Inspector Card */}
        <div className="absolute bottom-4 left-4 z-[500] w-64 rounded-xl border border-slate-200 bg-white/95 p-4 text-xs shadow-lg backdrop-blur">
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
          {!layersQuery.isLoading && inspector.layerCount === 0 && (
            <p className="mt-2.5 rounded-lg bg-amber-50 px-2 py-1.5 text-amber-700">
              No GIS layers yet for this habitation. Try <span className="font-medium">Auto-Populate</span> above, or use the{' '}
              <span className="font-medium">pin tool</span> to add one by hand.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
