"""Field-texture renderer tests — colormaps, PNG output, no-data transparency, meta.

The renderer is exercised on a synthetic ResourceGrid (no network / NASA POWER)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from field import colormaps
from field.render import FIELD_SPECS, field_meta, render_field_png
from resources.types import ResourceCell, ResourceGrid


# --- colormaps -------------------------------------------------------------------------


def test_sample_hits_endpoints_and_clamps() -> None:
    assert colormaps.sample("solar", 0.0) == (60, 0, 25)
    assert colormaps.sample("solar", 1.0) == (255, 248, 205)
    # out-of-range clamps to the ends (not an error)
    assert colormaps.sample("wind", -5.0) == colormaps.sample("wind", 0.0)
    assert colormaps.sample("wind", 9.0) == colormaps.sample("wind", 1.0)


def test_sample_is_monotonic_in_brightness() -> None:
    # luminance should rise from the dark low end to the pale high end
    lums = [sum(colormaps.sample("solar", t)) for t in np.linspace(0, 1, 11)]
    assert lums[0] < lums[-1]
    assert lums == sorted(lums)


def test_unknown_colormap_raises() -> None:
    with pytest.raises(KeyError):
        colormaps.sample("plasma", 0.5)


def test_apply_matches_sample_pointwise() -> None:
    arr = np.array([0.0, 0.5, 1.0])
    out = colormaps.apply("wind", arr)
    assert out.shape == (3, 3)
    assert tuple(int(x) for x in out[0]) == colormaps.sample("wind", 0.0)
    assert tuple(int(x) for x in out[2]) == colormaps.sample("wind", 1.0)


def test_legend_stops_are_hex() -> None:
    stops = colormaps.legend_stops("solar", n=9)
    assert len(stops) == 9
    assert all(s.startswith("#") and len(s) == 7 for s in stops)


# --- render_field_png ------------------------------------------------------------------


def _grid(cells: list[ResourceCell], variables: list[str], res: float = 2.0) -> ResourceGrid:
    return ResourceGrid(bbox=(-90, -180, 90, 180), resolution=res, variables=variables, cells=cells)


def _decode(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_render_returns_valid_png_of_requested_size() -> None:
    spec = FIELD_SPECS["wind"]
    # a small patch of real-ish wind cells near (0, 0)
    cells = [
        ResourceCell(lat=lat, lon=lon, values={spec.variable: 8.0})
        for lat in (-2.0, 0.0, 2.0)
        for lon in (-2.0, 0.0, 2.0)
    ]
    png = render_field_png(_grid(cells, [spec.variable]), spec, out_w=720, out_h=360)
    img = _decode(png)
    assert img.shape == (360, 720, 4)


def test_high_value_maps_hot_and_nodata_is_transparent() -> None:
    spec = FIELD_SPECS["wind"]  # vmin 0, vmax 11
    # a strong-wind patch around the equator/prime meridian
    cells = [
        ResourceCell(lat=lat, lon=lon, values={spec.variable: 11.0})
        for lat in (-2.0, 0.0, 2.0)
        for lon in (-2.0, 0.0, 2.0)
    ]
    png = render_field_png(_grid(cells, [spec.variable]), spec, out_w=360, out_h=180)
    img = _decode(png)

    # center of the equirectangular canvas (lat 0, lon 0) is inside the data patch -> opaque + pale (hot)
    cy, cx = 90, 180
    assert img[cy, cx, 3] == 255
    assert sum(int(c) for c in img[cy, cx, :3]) > 500  # near the pale high end of the ramp

    # a far corner (Antarctic / mid-Pacific) has no data -> fully transparent
    assert img[5, 5, 3] == 0


def test_empty_grid_renders_fully_transparent() -> None:
    spec = FIELD_SPECS["solar"]
    png = render_field_png(_grid([], [spec.variable]), spec, out_w=128, out_h=64)
    img = _decode(png)
    assert img.shape == (64, 128, 4)
    assert int(img[..., 3].max()) == 0


def test_field_meta_round_trips() -> None:
    meta = field_meta(FIELD_SPECS["solar"]).to_dict()
    assert meta["id"] == "solar"
    assert meta["units"] == "kWh/m²/day"
    assert meta["vmin"] == 2.5 and meta["vmax"] == 8.5
    assert isinstance(meta["legend"], list) and len(meta["legend"]) == 9
