# CLAUDE.md — Borealis

## What this is
Borealis is a weather-risk decision PLATFORM. It runs state-of-the-art AI ensemble
weather forecasts ONCE, then routes them through vertical-specific impact models to
deliver probabilistic, asset-level risk and an AI-generated briefing across four
verticals: renewable energy, agriculture, insurance, and logistics. Everything
renders on one interactive 3D globe.

**Critical framing (do not drift):** Borealis is NOT a general weather forecaster.
We run the best models' class and package them into decisions. The forecast is the
shared INPUT. The PRODUCT, in every vertical, is probabilistic asset-level risk plus
a plain-language explanation plus an interface someone trusts enough to act on.

**The platform principle:** every vertical is the same pipeline and differs in
exactly ONE place. Each vertical = an asset at a location + an impact function
(weather -> that domain's units) + a threshold + a decision. The forecast engine,
the ensemble/risk math, the globe, and the briefing layer are SHARED and
vertical-agnostic. Only the impact function and the meaning of "risk" change per
vertical. Adding a vertical = writing one ImpactModel.

## The verticals  { asset / weather->impact / risk metric / decision }
- **Energy:** solar or wind farm; irradiance and wind -> MW (pvlib, power curve);
  P10/50/90 generation and P(below bid floor); day-ahead bid, imbalance penalty,
  maintenance timing.
- **Agriculture:** field or orchard (crop, growth stage); overnight temp, precip,
  humidity, wind -> frost flag, heat stress, spray-window suitability, wetness;
  P(frost in 72h), P(spray window day X); frost protection, irrigation/spray/harvest
  timing.
- **Insurance:** portfolio of insured locations or a parametric trigger zone; gust,
  rainfall, hail proxy -> P(trigger hit) and expected exposure; P(payout),
  aggregate exposure; pre-position reserves, early payout, reinsurance hedge,
  policyholder alerts.
- **Logistics:** a route or fleet of lanes; wind, precip, visibility, snow along the
  route -> disruption score and delay-hours distribution; P(delay > X),
  P(disruption); reroute, reschedule, dynamic ETA.

Validation: the same Earth-2 model class is already used by energy majors
(TotalEnergies, Eni) and insurers (AXA).

## Honest constraints (bake in, never hide)
- These models smooth peak winds and underplay extremes. Never claim extreme-event
  skill. Frame value as probabilistic risk and lead time. This matters MOST for
  insurance and logistics, which care precisely about the extremes.
- Impact functions (pvlib, power curves, frost thresholds, trigger logic) add their
  own error. Surface uncertainty, do not hide it.
- A forecast is a distribution, not a point. Carry the full ensemble through to
  percentiles. Never collapse to a single number too early.

## Status (update as you go)
Current phase: Phase 2 complete (energy solar+wind, /api/assess verified live) — awaiting sign-off before Phase 3
- [x] Phase 1: monorepo scaffold + /health endpoint the frontend hits
- [x] Phase 2: core slice + ENERGY module (forecast -> impact -> risk, POST /api/assess)
- [ ] Phase 3: briefing (Anthropic structured output), vertical-aware
- [ ] Phase 4: frontend (Cesium globe, lens toggle, fan chart, briefing, wind layer)
- [ ] Phase 5: second vertical = AGRICULTURE (frost) + demo polish
- [ ] Later: insurance + logistics modules

## Working philosophy in this repo
- MVP first. Always keep the app runnable. Build and verify ONE layer at a time.
- Build the platform abstraction for real, but ship ONE vertical deep (energy)
  before adding others. Frost (agriculture) is the cheapest second vertical and the
  best for the "same storm, four decisions" demo.
- Type everything (pydantic backend, TS frontend). Leave clean seams. Stop and
  confirm before any large detour.

## Stack
- Backend: Python 3.11+, FastAPI, pydantic, uv for deps, pytest.
- Forecast (MVP): free Open-Meteo Ensemble API, behind a swappable ForecastProvider.
- Impact models: pvlib (solar) and a turbine power-curve model or windpowerlib (wind)
  for energy; simple threshold logic for the other verticals (see domain notes).
- LLM: Anthropic Python SDK, latest Claude model (verify the current id at
  docs.claude.com), structured output for the briefing.
- Frontend: Vite + React + TypeScript; CesiumJS via resium + vite-plugin-cesium;
  animated wind-particle layer (cesium-wind-layer or custom GPU layer); recharts for
  the percentile fan chart.
- Deploy (LATER, not now): backend + GPU forecast on Modal, frontend on Vercel.

## Repo structure (monorepo)
```
/backend
  forecast/    ForecastProvider; OpenMeteoProvider now, Earth2StudioProvider stub
  verticals/   ImpactModel interface + one module per vertical:
                 energy/ (pvlib + power curve), agri/ (frost etc.),
                 insurance/ (trigger + exposure), logistics/ (route disruption)
  risk/        GENERIC percentile + threshold-crossing math over an ImpactEnsemble
  briefing/    GENERIC Anthropic call, parameterized by vertical metadata
  registry.py  maps vertical id -> ImpactModel
  api/         FastAPI routes (entry: api/main.py exposing `app`)
  tests/
/frontend
  src/         globe, vertical/lens selector, asset panel, fan chart, briefing panel
CLAUDE.md      this file
README.md
.env.example   ANTHROPIC_API_KEY etc. (never commit a real .env)
```

## Core contract (GENERIC over verticals)
- `get_ensemble_forecast(lat, lon, hours) -> EnsembleForecast`        # N members, hourly fields
- `ImpactModel.apply(forecast, asset) -> ImpactEnsemble`              # per-member series in the vertical's units
- `assess_risk(impact_ensemble, thresholds) -> RiskAssessment`       # generic percentiles + P(cross threshold)
- `generate_briefing(forecast, impact_ensemble, risk, asset, vertical_meta) -> RiskBriefing`
      # structured: headline, probability, recommended_action, confidence, drivers[]
- `POST /api/assess { vertical, asset, thresholds } -> { forecast_summary, impact_fan, risk, briefing }`

Asset: `{ name, lat, lon, vertical, params }`  # params is vertical-specific
ImpactModel interface: `{ id, name, units, required_variables, apply(forecast, asset) -> ImpactEnsemble, briefing_role }`

## Commands
- Backend dev: `cd backend && uv run uvicorn api.main:app --reload`
- Backend tests: `cd backend && uv run pytest`
- Frontend dev: `cd frontend && npm run dev`
- Env: copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`. Keys only in `.env`.

## Domain notes and gotchas
- Keep `risk/` and `briefing/` GENERIC. They operate on a numeric ImpactEnsemble
  plus the vertical's metadata. ALL vertical-specific logic lives in `verticals/`.
- **Open-Meteo Ensemble API** (`api.open-meteo.com/v1/ensemble`): verify variable
  names against the live docs. Each module declares `required_variables`; fetch the
  union across active verticals.
- **Energy:** irradiance + temp -> PV via a simple PVWatts-style pvlib model, scaled
  to capacity. Wind: hub-height wind -> power curve, clamp below cut-in and above
  cut-out, cap at rated. Write pytest tests for this and the risk math (most
  error-prone).
- **Agriculture (cheapest, build second):** frost = count of members whose min temp
  drops below a crop threshold -> P(frost). Spray window = low wind AND dry. These
  are simple ensemble threshold counts.
- **Insurance:** pick ONE parametric trigger first (e.g. gust > threshold at the
  location) -> P(trigger). Exposure = sum over a small portfolio.
- **Logistics:** sample weather along a route polyline; disruption = members where
  wind/precip/visibility breach limits -> P(disruption) and a delay-hours
  distribution.
- **Anthropic briefing:** structured output (typed JSON, not prose). The system
  prompt uses the vertical's `briefing_role` (energy risk analyst / agronomist /
  cat-risk analyst / logistics dispatcher). It is GIVEN the numbers, explains the
  weather drivers, recommends an action with a confidence level, and NEVER invents
  numbers.
- **Cesium + Vite:** use vite-plugin-cesium to bundle assets and set
  CESIUM_BASE_URL; resium provides React components; a Cesium ion token is optional
  for the MVP; stick to the default WebGL renderer unless WebGPU is clearly stable.
  The lens toggle re-colors the globe and swaps the active asset set per vertical.
  The wind layer is Phase 4 polish, not a Phase 2 blocker.

## Demo centerpiece
One globe, a vertical/lens toggle. A single storm front sweeps the map; toggling
lenses shows the SAME weather as four different risks across four asset types (wind
farm output, vineyard frost, insurer payout trigger, freight-lane delay), each with
its own briefing. Same weather, four decisions.

## Out of scope (future seams — DO NOT build yet)
- Self-hosted NVIDIA Earth2Studio (AIFS-ENS + CorrDiff) on Modal, behind
  ForecastProvider.
- Backtesting against ERA5 reanalysis.
- Real portfolio/fleet ingestion at scale, auth, multi-tenant.
