"""Solar PV impact sub-model — explicit pvlib pipeline (the deep energy slice).

GHI (+ air temp, wind) -> AC power (MW) for ONE ensemble member, scaled to a plant DC
capacity. Pipeline: solar position -> Erbs decomposition (GHI->DNI/DHI) -> POA
transposition -> cell temperature -> PVWatts DC -> inverter clipping -> MW.

Chosen explicit (not ModelChain) so each stage is unit-testable and vectorizes cleanly
across ensemble members.

HONEST CONSTRAINT (CLAUDE.md): the impact function adds its own error on top of the
forecast — irradiance decomposition + sky transposition + cell-temp model + a lumped
PVWatts loss + single-aggregate-inverter clipping. P50 is not truth; carry the full
ensemble through to percentiles and surface the uncertainty.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pvlib import atmosphere, inverter, irradiance, pvsystem, solarposition, temperature


def _utc_index(times_utc: pd.DatetimeIndex | list) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(times_utc)
    return idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")


def solar_position(
    times_utc: pd.DatetimeIndex | list, lat: float, lon: float
) -> tuple[pd.Series, pd.Series]:
    """Apparent zenith + azimuth (degrees) for a location/time. Member-INDEPENDENT —
    compute once per request and reuse across all ensemble members (it dominates cost)."""
    idx = _utc_index(times_utc)
    solpos = solarposition.get_solarposition(idx, lat, lon)
    return solpos["apparent_zenith"], solpos["azimuth"]


def solar_ac_mw_for_member(
    times_utc: pd.DatetimeIndex | list,
    ghi: NDArray[np.floating] | list[float],
    temp_air: NDArray[np.floating] | list[float],
    wind_speed: NDArray[np.floating] | list[float],
    *,
    lat: float,
    lon: float,
    dc_capacity_kw: float,
    surface_tilt: float,
    surface_azimuth: float,
    gamma_pdc: float,
    system_loss: float,
    ac_dc_ratio: float,
    albedo: float = 0.25,
    eta_inv_nom: float = 0.96,
    sky_model: str = "isotropic",
    temperature_model: str = "faiman",
    zenith: pd.Series | None = None,
    azimuth: pd.Series | None = None,
) -> pd.Series:
    """AC power (MW) per hour for ONE ensemble member.

    Pass precomputed `zenith`/`azimuth` (from solar_position) to avoid recomputing the
    SPA per member; omit them and they're computed from lat/lon/times (handy in tests).
    """
    idx = _utc_index(times_utc)
    ghi_arr = np.asarray(ghi, dtype=float)
    temp_arr = np.asarray(temp_air, dtype=float)
    wind_arr = np.asarray(wind_speed, dtype=float)
    ghi_s = pd.Series(ghi_arr, index=idx)
    tair_s = pd.Series(temp_arr, index=idx)
    wind_s = pd.Series(wind_arr, index=idx)

    if zenith is None or azimuth is None:
        zenith, azimuth = solar_position(idx, lat, lon)

    # GHI -> DNI/DHI (Erbs). Force zero at night / sun below horizon.
    decomp = irradiance.erbs(ghi_s, zenith, idx)
    night = (ghi_s <= 0) | (zenith >= 90)
    dni = decomp["dni"].where(~night, 0.0)
    dhi = decomp["dhi"].where(~night, 0.0)

    # Plane-of-array irradiance. dni_extra/airmass are supplied so non-isotropic sky
    # models (haydavies/perez/...) work too; the default isotropic model ignores them.
    dni_extra = irradiance.get_extra_radiation(idx)
    airmass = atmosphere.get_relative_airmass(zenith)
    poa = irradiance.get_total_irradiance(
        surface_tilt=surface_tilt,
        surface_azimuth=surface_azimuth,
        solar_zenith=zenith,
        solar_azimuth=azimuth,
        dni=dni,
        ghi=ghi_s,
        dhi=dhi,
        dni_extra=dni_extra,
        airmass=airmass,
        albedo=albedo,
        model=sky_model,
    )
    poa_global = poa["poa_global"].clip(lower=0).fillna(0.0)

    # Cell temperature.
    if temperature_model == "sapm":
        sapm_params = temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"]
        temp_cell = temperature.sapm_cell(poa_global, tair_s, wind_s, **sapm_params)
    else:  # faiman (default): POA, air temp, 10 m wind, no module-construction params
        temp_cell = temperature.faiman(poa_global, tair_s, wind_s)

    # DC power (PVWatts). pdc0 in W. Pass effective irradiance POSITIONALLY so this works
    # across pvlib <0.13 (g_poa_effective) and >=0.13 (effective_irradiance).
    array_pdc0_w = dc_capacity_kw * 1000.0
    p_dc = pvsystem.pvwatts_dc(poa_global, temp_cell, array_pdc0_w, gamma_pdc)
    p_dc = p_dc * (1.0 - system_loss)  # lumped system DC losses

    # AC power + inverter clipping. inverter pdc0 = array_pdc0 / ILR -> realistic midday clip.
    inv_pdc0_w = array_pdc0_w / ac_dc_ratio
    p_ac = inverter.pvwatts(p_dc, inv_pdc0_w, eta_inv_nom=eta_inv_nom)

    # The fillna below absorbs pvlib's spurious NaN at zero DC power (night) — a physical
    # zero. A GENUINE input gap (NaN GHI/temp/wind) must NOT be laundered into a fabricated
    # 0 MW; re-apply NaN where the input was NaN so the generic risk NaN-guard fires.
    p_ac_mw = (p_ac.clip(lower=0).fillna(0.0)) / 1e6
    bad = np.isnan(ghi_arr) | np.isnan(temp_arr) | np.isnan(wind_arr)
    if bad.any():
        p_ac_mw = p_ac_mw.copy()
        p_ac_mw.iloc[bad] = np.nan
    p_ac_mw.name = "ac_mw"
    return p_ac_mw
