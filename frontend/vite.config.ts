import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies the backend so the frontend can call /health and /api
// same-origin (no CORS dance in dev). Backend runs on :8000.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
