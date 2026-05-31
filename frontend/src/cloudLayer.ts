import {
  Cartesian3,
  Color,
  Ellipsoid,
  EllipsoidGeometry,
  GeometryInstance,
  Material,
  MaterialAppearance,
  Matrix3,
  Matrix4,
  Primitive,
  type Viewer,
} from 'cesium'

// A slowly drifting, translucent global cloud layer on a sphere just above the surface. The texture is
// generated procedurally (soft white blobs over transparent), so there's no external asset to fetch. It's
// lit (MaterialAppearance, not flat) so clouds darken across the day/night terminator like the earth below.

export interface CloudLayerHandle {
  rotate: (rad: number) => void
  dispose: () => void
}

function makeCloudTexture(): string {
  const w = 2048
  const h = 1024
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d')
  if (!ctx) return c.toDataURL('image/png')
  ctx.clearRect(0, 0, w, h)
  const blob = (x: number, y: number, r: number, a: number): void => {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, `rgba(255,255,255,${a})`)
    g.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  }
  // Sparse, faint wisps — the earth must read clearly through the layer (no grey blanket).
  for (let i = 0; i < 240; i++) {
    const x = Math.random() * w
    // bias toward mid-latitude cloud bands; keep the equator and poles clearer
    const lat = Math.random()
    const y = (0.18 + lat * 0.64) * h
    const r = 10 + Math.random() * 34
    const a = 0.03 + Math.random() * 0.06
    blob(x, y, r, a)
    if (x < 60) blob(x + w, y, r, a) // wrap across the antimeridian so the band is seamless
    if (x > w - 60) blob(x - w, y, r, a)
  }
  return c.toDataURL('image/png')
}

export function addCloudLayer(viewer: Viewer): CloudLayerHandle {
  const radii = Cartesian3.multiplyByScalar(Ellipsoid.WGS84.radii, 1.004, new Cartesian3()) // ~25 km up
  const sphere = new Primitive({
    geometryInstances: new GeometryInstance({
      geometry: new EllipsoidGeometry({
        radii,
        vertexFormat: MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat,
      }),
    }),
    appearance: new MaterialAppearance({
      material: Material.fromType('Image', {
        image: makeCloudTexture(),
        color: new Color(1, 1, 1, 0.38),
      }),
      translucent: true,
      closed: true, // backface-cull so the far hemisphere's clouds don't show through the globe
    }),
    asynchronous: false,
  })
  viewer.scene.primitives.add(sphere)

  let angle = 0
  const rot = new Matrix3()
  return {
    rotate: (rad: number): void => {
      angle += rad
      Matrix4.fromRotationTranslation(Matrix3.fromRotationZ(angle, rot), Cartesian3.ZERO, sphere.modelMatrix)
    },
    dispose: (): void => {
      viewer.scene.primitives.remove(sphere) // also destroys the primitive + material
    },
  }
}
