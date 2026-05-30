import type { ReactElement } from 'react'
import type { Variability } from './lib/api'

const W = 252
const H = 60

// A compact P10–P90 band + P50 line sparkline (inline SVG; no charting dependency).
export function FanChart({ data, accent }: { data: Variability; accent: string }): ReactElement {
  const n = data.p50.length
  if (n < 2) return <p className="variab-note">No forecast data.</p>
  const maxY = Math.max(...data.p90, 1)
  const x = (i: number): number => (i / (n - 1)) * W
  const y = (val: number): number => H - (val / maxY) * (H - 2) - 1

  const band = [
    ...data.p90.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`),
    ...data.p10.map((_, i) => {
      const j = n - 1 - i
      return `${x(j).toFixed(1)},${y(data.p10[j] ?? 0).toFixed(1)}`
    }),
  ].join(' ')
  const line = data.p50
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p).toFixed(1)}`)
    .join(' ')

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="fan" role="img" aria-label="generation fan">
      <polygon points={band} fill={accent} opacity={0.18} />
      <path d={line} fill="none" stroke={accent} strokeWidth={1.5} />
    </svg>
  )
}
