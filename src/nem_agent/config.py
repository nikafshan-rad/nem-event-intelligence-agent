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
PROMPT_VERSION = "prompts/v15"      # directory under src/nem_agent/ read by the live controller

# Live-model prices in USD per 1M tokens (input, output), so budgets are always enforceable. Source: OpenAI API
# pricing page (developers.openai.com/api/docs/pricing), standard tier, read 2026-09-25 and re-checked 2026-09-28.
# Override with NEM_AGENT_PRICE_INPUT_PER_MTOK / _CACHED_INPUT_PER_MTOK / _OUTPUT_PER_MTOK; a model with no price is
# refused (fail closed).
MODEL_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {"gpt-5-mini": (0.25, 2.00)}
MODEL_CACHED_INPUT_PER_MTOK: dict[str, float] = {"gpt-5-mini": 0.025}
# Task-wide cap across every live run on this machine (nem_agent.budget); override with NEM_AGENT_TOTAL_BUDGET_USD.
LIVE_TOTAL_BUDGET_USD = 5.0
# Upper bound on output tokens (reasoning included) per model call, so each call has a known maximum cost.
MAX_OUTPUT_TOKENS: dict[str, int] = {"route": 2_000, "tools": 8_000, "synthesis": 16_000, "repair": 16_000}
