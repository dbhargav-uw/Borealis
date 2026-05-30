// Typed client for the Borealis site-selection API. Calls POST /api/suitability for BOTH
// lenses so the solar/wind toggle is instant and offline. Backend lat/lon -> globe lat/lng
// is mapped here at the boundary. All external input validated with Zod.

import { z } from 'zod'

export type Lens = 'solar' | 'wind'

export interface Region {
  lat_min: number
  lon_min: number
  lat_max: number
  lon_max: number
}

export interface SuitabilityCell {
  lat: number
  lng: number
  solarScore: number
  windScore: number
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
  sites: Record<Lens, RankedSite[]>
  units: Record<Lens, string>
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
  region: z.object({
    lat_min: z.number(),
    lon_min: z.number(),
    lat_max: z.number(),
    lon_max: z.number(),
  }),
  resolution: z.number(),
  metric_units: z.string(),
  n_cells: z.number(),
  cells: z.array(cellSchema),
  ranked_sites: z.array(rankedSchema),
})

type LensResponse = z.infer<typeof responseSchema>
type RankedRaw = z.infer<typeof rankedSchema>

async function fetchLens(region: Region, lens: Lens): Promise<LensResponse> {
  const res = await fetch('/api/suitability', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vertical: 'energy',
      region,
      resolution: 0.5,
      params: { lens },
      top_n: 5,
    }),
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'error' in body) {
        detail = `: ${String((body as { error: unknown }).error)}`
      }
    } catch {
      detail = ''
    }
    throw new Error(`Suitability request failed (${res.status})${detail}`)
  }
  const json: unknown = await res.json()
  return responseSchema.parse(json)
}

function toSite(s: RankedRaw): RankedSite {
  return { rank: s.rank, lat: s.lat, lng: s.lon, score: s.score, metrics: s.metrics, caveats: s.caveats }
}

export async function fetchSuitability(region: Region): Promise<SuitabilityData> {
  const [solar, wind] = await Promise.all([fetchLens(region, 'solar'), fetchLens(region, 'wind')])
  const windScoreByKey = new Map(wind.cells.map((c) => [`${c.lat},${c.lon}`, c.score]))
  const cells: SuitabilityCell[] = solar.cells.map((c) => ({
    lat: c.lat,
    lng: c.lon,
    solarScore: c.score,
    windScore: windScoreByKey.get(`${c.lat},${c.lon}`) ?? 0,
  }))
  return {
    region,
    cells,
    sites: { solar: solar.ranked_sites.map(toSite), wind: wind.ranked_sites.map(toSite) },
    units: { solar: solar.metric_units, wind: wind.metric_units },
  }
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

export async function fetchBriefing(
  region: Region,
  lens: Lens,
  regionLabel: string,
): Promise<SiteBriefing | null> {
  const res = await fetch('/api/suitability', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vertical: 'energy',
      region,
      resolution: 0.5,
      params: { lens },
      top_n: 5,
      include_briefing: true,
      region_label: regionLabel,
    }),
  })
  if (!res.ok) throw new Error(`Briefing request failed (${res.status})`)
  const json: unknown = await res.json()
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
  region: z.object({
    lat_min: z.number(),
    lon_min: z.number(),
    lat_max: z.number(),
    lon_max: z.number(),
  }),
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
      if (body && typeof body === 'object' && 'error' in body) {
        message = String((body as { error: unknown }).error)
      }
    } catch {
      message = `Search failed (${res.status})`
    }
    throw new Error(message)
  }
  const json: unknown = await res.json()
  const parsed = askSchema.parse(json)
  return { label: parsed.label, region: parsed.region, lens: parsed.lens }
}
