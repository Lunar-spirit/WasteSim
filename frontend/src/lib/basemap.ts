import L from 'leaflet'

// Several free, keyless raster basemaps, tried in order. Real map providers
// occasionally rate-limit, block, or go slow for embedded/automated
// traffic — rather than depend on exactly one of them, every map built
// with attachBasemapWithFallback watches for a burst of tile failures and
// quietly swaps to the next provider, so the map keeps working no matter
// which one is reachable right now.
//
// CARTO's free basemaps.cartocdn.com raster endpoint was tried first here
// originally, but as of this build it now returns a genuine 200 OK "API
// KEY REQUIRED" watermark image for every tile rather than an HTTP error —
// confirmed live by fetching a tile directly (a ~2KB placeholder PNG vs. a
// real ~40KB+ rendered tile) — so Leaflet's tileerror-counting fallback
// below never even sees it as a failure. Plain OpenStreetMap tiles are the
// primary provider instead: no key, confirmed working, most widely
// deployed keyless raster tile source there is.
export const BASEMAP_PROVIDERS: { id: string; url: string; subdomains?: string; attribution: string }[] = [
  {
    id: 'osm-standard',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
  },
  {
    id: 'opentopomap',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    subdomains: 'abc',
    attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap',
  },
]

// A tile server that's genuinely down errors quickly and repeatedly — this
// many failures on the current provider is treated as "this one isn't
// working", not just bad luck on a couple of tiles.
const TILE_FAILURE_THRESHOLD = 6

/**
 * Adds a raster basemap to `map` and returns it. If the current provider
 * racks up TILE_FAILURE_THRESHOLD failed tile loads, it's swapped out for
 * the next provider in BASEMAP_PROVIDERS (once), preserving whatever else
 * is already drawn on the map (markers, GeoJSON overlays) since only the
 * tile layer itself is replaced.
 */
export function attachBasemapWithFallback(map: L.Map): L.TileLayer {
  let providerIndex = 0
  let failureCount = 0
  let currentLayer = createLayer(providerIndex)
  currentLayer.addTo(map)
  return currentLayer

  function createLayer(index: number): L.TileLayer {
    const provider = BASEMAP_PROVIDERS[index] ?? BASEMAP_PROVIDERS[0]
    const layer = L.tileLayer(provider.url, {
      subdomains: provider.subdomains ?? 'abc',
      attribution: provider.attribution,
      maxZoom: 19,
    })
    layer.on('tileerror', () => {
      failureCount += 1
      if (failureCount >= TILE_FAILURE_THRESHOLD && providerIndex < BASEMAP_PROVIDERS.length - 1) {
        providerIndex += 1
        failureCount = 0
        const next = createLayer(providerIndex)
        next.addTo(map)
        map.removeLayer(currentLayer)
        currentLayer = next
      }
    })
    return layer
  }
}
