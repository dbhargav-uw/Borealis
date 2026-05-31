import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from 'react'
import type { GlobeHandle } from './ResourceGlobe'
import type { FloodStats } from './hazard/flood'
import { ErrorBoundary } from './ErrorBoundary'
import {
  bboxAround,
  coarseTornadoFallback,
  fetchAlerts,
  fetchAnalysis,
  fetchBestSite,
  fetchBriefing,
  fetchCurrentWind,
  fetchFieldMeta,
  fetchHazardBriefing,
  fetchPlace,
  fetchSeasonal,
  fetchStorms,
  fetchSuitability,
  fetchTornadoClimatology,
  fetchVariability,
  LAYERS,
  regionCenter,
  type Alert,
  type AlertFeed,
  type BestSiteExplanation,
  type FieldMeta,
  type GridWind,
  type Storm,
  type StormFeed,
  type HazardBriefing,
  type Intent,
  type LayerDef,
  type PlaceResult,
  type TornadoClimatology,
  type RankedSite,
  type Region,
  type Seasonal,
  type SiteBriefing,
  type SuitabilityData,
  type Variability,
} from './lib/api'
import { AnalysisDossier, type AnalysisState } from './AnalysisDossier'
import { FanChart } from './FanChart'
import { SeasonalChart } from './SeasonalChart'
import { logger } from './lib/logger'
import borealisMark from './assets/borealis-mark.svg'
import './App.css'

const ResourceGlobe = lazy(() => import('./ResourceGlobe').then((m) => ({ default: m.ResourceGlobe })))

// The landing hero: one cohesive global weather field (temperature) on the vivid globe.
const WEATHER_ACCENT = '#ffb060'
// On-demand colored data fields (off by default — the cinematic earth is the landing).
const DATA_FIELDS = [
  { id: 'temp', label: '🌡 Temp' },
  { id: 'wind', label: '🌀 Wind' },
  { id: 'solar', label: '☀ Solar' },
]
const GLOBAL_FOCUS = { lat: 22, lng: 8 }
// Stable empty refs so the globe's live-layer effects don't re-run on every render when nothing's shown.
const NO_STORMS: Storm[] = []
const NO_ALERTS: Alert[] = []

// LIVE / OBSERVED time formatting (kept distinct from the timeless illustrative sim copy).
function fmtUtcHm(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : `${d.toUTCString().slice(17, 22)} UTC`
}
function fmtUtcDateTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.toUTCString().slice(5, 22)} UTC`
}

// Suitability is loaded ONLY when a contextual lens + region are set (after an intent), never on landing.
type SuitState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: SuitabilityData }

type BriefState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; briefing: SiteBriefing }
  | { kind: 'none' }
  | { kind: 'error'; message: string }

type VarState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; data: Variability }
  | { kind: 'error'; message: string }

type SeasonState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; data: Seasonal }
  | { kind: 'error'; message: string }

interface Placement {
  label: string
  buildingType: string
  intent: Intent
  lat: number
  lng: number
  baseHeight: number
}

const FLOOD_PRESETS = [1, 3, 6, 10] // metres above the building base

type TornadoState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'active'; clim: TornadoClimatology }
  | { kind: 'negligible'; clim: TornadoClimatology }
  | { kind: 'error'; message: string }

type HazardBriefState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; b: HazardBriefing }
  | { kind: 'none' }

// LIVE / OBSERVED feeds (a SEPARATE category from the illustrative sim state above).
type StormsState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; feed: StormFeed }
  | { kind: 'error'; message: string }
type AlertsState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ok'; feed: AlertFeed }
  | { kind: 'error'; message: string }
type WindState = { kind: 'idle' } | { kind: 'ok'; grid: GridWind } | { kind: 'error' }

export function App(): ReactElement {
  // weather-map landing
  const [fieldMeta, setFieldMeta] = useState<Record<string, FieldMeta>>({})
  const [query, setQuery] = useState<string>('')
  const [asking, setAsking] = useState<boolean>(false)
  const [askError, setAskError] = useState<string | null>(null)
  const [placement, setPlacement] = useState<Placement | null>(null)
  const [dataField, setDataField] = useState<string | null>(null) // optional colored overlay (off by default)
  const [floodLevel, setFloodLevel] = useState<number | null>(null)
  const [floodStats, setFloodStats] = useState<FloodStats | null>(null)
  const [tornado, setTornado] = useState<TornadoState>({ kind: 'idle' })
  const [hazardBrief, setHazardBrief] = useState<HazardBriefState>({ kind: 'idle' })
  // per-location risk-analysis dossier (one /api/analysis call per placement; opens on placement, clears on reset)
  const [analysis, setAnalysis] = useState<AnalysisState>({ kind: 'idle' })
  // find-best-site: ranked candidate markers + the "why here" explanation (set on a region search)
  const [bestCandidates, setBestCandidates] = useState<RankedSite[]>([])
  const [bestExplanation, setBestExplanation] = useState<BestSiteExplanation | null>(null)
  const globeRef = useRef<GlobeHandle>(null)

  // LIVE / OBSERVED layers (shown only when zoomed out; OBSERVATIONAL, never the illustrative sim).
  // Wind streamlines are the hero weather look → ALWAYS on (no toggle). Storms (cyclones + tornado alerts) opt-in.
  const [stormsOn, setStormsOn] = useState<boolean>(false)
  const [zoomedOut, setZoomedOut] = useState<boolean>(true)
  const [storms, setStorms] = useState<StormsState>({ kind: 'idle' })
  const [alerts, setAlerts] = useState<AlertsState>({ kind: 'idle' })
  const [wind, setWind] = useState<WindState>({ kind: 'idle' })
  const [selectedStorm, setSelectedStorm] = useState<Storm | null>(null)
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null)

  // contextual suitability (revealed once an intent sets a lens + region)
  const [contextLens, setContextLens] = useState<string | null>(null)
  const [region, setRegion] = useState<Region | null>(null)
  const [regionLabel, setRegionLabel] = useState<string>('')
  const [suit, setSuit] = useState<SuitState>({ kind: 'idle' })
  const [selected, setSelected] = useState<RankedSite | null>(null)
  const [brief, setBrief] = useState<BriefState>({ kind: 'idle' })
  const [variab, setVariab] = useState<VarState>({ kind: 'idle' })
  const [season, setSeason] = useState<SeasonState>({ kind: 'idle' })
  const [landOnly, setLandOnly] = useState<boolean>(true)

  useEffect(() => {
    void (async (): Promise<void> => {
      try {
        setFieldMeta(await fetchFieldMeta())
      } catch (err) {
        logger.error('field meta fetch failed', err)
      }
    })()
  }, [])

  // LIVE wind grid — ALWAYS on (the hero weather layer); polled every ~12 min (cached server-side).
  useEffect(() => {
    let cancelled = false
    const load = async (): Promise<void> => {
      try {
        const grid = await fetchCurrentWind() // coarse, server-cached for hours; degrades to no flow on error
        if (!cancelled) setWind({ kind: 'ok', grid })
      } catch {
        if (!cancelled) setWind({ kind: 'error' })
      }
    }
    void load()
    const id = window.setInterval(() => void load(), 12 * 60_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  // LIVE storm + tornado-alert feeds — polled every ~12 min while the storms layer is toggled on (opt-in).
  useEffect(() => {
    if (!stormsOn) {
      setStorms({ kind: 'idle' })
      setAlerts({ kind: 'idle' })
      setSelectedStorm(null)
      setSelectedAlert(null)
      return
    }
    let cancelled = false
    const load = async (): Promise<void> => {
      setStorms((p) => (p.kind === 'ok' ? p : { kind: 'loading' }))
      setAlerts((p) => (p.kind === 'ok' ? p : { kind: 'loading' }))
      try {
        const feed = await fetchStorms()
        if (!cancelled) setStorms({ kind: 'ok', feed })
      } catch (err) {
        if (!cancelled) setStorms({ kind: 'error', message: err instanceof Error ? err.message : 'Storm feed failed' })
      }
      try {
        const feed = await fetchAlerts()
        if (!cancelled) setAlerts({ kind: 'ok', feed })
      } catch (err) {
        if (!cancelled) setAlerts({ kind: 'error', message: err instanceof Error ? err.message : 'Alert feed failed' })
      }
    }
    void load()
    const id = window.setInterval(() => void load(), 12 * 60_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [stormsOn])

  // suitability fetch — gated on a contextual lens + region (no fetch on the weather-map landing)
  useEffect(() => {
    if (!contextLens || !region) {
      setSuit({ kind: 'idle' })
      return
    }
    let cancelled = false
    setSuit({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const data = await fetchSuitability(region, landOnly)
        if (!cancelled) setSuit({ kind: 'ok', data })
      } catch (err) {
        logger.error('suitability fetch failed', err)
        if (!cancelled) setSuit({ kind: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [contextLens, region, landOnly])

  const lensDef: LayerDef | null = contextLens ? LAYERS.find((l) => l.id === contextLens) ?? null : null
  const accent = lensDef?.accent ?? WEATHER_ACCENT
  // No colored overlay by default: a contextual suitability lens, else the on-demand data field, else none.
  const fieldId = contextLens ?? dataField
  const data = suit.kind === 'ok' ? suit.data : null
  const sites = useMemo<RankedSite[]>(
    () => (data && contextLens ? data.sites[contextLens] ?? [] : []),
    [data, contextLens],
  )
  const focus = region ? regionCenter(region) : GLOBAL_FOCUS
  // LIVE layers render only when zoomed out (the global view) — never on a placed building. Wind is always on;
  // storms are opt-in.
  const showWind = zoomedOut
  const showStorms = stormsOn && zoomedOut
  const liveAsOf =
    storms.kind === 'ok' ? storms.feed.asOf : alerts.kind === 'ok' ? alerts.feed.asOf : null

  useEffect(() => {
    setSelected(sites[0] ?? null)
  }, [sites])

  useEffect(() => {
    setBrief({ kind: 'idle' })
    setVariab({ kind: 'idle' })
  }, [contextLens, region])

  useEffect(() => {
    if (!selected || !lensDef) {
      setSeason({ kind: 'idle' })
      return
    }
    let cancelled = false
    const site = selected
    const seasonalVar = lensDef.seasonalVar
    setSeason({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const d = await fetchSeasonal(site.lat, site.lng, seasonalVar)
        if (!cancelled) setSeason({ kind: 'ok', data: d })
      } catch (err) {
        if (!cancelled) setSeason({ kind: 'error', message: err instanceof Error ? err.message : 'Seasonal failed' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, lensDef])

  const unit = data && contextLens ? data.units[contextLens] ?? '' : ''
  const meta = fieldId ? fieldMeta[fieldId] : undefined

  const onPick = (site: RankedSite): void => {
    setSelected(site)
    setVariab({ kind: 'idle' })
    globeRef.current?.flyTo(site.lat, site.lng)
  }
  // One aggregation call per placement -> the left-side risk-analysis dossier (additive; never blocks).
  const openAnalysis = (
    lat: number, lng: number, buildingType: string, intent: Intent, placeName: string, elevationM: number,
  ): void => {
    setAnalysis({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const a = await fetchAnalysis({ lat, lng, buildingType, intent, placeName, elevationM })
        setAnalysis({ kind: 'ok', data: a })
      } catch (err) {
        logger.warn('analysis dossier unavailable', err)
        setAnalysis({ kind: 'error', message: err instanceof Error ? err.message : 'Analysis failed' })
      }
    })()
  }
  // The query bar places a building: parse (Anthropic) -> geocode (ion) -> terrain-clamped building ->
  // oblique fly-to -> surface the contextual layer for the intent (suitability lens, or a hazard view).
  // A "find the best place in <region> to build X" query instead searches the region (/api/best-site)
  // and builds at the winner.
  const onPlace = (e: FormEvent): void => {
    e.preventDefault()
    if (!query.trim() || asking) return
    setAsking(true)
    setAskError(null)
    void (async (): Promise<void> => {
      try {
        // Anthropic parses query -> {placeName, buildingType, intent}; without a key we degrade
        // gracefully by geocoding the raw query as a place with a generic building + intent.
        let p: PlaceResult
        try {
          p = await fetchPlace(query.trim())
        } catch (parseErr) {
          logger.warn('place parse unavailable; geocoding raw query', parseErr)
          p = {
            mode: 'place', label: query.trim(), placeName: query.trim(), buildingType: 'building', intent: 'general',
            approxFloors: null, heightM: null, footprintM: null, style: null, roofType: null, features: [],
          }
        }

        // FIND-BEST: search the region for the optimal site, then build at the winner.
        if (p.mode === 'find-best') {
          const best = await fetchBestSite(query.trim())
          if (!best.bestSite) {
            setAskError(best.message ?? `No suitable site found in ${best.regionLabel || 'that region'}.`)
            return
          }
          const site = best.bestSite
          const coords = await globeRef.current?.placeBuildingAt(site.lat, site.lng, {
            placeName: best.regionLabel, buildingType: best.buildingType, label: best.buildingType,
            approxFloors: null, heightM: null, footprintM: null,
          })
          if (!coords) {
            setAskError('Couldn’t place the building at the chosen site.')
            return
          }
          setFloodLevel(null)
          setTornado({ kind: 'idle' })
          setContextLens(null)
          setRegion(null)
          setBestCandidates(
            best.topCandidates.map((c, i) => ({ rank: i + 1, lat: c.lat, lng: c.lng, score: c.score, metrics: c.metrics, caveats: [] })),
          )
          setBestExplanation(best.explanation)
          setPlacement({
            label: `${best.buildingType} · best in ${best.regionLabel}`,
            buildingType: best.buildingType, intent: 'general',
            lat: coords.lat, lng: coords.lng, baseHeight: coords.baseHeight,
          })
          openAnalysis(coords.lat, coords.lng, best.buildingType, 'general', best.regionLabel, coords.baseHeight)
          return
        }

        const coords = await globeRef.current?.placeBuilding({
          placeName: p.placeName,
          buildingType: p.buildingType,
          label: p.label,
          approxFloors: p.approxFloors,
          heightM: p.heightM,
          footprintM: p.footprintM,
        })
        if (!coords) {
          setAskError(`Couldn’t locate “${p.placeName}”.`)
          return
        }
        setFloodLevel(null)
        setTornado({ kind: 'idle' })
        setBestCandidates([])
        setBestExplanation(null)
        setPlacement({
          label: p.label,
          buildingType: p.buildingType,
          intent: p.intent,
          lat: coords.lat,
          lng: coords.lng,
          baseHeight: coords.baseHeight,
        })
        openAnalysis(coords.lat, coords.lng, p.buildingType, p.intent, p.placeName, coords.baseHeight)
        if (p.intent === 'site-selection') {
          setRegionLabel(p.label)
          setContextLens('solar')
          setRegion(bboxAround(coords.lat, coords.lng))
        } else {
          setContextLens(null)
          setRegion(null)
        }
      } catch (err) {
        setAskError(err instanceof Error ? err.message : 'Placement failed')
      } finally {
        setAsking(false)
      }
    })()
  }
  const onBackToMap = (): void => {
    const from = placement
    globeRef.current?.clearBuilding()
    // fly back out to the cinematic globe (the default weather map), then auto-rotation resumes
    if (from) globeRef.current?.flyTo(from.lat, from.lng, 22_000_000)
    setPlacement(null)
    setAnalysis({ kind: 'idle' })
    setBestCandidates([])
    setBestExplanation(null)
    setFloodLevel(null)
    setFloodStats(null)
    setTornado({ kind: 'idle' })
    setHazardBrief({ kind: 'idle' })
    setContextLens(null)
    setRegion(null)
    setRegionLabel('')
    setSelected(null)
  }
  const onFlood = (level: number): void => {
    if (!placement) return
    const site = placement
    setTornado({ kind: 'idle' }) // starting a flood disposes any tornado (one hazard at a time)
    setHazardBrief({ kind: 'idle' })
    setFloodLevel(level)
    setFloodStats(null)
    void (async (): Promise<void> => {
      const stats = await globeRef.current?.startFlood({
        lat: site.lat,
        lng: site.lng,
        baseHeight: site.baseHeight,
        level,
      })
      if (stats) setFloodStats(stats)
    })()
  }
  const onTornado = (): void => {
    if (!placement || tornado.kind === 'loading') return
    const site = placement
    setFloodLevel(null)
    setHazardBrief({ kind: 'idle' })
    setTornado({ kind: 'loading' })
    void (async (): Promise<void> => {
      let clim
      try {
        clim = await fetchTornadoClimatology(site.lat, site.lng)
      } catch (err) {
        logger.warn('tornado climatology unavailable; using coarse offline model', err)
        clim = coarseTornadoFallback(site.lat, site.lng)
      }
      if (clim.negligible) {
        globeRef.current?.clearHazard() // honest: no fake funnel where tornadoes don't occur
        setTornado({ kind: 'negligible', clim })
        return
      }
      globeRef.current?.startTornado({ lat: site.lat, lng: site.lng, baseHeight: site.baseHeight, intensity: clim.dominantEf })
      setTornado({ kind: 'active', clim })
    })()
  }
  const onClearHazard = (): void => {
    globeRef.current?.clearHazard()
    setFloodLevel(null)
    setTornado({ kind: 'idle' })
    setHazardBrief({ kind: 'idle' })
  }
  const onExplainHazard = (): void => {
    if (!placement || hazardBrief.kind === 'loading') return
    const kind: 'flood' | 'tornado' | null =
      floodLevel !== null ? 'flood' : tornado.kind === 'active' ? 'tornado' : null
    if (!kind) return
    const scenario: Record<string, unknown> =
      kind === 'flood'
        ? { water_level_m: floodLevel, base_elevation_m: Math.round(placement.baseHeight), terrain: 'Cesium World Terrain', model: 'bathtub inundation (illustrative)' }
        : tornado.kind === 'active'
          ? { ef_scale: tornado.clim.dominantEf, annual_frequency_per_year: tornado.clim.annualFrequency, region: tornado.clim.region, source: tornado.clim.source }
          : {}
    const label = placement.label
    setHazardBrief({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const b = await fetchHazardBriefing({ kind, buildingLabel: label, placeName: label, scenario })
        setHazardBrief(b ? { kind: 'ok', b } : { kind: 'none' })
      } catch {
        setHazardBrief({ kind: 'none' })
      }
    })()
  }
  const onExplain = (): void => {
    if (brief.kind === 'loading' || !region || !lensDef) return
    setBrief({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const b = await fetchBriefing(region, lensDef, regionLabel, landOnly)
        setBrief(b ? { kind: 'ok', briefing: b } : { kind: 'none' })
      } catch (err) {
        setBrief({ kind: 'error', message: err instanceof Error ? err.message : 'Briefing failed' })
      }
    })()
  }
  const onVariability = (): void => {
    if (!selected || !contextLens) return
    const site = selected
    const lens = contextLens
    setVariab({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const d = await fetchVariability(site.lat, site.lng, lens)
        setVariab({ kind: 'ok', data: d })
      } catch (err) {
        setVariab({ kind: 'error', message: err instanceof Error ? err.message : 'Forecast failed' })
      }
    })()
  }

  return (
    <main className="screen">
      <div className="globe-wrap">
        <ErrorBoundary
          fallback={
            <div className="globe-loading">
              <span>Globe failed to load — hard-reload (⌘⇧R). If it persists, restart Vite after <code>rm -rf node_modules/.vite</code>.</span>
            </div>
          }
        >
          <Suspense fallback={<div className="globe-loading"><span>Spinning up the globe…</span></div>}>
            <ResourceGlobe
              ref={globeRef}
              sites={bestCandidates.length > 0 ? bestCandidates : sites}
              layerId={fieldId}
              accent={accent}
              focus={focus}
              selectedRank={selected?.rank ?? null}
              onSiteClick={onPick}
              storms={showStorms && storms.kind === 'ok' ? storms.feed.storms : NO_STORMS}
              alerts={showStorms && alerts.kind === 'ok' ? alerts.feed.alerts : NO_ALERTS}
              windGrid={showWind && wind.kind === 'ok' ? wind.grid : null}
              dimBase={showWind}
              onStormClick={(s) => {
                setSelectedStorm(s)
                setSelectedAlert(null)
              }}
              onAlertClick={(a) => {
                setSelectedAlert(a)
                setSelectedStorm(null)
              }}
              onZoomChange={setZoomedOut}
            />
          </Suspense>
        </ErrorBoundary>
      </div>

      <header className="hud hud--top">
        <div className="brand">
          <img className="brand__mark" src={borealisMark} alt="" aria-hidden width={34} height={34} />
          <h1>Borealis</h1>
        </div>
        <p className="tagline">A living weather map — ask it where to build, or what could go wrong.</p>
        <form className="ask" onSubmit={onPlace}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name a place — e.g. “a coastal hospital in Miami”"
            aria-label="Ask the globe"
          />
          <button type="submit" disabled={asking}>{asking ? '…' : 'Go'}</button>
        </form>
        {askError && <p className="ask-error">{askError}</p>}
        {!contextLens && !placement && (
          <>
            <div className="lens-toggle datafield-toggle" role="group" aria-label="Data field overlay">
              <button
                type="button"
                className={dataField === null ? 'lens lens--active' : 'lens'}
                onClick={() => setDataField(null)}
              >
                Map
              </button>
              {DATA_FIELDS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={dataField === f.id ? 'lens lens--active' : 'lens'}
                  onClick={() => setDataField(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="lens-toggle storms-toggle" role="group" aria-label="Live storms overlay">
              <button
                type="button"
                className={stormsOn ? 'lens lens--active lens--live' : 'lens'}
                onClick={() => setStormsOn((v) => !v)}
                title="Real, timestamped storms — NHC named cyclones + NWS tornado alerts"
              >
                🌀 Storms
              </button>
            </div>
          </>
        )}
        {contextLens && (
          <>
            <div className="lens-toggle" role="group" aria-label="Suitability layer">
              {LAYERS.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className={l.id === contextLens ? 'lens lens--active' : 'lens'}
                  style={l.id === contextLens ? { borderColor: l.accent, color: l.accent } : undefined}
                  onClick={() => setContextLens(l.id)}
                >
                  {l.label}
                </button>
              ))}
            </div>
            <label className="offshore">
              <input type="checkbox" checked={!landOnly} onChange={(e) => setLandOnly(!e.target.checked)} />
              Include offshore
            </label>
            <p className="region-label">
              {regionLabel} · <button type="button" className="link-btn" onClick={onBackToMap}>back to weather map</button>
            </p>
          </>
        )}
      </header>

      {placement && analysis.kind !== 'idle' && (
        <AnalysisDossier placement={placement} state={analysis} whyHere={bestExplanation} onClose={onBackToMap} />
      )}

      {placement && placement.intent !== 'site-selection' && (
        <aside className="hud hud--placement">
          <div className="place-head">
            <strong>{placement.label}</strong>
            <button type="button" className="link-btn" onClick={onBackToMap}>back to map</button>
          </div>
          <p className="place-sub">
            {placement.buildingType} · {placement.lat.toFixed(3)}, {placement.lng.toFixed(3)} · base {placement.baseHeight.toFixed(0)} m
          </p>
          <div className="hazard-row">
            <span className="hazard-label">🌊 Flood level</span>
            <div className="hazard-presets">
              {FLOOD_PRESETS.map((m) => (
                <button
                  key={m}
                  type="button"
                  className={floodLevel === m ? 'preset preset--active' : 'preset'}
                  onClick={() => onFlood(m)}
                >
                  +{m}m
                </button>
              ))}
            </div>
          </div>
          <div className="hazard-row">
            <span className="hazard-label">🌪 Tornado</span>
            <div className="hazard-presets">
              <button
                type="button"
                className={tornado.kind === 'active' ? 'preset preset--active' : 'preset'}
                onClick={onTornado}
                disabled={tornado.kind === 'loading'}
              >
                {tornado.kind === 'loading' ? '…' : 'simulate'}
              </button>
              {(floodLevel !== null || tornado.kind === 'active' || tornado.kind === 'negligible') && (
                <button type="button" className="preset" onClick={onClearHazard}>clear</button>
              )}
            </div>
          </div>

          {floodLevel !== null && (
            <div className="flood-readout">
              <div className="flood-metrics">
                <div className="flood-metric">
                  <span className="flood-metric-val">{floodLevel} m</span>
                  <span className="flood-metric-cap">depth at building</span>
                </div>
                <div className="flood-metric">
                  <span className="flood-metric-val">
                    {floodStats ? `${floodStats.submergedPct}%` : '…'}
                  </span>
                  <span className="flood-metric-cap">area submerged</span>
                </div>
              </div>
              <div className="flood-legend">
                <span className="flood-legend-cap">depth</span>
                <span className="flood-legend-ramp" />
                <span className="flood-legend-ends">
                  <span>0</span>
                  <span>{floodLevel} m</span>
                </span>
              </div>
              <p className="place-hint">
                Bathtub inundation +{floodLevel} m over Cesium World Terrain — the wetted area follows real elevation.{' '}
                <strong>Illustrative, not a hydrodynamic model.</strong>
              </p>
            </div>
          )}
          {tornado.kind === 'active' && (
            <p className="place-hint">
              Illustrative EF-{tornado.clim.dominantEf} tornado · ~{tornado.clim.annualFrequency.toFixed(2)}/yr regionally ({tornado.clim.region}) · {tornado.clim.source}.{' '}
              <strong>Not a forecast.</strong>
            </p>
          )}
          {tornado.kind === 'negligible' && (
            <p className="place-hint">
              <strong>Negligible tornado risk here</strong> — {tornado.clim.region}, per {tornado.clim.source}. No funnel shown (we don’t fake one).
            </p>
          )}
          {tornado.kind === 'error' && <p className="place-hint">Tornado climatology unavailable: {tornado.message}</p>}
          {floodLevel === null && tornado.kind === 'idle' && (
            <p className="place-hint">Pick a flood level, or simulate a tornado — both grounded in real terrain &amp; NOAA SPC climatology.</p>
          )}
          {(floodLevel !== null || tornado.kind === 'active') && (
            <div className="hazard-brief">
              <button type="button" className="explain-btn" onClick={onExplainHazard} disabled={hazardBrief.kind === 'loading'}>
                {hazardBrief.kind === 'loading' ? 'Explaining…' : '✨ Explain exposure'}
              </button>
              {hazardBrief.kind === 'none' && (
                <p className="place-hint">AI explanation unavailable — set <code>ANTHROPIC_API_KEY</code>.</p>
              )}
              {hazardBrief.kind === 'ok' && (
                <>
                  <p className="place-hint"><strong>{hazardBrief.b.headline}</strong></p>
                  <p className="place-hint">{hazardBrief.b.exposure}</p>
                </>
              )}
            </div>
          )}
        </aside>
      )}

      {contextLens && lensDef && (
        <section className="hud hud--sites">
          <div className="sites-head">
            <h2 style={{ color: accent }}>Top sites · {lensDef.name}</h2>
            <button type="button" className="explain-btn" onClick={onExplain}>✨ Explain</button>
          </div>
          <ol>
            {suit.kind === 'loading' && <li className="empty">Scoring climatology…</li>}
            {suit.kind === 'error' && <li className="empty">{suit.message}</li>}
            {suit.kind === 'ok' && sites.length === 0 && <li className="empty">No scorable cells in this region.</li>}
            {sites.map((s) => (
              <li key={s.rank}>
                <button
                  type="button"
                  className={selected?.rank === s.rank ? 'site site--active' : 'site'}
                  onClick={() => onPick(s)}
                >
                  <span className="site-rank" style={{ background: accent }}>#{s.rank}</span>
                  <span className="site-loc">{s.lat.toFixed(2)}, {s.lng.toFixed(2)}</span>
                  <span className="site-score">{(s.score * 100).toFixed(0)}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      {contextLens && brief.kind !== 'idle' && (
        <aside className="hud hud--briefing">
          {brief.kind === 'loading' && <p className="brief-loading">Generating “why this site” briefing…</p>}
          {brief.kind === 'none' && (
            <p className="brief-none">
              AI briefing unavailable — set <code>ANTHROPIC_API_KEY</code> in <code>.env</code> to enable it.
            </p>
          )}
          {brief.kind === 'error' && <p className="brief-none">Briefing failed: {brief.message}</p>}
          {brief.kind === 'ok' && (
            <>
              <div className="brief-head">
                <strong>{brief.briefing.headline}</strong>
                <span className={`conf conf--${brief.briefing.confidence}`}>{brief.briefing.confidence}</span>
              </div>
              <p className="brief-body">{brief.briefing.why_top_sites}</p>
              <div className="chips">
                {brief.briefing.top_drivers.map((d, i) => (
                  <span key={i} className="chip" style={{ borderColor: accent }}>{d}</span>
                ))}
              </div>
              <ul className="caveats">
                {brief.briefing.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </>
          )}
        </aside>
      )}

      {contextLens && lensDef && selected && (
        <aside className="hud hud--detail">
          <div className="detail-head">
            <span className="site-rank" style={{ background: accent }}>#{selected.rank}</span>
            <div>
              <strong>{selected.lat.toFixed(2)}, {selected.lng.toFixed(2)}</strong>
              <div className="detail-sub">relative suitability {(selected.score * 100).toFixed(0)} / 100</div>
            </div>
          </div>
          <div className="bar"><span style={{ width: `${selected.score * 100}%`, background: accent }} /></div>
          <p className="detail-metric">
            <span className="detail-label">{lensDef.metricLabel}</span>
            <span>{(selected.metrics[lensDef.metricKey] ?? 0).toFixed(0)} {unit}</span>
          </p>
          <ul className="caveats">
            {selected.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
          <div className="season">
            {season.kind === 'loading' && <p className="variab-note">Loading seasonal profile…</p>}
            {season.kind === 'error' && <p className="variab-note">{season.message}</p>}
            {season.kind === 'ok' && (
              <>
                <SeasonalChart data={season.data} accent={accent} />
                <p className="variab-note">Seasonal {lensDef.name} · monthly climatology ({season.data.units})</p>
              </>
            )}
          </div>
          {lensDef.vertical === 'energy' && (
            <div className="variab">
              {variab.kind === 'idle' && (
                <button type="button" className="variab-btn" onClick={onVariability}>
                  ▸ Short-term variability (Act 2)
                </button>
              )}
              {variab.kind === 'loading' && <p className="variab-note">Fetching live forecast…</p>}
              {variab.kind === 'error' && <p className="variab-note">{variab.message}</p>}
              {variab.kind === 'ok' && (
                <>
                  <FanChart data={variab.data} accent={accent} />
                  <p className="variab-note">Next 48 h generation · P10–P90 ({variab.data.units})</p>
                </>
              )}
            </div>
          )}
        </aside>
      )}

      {(zoomedOut || stormsOn) && (
        <div className="hud hud--live-legend">
          <span className="live-badge">● LIVE</span>
          {zoomedOut && (
            <>
              <span className="ramp ramp--wind" />
              <span className="legend-note">
                wind · calm→gale
                {wind.kind === 'error'
                  ? ' · unavailable'
                  : wind.kind === 'ok'
                    ? ` · as of ${fmtUtcHm(wind.grid.asOf)}`
                    : ' · loading…'}
              </span>
            </>
          )}
          {stormsOn &&
            (storms.kind === 'error' && alerts.kind === 'error' ? (
              <span className="legend-note">Storm feed unavailable.</span>
            ) : storms.kind !== 'ok' && alerts.kind !== 'ok' ? (
              <span className="legend-note">Loading storms…</span>
            ) : (
              <>
                <span className="ramp ramp--cat" />
                <span className="legend-note">
                  TS→Cat 5 · <b className="sw-warn">warning</b> · <b className="sw-watch">watch</b>
                </span>
                <span className="legend-note">
                  {storms.kind === 'ok' ? `${storms.feed.storms.length} cyclones` : '…'} ·{' '}
                  {alerts.kind === 'ok' ? `${alerts.feed.alerts.length} tornado alerts` : '…'}
                  {liveAsOf ? ` · as of ${fmtUtcHm(liveAsOf)}` : ''}
                </span>
                {storms.kind === 'ok' &&
                  storms.feed.storms.length === 0 &&
                  alerts.kind === 'ok' &&
                  alerts.feed.alerts.length === 0 && (
                    <span className="legend-note">No named cyclones / tornado alerts now · NHC Atlantic + E/C Pacific · NWS US-only.</span>
                  )}
              </>
            ))}
          {!zoomedOut && <span className="legend-note">Zoom out to view on the globe.</span>}
        </div>
      )}

      {selectedStorm && (
        <aside className="hud hud--live-detail">
          <div className="place-head">
            <strong>🌀 {selectedStorm.name}</strong>
            <button type="button" className="link-btn" onClick={() => setSelectedStorm(null)}>close</button>
          </div>
          <p className="place-sub">
            <span className="live-badge">● LIVE · OBSERVED</span> · {selectedStorm.classification} · {selectedStorm.basin}
          </p>
          <div className="live-metrics">
            <div className="live-metric">
              <span className="live-metric-val">{selectedStorm.category >= 1 ? `Cat ${selectedStorm.category}` : 'TS'}</span>
              <span className="live-metric-cap">category</span>
            </div>
            <div className="live-metric">
              <span className="live-metric-val">{selectedStorm.maxWindKt.toFixed(0)} kt</span>
              <span className="live-metric-cap">max wind</span>
            </div>
          </div>
          <p className="place-hint">
            {selectedStorm.lat.toFixed(1)}, {selectedStorm.lng.toFixed(1)}
            {selectedStorm.movement ? ` · moving ${selectedStorm.movement}` : ''}
            {selectedStorm.minPressureMb !== null ? ` · ${selectedStorm.minPressureMb.toFixed(0)} mb` : ''}
          </p>
          <p className="place-hint">
            {selectedStorm.source} · advisory {fmtUtcDateTime(selectedStorm.advisoryTime)}.{' '}
            <strong>Live observation, not a Borealis scenario.</strong>
          </p>
        </aside>
      )}

      {selectedAlert && (
        <aside className="hud hud--live-detail">
          <div className="place-head">
            <strong>{selectedAlert.event}</strong>
            <button type="button" className="link-btn" onClick={() => setSelectedAlert(null)}>close</button>
          </div>
          <p className="place-sub">
            <span className="live-badge">● LIVE · OBSERVED</span> · {selectedAlert.severity}
          </p>
          <p className="place-hint">{selectedAlert.areaDesc}</p>
          {selectedAlert.headline && <p className="place-hint">{selectedAlert.headline}</p>}
          <p className="place-hint">
            {selectedAlert.source}
            {selectedAlert.expiresAt ? ` · expires ${fmtUtcDateTime(selectedAlert.expiresAt)}` : ''}.{' '}
            <strong>NWS observed alert, not a Borealis scenario.</strong>
          </p>
        </aside>
      )}

      <footer className="hud hud--legend">
        {meta && fieldId ? (
          <>
            <span>{meta.vmin}</span>
            <span className="ramp" style={{ background: `linear-gradient(90deg, ${meta.legend.join(', ')})` }} />
            <span>{meta.vmax}</span>
            <span className="legend-note">
              {meta.label} · {meta.units} · {contextLens ? 'absolute scale · suitability lens' : 'global field'} · NASA POWER climatology
            </span>
          </>
        ) : (
          <span className="legend-note">Cesium World Imagery + World Terrain · day/night city lights</span>
        )}
      </footer>
    </main>
  )
}
