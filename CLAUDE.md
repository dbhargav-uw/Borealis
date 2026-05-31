# CLAUDE.md — Borealis

## What this is
Borealis is a **weather map you act on**, on a high-fidelity CesiumJS globe. The FRONT experience:
1. **Land** on one cohesive global climate field (default: temperature) draped on the vivid Bing +
   World Terrain globe — a striking weather map, no tool chrome.
2. **Place a building by natural language** ("a coastal hospital in Miami"): an Anthropic call parses
   `{placeName, buildingType, intent}`, the Cesium ion geocoder resolves it, and a terrain-clamped
   building appears with an oblique fly-to.
3. **Run a grounded, ILLUSTRATIVE catastrophe view** at that building — a flood (bathtub inundation
   over real Cesium World Terrain) or a tornado (particle funnel whose EF intensity + likelihood come
   from real NOAA SPC climatology) — with an AI hazard-exposure explanation.
4. **Toggle a LIVE / OBSERVED storm overlay** on the zoomed-out globe (a SEPARATE category from the
   illustrative sim): real, timestamped active NHC tropical cyclones (rotating spiral glyphs, color-ramped
   by category), NWS tornado warning/watch polygons (warning red / watch amber), and a live Open-Meteo
   current wind-flow particle layer. Everything carries its source + observation time; an empty feed is
   reported honestly ("none active"), never faked. Shows only when zoomed out; detail on click.

**Suitability is now a CONTEXTUAL layer**, not the landing. The renewable site-selection engine
(SuitabilityModel + 3 lenses solar/wind/cropland, generic score-and-rank, ranked sites, "why this site"
briefing) is fully PRESERVED and surfaces when the intent is site-selection — it is no longer the default UI.

**Critical honesty (do not drift):** the flood/tornado views are ILLUSTRATIVE visualizations whose
magnitude/likelihood are grounded in real elevation (Cesium World Terrain) and real tornado climatology
(NOAA SPC). They are NOT a physics or meteorology engine and must never read as predictions — every hazard
view labels scenario, depth/intensity, and data source, and negligible-risk locations are reported honestly
(no faked tornado). Suitability remains RELATIVE climatology ranking, never bankable yield.
**Two categories never blur:** the flood/tornado views are ILLUSTRATIVE (sim, grounded but NOT a prediction);
the live-storms overlay is LIVE/OBSERVED (real, timestamped feeds — NHC/NWS/Open-Meteo). They share no label,
legend, color ramp, or code path. An empty live feed means "none currently active / feed unavailable" (NWS
alerts US-only; NHC Atlantic + E/Central Pacific) — never "safe".

**The platform principle:** every vertical/lens is the same pipeline and differs in exactly ONE place.
A vertical = a resource grid over a region + a SuitabilityModel (climatology -> that domain's score) +
normalization + a ranking decision. The ResourceProvider, the generic score-and-rank math, the globe, and
the briefing layer are SHARED and vertical-agnostic. Adding a vertical/lens = writing one SuitabilityModel.
Energy ships first with TWO lenses (solar, wind) behind one model via params['lens'].

## The lenses  { resource -> suitability metric -> decision }
- **Energy / solar:** GHI + temp -> PV specific yield (kWh/kWp/yr, PVWatts-style annual estimate with a
  temperature derate) -> normalized solar suitability -> where to site a solar farm.
- **Energy / wind:** WS50M -> wind power density 0.5·ρ·v³ (W/m²) -> normalized wind suitability -> where to
  site a wind farm.
- **Later:** Agriculture suitability (growing-degree-days / frost-free window) on the SAME grid + scoring
  + ranking — proving the platform principle on the new spine.

## Honest constraints (bake in, never hide)
- Climatology is a ~20-year monthly/annual MEAN (NASA POWER, MERRA-2, 2001–2020). It is a RANKING
  comparator, NOT bankable yield, and carries no extreme-event skill. Frame output as RELATIVE suitability
  that points to a real site assessment — never as investable energy.
- Suitability is RELATIVE: scores are min-max normalized ACROSS the queried region, so a cell scores
  differently under a different bbox. Always also expose the raw physical metric (kWh/kWp/yr, W/m²).
- The solar score is a PVWatts-style annual estimate (irradiation × performance ratio × temperature
  derate), not a full hourly pvlib simulation — a fast, defensible ranking comparator; the full per-cell
  pvlib sim (reusing operational solar.py) is a documented richer upgrade.
- Capacity factor from a single annual mean wind speed is approximate (no speed distribution) — prefer
  wind power density for the MVP; escalate to Global Wind Atlas for anything bankable.
- The native grid is coarse (NASA POWER regional ~0.5°, ~50 km cells; radiation is ~1° and joined by
  nearest neighbour). State the resolution; if you interpolate for the globe, LABEL it interpolated.
- Ocean / no-data cells (POWER's -999 fill) are cleaned out by the provider, never scored as zero.

## Core contract (GENERIC over verticals)
- `get_resource_grid(bbox, resolution, variables) -> ResourceGrid`      # NASA POWER now; Atlas GeoTIFF later
- `SuitabilityModel.score_cell(cell, params) -> SuitabilityScore`       # per-cell, physical value + metrics
- `score_and_rank(grid, scores, weights, top_n) -> SuitabilityResult`   # generic normalize + MCDA + rank
- `generate_site_briefing(grid_summary, ranked_sites, vertical_meta) -> SiteBriefing`  # structured, given numbers
- `POST /api/suitability { vertical, region, resolution, params{lens}, weights, top_n }`
      `-> { region, resolution, vertical, metric_units, n_cells, cells, ranked_sites, briefing }`
- LIVE / OBSERVED read-only feeds (NOT the suitability spine; SEPARATE from the illustrative sim):
  - `GET /api/storms`  -> active NHC cyclones (id, name, basin, classification, Saffir-Simpson category, position,
        max_wind_kt, movement, advisory_time) + `as_of` + `source` + `coverage`. (Track/cone GIS = fast-follow.)
  - `GET /api/alerts`  -> NWS active tornado warning/watch GeoJSON polygons (event, severity, area, issued/expires,
        geometry) + `as_of` + `coverage`. US-only.
  - `GET /api/current-wind`  -> coarse global current wind grid `{ bbox, resolution, nx, ny, u, v, speed }` (Open-Meteo,
        labeled coarse/interpolated) for the wind-flow layer.
- CONTEXTUAL per-location risk dossier (COMPOSES the suitability + hazard + briefing layers — NOT a new engine):
  - `POST|GET /api/analysis { lat, lon, building_type, intent, place_name?, elevation_m? }`
        `-> { location, resource{solar,wind,[crop]}, hazards{flood,tornado,live}, insurance[], summary, disclaimer }`.
        resource = relative comparator (lenses scored on a small surrounding grid, never bankable yield); flood = elevation
        read (Cesium terrain, sampled client-side + passed in); tornado = REUSED SPC climatology; live = REUSED NHC/NWS feeds;
        insurance[]+summary = Anthropic synthesis, ILLUSTRATIVE/EDUCATIONAL (not advice), invents no numbers, degrades to
        []/null. Cached per location (one call per placement). crop lens only for agri building types (farm/ranch/…).
- FIND-BEST-SITE (region search → build at the winner; composes suitability + hazard + briefing):
  - `POST /api/best-site { query }` -> `{ best_site{lat,lon,score,suitability,metrics}, top_candidates[], region_bbox,
        region_label, building_type, objective, metric_units, explanation, disclaimer }`. Anthropic parse → region bbox +
        objective (solar/wind/crop/hazard_min, inferred from building type + explicit "avoid floods/tornadoes"); score a
        coarse grid with the objective's SuitabilityModel (`score_and_rank`) + land mask, blend HAZARD penalties (tornado
        from SPC `tornado_climatology`, flood from coarse Open-Meteo elevation `resources/elevation.py`); pick the top
        valid cell + top-N. Relative comparator (NOT bankable). Cached per query.

ResourceCell: `{ lat, lon, values: { <POWER var>: annual_mean } }`
SuitabilityModel interface: `{ id, name, required_variables, briefing_role,
  metric_units(params), score_cell(cell, params) -> SuitabilityScore }`

## Status (update as you go)
Current phase: front-experience repivot to weather-map -> building -> hazard sim (suitability is contextual).
Set ANTHROPIC_API_KEY for live building-parse + briefings; VITE_CESIUM_ION_TOKEN in frontend/.env for the
premium Bing/World-Terrain earth + the ion geocoder.
- [x] P1–P8: site-selection spine + Cesium/resium globe + continuous global field textures (solar/wind/temp,
      `scripts/bake_field_textures.py`) + `/api/seasonal` (all PRESERVED, now contextual)
- [x] Phase A: **weather-map landing** — temperature hero field, lens toggle + sites hidden from the landing
      (suitability code intact, surfaced only by intent)
- [x] Phase B: **query-placed building** — `POST /api/place` (Anthropic parse) -> ion geocoder ->
      terrain-clamped extruded-box building (glTF-by-type hook) -> oblique fly-to. Degrades without a key
      (geocodes the raw query).
- [x] Phase C: **flood sim** — `hazard/flood.ts` bathtub inundation over real terrain (depthTestAgainstTerrain),
      +N m presets, animated rise, honesty label, disposed on reset.
- [x] Phase D: **tornado** — `GET /api/tornado-climatology` (NOAA SPC coarse model + `scripts/build_tornado_climatology.py`
      for the full 1° grid) drives EF intensity + likelihood; `hazard/tornado.ts` particle funnel + building shake;
      **negligible-risk locations honestly show no funnel**. (Funnel particle visual needs a Cesium ParticleSystem
      tuning pass — renders without error but not yet visibly; the data/honesty/label/dispose paths are verified.)
- [x] Phase E (LIVE, SEPARATE from the sim): **observational live-storms overlay** — `GET /api/storms` (NHC active
      cyclones + Saffir-Simpson category), `GET /api/alerts` (NWS tornado warning/watch polygons), `GET /api/current-wind`
      (coarse Open-Meteo current grid), backed by `backend/storms/` (+ `operational/forecast/current_wind.py`). Frontend
      `hazard/{liveStorms,liveAlerts,windFlow}.ts` + a "🌀 Live storms" toggle, category/warning-watch legend, "as of"
      timestamp, click-detail. Real, timestamped, LIVE/OBSERVED; shown only zoomed out; empty feed reported honestly;
      walled off from the ILLUSTRATIVE sim. (NHC track/cone GIS + nicer wind streamlines are documented fast-follows.)
      LIVE-LAYER BEAUTIFY pass: (1) STORM FILTER — `nhc.is_named_cyclone` keeps only genuine NAMED cyclones at TS
      strength+ (classification TS/HU/STS/SS or ≥34 kt; drops TD/SD/PTC/DB/LO/WV/EX + invests/unnamed) so the map shows
      the handful of real systems (also tightens the legend count + dossier proximity). (2) STORM RENDER — each storm is a
      GEOREFERENCED spiral CLOUD (two ground-draped `ellipse`s at ~3 km height: faint outer canopy + denser inner core
      with an eye for Cat 3+) at its real STATIC position (only motion = a slow in-place `stRotation` swirl, hemisphere-
      correct N=CCW/S=CW), sized to an APPROXIMATE wind-field radius (135→370 km by category — documented proxy; the feed
      has no real radii). Daytime-legible via a near-white cloud body + a soft DARK feathered rim baked into the texture
      (not additive); far side occluded by the globe; exact-position marker + dark-outlined label on top. (3) WIND —
      `windFlow.ts` renders nullschool-style STREAMLINES via a TRUE GPU pipeline (`cesium-wind-layer`): particle state in
      a texture advanced by a fragment shader sampling the wind UV texture, ping-pong FRAMEBUFFER trails (cost O(screen),
      independent of particle count), one batched `CustomPrimitive` draw. Density = `particlesTextureSize²` (128 → ~16k
      particles, cheap on GPU); speed colormap via `colors` (teal→green→yellow→white); `lineLength`/`lineWidth` trails.
      Efficiency: `useViewerBounds` culls off-screen/back-hemisphere particles, the wind UV texture is uploaded once per
      ~12-min poll (the `addWindFlow` effect re-runs on the grid prop), the lib reuses its own FBOs/buffers, and the layer
      pauses on `document.hidden`; `destroy()` on toggle-off. (This SUPERSEDES the earlier finding that cesium-wind-layer
      no-renders on 1.141 — v0.10.1, peer cesium ^1.127, integrates cleanly; the prior CPU `PolylineGlow` streamlines
      lagged because advection + per-frame buffer rebuilds + ~1k non-batching draws were all CPU-bound.) (4) BASE CONTRAST —
      when wind is on, `ResourceGlobe` mutes the base imagery (`<ImageryLayer brightness=0.5 saturation=0.55>`) so the
      streamlines pop on the bright day side; vivid imagery is restored when wind is off. (5) DEFAULTS/TOGGLES — split
      into independent **Wind (default ON — the hero look)** + **Storms (default OFF, opt-in)** toggles (`windOn`/`stormsOn`,
      separate polls + gating + legend lines). Storm spiral-cloud visuals are unchanged; only their default visibility did.
      NOTE: past/forecast TRACK + cone remain NOT rendered (no track geometry in the scalar feed; never fabricated).
- [x] Phase F (CONTEXTUAL dossier): **per-location risk analysis** — `GET|POST /api/analysis` (`backend/api/analysis.py`)
      COMPOSES the suitability lenses (energy solar/wind + agri crop) + flood(elevation)/tornado(SPC)/live(NHC+NWS) hazards
      + an Anthropic insurance+summary synthesis (`generate_analysis_briefing` in `briefing/`), cached per location. Frontend
      `AnalysisDossier.tsx` + `fetchAnalysis()` (`lib/api.ts`) + `.hud--dossier`: a left glassmorphic panel that opens on
      placement and closes on reset, with LOCATION / RENEWABLE RESOURCE / HAZARD EXPOSURE / INSURANCE / SUMMARY sections,
      each carrying its data source + the "relative comparator / illustrative / not advice" honesty labels. The LLM invents
      no numbers and the whole synthesis degrades to []/null without a key. Tests: `backend/tests/test_analysis.py`.
- [x] Phase G (detailed building): **type-keyed glTF placed building** — the stylized extruded box is replaced by a
      detailed model from a CURATED CC0 glTF library (`frontend/public/models/*.glb` + `ATTRIBUTIONS.md`: Quaternius
      house/hospital/office_tower(Bank)/residential_tower(Flat)/mid_rise(Shop) + 32kda warehouse, all CC0). `/api/place`
      now returns a richer SPEC (`approx_floors, height_m, footprint_m, style, roof_type, features`) via the SAME Anthropic
      call; `frontend/src/buildingModels.ts` (`pickBuildingModel`) maps the parsed type→best model + scales it to the
      parsed real-world height (clamped) + a terrain base offset. `ResourceGlobe.placeBuilding` renders a `model` Entity
      (PBR materials, `ShadowMode.ENABLED`, accent silhouette so it's distinct), lazily adds Cesium **OSM Buildings**
      (ion asset, real city context) + sun-driven **shadows** (capped 2048 shadow-map, soft) — both ON only during a
      placement, OFF on the cinematic globe; one model at a time, disposed on new placement/reset. Honesty: a small
      "representative model — not the actual structure" label (dossier Location section). Tornado shake + flood + dossier
      all still consume `{lat,lng,baseHeight}` unchanged. (Text-to-3D generation for unmatched types is a documented
      seam below — deferred, off by default, needs a new secret.)
- [x] Phase H (find-best-site + wind-always-on): **`POST /api/best-site`** (`backend/api/best_site.py`) — a "find the best
      place in <region> to build X" query parses to region bbox + objective (`parse_best_site_query`), scores a coarse grid
      with the objective's SuitabilityModel + land mask, blends tornado (SPC) + flood (Open-Meteo elevation,
      `resources/elevation.py`) penalties, picks the top valid cell + top-N candidates, and an LLM explains "why here"
      (`generate_best_site_explanation`). Frontend: `parse_building_query` gains a `mode` (place|find-best) for routing;
      `fetchBestSite` (`lib/api.ts`); `ResourceGlobe.placeBuildingAt(lat,lng,spec)` builds at the winner (no geocode);
      candidate markers + a "🏆 Best in region — why here" block in the dossier. Relative comparator, labeled not-bankable;
      tests `backend/tests/test_best_site.py`. WIND IS NOW ALWAYS ON — the 💨 Wind toggle is removed (`showWind=zoomedOut`,
      base-dimming likewise); Storms stays toggleable.
- [x] Phase I (energy infrastructure models): solar/wind placements render INFRASTRUCTURE, not a building.
      `buildingModels.modelKind(buildingType)` → solar | wind | building; `ResourceGlobe.placeModelAt` branches:
      SOLAR = a grid of the CC-BY `solar_panel.glb` (OpenGameArt/Jummit) tiled into rows, each tilted toward the equator
      at ~site latitude; WIND = a cluster of `turbine.glb` (3-blade HAWT authored procedurally by
      `frontend/scripts/build_turbine.mjs` with a named `rotor` node) whose blades SPIN via `nodeTransformations`
      (Quaternion about local +Z, reused scratch — no per-frame alloc) and YAW into the live Open-Meteo wind. Both
      terrain-clamped, PBR + shadows, disposed on reset (multi-entity `infraRef` + a `rotorSpinRef` preRender remover),
      labeled "representative". Drives off the parsed buildingType so it works for direct placement AND find-best-site
      (objective solar/wind → "solar farm"/"wind farm"). NOTE: `tsc -b` (the build) is stricter than `tsc --noEmit` —
      verify with `npm run build`.
- [ ] Remaining: NHC track/cone (KMZ/shapefile) for storms; Global Wind/Solar Atlas enrichment; NASA-POWER fallback when
      Open-Meteo 429-rate-limits the per-placement analysis grid; **text-to-3D fallback** (Phase D seam) — behind a flag
      (`VITE_ENABLE_TEXT_TO_3D` + a backend Meshy/Tripo/Hunyuan proxy needing a new secret): generate a mesh on demand
      from the parsed spec ONLY when no curated match exists, normalize scale/orientation, cache by spec hash, and fall
      back to the curated default on slow/fail; more detailed/varied glTF models for the curated library (school/stadium/
      data-center currently reuse the nearest match + scaling).

## The new flow + hazard honesty contract
weather-map landing -> NL-query-placed building (Anthropic parse + Cesium ion geocode) -> grounded flood/tornado
sim. Data sources: Cesium World Terrain (flood inundation), NOAA SPC tornado database (tornado climatology, coarse
built-in + `build_tornado_climatology.py` for the fine grid), Cesium ion geocoder (geocoding — no new secret).
Hazards are ILLUSTRATIVE, never predictive: always label scenario + depth/intensity + source; never fake a tornado
where SPC climatology says risk is negligible. New code: `frontend/src/hazard/{flood,tornado}.ts`,
`frontend/src/ResourceGlobe.tsx` (geocode/building/hazard control methods), `backend/api/{place,tornado}.py`,
`backend/data/tornado_climatology.json` (optional), `scripts/build_tornado_climatology.py`, `field/` += a temp field.

**Live layer (DISTINCT category — real, not sim):** LIVE/OBSERVED storm overlay from NHC (active tropical cyclones —
Atlantic + E/Central Pacific), NWS (active tornado warning/watch polygons — US-only), and Open-Meteo (live surface
wind — global, coarse). Each item is stamped with `source` + observation/issue time; nothing here is illustrative or
predicted, and it NEVER reuses the sim's grey funnel/blue flood or the words "illustrative"/"simulate". New code:
`backend/storms/` (NHC + NWS providers + stdlib TTL cache + pydantic types), `backend/operational/forecast/current_wind.py`,
`backend/api/{storms,alerts,current_wind}.py` (mounted in `api/main.py`), `frontend/src/hazard/{liveStorms,liveAlerts,
windFlow}.ts`, `frontend/src/lib/api.ts` (`fetchStorms`/`fetchAlerts`/`fetchCurrentWind`), `ResourceGlobe.tsx`
(storms/alerts/windGrid props + camera-altitude `onZoomChange` gate), `App.tsx` (toggle + legend + detail + ~12-min poll).
The illustrative sim and the live overlay never share a label, legend, color ramp, or code path. NOTE: the wind flow now
uses `cesium-wind-layer` (v0.10.1) — a GPU particle-texture + ping-pong-framebuffer streamline pipeline — driven by the
`GridWind` reshaped into its `WindData`; density = `particlesTextureSize²`. (This supersedes the earlier note that the lib
no-renders on 1.141, and the interim CPU `PointPrimitiveCollection`/`PolylineGlow` advections, which were CPU-bound + laggy.)

## Working philosophy in this repo
- MVP first. Always keep the app runnable. Build and verify ONE layer at a time.
- Build the platform abstraction for real, but ship ENERGY (solar+wind) deep first.
- Type everything (pydantic backend, TS frontend). Leave clean seams. Stop and confirm before any large
  detour. Write pytest tests for the suitability scoring and the ranking math (most error-prone).

## Repo structure (monorepo)
```
/backend
  resources/   ResourceProvider seam: NASAPowerProvider (climatology) + ResourceGrid/Cell types
  verticals/   base.py (SuitabilityModel + the operational ImpactModel) + energy/
                 (solar.py + wind.py SHARED physics; suitability.py = EnergySuitabilityModel)
  scoring/     GENERIC normalize + MCDA + rank over SuitabilityScores
  briefing/    GENERIC "why this site" briefing (Anthropic structured output) — P4
  field/       Resource-field texture renderer: colormaps (inferno/viridis) + render_field_png
                 (ResourceGrid -> smooth global equirectangular RGBA PNG on a fixed absolute scale)
  registry.py  vertical id -> SuitabilityModel (+ a parallel impact registry for Act 2)
  api/         FastAPI: /health, POST /api/suitability, GET /api/seasonal (entry: api/main.py -> app)
  storms/      LIVE/OBSERVED feed layer (SEPARATE from the sim + the suitability spine): NHC cyclone (nhc.py)
                 + NWS alert (nws.py) clients + stdlib TTL cache (cache.py) + pydantic types -> /api/storms,
                 /api/alerts (read-only). Live current-wind grid lives in operational/forecast/current_wind.py.
  operational/ DEFERRED SECOND ACT (forecast/, energy MW fan, risk, /api/operational/assess)
  tests/  scripts/  (scripts/bake_field_textures.py bakes the global field PNGs -> frontend/public/fields/)
/frontend      Vite + React + TS; CesiumJS globe via resium (P8) — see src/ResourceGlobe.tsx
```

## Stack
- Backend: Python 3.11+, FastAPI, pydantic, uv, pytest.
- Resource (MVP): free NASA POWER climatology API (no key, global, regional bbox), behind a swappable
  ResourceProvider; Global Wind Atlas / Global Solar Atlas GeoTIFF as a later raster provider.
- Suitability: PVWatts-style annual yield for solar (pvlib available for the richer per-cell sim) + numpy
  wind power density.
- LLM: Anthropic Python SDK, structured output, claude-sonnet-4-6, for the "why this site" briefing +
  NL search (verify the current model id at docs.claude.com).
- Field textures: Pillow + numpy/scipy bake the climatology grid into a smooth global equirectangular
  PNG per lens (multi-stop inferno/viridis colormap, fixed absolute scale) — the DISPLAYED field.
- Frontend: Vite + React + TypeScript (strict); **CesiumJS via resium** (Three-free, WebGL globe) — the
  resource field is one continuous translucent `SingleTileImageryProvider` overlay (NOT scattered points),
  glowing `Entity` markers + labels for ranked sites, `camera.flyTo`, atmosphere/fog. Vivid earth via a
  Cesium ion token (Bing World Imagery + World Terrain), graceful offline Natural Earth II fallback without
  one. Cesium is lazy-loaded; `vite-plugin-cesium` wires CESIUM_BASE_URL/assets. (This repo is React+Vite,
  NOT Next.js/Supabase/Stripe — the global App-Router rules do not apply here.)
- Deploy (LATER, not now): backend on Modal/Fly, frontend on Vercel.

## Commands
- Backend dev: `cd backend && uv run uvicorn api.main:app --reload`
- Backend tests: `cd backend && uv run pytest`
- Live spine smoke: `cd backend && uv run python scripts/smoke_suitability.py` (or smoke_resource.py)
- Live storm feeds smoke: `cd backend && uv run python scripts/smoke_storms.py` (hits NHC/NWS/Open-Meteo;
  prints active cyclones + alert count + a wind sample with timestamps — empty result is a PASS: none active)
- Bake the global field textures: `cd backend && uv run python scripts/bake_field_textures.py`
  (per-tile cached/resumable in backend/.cache/; `--bbox lat_min,lon_min,lat_max,lon_max` to scope down)
- Frontend dev: `cd frontend && npm run dev`
- Env: copy `.env.example` to `.env` (NASA POWER needs no key; set ANTHROPIC_API_KEY for AI). For the
  premium earth, put `VITE_CESIUM_ION_TOKEN=` in `frontend/.env` (free tier; offline fallback without it).

## Domain notes and gotchas
- Keep `scoring/` and `briefing/` GENERIC — numbers + vertical metadata only. ALL lens-specific logic
  lives in `verticals/energy/`.
- **NASA POWER**: regional climatology is ONE parameter per call (fan out + nearest-neighbour join across
  POWER's differing native grids — radiation ~1° vs MERRA-2 ~0.5°×0.625°); drop -999; bbox span 2–10°/axis.
- **Suitability** is min-max normalized across the queried region (RELATIVE) and drives the ranked sites;
  the DISPLAYED field is the RAW physical metric on a FIXED absolute scale (consistent globally) — two
  expressions of the same POWER climatology. Carry both; never overclaim climatology as bankable yield.
- **Field bake**: infer the lattice resolution from the data's native spacing (POWER lat 0.5° vs lon 0.625°,
  radiation ~2° after coarsening) — rasterising onto a finer lattice leaves no-data holes that make the
  texture's ALPHA dotted. POWER rate-limits (429) under fan-out, so the bake backs off + caches per tile.
- **Cesium/resium**: build imagery/terrain providers OUTSIDE render (or memoize) — resium recreates an
  `<ImageryLayer>` whenever its `imageryProvider` prop changes (intended on lens swap, keyed). Field overlay
  = `SingleTileImageryProvider.fromUrl(/fields/<lens>.png, { rectangle: Rectangle.MAX_VALUE })` at alpha ~0.66.
  Cap `resolutionScale` at 2; lazy-load the globe; pause auto-rotate on interaction + during flyTo. Globe
  lighting is OFF so the field reads consistently everywhere (flip on for the day/night terminator look).

## DEFERRED SECOND ACT (shelved, not scrapped)
`backend/operational/` holds the original operational path: Open-Meteo ForecastProvider -> EnergyModel
(per-member MW fan) -> assess_risk (P10/P50/P90 + threshold crossings) -> POST /api/operational/assess. It
is the planned "click a chosen site -> short-term generation variability" act — kept importable, tested,
and mounted, to be revived later. `verticals/energy/solar.py` and `wind.py` are SHARED by both acts.

## Out of scope (future seams — DO NOT build yet)
- Global Wind/Solar Atlas GeoTIFF sampling (rasterio) behind the same ResourceProvider.
- Constraint layers beyond the land/water mask (shipped): protected areas, slope, grid distance.
- AOI tiler for bounding boxes larger than POWER's 10°/axis regional cap.
- Full per-cell pvlib hourly solar simulation; ERA5 backtesting; auth/multi-tenant.
- Storm forecasting / track prediction of any kind on the live-storms layer — it is OBSERVATION-ONLY (display the
  current NHC/NWS/Open-Meteo state + timestamp). NHC past/forecast track + cone of uncertainty (KMZ/shapefile -> GeoJSON)
  and a richer GPU wind-streamline layer are documented FAST-FOLLOWS, not yet built.
