"""Bake the continuous global resource-field textures from NASA POWER climatology.

Produces one smooth equirectangular PNG per lens (solar, wind) + a meta.json (color scale +
legend), written to frontend/public/fields/, for the Cesium globe to drape as a single
translucent ImageryLayer. NASA POWER caps a regional request at 10°/axis and one parameter per
call, so a global field is ~648 tiles/variable: we fetch them with polite concurrency and CACHE
each tile to disk, so the bake is resumable across flaky runs and reruns are instant.

Usage (from backend/):
    uv run python scripts/bake_field_textures.py                 # global solar + wind
    uv run python scripts/bake_field_textures.py --vars wind     # just wind
    uv run python scripts/bake_field_textures.py --bbox 30,-15,72,45   # a region (rest stays clear)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

# Allow `python scripts/bake_field_textures.py` from backend/ (add backend/ to path).
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from field import FIELD_SPECS, field_meta, render_field_png  # noqa: E402
from field.render import FieldSpec  # noqa: E402
from resources import NASAPowerProvider  # noqa: E402
from resources.types import ResourceCell, ResourceGrid  # noqa: E402

CACHE_DIR = BACKEND_DIR / ".cache" / "field"
DEFAULT_OUT = BACKEND_DIR.parent / "frontend" / "public" / "fields"
GLOBAL_BBOX = (-90.0, -180.0, 90.0, 180.0)


def _tiles(bbox: tuple[float, float, float, float], tile: float) -> list[tuple[float, float, float, float]]:
    lat_min, lon_min, lat_max, lon_max = bbox

    def bands(lo: float, hi: float) -> list[tuple[float, float]]:
        n = max(1, math.ceil((hi - lo) / tile - 1e-9))
        step = (hi - lo) / n
        return [(lo + i * step, lo + (i + 1) * step) for i in range(n)]

    return [
        (a0, o0, a1, o1)
        for (a0, a1) in bands(lat_min, lat_max)
        for (o0, o1) in bands(lon_min, lon_max)
    ]


def _cache_path(var: str, t: tuple[float, float, float, float]) -> Path:
    key = f"{t[0]:+06.1f}_{t[1]:+06.1f}_{t[2]:+06.1f}_{t[3]:+06.1f}".replace(".", "p")
    return CACHE_DIR / var / f"{key}.json"


async def _tile_cells(
    provider: NASAPowerProvider,
    sem: asyncio.Semaphore,
    var: str,
    res: float,
    t: tuple[float, float, float, float],
    retries: int = 5,
) -> list[tuple[float, float, float]]:
    """(lat, lon, value) triples for one tile/variable — from cache if present, else POWER.
    NASA POWER rate-limits (429) under fan-out, so we back off and retry outside the semaphore."""
    cache = _cache_path(var, t)
    if cache.exists():
        return [tuple(x) for x in json.loads(cache.read_text())]  # type: ignore[misc]
    delay = 1.5
    for attempt in range(retries + 1):
        try:
            async with sem:
                grid = await provider.get_resource_grid(t, res, [var])
        except Exception as exc:  # noqa: BLE001 -- one bad tile must not kill the whole bake
            if "429" in str(exc) and attempt < retries:
                await asyncio.sleep(delay)  # backoff with the semaphore released
                delay = min(delay * 1.8, 20.0)
                continue
            print(f"  ! tile {t} [{var}] failed: {exc}")
            return []
        triples = [(c.lat, c.lon, c.values[var]) for c in grid.cells if var in c.values]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(triples))
        return triples
    return []


async def _bake_one(
    provider: NASAPowerProvider,
    sem: asyncio.Semaphore,
    spec: FieldSpec,
    bbox: tuple[float, float, float, float],
    res: float,
    tile: float,
    out_dir: Path,
) -> dict[str, object]:
    tiles = _tiles(bbox, tile)
    print(f"[{spec.id}] {spec.variable}: {len(tiles)} tiles (res {res}°)…")
    results = await asyncio.gather(
        *(_tile_cells(provider, sem, spec.variable, res, t) for t in tiles)
    )
    cells: list[ResourceCell] = []
    non_empty = 0
    for triples in results:
        if triples:
            non_empty += 1
        for lat, lon, val in triples:
            cells.append(ResourceCell(lat=lat, lon=lon, values={spec.variable: val}))
    grid = ResourceGrid(bbox=bbox, resolution=res, variables=[spec.variable], cells=cells)
    png = render_field_png(grid, spec)  # base_res inferred from the data's native spacing
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{spec.id}.png").write_bytes(png)
    print(
        f"[{spec.id}] {non_empty}/{len(tiles)} tiles with data, {len(cells)} cells "
        f"-> {spec.id}.png ({len(png) // 1024} KB)"
    )
    return field_meta(spec).to_dict()


async def main() -> None:
    ap = argparse.ArgumentParser(description="Bake global resource-field textures from NASA POWER.")
    ap.add_argument("--vars", default="solar,wind", help="comma list of field ids (solar,wind)")
    ap.add_argument("--bbox", default=None, help="lat_min,lon_min,lat_max,lon_max (default: global)")
    ap.add_argument("--res", type=float, default=1.0, help="grid resolution in degrees (default 1.0)")
    ap.add_argument("--tile", type=float, default=10.0, help="tile span per axis (POWER cap 10°)")
    ap.add_argument("--concurrency", type=int, default=8, help="max concurrent POWER requests")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output directory for PNGs + meta.json")
    args = ap.parse_args()

    ids = [v.strip() for v in args.vars.split(",") if v.strip()]
    unknown = [v for v in ids if v not in FIELD_SPECS]
    if unknown:
        ap.error(f"unknown field ids {unknown}; have {sorted(FIELD_SPECS)}")
    bbox = GLOBAL_BBOX if not args.bbox else tuple(float(x) for x in args.bbox.split(","))  # type: ignore[assignment]
    out_dir = Path(args.out)

    provider = NASAPowerProvider()
    sem = asyncio.Semaphore(args.concurrency)
    metas: dict[str, object] = {}
    for fid in ids:
        metas[fid] = await _bake_one(provider, sem, FIELD_SPECS[fid], bbox, args.res, args.tile, out_dir)

    meta = {"resolution": args.res, "bbox": list(bbox), "fields": metas}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\nWrote {out_dir / 'meta.json'} with fields: {', '.join(metas)}")


if __name__ == "__main__":
    asyncio.run(main())
