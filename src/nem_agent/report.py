"""`InvestigationReport` — the structured, validated output of every investigation (replay or live)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["answered", "answered_with_caveats", "needs_clarification", "abstained", "refused"]
Mode = Literal["replay", "live"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventWindow(_M):
    start_utc: str
    end_utc: str
    start_local: str
    end_local: str
    timezone: str


class Observation(_M):
    metric: str
    value: float
    unit: str
    valid_at_utc: str
    valid_at_local: str | None = None
    interval_minutes: int | None = None
    evidence_id: str
    source_row_ids: list[str] = Field(min_length=1)
    evidence_class: Literal["observed", "aemo_forecast", "derived", "retrospective_context"]
    label: str


class ForecastComparison(_M):
    status: Literal["ok", "unavailable", "refused"]
    run_selector: str | None = None
    as_of_utc: str | None = None
    definition_check: str
    n_pairs: int = 0
    mae_mw: float | None = None
    mae_evidence_id: str | None = None
    mean_error_mw: float | None = None
    mean_error_evidence_id: str | None = None
    largest_abs_error: dict[str, Any] | None = None
    note: str


class Hypothesis(_M):
    statement: str
    certainty: Literal["hypothesis"] = "hypothesis"
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    what_would_test_it: str


class PublishedFinding(_M):
    statement: str
    citation_ids: list[str] = Field(min_length=1)
    doc_type: Literal["market_notice", "event_report", "definition", "procedure"]
    applies_to_event: bool


class Citation(_M):
    citation_id: str
    chunk_id: str
    doc_id: str
    title: str
    url: str
    section: str | None = None
    page: int | None = None
    publication_date: str | None = None
    doc_type: str
    quote: str = Field(max_length=600, description="verbatim excerpt; the validator rejects quotes under 10 characters")
    supports: str = Field(description="the claim this quotation supports")


class NumericClaim(_M):
    claim_id: str
    text: str
    value: float
    unit: str
    evidence_id: str
    rounding: float = Field(0.5, description="absolute tolerance in `unit` between claimed and evidence value")


class Versions(_M):
    code: str
    data: str | None
    corpus: str | None
    prompt: str
    model: str | None
    controller: str


class SearchScope(_M):
    """One document search as it was actually executed (built by the controller from the tool call, not the model)."""
    call_id: str
    query: str
    region: str | None
    event_window_utc: list[str | None]
    as_of_utc: str | None
    document_types: list[str] | None
    results: int
    market_notices: str = Field(description="'searched: <outcome>', 'not searched: <reason>' or 'not requested'")


class InvestigationReport(_M):
    schema_version: Literal["1"] = "1"
    question: str
    mode: Mode
    intent: Literal["market_event_review", "forecast_review", "source_explanation"] | None
    region: str | None
    as_of: str | None
    event_window: EventWindow | None
    headline: str
    summary: list[str] = Field(default_factory=list, description="short narrative paragraphs; numbers must be claims")
    observations: list[Observation] = Field(default_factory=list)
    forecast_comparison: ForecastComparison | None = None
    possible_explanations: list[Hypothesis] = Field(default_factory=list)
    published_findings: list[PublishedFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    search_scope: list[SearchScope] = Field(default_factory=list, description="document searches actually executed")
    source_manifest: dict[str, Any] = Field(default_factory=dict)
    status: Status
    trace_id: str
    versions: Versions
    generator: str = Field(description="'scripted-replay-controller' or 'live-model:<model id>'")
    validation: dict[str, Any] = Field(default_factory=dict)


def report_json_schema() -> dict[str, Any]:
    return InvestigationReport.model_json_schema()
