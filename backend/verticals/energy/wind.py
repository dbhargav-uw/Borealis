"""Dependency-light wind-farm power-curve sub-model (numpy only).

Maps hub-height wind speed (m/s) -> AC power (MW), vectorized over [member][hour].
Secondary to the solar PV model; both feed the one EnergyModel and emit units "MW".

Power-curve shape (standard textbook approximation, P ∝ v³ in partial load):
    v < cut_in            -> 0
    cut_in <= v < rated   -> cubic ramp  P = rated * (v³ - cut_in³)/(rated³ - cut_in³)
    rated <= v <= cut_out -> rated
    v > cut_out           -> 0   (hard shutdown cliff)

HONEST CONSTRAINT (CLAUDE.md): NWP/AI ensembles smooth peak winds, and the v³ ramp
AMPLIFIES wind error (~5% wind bias near rated ≈ ~15% power bias before the rated cap
clips it). The 25 m/s cut-out is a cliff — members straddling it swing rated↔0. That
spread is REAL signal: it MUST survive to the P10/50/90 fan; never collapse to the mean.
Single representative turbine × n_turbines ignores wakes/spatial variation — `availability`
is the honest de-rate seam (default 1.0).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def turbine_power_fraction(
    wind_ms: NDArray[np.floating] | list[list[float]],
    *,
    cut_in_ms: float,
    rated_ms: float,
    cut_out_ms: float,
) -> NDArray[np.float64]:
    """Per-turbine output as a fraction of rated power in [0, 1]. Pure; shape-preserving."""
    v = np.asarray(wind_ms, dtype=np.float64)

    denom = rated_ms**3 - cut_in_ms**3
    if denom <= 0:
        raise ValueError("rated_ms must be > cut_in_ms")
    ramp = (v**3 - cut_in_ms**3) / denom

    frac = np.where(
        v < cut_in_ms,
        0.0,
        np.where(
            v < rated_ms,
            ramp,                                  # cut_in..rated: cubic
            np.where(v <= cut_out_ms, 1.0, 0.0),   # rated..cut_out flat; >cut_out shutdown
        ),
    )
    frac = np.clip(frac, 0.0, 1.0)  # guard float noise at boundaries
    # A NaN wind (forecast gap) must NOT be laundered into the >cut_out 0.0 branch — let it
    # propagate so the generic risk NaN-guard fires instead of fabricating 0 MW.
    return np.where(np.isnan(v), np.nan, frac)


def wind_power_mw(
    wind_ms: NDArray[np.floating] | list[list[float]],
    *,
    rated_power_kw: float = 3000.0,
    n_turbines: int = 1,
    cut_in_ms: float = 3.0,
    rated_ms: float = 12.0,
    cut_out_ms: float = 25.0,
    availability: float = 1.0,
) -> NDArray[np.float64]:
    """Farm AC power in MW, vectorized over [member][hour].

    `wind_ms`: hub-height wind speed (m/s) — Open-Meteo `wind_speed_100m`, fetched with
    wind_speed_unit=ms. Returns float64 [member, hour] MW.
    """
    frac = turbine_power_fraction(
        wind_ms, cut_in_ms=cut_in_ms, rated_ms=rated_ms, cut_out_ms=cut_out_ms
    )
    farm_rated_mw = (rated_power_kw / 1000.0) * n_turbines  # kW -> MW
    return frac * farm_rated_mw * availability


def extrapolate_to_hub(
    wind_ref_ms: NDArray[np.floating] | list[list[float]],
    *,
    ref_height_m: float = 10.0,
    hub_height_m: float = 100.0,
    alpha: float = 0.143,  # 1/7 power law, neutral open terrain
) -> NDArray[np.float64]:
    """Power-law wind shear v_hub = v_ref * (hub/ref)^alpha. FALLBACK only — prefer the
    native wind_speed_100m field; extrapolation adds error (alpha varies with stability)."""
    v = np.asarray(wind_ref_ms, dtype=np.float64)
    return v * (hub_height_m / ref_height_m) ** alpha
