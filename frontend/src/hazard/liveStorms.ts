import {
  Cartesian2,
  Cartesian3,
  CallbackProperty,
  Color,
  Entity as CesiumEntity,
  ImageMaterialProperty,
  LabelStyle,
  NearFarScalar,
  type Property,
  VerticalOrigin,
  type Viewer,
} from 'cesium'

import type { Storm } from '../lib/api'

// LIVE / OBSERVED NHC tropical cyclones rendered as a GEOREFERENCED spiral CLOUD draped on the globe at
// each storm's REAL CURRENT position (static — refreshed only on the data poll; the only motion is a slow
// in-place swirl). Each storm = a layered pair of ground-clamped ellipses (faint outer canopy + denser
// inner core with an eye for Cat 3+), textured with a procedural near-white cloud + a soft DARK feathered
// rim so it reads on BOTH bright daytime imagery and the dark night side (not additive/glow-only). Sized to
// an approximate wind-field radius (the scalar feed has NO real radii — size is a documented category proxy).
// OBSERVATIONAL, never the illustrative sim. Clickable entity id is `live-storm-<index>`. Past/forecast TRACK
// + cone are a deferred fast-follow (the feed has no track geometry — never fabricated).

export interface LiveStormsHandle {
  dispose: () => void
}

// Subtle naturalistic category accent (rim/label only — never tints the whole cloud). TS(0) → Cat 5.
const CAT_COLORS = ['#bfe0ff', '#9fe9d6', '#ffe89c', '#ffc888', '#ff9b8e', '#ff7fae']
function catColor(cat: number): Color {
  return Color.fromCssColorString(CAT_COLORS[Math.max(0, Math.min(5, cat))] ?? '#bfe0ff')
}
function catLabel(cat: number): string {
  return cat >= 1 ? `Cat ${cat}` : 'TS'
}
// Approximate wind-field radius (metres). DOCUMENTED approximation — CurrentStorms.json carries no wind radii.
function radiusM(cat: number): number {
  return (135 + Math.max(0, Math.min(5, cat)) * 47) * 1000 // ~135 km (TS) → ~370 km (Cat 5)
}

const TAU = Math.PI * 2

// Draw soft, feathered spiral cloud bands centered at the canvas origin.
function drawSpiral(
  ctx: CanvasRenderingContext2D,
  opts: { arms: number; turns: number; rInner: number; rOuter: number; width: number; alpha: number },
): void {
  const { arms, turns, rInner, rOuter, width, alpha } = opts
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.shadowColor = `rgba(255,255,255,${alpha * 0.5})`
  ctx.shadowBlur = 8
  const grad = ctx.createRadialGradient(0, 0, rInner, 0, 0, rOuter)
  grad.addColorStop(0, `rgba(255,255,255,${alpha})`)
  grad.addColorStop(0.6, `rgba(242,247,255,${alpha * 0.85})`)
  grad.addColorStop(1, `rgba(220,230,245,${alpha * 0.12})`) // fade to nothing at the rim
  ctx.strokeStyle = grad
  ctx.lineWidth = width
  for (let a = 0; a < arms; a++) {
    const rot = (a / arms) * TAU
    ctx.beginPath()
    for (let t = 0; t <= 1.0001; t += 0.012) {
      const ang = rot + t * Math.PI * 2 * turns
      const r = rInner + t * (rOuter - rInner)
      const x = Math.cos(ang) * r
      const y = Math.sin(ang) * r
      if (t === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }
  ctx.shadowBlur = 0
}

// Faint, broad outer canopy + a soft DARK feathered rim (the daytime-contrast halo, drawn UNDER the cloud).
function cloudOuter(): string {
  const s = 512
  const R = s / 2
  const c = document.createElement('canvas')
  c.width = s
  c.height = s
  const ctx = c.getContext('2d')
  if (!ctx) return c.toDataURL('image/png')
  ctx.translate(R, R)
  // soft dark halo ring (under) — separates the cloud edge from bright terrain in daylight
  const halo = ctx.createRadialGradient(0, 0, 0, 0, 0, R)
  halo.addColorStop(0.0, 'rgba(8,12,22,0)')
  halo.addColorStop(0.5, 'rgba(8,12,22,0.10)')
  halo.addColorStop(0.82, 'rgba(8,12,22,0.34)')
  halo.addColorStop(0.95, 'rgba(8,12,22,0.16)')
  halo.addColorStop(1.0, 'rgba(8,12,22,0)')
  ctx.fillStyle = halo
  ctx.beginPath()
  ctx.arc(0, 0, R, 0, TAU)
  ctx.fill()
  // faint broad spiral canopy on top
  drawSpiral(ctx, { arms: 5, turns: 1.15, rInner: 18, rOuter: R - 10, width: 22, alpha: 0.42 })
  return c.toDataURL('image/png')
}

// Denser inner core: brighter banded spiral + a visible EYE (Cat 3+) or soft bright core, + category rim.
function cloudInner(cat: number): string {
  const s = 512
  const R = s / 2
  const c = document.createElement('canvas')
  c.width = s
  c.height = s
  const ctx = c.getContext('2d')
  if (!ctx) return c.toDataURL('image/png')
  ctx.translate(R, R)
  const strong = cat >= 3
  // soft dark backing so the bright core pops on bright imagery
  const back = ctx.createRadialGradient(0, 0, 0, 0, 0, R)
  back.addColorStop(0.0, 'rgba(8,12,22,0.16)')
  back.addColorStop(0.7, 'rgba(8,12,22,0.30)')
  back.addColorStop(1.0, 'rgba(8,12,22,0)')
  ctx.fillStyle = back
  ctx.beginPath()
  ctx.arc(0, 0, R, 0, TAU)
  ctx.fill()
  // dense banded spiral
  drawSpiral(ctx, { arms: strong ? 4 : 3, turns: 1.6, rInner: strong ? 40 : 16, rOuter: R - 14, width: 26, alpha: 0.92 })
  // eye / core
  if (strong) {
    ctx.strokeStyle = 'rgba(255,255,255,0.96)' // bright eyewall
    ctx.lineWidth = 12
    ctx.beginPath()
    ctx.arc(0, 0, 34, 0, TAU)
    ctx.stroke()
    const eye = ctx.createRadialGradient(0, 0, 0, 0, 0, 28) // dark calm eye
    eye.addColorStop(0, 'rgba(6,10,18,0.92)')
    eye.addColorStop(1, 'rgba(6,10,18,0)')
    ctx.fillStyle = eye
    ctx.beginPath()
    ctx.arc(0, 0, 28, 0, TAU)
    ctx.fill()
  } else {
    const core = ctx.createRadialGradient(0, 0, 0, 0, 0, 30)
    core.addColorStop(0, 'rgba(255,255,255,0.95)')
    core.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = core
    ctx.beginPath()
    ctx.arc(0, 0, 30, 0, TAU)
    ctx.fill()
  }
  // subtle category rim tint
  ctx.strokeStyle = catColor(cat).withAlpha(0.5).toCssColorString()
  ctx.lineWidth = 6
  ctx.beginPath()
  ctx.arc(0, 0, R - 10, 0, TAU)
  ctx.stroke()
  return c.toDataURL('image/png')
}

// Textures baked ONCE (outer is category-independent; inner varies by eye/rim). No per-frame/per-storm canvas.
const OUTER = cloudOuter()
const INNER: string[] = [0, 1, 2, 3, 4, 5].map(cloudInner)

// Reused scratch (no per-frame allocation) for the near-hemisphere visibility test.
const _toCam = new Cartesian3()

export function addStorms(viewer: Viewer, storms: Storm[]): LiveStormsHandle {
  // The ONLY motion: a slow in-place swirl (storms stay at their real, static position between polls).
  let spin = 0
  const onPre = (): void => {
    spin += 0.0035 // gentle local rotation
  }
  viewer.scene.preRender.addEventListener(onPre)

  const entities: CesiumEntity[] = []
  storms.forEach((s, i) => {
    const pos = Cartesian3.fromDegrees(s.lng, s.lat)
    const normal = Cartesian3.normalize(pos, new Cartesian3()) // outward normal at the storm (constant)
    const sense = s.lat >= 0 ? 1 : -1 // N hemisphere spins counter-clockwise, S clockwise
    const visible = (): boolean => {
      Cartesian3.subtract(viewer.camera.positionWC, pos, _toCam)
      return Cartesian3.dot(normal, _toCam) > 0 // hide the far-side storm entirely
    }
    const R = radiusM(s.category)
    const idx = Math.max(0, Math.min(5, s.category))

    // Main (clickable) entity: faint outer cloud canopy + exact-position marker + label.
    entities.push(
      viewer.entities.add(
        new CesiumEntity({
          id: `live-storm-${i}`,
          position: pos,
          show: new CallbackProperty(visible, false) as unknown as boolean,
          ellipse: {
            semiMajorAxis: R,
            semiMinorAxis: R,
            height: 3000, // just above the sea so it drapes cleanly; far side occluded by the globe
            material: new ImageMaterialProperty({ image: OUTER, transparent: true, color: Color.WHITE }),
            stRotation: new CallbackProperty(() => spin * sense, false) as unknown as Property,
          },
          point: {
            pixelSize: 4,
            color: Color.WHITE.withAlpha(0.9),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: `🌀 ${s.name} · ${catLabel(s.category)}`,
            font: '600 13px Inter, system-ui, sans-serif',
            fillColor: Color.WHITE,
            style: LabelStyle.FILL_AND_OUTLINE,
            outlineColor: Color.fromCssColorString('#05070f'),
            outlineWidth: 3,
            verticalOrigin: VerticalOrigin.TOP,
            pixelOffset: new Cartesian2(0, 16),
            showBackground: true,
            backgroundColor: Color.fromCssColorString('#0b1020').withAlpha(0.72),
            backgroundPadding: new Cartesian2(6, 4),
            translucencyByDistance: new NearFarScalar(6.0e6, 1.0, 3.0e7, 0.0),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        }),
      ),
    )

    // Denser inner core (non-clickable): a slightly faster swirl for parallax/depth.
    entities.push(
      viewer.entities.add(
        new CesiumEntity({
          id: `live-cloud-${i}`,
          position: pos,
          show: new CallbackProperty(visible, false) as unknown as boolean,
          ellipse: {
            semiMajorAxis: R * 0.5,
            semiMinorAxis: R * 0.5,
            height: 3500,
            material: new ImageMaterialProperty({ image: INNER[idx], transparent: true, color: Color.WHITE }),
            stRotation: new CallbackProperty(() => spin * sense * 1.35, false) as unknown as Property,
          },
        }),
      ),
    )
  })

  return {
    dispose: (): void => {
      viewer.scene.preRender.removeEventListener(onPre)
      for (const e of entities) viewer.entities.remove(e)
    },
  }
}
