/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Cesium ion token for premium Bing World Imagery + World Terrain (optional; offline fallback). */
  readonly VITE_CESIUM_ION_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
