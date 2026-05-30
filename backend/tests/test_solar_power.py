"""Solar PV pipeline tests. The zero-GHI and inverter-clip cases are exact; the daytime
magnitude bounds are deliberately loose (synthetic GHI fixture) but catch unit slips."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from verticals.energy.solar import solar_ac_mw_for_member

LAT, LON = 33.45, -112.07  # Phoenix
COMMON = dict(
    lat=LAT,
    lon=LON,
    dc_capacity_kw=1000.0,  # 1 MW DC
    surface_tilt=25.0,
    surface_azimuth=180.0,
    gamma_pdc=-0.004,
    system_loss=0.14,
    ac_dc_ratio=1.2,
)
# AC clip cap = dc_capacity_w / ac_dc_ratio * eta_inv_nom = 1e6/1.2*0.96 = 0.80 MW.
CLIP_CAP_MW = (1000.0 * 1000.0 / 1.2) * 0.96 / 1e6


def _day_index() -> pd.DatetimeIndex:
    # 2026-06-21 hourly UTC; local solar noon ~19:00 UTC at this longitude.
    return pd.date_range("2026-06-21 00:00", periods=24, freq="h", tz="UTC")


def test_zero_ghi_gives_zero_ac() -> None:
    idx = _day_index()
    ac = solar_ac_mw_for_member(
        idx, ghi=np.zeros(24), temp_air=np.full(24, 20.0), wind_speed=np.full(24, 2.0), **COMMON
    )
    assert (ac.values >= 0).all()        # no negative inverter leak
    assert ac.max() < 1e-6               # no sun -> ~0 everywhere


def test_daytime_magnitude_is_sane() -> None:
    idx = _day_index()
    ghi = np.zeros(24)
    for h in range(13, 24):              # rough daylight band (UTC) for this lon
        ghi[h] = max(0.0, 900 - abs(h - 19) * 130)
    ac = solar_ac_mw_for_member(
        idx, ghi=ghi, temp_air=np.full(24, 35.0), wind_speed=np.full(24, 3.0), **COMMON
    )
    peak = float(ac.max())
    assert 0.2 <= peak <= CLIP_CAP_MW + 1e-6        # sane magnitude, never above clip
    assert ac.values.min() >= 0.0
    assert 1.0 <= float(ac.sum()) <= 9.0            # daily MWh for a 1 MW plant


def test_inverter_clips_at_cap() -> None:
    idx = _day_index()
    ghi = np.zeros(24)
    ghi[19] = 3000.0                     # absurd irradiance -> DC blows past inverter limit
    ac = solar_ac_mw_for_member(
        idx, ghi=ghi, temp_air=np.full(24, 25.0), wind_speed=np.full(24, 1.0), **COMMON
    )
    assert float(ac.max()) == pytest.approx(CLIP_CAP_MW, rel=1e-6)
