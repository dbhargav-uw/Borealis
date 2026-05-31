import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactElement,
} from 'react'
import { Entity, ImageryLayer, Viewer, useCesium, type CesiumComponentRef } from 'resium'
import {
  buildModuleUrl,
  Cartesian2,
  Cartesian3,
  Color,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  defined,
  Ion,
  LabelStyle,
  NearFarScalar,
  Rectangle,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  SingleTileImageryProvider,
  TileMapServiceImageryProvider,
  VerticalOrigin,
  Viewer as CesiumViewer,
  type ImageryProvider,
  type TerrainProvider,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import type { RankedSite } from './lib/api'

export interface GlobeHandle {
  flyTo: (lat: number, lng: number, altitude?: number) => void
}

interface Props {
  sites: RankedSite[]
  layerId: string
  accent: string
  focus: { lat: number; lng: number }
  selectedRank: number | null
  onSiteClick: (site: RankedSite) => void
}

interface Control {
  flyTo: (lat: number, lng: number, altitude?: number) => void
}

const ION_TOKEN = (import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined)?.trim()
const FIELD_LENSES = new Set(['solar', 'wind'])
const RESUME_SPIN_MS = 4500
const FIELD_ALPHA = 0.66

// --- inner scene: owns the live viewer (auto-rotate, click-pick, flyTo, markers) ----------

interface SceneProps extends Props {
  base: ImageryProvider | null
  field: ImageryProvider | null
  control: React.MutableRefObject<Control | null>
}

function GlobeScene({
  base,
  field,
  sites,
  accent,
  focus,
  selectedRank,
  onSiteClick,
  control,
}: SceneProps): ReactElement {
  const { viewer } = useCesium()
  const spinningRef = useRef<boolean>(false)
  const resumeTimer = useRef<number | null>(null)
  const onSiteClickRef = useRef(onSiteClick)
  const sitesRef = useRef(sites)
  const firstFocus = useRef<boolean>(true)
  onSiteClickRef.current = onSiteClick
  sitesRef.current = sites

  const accentColor = useMemo(() => Color.fromCssColorString(accent), [accent])

  useEffect(() => {
    if (!viewer) return
    const scene = viewer.scene
    // The headline feature is the resource field shown CONSISTENTLY everywhere, so we keep the
    // globe evenly lit (no day/night terminator darkening half the field) while still keeping the
    // atmosphere + ground-atmosphere + fog for a premium look. (Flip enableLighting on for the
    // sun-terminator look if realism is preferred over uniform field legibility.)
    scene.globe.enableLighting = false
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = true
    scene.fog.enabled = true
    scene.globe.baseColor = Color.fromCssColorString('#05070f')
    scene.globe.showGroundAtmosphere = true
    viewer.useBrowserRecommendedResolution = false
    viewer.resolutionScale = Math.min(window.devicePixelRatio || 1, 2)

    // a wide opening view that shows the whole continuous field; gentle spin after idle
    viewer.camera.setView({ destination: Cartesian3.fromDegrees(focus.lng, 12, 26_000_000) })

    const scheduleResume = (): void => {
      if (resumeTimer.current !== null) window.clearTimeout(resumeTimer.current)
      resumeTimer.current = window.setTimeout(() => {
        spinningRef.current = true
      }, RESUME_SPIN_MS)
    }
    const pauseSpin = (): void => {
      spinningRef.current = false
      scheduleResume()
    }
    scheduleResume()

    const flyTo = (lat: number, lng: number, altitude = 900_000): void => {
      spinningRef.current = false
      if (resumeTimer.current !== null) window.clearTimeout(resumeTimer.current)
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(lng, lat, altitude),
        duration: 1.6,
        complete: scheduleResume,
      })
    }
    control.current = { flyTo }

    const spinAxis = Cartesian3.UNIT_Z
    const onTick = (): void => {
      if (spinningRef.current) viewer.camera.rotate(spinAxis, -0.0009)
    }
    viewer.clock.onTick.addEventListener(onTick)

    const canvas = scene.canvas
    const onInteract = (): void => pauseSpin()
    canvas.addEventListener('pointerdown', onInteract)
    canvas.addEventListener('wheel', onInteract, { passive: true })

    const handler = new ScreenSpaceEventHandler(canvas)
    handler.setInputAction((movement: ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = scene.pick(movement.position)
      const id = defined(picked) && picked && picked.id ? (picked.id as { id?: string }).id : undefined
      if (id && id.startsWith('site-')) {
        const rank = Number(id.slice(5))
        const site = sitesRef.current.find((s) => s.rank === rank)
        if (site) onSiteClickRef.current(site)
      }
    }, ScreenSpaceEventType.LEFT_CLICK)

    return () => {
      viewer.clock.onTick.removeEventListener(onTick)
      canvas.removeEventListener('pointerdown', onInteract)
      canvas.removeEventListener('wheel', onInteract)
      handler.destroy()
      if (resumeTimer.current !== null) window.clearTimeout(resumeTimer.current)
      control.current = null
    }
  }, [viewer, control]) // eslint-disable-line react-hooks/exhaustive-deps

  // fly to a newly-queried region (skip the very first render, which sets the opening view)
  useEffect(() => {
    if (firstFocus.current) {
      firstFocus.current = false
      return
    }
    control.current?.flyTo(focus.lat, focus.lng, 3_500_000)
  }, [focus.lat, focus.lng, control])

  return (
    <>
      {base && <ImageryLayer imageryProvider={base} />}
      {field && <ImageryLayer key="field" imageryProvider={field} alpha={FIELD_ALPHA} />}
      {sites.map((s) => {
        const selected = s.rank === selectedRank
        return (
          <Entity
            key={s.rank}
            id={`site-${s.rank}`}
            position={Cartesian3.fromDegrees(s.lng, s.lat)}
            point={{
              pixelSize: selected ? 18 : 12,
              color: accentColor,
              outlineColor: Color.WHITE.withAlpha(selected ? 0.95 : 0.6),
              outlineWidth: selected ? 3 : 2,
              scaleByDistance: new NearFarScalar(1.0e6, 1.4, 2.0e7, 0.55),
            }}
            label={{
              text: `#${s.rank}`,
              font: '600 13px Inter, system-ui, sans-serif',
              fillColor: Color.WHITE,
              style: LabelStyle.FILL_AND_OUTLINE,
              outlineColor: Color.fromCssColorString('#05070f'),
              outlineWidth: 3,
              verticalOrigin: VerticalOrigin.BOTTOM,
              pixelOffset: new Cartesian2(0, -16),
              showBackground: true,
              backgroundColor: Color.fromCssColorString('#0b1020').withAlpha(0.7),
              backgroundPadding: new Cartesian2(6, 4),
              translucencyByDistance: new NearFarScalar(4.0e6, 1.0, 2.2e7, 0.0),
            }}
          />
        )
      })}
    </>
  )
}

// --- outer wrapper: resolves base/terrain/field providers, then mounts the Viewer ----------

export const ResourceGlobe = forwardRef<GlobeHandle, Props>(function ResourceGlobe(
  props,
  ref,
): ReactElement {
  const viewerRef = useRef<CesiumComponentRef<CesiumViewer>>(null)
  const control = useRef<Control | null>(null)
  const [base, setBase] = useState<ImageryProvider | null>(null)
  const [terrain, setTerrain] = useState<TerrainProvider | undefined>(undefined)
  const [field, setField] = useState<ImageryProvider | null>(null)

  useImperativeHandle(
    ref,
    () => ({
      flyTo: (lat: number, lng: number, altitude?: number): void =>
        control.current?.flyTo(lat, lng, altitude),
    }),
    [],
  )

  // base imagery + terrain (vivid earth via ion token; offline Natural Earth II without one)
  useEffect(() => {
    let cancelled = false
    const offlineBase = async (): Promise<void> => {
      const img = await TileMapServiceImageryProvider.fromUrl(
        buildModuleUrl('Assets/Textures/NaturalEarthII'),
      )
      if (!cancelled) setBase(img)
    }
    void (async (): Promise<void> => {
      try {
        if (ION_TOKEN) {
          Ion.defaultAccessToken = ION_TOKEN
          const [img, terr] = await Promise.all([
            createWorldImageryAsync(),
            createWorldTerrainAsync(),
          ])
          if (!cancelled) {
            setBase(img)
            setTerrain(terr)
          }
        } else {
          await offlineBase()
        }
      } catch {
        try {
          await offlineBase() // bad token / offline -> still render a colorful earth
        } catch {
          /* leave base null; the globe still renders on the ellipsoid */
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // field texture for the active lens (solar/wind only; cropland has no field layer)
  useEffect(() => {
    let cancelled = false
    if (!FIELD_LENSES.has(props.layerId)) {
      setField(null)
      return
    }
    void (async (): Promise<void> => {
      try {
        const provider = await SingleTileImageryProvider.fromUrl(`/fields/${props.layerId}.png`, {
          rectangle: Rectangle.MAX_VALUE,
        })
        if (!cancelled) setField(provider)
      } catch {
        if (!cancelled) setField(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [props.layerId])

  if (!base) {
    return (
      <div className="globe-loading">
        <span>Spinning up the globe…</span>
      </div>
    )
  }

  return (
    <Viewer
      ref={viewerRef}
      full
      baseLayer={false}
      terrainProvider={terrain}
      baseLayerPicker={false}
      geocoder={false}
      homeButton={false}
      sceneModePicker={false}
      navigationHelpButton={false}
      fullscreenButton={false}
      timeline={false}
      animation={false}
      infoBox={false}
      selectionIndicator={false}
    >
      <GlobeScene {...props} base={base} field={field} control={control} />
    </Viewer>
  )
})
