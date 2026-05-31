import type { ReactElement } from 'react'
import type { Seasonal } from './lib/api'

const W = 252
const H = 54
const MONTHS = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']

// A compact 12-month climatology sparkline (inline SVG; no charting dependency).
export function SeasonalChart({ data, accent }: { data: Seasonal; accent: string }): ReactElement {
  const n = data.months.length
  if (n < 2) return <p className="variab-note">No seasonal data.</p>
  const max = Math.max(...data.months)
  const min = Math.min(...data.months)
  const span = max - min || 1
  const x = (i: number): number => (i / (n - 1)) * (W - 8) + 4
  const y = (v: number): number => H - 14 - ((v - min) / span) * (H - 22)

  const line = data.months.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${x(n - 1).toFixed(1)},${H - 12} L${x(0).toFixed(1)},${H - 12} Z`

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="fan" role="img" aria-label="seasonal profile">
      <path d={area} fill={accent} opacity={0.16} />
      <path d={line} fill="none" stroke={accent} strokeWidth={1.5} />
      {data.months.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={1.5} fill={accent} />
      ))}
      {MONTHS.map((m, i) => (
        <text key={i} x={x(i)} y={H - 2} fontSize={6.5} fill="#8b93a7" textAnchor="middle">{m}</text>
      ))}
    </svg>
  )
}
