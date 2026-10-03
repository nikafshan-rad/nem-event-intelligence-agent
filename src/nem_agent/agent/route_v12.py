"""The routing contract of prompts v12, unchanged (the historical adapter, D26).

The classes keep their v12 names, so their JSON schema is byte-identical to the one sent under v12: the frozen checks
that measured it are reproduced exactly. Decisions recorded under v12 are parsed with these and read through
``structured.requested_from_v12``; their timestamps are not read for values. Model-facing schemas carry no
docstring, which would enter the schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutedForecastRun(_M):
    selection: Literal["none", "last_issued_before", "issued_at", "as_of_availability", "unclear"] = Field(
        description="the one forecast run the question asks for: last_issued_before = the last run issued before the "
                    "target half-hour starts; issued_at = the run issued at a stated time; as_of_availability = what "
                    "was public or known at a cutoff; none = no specific run is asked for; unclear = one specific run "
                    "is asked for, but which cannot be told")
    selection_text: str | None = Field(description="the question's exact words asking for this run, copied verbatim")
    half_hour_text: str | None = Field(
        description="the question's exact words naming the target half-hour, copied verbatim (with its clock times, "
                    "and its date and time zone where they are written next to it)")
    target_half_hour_end_utc: str | None = Field(description="the target half-hour's END, ISO-8601 UTC ending in Z")
    issued_at_utc: str | None = Field(description="issued_at only: the stated issue time, ISO-8601 UTC ending in Z")


class RoutedMaximum(_M):
    kind: Literal["none", "maximum", "unclear"] = Field(
        description="maximum = the question asks when, or at what level, a demand measure reached its maximum over a "
                    "window; none = it does not (demand AT the price peak or in a named interval, the peak price); "
                    "unclear = a demand peak is asked for, but what is meant cannot be told")
    measure: Literal["dispatch_total_demand", "operational_demand", "unspecified"] | None = Field(
        description="dispatch total demand (TOTALDEMAND, 5-minute) or operational demand (half-hourly)")
    measure_text: str | None = Field(
        description="the question's exact words asking for the measure's maximum, copied verbatim (measure and peak "
                    "word)")
    window: Literal["whole_local_day", "event", "explicit", "unspecified"] | None = Field(
        description="whole_local_day = one whole local calendar day; event = a price event's window; explicit = a "
                    "start and an end")
    window_text: str | None = Field(description="the question's exact words naming the window, copied verbatim")
    window_start_utc: str | None = Field(description="explicit only: the window start, ISO-8601 UTC ending in Z")
    window_end_utc: str | None = Field(description="explicit only: the window end, ISO-8601 UTC ending in Z")


class RoutedRequest(_M):
    forecast_run: RoutedForecastRun
    maximum: RoutedMaximum


class RouteDecision(_M):
    intent: Literal["market_event_review", "forecast_review", "source_explanation"] | None
    region: Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"] | None
    event_date: str | None = Field(description="YYYY-MM-DD in the region's local time")
    as_of_utc: str | None
    needs_clarification: bool
    clarification_reason: Literal["several_regions", "several_dates", "missing_region_or_date",
                                  "unclear_question"] | None = Field(
        description="why clarification is needed; null when needs_clarification is false")
    clarification: str | None
    out_of_scope: bool
    # the forecast run and demand maximum the question asks for, with the question's own words for each (I-18);
    # absent in routes recorded before prompts v12: "not reported", never "no requirement"
    requested: RoutedRequest | None = None
