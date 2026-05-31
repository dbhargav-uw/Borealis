import { Component, type ErrorInfo, type ReactNode } from 'react'
import { logger } from './lib/logger'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  error: Error | null
}

// Top-level error boundary: turns a render or lazy-chunk crash into a visible, logged message
// instead of a blank white screen. (A common trigger is a stale Vite optimized-deps cache after
// an .env/config change — the open tab holds old hashed module URLs that now 404, so the lazy
// globe import rejects.) React 19 still has no hook equivalent, so this is a class component.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logger.error('UI crashed (caught by ErrorBoundary):', error, info.componentStack)
  }

  private handleReload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    const { error } = this.state
    if (error) {
      if (this.props.fallback !== undefined) return this.props.fallback
      return (
        <div className="boundary">
          <h2>Something broke while rendering.</h2>
          <code>{error.message}</code>
          <p className="hint">
            Often a stale dev cache after an <code>.env</code>/config change. Hard-reload
            (<kbd>⌘⇧R</kbd>), or stop Vite and run <code>rm -rf node_modules/.vite &amp;&amp; npm run dev</code>.
          </p>
          <button type="button" onClick={this.handleReload}>Reload</button>
        </div>
      )
    }
    return this.props.children
  }
}
