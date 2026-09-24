import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
  },
  // maplibre-gl spins up its own Web Worker internally, constructing the
  // worker's URL relative to its own module. Vite's dependency
  // pre-bundling rewrites that module into .vite/deps/maplibre-gl.js,
  // which breaks that relative URL ("Worker failed to load", found live
  // in the browser) — excluding it from pre-bundling serves it straight
  // from node_modules as native ESM instead, where the URL resolves correctly.
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
})
