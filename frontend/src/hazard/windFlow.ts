import type { Viewer } from 'cesium'
import { WindLayer, type WindData, type WindLayerOptions } from 'cesium-wind-layer'

import type { GridWind } from '../lib/api'

// LIVE / OBSERVED global wind, rendered as nullschool-style flowing STREAMLINES via a TRUE GPU pipeline
// (cesium-wind-layer): particle state lives in a texture and is advanced in a fragment shader that samples
// the wind UV texture, trails accumulate in ping-pong FRAMEBUFFERS (cost O(screen), independent of particle
// count), and the whole field is one batched CustomPrimitive draw — no per-particle JS, no per-frame buffer
// rebuilds, no per-particle entities. Density is therefore cheap (= particlesTextureSize²). The wind UV
// texture is uploaded once here (per data poll, when the prop changes); `useViewerBounds` culls off-screen /
// back-hemisphere particles; the layer pauses when the tab is hidden. Direction + speed are REAL; only the
// drift is animated. Distinct from the illustrative sim.

export interface WindFlowHandle {
  dispose: () => void
}

// Density: particles = size². 192 → ~37k particles — a thick nullschool field, still cheap on the GPU.
const PARTICLES_TEXTURE_SIZE = 192
// Speed colormap (fully opaque, bright across the whole range so even slow particles read in daylight):
// turquoise → green → yellow → white. Lifted off the near-black low end that was invisible on bright Bing.
const COLORS = ['rgba(64,224,208,1)', 'rgba(91,227,122,1)', 'rgba(173,236,80,1)', 'rgba(255,227,77,1)', 'rgba(255,255,255,1)']

function minMax(a: number[]): { min: number; max: number } {
  let min = Infinity
  let max = -Infinity
  for (const x of a) {
    if (x < min) min = x
    if (x > max) max = x
  }
  return { min, max }
}

// Reshape the Open-Meteo GridWind (row-major, row 0 = north) into cesium-wind-layer's WindData.
function toWindData(grid: GridWind): WindData {
  const [latMin, lonMin, latMax, lonMax] = grid.bbox
  return {
    u: { array: Float32Array.from(grid.u), ...minMax(grid.u) },
    v: { array: Float32Array.from(grid.v), ...minMax(grid.v) },
    speed: { array: Float32Array.from(grid.speed), ...minMax(grid.speed) },
    width: grid.nx,
    height: grid.ny,
    bounds: { west: lonMin, south: latMin, east: lonMax, north: latMax },
  }
}

const OPTIONS: Partial<WindLayerOptions> = {
  particlesTextureSize: PARTICLES_TEXTURE_SIZE,
  lineWidth: { min: 3, max: 9 }, // MUCH bigger particles so they read in daylight
  lineLength: { min: 80, max: 300 }, // slightly longer trails
  speedFactor: 0.8,
  dropRate: 0.003,
  dropRateBump: 0.002,
  colors: COLORS,
  flipY: false, // grid row 0 = north; flip here if the field ever renders inverted
  useViewerBounds: true, // only advect/draw particles within the visible viewport (back-hemisphere cull)
  dynamic: true,
}

export function addWindFlow(viewer: Viewer, grid: GridWind): WindFlowHandle {
  // Constructor builds the GPU pipeline and adds it to the scene; the UV texture is uploaded once here.
  const layer = new WindLayer(viewer, toWindData(grid), OPTIONS)

  // Pause GPU work when the tab is hidden (no point advecting an unseen field).
  const onVisibility = (): void => {
    if (!layer.isDestroyed()) layer.show = !document.hidden
  }
  document.addEventListener('visibilitychange', onVisibility)
  onVisibility()

  return {
    dispose: (): void => {
      document.removeEventListener('visibilitychange', onVisibility)
      if (!layer.isDestroyed()) layer.destroy() // releases textures / framebuffers / primitive
    },
  }
}
