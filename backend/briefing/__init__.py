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


# --- "place a building": natural-language -> a geocodable place + building + intent --------


class BuildingQuery(BaseModel):
    label: str                                  # short human label, e.g. "Coastal hospital, Miami"
    place_name: str                             # a GEOCODABLE place string, e.g. "Miami, Florida, USA"
    building_type: str                          # e.g. hospital | house | tower | school | warehouse | farm
    intent: Literal["site-selection", "flood", "tornado", "general"]
    # Richer SPEC (all optional) — drives glTF model SELECTION + SIZING on the globe. Nullable so the
    # parse stays robust; the frontend model loader falls back to per-type defaults when a field is null.
    approx_floors: int | None = None            # storeys, if implied/stated
    height_m: float | None = None               # approximate total height in metres, if implied/stated
    footprint_m: float | None = None            # approximate footprint width in metres (square-ish)
    style: str | None = None                    # architectural style / era, e.g. "modern glass", "1900s brick"
    roof_type: str | None = None                # e.g. "flat", "pitched", "domed"
    features: list[str] = []                    # notable features, e.g. ["helipad", "glass facade"]


_PLACE_SYSTEM = """You turn a natural-language request to place a building into a structured query for a 3D \
globe that renders a representative detailed model of the building at the geocoded site. Given something like \
"a coastal hospital in Miami" or "a 40-storey glass office tower in Dubai" or "my house in Tulsa during a \
tornado", return:
- `label`: a short human label for the building (e.g. "Coastal hospital, Miami").
- `place_name`: a clean, GEOCODABLE place string (city + region + country where possible), e.g. \
"Miami, Florida, USA". Do NOT include the building type in place_name.
- `building_type`: one lowercase word/phrase for the structure (hospital, house, office tower, residential \
tower, school, warehouse, factory, data center, stadium, farm, …). Default to "building" if unclear.
- `intent`: the user's concern — 'flood' (coastal/sea-level/inundation), 'tornado' (tornado/twister), \
'site-selection' (where to build a solar/wind/renewable project), or 'general'. Infer from wording; default 'general'.
- SPEC fields to drive model selection + realistic sizing — fill what is stated OR reasonably implied by the \
building type, else leave null:
  - `approx_floors`: storeys (e.g. a "skyscraper" ~50, a "house" ~2, a "hospital" ~8).
  - `height_m`: approximate total height in metres (≈ floors × 3.3 if only floors are known).
  - `footprint_m`: approximate footprint width in metres (a house ~12, a hospital ~60, a stadium ~180).
  - `style`: architectural style / era if implied (e.g. "modern glass curtain-wall", "mid-century brick").
  - `roof_type`: "flat" | "pitched" | "domed" | … if implied.
  - `features`: short notable features (e.g. ["helipad", "glass facade", "solar roof"]). Empty list if none.
Be realistic and conservative; never invent precise numbers the request doesn't support — prefer null."""


async def parse_building_query(
    *,
    query: str,
    model: str = DEFAULT_BRIEFING_MODEL,
    api_key: str | None = None,
) -> BuildingQuery:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BriefingUnavailable("ANTHROPIC_API_KEY not configured")
    system = [{"type": "text", "text": _PLACE_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    try:
        async with anthropic.AsyncAnthropic(api_key=key) as client:
            resp = await client.messages.parse(
                model=model,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": query}],
                output_format=BuildingQuery,
            )
    except anthropic.APIError as exc:
        raise BriefingUnavailable(f"Anthropic API error: {exc}") from exc
    if resp.parsed_output is None:
        raise BriefingUnavailable("model returned no structured output")
    return resp.parsed_output


# --- per-location risk-analysis synthesis: illustrative insurance considerations + summary --
# Composes the dossier's already-computed resource + hazard NUMBERS into (a) educational
# insurance considerations and (b) a short synthesis. STRICTLY grounded in the values given;
# invents no numbers; insurance is illustrative/educational, NOT advice. Degrades to None.


class InsuranceConsideration(BaseModel):
    kind: str            # short tag, e.g. "Flood", "Windstorm", "Parametric"
    consideration: str   # one illustrative, educational line
    rationale: str       # which computed hazard number(s) motivate it


class AnalysisBriefing(BaseModel):
    insurance: list[InsuranceConsideration]
    summary: str         # ties resource opportunity + hazard risk + insurance together


_ANALYSIS_SYSTEM = """You are a risk-analysis explainer for Borealis. You are GIVEN precomputed \
resource and hazard numbers for a single placed building, and you produce (1) a few ILLUSTRATIVE, \
EDUCATIONAL insurance CONSIDERATIONS and (2) a short SUMMARY tying resource opportunity and hazard \
exposure together — for a non-expert exploring a map.

HARD RULES (critical — this is a demo, not a financial product):
- NEVER invent, alter, or recompute any number. Cite ONLY values you are given. If a section was \
unavailable, say so plainly rather than guessing.
- The renewable-resource scores are long-term CLIMATOLOGY and a RELATIVE comparator within a small \
region — NOT bankable energy yield. The flood/tornado figures are ILLUSTRATIVE, grounded in real \
elevation (Cesium World Terrain) and NOAA SPC climatology — NOT predictions.
- INSURANCE: each item is an ILLUSTRATIVE, EDUCATIONAL consideration derived from the computed hazard \
profile (e.g. "flood coverage is commonly considered for low-lying coastal sites", windstorm/parametric \
options). It is NOT insurance advice, NOT a quote, NOT a recommendation to buy or decline anything. Tie \
each `rationale` to a specific computed hazard signal. Give 2-4 items; if all hazards are negligible, say \
that and return fewer (or an item noting standard coverage considerations only).
- SUMMARY: 2-4 sentences. Connect the resource read and the hazard exposure; end by reminding the reader \
these are illustrative/educational, not advice or a forecast. Pick nothing the numbers don't support.
- Be concise and concrete."""


def _analysis_payload(
    location: dict[str, Any], resource: dict[str, Any], hazards: dict[str, Any]
) -> str:
    import json

    return (
        "LOCATION:\n" + json.dumps(location, default=str) + "\n\n"
        "RENEWABLE RESOURCE (relative comparator, not bankable yield):\n"
        + json.dumps(resource, default=str) + "\n\n"
        "HAZARD EXPOSURE (illustrative; grounded in elevation + NOAA SPC + live feeds):\n"
        + json.dumps(hazards, default=str) + "\n\n"
        "Produce illustrative/educational insurance considerations grounded in these hazard signals, "
        "and a short summary. Invent no numbers."
    )


async def generate_analysis_briefing(
    *,
    location: dict[str, Any],
    resource: dict[str, Any],
    hazards: dict[str, Any],
    model: str = DEFAULT_BRIEFING_MODEL,
    api_key: str | None = None,
) -> AnalysisBriefing:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BriefingUnavailable("ANTHROPIC_API_KEY not configured")
    system = [{"type": "text", "text": _ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    user = _analysis_payload(location, resource, hazards)
    try:
        async with anthropic.AsyncAnthropic(api_key=key) as client:
            resp = await client.messages.parse(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=AnalysisBriefing,
            )
    except anthropic.APIError as exc:
        raise BriefingUnavailable(f"Anthropic API error: {exc}") from exc
    if resp.parsed_output is None:
        raise BriefingUnavailable("model returned no structured output")
    return resp.parsed_output


# --- hazard-exposure explanation for a simulated flood/tornado at a placed building --------


class HazardBriefing(BaseModel):
    headline: str
    exposure: str            # plain-language explanation of the building's exposure to this scenario
    caveats: list[str]
    confidence: Literal["low", "medium", "high"]


_HAZARD_SYSTEM = """You explain a building's exposure to an ILLUSTRATIVE hazard scenario shown on a 3D \
globe, for a non-expert. You are GIVEN the scenario numbers — explain what they imply for this building.

HARD RULES (critical):
- This is an ILLUSTRATIVE visualization, NOT a physics/meteorological simulation or a forecast. The \
magnitude/likelihood are grounded in real data (Cesium World Terrain elevation for floods; NOAA SPC \
tornado climatology for tornadoes), but the rendered event is illustrative. Say this plainly.
- NEVER invent or alter a number; cite only the values you are given.
- For FLOOD: it is a "bathtub" inundation (water at a fixed level over real terrain) — extent is realistic \
because it follows elevation, but it ignores flow, drainage, and defenses. For TORNADO: likelihood + EF come \
from long-term regional climatology, NOT a prediction for any specific day.
- caveats MUST include the illustrative-not-predictive point and name the data source.
- Be concise (2-4 sentences of `exposure`); pick confidence honestly."""


async def generate_hazard_briefing(
    *,
    kind: Literal["flood", "tornado"],
    building_label: str,
    place_name: str,
    scenario: dict[str, Any],
    model: str = DEFAULT_BRIEFING_MODEL,
    api_key: str | None = None,
) -> HazardBriefing:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise BriefingUnavailable("ANTHROPIC_API_KEY not configured")
    details = "\n".join(f"  {k}: {v}" for k, v in scenario.items())
    user = (
        f"Hazard: {kind}\nBuilding: {building_label}\nLocation: {place_name}\nScenario numbers:\n{details}\n"
        f"Explain this building's exposure to the {kind} scenario above."
    )
    system = [{"type": "text", "text": _HAZARD_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    try:
        async with anthropic.AsyncAnthropic(api_key=key) as client:
            resp = await client.messages.parse(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=HazardBriefing,
            )
    except anthropic.APIError as exc:
        raise BriefingUnavailable(f"Anthropic API error: {exc}") from exc
    if resp.parsed_output is None:
        raise BriefingUnavailable("model returned no structured output")
    return resp.parsed_output
