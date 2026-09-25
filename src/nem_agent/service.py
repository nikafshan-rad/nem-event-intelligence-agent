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
from .agent.request import InvestigateRequest, Resolution, resolve
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
        if decision is None:
            req_eff = req
        else:
            upd: dict[str, Any] = {"intent": req.intent or decision.intent, "region": req.region or decision.region,
                                   "event_date": req.event_date or decision.event_date,
                                   "as_of_utc": req.as_of_utc or decision.as_of_utc}
            try:  # re-validate: the model's values must pass the same schema as user input
                req_eff = InvestigateRequest.model_validate({**req.model_dump(), **upd})
            except ValueError:
                req_eff, decision = req, None
            if decision is not None:
                trace.add("route", "model_decision", decision=decision.model_dump())
        res = resolve(req_eff, selection)
        if decision is not None and (decision.out_of_scope or decision.needs_clarification) and res.status == "ok":
            res.status = "refused" if decision.out_of_scope else "needs_clarification"
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


def _non_answer(req: InvestigateRequest, res: Resolution, trace: Trace, versions: Versions) -> InvestigationReport:
    status = "refused" if res.status == "refused" else "needs_clarification"
    head = ("Refused: " if status == "refused" else "Clarification needed: ") + " ".join(res.reasons)
    return InvestigationReport(
        question=req.question, mode=req.mode, intent=res.intent, region=res.region, as_of=req.as_of_utc,
        event_window=None, headline=head[:500], summary=[], uncertainties=res.reasons, missing_evidence=[],
        status=status, trace_id=trace.trace_id, versions=versions,
        generator=CONTROLLER_VERSION if req.mode == "replay" else "live-responses-controller/1")
