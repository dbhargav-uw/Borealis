import {
  buildModuleUrl,
  Cartesian3,
  Cartographic,
  Color,
  EllipseGeometry,
  EllipsoidSurfaceAppearance,
  GeometryInstance,
  Material,
  Matrix4,
  Primitive,
  sampleTerrainMostDetailed,
  type Viewer,
} from 'cesium'

// Bathtub inundation: a Cesium Water-material surface raised over the REAL terrain. With
// scene.globe.depthTestAgainstTerrain on, terrain higher than the water OCCLUDES it, so the wetted
// extent follows real elevation — the standard simplified, honest flood model. ILLUSTRATIVE, not a
// hydrodynamic simulation.

export interface FloodOpts {
  lat: number
  lng: number
  baseHeight: number // terrain elevation at the building (m)
  level: number // metres of water above the building base
  radiusM?: number
}

export interface FloodStats {
  depthAtBuilding: number // m of water over the building base
  submergedPct: number // % of the disc whose terrain is below the water level (0..100)
}

export interface FloodHandle {
  dispose: () => void
  setLevel: (level: number) => void
}

const _up = new Cartesian3()
const _t = new Cartesian3()

export function startFlood(viewer: Viewer, opts: FloodOpts): FloodHandle {
  viewer.scene.globe.depthTestAgainstTerrain = true
  const radius = opts.radiusM ?? 7000
  const ground = Cartesian3.fromDegrees(opts.lng, opts.lat, opts.baseHeight)
  Cartesian3.normalize(ground, _up)
  let current = 0 // metres risen above the building base
  let target = opts.level

  const water = new Primitive({
    geometryInstances: new GeometryInstance({
      geometry: new EllipseGeometry({
        center: Cartesian3.fromDegrees(opts.lng, opts.lat, opts.baseHeight),
        semiMajorAxis: radius,
        semiMinorAxis: radius,
        vertexFormat: EllipsoidSurfaceAppearance.VERTEX_FORMAT,
      }),
    }),
    appearance: new EllipsoidSurfaceAppearance({
      translucent: true,
      material: Material.fromType('Water', {
        baseWaterColor: new Color(0.1, 0.36, 0.56, 0.82),
        blendColor: new Color(0.04, 0.22, 0.4, 0.9),
        normalMap: buildModuleUrl('Assets/Textures/waterNormals.jpg'),
        frequency: 3800.0,
        animationSpeed: 0.025,
        amplitude: 4.0,
        specularIntensity: 0.7,
      }),
    }),
    asynchronous: false,
  })
  water.show = false
  viewer.scene.primitives.add(water)

  // eased rise: translate the disc up the local vertical each frame (cheap; no geometry rebuild).
  const onPre = (): void => {
    current += (target - current) * 0.05
    Cartesian3.multiplyByScalar(_up, current, _t)
    Matrix4.fromTranslation(_t, water.modelMatrix)
    water.show = true
  }
  viewer.scene.preRender.addEventListener(onPre)

  return {
    dispose: (): void => {
      viewer.scene.preRender.removeEventListener(onPre)
      viewer.scene.primitives.remove(water) // destroys the primitive
      viewer.scene.globe.depthTestAgainstTerrain = false
    },
    setLevel: (level: number): void => {
      target = level
    },
  }
}

// Sample terrain on a grid across the disc to estimate the submerged extent at a given water level.
export async function floodStats(viewer: Viewer, opts: FloodOpts): Promise<FloodStats> {
  const waterH = opts.baseHeight + opts.level
  const radius = opts.radiusM ?? 7000
  const dDeg = radius / 111_320 // ~metres per degree
  const samples: Cartographic[] = []
  const N = 11
  for (let a = 0; a < N; a++) {
    for (let b = 0; b < N; b++) {
      const dx = (a / (N - 1) - 0.5) * 2 * dDeg
      const dy = (b / (N - 1) - 0.5) * 2 * dDeg
      if (dx * dx + dy * dy <= dDeg * dDeg) {
        samples.push(Cartographic.fromDegrees(opts.lng + dx, opts.lat + dy))
      }
    }
  }
  let submerged = 0
  try {
    const out = await sampleTerrainMostDetailed(viewer.terrainProvider, samples)
    for (const c of out) if ((c.height ?? 0) < waterH) submerged += 1
  } catch {
    return { depthAtBuilding: opts.level, submergedPct: 0 }
  }
  return {
    depthAtBuilding: opts.level,
    submergedPct: samples.length ? Math.round((submerged / samples.length) * 100) : 0,
  }
}
