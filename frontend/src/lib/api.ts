// Typed client for the Borealis site-selection API. Drives a generic set of LAYERS
// (solar/wind = energy vertical, cropland = agriculture vertical). Each layer is one
// /api/suitability call; the frontend merges them so toggling between layers is instant +
// offline. Backend lat/lon -> globe lat/lng is mapped at this boundary. Zod-validated.

import { z } from 'zod'

export type Lens = 'solar' | 'wind'

export interface LayerDef {
  id: string
  label: string
  name: string
  vertical: string
  params: Record<string, string>
  accent: string // hex
  metricKey: string
  metricLabel: string
  seasonalVar: string // NASA POWER param for the per-site seasonal sparkline
}

export const LAYERS: LayerDef[] = [
  { id: 'solar', label: '☀ Solar', name: 'solar', vertical: 'energy', params: { lens: 'solar' }, accent: '#ffd140', metricKey: 'specific_yield_kwh_kwp_yr', metricLabel: 'Specific yield', seasonalVar: 'ALLSKY_SFC_SW_DWN' },
  { id: 'wind', label: '🌀 Wind', name: 'wind', vertical: 'energy', params: { lens: 'wind' }, accent: '#4ed6ff', metricKey: 'wind_power_density_wm2', metricLabel: 'Wind power density', seasonalVar: 'WS50M' },
  { id: 'cropland', label: '🌱 Cropland', name: 'cropland', vertical: 'agriculture', params: {}, accent: '#7ce38b', metricKey: 'growing_degree_days', metricLabel: 'Growing-degree-days', seasonalVar: 'T2M' },
]

export interface Region {
  lat_min: number
  lon_min: number
  lat_max: number
  lon_max: number
}

export interface SuitabilityCell {
  lat: number
  lng: number
  scores: Record<string, number> // layer id -> 0..1 score
}

export interface RankedSite {
  rank: number
  lat: number
  lng: number
  score: number
  metrics: Record<string, number>
  caveats: string[]
}

export interface SuitabilityData {
  region: Region
  cells: SuitabilityCell[]
  sites: Record<string, RankedSite[]>
  units: Record<string, string>
}

const cellSchema = z.object({
  lat: z.number(),
  lon: z.number(),
  score: z.number(),
  metrics: z.record(z.string(), z.number()),
})

const rankedSchema = z.object({
  rank: z.number(),
  lat: z.number(),
  lon: z.number(),
  score: z.number(),
  metrics: z.record(z.string(), z.number()),
  caveats: z.array(z.string()),
})

const responseSchema = z.object({
  metric_units: z.string(),
  cells: z.array(cellSchema),
  ranked_sites: z.array(rankedSchema),
})

type LayerResponse = z.infer<typeof responseSchema>
type RankedRaw = z.infer<typeof rankedSchema>

function toSite(s: RankedRaw): RankedSite {
  return { rank: s.rank, lat: s.lat, lng: s.lon, score: s.score, metrics: s.metrics, caveats: s.caveats }
}

async function fetchLayer(region: Region, layer: LayerDef, landOnly: boolean, briefing = false, regionLabel = ''): Promise<unknown> {
  const res = await fetch('/api/suitability', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vertical: layer.vertical,
      region,
      resolution: 0.5,
      params: layer.params,
      top_n: 5,
      land_only: landOnly,
      include_briefing: briefing,
      region_label: regionLabel,
    }),
  })
  if (!res.ok) throw new Error(`Suitability request failed (${res.status})`)
  return res.json()
}

export async function fetchSuitability(region: Region, landOnly = true): Promise<SuitabilityData> {
  const raw = await Promise.all(LAYERS.map((l) => fetchLayer(region, l, landOnly)))
  const responses: LayerResponse[] = raw.map((r) => responseSchema.parse(r))

  const cellMap = new Map<string, SuitabilityCell>()
  const sites: Record<string, RankedSite[]> = {}
  const units: Record<string, string> = {}

  LAYERS.forEach((layer, i) => {
    const r = responses[i]
    if (!r) return
    sites[layer.id] = r.ranked_sites.map(toSite)
    units[layer.id] = r.metric_units
    for (const c of r.cells) {
      const key = `${c.lat},${c.lon}`
      const existing = cellMap.get(key) ?? { lat: c.lat, lng: c.lon, scores: {} }
      existing.scores[layer.id] = c.score
      cellMap.set(key, existing)
    }
  })

  return { region, cells: [...cellMap.values()], sites, units }
}

export function regionCenter(r: Region): { lat: number; lng: number } {
  return { lat: (r.lat_min + r.lat_max) / 2, lng: (r.lon_min + r.lon_max) / 2 }
}

// --- displayed resource field: legend metadata for the baked global textures --------------
// The field PNGs (frontend/public/fields/<lens>.png) are the RAW physical metric on a fixed
// absolute scale; meta.json carries the scale + colormap legend stops for each lens.

export interface FieldMeta {
  id: string
  label: string
  units: string
  vmin: number
  vmax: number
  legend: string[] // hex stops, low -> high
}

const fieldMetaSchema = z.object({
  id: z.string(),
  label: z.string(),
  units: z.string(),
  vmin: z.number(),
  vmax: z.number(),
  legend: z.array(z.string()),
})

const fieldsSchema = z.object({ fields: z.record(z.string(), fieldMetaSchema) })

export async function fetchFieldMeta(): Promise<Record<string, FieldMeta>> {
  const res = await fetch('/fields/meta.json')
  if (!res.ok) return {}
  try {
    const json: unknown = await res.json()
    return fieldsSchema.parse(json).fields
  } catch {
    return {} // field textures not baked yet -> legend falls back to the relative note
  }
}

// --- per-site seasonal climatology profile (detail panel sparkline) -----------------------

export interface Seasonal {
  variable: string
  units: string
  months: number[]
}

const seasonalSchema = z.object({
  variable: z.string(),
  units: z.string(),
  months: z.array(z.number()),
})

export async function fetchSeasonal(lat: number, lng: number, variable: string): Promise<Seasonal> {
  const qs = new URLSearchParams({ lat: String(lat), lon: String(lng), variable })
  const res = await fetch(`/api/seasonal?${qs.toString()}`)
  if (!res.ok) throw new Error(`Seasonal request failed (${res.status})`)
  return seasonalSchema.parse(await res.json())
}

// --- Act 2: short-term generation variability for a CHOSEN site -------------------------
// Reuses the shelved operational forecast path (/api/operational/assess): once you've
// picked WHERE to build, see that site's near-term P10/P50/P90 generation fan.

export interface Variability {
  units: string
  p10: number[]
  p50: number[]
  p90: number[]
}

const fanSchema = z.object({
  impact_fan: z.object({
    units: z.string(),
    p10: z.array(z.number()),
    p50: z.array(z.number()),
    p90: z.array(z.number()),
  }),
})

export async function fetchVariability(lat: number, lng: number, layerId: string): Promise<Variability> {
  const params =
    layerId === 'wind'
      ? { kind: 'wind', rated_power_kw: 3000, n_turbines: 10 }
      : { kind: 'solar', dc_capacity_kw: 100000, surface_tilt: 25, surface_azimuth: 180, gamma_pdc: -0.004, system_loss: 0.14, ac_dc_ratio: 1.2 }
  const res = await fetch('/api/operational/assess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vertical: 'energy',
      asset: { name: 'chosen site', lat, lon: lng, vertical: 'energy', params },
      thresholds: [],
      hours: 48,
    }),
  })
  if (!res.ok) throw new Error(`Variability request failed (${res.status})`)
  const json: unknown = await res.json()
  const fan = fanSchema.parse(json).impact_fan
  return { units: fan.units, p10: fan.p10, p50: fan.p50, p90: fan.p90 }
}

// --- "why this site" briefing (on demand; degrades to null without an API key) ---------

export interface SiteBriefing {
  headline: string
  why_top_sites: string
  top_drivers: string[]
  caveats: string[]
  confidence: 'low' | 'medium' | 'high'
}

const briefingSchema = z.object({
  headline: z.string(),
  why_top_sites: z.string(),
  top_drivers: z.array(z.string()),
  caveats: z.array(z.string()),
  confidence: z.enum(['low', 'medium', 'high']),
})

export async function fetchBriefing(region: Region, layer: LayerDef, regionLabel: string, landOnly = true): Promise<SiteBriefing | null> {
  const json = await fetchLayer(region, layer, landOnly, true, regionLabel)
  return z.object({ briefing: briefingSchema.nullable() }).parse(json).briefing
}

// --- "ask the globe" natural-language search -------------------------------------------

export interface AskResult {
  label: string
  region: Region
  lens: Lens
}

const askSchema = z.object({
  label: z.string(),
  region: z.object({ lat_min: z.number(), lon_min: z.number(), lat_max: z.number(), lon_max: z.number() }),
  lens: z.enum(['solar', 'wind']),
})

export async function fetchAsk(query: string): Promise<AskResult> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  if (!res.ok) {
    let message = `Search failed (${res.status})`
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'error' in body) message = String((body as { error: unknown }).error)
    } catch {
      message = `Search failed (${res.status})`
    }
    throw new Error(message)
  }
  const json: unknown = await res.json()
  const parsed = askSchema.parse(json)
  return { label: parsed.label, region: parsed.region, lens: parsed.lens }
}

// --- "place a building" natural-language -> a geocodable place + building + intent --------

export type Intent = 'site-selection' | 'flood' | 'tornado' | 'general'

// Richer building SPEC (all optional) — drives glTF model selection + sizing on the globe.
export interface BuildingSpecMeta {
  approxFloors: number | null
  heightM: number | null
  footprintM: number | null
  style: string | null
  roofType: string | null
  features: string[]
}

export interface PlaceResult extends BuildingSpecMeta {
  label: string
  placeName: string
  buildingType: string
  intent: Intent
}

const placeSchema = z.object({
  label: z.string(),
  place_name: z.string(),
  building_type: z.string(),
  intent: z.enum(['site-selection', 'flood', 'tornado', 'general']),
  approx_floors: z.number().nullable().optional(),
  height_m: z.number().nullable().optional(),
  footprint_m: z.number().nullable().optional(),
  style: z.string().nullable().optional(),
  roof_type: z.string().nullable().optional(),
  features: z.array(z.string()).optional(),
})

export async function fetchPlace(query: string): Promise<PlaceResult> {
  const res = await fetch('/api/place', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  if (!res.ok) {
    let message = `Placement failed (${res.status})`
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'error' in body) message = String((body as { error: unknown }).error)
    } catch {
      message = `Placement failed (${res.status})`
    }
    throw new Error(message)
  }
  const p = placeSchema.parse(await res.json())
  return {
    label: p.label,
    placeName: p.place_name,
    buildingType: p.building_type,
    intent: p.intent,
    approxFloors: p.approx_floors ?? null,
    heightM: p.height_m ?? null,
    footprintM: p.footprint_m ?? null,
    style: p.style ?? null,
    roofType: p.roof_type ?? null,
    features: p.features ?? [],
  }
}

// --- AI hazard-exposure briefing (reuses the briefing layer; null without a key) ----------

export interface HazardBriefing {
  headline: string
  exposure: string
  caveats: string[]
  confidence: 'low' | 'medium' | 'high'
}

const hazardBriefingSchema = z.object({
  briefing: z
    .object({
      headline: z.string(),
      exposure: z.string(),
      caveats: z.array(z.string()),
      confidence: z.enum(['low', 'medium', 'high']),
    })
    .nullable(),
})

export async function fetchHazardBriefing(args: {
  kind: 'flood' | 'tornado'
  buildingLabel: string
  placeName: string
  scenario: Record<string, unknown>
}): Promise<HazardBriefing | null> {
  const res = await fetch('/api/hazard-briefing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: args.kind,
      building_label: args.buildingLabel,
      place_name: args.placeName,
      scenario: args.scenario,
    }),
  })
  if (!res.ok) return null
  return hazardBriefingSchema.parse(await res.json()).briefing
}

// --- tornado climatology (NOAA SPC) for a point -------------------------------------------

export interface TornadoClimatology {
  region: string
  annualFrequency: number
  efDistribution: Record<string, number>
  dominantEf: number
  negligible: boolean
  source: string
}

const tornadoSchema = z.object({
  region: z.string(),
  annual_frequency: z.number(),
  ef_distribution: z.record(z.string(), z.number()),
  dominant_ef: z.number(),
  negligible: z.boolean(),
  source: z.string(),
})

// Coarse, real-SPC-based fallback used when the backend is unreachable — preserves the honesty
// contract (non-tornado regions report negligible). Mirrors backend/api/tornado.py::_coarse.
export function coarseTornadoFallback(lat: number, lng: number): TornadoClimatology {
  const source = 'NOAA SPC climatology (coarse, offline)'
  const typical = { EF0: 0.42, EF1: 0.33, EF2: 0.15, EF3: 0.07, EF4: 0.025, EF5: 0.005 }
  const weak = { EF0: 0.52, EF1: 0.32, EF2: 0.11, EF3: 0.04, EF4: 0.009, EF5: 0.001 }
  const none = { EF0: 0, EF1: 0, EF2: 0, EF3: 0, EF4: 0, EF5: 0 }
  if (lat >= 30 && lat <= 49 && lng >= -104 && lng <= -90)
    return { region: 'U.S. Great Plains (Tornado Alley)', annualFrequency: 1.4, efDistribution: typical, dominantEf: 1, negligible: false, source }
  if (lat >= 30 && lat <= 37 && lng >= -94 && lng <= -82)
    return { region: 'U.S. Southeast (Dixie Alley)', annualFrequency: 1.1, efDistribution: typical, dominantEf: 1, negligible: false, source }
  if (lat >= 25 && lat <= 49 && lng >= -100 && lng <= -72)
    return { region: 'Central/Eastern U.S.', annualFrequency: 0.5, efDistribution: weak, dominantEf: 0, negligible: false, source }
  return { region: 'Negligible tornado region', annualFrequency: 0, efDistribution: none, dominantEf: 0, negligible: true, source }
}

export async function fetchTornadoClimatology(lat: number, lng: number): Promise<TornadoClimatology> {
  const qs = new URLSearchParams({ lat: String(lat), lon: String(lng) })
  const res = await fetch(`/api/tornado-climatology?${qs.toString()}`)
  if (!res.ok) throw new Error(`Tornado climatology failed (${res.status})`)
  const t = tornadoSchema.parse(await res.json())
  return {
    region: t.region,
    annualFrequency: t.annual_frequency,
    efDistribution: t.ef_distribution,
    dominantEf: t.dominant_ef,
    negligible: t.negligible,
    source: t.source,
  }
}

// --- LIVE / OBSERVED storm feeds (a SEPARATE category from the ILLUSTRATIVE building-level sim) ----
// Real, timestamped data: NHC active cyclones, NWS tornado alerts, Open-Meteo current wind. These never
// share a label, legend, color ramp, or code path with the illustrative flood/tornado simulation.

export interface Storm {
  id: string
  name: string
  basin: string
  classification: string
  category: number // Saffir–Simpson 0..5 (0 = TS or weaker)
  lat: number
  lng: number
  maxWindKt: number
  minPressureMb: number | null
  movement: string | null
  advisoryTime: string
  source: string
}
export interface StormFeed {
  storms: Storm[]
  asOf: string
  source: string
  coverage: string
}

const stormSchema = z.object({
  id: z.string(),
  name: z.string(),
  basin: z.string(),
  classification: z.string(),
  category: z.number(),
  lat: z.number(),
  lon: z.number(),
  max_wind_kt: z.number(),
  min_pressure_mb: z.number().nullable(),
  movement: z.string().nullable(),
  advisory_time: z.string(),
  source: z.string(),
})
const stormsSchema = z.object({
  storms: z.array(stormSchema),
  as_of: z.string(),
  source: z.string(),
  coverage: z.string(),
})

export async function fetchStorms(): Promise<StormFeed> {
  const res = await fetch('/api/storms')
  if (!res.ok) throw new Error(`Storms feed failed (${res.status})`)
  const j = stormsSchema.parse(await res.json())
  return {
    asOf: j.as_of,
    source: j.source,
    coverage: j.coverage,
    storms: j.storms.map((s) => ({
      id: s.id,
      name: s.name,
      basin: s.basin,
      classification: s.classification,
      category: s.category,
      lat: s.lat,
      lng: s.lon,
      maxWindKt: s.max_wind_kt,
      minPressureMb: s.min_pressure_mb,
      movement: s.movement,
      advisoryTime: s.advisory_time,
      source: s.source,
    })),
  }
}

// GeoJSON geometry kept loosely typed (Polygon | MultiPolygon | null); narrowed where consumed.
export interface AlertGeometry {
  type: string
  coordinates: unknown
}
export interface Alert {
  id: string
  event: string
  severity: string
  certainty: string
  urgency: string
  headline: string | null
  areaDesc: string
  issuedAt: string | null
  expiresAt: string | null
  geometry: AlertGeometry | null
  source: string
}
export interface AlertFeed {
  alerts: Alert[]
  asOf: string
  source: string
  coverage: string
}

const alertSchema = z.object({
  id: z.string(),
  event: z.string(),
  severity: z.string(),
  certainty: z.string(),
  urgency: z.string(),
  headline: z.string().nullable(),
  area_desc: z.string(),
  issued_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  geometry: z.object({ type: z.string(), coordinates: z.unknown() }).nullable(),
  source: z.string(),
})
const alertsSchema = z.object({
  alerts: z.array(alertSchema),
  as_of: z.string(),
  source: z.string(),
  coverage: z.string(),
})

export async function fetchAlerts(): Promise<AlertFeed> {
  const res = await fetch('/api/alerts')
  if (!res.ok) throw new Error(`Alerts feed failed (${res.status})`)
  const j = alertsSchema.parse(await res.json())
  return {
    asOf: j.as_of,
    source: j.source,
    coverage: j.coverage,
    alerts: j.alerts.map((a) => ({
      id: a.id,
      event: a.event,
      severity: a.severity,
      certainty: a.certainty,
      urgency: a.urgency,
      headline: a.headline,
      areaDesc: a.area_desc,
      issuedAt: a.issued_at,
      expiresAt: a.expires_at,
      geometry: a.geometry,
      source: a.source,
    })),
  }
}

// Coarse global current-wind grid (u/v m/s, row-major; row 0 = north). Drives the live wind-flow layer.
export interface GridWind {
  bbox: [number, number, number, number] // lat_min, lon_min, lat_max, lon_max
  resolution: number
  nx: number
  ny: number
  u: number[]
  v: number[]
  speed: number[]
  asOf: string
  source: string
  note: string
}

const gridWindSchema = z.object({
  bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  resolution: z.number(),
  nx: z.number(),
  ny: z.number(),
  u: z.array(z.number()),
  v: z.array(z.number()),
  speed: z.array(z.number()),
  as_of: z.string(),
  source: z.string(),
  note: z.string(),
})

export async function fetchCurrentWind(): Promise<GridWind> {
  const res = await fetch('/api/current-wind')
  if (!res.ok) throw new Error(`Current wind failed (${res.status})`)
  const g = gridWindSchema.parse(await res.json())
  return {
    bbox: g.bbox,
    resolution: g.resolution,
    nx: g.nx,
    ny: g.ny,
    u: g.u,
    v: g.v,
    speed: g.speed,
    asOf: g.as_of,
    source: g.source,
    note: g.note,
  }
}

// --- per-location RISK ANALYSIS dossier (one aggregation call per placement) ---------------
// Composes the existing suitability + hazard + briefing engines for a placed building. Honesty
// is preserved: resource = relative comparator (not bankable yield); flood/tornado = illustrative
// + labeled; live = real/timestamped; insurance = educational, not advice; LLM invents no numbers.

export interface ResourceLens {
  lens: string
  score: number
  rawMetric: number
  units: string
  read: string
  metrics: Record<string, number>
}
export interface ResourceSection {
  available: boolean
  regionLabel: string
  solar: ResourceLens | null
  wind: ResourceLens | null
  crop: ResourceLens | null
  note: string
  source: string
  message: string | null
}
export interface FloodExposure {
  elevationM: number | null
  lowLying: boolean
  exposure: string
  scenarioNote: string
  source: string
}
export interface TornadoExposure {
  region: string
  annualFrequency: number
  dominantEf: number
  efDistribution: Record<string, number>
  negligible: boolean
  read: string
  scenarioNote: string
  source: string
}
export interface LiveContext {
  available: boolean
  nearbyStorm: string | null
  stormCategory: number | null
  stormDistanceKm: number | null
  underAlert: boolean
  alertEvent: string | null
  summary: string
  asOf: string | null
  source: string
  coverage: string
}
export interface InsuranceConsideration {
  kind: string
  consideration: string
  rationale: string
}
export interface AnalysisLocation {
  placeName: string | null
  lat: number
  lon: number
  elevationM: number | null
  terrain: string
  buildingType: string
  intent: string
}
export interface Analysis {
  location: AnalysisLocation
  resource: ResourceSection
  hazards: { flood: FloodExposure; tornado: TornadoExposure; live: LiveContext }
  insurance: InsuranceConsideration[]
  summary: string | null
  disclaimer: string
}

const lensSchema = z.object({
  lens: z.string(),
  score: z.number(),
  raw_metric: z.number(),
  units: z.string(),
  read: z.string(),
  metrics: z.record(z.string(), z.number()),
})
const analysisSchema = z.object({
  location: z.object({
    place_name: z.string().nullable(),
    lat: z.number(),
    lon: z.number(),
    elevation_m: z.number().nullable(),
    terrain: z.string(),
    building_type: z.string(),
    intent: z.string(),
  }),
  resource: z.object({
    available: z.boolean(),
    region_label: z.string(),
    solar: lensSchema.nullable(),
    wind: lensSchema.nullable(),
    crop: lensSchema.nullable(),
    note: z.string(),
    source: z.string(),
    message: z.string().nullable(),
  }),
  hazards: z.object({
    flood: z.object({
      elevation_m: z.number().nullable(),
      low_lying: z.boolean(),
      exposure: z.string(),
      scenario_note: z.string(),
      source: z.string(),
    }),
    tornado: z.object({
      region: z.string(),
      annual_frequency: z.number(),
      dominant_ef: z.number(),
      ef_distribution: z.record(z.string(), z.number()),
      negligible: z.boolean(),
      read: z.string(),
      scenario_note: z.string(),
      source: z.string(),
    }),
    live: z.object({
      available: z.boolean(),
      nearby_storm: z.string().nullable(),
      storm_category: z.number().nullable(),
      storm_distance_km: z.number().nullable(),
      under_alert: z.boolean(),
      alert_event: z.string().nullable(),
      summary: z.string(),
      as_of: z.string().nullable(),
      source: z.string(),
      coverage: z.string(),
    }),
  }),
  insurance: z.array(z.object({ kind: z.string(), consideration: z.string(), rationale: z.string() })),
  summary: z.string().nullable(),
  disclaimer: z.string(),
})

function toLens(l: z.infer<typeof lensSchema> | null): ResourceLens | null {
  return l && { lens: l.lens, score: l.score, rawMetric: l.raw_metric, units: l.units, read: l.read, metrics: l.metrics }
}

export async function fetchAnalysis(args: {
  lat: number
  lng: number
  buildingType: string
  intent: string
  placeName: string
  elevationM: number | null
}): Promise<Analysis> {
  const res = await fetch('/api/analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lat: args.lat,
      lon: args.lng,
      building_type: args.buildingType,
      intent: args.intent,
      place_name: args.placeName,
      elevation_m: args.elevationM,
    }),
  })
  if (!res.ok) throw new Error(`Analysis request failed (${res.status})`)
  const a = analysisSchema.parse(await res.json())
  return {
    location: {
      placeName: a.location.place_name,
      lat: a.location.lat,
      lon: a.location.lon,
      elevationM: a.location.elevation_m,
      terrain: a.location.terrain,
      buildingType: a.location.building_type,
      intent: a.location.intent,
    },
    resource: {
      available: a.resource.available,
      regionLabel: a.resource.region_label,
      solar: toLens(a.resource.solar),
      wind: toLens(a.resource.wind),
      crop: toLens(a.resource.crop),
      note: a.resource.note,
      source: a.resource.source,
      message: a.resource.message,
    },
    hazards: {
      flood: {
        elevationM: a.hazards.flood.elevation_m,
        lowLying: a.hazards.flood.low_lying,
        exposure: a.hazards.flood.exposure,
        scenarioNote: a.hazards.flood.scenario_note,
        source: a.hazards.flood.source,
      },
      tornado: {
        region: a.hazards.tornado.region,
        annualFrequency: a.hazards.tornado.annual_frequency,
        dominantEf: a.hazards.tornado.dominant_ef,
        efDistribution: a.hazards.tornado.ef_distribution,
        negligible: a.hazards.tornado.negligible,
        read: a.hazards.tornado.read,
        scenarioNote: a.hazards.tornado.scenario_note,
        source: a.hazards.tornado.source,
      },
      live: {
        available: a.hazards.live.available,
        nearbyStorm: a.hazards.live.nearby_storm,
        stormCategory: a.hazards.live.storm_category,
        stormDistanceKm: a.hazards.live.storm_distance_km,
        underAlert: a.hazards.live.under_alert,
        alertEvent: a.hazards.live.alert_event,
        summary: a.hazards.live.summary,
        asOf: a.hazards.live.as_of,
        source: a.hazards.live.source,
        coverage: a.hazards.live.coverage,
      },
    },
    insurance: a.insurance,
    summary: a.summary,
    disclaimer: a.disclaimer,
  }
}

// A small bbox (~4°/axis, clamped) centered on a point — for contextual suitability around a placement.
export function bboxAround(lat: number, lng: number, half = 2): Region {
  const lat_min = Math.max(-89, lat - half)
  const lat_max = Math.min(89, lat + half)
  const lon_min = Math.max(-179, lng - half)
  const lon_max = Math.min(179, lng + half)
  return { lat_min, lon_min, lat_max, lon_max }
}
