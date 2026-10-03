"""Deterministic rendering of computed results (D25): the computed answer, apart from the model's interpretation.

One renderer for normal answers and fallbacks, in Live and Replay. It reads the investigation's verified-result registry
(D24), never the legacy binding:
- **An admitted result** is rendered by its status: ``established`` states the maximum (every tied interval);
  ``not_established`` says no maximum is established and gives the highest value held as only that; ``unavailable``
  gives its reason. Its deterministic limitations and its source rows come with it.
- **A result the verifier did not admit** (``failed`` or ``unverifiable``) is ``not_verified``: no value at all, only
  why it is not given.

The wording is the controller's sentence (``demand_max.statement``), so the text is today's for an admitted result.
The report carries the rendered results in its ``answer`` field; the model's text never sets them, and the validator
checks their statements like every other narrative (``answer[i]``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .results import ReportedResult, ResultRegistry


class RenderedResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result_id: str
    kind: Literal["demand_maximum"]
    status: Literal["established", "not_established", "unavailable", "not_verified"]
    verification: Literal["verified", "failed", "unverifiable"] = Field(
        description="the runtime verifier's outcome in the run that produced the answer")
    statement: str
    limitations: tuple[str, ...] = Field((), description="deterministic limitations of the result")
    source_row_ids: tuple[str, ...] = Field((), description="source rows of the interval(s) stated")


def render_result(reported: ReportedResult, registry: ResultRegistry, region: str,
                  num: Callable[[str], str]) -> RenderedResult:
    """The rendered form of one computed result. ``num(evidence_id)`` formats a value and records its claim; it is
    called only for an admitted result's own in-run evidence."""
    from .agent import demand_max

    r = reported.result
    admitted = registry.verified(r.result_id)
    if admitted is None:  # not admitted: nothing of its content is stated
        outcome = reported.server_verification.outcome
        return RenderedResult(result_id=r.result_id, kind=r.identity.kind, status="not_verified",
                              verification="unverifiable" if outcome == "verified" else outcome,
                              statement=demand_max.statement_not_verified(r.identity, region, outcome))
    r = admitted.result
    return RenderedResult(result_id=r.result_id, kind=r.identity.kind, status=r.status, verification="verified",
                          statement=demand_max.statement(r, region, num),
                          limitations=tuple(x.text for x in r.limitations), source_row_ids=r.source_row_ids)
