import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  type ReactElement,
} from 'react'
import Globe, { type GlobeMethods } from 'react-globe.gl'
import type { Lens, RankedSite, SuitabilityCell } from './lib/api'
import { LENS_ACCENT, scoreColor } from './lib/colors'

export interface GlobeHandle {
  flyTo: (lat: number, lng: number, altitude?: number) => void
}

interface Props {
  cells: SuitabilityCell[]
  sites: RankedSite[]
  lens: Lens
  width: number
  height: number
  focus: { lat: number; lng: number }
  onSiteClick: (site: RankedSite) => void
}

const EARTH_DARK = '/earth-dark.jpg' // bundled in public/ (same-origin; avoids CORS)

function weightOf(cell: SuitabilityCell, lens: Lens): number {
  return lens === 'solar' ? cell.solarScore : cell.windScore
}

export const SuitabilityGlobe = forwardRef<GlobeHandle, Props>(function SuitabilityGlobe(
  { cells, sites, lens, width, height, focus, onSiteClick },
  ref,
): ReactElement {
  const globeRef = useRef<GlobeMethods | undefined>(undefined)

  useImperativeHandle(
    ref,
    () => ({
      flyTo: (lat: number, lng: number, altitude = 0.55): void => {
        globeRef.current?.pointOfView({ lat, lng, altitude }, 1200)
      },
    }),
    [],
  )

  // Gentle auto-rotate + frame the region once the globe is mounted.
  useEffect(() => {
    const globe = globeRef.current
    if (!globe) return
    const controls = globe.controls()
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.3
    globe.pointOfView({ lat: focus.lat, lng: focus.lng, altitude: 1.5 }, 0)
    // focus only matters for the initial frame; subsequent moves go through flyTo
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Accessors recomputed per lens so the field recolors on toggle.
  const pointColor = useMemo(
    () => (d: object): string => scoreColor(weightOf(d as SuitabilityCell, lens), lens),
    [lens],
  )
  const pointAltitude = useMemo(
    () => (d: object): number => 0.01 + 0.22 * weightOf(d as SuitabilityCell, lens),
    [lens],
  )
  const accent = LENS_ACCENT[lens]

  return (
    <Globe
      ref={globeRef}
      width={width}
      height={height}
      globeImageUrl={EARTH_DARK}
      backgroundColor="rgba(0,0,0,0)"
      showAtmosphere
      atmosphereColor={accent}
      atmosphereAltitude={0.18}
      // --- suitability field ---
      pointsData={cells}
      pointLat="lat"
      pointLng="lng"
      pointColor={pointColor}
      pointAltitude={pointAltitude}
      pointRadius={0.3}
      pointsMerge={false}
      pointsTransitionDuration={600}
      // --- ranked sites: glowing rings + rank labels ---
      ringsData={sites}
      ringLat="lat"
      ringLng="lng"
      ringColor={(): string => accent}
      ringMaxRadius={3.5}
      ringPropagationSpeed={1.6}
      ringRepeatPeriod={1000}
      labelsData={sites}
      labelLat="lat"
      labelLng="lng"
      labelText={(d: object): string => `#${(d as RankedSite).rank}`}
      labelSize={1.5}
      labelDotRadius={0.45}
      labelColor={(): string => '#ffffff'}
      labelResolution={2}
      onLabelClick={(d: object): void => onSiteClick(d as RankedSite)}
    />
  )
})
