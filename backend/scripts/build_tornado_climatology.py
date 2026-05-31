"""Build a fine-grained tornado climatology grid from the NOAA SPC tornado database.

Downloads SPC's 1950–present tornado CSV (start lat/lon + EF/Fujita magnitude per tornado), bins it to
1° cells, and writes backend/data/tornado_climatology.json = { years, cells: [{lat, lon, region,
annual_frequency, ef_distribution, dominant_ef, negligible}] }. The /api/tornado-climatology endpoint
prefers this grid when present and otherwise uses a coarse built-in SPC-based model.

Usage (from backend/):  uv run python scripts/build_tornado_climatology.py
Source: https://www.spc.noaa.gov/wcm/  (Severe Weather Maps, Graphics, and Data — tornado database)
"""

from __future__ import annotations

import csv
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUT = BACKEND_DIR / "data" / "tornado_climatology.json"
# SPC "Watch/Warning/Mesoscale" tornado database (actual tornadoes). Update the year as SPC publishes.
SPC_CSV_URL = "https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv"
EF_KEYS = ["EF0", "EF1", "EF2", "EF3", "EF4", "EF5"]


def main() -> None:
    print(f"Downloading SPC tornado database: {SPC_CSV_URL}")
    try:
        resp = httpx.get(SPC_CSV_URL, timeout=120.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Download failed: {exc}\n(The endpoint still works via the coarse built-in model.)")
        sys.exit(1)

    reader = csv.DictReader(io.StringIO(resp.text))
    counts: dict[tuple[int, int], int] = defaultdict(int)
    ef_hist: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    years: set[int] = set()

    for row in reader:
        try:
            lat, lon, mag = float(row["slat"]), float(row["slon"]), int(float(row["mag"]))
            yr = int(row["yr"])
        except (KeyError, ValueError, TypeError):
            continue
        if lat == 0.0 and lon == 0.0:
            continue  # missing location
        years.add(yr)
        cell = (int(lat // 1), int(lon // 1))
        counts[cell] += 1
        if 0 <= mag <= 5:
            ef_hist[cell][mag] += 1

    n_years = max(1, len(years))
    cells = []
    for (clat, clon), n in counts.items():
        hist = ef_hist[(clat, clon)]
        total = sum(hist) or 1
        dist = {EF_KEYS[i]: round(hist[i] / total, 4) for i in range(6)}
        freq = round(n / n_years, 3)
        cells.append({
            "lat": clat + 0.5,
            "lon": clon + 0.5,
            "region": "NOAA SPC 1° cell",
            "annual_frequency": freq,
            "ef_distribution": dist,
            "dominant_ef": max(range(6), key=lambda i: hist[i]),
            "negligible": freq < 0.02,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"years": sorted(years)[:1] + sorted(years)[-1:], "cells": cells}))
    print(f"Wrote {OUT} — {len(cells)} cells over {n_years} years ({len(cells)} populated 1° boxes).")


if __name__ == "__main__":
    main()
