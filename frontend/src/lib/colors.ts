// Suitability color scale: a single-hue intensity ramp per lens (dark base -> bright lens
// color as the 0..1 score rises). Solar = warm gold, wind = cool cyan.

import type { Lens } from './api'

const BASE: readonly [number, number, number] = [18, 22, 40]
const HIGH: Record<Lens, readonly [number, number, number]> = {
  solar: [255, 209, 64],
  wind: [78, 214, 255],
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

export function scoreColor(score: number, lens: Lens): string {
  const t = clamp01(score)
  const high = HIGH[lens]
  const mix = (a: number, b: number): number => Math.round(a + (b - a) * t)
  return `rgb(${mix(BASE[0], high[0])}, ${mix(BASE[1], high[1])}, ${mix(BASE[2], high[2])})`
}

export const LENS_ACCENT: Record<Lens, string> = {
  solar: '#ffd140',
  wind: '#4ed6ff',
}
