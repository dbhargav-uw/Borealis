# CLAUDE.md — Borealis

## What this is
Borealis is a renewable **site-selection** platform. It runs long-term climatology through
vertical-specific suitability models to answer "where on Earth should we build solar or wind?" —
delivering a normalized, location-level suitability heatmap plus ranked candidate sites plus an
AI-generated "why this site" briefing, all on one interactive 3D globe.

**Critical framing (do not drift):** Borealis is NOT a weather forecaster and NOT (currently) an
operational risk tool. The PRODUCT is "where should this asset go", expressed as relative suitability +
ranked sites + a trustworthy plain-language explanation. The climatology is the shared INPUT. The user is
a developer/investor choosing where to deploy capital, not an operator running an existing farm.

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

ResourceCell: `{ lat, lon, values: { <POWER var>: annual_mean } }`
SuitabilityModel interface: `{ id, name, required_variables, briefing_role,
  metric_units(params), score_cell(cell, params) -> SuitabilityScore }`

## Status (update as you go)
Current phase: PIVOT to site selection — P1–P4 complete (backend + globe + LLM seam; set ANTHROPIC_API_KEY for live briefings)
- [x] P1: shelve forecast-risk to operational/ + ResourceProvider / NASAPowerProvider
- [x] P2: EnergySuitabilityModel (solar+wind) + generic score_and_rank + POST /api/suitability (live-verified)
- [x] P3: react-globe.gl heatmap + ranked sites + fly-to + lens toggle (live-verified in browser)
- [x] P4: "why this site" briefing (claude-sonnet-4-6) + "ask the globe" NL search (degrade gracefully w/o a key)
- [ ] Later: land/water + other constraints, Global Wind/Solar Atlas, agriculture lens, re-activate Act 2

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
  registry.py  vertical id -> SuitabilityModel (+ a parallel impact registry for Act 2)
  api/         FastAPI: /health, POST /api/suitability (entry: api/main.py -> app)
  operational/ DEFERRED SECOND ACT (forecast/, energy MW fan, risk, /api/operational/assess)
  tests/  scripts/
/frontend      Vite + React + TS; react-globe.gl globe (P3)
```

## Stack
- Backend: Python 3.11+, FastAPI, pydantic, uv, pytest.
- Resource (MVP): free NASA POWER climatology API (no key, global, regional bbox), behind a swappable
  ResourceProvider; Global Wind Atlas / Global Solar Atlas GeoTIFF as a later raster provider.
- Suitability: PVWatts-style annual yield for solar (pvlib available for the richer per-cell sim) + numpy
  wind power density.
- LLM: Anthropic Python SDK, structured output, claude-sonnet-4-6, for the "why this site" briefing +
  NL search (verify the current model id at docs.claude.com).
- Frontend: Vite + React + TypeScript (strict); react-globe.gl (Three.js) — heatmap layer for the
  suitability field, points/rings/labels for ranked sites, pointOfView fly-to, atmosphere. (This repo is
  React+Vite, NOT Next.js/Supabase/Stripe — the global App-Router rules do not apply here.)
- Deploy (LATER, not now): backend on Modal/Fly, frontend on Vercel.

## Commands
- Backend dev: `cd backend && uv run uvicorn api.main:app --reload`
- Backend tests: `cd backend && uv run pytest`
- Live spine smoke: `cd backend && uv run python scripts/smoke_suitability.py` (or smoke_resource.py)
- Frontend dev (P3): `cd frontend && npm run dev`
- Env: copy `.env.example` to `.env` (NASA POWER needs no key; set ANTHROPIC_API_KEY for P4).

## Domain notes and gotchas
- Keep `scoring/` and `briefing/` GENERIC — numbers + vertical metadata only. ALL lens-specific logic
  lives in `verticals/energy/`.
- **NASA POWER**: regional climatology is ONE parameter per call (fan out + nearest-neighbour join across
  POWER's differing native grids — radiation ~1° vs MERRA-2 ~0.5°×0.625°); drop -999; bbox span 2–10°/axis.
- **Suitability** is min-max normalized across the queried region (RELATIVE); carry the raw physical metric
  too. Never overclaim climatology as bankable yield.
- **react-globe.gl**: `heatmapsData` is an ARRAY OF DATASETS (`[cells]`); set explicit width/height (default
  = full window); backend `lat`/`lon` -> globe `lat`/`lng`; send both solar+wind scores per cell for an
  instant offline lens toggle.

## DEFERRED SECOND ACT (shelved, not scrapped)
`backend/operational/` holds the original operational path: Open-Meteo ForecastProvider -> EnergyModel
(per-member MW fan) -> assess_risk (P10/P50/P90 + threshold crossings) -> POST /api/operational/assess. It
is the planned "click a chosen site -> short-term generation variability" act — kept importable, tested,
and mounted, to be revived later. `verticals/energy/solar.py` and `wind.py` are SHARED by both acts.

## Out of scope (future seams — DO NOT build yet)
- Global Wind/Solar Atlas GeoTIFF sampling (rasterio) behind the same ResourceProvider.
- Constraint layers beyond the first (land/water mask is next; then protected areas, slope, grid distance).
- AOI tiler for bounding boxes larger than POWER's 10°/axis regional cap.
- Full per-cell pvlib hourly solar simulation; ERA5 backtesting; auth/multi-tenant.
