"""GENERIC "why this site" AI briefing for the site-selection product.

One Anthropic structured-output call (claude-sonnet-4-6 by default). The model is GIVEN
the computed numbers (ranked sites + metrics) and explains WHY the top region scores well
— it NEVER invents or alters a number, and ALWAYS carries the "climatology, not bankable
yield" caveat. Parameterized by the vertical's briefing_role.

Degrades gracefully: with no ANTHROPIC_API_KEY (or any API failure) it raises
BriefingUnavailable, and the route returns briefing=None — the suitability result is the
core product; the briefing is additive.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

DEFAULT_BRIEFING_MODEL = "claude-sonnet-4-6"


class SiteBriefing(BaseModel):
    headline: str
    why_top_sites: str
    top_drivers: list[str]
    caveats: list[str]
    confidence: Literal["low", "medium", "high"]


class BriefingUnavailable(RuntimeError):
    """No ANTHROPIC_API_KEY configured, or the briefing service failed."""


_SYSTEM = """You are a {briefing_role} for Borealis, a renewable SITE-SELECTION platform. \
You are GIVEN precomputed suitability numbers for candidate sites in a region. Explain, in \
plain language, WHY the top-ranked area scores well for this lens and what a developer or \
investor should know before committing capital.

HARD RULES:
- NEVER invent, alter, or recompute any number. Cite only values you are given.
- These are long-term CLIMATOLOGY means (NASA POWER, ~20 years) and a RELATIVE ranking \
WITHIN the queried region — NOT bankable energy yield and NOT extreme-event skill. Say so plainly.
- top_drivers: the few weather/resource factors driving the score (e.g. high irradiance, \
strong coastal wind).
- caveats: MUST include that this is climatology, not bankable yield, and that scores are \
relative to the region. Recommend ONE concrete next step (e.g. an on-site measurement \
campaign / bankable assessment).
- Be concise and concrete; pick a confidence level honestly from how clustered/extreme the \
numbers are."""


def _payload(
    region_label: str, lens: str, metric_units: str, ranked_sites: list[dict[str, Any]]
) -> str:
    lines = [
        f"Region: {region_label}",
        f"Lens: {lens}",
        f"Suitability metric units: {metric_units}",
        f"Top {len(ranked_sites)} candidate sites (relative score 0..1 + physical metrics):",
    ]
    for site in ranked_sites:
        lat = site.get("lat")
        lon = site.get("lng", site.get("lon"))
        metrics = ", ".join(f"{k}={v:.3g}" for k, v in (site.get("metrics") or {}).items())
        lines.append(f"  #{site['rank']} ({lat:.2f}, {lon:.2f}) score={site['score']:.3f} | {metrics}")
    lines.append("Explain why the top area scores well in this lens and recommend a next step.")
    return "\n".join(lines)


async def generate_site_briefing(
    *,
    region_label: str,
    lens: str,
    metric_units: str,
    ranked_sites: list[dict[str, Any]],
    briefing_role: str,
    model: str = DEFAULT_BRIEFING_MODEL,
    api_key: str | None = None,
) -> SiteBriefing:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BriefingUnavailable("ANTHROPIC_API_KEY not configured")

    system = [
        {
            "type": "text",
            "text": _SYSTEM.format(briefing_role=briefing_role),
            "cache_control": {"type": "ephemeral"},  # stable per vertical -> cache-friendly
        }
    ]
    user = _payload(region_label, lens, metric_units, ranked_sites)

    try:
        async with anthropic.AsyncAnthropic(api_key=key) as client:
            resp = await client.messages.parse(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=SiteBriefing,
            )
    except anthropic.APIError as exc:
        raise BriefingUnavailable(f"Anthropic API error: {exc}") from exc

    if resp.parsed_output is None:
        raise BriefingUnavailable("model returned no structured output")
    return resp.parsed_output


# --- "ask the globe": natural-language -> a region + lens ------------------------------


class GlobeQuery(BaseModel):
    label: str                       # human region label, e.g. "Andalucía, Spain"
    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float
    lens: Literal["solar", "wind"]


_QUERY_SYSTEM = """You translate a natural-language renewable-siting question into a query \
for a site-selection globe. Given a question like "best solar sites in Spain" or "where \
should I build wind near Texas", return: a human `label` for the region, a BOUNDING BOX \
(lat_min/lon_min/lat_max/lon_max in decimal degrees WGS84) covering the relevant area, and \
the `lens` ('solar' or 'wind').

CONSTRAINTS:
- The bounding box must be at most ~10° per axis and at least ~2° per axis. If the named \
place is larger (e.g. a country), zoom to its most relevant core sub-region.
- Require lat_min<lat_max and lon_min<lon_max. West longitudes are negative.
- If no lens is stated, infer it from the question; default to 'solar'."""


async def parse_globe_query(
    *,
    query: str,
    model: str = DEFAULT_BRIEFING_MODEL,
    api_key: str | None = None,
) -> GlobeQuery:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BriefingUnavailable("ANTHROPIC_API_KEY not configured")
    system = [{"type": "text", "text": _QUERY_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    try:
        async with anthropic.AsyncAnthropic(api_key=key) as client:
            resp = await client.messages.parse(
                model=model,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": query}],
                output_format=GlobeQuery,
            )
    except anthropic.APIError as exc:
        raise BriefingUnavailable(f"Anthropic API error: {exc}") from exc
    if resp.parsed_output is None:
        raise BriefingUnavailable("model returned no structured output")
    return resp.parsed_output
