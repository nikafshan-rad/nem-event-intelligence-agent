"""FastAPI service: `GET /health`, `POST /investigate`, evidence/trace lookup and the local case-note approval flow.

Errors are bounded and explicit: invalid input → 422 with field messages; live mode without a key → 400;
unknown ids → 404. No stack traces or secrets are returned.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, paths
from .agent.request import InvestigateRequest
from .approvals import MOCK_REVIEWERS, ApprovalError, CaseNoteStore, note_content_from_report
from .report import InvestigationReport

app = FastAPI(title="NEM Event Intelligence Agent", version=__version__,
              description="Read-only investigations over public AEMO/NASA data with cited, validated reports. "
                          "Independent research project; not affiliated with AEMO.")
_REPORTS: dict[str, dict[str, Any]] = {}  # trace_id -> report (bounded in-memory cache for case-note proposals)
_TRACE_RE = re.compile(r"^tr-[0-9a-f]{12}$")


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errs = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()[:8]]
    return JSONResponse(status_code=422, content={"error": "invalid_request", "details": errs,
                                                  "hint": "See GET /docs for the InvestigateRequest schema."})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": "internal_error", "type": type(exc).__name__})


@app.get("/health")
def health() -> dict[str, Any]:
    from .service import code_version, corpus_version
    from .store import Store, StoreMissingError

    try:
        dv = Store().data_version
    except StoreMissingError:
        dv = None
    from .sources import source_statuses

    summary = source_statuses()["summary"] if dv else None
    return {"status": "ok" if dv else "degraded", "version": __version__, "code": code_version(), "data_version": dv,
            "corpus_version": corpus_version(), "replay_available": dv is not None,
            "live_available": bool(os.environ.get("OPENAI_API_KEY")), "sources": summary}


@app.get("/sources")
def sources() -> dict[str, Any]:
    """Pinned source versions in use, sources revised upstream, and unavailable sources (see docs/source-governance.md)."""
    from .sources import source_statuses

    return source_statuses()


@app.get("/events")
def events() -> list[dict[str, Any]]:
    from .selection import load_selection

    return [e.model_dump(exclude={"checks"}) for e in load_selection().events]


@app.post("/investigate")
def post_investigate(req: InvestigateRequest) -> dict[str, Any]:
    from .service import investigate

    if req.mode == "live" and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="Live mode needs OPENAI_API_KEY on the server; use mode=replay.")
    res = investigate(req)
    rep = res.report.model_dump()
    if len(_REPORTS) > 200:
        _REPORTS.pop(next(iter(_REPORTS)))
    _REPORTS[rep["trace_id"]] = rep
    return {"report": rep, "trace_id": rep["trace_id"], "latency_ms": res.latency_ms, "usage": res.usage,
            "tool_calls": [{"call_id": r.call_id, "name": r.name, "status": r.status, "args": r.args,
                            "blocked_reason": r.blocked_reason, "duration_ms": r.duration_ms, "optional": r.optional,
                            "missing": r.missing[:3]} for r in res.records]}


@app.get("/schema/report")
def report_schema() -> dict[str, Any]:
    return InvestigationReport.model_json_schema()


@app.get("/evidence/{row_id:path}")
def evidence(row_id: str) -> dict[str, Any]:
    from .store import Store, trace_row

    try:
        return trace_row(Store(), row_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/trace/{trace_id}")
def trace(trace_id: str) -> dict[str, Any]:
    if not _TRACE_RE.match(trace_id):
        raise HTTPException(status_code=404, detail="unknown trace id")
    p = paths.artifacts_dir() / "traces" / f"{trace_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="unknown trace id")
    return json.loads(p.read_text())


# ------------------------------------------------------------------ local case-note approval (human-facing)
class ProposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: str = Field(pattern=r"^tr-[0-9a-f]{12}$")
    author: str = Field(min_length=1, max_length=60)


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str | None = None


@app.post("/case-notes/propose")
def propose(body: ProposeBody) -> dict[str, Any]:
    rep = _REPORTS.get(body.trace_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="run POST /investigate first; trace id not in this server's cache")
    p = CaseNoteStore().propose(note_content_from_report(rep), author=body.author)
    return {"proposal_id": p.proposal_id, "content_sha256": p.content_sha256, "preview": p.content,
            "next": f"a different reviewer ({', '.join(sorted(MOCK_REVIEWERS))}) approves this exact hash"}


@app.post("/case-notes/{proposal_id}/approve")
def approve(proposal_id: str, body: ApproveBody, x_mock_reviewer: str = Header(...)) -> dict[str, Any]:
    try:
        a = CaseNoteStore().approve(proposal_id, x_mock_reviewer, body.approved_sha256)
    except ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"approval_id": a.approval_id, "reviewer": a.reviewer, "approved_sha256": a.approved_sha256}


@app.post("/case-notes/{proposal_id}/publish")
def publish(proposal_id: str, body: PublishBody) -> dict[str, Any]:
    try:
        return CaseNoteStore().publish(proposal_id, body.approval_id)
    except ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
