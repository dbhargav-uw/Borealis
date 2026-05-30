"""OpenMeteoProvider — free Open-Meteo Ensemble API (real fetch).

Verified live 2026-05-30. Facts baked into this implementation:
- The ensemble API lives on the ensemble-api.* subdomain (api.* 404s).
- Members are suffixed copies of each variable: the UNSUFFIXED base var is the
  control = member 0, then `<var>_member01`..`<var>_memberNN`. There is NO member00.
- A single shared `hourly.time` array; member series are time-aligned.
- Request `wind_speed_unit=ms` (default is km/h) and `timezone=GMT` (UTC, no DST).
- Some models (icon_seamless / gem_global / bom_*) return all-null wind_speed_100m;
  this provider GUARDS that and raises rather than silently emitting nulls.

The provider owns data CLEANING and surfaces upstream/parse failures as RuntimeError so
the API layer maps them to a typed 502 (never an untyped 500). Interior gaps are
forward/back-filled so NaN never reaches the (NaN-rejecting) generic risk math.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import ForecastProvider
from .constants import DEFAULT_ENSEMBLE_MODEL, ENSEMBLE_BASE_URL
from .types import EnsembleForecast


def _ffill_bfill(series: list[float | None]) -> list[float] | None:
    """Forward-fill interior nulls (carry last), then back-fill a leading null
    (use next). Returns None if the series is entirely null."""
    out: list[float | None] = list(series)
    last: float | None = None
    for i, v in enumerate(out):
        if v is None:
            out[i] = last
        else:
            last = v
    nxt: float | None = None
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            out[i] = nxt
        else:
            nxt = out[i]
    if any(v is None for v in out):
        return None
    return [float(v) for v in out]


class OpenMeteoProvider(ForecastProvider):
    def __init__(
        self,
        base_url: str = ENSEMBLE_BASE_URL,
        model: str = DEFAULT_ENSEMBLE_MODEL,
    ) -> None:
        self.base_url = base_url
        self.model = model

    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        hours: int,
        variables: list[str],
    ) -> EnsembleForecast:
        forecast_days = max(1, min(35, (hours + 23) // 24))
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(variables),
            "models": self.model,
            "forecast_days": forecast_days,
            "timezone": "GMT",          # naive ISO strings are UTC; aligns with pvlib
            "wind_speed_unit": "ms",    # SI in; impact models never guess units
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self.base_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Open-Meteo error: {data.get('reason')}")

        # Parsing failures (missing keys, bad timestamps) are provider faults -> RuntimeError
        # (-> 502), not untyped 500s. Our own RuntimeErrors below pass through unchanged.
        try:
            return self._decode(data, variables, hours)
        except RuntimeError:
            raise
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(f"Open-Meteo response malformed: {exc}") from exc

    def _decode(
        self, data: dict, variables: list[str], hours: int
    ) -> EnsembleForecast:
        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            raise RuntimeError("Open-Meteo response missing hourly data.")

        timestamps = [
            datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            for t in hourly["time"]
        ][:hours]
        n_hours = len(timestamps)

        out_vars: dict[str, list[list[float]]] = {}
        member_count = 0
        for base in variables:
            if base not in hourly:
                raise RuntimeError(
                    f"Open-Meteo did not return required variable '{base}' "
                    f"for model '{self.model}'."
                )
            # member 0 = control (unsuffixed), then _member01.._memberNN contiguously.
            raw: list[list[float | None]] = [hourly[base][:n_hours]]
            i = 1
            while (key := f"{base}_member{i:02d}") in hourly:
                raw.append(hourly[key][:n_hours])
                i += 1

            if all(v is None for member in raw for v in member):
                raise RuntimeError(
                    f"Open-Meteo model '{self.model}' returned all-null '{base}'. "
                    "Pick a model that carries it (e.g. gfs_seamless / ecmwf_ifs025)."
                )

            filled: list[list[float]] = []
            for member in raw:
                clean = _ffill_bfill(member)
                if clean is None:
                    raise RuntimeError(
                        f"Open-Meteo '{base}' has an all-null member series; cannot clean."
                    )
                if len(clean) != n_hours:
                    raise RuntimeError(
                        f"Open-Meteo '{base}' member series length {len(clean)} != {n_hours} "
                        "(ragged response)."
                    )
                filled.append(clean)

            out_vars[base] = filled
            member_count = max(member_count, len(filled))

        return EnsembleForecast(
            lat=float(data["latitude"]),
            lon=float(data["longitude"]),
            timestamps=timestamps,
            members=member_count,
            variables=out_vars,
        )
