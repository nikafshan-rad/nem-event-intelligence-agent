"""`InvestigationReport` — the structured, validated output of every investigation (replay or live)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .render import RenderedResult
from .results import ReportedResult

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
    # The report's format (D25), machine-detectable:
    # - "2": the code rendered a separate computed answer: it is in ``answer``, and ``summary`` holds only the
    #   interpretation (the model's lines in Live, the scripted lines in Replay). Set by the controller, never by model
    #   output, and only on reports that carry a computed result.
    # - "1": every other report, and every report before D25: ``summary`` holds everything shown, a computed sentence
    #   included. A report with no ``schema_version`` (a record written by an exporter that does not keep it) is "1".
    # ``summary_v1`` reads either the way format 1 is read.
    schema_version: Literal["1", "2"] = Field("1", description=(
        "Report format. '2': the computed answer is in `answer` and `summary` is the interpretation only. '1': "
        "`summary` holds everything shown (no separate computed answer). Read `summary` as format 1 with "
        "`summary_v1`."))
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
    # explanations the validated evidence rules out (I-7c), moved here from possible_explanations after validation
    ruled_out_explanations: list[Hypothesis] = Field(default_factory=list)
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
    # D24: typed results the code computed (demand maxima), each with the producing server's verification statement at
    # response time; set only by the controller, never by model output, and not trusted when read back from JSON
    # (``results.verify_loaded`` re-derives them from the pinned store). Nothing displays or validates them yet.
    # D25: the computed answer, rendered by ``render.render_result`` from results the runtime verifier admitted (a result
    # it did not admit is rendered with no value); set only by the controller, apart from the model's interpretation
    # (``summary`` and the rest), and validated like every other narrative (``answer[i]``)
    answer: list[RenderedResult] = Field(default_factory=list, description=(
        "The computed answer: each computed result rendered deterministically from a verified result, with its "
        "limitations and source rows; apart from the narrative, which is the interpretation"))
    results: list[ReportedResult] = Field(default_factory=list, description=(
        "Typed analytical results computed by code (analytical_result/1), with the producing server's verification "
        "statement; re-verify against the pinned store before relying on a result read back from JSON"))
    @model_validator(mode="after")
    def _format_matches_answer(self) -> InvestigationReport:
        """A report carrying a computed answer is format 2; format 1 has no ``answer`` (D25). Format 2 may hold an empty
        ``answer`` (a fallback that kept none of it): its ``summary`` is still the interpretation only."""
        if self.answer and self.schema_version != "2":
            raise ValueError("a report carrying a computed answer (`answer`) must have schema_version '2'")
        return self

    # The model's own headline when the controller shows another (Live, I-3c): validated like the shown headline, so
    # replacing it hides nothing the validator would act on, and never serialised or shown.
    _model_headline: str | None = PrivateAttr(default=None)
    # What the controller wrote, recorded by the controller itself while it builds the report (I-21), never serialised
    # and never taken from model output: ``result_lines``, each summary line stating a requested demand maximum with its
    # binding (index into the resolution's ``demand_max``), position, text and the controller's own claims; and
    # ``controller_notes``, the positions of the uncertainties and missing-evidence items the code wrote. The facts-only
    # fallback reads it (``validation.facts_only``); nothing else does.
    _provenance: dict[str, Any] = PrivateAttr(default_factory=dict)


def report_format(report: InvestigationReport | dict[str, Any]) -> Literal["1", "2"]:
    """The report's format (D25): "2" when it says so, else "1" (including a record with no ``schema_version``)."""
    d = report.model_dump() if isinstance(report, InvestigationReport) else report
    return "2" if d.get("schema_version") == "2" else "1"


def summary_v1(report: InvestigationReport | dict[str, Any]) -> list[str]:
    """``summary`` read as format 1 (the compatibility adapter, D25): everything a format-1 reader showed as the summary.
    Format 2: the computed answer's statements, then the interpretation (for the saved Live runs with a maximum, exactly
    what they showed). Format 1: ``summary`` itself."""
    d = report.model_dump() if isinstance(report, InvestigationReport) else report
    if report_format(d) == "2":
        return [a["statement"] for a in d.get("answer") or []] + list(d.get("summary") or [])
    return list(d.get("summary") or [])


def report_json_schema() -> dict[str, Any]:
    return InvestigationReport.model_json_schema()
