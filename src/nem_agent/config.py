"""Bounds and policy constants. Changing one is a documented decision (docs/decisions.md)."""

from __future__ import annotations

MAX_PRICE_WINDOW_HOURS = 48
MAX_EVENT_SEARCH_DAYS = 7
MAX_FORECAST_TARGET_HOURS = 24
MAX_FORECAST_RUNS_RETURNED = 8
MAX_ACTUAL_WINDOW_HOURS = 48
MAX_GENERATION_WINDOW_HOURS = 12
MAX_GENERATION_TOP_N = 10
MAX_WEATHER_WINDOW_HOURS = 48
MAX_RETRIEVAL_TOP_K = 8
MAX_RETRIEVED_CHARS = 12_000        # total characters of retrieved text passed on per question
MAX_OPTIONAL_DIAGNOSTICS = 2        # optional tool calls allowed on top of the intent playbook
MAX_MODEL_CALLS = 8                 # live path: model round trips per question
MAX_REPAIR_ATTEMPTS = 1
PROMPT_VERSION = "prompts/v1"
