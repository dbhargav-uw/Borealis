import { Cartesian3, Color, Entity as CesiumEntity, PolygonHierarchy, type Viewer } from 'cesium'

import type { Alert } from '../lib/api'

// LIVE / OBSERVED NWS tornado warning + watch polygons on the global map. The official warning palette
// (warning red, watch amber) — categorically distinct from the illustrative grey funnel sim, which stays
// building-anchored. NO funnel is ever drawn on the global map. Entity ids are `live-alert-*` so the
// sim's `hazard-tornado-*` dispose path never collides. Pure Entity polygons (no shader / ground worker).

export interface LiveAlertsHandle {
  dispose: () => void
}

const WARNING = Color.fromCssColorString('#ff3b30')
const WATCH = Color.fromCssColorString('#ffcc00')

function isWarning(alert: Alert): boolean {
  return alert.event.toLowerCase().includes('warning')
}

// Outer rings (lon/lat) of a GeoJSON Polygon | MultiPolygon; [] for anything else (e.g. zone-only watch).
function outerRings(geometry: Alert['geometry']): number[][][] {
  if (!geometry) return []
  const coords = geometry.coordinates
  if (geometry.type === 'Polygon' && Array.isArray(coords)) {
    const first = (coords as number[][][])[0]
    return first ? [first] : []
  }
  if (geometry.type === 'MultiPolygon' && Array.isArray(coords)) {
    return (coords as number[][][][])
      .map((poly) => poly[0])
      .filter((ring): ring is number[][] => Array.isArray(ring))
  }
  return []
}

function ringToPositions(ring: number[][]): Cartesian3[] {
  const flat: number[] = []
  for (const pair of ring) {
    const lon = pair[0]
    const lat = pair[1]
    if (typeof lon === 'number' && typeof lat === 'number') flat.push(lon, lat) // GeoJSON is [lon, lat]
  }
  return Cartesian3.fromDegreesArray(flat)
}

export function addAlerts(viewer: Viewer, alerts: Alert[]): LiveAlertsHandle {
  const entities: CesiumEntity[] = []
  alerts.forEach((alert, i) => {
    const warning = isWarning(alert)
    const color = warning ? WARNING : WATCH
    outerRings(alert.geometry).forEach((ring, j) => {
      if (ring.length < 3) return
      entities.push(
        viewer.entities.add(
          new CesiumEntity({
            id: `live-alert-${i}-${j}`, // numeric alert index → resolved on click via the data ref
            polygon: {
              hierarchy: new PolygonHierarchy(ringToPositions(ring)),
              material: color.withAlpha(warning ? 0.24 : 0.16),
              outline: true,
              outlineColor: color.withAlpha(0.95),
              height: 0,
            },
          }),
        ),
      )
    })
  })
  return {
    dispose: (): void => {
      for (const e of entities) viewer.entities.remove(e)
    },
  }
}
