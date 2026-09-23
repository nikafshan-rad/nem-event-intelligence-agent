"""`publish_case_note` — a gated LOCAL write action (demo of an approval boundary, not a real review service).

Flow: ``propose`` (preview + SHA-256 of the exact content) → ``approve`` by a *different*, allowlisted mock
reviewer who supplies that exact hash → ``publish`` writes one note file, exactly once.

Rejected (nothing written): no approval; approval for a different/stale hash (content revised after approval);
self-approval; unknown reviewer; re-use of an approval (idempotent: returns the existing note, no second write).
The model never calls this module: it is not in the tool registry, and the API exposes it only as explicit
human-facing endpoints. Nothing leaves the local ``data/case_notes`` directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths
from .timeutil import iso_utc

MOCK_REVIEWERS = frozenset({"mock-reviewer-a", "mock-reviewer-b"})


class ApprovalError(PermissionError):
    """The write is not authorised; the reason is in the message."""


@dataclass
class Proposal:
    proposal_id: str
    author: str
    created_at: str
    content: dict[str, Any]
    content_sha256: str
    revision: int = 1


@dataclass
class Approval:
    approval_id: str
    proposal_id: str
    reviewer: str
    approved_sha256: str
    approved_at: str
    used: bool = False


def canonical_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _now() -> str:
    return iso_utc(datetime.now(UTC))


class CaseNoteStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.case_notes_dir()
        for sub in ("proposals", "approvals", "notes"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- persistence helpers
    def _p(self, kind: str, ident: str) -> Path:
        return self.root / kind / f"{ident}.json"

    def _save(self, kind: str, ident: str, obj: Any) -> None:
        tmp = self._p(kind, ident).with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(obj), indent=2, sort_keys=True))
        tmp.replace(self._p(kind, ident))

    def proposal(self, proposal_id: str) -> Proposal:
        p = self._p("proposals", proposal_id)
        if not p.exists():
            raise ApprovalError(f"unknown proposal {proposal_id}")
        return Proposal(**json.loads(p.read_text()))

    def approval(self, approval_id: str) -> Approval:
        p = self._p("approvals", approval_id)
        if not p.exists():
            raise ApprovalError(f"unknown approval {approval_id}")
        return Approval(**json.loads(p.read_text()))

    def notes(self) -> list[dict[str, Any]]:
        return [json.loads(p.read_text()) for p in sorted((self.root / "notes").glob("*.json"))]

    # ---------------------------------------------------------------- flow
    def propose(self, content: dict[str, Any], author: str) -> Proposal:
        if not author:
            raise ApprovalError("author required")
        prop = Proposal(proposal_id=f"prop-{uuid.uuid4().hex[:12]}", author=author, created_at=_now(), content=content,
                        content_sha256=canonical_hash(content))
        self._save("proposals", prop.proposal_id, prop)
        return prop

    def revise(self, proposal_id: str, content: dict[str, Any], author: str) -> Proposal:
        prop = self.proposal(proposal_id)
        if author != prop.author:
            raise ApprovalError("only the author may revise a proposal")
        prop.content, prop.content_sha256, prop.revision = content, canonical_hash(content), prop.revision + 1
        self._save("proposals", prop.proposal_id, prop)
        return prop  # earlier approvals no longer match the hash and become stale

    def approve(self, proposal_id: str, reviewer: str, approved_sha256: str) -> Approval:
        prop = self.proposal(proposal_id)
        if reviewer not in MOCK_REVIEWERS:
            raise ApprovalError(f"reviewer '{reviewer}' is not an allowlisted mock reviewer")
        if reviewer == prop.author:
            raise ApprovalError("self-approval is not allowed: reviewer must differ from the author")
        if approved_sha256 != prop.content_sha256:
            raise ApprovalError("approved hash does not match the proposal's current content (stale or wrong preview)")
        appr = Approval(approval_id=f"appr-{uuid.uuid4().hex[:12]}", proposal_id=proposal_id, reviewer=reviewer,
                        approved_sha256=approved_sha256, approved_at=_now())
        self._save("approvals", appr.approval_id, appr)
        return appr

    def publish(self, proposal_id: str, approval_id: str | None) -> dict[str, Any]:
        """Idempotent: one note per (proposal, content hash). Returns {'status': 'written'|'already_published', ...}."""
        prop = self.proposal(proposal_id)
        if not approval_id:
            raise ApprovalError("no approval supplied; nothing written")
        appr = self.approval(approval_id)
        if appr.proposal_id != proposal_id:
            raise ApprovalError("approval belongs to a different proposal")
        if appr.approved_sha256 != prop.content_sha256:
            raise ApprovalError("approval is stale: the proposal changed after it was approved")
        if appr.reviewer == prop.author:
            raise ApprovalError("self-approval is not allowed")
        note_id = f"note-{prop.content_sha256[:16]}"
        path = self._p("notes", note_id)
        record = {"note_id": note_id, "proposal_id": proposal_id, "content_sha256": prop.content_sha256,
                  "author": prop.author, "reviewer": appr.reviewer, "approval_id": appr.approval_id,
                  "published_at": _now(), "content": prop.content,
                  "disclaimer": "Local research note; mock approval workflow; not an external publication."}
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # exactly-once create
        except FileExistsError:
            existing = json.loads(path.read_text())
            return {"status": "already_published", "note": existing}
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(record, indent=2, sort_keys=True))
        appr.used = True
        self._save("approvals", appr.approval_id, appr)
        return {"status": "written", "note": record}


def note_content_from_report(report: Any) -> dict[str, Any]:
    """The previewable content of a case note: only validated report fields, never free model text."""
    r = report.model_dump() if hasattr(report, "model_dump") else dict(report)
    return {"question": r["question"], "region": r["region"], "event_window": r["event_window"],
            "headline": r["headline"], "status": r["status"], "observations": r["observations"],
            "citations": [{k: c[k] for k in ("citation_id", "title", "url", "quote")} for c in r["citations"]],
            "uncertainties": r["uncertainties"], "trace_id": r["trace_id"], "versions": r["versions"],
            "validation_passed": r.get("validation", {}).get("final_passed")}
