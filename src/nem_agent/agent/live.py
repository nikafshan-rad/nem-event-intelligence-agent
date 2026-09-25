"""Live controller: a real model issues function calls through the bounded dispatcher (OpenAI Responses API).

Loop (stateless; the full input list is re-sent each turn):

1. **Route** — one structured-output call returns intent/region/date/as-of; code validates it and applies the same
   deterministic guards as replay (out-of-scope, non-NEM, ambiguity).
2. **Tools** — the model sees only the playbook's tools (strict schemas). Each ``function_call`` is validated and
   executed by :class:`Dispatcher`; its result is returned as ``function_call_output`` with the same ``call_id``.
   Bounded by ``MAX_MODEL_CALLS`` and the session budget. Missing required tools are requested once.
3. **Synthesis** — one structured-output call returns :class:`ModelReport`; the controller copies values and source
   metadata from the evidence registry (the model supplies only ids, quotes and wording).
4. **Validation** — independent validator; on critical violations one repair turn, then facts-only fallback.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import config
from ..evidence import EvidenceRegistry
from ..report import (
    Citation,
    EventWindow,
    Hypothesis,
    InvestigationReport,
    NumericClaim,
    Observation,
    PublishedFinding,
    Versions,
)
from ..timeutil import iso_utc, local_str, parse_iso
from ..tools import openai_function_tools
from ..tools.args import strict_json_schema
from .dispatcher import Dispatcher
from .playbook import PLAYBOOKS
from .request import Resolution

CONTROLLER = "live-responses-controller/1"
# Retrieved text is capped at config.MAX_RETRIEVED_CHARS (12k) plus ~0.6k metadata per result; 20k keeps a full
# top_k=8 notice result intact (truncation cuts the JSON, so it is recorded in the trace when it happens).
MAX_TOOL_OUTPUT_CHARS = 20_000
# Model calls kept back from the tool loop so a report can always be written and repaired once (a live run spent
# six calls on one-tool-per-turn loops and left no call for the repair turn).
RESERVED_CALLS = 2


def model_id_from_env() -> str:
    return os.environ.get("NEM_AGENT_MODEL", "gpt-5-mini")


def prompt(name: str) -> str:
    return (resources.files("nem_agent").joinpath(*config.PROMPT_VERSION.split("/")) / f"{name}.md").read_text()


# ------------------------------------------------------------------------------------ model-facing schemas
class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteDecision(_S):
    intent: Literal["market_event_review", "forecast_review", "source_explanation"] | None
    region: Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"] | None
    event_date: str | None = Field(description="YYYY-MM-DD in the region's local time")
    as_of_utc: str | None
    needs_clarification: bool
    clarification: str | None
    out_of_scope: bool


EVIDENCE_ID_NOTE = "an evidence_id (ev + 4 digits) from a tool result; never a chunk_id or citation_id"


class MClaim(_S):
    claim_id: str
    text: str
    value: float = Field(description="the number exactly as displayed in the text")
    unit: str = Field(description="the unit the tool gave for this evidence item")
    evidence_id: str = Field(description=EVIDENCE_ID_NOTE)
    rounding: float


class MHypothesis(_S):
    statement: str = Field(description="hedged (may/might/could); mention documents by citation id, e.g. [c2]")
    supporting_evidence_ids: list[str] = Field(description=f"each is {EVIDENCE_ID_NOTE}; may be empty")
    what_would_test_it: str


class MFinding(_S):
    citation_id: str = Field(description="citation_id of your citation quoting a same-region, same-window AEMO market "
                                         "notice; the controller renders the finding as that verbatim quote")
    applies_to_event: bool


class MCitation(_S):
    citation_id: str
    chunk_id: str = Field(description="chunk_id of a passage returned by retrieve_public_evidence")
    quote: str = Field(description="one sentence or clause (<= 200 characters) copied character-for-character, "
                                   "including capitalisation, from that passage")
    supports: str


class ModelReport(_S):
    status: Literal["answered", "answered_with_caveats", "needs_clarification", "abstained"]
    headline: str
    summary: list[str]
    observation_evidence_ids: list[str] = Field(description=f"each is {EVIDENCE_ID_NOTE}")
    numeric_claims: list[MClaim]
    possible_explanations: list[MHypothesis]
    published_findings: list[MFinding]
    citations: list[MCitation]
    uncertainties: list[str]
    missing_evidence: list[str]


# ------------------------------------------------------------------------------------ transports
class Transport(Protocol):
    def create(self, **kwargs: Any) -> dict[str, Any]: ...


class OpenAITransport:
    """Thin adapter over the installed OpenAI SDK; returns plain dicts."""

    def __init__(self, timeout_s: float | None = None, client: Any = None) -> None:
        from openai import OpenAI

        self.client = client or OpenAI(timeout=timeout_s or float(os.environ.get("NEM_AGENT_API_TIMEOUT_S", "60")),
                                       max_retries=1)

    def create(self, **kwargs: Any) -> dict[str, Any]:
        resp = self.client.responses.create(**kwargs)
        return resp.model_dump(mode="json")


def model_prices(model: str) -> tuple[float, float] | None:
    """USD per 1M (input, output) tokens: environment override, else the dated table in config, else None."""
    pin, pout = os.environ.get("NEM_AGENT_PRICE_INPUT_PER_MTOK"), os.environ.get("NEM_AGENT_PRICE_OUTPUT_PER_MTOK")
    if pin and pout:
        return float(pin), float(pout)
    return config.MODEL_PRICES_PER_MTOK.get(model)


@dataclass
class Usage:
    model: str = ""
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    started: float = field(default_factory=time.monotonic)

    def add(self, resp: dict[str, Any]) -> None:
        self.model_calls += 1
        u = resp.get("usage") or {}
        self.input_tokens += int(u.get("input_tokens") or 0)
        self.output_tokens += int(u.get("output_tokens") or 0)
        if (p := model_prices(self.model)) is not None:  # cached input charged at the full rate: an upper bound
            self.cost_usd = round(self.input_tokens / 1e6 * p[0] + self.output_tokens / 1e6 * p[1], 6)

    def as_dict(self) -> dict[str, Any]:
        return {"model_calls": self.model_calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd, "cost_note": "upper bound: cached input charged at the uncached rate"
                if self.cost_usd is not None else "no price known for this model",
                "elapsed_s": round(time.monotonic() - self.started, 2)}


class BudgetExceeded(RuntimeError):
    pass


def _texts(resp: dict[str, Any]) -> str:
    out = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    out.append(c.get("text", ""))
    return "".join(out)


def _trace_draft(trace: Any, stage: str, draft: BaseModel | None) -> None:
    """Keep the model's draft in the (local, redacted) trace so a rejected narrative can be inspected later."""
    if draft is not None:
        trace.add("model", f"{stage}:draft", report=draft.model_dump())


# How to fix each violation, sent with the repair turn (the validator's own wording says only what failed).
REPAIR_HINTS = {
    "NUMERIC_UNTRACKED": "Every number outside a quote must be a numeric_claim that cites the evidence_id holding it. "
                         "Otherwise delete the number: write clock times as HH:MM, name variables (e.g. WS50M) "
                         "instead of restating numbers in their names, and keep document numbers inside quotes.",
    "CLAIM_EVIDENCE_MISSING": "A numeric_claim must cite an evidence_id (ev + 4 digits) returned by a tool. Chunk and "
                              "citation ids are not numeric evidence: delete such claims and the numbers they covered.",
    "CLAIM_UNIT_MISMATCH": "Cite the evidence item that holds exactly this value in this unit; if no tool returned it "
                           "with its own evidence_id, delete the number.",
    "CLAIM_VALUE_MISMATCH": "Cite the evidence item that holds exactly this value; if none does, delete the number.",
    "HYPOTHESIS_EVIDENCE_MISSING": "supporting_evidence_ids accepts only tool evidence_ids (it may be empty); mention "
                                   "documents by an existing citation id in the statement, e.g. [c2]. Add a new "
                                   "citation only with a short quote copied exactly.",
    "UNSUPPORTED_CAUSALITY": "Remove causal wording outside possible_explanations; AEMO's own wording belongs only "
                             "inside a citation quote.",
    "HYPOTHESIS_UNHEDGED": "Word every possible explanation with may, might or could.",
    "CITATION_QUOTE_NOT_FOUND": "Copy a short quote (one sentence) character-for-character, including "
                                "capitalisation, from the retrieved passage, or drop the citation.",
    "CITATION_UNKNOWN_CHUNK": "Cite only chunk_ids returned by retrieve_public_evidence in this investigation.",
}


def repair_message(result: Any) -> str:
    crit = result.critical
    lines = [f"- {v.code}: {v.detail}" for v in crit[:20]]
    if len(crit) > 20:
        lines.append(f"- ... and {len(crit) - 20} more of the same kinds")
    hints = [f"- {c}: {REPAIR_HINTS[c]}" for c in sorted({v.code for v in crit}) if c in REPAIR_HINTS]
    return ("The report failed independent validation. Fix ONLY these problems and return the full corrected JSON:\n"
            + "\n".join(lines) + ("\nHow to fix them:\n" + "\n".join(hints) if hints else ""))


def _replayable(item: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an output item into an input item for the next stateless turn."""
    t = item.get("type")
    if t == "function_call":
        return {"type": "function_call", "call_id": item["call_id"], "name": item["name"], "arguments": item["arguments"]}
    if t == "message":
        return {"role": "assistant", "content": _texts({"output": [item]})}
    if t == "reasoning" and item.get("encrypted_content"):
        return {k: item[k] for k in ("type", "id", "summary", "encrypted_content") if k in item}
    return None


# ------------------------------------------------------------------------------------ controller
class LiveController:
    def __init__(self, dispatcher: Dispatcher | None, registry: EvidenceRegistry, versions: Versions,
                 client: Transport | None = None, model: str | None = None) -> None:
        self.d = dispatcher
        self.reg = registry
        self.versions = versions
        self.client = client or OpenAITransport()
        self.model = model or model_id_from_env()
        self.usage = Usage(model=self.model)
        self.transcript: list[dict[str, Any]] = []

    # -- model call with bounds ------------------------------------------------------------------------------
    def _call(self, trace: Any, stage: str, **kwargs: Any) -> dict[str, Any]:
        if self.usage.model_calls >= config.MAX_MODEL_CALLS:
            raise BudgetExceeded(f"model call cap reached ({config.MAX_MODEL_CALLS})")
        if model_prices(self.model) is None:  # without a price the budget cannot be enforced: fail closed
            raise BudgetExceeded(f"no price known for model {self.model!r}; set NEM_AGENT_PRICE_INPUT_PER_MTOK and "
                                 "NEM_AGENT_PRICE_OUTPUT_PER_MTOK")
        budget = float(os.environ.get("NEM_AGENT_SESSION_BUDGET_USD", "0.50"))
        if self.usage.cost_usd is not None and self.usage.cost_usd >= budget:
            raise BudgetExceeded(f"session budget {budget} USD reached")
        t0 = time.monotonic()
        resp = self.client.create(model=self.model, store=False, **kwargs)
        self.usage.add(resp)
        calls = [{"call_id": i.get("call_id"), "name": i.get("name"), "arguments": i.get("arguments")}
                 for i in resp.get("output", []) if i.get("type") == "function_call"]
        trace.add("model", stage, model=self.model, response_id=resp.get("id"), function_calls=calls,
                  usage=resp.get("usage"), duration_ms=round((time.monotonic() - t0) * 1000, 1))
        self.transcript.append({"stage": stage, "response_id": resp.get("id"), "function_calls": calls})
        return resp

    def _structured(self, trace: Any, stage: str, schema_model: type[BaseModel], instructions: str,
                    input_items: list[Any]) -> tuple[BaseModel | None, str]:
        fmt = {"type": "json_schema", "name": schema_model.__name__, "schema": strict_json_schema(schema_model), "strict": True}
        resp = self._call(trace, stage, instructions=instructions, input=input_items, text={"format": fmt})
        raw = _texts(resp)
        try:
            return schema_model.model_validate_json(raw), raw
        except ValidationError as exc:
            trace.add("model", f"{stage}:invalid_json", error=str(exc)[:400])
            return None, raw

    # -- 1. route ---------------------------------------------------------------------------------------------
    def route(self, question: str, trace: Any) -> RouteDecision | None:
        dec, _ = self._structured(trace, "route", RouteDecision, prompt("route"),
                                  [{"role": "user", "content": question}])
        if dec is None:
            return None
        assert isinstance(dec, RouteDecision)
        if dec.event_date:
            try:
                date.fromisoformat(dec.event_date)
            except ValueError:
                return dec.model_copy(update={"event_date": None, "needs_clarification": True,
                                              "clarification": "The event date could not be parsed."})
        if dec.as_of_utc:
            try:
                parse_iso(dec.as_of_utc)
            except ValueError:
                return dec.model_copy(update={"as_of_utc": None})
        return dec

    # -- 2 + 3. tools and synthesis -----------------------------------------------------------------------------
    def run(self, res: Resolution) -> InvestigationReport:
        assert self.d is not None and res.intent is not None
        trace = self.d.trace
        pb = PLAYBOOKS[res.intent]
        allowed = list(pb.required) + list(pb.optional)
        context = {
            "question": res.request.question, "intent": res.intent, "region": res.region,
            "window_utc": [iso_utc(res.window[0]), iso_utc(res.window[1])] if res.window else None,
            "window_local": [local_str(res.window[0], res.region), local_str(res.window[1], res.region)]
            if res.window and res.region else None,
            "as_of_utc": iso_utc(res.as_of) if res.as_of else None,
            "event_peak_interval_end_utc": res.event.peak_interval_end_utc if res.event else None,
            "required_tools": list(pb.required), "optional_tools_max_2": list(pb.optional),
        }
        items: list[Any] = [{"role": "user", "content": "Investigation context (JSON):\n" + json.dumps(context, indent=1)}]
        tools = openai_function_tools(allowed)
        nudged = False
        stopped: list[str] = []
        try:
            while True:
                if self.usage.model_calls >= config.MAX_MODEL_CALLS - RESERVED_CALLS:
                    stopped.append(f"Tool loop stopped at the model call cap ({self.usage.model_calls} of "
                                   f"{config.MAX_MODEL_CALLS} calls; {RESERVED_CALLS} kept for synthesis and repair).")
                    trace.add("model", "tool_loop_stopped", reason=stopped[-1])
                    break
                resp = self._call(trace, "tools", instructions=prompt("system"), input=items, tools=tools,
                                  tool_choice="auto", parallel_tool_calls=True)
                calls = [i for i in resp.get("output", []) if i.get("type") == "function_call"]
                items += [x for x in (_replayable(i) for i in resp.get("output", [])) if x]
                for c in calls:
                    rec = self.d.call(c["name"], c.get("arguments") or "{}", call_id=c["call_id"], origin="model")
                    payload = json.dumps(rec.model_payload(), default=str)
                    if len(payload) > MAX_TOOL_OUTPUT_CHARS:
                        trace.add("model", "tool_output_truncated", call_id=c["call_id"], chars=len(payload))
                        payload = payload[:MAX_TOOL_OUTPUT_CHARS] + '..."[truncated]"'
                    items.append({"type": "function_call_output", "call_id": c["call_id"], "output": payload})
                if calls:
                    continue
                missing = self.d.required_missing()
                if missing and not nudged:
                    nudged = True
                    items.append({"role": "user", "content": f"Required tools not yet called: {missing}. Call them now."})
                    continue
                break
            items.append({"role": "user", "content": prompt("synthesis")})
            mrep, raw = self._structured(trace, "synthesis", ModelReport, prompt("system"), items)
            _trace_draft(trace, "synthesis", mrep)
        except BudgetExceeded as exc:
            trace.add("model", "budget_exceeded", reason=str(exc))
            return self._build(res, None, extra_missing=[f"Live run stopped: {exc}"])
        report = self._build(res, mrep if isinstance(mrep, ModelReport) else None,
                             extra_missing=stopped + ([] if mrep else ["Model output did not match the report schema."]))
        # -- 4. one bounded repair turn driven by the independent validator
        from ..validation import validate

        first = validate(report, self.reg, as_of=res.as_of, window=res.window, records=self.d.records,
                         required_tools=pb.required)
        if first.critical and self.usage.model_calls < config.MAX_MODEL_CALLS:
            items += [{"role": "assistant", "content": raw or ""}, {"role": "user", "content": repair_message(first)}]
            try:
                mrep2, _ = self._structured(trace, "repair", ModelReport, prompt("system"), items)
                _trace_draft(trace, "repair", mrep2)
            except BudgetExceeded as exc:
                mrep2 = None
                trace.add("model", "budget_exceeded", reason=str(exc))
            if isinstance(mrep2, ModelReport):
                report = self._build(res, mrep2, extra_missing=stopped)
            report = report.model_copy(update={"validation": {"repair_attempted": True,
                                                              "pre_repair_codes": sorted({v.code for v in first.critical}),
                                                              "pre_repair": first.as_dict()}})
        return report

    def _build(self, res: Resolution, m: ModelReport | None, extra_missing: list[str]) -> InvestigationReport:
        missing = list(extra_missing)
        recs = self.d.records if self.d else []
        for i, r in enumerate(recs):
            if r.status == "blocked" and any(x.name == r.name and x.status == "ok" for x in recs[i + 1:]):
                continue  # a corrected retry of the same tool succeeded; nothing is missing
            if r.status in ("unavailable", "refused", "error", "blocked"):
                missing.append(f"{r.name}: {r.status} — {(r.missing or [r.blocked_reason or ''])[0]}"[:400])
        obs: list[Observation] = []
        cites: list[Citation] = []
        if m is not None:
            for eid in m.observation_evidence_ids:
                ev = self.reg.get(eid)
                if ev is None or ev.value is None or ev.evidence_class == "published_document":
                    missing.append(f"model referenced unknown or non-numeric evidence id {eid}")
                    continue
                if not ev.valid_at_utc:  # e.g. the analysis threshold: citable in a claim, but not an observation
                    missing.append(f"{eid} ({ev.metric}) is not a time-stamped observation; listed only as a claim")
                    continue
                obs.append(Observation(metric=ev.metric, value=float(ev.value), unit=ev.unit, valid_at_utc=ev.valid_at_utc,
                                       valid_at_local=local_str(parse_iso(ev.valid_at_utc), res.region) if res.region else None,
                                       interval_minutes=ev.interval_minutes, evidence_id=eid,
                                       source_row_ids=(ev.source_row_ids or [f"derived:{ev.derivation}"])[:12],
                                       evidence_class=ev.evidence_class,
                                       label=(ev.label or ev.derivation or ev.metric)[:300]))
            for c in m.citations:
                ch = self.reg.chunks.get(c.chunk_id)
                cites.append(Citation(citation_id=c.citation_id, chunk_id=c.chunk_id,
                                      doc_id=ch.doc_id if ch else "unknown", title=ch.title if ch else "unknown",
                                      url=ch.url if ch else "unknown", section=ch.section if ch else None,
                                      page=ch.page if ch else None, publication_date=ch.publication_date if ch else None,
                                      doc_type=ch.doc_type if ch else "unknown", quote=c.quote[:600],
                                      supports=c.supports[:400]))
        # Findings are rendered from the cited verbatim quote (as in replay); the model chooses only which citation.
        findings: list[PublishedFinding] = []
        by_id = {c.citation_id: c for c in cites}
        for f in m.published_findings if m is not None else []:
            fc = by_id.get(f.citation_id)
            if fc is None or fc.doc_type not in ("market_notice", "event_report", "definition", "procedure"):
                missing.append(f"model listed a published finding for unknown or unretrieved citation {f.citation_id}")
                continue
            findings.append(PublishedFinding(
                statement=f"An AEMO {fc.doc_type.replace('_', ' ')} for {res.region} [{fc.citation_id}] says: “{fc.quote}”",
                citation_ids=[fc.citation_id], doc_type=fc.doc_type, applies_to_event=f.applies_to_event))
        ew = None
        if res.window and res.region:
            ew = EventWindow(start_utc=iso_utc(res.window[0]), end_utc=iso_utc(res.window[1]),
                             start_local=local_str(res.window[0], res.region), end_local=local_str(res.window[1], res.region),
                             timezone=str(res.routing.get("region_tz") or ""))
        status = m.status if m else "abstained"
        return InvestigationReport(
            question=res.request.question, mode="live", intent=res.intent, region=res.region,
            as_of=iso_utc(res.as_of) if res.as_of else None, event_window=ew,
            headline=m.headline if m else "Abstained: the live model did not produce a valid report.",
            summary=m.summary if m else [], observations=obs,
            numeric_claims=[NumericClaim(**c.model_dump()) for c in m.numeric_claims] if m else [],
            possible_explanations=[Hypothesis(statement=h.statement, supporting_evidence_ids=h.supporting_evidence_ids,
                                              what_would_test_it=h.what_would_test_it) for h in m.possible_explanations] if m else [],
            published_findings=findings,
            citations=cites, uncertainties=m.uncertainties if m else [],
            missing_evidence=list(dict.fromkeys((m.missing_evidence if m else []) + missing)),
            source_manifest={"data_version": self.versions.data, "corpus_version": self.versions.corpus,
                             "model": self.model, "usage": self.usage.as_dict(), "transcript": self.transcript},
            status=status if status != "needs_clarification" else "needs_clarification",
            trace_id=self.d.trace.trace_id if self.d else "n/a", versions=self.versions,
            generator=f"live-model:{self.model}")
