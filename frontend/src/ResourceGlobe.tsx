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
  CallbackPositionProperty,
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Cartographic,
  Cesium3DTileset,
  Color,
  createOsmBuildingsAsync,
  createWorldImageryAsync,
  createWorldTerrainAsync,
  defined,
  Entity as CesiumEntity,
  HeadingPitchRange,
  HeadingPitchRoll,
  Ion,
  IonGeocoderService,
  IonImageryProvider,
  LabelStyle,
  Math as CesiumMath,
  NearFarScalar,
  Quaternion,
  Rectangle,
  sampleTerrainMostDetailed,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  ShadowMode,
  Transforms,
  TranslationRotationScale,
  SingleTileImageryProvider,
  TileMapServiceImageryProvider,
  VerticalOrigin,
  Viewer as CesiumViewer,
  type ImageryProvider,
  type TerrainProvider,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import type { Alert, GridWind, RankedSite, Storm } from './lib/api'
import { logger } from './lib/logger'
import { floodStats, startFlood as runFloodSim, type FloodOpts, type FloodStats } from './hazard/flood'
import { startTornado as runTornadoSim, type TornadoOpts } from './hazard/tornado'
import { addCloudLayer, type CloudLayerHandle } from './cloudLayer'
import { addAlerts } from './hazard/liveAlerts'
import { addStorms } from './hazard/liveStorms'
import { addWindFlow } from './hazard/windFlow'
import {
  modelKind,
  pickBuildingModel,
  SOLAR_PANEL_URL,
  TURBINE_NATIVE_H,
  TURBINE_URL,
} from './buildingModels'

export interface BuildingSpec {
  placeName: string
  buildingType: string
  label: string
  // richer parsed spec (optional) -> drives glTF model selection + real-world sizing
  approxFloors?: number | null
  heightM?: number | null
  footprintM?: number | null
}

export interface BuildingPlacement {
  lat: number
  lng: number
  baseHeight: number
}

export interface GlobeHandle {
  flyTo: (lat: number, lng: number, altitude?: number) => void
  placeBuilding: (spec: BuildingSpec) => Promise<BuildingPlacement | null>
  placeBuildingAt: (lat: number, lng: number, spec: BuildingSpec) => Promise<BuildingPlacement | null>
  clearBuilding: () => void
  startFlood: (opts: FloodOpts) => Promise<FloodStats | null>
  setFloodLevel: (level: number) => void
  startTornado: (opts: TornadoOpts) => void
  clearHazard: () => void
}

interface Props {
  sites: RankedSite[]
  layerId: string | null // null = no colored field (default cinematic earth)
  accent: string
  focus: { lat: number; lng: number }
  selectedRank: number | null
  onSiteClick: (site: RankedSite) => void
  // LIVE / OBSERVED storm layer (shown only when zoomed out; App gates by passing [] / null otherwise).
  storms?: Storm[]
  alerts?: Alert[]
  windGrid?: GridWind | null
  onStormClick?: (storm: Storm) => void
  onAlertClick?: (alert: Alert) => void
  onZoomChange?: (zoomedOut: boolean) => void // fired on threshold crossing only (no per-frame thrash)
  dimBase?: boolean // mute + desaturate the base imagery so the wind streamlines pop (restored when off)
}

interface Control {
  flyTo: (lat: number, lng: number, altitude?: number) => void
  placeBuilding: (spec: BuildingSpec) => Promise<BuildingPlacement | null>
  placeBuildingAt: (lat: number, lng: number, spec: BuildingSpec) => Promise<BuildingPlacement | null>
  clearBuilding: () => void
  startFlood: (opts: FloodOpts) => Promise<FloodStats | null>
  setFloodLevel: (level: number) => void
  startTornado: (opts: TornadoOpts) => void
  clearHazard: () => void
}

// The placed building is now a detailed, type-keyed glTF MODEL from the curated CC0 library
// (see buildingModels.ts) — scaled to the parsed height, terrain-clamped, with PBR materials,
// sun-driven shadows, and an accent silhouette so it reads distinct among Cesium OSM Buildings.
const BUILDING_GLOW = Color.fromCssColorString('#9ad8ff') // accent silhouette on the user's building

const ION_TOKEN = (import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined)?.trim()
const FIELD_LENSES = new Set(['solar', 'wind', 'temp']) // baked global field textures
const RESUME_SPIN_MS = 4500
// Auto-rotate ONLY when very zoomed out (the cinematic globe), and slowly. Rotating the camera while
// zoomed in spins the ground under you and reads as uncanny, so it's gated on camera altitude.
const SPIN_MIN_ALTITUDE = 10_000_000 // m above the ellipsoid — below this, no spin at all
const SPIN_RATE = -0.0003 // rad/tick (~1°/s at 60fps) — a gentle cinematic drift
const FIELD_ALPHA = 0.55 // the colored data field is an optional, subtle overlay (never the default)

// --- inner scene: owns the live viewer (auto-rotate, click-pick, flyTo, markers) ----------

interface SceneProps extends Props {
  base: ImageryProvider | null
  night: ImageryProvider | null
  field: ImageryProvider | null
  control: React.MutableRefObject<Control | null>
}

function GlobeScene({
  base,
  night,
  field,
  sites,
  accent,
  focus,
  selectedRank,
  onSiteClick,
  storms,
  alerts,
  windGrid,
  onStormClick,
  onAlertClick,
  onZoomChange,
  dimBase,
  control,
}: SceneProps): ReactElement {
  const { viewer } = useCesium()
  const spinningRef = useRef<boolean>(false)
  const resumeTimer = useRef<number | null>(null)
  const onSiteClickRef = useRef(onSiteClick)
  const sitesRef = useRef(sites)
  const firstFocus = useRef<boolean>(true)
  const cloudRef = useRef<CloudLayerHandle | null>(null)
  const buildingRef = useRef<CesiumEntity | null>(null)
  const infraRef = useRef<CesiumEntity[]>([]) // solar-array panels / wind-turbine cluster (multi-entity)
  const rotorSpinRef = useRef<(() => void) | null>(null) // removes the blade-spin preRender listener
  const osmRef = useRef<Cesium3DTileset | null>(null) // Cesium OSM Buildings (lazy; loaded once, shown on placement)
  const osmLoadingRef = useRef<boolean>(false)
  const hazardRef = useRef<{ dispose: () => void; setLevel?: (level: number) => void } | null>(null)
  // LIVE layer click-resolution + zoom-change callback (refs so the stable pick/camera handlers see latest).
  const stormsDataRef = useRef<Storm[]>(storms ?? [])
  const alertsDataRef = useRef<Alert[]>(alerts ?? [])
  const windGridRef = useRef<GridWind | null | undefined>(windGrid) // latest wind grid for turbine yaw
  const onStormClickRef = useRef(onStormClick)
  const onAlertClickRef = useRef(onAlertClick)
  const onZoomChangeRef = useRef(onZoomChange)
  onSiteClickRef.current = onSiteClick
  sitesRef.current = sites
  stormsDataRef.current = storms ?? []
  alertsDataRef.current = alerts ?? []
  windGridRef.current = windGrid
  onStormClickRef.current = onStormClick
  onAlertClickRef.current = onAlertClick
  onZoomChangeRef.current = onZoomChange

  const accentColor = useMemo(() => Color.fromCssColorString(accent), [accent])

  useEffect(() => {
    if (!viewer) return
    // Re-arm the "skip the first focus fly" guard per viewer instance. React StrictMode (dev) mounts this
    // effect twice and refs persist across the simulated remount, so without this the second mount's focus
    // effect would fly to the default region and clobber the opening full-globe view.
    firstFocus.current = true
    const scene = viewer.scene
    // Cinematic photoreal earth: day/night terminator + atmosphere limb-glow + subtle bloom. There is
    // NO colored data overlay by default now (it's an on-demand toggle), so the lit earth + city lights
    // are the hero — enabling lighting is the right call here.
    scene.globe.enableLighting = true
    scene.globe.dynamicAtmosphereLighting = true
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = true
    scene.fog.enabled = true
    scene.globe.showGroundAtmosphere = true
    scene.globe.baseColor = Color.fromCssColorString('#0a1a30') // ocean-ish under any terrain gaps
    scene.highDynamicRange = true
    // enhanced atmosphere / limb glow (unified Atmosphere in Cesium 1.1x)
    const atmo = (scene as { atmosphere?: { brightnessShift: number; saturationShift: number } }).atmosphere
    if (atmo) {
      atmo.brightnessShift = 0.18
      atmo.saturationShift = 0.12
    }
    // subtle bloom so the sun, city lights, and glowing markers bloom (kept low for ~60fps)
    const bloom = scene.postProcessStages.bloom
    bloom.enabled = true
    bloom.uniforms.glowOnly = false
    bloom.uniforms.contrast = 118
    bloom.uniforms.brightness = -0.45
    bloom.uniforms.delta = 1.2
    bloom.uniforms.sigma = 3.0
    bloom.uniforms.stepSize = 1.0
    viewer.useBrowserRecommendedResolution = false
    viewer.resolutionScale = Math.min(window.devicePixelRatio || 1, 2)

    // Sun-driven shadows for the placed building + OSM Buildings — configured once, capped for perf,
    // and only switched ON during a placement (off on the cinematic globe). Most of the quality jump.
    viewer.shadows = false
    const shadowMap = viewer.shadowMap
    shadowMap.size = 2048 // capped shadow-map resolution
    shadowMap.softShadows = true
    shadowMap.maximumDistance = 8000

    // Open looking at the DAY side (sub-solar longitude) so the landing is the vivid, lit earth with
    // the atmosphere limb-glow — not the dark night hemisphere. Gentle spin after idle.
    const utcH = new Date().getUTCHours() + new Date().getUTCMinutes() / 60
    const subSolarLon = ((-15 * (utcH - 12) + 540) % 360) - 180 // ≈ longitude under the sun
    viewer.camera.setView({ destination: Cartesian3.fromDegrees(subSolarLon, 16, 24_000_000) })

    // Drifting translucent cloud layer (procedural; lit so it darkens across the terminator).
    cloudRef.current?.dispose()
    cloudRef.current = addCloudLayer(viewer)

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
    // --- geocode + place a terrain-clamped building (Phase B) -----------------------------
    const geocoder = new IonGeocoderService({ scene })

    const clearHazard = (): void => {
      if (hazardRef.current) {
        hazardRef.current.dispose()
        hazardRef.current = null
      }
    }
    const startFlood = async (opts: FloodOpts): Promise<FloodStats | null> => {
      clearHazard()
      hazardRef.current = runFloodSim(viewer, opts)
      try {
        return await floodStats(viewer, opts)
      } catch {
        return null
      }
    }
    const setFloodLevel = (level: number): void => {
      hazardRef.current?.setLevel?.(level)
    }
    const startTornado = (opts: TornadoOpts): void => {
      clearHazard()
      const funnel = runTornadoSim(viewer, opts)
      // shake the building while the funnel is active (restore its original position on dispose)
      const ent = buildingRef.current
      const originalPos = ent?.position
      const base = originalPos?.getValue(viewer.clock.currentTime)
      const amp = 0.2 + opts.intensity * 0.25
      const shakeScratch = new Cartesian3()
      if (ent && base) {
        ent.position = new CallbackPositionProperty(() => {
          shakeScratch.x = base.x + (Math.random() - 0.5) * amp
          shakeScratch.y = base.y + (Math.random() - 0.5) * amp
          shakeScratch.z = base.z + (Math.random() - 0.5) * amp
          return shakeScratch
        }, false)
      }
      hazardRef.current = {
        dispose: (): void => {
          funnel.dispose()
          if (ent && originalPos) ent.position = originalPos
        },
      }
    }

    const clearBuilding = (): void => {
      clearHazard()
      if (rotorSpinRef.current) {
        rotorSpinRef.current() // remove the blade-spin preRender listener
        rotorSpinRef.current = null
      }
      if (buildingRef.current) {
        viewer.entities.remove(buildingRef.current)
        buildingRef.current = null
      }
      for (const e of infraRef.current) viewer.entities.remove(e) // solar panels / turbines
      infraRef.current = []
      // keep OSM Buildings loaded (cheap to re-show) but hide it + drop shadows off the cinematic globe
      if (osmRef.current) osmRef.current.show = false
      viewer.shadows = false
    }

    // Lazily add Cesium OSM Buildings (real city context) once, then just toggle visibility. ion-only.
    const ensureOsmBuildings = async (): Promise<void> => {
      if (!ION_TOKEN) return
      if (osmRef.current) {
        osmRef.current.show = true
        return
      }
      if (osmLoadingRef.current) return
      osmLoadingRef.current = true
      try {
        const osm = await createOsmBuildingsAsync()
        osm.shadows = ShadowMode.ENABLED
        viewer.scene.primitives.add(osm)
        osmRef.current = osm
      } catch (err) {
        logger.warn('OSM Buildings unavailable', err)
      } finally {
        osmLoadingRef.current = false
      }
    }

    // Shared model placement (terrain-clamp + detailed glTF + OSM context + shadows + fly-to), used by both
    // the geocoded place flow and the find-best flow (which already has the winning coordinates).
    const M_PER_DEG = 111320
    const labelGraphics = (text: string): CesiumEntity.ConstructorOptions['label'] => ({
      text,
      font: '600 13px Inter, system-ui, sans-serif',
      fillColor: Color.WHITE,
      style: LabelStyle.FILL_AND_OUTLINE,
      outlineColor: Color.fromCssColorString('#05070f'),
      outlineWidth: 3,
      verticalOrigin: VerticalOrigin.BOTTOM,
      pixelOffset: new Cartesian2(0, -14),
      showBackground: true,
      backgroundColor: Color.fromCssColorString('#0b1020').withAlpha(0.7),
      backgroundPadding: new Cartesian2(6, 4),
      translucencyByDistance: new NearFarScalar(2.0e5, 1.0, 4.0e6, 0.0),
    })

    const placeModelAt = async (lat: number, lng: number, spec: BuildingSpec): Promise<BuildingPlacement | null> => {
      let baseHeight = 0
      try {
        const sampled = await sampleTerrainMostDetailed(viewer.terrainProvider, [Cartographic.fromDegrees(lng, lat)])
        baseHeight = sampled[0]?.height ?? 0
      } catch {
        baseHeight = 0
      }

      clearBuilding()
      const kind = modelKind(spec.buildingType)
      // metres east/north -> lat/lon around the placement center (small-offset flat-earth approx)
      const offsetDeg = (east: number, north: number): [number, number] => [
        lat + north / M_PER_DEG,
        lng + east / (M_PER_DEG * Math.cos(CesiumMath.toRadians(lat))),
      ]
      let flyTarget: CesiumEntity | CesiumEntity[]
      let flyAlt: number

      if (kind === 'solar') {
        // SOLAR ARRAY: rows of flat PV panels tilted toward the equator at ~site latitude (a real heuristic).
        const tiltDeg = Math.min(40, Math.max(10, Math.abs(lat)))
        const pitch = CesiumMath.toRadians(lat >= 0 ? -tiltDeg : tiltDeg) // tilt the panel face toward the equator
        const rows = 5, cols = 6, dN = 4.2, dE = 2.8
        const panels: CesiumEntity[] = []
        for (let r = 0; r < rows; r++) {
          for (let c = 0; c < cols; c++) {
            const [pl, pg] = offsetDeg((c - (cols - 1) / 2) * dE, (r - (rows - 1) / 2) * dN)
            const pos = Cartesian3.fromDegrees(pg, pl, baseHeight)
            panels.push(
              viewer.entities.add(
                new CesiumEntity({
                  position: pos,
                  orientation: Transforms.headingPitchRollQuaternion(pos, new HeadingPitchRoll(0, pitch, 0)),
                  model: { uri: SOLAR_PANEL_URL, scale: 1.6, shadows: ShadowMode.ENABLED, maximumScale: 800 },
                }),
              ),
            )
          }
        }
        const labelEnt = viewer.entities.add(
          new CesiumEntity({ id: 'building', position: Cartesian3.fromDegrees(lng, lat, baseHeight), label: labelGraphics(`☀ ${spec.label} · representative solar array`) }),
        )
        panels.push(labelEnt)
        infraRef.current = panels
        buildingRef.current = labelEnt
        flyTarget = panels
        flyAlt = 600
      } else if (kind === 'wind') {
        // WIND FARM: a cluster of 3-blade turbines; the rotor node spins slowly; turbines yaw into the wind.
        const hub = 70 * (spec.heightM ? Math.max(0.6, Math.min(2.0, spec.heightM / 100)) : 1)
        const scale = hub / TURBINE_NATIVE_H
        let heading = 0
        const g = windGridRef.current
        if (g) {
          const [latMin, lonMin, latMax, lonMax] = g.bbox
          const j = Math.min(g.nx - 1, Math.max(0, Math.floor(((lng - lonMin) / (lonMax - lonMin)) * g.nx)))
          const i = Math.min(g.ny - 1, Math.max(0, Math.floor(((latMax - lat) / (latMax - latMin)) * g.ny)))
          const u = g.u[i * g.nx + j] ?? 0
          const v = g.v[i * g.nx + j] ?? 0
          if (Math.hypot(u, v) > 0.1) heading = Math.atan2(-u, -v) // rotor faces INTO the wind
        }
        let spin = 0
        const onSpin = (): void => {
          spin += 0.02 // slow, realistic blade rotation
        }
        viewer.scene.preRender.addEventListener(onSpin)
        rotorSpinRef.current = (): void => {
          viewer.scene.preRender.removeEventListener(onSpin)
        }
        const offsets: [number, number][] = [[0, 0], [280, 160], [-240, 210], [210, -250], [-300, -130]]
        const turbines: CesiumEntity[] = []
        offsets.forEach(([e, n], i) => {
          const [pl, pg] = offsetDeg(e, n)
          const pos = Cartesian3.fromDegrees(pg, pl, baseHeight)
          const trs = new TranslationRotationScale() // reused per turbine (mutated each frame, no alloc)
          const quat = new Quaternion()
          const phase = i * 0.8
          turbines.push(
            viewer.entities.add(
              new CesiumEntity({
                position: pos,
                orientation: Transforms.headingPitchRollQuaternion(pos, new HeadingPitchRoll(heading, 0, 0)),
                model: {
                  uri: TURBINE_URL,
                  scale,
                  minimumPixelSize: 48,
                  maximumScale: 20000,
                  shadows: ShadowMode.ENABLED,
                  nodeTransformations: {
                    // a CallbackProperty is valid at runtime (PropertyBag resolves it per frame); cast for TS
                    rotor: new CallbackProperty(() => {
                      Quaternion.fromAxisAngle(Cartesian3.UNIT_Z, spin + phase, quat)
                      trs.rotation = quat
                      return trs
                    }, false) as unknown as TranslationRotationScale,
                  },
                },
              }),
            ),
          )
        })
        const labelEnt = viewer.entities.add(
          new CesiumEntity({ id: 'building', position: Cartesian3.fromDegrees(lng, lat, baseHeight), label: labelGraphics(`🌀 ${spec.label} · representative turbines`) }),
        )
        turbines.push(labelEnt)
        infraRef.current = turbines
        buildingRef.current = labelEnt
        flyTarget = turbines
        flyAlt = hub * 12
      } else {
        // BUILDING: detailed glTF model from the curated CC0 library, scaled to the parsed real-world height.
        const picked = pickBuildingModel({
          buildingType: spec.buildingType,
          approxFloors: spec.approxFloors,
          heightM: spec.heightM,
          footprintM: spec.footprintM,
        })
        const ent = viewer.entities.add(
          new CesiumEntity({
            id: 'building',
            name: spec.label,
            position: Cartesian3.fromDegrees(lng, lat, baseHeight + picked.baseOffsetM),
            model: {
              uri: picked.url,
              scale: picked.scale,
              minimumPixelSize: 64,
              maximumScale: 20000,
              shadows: ShadowMode.ENABLED,
              silhouetteColor: BUILDING_GLOW,
              silhouetteSize: 2.0,
            },
            label: labelGraphics(spec.label),
          }),
        )
        buildingRef.current = ent
        flyTarget = ent
        flyAlt = Math.max(700, picked.targetHeightM * 9)
      }

      // Real city context + sun shadows, lazily, only now (a placement) — not on the cinematic globe.
      void ensureOsmBuildings()
      viewer.shadows = true

      spinningRef.current = false
      if (resumeTimer.current !== null) window.clearTimeout(resumeTimer.current)
      void viewer.flyTo(flyTarget, {
        duration: 2.0,
        offset: new HeadingPitchRange(CesiumMath.toRadians(35), CesiumMath.toRadians(-22), flyAlt),
      })
      return { lat, lng, baseHeight }
    }

    const placeBuilding = async (spec: BuildingSpec): Promise<BuildingPlacement | null> => {
      try {
        const results = await geocoder.geocode(spec.placeName)
        const dest = results[0]?.destination
        if (!dest) return null
        const carto = dest instanceof Rectangle ? Rectangle.center(dest) : Cartographic.fromCartesian(dest)
        return placeModelAt(CesiumMath.toDegrees(carto.latitude), CesiumMath.toDegrees(carto.longitude), spec)
      } catch (err) {
        logger.warn('geocode failed', err)
        return null
      }
    }
    // find-best flow: place directly at the winning coordinates (no geocode).
    const placeBuildingAt = (lat: number, lng: number, spec: BuildingSpec): Promise<BuildingPlacement | null> =>
      placeModelAt(lat, lng, spec)

    control.current = {
      flyTo, placeBuilding, placeBuildingAt, clearBuilding, startFlood, setFloodLevel, startTornado, clearHazard,
    }

    const spinAxis = Cartesian3.UNIT_Z
    const onTick = (): void => {
      // Only auto-rotate when idle AND very zoomed out — never spin the ground while zoomed in.
      const altitude = viewer.camera.positionCartographic?.height ?? 0
      if (spinningRef.current && altitude > SPIN_MIN_ALTITUDE) viewer.camera.rotate(spinAxis, SPIN_RATE)
      cloudRef.current?.rotate(0.00016) // slow eastward cloud drift relative to the ground
    }
    viewer.clock.onTick.addEventListener(onTick)

    const canvas = scene.canvas
    const onInteract = (): void => pauseSpin()
    canvas.addEventListener('pointerdown', onInteract)
    canvas.addEventListener('wheel', onInteract, { passive: true })

    const handler = new ScreenSpaceEventHandler(canvas)
    handler.setInputAction((movement: ScreenSpaceEventHandler.PositionedEvent) => {
      const picked = scene.pick(movement.position)
      // For an entity pick, Cesium sets picked.id to the Entity, whose own .id is our `site-N`
      // string. Narrow defensively so it works whether picked.id is the Entity or already a string.
      const pid: unknown = defined(picked) && picked ? (picked as { id?: unknown }).id : undefined
      const id = typeof pid === 'string' ? pid : (pid as { id?: string } | null | undefined)?.id
      if (id && id.startsWith('site-')) {
        const rank = Number(id.slice(5))
        const site = sitesRef.current.find((s) => s.rank === rank)
        if (site) onSiteClickRef.current(site)
      } else if (id && id.startsWith('live-storm-')) {
        const storm = stormsDataRef.current[Number(id.slice('live-storm-'.length))]
        if (storm) onStormClickRef.current?.(storm)
      } else if (id && id.startsWith('live-alert-')) {
        const alert = alertsDataRef.current[Number(id.split('-')[2])]
        if (alert) onAlertClickRef.current?.(alert)
      }
    }, ScreenSpaceEventType.LEFT_CLICK)

    // Surface zoomed-out vs zoomed-in to the parent ONLY on a threshold crossing (so the live layer can
    // show only on the global view without a per-frame React update). Reuse the spin altitude threshold.
    let lastZoomedOut: boolean | null = null
    viewer.camera.percentageChanged = 0.2
    const onCameraChange = (): void => {
      const zoomedOut = (viewer.camera.positionCartographic?.height ?? 0) > SPIN_MIN_ALTITUDE
      if (zoomedOut !== lastZoomedOut) {
        lastZoomedOut = zoomedOut
        onZoomChangeRef.current?.(zoomedOut)
      }
    }
    viewer.camera.changed.addEventListener(onCameraChange)
    onCameraChange() // fire the initial state

    return () => {
      viewer.clock.onTick.removeEventListener(onTick)
      viewer.camera.changed.removeEventListener(onCameraChange)
      canvas.removeEventListener('pointerdown', onInteract)
      canvas.removeEventListener('wheel', onInteract)
      handler.destroy()
      if (resumeTimer.current !== null) window.clearTimeout(resumeTimer.current)
      clearBuilding()
      if (osmRef.current) {
        viewer.scene.primitives.remove(osmRef.current) // disposes the tileset
        osmRef.current = null
      }
      cloudRef.current?.dispose()
      cloudRef.current = null
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

  // LIVE storm glyphs — added when the prop has storms (App passes [] when zoomed in / toggled off).
  useEffect(() => {
    if (!viewer || !storms || storms.length === 0) return
    const layer = addStorms(viewer, storms)
    return () => layer.dispose()
  }, [viewer, storms])

  // LIVE tornado warning/watch polygons.
  useEffect(() => {
    if (!viewer || !alerts || alerts.length === 0) return
    const layer = addAlerts(viewer, alerts)
    return () => layer.dispose()
  }, [viewer, alerts])

  // LIVE wind-flow layer (GPU streamlines from the current Open-Meteo grid).
  useEffect(() => {
    if (!viewer || !windGrid) return
    const layer = addWindFlow(viewer, windGrid)
    return () => layer.dispose()
  }, [viewer, windGrid])

  return (
    <>
      {base && (
        <ImageryLayer
          imageryProvider={base}
          brightness={dimBase ? 0.7 : 1.0}
          saturation={dimBase ? 0.85 : 1.0}
        />
      )}
      {night && <ImageryLayer key="night" imageryProvider={night} dayAlpha={0} nightAlpha={0.92} />}
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
  const [night, setNight] = useState<ImageryProvider | null>(null)
  const [field, setField] = useState<ImageryProvider | null>(null)

  useImperativeHandle(
    ref,
    () => ({
      flyTo: (lat: number, lng: number, altitude?: number): void =>
        control.current?.flyTo(lat, lng, altitude),
      placeBuilding: (spec: BuildingSpec): Promise<BuildingPlacement | null> =>
        control.current ? control.current.placeBuilding(spec) : Promise.resolve(null),
      placeBuildingAt: (lat: number, lng: number, spec: BuildingSpec): Promise<BuildingPlacement | null> =>
        control.current ? control.current.placeBuildingAt(lat, lng, spec) : Promise.resolve(null),
      clearBuilding: (): void => control.current?.clearBuilding(),
      startFlood: (opts: FloodOpts): Promise<FloodStats | null> =>
        control.current ? control.current.startFlood(opts) : Promise.resolve(null),
      setFloodLevel: (level: number): void => control.current?.setFloodLevel(level),
      startTornado: (opts: TornadoOpts): void => control.current?.startTornado(opts),
      clearHazard: (): void => control.current?.clearHazard(),
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
            createWorldTerrainAsync({ requestWaterMask: true, requestVertexNormals: true }),
          ])
          if (!cancelled) {
            setBase(img)
            setTerrain(terr)
          }
          // Earth at Night (Black Marble) — shown only on the night side via dayAlpha/nightAlpha.
          IonImageryProvider.fromAssetId(3812)
            .then((n) => {
              if (!cancelled) setNight(n)
            })
            .catch((err) => logger.warn('night imagery unavailable', err))
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
    const lens = props.layerId
    if (!lens || !FIELD_LENSES.has(lens)) {
      setField(null)
      return
    }
    void (async (): Promise<void> => {
      try {
        const provider = await SingleTileImageryProvider.fromUrl(`/fields/${lens}.png`, {
          rectangle: Rectangle.MAX_VALUE,
        })
        if (!cancelled) setField(provider)
      } catch (err) {
        logger.warn('field texture load failed', err)
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
      <GlobeScene {...props} base={base} night={night} field={field} control={control} />
    </Viewer>
  )
})
