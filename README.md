<p align="center">
  <img src="assets/brand/borealis-logo-dark.svg" alt="Borealis" width="440" />
</p>

**A weather map you act on**, on a high-fidelity CesiumJS globe. Land on a cohesive global
climate field, place a building (or a solar/wind farm) by natural language, find the best
site in a region, and see a grounded risk-analysis dossier — with real, live storm and wind
overlays. See [CLAUDE.md](./CLAUDE.md) for the authoritative spec.

> **Honesty first.** Flood/tornado views are **illustrative** visualizations grounded in real
> elevation (Cesium World Terrain) and NOAA SPC tornado climatology — never predictions.
> Suitability/best-site scores are a **relative climatology comparator**, not bankable yield.
> The live-storms overlay is **real, timestamped** NHC/NWS/Open-Meteo data (a separate category
> from the sim). Solar/wind models are **representative** renderings, not actual capacity.

## What it does

- **Cinematic globe** — Bing World Imagery + World Terrain via a Cesium ion token (graceful
  Natural Earth fallback), a temperature hero field, day/night terminator, drifting clouds.
- **Natural-language placement** — *"a coastal hospital in Miami"* → an Anthropic parse →
  ion geocode → a detailed, type-keyed **glTF building** (CC0 library) scaled to the parsed
  spec, among **Cesium OSM Buildings** with sun shadows.
- **Solar & wind infrastructure** — *"build a wind farm in west Texas"* renders a cluster of
  3-blade turbines with **spinning rotors** that yaw into the live wind; solar renders a
  **tilted PV panel array** (panels angled toward the equator at the site latitude).
- **Find the best site** — *"best place in Texas for a solar farm"* scores a region grid
  (`/api/best-site`): the relevant SuitabilityModel + flood/tornado **hazard penalties** +
  land mask → picks the top site, builds there, and explains **why it won** vs the alternatives.
- **Risk-analysis dossier** — on placement, `/api/analysis` composes a left-panel dossier:
  location, renewable resource (solar/wind/crop), hazard exposure (flood / tornado / live
  storms), illustrative insurance considerations, and an AI summary.
- **Grounded hazard sims** — bathtub flood inundation over real terrain; an EF-rated tornado
  driven by NOAA SPC climatology (and honest "negligible here" where true).
- **Live overlays (zoomed out)** — a nullschool-style **wind streamline field** (always on,
  GPU particle/trail pipeline) and a toggleable **storms** layer: NHC named cyclones as
  georeferenced spiral clouds + NWS tornado warning/watch polygons, each stamped with source + time.
- **Suitability spine** — the renewable site-selection engine (solar/wind/cropland lenses,
  generic score-and-rank + MCDA, ranked sites, "why this site" briefing), surfaced contextually.

## Layout

```
backend/      FastAPI (uv-managed) — entry api/main.py -> app
  resources/    ResourceProvider seam (NASA POWER + Open-Meteo ERA5) + elevation
  verticals/    SuitabilityModel interface + energy (solar/wind) + agriculture
  scoring/      GENERIC normalize + MCDA + rank
  constraints/  land/water mask
  briefing/     Anthropic structured output (parse, site/hazard/analysis/best-site briefings)
  storms/       LIVE NHC + NWS feed clients + TTL cache
  field/        climatology -> global field PNG textures
  api/          /api/{suitability,seasonal,place,analysis,best-site,tornado-climatology,
                       storms,alerts,current-wind,operational/assess}
  tests/  scripts/
frontend/     Vite + React + TS; CesiumJS globe via resium
  src/ResourceGlobe.tsx   globe, placement, glTF buildings + solar/wind infra, hazards
  src/hazard/             flood, tornado, liveStorms, liveAlerts, windFlow (cesium-wind-layer)
  src/AnalysisDossier.tsx left-panel risk dossier
  src/buildingModels.ts   type -> model (building / solar / wind)
  public/models/          CC-licensed glTF assets (see ATTRIBUTIONS.md)
```

## Setup

```bash
cp .env.example .env        # set GEMINI_API_KEY for NL parse + AI briefings
```

For the premium earth + geocoder, put a (free-tier) Cesium ion token in `frontend/.env`:

```bash
echo "VITE_CESIUM_ION_TOKEN=your_token_here" > frontend/.env
```

### Backend

```bash
cd backend
uv sync
uv run uvicorn api.main:app --reload      # http://localhost:8000
uv run pytest                             # tests
```

### Frontend

```bash
cd frontend
npm install
npm run dev                               # http://localhost:5173 (proxies /health, /api -> :8000)
```

Open the frontend and try: *"a coastal hospital in Miami"*, *"build a wind farm in west Texas"*,
or *"find the best place in Arizona for a solar farm"*.

## Status

- [x] Site-selection spine (suitability lenses, score-and-rank, ranked sites) + Cesium globe + field textures
- [x] Weather-map landing → NL building placement → grounded flood/tornado hazard sims
- [x] Live overlays: nullschool wind streamlines (always on) + NHC cyclone / NWS tornado storms (toggle)
- [x] Per-location risk-analysis dossier (`/api/analysis`)
- [x] Detailed type-keyed glTF buildings + OSM Buildings context + shadows
- [x] Find-best-site region search (`/api/best-site`) + solar-array / spinning-turbine infrastructure
- [ ] NHC track/cone (KMZ/shapefile); Global Wind/Solar Atlas enrichment; text-to-3D fallback

Data sources: NASA POWER & Open-Meteo (climatology + elevation + live wind), Cesium World Terrain,
NOAA SPC (tornado climatology), NHC (cyclones), NWS (tornado alerts), Anthropic (parse + briefings).
