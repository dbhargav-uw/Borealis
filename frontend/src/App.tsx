import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { SuitabilityGlobe, type GlobeHandle } from './SuitabilityGlobe'
import {
  fetchSuitability,
  regionCenter,
  type Lens,
  type RankedSite,
  type Region,
  type SuitabilityData,
} from './lib/api'
import { LENS_ACCENT } from './lib/colors'
import { logger } from './lib/logger'
import './App.css'

// MVP demo region (NASA POWER regional is capped at 10°/axis). The "ask the globe" NL
// search (P4) will let the user pick any region.
const DEFAULT_REGION: Region = { lat_min: 36, lon_min: -10, lat_max: 44, lon_max: 0 }
const REGION_NAME = 'Iberian Peninsula'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: SuitabilityData }

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
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [lens, setLens] = useState<Lens>('solar')
  const [selected, setSelected] = useState<RankedSite | null>(null)
  const globeRef = useRef<GlobeHandle>(null)
  const { width, height } = useWindowSize()

  useEffect(() => {
    let cancelled = false
    const run = async (): Promise<void> => {
      try {
        const data = await fetchSuitability(DEFAULT_REGION)
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
  }, [])

  const data = state.kind === 'ok' ? state.data : null
  const sites = useMemo<RankedSite[]>(() => (data ? data.sites[lens] : []), [data, lens])

  // Reset the selected site to the best one whenever the lens (or data) changes.
  useEffect(() => {
    setSelected(sites[0] ?? null)
  }, [sites])

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
        <p className="tagline">Where on Earth to build solar &amp; wind — {REGION_NAME}</p>
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
      </header>

      <section className="hud hud--sites">
        <h2 style={{ color: accent }}>Top sites · {lens}</h2>
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
