<p align="center">
  <img src="assets/brand/borealis-logo-dark.svg" alt="Borealis" width="440" />
</p>

Weather-risk **decision** platform. One generic spine — ensemble forecast →
impact model → percentile risk → AI briefing → 3D globe — shared across four
verticals (energy, agriculture, insurance, logistics). A vertical is just a
pluggable `ImpactModel` registered in `registry.py`. See [CLAUDE.md](./CLAUDE.md)
for the authoritative spec.

## Layout

```
backend/    FastAPI spine (uv-managed)
  forecast/   ForecastProvider seam (OpenMeteoProvider now, Earth2Studio later)
  verticals/  ImpactModel interface + one module per vertical
  risk/       GENERIC percentile + threshold-crossing math
  briefing/   GENERIC Anthropic structured-output briefing
  registry.py vertical id -> ImpactModel
  api/        routes (entry: api/main.py -> app)
  tests/
frontend/   Vite + React + TS (Cesium globe lands in Phase 4)
```

## Setup

```bash
cp .env.example .env        # fill in ANTHROPIC_API_KEY when you reach Phase 3
```

### Backend

```bash
cd backend
uv sync                                   # create env + install deps
uv run uvicorn api.main:app --reload      # http://localhost:8000
uv run pytest                             # tests
```

### Frontend

```bash
cd frontend
npm install
npm run dev                               # http://localhost:5173 (proxies /health, /api -> :8000)
```

Open the frontend; it calls the backend `/health` and shows the connection
status — the Phase 1 "they're talking" proof.

## Status

- [x] Phase 1: monorepo scaffold + `/health`
- [ ] Phase 2: core slice + ENERGY (`POST /api/assess`)
- [ ] Phase 3: AI briefing (Anthropic structured output)
- [ ] Phase 4: Cesium globe + lens + fan chart + briefing + wind layer
- [ ] Phase 5: AGRICULTURE (frost) + "same storm, four decisions" demo
