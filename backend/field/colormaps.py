"""Multi-stop perceptual colormaps for the resource-field textures — no matplotlib dependency.

Two rich ramps, defined by explicit anchor stops and linearly interpolated:
- SOLAR : inferno-style  maroon -> red -> orange -> amber -> pale yellow  (irradiance)
- WIND  : viridis-style  indigo -> blue -> teal -> cyan -> pale            (wind speed)

A two-color ramp washes out the middle of the distribution; these multi-stop ramps keep the
whole range legible against a vivid earth.
"""

from __future__ import annotations

import numpy as np

RGB = tuple[int, int, int]
Anchor = tuple[float, RGB]

# (t in 0..1, (R, G, B) 0..255). Interpolated linearly between consecutive stops.
SOLAR_ANCHORS: list[Anchor] = [
    (0.0, (60, 0, 25)),       # deep maroon
    (0.25, (150, 25, 35)),    # red
    (0.5, (224, 95, 35)),     # orange
    (0.7, (248, 165, 45)),    # amber
    (0.88, (253, 215, 110)),  # pale amber
    (1.0, (255, 248, 205)),   # pale yellow
]

WIND_ANCHORS: list[Anchor] = [
    (0.0, (30, 15, 75)),      # indigo
    (0.3, (38, 75, 150)),     # blue
    (0.55, (26, 145, 145)),   # teal
    (0.78, (70, 205, 205)),   # cyan
    (1.0, (220, 248, 248)),   # pale
]

# Diverging temperature ramp (the classic weather-map read): deep blue (cold) -> pale (mild) -> deep red (hot).
TEMP_ANCHORS: list[Anchor] = [
    (0.0, (40, 50, 140)),     # deep blue (very cold)
    (0.25, (60, 140, 210)),   # blue
    (0.45, (180, 225, 235)),  # pale cyan
    (0.55, (245, 240, 205)),  # warm pale (mild)
    (0.72, (240, 170, 70)),   # orange
    (0.88, (220, 75, 50)),    # red
    (1.0, (150, 30, 40)),     # deep red (very hot)
]

COLORMAPS: dict[str, list[Anchor]] = {
    "solar": SOLAR_ANCHORS,
    "wind": WIND_ANCHORS,
    "temp": TEMP_ANCHORS,
}


def _anchors(name: str) -> list[Anchor]:
    try:
        return COLORMAPS[name]
    except KeyError as exc:
        raise KeyError(f"unknown colormap '{name}' (have {sorted(COLORMAPS)})") from exc


def sample(name: str, t: float) -> RGB:
    """RGB (0..255) at position t in 0..1 along the named colormap (clamped)."""
    anchors = _anchors(name)
    t = float(min(1.0, max(0.0, t)))
    for (t0, c0), (t1, c1) in zip(anchors, anchors[1:]):
        if t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return (
                int(round(c0[0] + (c1[0] - c0[0]) * f)),
                int(round(c0[1] + (c1[1] - c0[1]) * f)),
                int(round(c0[2] + (c1[2] - c0[2]) * f)),
            )
    return anchors[-1][1]


def apply(name: str, norm: np.ndarray) -> np.ndarray:
    """Map a float array in 0..1 -> uint8 RGB array (..., 3), vectorised per channel."""
    anchors = _anchors(name)
    ts = np.array([a[0] for a in anchors], dtype=np.float64)
    cs = np.array([a[1] for a in anchors], dtype=np.float64)  # (n, 3)
    clipped = np.clip(norm, 0.0, 1.0)
    out = np.empty((*clipped.shape, 3), dtype=np.float64)
    for ch in range(3):
        out[..., ch] = np.interp(clipped, ts, cs[:, ch])
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def legend_stops(name: str, n: int = 9) -> list[str]:
    """n hex color stops evenly spaced low->high, for a CSS gradient legend."""
    stops: list[str] = []
    for i in range(n):
        r, g, b = sample(name, i / (n - 1))
        stops.append(f"#{r:02x}{g:02x}{b:02x}")
    return stops
