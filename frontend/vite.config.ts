import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import cesium from 'vite-plugin-cesium'

// Dev server proxies the backend so the frontend can call /health and /api
// same-origin (no CORS dance in dev). Backend runs on :8000.
// vite-plugin-cesium wires CESIUM_BASE_URL + copies Cesium's Assets/Widgets/Workers.
// https://vite.dev/config/
const proxy = {
  '/health': { target: 'http://localhost:8000', changeOrigin: true },
  '/api': { target: 'http://localhost:8000', changeOrigin: true },
}

export default defineConfig({
  plugins: [react(), cesium()],
  // Pre-bundle the heavy WebGL deps up front so an .env/config edit is less likely to trigger a
  // surprise mid-session re-optimize (which re-hashes dep URLs and 404s an already-open tab).
  optimizeDeps: { include: ['cesium', 'resium'] },
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy }, // `vite preview` (built app) also proxies the backend
})
