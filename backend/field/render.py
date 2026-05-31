"""ResourceGrid -> smooth global equirectangular RGBA PNG on a FIXED absolute color scale.

This is the DISPLAYED resource field (raw physical metric, consistent everywhere), draped on
the Cesium globe as one translucent ImageryLayer — NOT the relative suitability score. The
climatology cells are scattered (oceans dropped), so we rasterise onto a regular global lattice,
nearest-fill the holes for clean bilinear upsampling, keep a soft alpha mask (so oceans/gaps
stay transparent and the earth shows through), apply the colormap, and encode a PNG.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from field import colormaps
from resources.types import ResourceGrid


@dataclass(frozen=True)
class FieldSpec:
    id: str        # "solar" | "wind"
    variable: str  # NASA POWER param, e.g. "ALLSKY_SFC_SW_DWN"
    label: str     # human label for the legend
    units: str     # physical units of the displayed metric
    vmin: float    # fixed absolute scale min (global climatology)
    vmax: float    # fixed absolute scale max
    cmap: str      # colormap name in field.colormaps

    def __post_init__(self) -> None:
        if not self.vmin < self.vmax:
            raise ValueError(f"FieldSpec {self.id!r}: require vmin < vmax (got {self.vmin}, {self.vmax})")


# Fixed absolute display ranges so the color scale is consistent everywhere, regardless of the
# region in view. (GHI ~2.5–8.5 kWh/m²/day spans desert→cloud; WS50M ~0–11 m/s spans calm→class.)
FIELD_SPECS: dict[str, FieldSpec] = {
    "solar": FieldSpec(
        "solar", "ALLSKY_SFC_SW_DWN", "Solar irradiance (GHI)", "kWh/m²/day", 2.5, 8.5, "solar"
    ),
    "wind": FieldSpec("wind", "WS50M", "Wind speed @ 50 m", "m/s", 0.0, 11.0, "wind"),
}


@dataclass(frozen=True)
class FieldMeta:
    id: str
    label: str
    units: str
    vmin: float
    vmax: float
    legend: list[str]  # hex color stops, low -> high

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "units": self.units,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "legend": self.legend,
        }


def field_meta(spec: FieldSpec) -> FieldMeta:
    return FieldMeta(
        spec.id, spec.label, spec.units, spec.vmin, spec.vmax, colormaps.legend_stops(spec.cmap)
    )


def _infer_base_res(grid: ResourceGrid, fallback: float = 1.0) -> float:
    """The grid's native cell spacing, inferred from the data. We rasterise onto a lattice at
    THIS resolution so every data point fills its own texel (no interleaved no-data holes that
    would make the alpha mask dotted). Use the coarser axis (POWER's lat 0.5° vs lon 0.625°),
    so neither axis leaves gaps. Clamped to a sane range."""
    lats = sorted({c.lat for c in grid.cells})
    lons = sorted({c.lon for c in grid.cells})

    def step(vals: list[float]) -> float | None:
        diffs = sorted(b - a for a, b in zip(vals, vals[1:]) if b - a > 1e-6)
        return diffs[len(diffs) // 2] if diffs else None  # median spacing (robust to gaps)

    cands = [s for s in (step(lats), step(lons)) if s is not None]
    return min(5.0, max(0.4, max(cands))) if cands else fallback


def _rasterize_global(grid: ResourceGrid, variable: str, base_res: float) -> np.ndarray:
    """Place scattered climatology cells onto a regular global lat/lon array (north-up),
    NaN where no cell falls. base_res in degrees."""
    n_lat = int(round(180.0 / base_res))
    n_lon = int(round(360.0 / base_res))
    arr = np.full((n_lat, n_lon), np.nan, dtype=np.float64)
    for cell in grid.cells:
        v = cell.values.get(variable)
        if v is None:
            continue
        # north (+90) at row 0; clamp the south pole (lat -90 -> row n_lat) into range.
        i = min(int(round((90.0 - cell.lat) / base_res)), n_lat - 1)
        # wrap longitude so lon +180 maps onto the -180 column (no antimeridian seam / dropped cell).
        j = int(round((cell.lon + 180.0) / base_res)) % n_lon
        if 0 <= i < n_lat:
            arr[i, j] = v
    return arr


def render_field_png(
    grid: ResourceGrid,
    spec: FieldSpec,
    out_w: int = 2160,
    out_h: int = 1080,
    base_res: float | None = None,
) -> bytes:
    """Render `grid`'s `spec.variable` as a smooth global equirectangular RGBA PNG (bytes)."""
    res = base_res if base_res is not None else _infer_base_res(grid)
    coarse = _rasterize_global(grid, spec.variable, res)  # (n_lat, n_lon), NaN holes
    valid = np.isfinite(coarse)
    if not valid.any():
        return _encode_png(np.zeros((out_h, out_w, 4), dtype=np.uint8))  # nothing -> transparent

    # Normalize against the FIXED absolute scale (clamped later by the colormap).
    norm = (coarse - spec.vmin) / (spec.vmax - spec.vmin)

    # Nearest-fill the NaN holes so bilinear upsampling doesn't smear them, while keeping a
    # separate alpha mask so oceans/gaps stay transparent (soft coastlines after upsampling).
    idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    filled = np.clip(np.nan_to_num(norm[tuple(idx)], nan=0.0), 0.0, 1.0)

    zoom_y, zoom_x = out_h / coarse.shape[0], out_w / coarse.shape[1]
    up = np.clip(ndimage.zoom(filled, (zoom_y, zoom_x), order=1), 0.0, 1.0)  # bilinear
    alpha = np.clip(
        ndimage.zoom(valid.astype(np.float64), (zoom_y, zoom_x), order=1), 0.0, 1.0
    )

    rgb = colormaps.apply(spec.cmap, up)  # (H, W, 3) uint8
    rgba = np.dstack([rgb, np.round(alpha * 255).astype(np.uint8)])
    return _encode_png(rgba)


def _encode_png(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
