// Suitability color scale: a single-hue intensity ramp from a dark base to the layer's
// accent color as the 0..1 score rises.

const BASE: readonly [number, number, number] = [18, 22, 40]

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

export function scoreColor(score: number, accentHex: string): string {
  const t = clamp01(score)
  const high = hexToRgb(accentHex)
  const mix = (a: number, b: number): number => Math.round(a + (b - a) * t)
  return `rgb(${mix(BASE[0], high[0])}, ${mix(BASE[1], high[1])}, ${mix(BASE[2], high[2])})`
}
