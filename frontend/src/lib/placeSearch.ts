// Nominatim (OpenStreetMap's own free, keyless geocoding service) can
// return a place's REAL administrative boundary polygon by name — "Udupi"
// or "Karnataka" — instead of a planner having to draw a rectangle by
// hand. Called directly from the browser: Nominatim's public API sends
// CORS headers for exactly this. Usage policy requires a real User-Agent
// and no more than ~1 request/second, both fine for a person typing one
// search at a time.
//
// `geojson` is typed as a plain object, not a GeoJSON.Polygon/MultiPolygon
// namespace type — @types/geojson isn't a project dependency, and this
// value only ever gets handed straight to MapLibre's GeoJSON source or the
// backend's own `boundary_geojson: Record<string, unknown>` field, never
// inspected field-by-field on the frontend.
export interface PlaceSearchResult {
  osmId: number
  name: string
  displayName: string
  placeType: string // e.g. "state", "state_district", "city", "village"
  geojson: Record<string, unknown>
  boundingBox: [number, number, number, number] // [minLon, minLat, maxLon, maxLat]
  state?: string
  district?: string
  country?: string
}

interface NominatimResult {
  osm_id: number
  name: string
  display_name: string
  addresstype: string
  category: string
  geojson?: { type: string; coordinates: unknown }
  boundingbox: [string, string, string, string] // [minLat, maxLat, minLon, maxLon] — Nominatim's own odd order
  address?: { state?: string; state_district?: string; county?: string; country?: string }
}

export async function searchPlaceBoundaries(query: string): Promise<PlaceSearchResult[]> {
  const url = new URL('https://nominatim.openstreetmap.org/search')
  url.searchParams.set('q', query)
  url.searchParams.set('format', 'jsonv2')
  url.searchParams.set('polygon_geojson', '1')
  url.searchParams.set('addressdetails', '1')
  url.searchParams.set('limit', '6')

  const response = await fetch(url.toString(), {
    headers: { 'Accept-Language': 'en' },
  })
  if (!response.ok) {
    throw new Error(`Place search failed (${response.status})`)
  }
  const results = (await response.json()) as NominatimResult[]

  return results
    .filter((r): r is NominatimResult & { geojson: NonNullable<NominatimResult['geojson']> } =>
      r.geojson != null && (r.geojson.type === 'Polygon' || r.geojson.type === 'MultiPolygon'),
    )
    .map((r) => {
      const [minLat, maxLat, minLon, maxLon] = r.boundingbox.map(Number)
      return {
        osmId: r.osm_id,
        name: r.name,
        displayName: r.display_name,
        placeType: r.addresstype || r.category,
        geojson: r.geojson as Record<string, unknown>,
        boundingBox: [minLon, minLat, maxLon, maxLat] as [number, number, number, number],
        state: r.address?.state,
        district: r.address?.state_district ?? r.address?.county,
        country: r.address?.country,
      }
    })
}
