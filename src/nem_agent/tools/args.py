"""Typed tool arguments. Validation happens before any tool code runs; a failure blocks the call."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .. import config
from ..timeutil import parse_iso

Region = Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]


def _iso(v: str) -> str:
    parse_iso(v)  # raises ValueError without an explicit offset
    return v


IsoTs = Annotated[str, AfterValidator(_iso), Field(description="ISO-8601 timestamp with offset, e.g. 2026-07-30T16:35:00Z")]


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def ts(self, name: str) -> datetime | None:
        v = getattr(self, name)
        return parse_iso(v) if v else None


def _check_range(start: str, end: str, max_hours: float, label: str) -> None:
    a, b = parse_iso(start), parse_iso(end)
    if b <= a:
        raise ValueError(f"{label}: end must be after start")
    if b - a > timedelta(hours=max_hours):
        raise ValueError(f"{label}: range {(b - a).total_seconds() / 3600:.1f} h exceeds the {max_hours} h bound")


class FindMarketEventsArgs(StrictArgs):
    region: Region
    start_utc: IsoTs
    end_utc: IsoTs
    kind: Literal["high_price", "low_price"]
    threshold_aud_per_mwh: float | None = Field(None, description="defaults to the project analysis threshold")
    max_results: int = Field(5, ge=1, le=20)

    @model_validator(mode="after")
    def _r(self) -> FindMarketEventsArgs:
        _check_range(self.start_utc, self.end_utc, config.MAX_EVENT_SEARCH_DAYS * 24, "find_market_events")
        return self


class PriceTimelineArgs(StrictArgs):
    region: Region
    start_utc: IsoTs
    end_utc: IsoTs
    as_of_utc: IsoTs | None = None

    @model_validator(mode="after")
    def _r(self) -> PriceTimelineArgs:
        _check_range(self.start_utc, self.end_utc, config.MAX_PRICE_WINDOW_HOURS, "get_price_timeline")
        return self


class ForecastRunsArgs(StrictArgs):
    region: Region
    target_start_utc: IsoTs
    target_end_utc: IsoTs
    as_of_utc: IsoTs | None = None
    max_runs: int = Field(4, ge=1, le=config.MAX_FORECAST_RUNS_RETURNED)

    @model_validator(mode="after")
    def _r(self) -> ForecastRunsArgs:
        _check_range(self.target_start_utc, self.target_end_utc, config.MAX_FORECAST_TARGET_HOURS, "get_forecast_runs")
        return self


RevisionPolicy = Literal["initial", "updated", "latest_available"]


class ActualDemandArgs(StrictArgs):
    region: Region
    start_utc: IsoTs
    end_utc: IsoTs
    revision_policy: RevisionPolicy = "latest_available"
    as_of_utc: IsoTs | None = None

    @model_validator(mode="after")
    def _r(self) -> ActualDemandArgs:
        _check_range(self.start_utc, self.end_utc, config.MAX_ACTUAL_WINDOW_HOURS, "get_actual_demand")
        return self


class CompareArgs(StrictArgs):
    region: Region
    target_start_utc: IsoTs
    target_end_utc: IsoTs
    run_selector: Literal["latest_available_as_of", "latest_before_target", "min_lead_hours", "run_id"] = "latest_before_target"
    min_lead_hours: float | None = Field(None, ge=0, le=168)
    run_id: str | None = Field(None, max_length=120)
    as_of_utc: IsoTs | None = None
    actual_revision: RevisionPolicy = "latest_available"
    actual_metric: Literal["OPERATIONAL_DEMAND", "DISPATCH_TOTALDEMAND"] = "OPERATIONAL_DEMAND"

    @model_validator(mode="after")
    def _r(self) -> CompareArgs:
        _check_range(self.target_start_utc, self.target_end_utc, config.MAX_FORECAST_TARGET_HOURS, "compare_forecast_actual")
        if self.run_selector == "min_lead_hours" and self.min_lead_hours is None:
            raise ValueError("run_selector=min_lead_hours requires min_lead_hours")
        if self.run_selector == "run_id" and not self.run_id:
            raise ValueError("run_selector=run_id requires run_id")
        if self.run_selector == "latest_available_as_of" and not self.as_of_utc:
            raise ValueError("run_selector=latest_available_as_of requires as_of_utc")
        return self


class GenerationChangeArgs(StrictArgs):
    region: Region
    start_utc: IsoTs
    end_utc: IsoTs
    top_n: int = Field(5, ge=1, le=config.MAX_GENERATION_TOP_N)
    as_of_utc: IsoTs | None = None

    @model_validator(mode="after")
    def _r(self) -> GenerationChangeArgs:
        _check_range(self.start_utc, self.end_utc, config.MAX_GENERATION_WINDOW_HOURS, "get_generation_change")
        return self


class WeatherArgs(StrictArgs):
    region: Region
    start_utc: IsoTs
    end_utc: IsoTs
    as_of_utc: IsoTs | None = None

    @model_validator(mode="after")
    def _r(self) -> WeatherArgs:
        _check_range(self.start_utc, self.end_utc, config.MAX_WEATHER_WINDOW_HOURS, "get_weather_context")
        return self


class RetrieveArgs(StrictArgs):
    query: str = Field(min_length=3, max_length=300)
    region: Region | None = None
    event_start_utc: IsoTs | None = None
    event_end_utc: IsoTs | None = None
    as_of_utc: IsoTs | None = None
    top_k: int = Field(5, ge=1, le=config.MAX_RETRIEVAL_TOP_K)
    doc_types: list[Literal["definition", "procedure", "market_notice"]] | None = None

    @model_validator(mode="after")
    def _r(self) -> RetrieveArgs:
        if bool(self.event_start_utc) != bool(self.event_end_utc):
            raise ValueError("event_start_utc and event_end_utc must be given together")
        if self.event_start_utc and self.event_end_utc:
            _check_range(self.event_start_utc, self.event_end_utc, 24 * 7, "retrieve_public_evidence")
        return self


# Constraint keywords are enforced server-side by pydantic; they are stripped from the model-facing schema
# because strict function-calling implementations support only a subset of JSON Schema.
_STRIP = {"default", "title", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
          "exclusiveMaximum", "pattern", "minItems", "maxItems", "format"}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for OpenAI strict function calling: every property required (nullable when optional),
    ``additionalProperties: false``, no defaults."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return fix(defs[node["$ref"].split("/")[-1]])
            node = {k: fix(v) for k, v in node.items() if k not in _STRIP}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node

    return fix(schema)
