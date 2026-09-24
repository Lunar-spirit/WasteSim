import { useQuery } from '@tanstack/react-query'
import { Loader2, MapPinOff } from 'lucide-react'
// maplibre-gl v6 ships ESM with only named exports — there is no default
// export (`import maplibregl from 'maplibre-gl'` fails at runtime with
// "does not provide an export named 'default'", found live while first
// loading this component in the browser).
import { Map as MaplibreMap, NavigationControl, type StyleSpecification } from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import { fetchMapOverlay } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import type { MapOverlay } from '../types/api'

// A plain OSM raster basemap — no API key, no hosted vector-style
// dependency, works offline-of-any-third-party-key the same way the
// backend's own external integrations are all keyless by default.
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

// One colour per layer_type so roads, facilities, water bodies etc read
// distinctly on the map without needing a full style config from the user.
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

function renderOverlay(map: MaplibreMap, overlay: MapOverlay) {
  // Clear anything from a previous habitation/render before drawing again.
  const staleLayers = map.getStyle().layers?.filter((l) => l.id.startsWith(LAYER_SOURCE_PREFIX) || l.id.startsWith(BOUNDARY_SOURCE_ID)) ?? []
  for (const layer of staleLayers) {
    if (map.getLayer(layer.id)) map.removeLayer(layer.id)
  }
  for (const sourceId of Object.keys(map.getStyle().sources ?? {})) {
    if (sourceId.startsWith(LAYER_SOURCE_PREFIX) || sourceId === BOUNDARY_SOURCE_ID) {
      if (map.getSource(sourceId)) map.removeSource(sourceId)
    }
  }

  if (overlay.boundary) {
    addFeatureCollectionLayers(
      map,
      BOUNDARY_SOURCE_ID,
      { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: overlay.boundary }] },
      '#16a34a',
    )
  }

  for (const layer of overlay.layers) {
    if (layer.mode !== 'geojson' || !layer.features) continue
    const colour = LAYER_COLOURS[layer.layer_type] ?? '#0ea5e9'
    addFeatureCollectionLayers(map, `${LAYER_SOURCE_PREFIX}${layer.layer_id}`, layer.features, colour)
  }

  if (overlay.bbox) {
    const [minLon, minLat, maxLon, maxLat] = overlay.bbox
    map.fitBounds(
      [
        [minLon, minLat],
        [maxLon, maxLat],
      ],
      { padding: 48, duration: 400 },
    )
  }
}

export default function GisMap() {
  const { currentHabitationId } = useAppContext()
  const mapContainerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MaplibreMap | null>(null)
  const isStyleLoadedRef = useRef(false)

  const overlayQuery = useQuery({
    queryKey: ['map-overlay', currentHabitationId],
    queryFn: () => fetchMapOverlay(currentHabitationId),
  })

  // Create the map once.
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
      if (overlayQuery.data) renderOverlay(map, overlayQuery.data)
    })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      isStyleLoadedRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Redraw whenever the overlay data changes (new habitation, refetch).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !overlayQuery.data || !isStyleLoadedRef.current) return
    renderOverlay(map, overlayQuery.data)
  }, [overlayQuery.data])

  const totalFeatures = overlayQuery.data?.layers.reduce((sum, l) => sum + l.feature_count, 0) ?? 0

  return (
    <div className="relative flex h-full flex-col gap-3 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">GIS Map View</h2>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          {overlayQuery.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {overlayQuery.data && (
            <span>
              {overlayQuery.data.layers.length} layer(s) · {totalFeatures} feature(s)
            </span>
          )}
        </div>
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
      </div>

      {overlayQuery.data && overlayQuery.data.layers.length > 0 && (
        <div className="flex flex-wrap gap-3 text-xs">
          {overlayQuery.data.layers.map((layer) => (
            <span key={layer.layer_id} className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: LAYER_COLOURS[layer.layer_type] ?? '#0ea5e9' }}
              />
              {layer.layer_name} ({layer.feature_count})
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
