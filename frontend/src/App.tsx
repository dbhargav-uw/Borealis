import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactElement } from 'react'
import { SuitabilityGlobe, type GlobeHandle } from './SuitabilityGlobe'
import {
  fetchAsk,
  fetchBriefing,
  fetchSuitability,
  fetchVariability,
  LAYERS,
  regionCenter,
  type LayerDef,
  type RankedSite,
  type Region,
  type SiteBriefing,
  type SuitabilityData,
  type Variability,
} from './lib/api'
import { FanChart } from './FanChart'
import { logger } from './lib/logger'
import './App.css'

const DEFAULT_REGION: Region = { lat_min: 36, lon_min: -10, lat_max: 44, lon_max: 0 }
const DEFAULT_LABEL = 'Iberian Peninsula'
const FALLBACK_LAYER: LayerDef = LAYERS[0]!

type State =
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

function useWindowSize(): { width: number; height: number } {
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  useEffect(() => {
    const onResize = (): void => setSize({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return size
}

export function App(): ReactElement {
  const [region, setRegion] = useState<Region>(DEFAULT_REGION)
  const [regionLabel, setRegionLabel] = useState<string>(DEFAULT_LABEL)
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [activeLayer, setActiveLayer] = useState<string>('solar')
  const [selected, setSelected] = useState<RankedSite | null>(null)
  const [brief, setBrief] = useState<BriefState>({ kind: 'idle' })
  const [variab, setVariab] = useState<VarState>({ kind: 'idle' })
  const [query, setQuery] = useState<string>('')
  const [asking, setAsking] = useState<boolean>(false)
  const [askError, setAskError] = useState<string | null>(null)
  const [landOnly, setLandOnly] = useState<boolean>(true)
  const globeRef = useRef<GlobeHandle>(null)
  const { width, height } = useWindowSize()

  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    const run = async (): Promise<void> => {
      try {
        const data = await fetchSuitability(region, landOnly)
        if (!cancelled) setState({ kind: 'ok', data })
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error'
        logger.error('suitability fetch failed', err)
        if (!cancelled) setState({ kind: 'error', message })
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [region, landOnly])

  const layer = LAYERS.find((l) => l.id === activeLayer) ?? FALLBACK_LAYER
  const accent = layer.accent
  const data = state.kind === 'ok' ? state.data : null
  const sites = useMemo<RankedSite[]>(() => (data ? data.sites[activeLayer] ?? [] : []), [data, activeLayer])

  useEffect(() => {
    setSelected(sites[0] ?? null)
  }, [sites])

  useEffect(() => {
    setBrief({ kind: 'idle' })
    setVariab({ kind: 'idle' })
  }, [activeLayer, region])

  if (state.kind === 'loading') {
    return (
      <main className="screen">
        <div className="splash">
          <h1>Borealis</h1>
          <p>Scanning climatology for the best places to build…</p>
        </div>
      </main>
    )
  }
  if (state.kind === 'error') {
    return (
      <main className="screen">
        <div className="splash splash--error">
          <h1>Borealis</h1>
          <p>Couldn’t load suitability data.</p>
          <code>{state.message}</code>
          <p className="hint">Is the backend up? <code>cd backend &amp;&amp; uv run uvicorn api.main:app --reload</code></p>
        </div>
      </main>
    )
  }

  const unit = state.data.units[activeLayer] ?? ''
  const onPick = (site: RankedSite): void => {
    setSelected(site)
    setVariab({ kind: 'idle' })
    globeRef.current?.flyTo(site.lat, site.lng)
  }
  const onAsk = (e: FormEvent): void => {
    e.preventDefault()
    if (!query.trim() || asking) return
    setAsking(true)
    setAskError(null)
    void (async (): Promise<void> => {
      try {
        const res = await fetchAsk(query.trim())
        setRegionLabel(res.label)
        setActiveLayer(res.lens)
        setRegion(res.region)
      } catch (err) {
        setAskError(err instanceof Error ? err.message : 'Search failed')
      } finally {
        setAsking(false)
      }
    })()
  }
  const onExplain = (): void => {
    setBrief({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const b = await fetchBriefing(region, layer, regionLabel, landOnly)
        setBrief(b ? { kind: 'ok', briefing: b } : { kind: 'none' })
      } catch (err) {
        setBrief({ kind: 'error', message: err instanceof Error ? err.message : 'Briefing failed' })
      }
    })()
  }
  const onVariability = (): void => {
    if (!selected) return
    const site = selected
    setVariab({ kind: 'loading' })
    void (async (): Promise<void> => {
      try {
        const d = await fetchVariability(site.lat, site.lng, activeLayer)
        setVariab({ kind: 'ok', data: d })
      } catch (err) {
        setVariab({ kind: 'error', message: err instanceof Error ? err.message : 'Forecast failed' })
      }
    })()
  }

  return (
    <main className="screen">
      <div className="globe-wrap">
        <SuitabilityGlobe
          ref={globeRef}
          cells={state.data.cells}
          sites={sites}
          layerId={activeLayer}
          accent={accent}
          width={width}
          height={height}
          focus={regionCenter(state.data.region)}
          onSiteClick={onPick}
        />
      </div>

      <header className="hud hud--top">
        <h1>Borealis</h1>
        <p className="tagline">Where on Earth to build — solar, wind &amp; cropland</p>
        <form className="ask" onSubmit={onAsk}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask the globe — e.g. “best wind sites in Scotland”"
            aria-label="Ask the globe"
          />
          <button type="submit" disabled={asking}>{asking ? '…' : 'Ask'}</button>
        </form>
        {askError && <p className="ask-error">{askError}</p>}
        <div className="lens-toggle" role="group" aria-label="Suitability layer">
          {LAYERS.map((l) => (
            <button
              key={l.id}
              type="button"
              className={l.id === activeLayer ? 'lens lens--active' : 'lens'}
              style={l.id === activeLayer ? { borderColor: l.accent, color: l.accent } : undefined}
              onClick={() => setActiveLayer(l.id)}
            >
              {l.label}
            </button>
          ))}
        </div>
        <label className="offshore">
          <input type="checkbox" checked={!landOnly} onChange={(e) => setLandOnly(!e.target.checked)} />
          Include offshore
        </label>
        <p className="region-label">{regionLabel}</p>
      </header>

      <section className="hud hud--sites">
        <div className="sites-head">
          <h2 style={{ color: accent }}>Top sites · {layer.name}</h2>
          <button type="button" className="explain-btn" onClick={onExplain}>✨ Explain</button>
        </div>
        <ol>
          {sites.length === 0 && <li className="empty">No scorable cells in this region.</li>}
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

      {brief.kind !== 'idle' && (
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

      {selected && (
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
            <span className="detail-label">{layer.metricLabel}</span>
            <span>{(selected.metrics[layer.metricKey] ?? 0).toFixed(0)} {unit}</span>
          </p>
          <ul className="caveats">
            {selected.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
          {layer.vertical === 'energy' && (
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

      <footer className="hud hud--legend">
        <span>low</span>
        <span className="ramp" style={{ background: `linear-gradient(90deg, #12162866, ${accent})` }} />
        <span>high</span>
        <span className="legend-note">relative across region · NASA POWER climatology, not bankable yield</span>
      </footer>
    </main>
  )
}
