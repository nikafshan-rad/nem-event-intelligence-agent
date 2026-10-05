"""Task-wide spending cap for hosted-model calls, shared by every process on this machine (CLI, evaluation, UI).

Each model call first **reserves** its worst-case cost (a generous estimate of the input tokens plus that stage's
``max_output_tokens``, all at list price) in an append-only ledger under an exclusive file lock. The call is refused
when the amount already spent or reserved plus that reservation would exceed the cap. After the call the reservation is
**settled** at the actual cost from the reported usage (cached input at the cached rate). A reservation that is never
settled (a crash) stays counted, so the ledger over-counts rather than under-counts. A request whose outcome is
unknown (a timeout or a connection error after it was sent) is settled at its worst case, because the provider may
still have processed and billed it. A **charge** records such a cost for an attempt the ledger never reserved.

Cap: ``NEM_AGENT_TOTAL_BUDGET_USD`` (default ``config.LIVE_TOTAL_BUDGET_USD``). Ledger: ``NEM_AGENT_BUDGET_LEDGER``
(default ``artifacts/live_budget/ledger.jsonl``, git-ignored). No key or prompt text is written to the ledger.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import config, paths


class BudgetExceeded(RuntimeError):
    """A model call, or (at the preflight) a whole Live investigation, that a cap does not allow. ``stage``: the
    model-call stage refused, or ``preflight`` before any call (set by the live controller, D34)."""

    stage: str | None = None


def ledger_path() -> Path:
    p = os.environ.get("NEM_AGENT_BUDGET_LEDGER")
    return Path(p) if p else paths.artifacts_dir() / "live_budget" / "ledger.jsonl"


def total_budget() -> float:
    return float(os.environ.get("NEM_AGENT_TOTAL_BUDGET_USD", config.LIVE_TOTAL_BUDGET_USD))


def prices(model: str) -> tuple[float, float, float] | None:
    """USD per 1M tokens (input, cached input, output): environment override, else the dated config table."""
    pin, pout = os.environ.get("NEM_AGENT_PRICE_INPUT_PER_MTOK"), os.environ.get("NEM_AGENT_PRICE_OUTPUT_PER_MTOK")
    if pin and pout:
        return float(pin), float(os.environ.get("NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK", pin)), float(pout)
    p = config.MODEL_PRICES_PER_MTOK.get(model)
    return None if p is None else (p[0], config.MODEL_CACHED_INPUT_PER_MTOK.get(model, p[0]), p[1])


def call_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    """List-price cost of one response from its reported usage (cached input at the cached rate)."""
    p = prices(model)
    if p is None:
        return None
    u = usage or {}
    tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
    cached = int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    return round(((tin - cached) * p[0] + cached * p[1] + tout * p[2]) / 1e6, 6)


def worst_case_cost(model: str, request_chars: int, max_output_tokens: int) -> float:
    p = prices(model)
    if p is None:
        raise BudgetExceeded(f"no price known for model {model!r}; the budget cannot be enforced")
    # about 4 characters per token for English/JSON; count one token per 2 characters to stay on the safe side
    return round((request_chars / 2 * p[0] + max_output_tokens * p[2]) / 1e6, 6)


@contextmanager
def _locked() -> Iterator[Any]:
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield fh
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def preflight(required_usd: float) -> tuple[float, float]:
    """Whether work whose bounded worst case is ``required_usd`` fits under the task-wide cap now, with everything
    already spent or reserved counted: (committed, cap), or refused (BudgetExceeded). It reserves nothing: each call is
    still reserved and settled on its own (``reserve``, ``settle``), so nothing is counted twice (D34)."""
    cap = total_budget()
    with _locked() as fh:
        committed = _committed(fh)
    if committed + required_usd > cap:
        raise BudgetExceeded(f"task budget {cap:.2f} USD: {committed:.4f} spent or reserved, and this investigation's "
                             f"bounded worst case is {required_usd:.4f}, so it is not started")
    return committed, cap


def _committed(fh: Any) -> float:
    fh.seek(0)
    reserved: dict[str, float] = {}
    settled: dict[str, float] = {}
    charged = 0.0
    for ln in fh.read().splitlines():
        if not ln.strip():
            continue
        e = json.loads(ln)
        if e["kind"] == "charge":
            charged += float(e["usd"])
        else:
            (settled if e["kind"] == "settle" else reserved)[e["id"]] = float(e["usd"])
    return sum(settled.values()) + sum(v for k, v in reserved.items() if k not in settled) + charged


def spent() -> float:
    with _locked() as fh:
        return round(_committed(fh), 6)


def reserve(model: str, stage: str, worst_case_usd: float) -> str:
    cap = total_budget()
    with _locked() as fh:
        committed = _committed(fh)
        if committed + worst_case_usd > cap:
            raise BudgetExceeded(f"task budget {cap:.2f} USD: {committed:.4f} spent or reserved, this call could cost "
                                 f"up to {worst_case_usd:.4f}")
        rid = uuid.uuid4().hex
        fh.write(json.dumps({"id": rid, "kind": "reserve", "usd": worst_case_usd, "model": model, "stage": stage,
                             "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rid


def settle(rid: str, actual_usd: float, usage: dict[str, Any] | None = None) -> None:
    u = usage or {}
    with _locked() as fh:
        fh.write(json.dumps({"id": rid, "kind": "settle", "usd": actual_usd,
                             "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                             "cached_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens"),
                             "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def charge(model: str, stage: str, usd: float, note: str) -> None:
    """Record a possible cost the ledger never reserved (e.g. a hidden SDK retry), at its worst case."""
    with _locked() as fh:
        fh.write(json.dumps({"id": uuid.uuid4().hex, "kind": "charge", "usd": usd, "model": model, "stage": stage,
                             "note": note, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
