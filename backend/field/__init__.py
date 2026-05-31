"""Resource-field texture layer: turns a climatology ResourceGrid into a smooth, global
equirectangular RGBA texture on a FIXED absolute color scale (the DISPLAYED field), plus the
legend metadata. Distinct from the relative suitability score — same NASA POWER input, two
expressions: the raw physical metric (consistent everywhere, this module) and the
region-relative score (scoring/)."""

from __future__ import annotations

from .render import (
    FIELD_SPECS,
    FieldMeta,
    FieldSpec,
    field_meta,
    render_field_png,
)

__all__ = [
    "FIELD_SPECS",
    "FieldMeta",
    "FieldSpec",
    "field_meta",
    "render_field_png",
]
