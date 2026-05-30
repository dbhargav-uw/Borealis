import { useEffect, useState, type ReactElement } from 'react'
import { fetchHealth, type Health } from './lib/api'
import { logger } from './lib/logger'
import borealisMark from './assets/borealis-mark.svg'
import './App.css'

type ConnState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; health: Health }

function StatusPanel({ state }: { state: ConnState }): ReactElement {
  switch (state.kind) {
    case 'loading':
      return <p className="status status--loading">Connecting to backend…</p>
    case 'error':
      return (
        <div className="status status--error">
          <p className="status__title">Backend unreachable</p>
          <code>{state.message}</code>
          <p className="hint">
            Is it running? <code>cd backend &amp;&amp; uv run uvicorn api.main:app --reload</code>
          </p>
        </div>
      )
    case 'ok':
      return (
        <div className="status status--ok">
          <p className="status__title">Connected</p>
          <dl>
            <dt>service</dt>
            <dd>{state.health.service}</dd>
            <dt>version</dt>
            <dd>{state.health.version}</dd>
            <dt>status</dt>
            <dd>{state.health.status}</dd>
          </dl>
        </div>
      )
  }
}

export function App(): ReactElement {
  const [state, setState] = useState<ConnState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const run = async (): Promise<void> => {
      try {
        const health = await fetchHealth()
        if (!cancelled) setState({ kind: 'ok', health })
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error'
        logger.error('health check failed', err)
        if (!cancelled) setState({ kind: 'error', message })
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="app">
      <div className="brand">
        <img className="brand__mark" src={borealisMark} alt="" aria-hidden width={56} height={56} />
        <h1>Borealis</h1>
      </div>
      <p className="tagline">Weather-risk decision platform · Phase 1 scaffold</p>
      <StatusPanel state={state} />
    </main>
  )
}
