# Borealis — frontend

Vite + React + TypeScript client for Borealis. See the repo-root
[`README.md`](../README.md) and [`CLAUDE.md`](../CLAUDE.md) for the full picture.

## Dev

```bash
npm install
npm run dev      # http://localhost:5173
```

The dev server proxies `/health` and `/api` to the backend on `http://localhost:8000`
(see `vite.config.ts`), so the app calls the API same-origin with no CORS in dev.
Start the backend first (`cd ../backend && uv run uvicorn api.main:app --reload`).

## Scripts

- `npm run dev` — dev server with HMR
- `npm run build` — `tsc -b` (strict type-check) then production build
- `npm run lint` — ESLint
- `npm run preview` — preview the production build

## Conventions

TS strict mode; no `any` (use `unknown` + narrowing); explicit return types; named
exports; external input validated with Zod (`src/lib/api.ts`); `console` goes
through the prod-no-op `logger` (`src/lib/logger.ts`).

## Status

Phase 1 renders a backend-connection panel (loading / error / connected) driven by
`/health`. The Cesium globe, lens selector, fan chart, briefing panel, and wind
layer land in Phase 4.
