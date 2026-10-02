"""One entry point for CLI, API, UI and evaluation: ``investigate(request) -> InvestigationResult``."""

from __future__ import annotations

import functools
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from . import config, paths
from .agent.dispatcher import Dispatcher, ToolCallRecord
from .agent.replay import CONTROLLER_VERSION, ReplayController
from .agent.request import (
    InvestigateRequest,
    Resolution,
    asks_about_notices,
    asks_forecast_as_of,
    extract_as_of,
    extract_dates,
    extract_regions,
    forecast_issue_time,
    resolve,
)
from .evidence import EvidenceRegistry
from .report import InvestigationReport, Versions
from .selection import Selection, load_selection
from .store import Store
from .trace import Trace


@dataclass
class InvestigationResult:
    report: InvestigationReport
    trace: Trace
    records: list[ToolCallRecord] = field(default_factory=list)
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)
    resolution: Resolution | None = None
    latency_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paths.repo_root(), capture_output=True,
                             text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=paths.repo_root(),
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def corpus_version() -> str | None:
    p = paths.index_dir() / "index_manifest.json"
    if p.exists():
        return str(json.loads(p.read_text()).get("corpus_version"))
    return None


@functools.lru_cache(maxsize=1)
def _shared() -> tuple[Store, Selection]:
    return Store(), load_selection()


def reset_cache() -> None:
    _shared.cache_clear()


def investigate(req: InvestigateRequest, *, store: Store | None = None, selection: Selection | None = None,
                live_client: Any = None, write_trace: bool = True) -> InvestigationResult:
    t0 = time.monotonic()
    if store is None or selection is None:
        s, sel = _shared()
        store, selection = store or s, selection or sel
    trace = Trace()
    registry = EvidenceRegistry()
    live = None
    if req.mode == "live":
        from .agent.live import LiveController

        live = LiveController(None, registry, Versions(code=code_version(), data=store.data_version, corpus=corpus_version(),
                                                       prompt=config.PROMPT_VERSION, model=None, controller="live"),
                              client=live_client)
        decision = live.route(req.question, trace)
        override: str | None = None
        if decision is None:
            req_eff = req
        else:
            upd, override, notes = route_policy(req, decision)
            try:  # re-validate: the model's values must pass the same schema as user input
                req_eff = InvestigateRequest.model_validate({**req.model_dump(), **upd})
            except ValueError:
                req_eff, decision, override = req, None, None
            if decision is not None:
                trace.add("route", "model_decision", decision=decision.model_dump(), policy_notes=notes)
        res = resolve(req_eff, selection)
        if decision is not None and override and res.status == "ok":
            res.status = override  # type: ignore[assignment]
            res.reasons = [decision.clarification or "The model judged the question out of scope or ambiguous."]
        if decision is None:
            res.status, res.reasons = "needs_clarification", ["The routing model returned invalid output."]
    else:
        res = resolve(req, selection)
    trace.add("route", res.intent or "none", status=res.status, routing=res.routing, reasons=res.reasons,
              region=res.region, as_of=res.as_of.isoformat() if res.as_of else None,
              window=[w.isoformat() for w in res.window] if res.window else None)
    model_id = live.model if live else None
    versions = Versions(code=code_version(), data=store.data_version, corpus=corpus_version(),
                        prompt=config.PROMPT_VERSION, model=model_id,
                        controller=CONTROLLER_VERSION if req.mode == "replay" else "live-responses-controller/1")
    records: list[ToolCallRecord] = []
    usage: dict[str, Any] = {}
    if res.status != "ok" or res.intent is None:
        report = _non_answer(req, res, trace, versions)
    else:
        disp = Dispatcher(store, selection, trace, registry, res.intent, res.as_of)
        if live is None:
            report = ReplayController(disp, registry, versions).run(res)
        else:
            live.d, live.versions = disp, versions
            report = live.run(res)
        records = disp.records
    if live is not None:
        usage = live.usage.as_dict()
    from .validation import validate_and_finalize
    report = validate_and_finalize(report, registry, records, res, trace)
    latency = round((time.monotonic() - t0) * 1000, 1)
    trace.add("done", report.status, latency_ms=latency, usage=usage)
    if write_trace:
        trace.write()
    return InvestigationResult(report, trace, records, registry, res, latency, usage)


def route_policy(req: InvestigateRequest, decision: Any) -> tuple[dict[str, Any], str | None, list[str]]:
    """Apply the model's routing decision under the same rules the deterministic resolver uses.

    The model classifies the question and extracts parameters; code decides what those mean:
    - several regions or dates named in the question are left to the resolver, which finds them in the text itself,
      instead of trusting the model to have picked one or to have flagged it;
    - a definition or document question needs no region or date, so the model's request for one is not applied
      (L3 live, DOC03: "What is TOTALDEMAND in the dispatch region summary data?" was sent back for a region);
    - an as-of question about forecasts is a forecast review even when it names an event (L3 live, AMB06);
    - a forecast question with one region, no date and an explicit as-of cutoff is dated by the cutoff, so the model's
      request for a missing date is not applied (held-out v5 Y07); the resolver derives the day from the cutoff.
    Out-of-scope decisions and every other clarification request are applied unchanged.
    Returns (request updates, status override or None, notes for the trace)."""
    q = req.question
    notes: list[str] = []
    several = len(extract_regions(q)) > 1 or len(extract_dates(q)) > 1
    intent = req.intent or decision.intent
    if req.intent is None and intent in ("market_event_review", "forecast_review") and asks_about_notices(q):
        intent = "source_explanation"
        notes.append("routed as source_explanation: a question about what notices said")
    if req.intent is None and intent == "market_event_review" and asks_forecast_as_of(q):
        intent = "forecast_review"
        notes.append("routed as forecast_review: an as-of question about forecasts")
    as_of = req.as_of_utc or decision.as_of_utc
    if req.as_of_utc is None and decision.as_of_utc and forecast_issue_time(q) is not None:
        as_of = None
        notes.append("as_of not applied: the time in the question is a forecast's issue time, not an as-of cutoff")
    if several:
        notes.append("several regions or dates in the question: left to the resolver")
    upd: dict[str, Any] = {"intent": intent, "region": req.region or (None if several else decision.region),
                           "event_date": req.event_date or (None if several else decision.event_date),
                           "as_of_utc": as_of}
    override: str | None = None
    if decision.out_of_scope:
        override = "refused"
    elif decision.needs_clarification:
        if intent == "source_explanation" and decision.clarification_reason == "missing_region_or_date":
            notes.append("clarification not applied: a definition or document question needs no region or date")
        elif (intent == "forecast_review" and decision.clarification_reason == "missing_region_or_date"
              and not several and not extract_dates(q) and (req.region or len(extract_regions(q)) == 1)
              and (req.as_of_utc or extract_as_of(q, None, None))):
            notes.append("clarification not applied: the explicit as-of cutoff gives the date (its local date in the "
                         "region)")
        else:
            override = "needs_clarification"
    return upd, override, notes


def _non_answer(req: InvestigateRequest, res: Resolution, trace: Trace, versions: Versions) -> InvestigationReport:
    status = "refused" if res.status == "refused" else "needs_clarification"
    head = ("Refused: " if status == "refused" else "Clarification needed: ") + " ".join(res.reasons)
    return InvestigationReport(
        question=req.question, mode=req.mode, intent=res.intent, region=res.region, as_of=req.as_of_utc,
        event_window=None, headline=head[:500], summary=[], uncertainties=res.reasons, missing_evidence=[],
        status=status, trace_id=trace.trace_id, versions=versions,
        generator=CONTROLLER_VERSION if req.mode == "replay" else "live-responses-controller/1")
