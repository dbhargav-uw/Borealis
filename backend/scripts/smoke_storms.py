"""Smoke the LIVE feeds: NHC cyclones + NWS tornado alerts + Open-Meteo current wind.

Hits the REAL endpoints. Empty results are a PASS (off-season / no active alert). Prints counts +
timestamps + a wind sample so you can eyeball that the plumbing + honesty timestamps work.

Run: cd backend && uv run python scripts/smoke_storms.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # backend/ on path

from api.config import get_settings  # noqa: E402
from operational.forecast.current_wind import build_current_wind  # noqa: E402
from storms import build_alerts_response, build_storms_response  # noqa: E402


async def main() -> None:
    s = get_settings()

    print("== NHC active tropical cyclones ==")
    storms = await build_storms_response(s.nhc_current_storms_url)
    print(f"as_of={storms.as_of}  source={storms.source}")
    print(f"coverage: {storms.coverage}")
    if not storms.storms:
        print("  (none active — normal off-season; empty is a PASS)")
    for st in storms.storms:
        print(
            f"  {st.name} [{st.classification}] Cat{st.category} {st.max_wind_kt:.0f} kt "
            f"@ ({st.lat:.1f},{st.lon:.1f}) moving {st.movement}"
        )

    print("\n== NWS active tornado warnings/watches ==")
    alerts = await build_alerts_response(s.nws_alerts_url, s.nws_user_agent)
    print(f"as_of={alerts.as_of}  source={alerts.source}")
    print(f"coverage: {alerts.coverage}")
    print(f"  active: {len(alerts.alerts)} (empty is a PASS)")
    for a in alerts.alerts[:5]:
        print(f"  {a.event} [{a.severity}] {a.area_desc[:60]} expires {a.expires_at}")

    print("\n== Open-Meteo live current wind grid ==")
    grid = await build_current_wind(s.open_meteo_forecast_url, s.current_wind_resolution)
    nonzero = sum(1 for sp in grid.speed if sp > 0)
    print(f"as_of={grid.as_of}  {grid.ny}x{grid.nx} cells @ {grid.resolution}°  ({nonzero} with wind)")
    print(f"  note: {grid.note}")
    mid = (grid.ny // 2) * grid.nx + grid.nx // 2
    print(f"  sample mid-cell  u={grid.u[mid]:.1f}  v={grid.v[mid]:.1f}  speed={grid.speed[mid]:.1f} m/s")


if __name__ == "__main__":
    asyncio.run(main())
