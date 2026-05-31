// Curated CC0 glTF building library + type→model mapping + real-world sizing.
// The placed building is a REPRESENTATIVE detailed model of the parsed building TYPE (not the
// actual structure on the parcel); see public/models/ATTRIBUTIONS.md. A sensible default model
// + height-driven scaling covers any unmatched type. Native heights are the model's Y extent
// (model units treated as metres for scaling), measured from each glb's POSITION bounds.

export interface BuildingModelDef {
  key: string
  url: string
  nativeHeightM: number // model's native height (Y extent, model units)
  nativeBaseY: number // model's native min.y (origin offset from its base; ~0 if base-aligned)
  defaultHeightM: number // target real-world height when the parse gives no floors/height
  label: string
}

const MODELS: Record<string, BuildingModelDef> = {
  house: { key: 'house', url: '/models/house.glb', nativeHeightM: 1.42, nativeBaseY: 0, defaultHeightM: 9, label: 'House' },
  hospital: { key: 'hospital', url: '/models/hospital.glb', nativeHeightM: 4.75, nativeBaseY: 0, defaultHeightM: 30, label: 'Hospital' },
  office_tower: { key: 'office_tower', url: '/models/office_tower.glb', nativeHeightM: 2.92, nativeBaseY: 0, defaultHeightM: 140, label: 'Office tower' },
  residential_tower: { key: 'residential_tower', url: '/models/residential_tower.glb', nativeHeightM: 3.17, nativeBaseY: 0, defaultHeightM: 90, label: 'Residential tower' },
  warehouse: { key: 'warehouse', url: '/models/warehouse.glb', nativeHeightM: 8.2, nativeBaseY: -1, defaultHeightM: 14, label: 'Warehouse' },
  mid_rise: { key: 'mid_rise', url: '/models/mid_rise.glb', nativeHeightM: 1.4, nativeBaseY: 0, defaultHeightM: 24, label: 'Mid-rise' },
}

const DEFAULT_KEY = 'mid_rise'
const METRES_PER_FLOOR = 3.3

// Energy infrastructure (rendered as an array / cluster, NOT a single building) — see ResourceGlobe.
export type ModelKind = 'building' | 'solar' | 'wind'
export const SOLAR_PANEL_URL = '/models/solar_panel.glb' // CC-BY flat 2×2 m PV panel (tiled into a tilted array)
export const TURBINE_URL = '/models/turbine.glb' // procedural 3-blade HAWT; node "rotor" spins about local +Z
export const TURBINE_NATIVE_H = 10.2 // tower+hub height in model units (scale = target hub height / this)

// Pick the placement KIND from the parsed building type (solar farm / wind farm → infrastructure).
export function modelKind(buildingType: string): ModelKind {
  const s = buildingType.toLowerCase()
  if (/solar|photovoltaic|\bpv\b|\bpanel/.test(s)) return 'solar'
  if (/wind|turbine/.test(s)) return 'wind'
  return 'building'
}

// Map a free-text parsed building type to a model key (most specific first).
function typeToKey(buildingType: string): string {
  const s = buildingType.toLowerCase()
  if (/hospital|clinic|medical|health|infirmary/.test(s)) return 'hospital'
  if (/warehouse|factory|industrial|\bplant\b|data ?cent|distribution|logistics|depot/.test(s)) return 'warehouse'
  if (/office|corporate|headquarters|\bhq\b|\bbank\b|skyscraper|business/.test(s)) return 'office_tower'
  if (/apartment|residential|condo|\bflat\b|high.?rise|dorm|hotel|\btower\b/.test(s)) return 'residential_tower'
  if (/house|home|cottage|bungalow|villa|cabin|residence/.test(s)) return 'house'
  // school/civic/retail/generic -> the mid-rise default
  return DEFAULT_KEY
}

export interface BuildingSpecInput {
  buildingType: string
  approxFloors?: number | null
  heightM?: number | null
  footprintM?: number | null
}

export interface PickedModel {
  key: string
  url: string
  label: string
  scale: number // uniform scale to reach targetHeightM
  targetHeightM: number
  baseOffsetM: number // add to the terrain height so the model's base rests on the ground
}

// Pick the best library model for a parsed spec and compute its uniform scale to a real-world height.
export function pickBuildingModel(spec: BuildingSpecInput): PickedModel {
  const def = MODELS[typeToKey(spec.buildingType)] ?? MODELS[DEFAULT_KEY]!
  const fromFloors = spec.approxFloors && spec.approxFloors > 0 ? spec.approxFloors * METRES_PER_FLOOR : null
  const target = spec.heightM ?? fromFloors ?? def.defaultHeightM
  // Clamp to a sane real-world building range so a wild parse can't produce a degenerate model.
  const targetHeightM = Math.max(4, Math.min(650, target))
  const scale = targetHeightM / def.nativeHeightM
  return { key: def.key, url: def.url, label: def.label, scale, targetHeightM, baseOffsetM: -def.nativeBaseY * scale }
}
