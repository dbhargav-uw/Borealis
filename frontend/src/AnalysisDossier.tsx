import type { ReactElement, ReactNode } from 'react'
import type { Analysis, ResourceLens } from './lib/api'

// The per-location RISK ANALYSIS dossier (left panel). Opens on building placement, closes on reset.
// Presentational only: App owns the single /api/analysis fetch and passes the state in. Every section
// carries its data source + the honesty framing (relative comparator / illustrative / not advice).

export type AnalysisState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: Analysis }

interface Placement {
  label: string
  buildingType: string
  intent: string
  lat: number
  lng: number
  baseHeight: number
}

function scoreClass(score: number): string {
  return score >= 0.66 ? 'high' : score >= 0.4 ? 'medium' : 'low'
}

function LensRow({ label, accent, lens }: { label: string; accent: string; lens: ResourceLens }): ReactElement {
  return (
    <div className="dossier-lens">
      <div className="dossier-lens-head">
        <span className="dossier-lens-label">{label}</span>
        <span className={`conf conf--${scoreClass(lens.score)}`}>{(lens.score * 100).toFixed(0)} / 100</span>
      </div>
      <div className="bar">
        <span style={{ width: `${Math.max(2, lens.score * 100)}%`, background: accent }} />
      </div>
      <p className="dossier-read">{lens.read}</p>
      <p className="dossier-metric">
        {lens.rawMetric.toFixed(0)} {lens.units}
      </p>
    </div>
  )
}

function Section({ icon, title, children }: { icon: string; title: string; children: ReactNode }): ReactElement {
  return (
    <section className="dossier-section">
      <h3 className="dossier-h">
        <span aria-hidden>{icon}</span> {title}
      </h3>
      {children}
    </section>
  )
}

export function AnalysisDossier({
  placement,
  state,
  onClose,
}: {
  placement: Placement
  state: AnalysisState
  onClose: () => void
}): ReactElement {
  const data = state.kind === 'ok' ? state.data : null

  return (
    <aside className="hud hud--dossier">
      <div className="place-head">
        <strong>🛡 Risk analysis · {placement.label}</strong>
        <button type="button" className="link-btn" onClick={onClose}>
          close
        </button>
      </div>

      {state.kind === 'loading' && <p className="dossier-loading">Composing the location dossier…</p>}
      {state.kind === 'error' && <p className="dossier-loading">Analysis unavailable: {state.message}</p>}

      {data && (
        <>
          {/* 1) LOCATION */}
          <Section icon="📍" title="Location">
            <p className="place-sub">
              {data.location.placeName ?? placement.label}
            </p>
            <p className="dossier-read">
              {data.location.lat.toFixed(3)}, {data.location.lon.toFixed(3)} · {data.location.terrain}
            </p>
            <p className="dossier-read">
              {data.location.buildingType} · intent: {data.location.intent}
            </p>
            <p className="dossier-fine">
              Shown as a <strong>representative</strong> {data.location.buildingType} model — not the actual structure on this parcel.
            </p>
          </Section>

          {/* 2) RENEWABLE RESOURCE — relative comparator, never bankable yield */}
          <Section icon="⚡" title="Renewable resource">
            {data.resource.available ? (
              <>
                {data.resource.solar && <LensRow label="☀ Solar" accent="#ffd140" lens={data.resource.solar} />}
                {data.resource.wind && <LensRow label="🌀 Wind" accent="#4ed6ff" lens={data.resource.wind} />}
                {data.resource.crop && <LensRow label="🌱 Cropland" accent="#7ce38b" lens={data.resource.crop} />}
                <p className="dossier-fine">
                  {data.resource.note} <span className="dossier-src">{data.resource.source}</span>
                </p>
              </>
            ) : (
              <p className="dossier-read">{data.resource.message ?? 'Resource climatology unavailable here.'}</p>
            )}
          </Section>

          {/* 3) HAZARD EXPOSURE — grounded real data; scenarios labeled illustrative */}
          <Section icon="🌊" title="Hazard exposure">
            <div className="dossier-hazard">
              <span className="dossier-hazard-tag">Flood</span>
              <p className="dossier-read">{data.hazards.flood.exposure}</p>
              <p className="dossier-fine">
                <span className="dossier-illus">Illustrative scenario</span> · {data.hazards.flood.scenarioNote}{' '}
                <span className="dossier-src">{data.hazards.flood.source}</span>
              </p>
            </div>
            <div className="dossier-hazard">
              <span className="dossier-hazard-tag">🌪 Tornado / severe storm</span>
              <p className="dossier-read">{data.hazards.tornado.read}</p>
              <p className="dossier-fine">
                <span className="dossier-illus">Illustrative climatology</span> · {data.hazards.tornado.scenarioNote}{' '}
                <span className="dossier-src">{data.hazards.tornado.source}</span>
              </p>
            </div>
            <div className="dossier-hazard">
              <span className="dossier-hazard-tag">
                <span className="live-badge">● LIVE</span> Active storms / alerts
              </span>
              <p className="dossier-read">
                {data.hazards.live.available ? data.hazards.live.summary : 'Live feeds currently unavailable.'}
              </p>
              <p className="dossier-fine">
                {data.hazards.live.coverage}{' '}
                <span className="dossier-src">
                  {data.hazards.live.source}
                  {data.hazards.live.asOf ? ` · as of ${new Date(data.hazards.live.asOf).toUTCString().slice(5, 22)} UTC` : ''}
                </span>
              </p>
            </div>
          </Section>

          {/* 4) INSURANCE — illustrative / educational, NOT advice */}
          <Section icon="📋" title="Insurance considerations">
            <p className="dossier-notadvice">⚠ Illustrative &amp; educational only — not insurance advice, a quote, or a financial recommendation.</p>
            {data.insurance.length > 0 ? (
              <ul className="dossier-insurance">
                {data.insurance.map((ins, i) => (
                  <li key={i}>
                    <span className="chip">{ins.kind}</span>
                    <span className="dossier-read">{ins.consideration}</span>
                    <span className="dossier-fine">{ins.rationale}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="dossier-fine">
                AI considerations unavailable — set <code>ANTHROPIC_API_KEY</code> to enable the synthesis.
              </p>
            )}
          </Section>

          {/* 5) SUMMARY — Anthropic synthesis, grounded only in the numbers above */}
          <Section icon="🧭" title="Summary">
            {data.summary ? (
              <p className="dossier-read">{data.summary}</p>
            ) : (
              <p className="dossier-fine">
                AI summary unavailable — set <code>ANTHROPIC_API_KEY</code>. The structured sections above stand alone.
              </p>
            )}
          </Section>

          <p className="dossier-disclaimer">{data.disclaimer}</p>
        </>
      )}
    </aside>
  )
}
