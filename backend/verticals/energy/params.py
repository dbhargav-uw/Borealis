"""Validated, typed params for energy assets. asset.params is a free dict at the
contract boundary; the EnergyModel parses it into one of these per `kind`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class SolarParams(BaseModel):
    kind: Literal["solar"] = "solar"
    dc_capacity_kw: float = Field(..., gt=0)               # DC nameplate -> pdc0 = *1000 W
    ac_dc_ratio: float = Field(1.2, gt=1.0, le=2.0)        # ILR; inverter pdc0 = array/ratio
    surface_tilt: float = Field(25.0, ge=0, le=90)
    surface_azimuth: float = Field(180.0, ge=0, le=360)    # 180=S (N hemi)
    gamma_pdc: float = Field(-0.004, le=0)                 # power temp coeff, 1/°C
    system_loss: float = Field(0.14, ge=0, lt=1)           # lumped DC losses
    eta_inv_nom: float = Field(0.96, gt=0, le=1)
    albedo: float = Field(0.25, ge=0, le=1)
    sky_model: str = "isotropic"
    temperature_model: str = "faiman"


class WindParams(BaseModel):
    kind: Literal["wind"] = "wind"
    rated_power_kw: float = Field(3000.0, gt=0)            # per-turbine rated AC power
    n_turbines: int = Field(1, ge=1)
    cut_in_ms: float = Field(3.0, ge=0)
    rated_ms: float = Field(12.0, gt=0)
    cut_out_ms: float = Field(25.0, gt=0)
    availability: float = Field(1.0, gt=0, le=1)           # wake/downtime de-rate seam
    hub_height_m: float = Field(100.0, gt=0)               # inert unless 10m->hub fallback
    shear_alpha: float = Field(0.143, gt=0, lt=1)

    @model_validator(mode="after")
    def _ordered_curve(self) -> "WindParams":
        if not (self.cut_in_ms < self.rated_ms < self.cut_out_ms):
            raise ValueError("require cut_in_ms < rated_ms < cut_out_ms")
        return self


EnergyParams = SolarParams | WindParams


def parse_energy_params(params: dict) -> EnergyParams:
    """Dispatch on params['kind'] -> validated model. Raises ValueError (not pydantic's
    ValidationError) so the route maps every param problem to a 422."""
    kind = params.get("kind")
    model_cls: type[SolarParams] | type[WindParams] | None = {
        "solar": SolarParams,
        "wind": WindParams,
    }.get(kind)
    if model_cls is None:
        raise ValueError(
            f"energy asset requires params.kind in {{'solar','wind'}}, got {kind!r}"
        )
    try:
        return model_cls(**params)
    except ValidationError as exc:
        raise ValueError(f"invalid energy {kind} params: {exc}") from exc
