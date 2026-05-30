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
}

export const LAYERS: LayerDef[] = [
  { id: 'solar', label: '☀ Solar', name: 'solar', vertical: 'energy', params: { lens: 'solar' }, accent: '#ffd140', metricKey: 'specific_yield_kwh_kwp_yr', metricLabel: 'Specific yield' },
  { id: 'wind', label: '🌀 Wind', name: 'wind', vertical: 'energy', params: { lens: 'wind' }, accent: '#4ed6ff', metricKey: 'wind_power_density_wm2', metricLabel: 'Wind power density' },
  { id: 'cropland', label: '🌱 Cropland', name: 'cropland', vertical: 'agriculture', params: {}, accent: '#7ce38b', metricKey: 'growing_degree_days', metricLabel: 'Growing-degree-days' },
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
