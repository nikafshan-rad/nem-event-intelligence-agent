"""Provider-independent tool dispatcher: validate -> enforce policy -> execute -> register -> trace.

A call is *blocked before execution* when the tool is unknown, not allowed for the intent, over the optional
diagnostic budget, has invalid JSON/arguments, or asks for an as-of later than the request's cutoff.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .. import config
from ..evidence import EvidenceRegistry
from ..selection import Selection
from ..store import Store
from ..timeutil import iso_utc, parse_iso
from ..tools import CONTROLLER_TOOLS, TOOLS
from ..tools.impl import ToolContext
from ..trace import Trace
from .playbook import PLAYBOOKS


@dataclass
class ToolCallRecord:
    call_id: str
    name: str
    origin: str
    raw_args: Any
    args: dict[str, Any] | None
    status: str  # ok | unavailable | refused | blocked | error
    view: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
    duration_ms: float = 0.0
    source_row_ids: list[str] = field(default_factory=list)
    policy_notes: list[str] = field(default_factory=list)
    optional: bool = False

    def model_payload(self) -> dict[str, Any]:
        """What the controller/model sees as the tool result."""
        if self.status == "blocked":
            return {"status": "blocked", "reason": self.blocked_reason}
        return {"status": self.status, "result": self.view, "missing": self.missing, "policy_notes": self.policy_notes}


class Dispatcher:
    def __init__(self, store: Store, selection: Selection, trace: Trace, registry: EvidenceRegistry, intent: str,
                 request_as_of: datetime | None = None) -> None:
        self.store, self.selection, self.trace, self.registry = store, selection, trace, registry
        self.playbook = PLAYBOOKS[intent]
        self.request_as_of = request_as_of
        self.records: list[ToolCallRecord] = []
        self._n = 0

    # -------------------------------------------------------------------- accounting
    @property
    def optional_used(self) -> int:
        return sum(1 for r in self.records if r.optional and r.status != "blocked")

    def calls_of(self, name: str) -> int:
        return sum(1 for r in self.records if r.name == name and r.status != "blocked")

    def required_missing(self) -> list[str]:
        return [t for t in self.playbook.required if self.calls_of(t) == 0]

    # -------------------------------------------------------------------- main entry
    def call(self, name: str, raw_args: Any, *, call_id: str | None = None, origin: str = "controller") -> ToolCallRecord:
        self._n += 1
        cid = call_id or f"call-{self._n:03d}"
        rec = ToolCallRecord(call_id=cid, name=name, origin=origin, raw_args=raw_args, args=None, status="blocked")
        t0 = time.monotonic()
        try:
            self._validate_and_run(rec)
        finally:
            rec.duration_ms = round((time.monotonic() - t0) * 1000, 1)
            self.records.append(rec)
            self.trace.add("tool", name, call_id=cid, origin=origin, status=rec.status, args=rec.args or rec.raw_args,
                           blocked_reason=rec.blocked_reason, duration_ms=rec.duration_ms, optional=rec.optional,
                           policy_notes=rec.policy_notes, missing=rec.missing[:5],
                           source_ids=rec.source_row_ids[:20], n_source_ids=len(rec.source_row_ids))
        return rec

    def _block(self, rec: ToolCallRecord, reason: str) -> None:
        rec.status = "blocked"
        rec.blocked_reason = reason

    def _validate_and_run(self, rec: ToolCallRecord) -> None:
        spec = TOOLS.get(rec.name)
        if spec is None and rec.origin == "controller" and rec.name in self.playbook.controller_only:
            spec = CONTROLLER_TOOLS.get(rec.name)
        if spec is None:
            return self._block(rec, f"unknown tool '{rec.name}' (allowed: {', '.join(TOOLS)})")
        pb = self.playbook
        if rec.name in pb.required:
            if self.calls_of(rec.name) >= pb.max_calls_per_required_tool:
                return self._block(rec, f"'{rec.name}' already called {pb.max_calls_per_required_tool} times")
        elif rec.name in pb.controller_only:  # only a controller call reaches here (see above)
            if self.calls_of(rec.name) >= 1:
                return self._block(rec, f"'{rec.name}' already called once")
        elif rec.name in pb.optional:
            rec.optional = True
            if self.optional_used >= config.MAX_OPTIONAL_DIAGNOSTICS:
                return self._block(rec, f"optional diagnostic budget exhausted ({config.MAX_OPTIONAL_DIAGNOSTICS} max)")
        else:
            return self._block(rec, f"'{rec.name}' is not in the {pb.intent} playbook")
        raw = rec.raw_args
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                return self._block(rec, f"arguments are not valid JSON: {exc.msg}")
        if not isinstance(raw, dict):
            return self._block(rec, "arguments must be a JSON object")
        raw = {k: v for k, v in raw.items()}
        # Request-level as-of cutoff: injected when absent, a later value is a policy violation.
        if self.request_as_of is not None and "as_of_utc" in spec.args_model.model_fields:
            given = raw.get("as_of_utc")
            if given in (None, ""):
                raw["as_of_utc"] = iso_utc(self.request_as_of)
                rec.policy_notes.append(f"as_of_utc injected from request cutoff {iso_utc(self.request_as_of)}")
            else:
                try:
                    if parse_iso(str(given)) > self.request_as_of:
                        return self._block(rec, f"as_of_utc {given} is later than the request cutoff "
                                                f"{iso_utc(self.request_as_of)}")
                except ValueError:
                    pass  # let schema validation report it
        try:
            args = spec.args_model.model_validate(raw)
        except ValidationError as exc:
            msgs = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors()[:4])
            return self._block(rec, f"invalid arguments: {msgs}")
        rec.args = args.model_dump()
        ctx = ToolContext(store=self.store, selection=self.selection, registry=self.registry, call_id=rec.call_id,
                          request_as_of=self.request_as_of)
        try:
            out = spec.handler(ctx, args)
        except Exception as exc:  # a tool bug must surface as an error, never as fabricated output
            rec.status = "error"
            rec.missing = [f"{rec.name} failed: {type(exc).__name__}: {exc}"]
            return None
        rec.status, rec.view, rec.data, rec.missing = out.status, out.view, out.data, out.missing
        rec.source_row_ids = out.source_row_ids
        return None
