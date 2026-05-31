import {
  CallbackPositionProperty,
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Color,
  ConeEmitter,
  Entity as CesiumEntity,
  Math as CesiumMath,
  Matrix4,
  ParticleSystem,
  Quaternion,
  Transforms,
  type Particle,
  type PositionProperty,
  type Property,
  type Viewer,
} from 'cesium'

// An ILLUSTRATIVE tornado: a LAYERED particle vortex (condensation funnel + swirling/flying debris + a
// dust cloud at the base) descending from a darkened storm-cloud base, drifting along a visualized ground
// track. Its size/intensity is scaled by the EF rating from REAL NOAA SPC regional climatology (passed
// in). NOT a physics simulation.

export interface TornadoOpts {
  lat: number
  lng: number
  baseHeight: number
  intensity: number // EF 0..5
}

export interface TornadoHandle {
  dispose: () => void
}

// reusable scratch vectors (no per-particle / per-frame allocation in the render loop)
const _radial = new Cartesian3()
const _up = new Cartesian3()
const _vert = new Cartesian3()
const _horiz = new Cartesian3()
const _radialDir = new Cartesian3()
const _tangential = new Cartesian3()
const _tmp = new Cartesian3()
const _u = new Cartesian3()

// Forward geodesic on a sphere: point `distM` metres from (lat,lng) along `bearingDeg`.
function offset(lat: number, lng: number, bearingDeg: number, distM: number): { lat: number; lng: number } {
  const R = 6_371_000
  const br = CesiumMath.toRadians(bearingDeg)
  const la1 = CesiumMath.toRadians(lat)
  const lo1 = CesiumMath.toRadians(lng)
  const dr = distM / R
  const la2 = Math.asin(Math.sin(la1) * Math.cos(dr) + Math.cos(la1) * Math.sin(dr) * Math.cos(br))
  const lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la1), Math.cos(dr) - Math.sin(la1) * Math.sin(la2))
  return { lat: CesiumMath.toDegrees(la2), lng: CesiumMath.toDegrees(lo2) }
}

function particleTexture(inner: string, mid: string): string {
  const c = document.createElement('canvas')
  c.width = 64
  c.height = 64
  const ctx = c.getContext('2d')
  if (ctx) {
    const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32)
    g.addColorStop(0, inner)
    g.addColorStop(0.5, mid)
    g.addColorStop(1, 'rgba(120,122,138,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 64, 64)
  }
  return c.toDataURL('image/png') // a data-URL is the most reliable ParticleSystem image
}

export function startTornado(viewer: Viewer, opts: TornadoOpts): TornadoHandle {
  const ef = Math.max(0, Math.min(5, opts.intensity))
  const funnelRadius = 24 + ef * 12 // metres
  const funnelHeight = 200 + ef * 120 // metres
  const swirlAccel = 70 + ef * 22 // tangential acceleration -> accumulates the visible spin

  // A ground track the funnel travels along (visualized as a damage path). It starts behind the building
  // (SW) and runs ahead (NE); the funnel begins AT the building (track midpoint) and drifts forward.
  const bearing = 48
  const half = 2200 + ef * 900 // metres each side of the building
  const a = offset(opts.lat, opts.lng, bearing + 180, half)
  const b = offset(opts.lat, opts.lng, bearing, half)
  const startCart = Cartesian3.fromDegrees(a.lng, a.lat, opts.baseHeight)
  const endCart = Cartesian3.fromDegrees(b.lng, b.lat, opts.baseHeight)
  const total = half * 2
  const forwardSpeed = 4 + ef * 1.5 // m/s of forward drift (visual; slow enough to stay framed)
  let traveled = total * 0.5 // begin at the building (midpoint)

  // shared, mutating per-frame state: the funnel centre + its ENU frame.
  const center = Cartesian3.lerp(startCart, endCart, 0.5, new Cartesian3())
  const _mtx = Transforms.eastNorthUpToFixedFrame(center, undefined, new Matrix4())
  let spin = 0

  const onPre = (): void => {
    spin += 0.06
    traveled = Math.min(total, traveled + forwardSpeed / 60) // ~per-frame advance (60fps)
    Cartesian3.lerp(startCart, endCart, traveled / total, center)
    Transforms.eastNorthUpToFixedFrame(center, undefined, _mtx) // both particle systems share this ref
  }
  viewer.scene.preRender.addEventListener(onPre)

  // a point `dist` metres above the (moving) centre along its local vertical.
  const above = (dist: number, result: Cartesian3): Cartesian3 => {
    Cartesian3.normalize(center, _u)
    return Cartesian3.add(center, Cartesian3.multiplyByScalar(_u, dist, _tmp), result)
  }
  const _conePos = new Cartesian3()
  const _cloudPos = new Cartesian3()

  // --- visualized damage track (a polyline at the funnel base; NOT ground-clamped, which would pull in
  // the createGroundPolylineGeometry worker — needlessly heavy and brittle on lazy-loaded assets). The
  // tornado has depthTestAgainstTerrain off, so it draws over the terrain and stays visible. ---
  const track = viewer.entities.add(
    new CesiumEntity({
      id: 'hazard-tornado-track',
      polyline: {
        positions: [startCart, endCart],
        width: 12,
        material: Color.fromCssColorString('#2a1d10').withAlpha(0.8),
      },
    }),
  )

  // --- darkened storm-cloud base above the funnel (the local "storm sky") ---
  const storm = viewer.entities.add(
    new CesiumEntity({
      id: 'hazard-tornado-storm',
      position: new CallbackPositionProperty(() => above(funnelHeight, _cloudPos), false) as unknown as PositionProperty,
      cylinder: {
        length: 70,
        topRadius: funnelRadius * 9,
        bottomRadius: funnelRadius * 7,
        material: Color.fromCssColorString('#23262f').withAlpha(0.62),
        outline: false,
      },
    }),
  )

  // --- translucent funnel CONE — the reliable visible backbone; particle systems add the debris ---
  const cone = viewer.entities.add(
    new CesiumEntity({
      id: 'hazard-tornado-cone',
      position: new CallbackPositionProperty(() => above(funnelHeight / 2, _conePos), false) as unknown as PositionProperty,
      orientation: new CallbackProperty(() => Quaternion.fromAxisAngle(Cartesian3.UNIT_Z, spin), false) as unknown as Property,
      cylinder: {
        length: funnelHeight,
        topRadius: funnelRadius * 1.7,
        bottomRadius: funnelRadius * 0.35,
        material: Color.fromCssColorString('#9a9db0').withAlpha(0.38),
        outline: true,
        outlineColor: Color.fromCssColorString('#c7cad6').withAlpha(0.22),
        numberOfVerticalLines: 16,
      },
    }),
  )

  // --- layer 1: condensation funnel (light, rises, tightens into the column) ---
  const funnel = new ParticleSystem({
    image: particleTexture('rgba(228,231,239,1)', 'rgba(182,185,198,0.7)'),
    startColor: Color.fromCssColorString('#dfe2ea').withAlpha(0.95),
    endColor: Color.fromCssColorString('#8a8d9c').withAlpha(0.0),
    startScale: 1.0,
    endScale: 3.4,
    minimumParticleLife: 3.0,
    maximumParticleLife: 4.5,
    minimumSpeed: 38 + ef * 8,
    maximumSpeed: 58 + ef * 10,
    imageSize: new Cartesian2(26, 26),
    emissionRate: 340 + ef * 110, // capped for perf
    emitter: new ConeEmitter(CesiumMath.toRadians(14)),
    modelMatrix: _mtx,
    updateCallback: (p: Particle, dt: number): void => {
      Cartesian3.subtract(p.position, center, _radial)
      Cartesian3.normalize(center, _up)
      Cartesian3.multiplyByScalar(_up, Cartesian3.dot(_radial, _up), _vert)
      Cartesian3.subtract(_radial, _vert, _horiz)
      const dist = Cartesian3.magnitude(_horiz) || 0.001
      Cartesian3.divideByScalar(_horiz, dist, _radialDir)
      Cartesian3.cross(_up, _radialDir, _tangential)
      Cartesian3.add(p.velocity, Cartesian3.multiplyByScalar(_tangential, swirlAccel * dt, _tmp), p.velocity)
      const pull = -6.0 * dt * Math.max(0, dist - funnelRadius) // tighten toward the column
      Cartesian3.add(p.velocity, Cartesian3.multiplyByScalar(_radialDir, pull, _tmp), p.velocity)
    },
  })
  viewer.scene.primitives.add(funnel)

  // --- layer 2: dust cloud + flying debris (darker/tan, near the base, flung outward, gravity arc) ---
  const debris = new ParticleSystem({
    image: particleTexture('rgba(150,128,96,1)', 'rgba(96,82,62,0.6)'),
    startColor: Color.fromCssColorString('#8a7150').withAlpha(0.85),
    endColor: Color.fromCssColorString('#5a4c38').withAlpha(0.0),
    startScale: 1.4,
    endScale: 4.6,
    minimumParticleLife: 1.4,
    maximumParticleLife: 2.8,
    minimumSpeed: 12 + ef * 5,
    maximumSpeed: 26 + ef * 8,
    imageSize: new Cartesian2(22, 22),
    emissionRate: 170 + ef * 70, // capped for perf
    emitter: new ConeEmitter(CesiumMath.toRadians(36)), // wide -> spreads as a low dust cloud
    modelMatrix: _mtx,
    updateCallback: (p: Particle, dt: number): void => {
      Cartesian3.subtract(p.position, center, _radial)
      Cartesian3.normalize(center, _up)
      Cartesian3.multiplyByScalar(_up, Cartesian3.dot(_radial, _up), _vert)
      Cartesian3.subtract(_radial, _vert, _horiz)
      const dist = Cartesian3.magnitude(_horiz) || 0.001
      Cartesian3.divideByScalar(_horiz, dist, _radialDir)
      Cartesian3.cross(_up, _radialDir, _tangential)
      Cartesian3.add(p.velocity, Cartesian3.multiplyByScalar(_tangential, swirlAccel * 0.7 * dt, _tmp), p.velocity)
      Cartesian3.add(p.velocity, Cartesian3.multiplyByScalar(_radialDir, 8.0 * dt, _tmp), p.velocity) // fling outward
      Cartesian3.add(p.velocity, Cartesian3.multiplyByScalar(_up, -9.0 * dt, _tmp), p.velocity) // gravity -> debris arcs
    },
  })
  viewer.scene.primitives.add(debris)

  return {
    dispose: (): void => {
      viewer.scene.preRender.removeEventListener(onPre)
      viewer.entities.remove(track)
      viewer.entities.remove(storm)
      viewer.entities.remove(cone)
      viewer.scene.primitives.remove(funnel) // also destroys the system
      viewer.scene.primitives.remove(debris)
    },
  }
}
