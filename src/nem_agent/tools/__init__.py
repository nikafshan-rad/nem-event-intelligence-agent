"""Bounded, typed, read-only tool registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import args as A
from . import impl


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[A.StrictArgs]
    handler: Callable[..., impl.ToolOutput]
    description: str


TOOLS: dict[str, ToolSpec] = {s.name: s for s in [
    ToolSpec("find_market_events", A.FindMarketEventsArgs, impl.find_market_events,
             "Find 5-minute intervals in a region/window whose dispatch price meets a project analysis threshold "
             "(high: RRP >= threshold; low: RRP < threshold). Returns grouped episodes with evidence ids."),
    ToolSpec("get_price_timeline", A.PriceTimelineArgs, impl.get_price_timeline,
             "5-minute regional dispatch price (RRP) and dispatch context (TOTALDEMAND, NETINTERCHANGE) for a bounded "
             "window (max 48 h). Optional as_of_utc hides intervals not yet public at that time."),
    ToolSpec("get_forecast_runs", A.ForecastRunsArgs, impl.get_forecast_runs,
             "AEMO-issued half-hourly operational demand forecast runs (POE50, plus AEMO's POE10/POE90) for target "
             "half-hours (max 24 h). With as_of_utc, only runs provably public by then are returned."),
    ToolSpec("get_actual_demand", A.ActualDemandArgs, impl.get_actual_demand,
             "Actual half-hourly operational demand with revision metadata (initial real-time vs next-day updated)."),
    ToolSpec("compare_forecast_actual", A.CompareArgs, impl.compare_forecast_actual,
             "Aligned POE50 forecast vs actual operational demand errors (MW and % of actual) computed by code. "
             "Refuses incompatible demand definitions."),
    ToolSpec("get_generation_change", A.GenerationChangeArgs, impl.get_generation_change,
             "Largest unit-level dispatch SCADA output changes in a region over a bounded window (max 12 h). "
             "Descriptive only; not an outage diagnosis."),
    ToolSpec("get_weather_context", A.WeatherArgs, impl.get_weather_context,
             "Retrospective hourly NASA POWER weather at one documented point for the region. Unavailable in as-of views."),
    ToolSpec("retrieve_public_evidence", A.RetrieveArgs, impl.retrieve_public_evidence,
             "Hybrid keyword + embedding search over public AEMO documents and market notices, filtered for "
             "region/date/publication eligibility before ranking. Returns quotable chunks with citation metadata."),
]}

TOOL_NAMES = tuple(TOOLS)


def openai_function_tools(names: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Function-tool definitions for the OpenAI Responses API (strict schemas)."""
    out = []
    for n in names or TOOL_NAMES:
        spec = TOOLS[n]
        out.append({"type": "function", "name": spec.name, "description": spec.description,
                    "parameters": A.strict_json_schema(spec.args_model), "strict": True})
    return out
