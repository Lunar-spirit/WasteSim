import type { Map as MaplibreMap, StyleSpecification } from 'maplibre-gl'

// Primary basemap: CARTO's free, keyless Positron vector style. Verified
// live (curl) to still resolve a real style.json with working vector tile
// sources — unlike CARTO's separate raster basemaps.cartocdn.com/{z}/{x}/{y}
// endpoint, which now returns a 200 OK "API KEY REQUIRED" watermark image
// instead of an error, so a tile-error-counting fallback would never even
// see it as a failure. This vector style is a different CARTO product and
// was confirmed to still serve real tiles.
export const PRIMARY_STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

// Fallback basemap if the primary ever can't be reached: plain OpenStreetMap
// raster tiles, specified inline (no network round-trip needed to resolve
// the style itself) so it can always be applied synchronously.
export const BASE_RASTER_STYLE: StyleSpecification = {
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

// A style load that's genuinely going to succeed resolves in well under
// this on any real connection — a vector style's sprite/glyphs are a
// handful of small requests. Past this, something is stuck (not
// necessarily failed: a request that hangs with no response at all fires
// no 'error' event for the fallback below to catch).
const STYLE_LOAD_TIMEOUT_MS = 6000

/**
 * Watches a map created with `style: PRIMARY_STYLE_URL` for a style that
 * fails OR simply never finishes loading, and swaps it to the always-
 * available OSM raster style exactly once, so a flaky primary basemap
 * degrades to "a working map with a different look" rather than a
 * permanently blank canvas. Two triggers, because a blocked/hanging
 * request (no response ever arrives — not a CORS rejection or a 404) fires
 * neither MapLibre's 'error' event nor its own load timeout. `onFallback`
 * runs once the fallback style has finished loading — callers that draw
 * their own sources/layers on top of the basemap (boundary overlays,
 * draw-rectangle previews, ...) need it to re-add them, since swapping
 * styles clears every source but the new ones.
 */
export function attachBasemapFallback(map: MaplibreMap, onFallback?: () => void): void {
  let fellBack = false
  const fallBack = () => {
    if (fellBack) return
    fellBack = true
    map.setStyle(BASE_RASTER_STYLE)
    if (onFallback) map.once('load', onFallback)
  }

  map.on('error', fallBack)
  const timer = window.setTimeout(() => {
    if (!map.isStyleLoaded()) fallBack()
  }, STYLE_LOAD_TIMEOUT_MS)
  map.once('load', () => window.clearTimeout(timer))
}
