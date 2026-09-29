"""Closed intents and their deterministic tool playbooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Intent = Literal["market_event_review", "forecast_review", "source_explanation"]
INTENTS: tuple[Intent, ...] = ("market_event_review", "forecast_review", "source_explanation")


@dataclass(frozen=True)
class Playbook:
    intent: Intent
    required: tuple[str, ...]
    optional: tuple[str, ...]
    max_calls_per_required_tool: int = 3
    # tools the controller alone may call, once per investigation; never offered to the model
    controller_only: tuple[str, ...] = ()


PLAYBOOKS: dict[str, Playbook] = {
    "market_event_review": Playbook(
        "market_event_review",
        required=("find_market_events", "get_price_timeline", "get_actual_demand", "retrieve_public_evidence"),
        optional=("get_generation_change", "get_weather_context", "get_forecast_runs", "compare_forecast_actual"),
        controller_only=("get_regional_prices",),  # other regions at the price extreme, when the question is about them
    ),
    "forecast_review": Playbook(
        "forecast_review",
        required=("get_forecast_runs", "get_actual_demand", "compare_forecast_actual", "retrieve_public_evidence"),
        optional=("get_price_timeline", "get_weather_context", "find_market_events"),
    ),
    "source_explanation": Playbook(
        "source_explanation",
        required=("retrieve_public_evidence",),
        optional=("get_price_timeline", "find_market_events"),
        # notices are searched one region per call: room for all five NEM regions plus one general search, so a
        # question about "other regions" can be searched completely (L3 live, ADV02). Model calls stay capped at 8.
        max_calls_per_required_tool=6,
    ),
}
