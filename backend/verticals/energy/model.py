"""EnergyModel — the ONE 'energy' ImpactModel. Branches on asset.params['kind'] in
{solar, wind}; both emit the same unit (MW) under one briefing role. Energy is a single
vertical: solar and wind are two ways to produce the same MW for the same decision
(day-ahead bid / imbalance / maintenance timing)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from forecast.types import EnsembleForecast
from verticals.base import Asset, ImpactEnsemble, ImpactModel

from .params import SolarParams, WindParams, parse_energy_params
from .solar import solar_ac_mw_for_member, solar_position
from .wind import extrapolate_to_hub, wind_power_mw

_SOLAR_REQUIRED = ("shortwave_radiation", "temperature_2m", "wind_speed_10m")


class EnergyModel(ImpactModel):
    id = "energy"
    name = "Energy generation"
    units = "MW"
    briefing_role = "energy risk analyst"
    # Union across solar + wind; the provider fetches all in one ensemble call.
    required_variables = [
        "shortwave_radiation",
        "temperature_2m",
        "wind_speed_10m",
        "wind_speed_100m",
    ]

    def apply(self, forecast: EnsembleForecast, asset: Asset) -> ImpactEnsemble:
        params = parse_energy_params(asset.params)
        if isinstance(params, WindParams):
            series = self._wind(forecast, params)
        else:
            series = self._solar(forecast, asset, params)
        return ImpactEnsemble(units=self.units, timestamps=forecast.timestamps, series=series)

    def _wind(self, forecast: EnsembleForecast, p: WindParams) -> list[list[float]]:
        variables = forecast.variables
        if "wind_speed_100m" in variables:
            wind = variables["wind_speed_100m"]
        elif "wind_speed_10m" in variables:
            wind = extrapolate_to_hub(
                variables["wind_speed_10m"], hub_height_m=p.hub_height_m, alpha=p.shear_alpha
            )
        else:
            raise ValueError(
                "wind energy requires 'wind_speed_100m' (or 'wind_speed_10m' to extrapolate)."
            )
        mw = wind_power_mw(
            wind,
            rated_power_kw=p.rated_power_kw,
            n_turbines=p.n_turbines,
            cut_in_ms=p.cut_in_ms,
            rated_ms=p.rated_ms,
            cut_out_ms=p.cut_out_ms,
            availability=p.availability,
        )
        return np.asarray(mw, dtype=float).tolist()

    def _solar(
        self, forecast: EnsembleForecast, asset: Asset, p: SolarParams
    ) -> list[list[float]]:
        variables = forecast.variables
        for name in _SOLAR_REQUIRED:
            if name not in variables:
                raise ValueError(f"solar energy requires '{name}' in the forecast.")

        idx = pd.DatetimeIndex(forecast.timestamps)
        # SPA depends only on lat/lon/time — compute once, reuse across all members.
        zenith, azimuth = solar_position(idx, asset.lat, asset.lon)

        ghi = variables["shortwave_radiation"]
        temp = variables["temperature_2m"]
        wind = variables["wind_speed_10m"]
        # All solar inputs must share a member count, else the fan would silently be
        # computed over fewer members than forecast_summary reports. Fail loud instead.
        counts = {len(ghi), len(temp), len(wind)}
        if len(counts) != 1:
            raise ValueError(
                f"solar energy: mismatched ensemble member counts across variables "
                f"({len(ghi)}/{len(temp)}/{len(wind)}); cannot align the fan."
            )
        n_members = len(ghi)

        members: list[np.ndarray] = []
        for m in range(n_members):
            ac_mw = solar_ac_mw_for_member(
                idx,
                ghi[m],
                temp[m],
                wind[m],
                lat=asset.lat,
                lon=asset.lon,
                dc_capacity_kw=p.dc_capacity_kw,
                surface_tilt=p.surface_tilt,
                surface_azimuth=p.surface_azimuth,
                gamma_pdc=p.gamma_pdc,
                system_loss=p.system_loss,
                ac_dc_ratio=p.ac_dc_ratio,
                albedo=p.albedo,
                eta_inv_nom=p.eta_inv_nom,
                sky_model=p.sky_model,
                temperature_model=p.temperature_model,
                zenith=zenith,
                azimuth=azimuth,
            )
            members.append(ac_mw.to_numpy())

        return np.vstack(members).astype(float).tolist()
