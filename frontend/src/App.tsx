import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactElement } from 'react'
import { SuitabilityGlobe, type GlobeHandle } from './SuitabilityGlobe'
import {
  fetchAsk,
  fetchBriefing,
  fetchSuitability,
  regionCenter,
  type Lens,
  type RankedSite,
  type Region,
  type SiteBriefing,
  type SuitabilityData,
} from './lib/api'
import { LENS_ACCENT } from './lib/colors'
import { logger } from './lib/logger'
import './App.css'

const DEFAULT_REGION: Region = { lat_min: 36, lon_min: -10, lat_max: 44, lon_max: 0 }
const DEFAULT_LABEL = 'Iberian Peninsula'

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

function useWindowSize(): { width: number; height: number } {
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  useEffect(() => {
    const onResize = (): void => setSize({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return size
}

function headlineMetric(site: RankedSite, lens: Lens): { label: string; value: string } {
  if (lens === 'solar') {
    const yld = site.metrics['specific_yield_kwh_kwp_yr'] ?? 0
    const cf = (site.metrics['capacity_factor'] ?? 0) * 100
    return { label: 'Specific yield', value: `${yld.toFixed(0)} kWh/kWp·yr · CF ${cf.toFixed(0)}%` }
  }
  const wpd = site.metrics['wind_power_density_wm2'] ?? 0
  const v = site.metrics['mean_wind_50m_ms'] ?? 0
  return { label: 'Wind power density', value: `${wpd.toFixed(0)} W/m² · ${v.toFixed(1)} m/s @50m` }
}

export function App(): ReactElement {
  const [region, setRegion] = useState<Region>(DEFAULT_REGION)
  const [regionLabel, setRegionLabel] = useState<string>(DEFAULT_LABEL)
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [lens, setLens] = useState<Lens>('solar')
  const [selected, setSelected] = useState<RankedSite | null>(null)
  const [brief, setBrief] = useState<BriefState>({ kind: 'idle' })
  const [query, setQuery] = useState<string>('')
  const [asking, setAsking] = useState<boolean>(false)
  const [askError, setAskError] = useState<string | null>(null)
  const globeRef = useRef<GlobeHandle>(null)
  const { width, height } = useWindowSize()

  // (Re)load suitability whenever the region changes.
  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    const run = async (): Promise<void> => {
      try {
        const data = await fetchSuitability(region)
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
  }, [region])

  const data = state.kind === 'ok' ? state.data : null
  const sites = useMemo<RankedSite[]>(() => (data ? data.sites[lens] : []), [data, lens])

  useEffect(() => {
    setSelected(sites[0] ?? null)
  }, [sites])

  // The briefing is specific to (region, lens) — reset it when either changes.
  useEffect(() => {
    setBrief({ kind: 'idle' })
  }, [lens, region])

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

  const accent = LENS_ACCENT[lens]

  const onPick = (site: RankedSite): void => {
    setSelected(site)
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
        setLens(res.lens)
        setRegion(res.region) // triggers a reload + the globe reframes
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
        const b = await fetchBriefing(region, lens, regionLabel)
        setBrief(b ? { kind: 'ok', briefing: b } : { kind: 'none' })
      } catch (err) {
        setBrief({ kind: 'error', message: err instanceof Error ? err.message : 'Briefing failed' })
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
          lens={lens}
          width={width}
          height={height}
          focus={regionCenter(state.data.region)}
          onSiteClick={onPick}
        />
      </div>

      <header className="hud hud--top">
        <h1>Borealis</h1>
        <p className="tagline">Where on Earth to build solar &amp; wind</p>
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
        <div className="lens-toggle" role="group" aria-label="Resource lens">
          {(['solar', 'wind'] as const).map((l) => (
            <button
              key={l}
              type="button"
              className={l === lens ? 'lens lens--active' : 'lens'}
              style={l === lens ? { borderColor: accent, color: accent } : undefined}
              onClick={() => setLens(l)}
            >
              {l === 'solar' ? '☀ Solar' : '🌀 Wind'}
            </button>
          ))}
        </div>
        <p className="region-label">{regionLabel}</p>
      </header>

      <section className="hud hud--sites">
        <div className="sites-head">
          <h2 style={{ color: accent }}>Top sites · {lens}</h2>
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
          {(() => {
            const m = headlineMetric(selected, lens)
            return (
              <p className="detail-metric">
                <span className="detail-label">{m.label}</span>
                <span>{m.value}</span>
              </p>
            )
          })()}
          <ul className="caveats">
            {selected.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
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
