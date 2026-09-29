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
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from importlib import resources
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from .. import budget, config
from ..budget import BudgetExceeded
from ..evidence import EvidenceRegistry
from ..report import (
    Citation,
    EventWindow,
    ForecastComparison,
    Hypothesis,
    InvestigationReport,
    NumericClaim,
    Observation,
    PublishedFinding,
    SearchScope,
    Versions,
)
from ..timeutil import half_hour_end_for, iso_utc, local_str, parse_iso
from ..tools import openai_function_tools
from ..tools.args import strict_json_schema
from .dispatcher import Dispatcher
from .playbook import PLAYBOOKS
from .replay import forecast_focus
from .request import (
    Resolution,
    asks_if_notice_event_caused,
    forecast_issue_time,
    requested_measures,
)

CONTROLLER = "live-responses-controller/1"
# Retrieved text is capped at config.MAX_RETRIEVED_CHARS (12k) plus ~0.6k metadata per result; 20k keeps a full
# top_k=8 notice result intact (truncation cuts the JSON, so it is recorded in the trace when it happens).
MAX_TOOL_OUTPUT_CHARS = 20_000
# Model calls kept back from the tool loop so a report can always be written and repaired once (a live run spent
# six calls on one-tool-per-turn loops and left no call for the repair turn).
RESERVED_CALLS = 2
def _zoned(local: str) -> str:
    """"2026-07-27 07:00 AEST (UTC+1000)" -> "2026-07-27 07:00 AEST"."""
    return re.sub(r" [(]UTC[^)]*[)]", "", local)


# capitalised words that locate or phrase a question rather than name an incident (for _timing_answer)
_NOT_NAMES = {
    "was", "were", "is", "are", "did", "does", "do", "could", "would", "can", "has", "had", "how", "what", "why", "when",
    "which", "who", "the", "a", "an", "in", "on", "at", "for", "if", "that", "this", "and", "or", "i", "so",
    "aemo", "nem", "nemweb", "aest", "aedt", "acst", "acdt", "awst", "utc", "mw", "mwh", "rrp", "kv",
    "nsw", "nsw1", "qld", "qld1", "sa", "sa1", "tas", "tas1", "vic", "vic1", "victoria", "victorian", "queensland",
    "tasmania", "tasmanian", "south", "australia", "australian", "new", "wales", "january", "february", "march",
    "april", "may", "june", "july", "august", "september", "october", "november", "december", "jan", "feb", "mar",
    "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday"}


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
    clarification_reason: Literal["several_regions", "several_dates", "missing_region_or_date",
                                  "unclear_question"] | None = Field(
        description="why clarification is needed; null when needs_clarification is false")
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


class MDocStatement(_S):
    citation_id: str = Field(description="citation_id of the passage this sentence relies on")
    quote: str | None = Field(description="text copied character-for-character from that passage; the controller shows "
                                          "it in quotation marks with the citation (null when paraphrasing)")
    paraphrase: str | None = Field(description="a close restatement in your own words of only what the passage says "
                                               "(null when quoting)")


class ModelReport(_S):
    status: Literal["answered", "answered_with_caveats", "needs_clarification", "abstained"]
    headline: str
    summary: list[str]
    document_statements: list[MDocStatement] = Field(
        description="definition and document answers: one entry per sentence, each tied to one citation; the controller "
                    "writes the sentence and its [citation_id]. Leave empty for event and forecast reviews.")
    observation_evidence_ids: list[str] = Field(description=f"each is {EVIDENCE_ID_NOTE}")
    numeric_claims: list[MClaim]
    possible_explanations: list[MHypothesis]
    published_findings: list[MFinding]
    citations: list[MCitation]
    uncertainties: list[str]
    missing_evidence: list[str]
    forecast_mae_evidence_id: str | None = Field(
        description="for a forecast review: the evidence_id of the compare_forecast_actual MAE you report (else null)")


# Document questions: every sentence is a document statement tied to one citation, so the schema has no free summary.
# Regression H14 and held-out v3 V13/V14 wrote document answers as uncited summary sentences (DOC_CLAIM_UNCITED), and
# H14 fell back after its one repair. The controller renders the statements, as for any document answer.
DocumentReport: type[BaseModel] = create_model(
    "DocumentReport", __base__=_S,
    **{name: (f.annotation, f) for name, f in ModelReport.model_fields.items() if name != "summary"})  # type: ignore[call-overload]


def synthesis_schema(intent: str | None) -> type[BaseModel]:
    return DocumentReport if intent == "source_explanation" else ModelReport


def as_model_report(m: BaseModel | None) -> ModelReport | None:
    """A DocumentReport as the ModelReport the rest of the controller uses (with an empty summary)."""
    if m is None or isinstance(m, ModelReport):
        return m
    return ModelReport.model_validate({**m.model_dump(), "summary": []})


class MEdit(_S):
    target: str = Field(description="one of the items listed in the repair request, e.g. summary[3], headline, "
                                    "document_statements[0], possible_explanations[1], "
                                    "possible_explanations[1].what_would_test_it, numeric_claims[n8], citations[c2], "
                                    "published_findings[0], observation_evidence_ids[ev0001]")
    action: Literal["replace", "delete"]
    text: str | None = Field(description="replacement text for headline, summary[i], possible_explanations[i] (its "
                                         "statement) or possible_explanations[i].what_would_test_it; else null")
    statement: MDocStatement | None = Field(description="replacement for document_statements[i]; else null")
    claim: MClaim | None = Field(description="replacement for numeric_claims[<claim_id>]; else null")
    citation: MCitation | None = Field(description="replacement for citations[<citation_id>]; else null")


class RepairPatch(_S):
    edits: list[MEdit] = Field(description="exactly one edit (replace or delete) per listed item")
    new_numeric_claims: list[MClaim] = Field(description="claims for numbers your replacement text adds")
    new_citations: list[MCitation] = Field(description="citations your replacements add")


_WHERE_RE = re.compile(r"^(headline|summary\[\d+\]|possible_explanations\[\d+\](?:\.what_would_test_it)?|"
                       r"published_findings\[\d+\])(?=[:\s]|$)")
_ITEM_RE = re.compile(r"(summary|document_statements|possible_explanations|published_findings)\[(\d+)\]"
                      r"(\.what_would_test_it)?")


def resolve_statement_citation(ref: str, quote: str | None,
                               cites: list[Citation]) -> tuple[Citation | None, str]:
    """The report citation a document statement refers to, and how it was found.

    - 'exact': ``ref`` is a citation ID.
    - 'passage': ``ref`` is the passage (chunk) ID of exactly one citation, or of several of which exactly one is
      named by the statement's quote (the quote contains that citation's quote, or is part of it).
    - (None, 'ambiguous'): several citations of that passage, and the statement does not single one out.
    - (None, 'unknown'): neither a citation ID nor the passage of any citation.

    Unresolved statements stay uncited, and the validator rejects them. Resolution changes only which citation
    marker is shown: the quote is still checked verbatim against the same passage, and a paraphrase against its
    words. Held-out v4 W10: two statements cited the passage ID ``aemo_so_op_3705#p12c33``, while the draft's two
    citations of that passage were named ``…:supply`` and ``…:dt``."""
    from ..validation import _norm

    by_id = {c.citation_id: c for c in cites}
    if ref in by_id:
        return by_id[ref], "exact"
    cands = [c for c in cites if c.chunk_id == ref]
    if not cands:
        return None, "unknown"
    if len(cands) == 1:
        return cands[0], "passage"
    nq = _norm(quote or "")
    named = [c for c in cands if nq and _norm(c.quote) and (_norm(c.quote) in nq or nq in _norm(c.quote))]
    return (named[0], "passage") if len(named) == 1 else (None, "ambiguous")


def repair_targets(result: Any, m: ModelReport, origin: list[tuple[str, int]]) -> tuple[set[str], list[str]]:
    """The draft items each critical violation points at. ``origin`` maps rendered summary lines to their source
    (a document statement or a free summary line). Codes that name no item are returned as unmapped."""
    targets: set[str] = set()
    unmapped: list[str] = []
    claim_ids = {c.claim_id for c in m.numeric_claims}
    cite_ids = {c.citation_id for c in m.citations}
    for v in result.critical:
        d = v.detail
        mw = _WHERE_RE.match(d)
        if mw:
            t = mw.group(1)
            ms = re.fullmatch(r"summary\[(\d+)\]", t)
            if ms:
                i = int(ms.group(1))
                if i >= len(origin) or origin[i][0] == "controller":  # a controller-written line is no draft item
                    unmapped.append(v.code)
                    continue
                t = f"{origin[i][0]}[{origin[i][1]}]"
            targets.add(t)
            continue
        mf = re.match(r"finding (\d+):", d)
        if mf:
            targets.add(f"published_findings[{mf.group(1)}]")
            continue
        mt = re.match(r"([^\s:]+)", d)
        tok = mt.group(1) if mt else ""
        if tok in claim_ids:
            targets.add(f"numeric_claims[{tok}]")
            continue
        if tok in cite_ids:
            targets.add(f"citations[{tok}]")
            continue
        if re.fullmatch(r"ev\d{4}", tok):  # evidence-level (as-of, metric): the observation and claims that use it
            hit = [f"numeric_claims[{c.claim_id}]" for c in m.numeric_claims if c.evidence_id == tok]
            if tok in m.observation_evidence_ids:
                hit.append(f"observation_evidence_ids[{tok}]")
            if hit:
                targets.update(hit)
                continue
        unmapped.append(v.code)
    return targets, unmapped


def target_texts(m: ModelReport, targets: set[str]) -> dict[str, str]:
    """Current content of each item the repair may change, shown to the model."""
    out: dict[str, str] = {}
    for t in sorted(targets):
        mi = _ITEM_RE.fullmatch(t)
        if t == "headline":
            out[t] = m.headline
        elif mi:
            items = getattr(m, mi.group(1))
            i = int(mi.group(2))
            if i < len(items):
                it = items[i]
                out[t] = (it.what_would_test_it if mi.group(3) else it.statement) if mi.group(1) == "possible_explanations" \
                    else (it if isinstance(it, str) else json.dumps(it.model_dump(), ensure_ascii=False))
        elif t.startswith("numeric_claims["):
            c = next((c for c in m.numeric_claims if c.claim_id == t[15:-1]), None)
            out[t] = json.dumps(c.model_dump(), ensure_ascii=False) if c else ""
        elif t.startswith("citations["):
            c2 = next((c for c in m.citations if c.citation_id == t[10:-1]), None)
            out[t] = json.dumps(c2.model_dump(), ensure_ascii=False) if c2 else ""
        else:
            out[t] = t
    return out


def apply_patch(m: ModelReport, patch: RepairPatch, allowed: set[str]) -> tuple[ModelReport, list[str]]:
    """Apply a repair patch to the first draft. Only the failing items may change; every other item is carried over
    unchanged, so the one repair cannot break what already passed (L3 run 3, EV09: a full rewrite fixed four
    violations and introduced four new ones)."""
    d = m.model_dump()
    notes: list[str] = []
    drop: dict[str, set[int]] = {k: set() for k in ("summary", "document_statements", "possible_explanations",
                                                   "published_findings")}
    claims = {c["claim_id"]: c for c in d["numeric_claims"]}
    cites = {c["citation_id"]: c for c in d["citations"]}
    for e in patch.edits:
        if e.target not in allowed:
            notes.append(f"ignored an edit to {e.target}: only the failing items may change")
            continue
        mi = _ITEM_RE.fullmatch(e.target)
        if e.target == "headline":
            if e.action == "replace" and e.text:
                d["headline"] = e.text
            else:
                notes.append("the headline cannot be deleted; it was kept")
        elif mi:
            kind, i, test = mi.group(1), int(mi.group(2)), mi.group(3)
            if i >= len(d[kind]):
                notes.append(f"{e.target} does not exist")
            elif e.action == "delete":
                drop[kind].add(i)
            elif kind == "summary" and e.text is not None:
                d["summary"][i] = e.text
            elif kind == "document_statements" and e.statement is not None:
                d[kind][i] = e.statement.model_dump()
            elif kind == "possible_explanations" and e.text is not None:
                d[kind][i]["what_would_test_it" if test else "statement"] = e.text
            else:
                notes.append(f"the edit to {e.target} had no usable replacement; kept")
        elif e.target.startswith("numeric_claims["):
            cid = e.target[15:-1]
            if e.action == "delete":
                claims.pop(cid, None)
            elif e.claim is not None:
                claims[cid] = e.claim.model_dump()
        elif e.target.startswith("citations["):
            cid = e.target[10:-1]
            if e.action == "delete":
                cites.pop(cid, None)
            elif e.citation is not None:
                cites[cid] = e.citation.model_dump()
        elif e.target.startswith("observation_evidence_ids[") and e.action == "delete":
            d["observation_evidence_ids"] = [x for x in d["observation_evidence_ids"] if x != e.target[25:-1]]
        else:
            notes.append(f"the edit to {e.target} could not be applied")
    for kind, idxs in drop.items():
        d[kind] = [x for i, x in enumerate(d[kind]) if i not in idxs]
    for c in patch.new_numeric_claims:
        if c.claim_id in claims:
            notes.append(f"new claim {c.claim_id} reuses an existing id; not added")
        else:
            claims[c.claim_id] = c.model_dump()
    for c3 in patch.new_citations:
        if c3.citation_id in cites:
            notes.append(f"new citation {c3.citation_id} reuses an existing id; not added")
        else:
            cites[c3.citation_id] = c3.model_dump()
    d["numeric_claims"], d["citations"] = list(claims.values()), list(cites.values())
    return ModelReport.model_validate(d), notes


# ------------------------------------------------------------------------------------ transports
class Transport(Protocol):
    def create(self, **kwargs: Any) -> dict[str, Any]: ...


class OpenAITransport:
    """Thin adapter over the installed OpenAI SDK; returns plain dicts."""

    def __init__(self, timeout_s: float | None = None, client: Any = None) -> None:
        from openai import OpenAI

        # No SDK retries: a hidden retry is a second billed request the ledger never reserved (L3 run 3: a 60 s timeout
        # and one retry sent a synthesis request twice). Each attempt is reserved and settled by the controller.
        self.client = client or OpenAI(timeout=timeout_s or float(os.environ.get("NEM_AGENT_API_TIMEOUT_S", "300")),
                                       max_retries=0)

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
        if (c := budget.call_cost(self.model, u)) is not None:  # list price; cached input at the cached rate
            self.cost_usd = round((self.cost_usd or 0.0) + c, 6)

    def as_dict(self) -> dict[str, Any]:
        return {"model_calls": self.model_calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd, "cost_note": "list-price estimate (cached input at the cached rate)"
                if self.cost_usd is not None else "no price known for this model",
                "elapsed_s": round(time.monotonic() - self.started, 2)}


def _texts(resp: dict[str, Any]) -> str:
    out = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    out.append(c.get("text", ""))
    return "".join(out)


def compact_json(obj: Any, limit: int) -> tuple[str, int]:
    """Serialise a tool output within ``limit`` characters while keeping it valid JSON.

    Cutting the text (the previous behaviour) sent the model broken JSON: in a live run the forecast-runs output was
    112,364 characters. Instead the longest list is shortened, keeping its first and last items and replacing the
    middle with an explicit marker, until the output fits. Omitted values remain in the evidence registry.

    Text keeps its real characters (ensure_ascii=False): with ASCII escapes the model read "\\u2013" where the
    document has an en dash, and could not copy a quotation verbatim."""
    data = json.loads(json.dumps(obj, default=str))
    text = json.dumps(data, ensure_ascii=False)
    omitted = 0

    def lists(node: Any) -> list[list[Any]]:
        if isinstance(node, dict):
            return [x for v in node.values() for x in lists(v)]
        if isinstance(node, list):
            return [node] + [x for v in node for x in lists(v)]
        return []
    while len(text) > limit:
        cands = [lst for lst in lists(data) if len(lst) > 3]
        if not cands:
            break
        lst = max(cands, key=lambda x: len(json.dumps(x)))
        keep = max(1, len(lst) // 4)
        cut = len(lst) - 2 * keep
        prev = [x for x in lst if isinstance(x, dict) and "_omitted_items" in x]
        cut += sum(x["_omitted_items"] for x in prev)
        body = [x for x in lst if not (isinstance(x, dict) and "_omitted_items" in x)]
        lst[:] = body[:keep] + [{"_omitted_items": cut, "_note": "omitted to fit the model context"}] + body[-keep:]
        omitted = sum(x["_omitted_items"] for lst_ in lists(data) for x in lst_ if isinstance(x, dict)
                      and "_omitted_items" in x)
        text = json.dumps(data, ensure_ascii=False)
    if len(text) > limit:  # nothing left to shorten: say so rather than send broken JSON
        text = json.dumps({"status": "output_too_large", "chars": len(text),
                           "note": "ask for a narrower window or fewer items"})
    return text, omitted


def _forecast_comparison(recs: list[Any], mae_evidence_id: str) -> ForecastComparison | None:
    """Built from the compare_forecast_actual record the model names; every value is copied from the tool output."""
    for r in recs:
        v = r.view if r.name == "compare_forecast_actual" and r.status == "ok" else {}
        if (v.get("mae_mw") or {}).get("evidence_id") == mae_evidence_id:
            return ForecastComparison(
                status="ok", run_selector=v["run_selector"] + (f" ({v['min_lead_hours']} h)" if v.get("min_lead_hours")
                                                               else ""),
                as_of_utc=v.get("as_of_utc"), definition_check=v["definition_check"], n_pairs=v["n_pairs"],
                mae_mw=v["mae_mw"]["value"], mae_evidence_id=mae_evidence_id,
                mean_error_mw=v["mean_error_mw"]["value"], mean_error_evidence_id=v["mean_error_mw"]["evidence_id"],
                largest_abs_error=v.get("largest_abs_error"), note=f"{v['error_definition']}; {v['actuals_are']}.")
    return None


def _trace_tool_output(trace: Any, call_id: str, rec: Any, payload: str) -> None:
    """What the model was shown: the tool output (truncated) and, for retrieval, the ranked candidates."""
    extra: dict[str, Any] = {}
    view = rec.model_payload().get("result") or {}
    if rec.name == "retrieve_public_evidence" and isinstance(view, dict):
        extra["candidates"] = [{k: h.get(k) for k in ("chunk_id", "doc_type", "score", "event_region", "event_date",
                                                     "eligibility_reason")} for h in view.get("results", [])]
    trace.add("tool_output", rec.name, call_id=call_id, status=rec.status, chars=len(payload),
              output=payload[:6000], **extra)


def _trace_draft(trace: Any, stage: str, draft: BaseModel | None) -> None:
    """Keep the model's draft in the (local, redacted) trace so a rejected narrative can be inspected later."""
    if draft is not None:
        trace.add("model", f"{stage}:draft", report=draft.model_dump())


# How to fix each violation, sent with the repair turn (the validator's own wording says only what failed).
REPAIR_HINTS = {
    "NUMERIC_UNTRACKED": "Every number outside a quote must be a numeric_claim that cites the evidence_id holding it. "
                         "Otherwise delete the number: write clock times as HH:MM, name variables (e.g. WS50M) "
                         "instead of restating numbers in their names, and keep a document's numbers, voltages, "
                         "equipment and line names inside its quote (or leave them out of the sentence shown). A "
                         "quote is text inside double quotation marks (\"...\" or “...”); single quotes are not. "
                         "Spell out terms that begin with a digit (write 'five-minute pre-dispatch', not 5MPD).",
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
                                "capitalisation, from the retrieved passage, or drop the citation. Put quotes in "
                                "double quotation marks.",
    "CITATION_UNKNOWN_CHUNK": "Cite only chunk_ids returned by retrieve_public_evidence in this investigation.",
    "TIME_NOT_IN_EVIDENCE": "Copy clock times from a *_local or *_utc field of a tool output or the context, with the "
                            "zone as given; never convert or shift a time yourself. If no tool returned the time, "
                            "remove it.",
    "TIME_ZONE_MISSING": "Give every clock time its zone exactly as a tool returned it (e.g. '16:35 UTC' or "
                         "'2026-07-31 02:05 ACST'); a notice's 'HHMM hrs' is NEM time: use that notice's clock_times "
                         "(utc or local). If you cannot, remove the time.",
    "TIME_OF_DAY_UNVERIFIED": "Remove words such as morning, afternoon, evening or night, or state in the same sentence "
                              "the region-local time (from a *_local field) that shows it; a UTC time says nothing "
                              "about the time of day in the region.",
    "CLAIM_REGION_MISMATCH": "Only state numbers for the investigated region.",
    "QUOTE_NOT_IN_SOURCE": "Put only text copied exactly from the cited passage inside quotation marks; otherwise "
                           "remove the quotation marks and restate it, or delete it.",
    "MEASURE_SUBSTITUTED": "Answer with the measure the question names (see the context's requested_measures): total "
                           "demand is dispatch TOTALDEMAND (get_price_timeline), operational demand is get_actual_demand. "
                           "If the named measure was not returned, say so in missing_evidence instead of substituting.",
    "NOTICE_TIMING_OMITTED": "The question asks whether something a market notice reports explains the event. Add "
                             "one summary sentence that names the notice by a few words of its title (no [citation_id]) "
                             "and states its time with its zone and whether that is before, between or after the "
                             "event's intervals, copying the times and the relation from notice_timing; use no "
                             "causal wording.",
    "NOTICE_TIMING_CONTRADICTED": "The stated before/between/after (or the interval time) is wrong: copy the notice's "
                                  "time and its relation to the event from notice_timing (or compare it with the "
                                  "price timeline's first_interval_at_or_above_threshold and "
                                  "last_interval_at_or_above_threshold), or delete the comparison.",
    "NOTICE_TIMING_UNVERIFIED": "A notice time set against the event's intervals needs the price timeline for the whole "
                                "event window; call it, or compare the notice time only with a time a tool returned.",
    "NOTICE_TIME_ZONE_MISMATCH": "A notice's 'HHMM hrs' is NEM time (UTC+10): use the utc or local value in that "
                                 "notice's clock_times, with the zone as given.",
    "CLAIM_INTERVAL_MISMATCH": "Describe each number at its tool's resolution: a 5-minute value (dispatch RRP, "
                               "including the hourly samples of it) is not a half-hour value, and half-hour "
                               "operational demand is not a 5-minute value. Fix the label or delete the number.",
    "DOC_CLAIM_UNCITED": "In a document answer, write every sentence as a document_statement tied to the citation_id "
                         "of the passage it relies on (quote or close paraphrase); a document answer has no summary.",
    "DOC_CLAIM_UNSUPPORTED": "Restate only what the cited passage says, close to its wording, or quote it; drop claims "
                             "the passage does not make. Give each cited passage its own sentence: a sentence citing "
                             "two notices must be supported by each of them. In an event or forecast review, delete "
                             "a summary sentence that describes market notices: published_findings already shows "
                             "each notice verbatim.",
}


def _where_text(report: Any, detail: str) -> str | None:
    """The narrative item a violation points at (e.g. 'summary[4]'), so the repair can see the exact sentence."""
    m = re.match(r"(headline|summary|possible_explanations|published_findings)(?:\[(\d+)\])?(\.what_would_test_it)?",
                 detail)
    if report is None or not m:
        return None
    if m.group(1) == "headline":
        return str(report.headline)
    items = getattr(report, m.group(1), [])
    i = int(m.group(2) or 0)
    if i >= len(items):
        return None
    item = items[i]
    return str(getattr(item, "what_would_test_it" if m.group(3) else "statement", item))


def repair_message(result: Any, report: Any = None, targets: dict[str, str] | None = None) -> str:
    """The repair turn. With ``targets`` (a scoped repair) the model returns a RepairPatch that may change only the
    listed items; without, it returns the full corrected report."""
    crit = result.critical
    lines = []
    for v in crit[:20]:
        text = _where_text(report, v.detail)
        lines.append(f"- {v.code}: {v.detail}" + (f'\n    in: "{text[:240]}"' if text else ""))
    if len(crit) > 20:
        lines.append(f"- ... and {len(crit) - 20} more of the same kinds")
    hints = [f"- {c}: {REPAIR_HINTS[c]}" for c in sorted({v.code for v in crit}) if c in REPAIR_HINTS]
    if targets:
        head = ("The report failed independent validation. Return a RepairPatch with exactly one edit (replace or "
                "delete) for each item listed under 'Items you may change'; no other item can change.\n")
        items = "\nItems you may change (current content):\n" + "\n".join(f"- {k}: {v[:300]}" for k, v in targets.items())
    else:
        head = "The report failed independent validation. Fix ONLY these problems and return the full corrected JSON:\n"
        items = ""
    return (head + "\n".join(lines) + items + ("\nHow to fix them:\n" + "\n".join(hints) if hints else "") + "\n"
            + REPAIR_RULES)


# Stated with every repair: the one repair turn must not introduce a new violation.
REPAIR_RULES = ("While fixing: a quote is text inside double quotation marks (\"...\" or “...”) copied exactly from a "
                "passage; text copied without them counts as your own words, so its numbers must be registered claims. "
                "Do not add numbers, times or notice details that were not in the draft; deleting a sentence is an "
                "acceptable fix. Passage text belongs in a document_statements quote, never retyped in summary.")


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
        self._summary_origin: list[tuple[str, int]] = []  # rendered summary line -> its draft item

    # -- model call with bounds ------------------------------------------------------------------------------
    def _call(self, trace: Any, stage: str, **kwargs: Any) -> dict[str, Any]:
        if self.usage.model_calls >= config.MAX_MODEL_CALLS:
            raise BudgetExceeded(f"model call cap reached ({config.MAX_MODEL_CALLS})")
        if model_prices(self.model) is None:  # without a price the budget cannot be enforced: fail closed
            raise BudgetExceeded(f"no price known for model {self.model!r}; set NEM_AGENT_PRICE_INPUT_PER_MTOK and "
                                 "NEM_AGENT_PRICE_OUTPUT_PER_MTOK")
        session = float(os.environ.get("NEM_AGENT_SESSION_BUDGET_USD", "0.50"))
        if self.usage.cost_usd is not None and self.usage.cost_usd >= session:
            raise BudgetExceeded(f"session budget {session} USD reached")
        max_out = config.MAX_OUTPUT_TOKENS[stage]
        worst = budget.worst_case_cost(self.model, len(json.dumps(kwargs, default=str)), max_out)
        rid = budget.reserve(self.model, stage, worst)  # refuses when the task-wide cap could be exceeded
        t0 = time.monotonic()
        try:
            resp = self.client.create(model=self.model, store=False, max_output_tokens=max_out, **kwargs)
        except Exception as exc:
            # Only a request the provider rejected (HTTP 4xx) is known not to be billed. After a timeout, a connection
            # error or a 5xx it may have been processed, so it stays counted at its worst case.
            code = getattr(exc, "status_code", None)
            unbilled = isinstance(code, int) and 400 <= code < 500
            budget.settle(rid, 0.0 if unbilled else worst)
            trace.add("model", f"{stage}:error", error=type(exc).__name__, status_code=code,
                      settled_usd=0.0 if unbilled else worst, duration_ms=round((time.monotonic() - t0) * 1000, 1))
            raise
        cost = budget.call_cost(self.model, resp.get("usage"))
        budget.settle(rid, cost if cost is not None else worst, resp.get("usage"))
        self.usage.add(resp)
        calls = [{"call_id": i.get("call_id"), "name": i.get("name"), "arguments": i.get("arguments")}
                 for i in resp.get("output", []) if i.get("type") == "function_call"]
        trace.add("model", stage, model=self.model, response_id=resp.get("id"), function_calls=calls,
                  usage=resp.get("usage"), cost_usd=cost, max_output_tokens=max_out,
                  status=resp.get("status"), incomplete=resp.get("incomplete_details"),
                  duration_ms=round((time.monotonic() - t0) * 1000, 1))
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
                                              "clarification_reason": "missing_region_or_date",
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
        data_q = res.intent in ("market_event_review", "forecast_review")
        context: dict[str, Any] = {
            "question": res.request.question, "intent": res.intent, "region": res.region,
            "window_utc": [iso_utc(res.window[0]), iso_utc(res.window[1])] if res.window else None,
            "window_local": [local_str(res.window[0], res.region), local_str(res.window[1], res.region)]
            if res.window and res.region else None,
            "as_of_utc": iso_utc(res.as_of) if res.as_of else None,
            # a document question gets no event times: no tool returns them there, so they could not be cited
            # (L3 live, ADV02 repeated them from the context and failed the time check)
            "event_peak_interval_end_utc": res.event.peak_interval_end_utc if res.event and data_q else None,
            "event_peak_interval_end_local": local_str(parse_iso(res.event.peak_interval_end_utc), res.region)
            if res.event and res.region and data_q else None,
            "required_tools": list(pb.required), "optional_tools_max_2": list(pb.optional),
        }
        if res.event and res.region and data_q:  # computed here so the model never does time arithmetic
            hh = half_hour_end_for(parse_iso(res.event.peak_interval_end_utc))
            context["peak_half_hour_end_utc"] = iso_utc(hh)
            context["peak_half_hour_end_local"] = local_str(hh, res.region)
        measures = requested_measures(res.request.question)
        if measures:  # say which tool field holds each measure the question names (held-out H02, H03, H14)
            context["requested_measures"] = measures
        issued = forecast_issue_time(res.request.question)
        if issued is not None and res.region and self.d is not None:
            context["requested_forecast_run"] = self._run_issued_at(res.region, issued)
        if res.window and res.region and res.intent in ("forecast_review", "market_event_review"):
            lo, hi = forecast_focus(res)  # the same forecast-review scope the replay controller uses
            context["forecast_targets_utc"] = [iso_utc(lo), iso_utc(hi)]
            context["forecast_targets_local"] = [local_str(lo, res.region), local_str(hi, res.region)]
            context["forecast_note"] = ("A forecast review compares the 24 half-hours around the event peak: use "
                                        "forecast_targets_utc as target_start_utc/target_end_utc (forecast tools accept "
                                        "at most 24 h).")
        items: list[Any] = [{"role": "user", "content": "Investigation context (JSON):\n" +
                             json.dumps(context, indent=1, ensure_ascii=False)}]
        if res.intent == "source_explanation":
            items.append({"role": "user", "content": self._question_retrieval(res, trace)})
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
                    full = json.dumps(rec.model_payload(), default=str, ensure_ascii=False)
                    payload, omitted = compact_json(rec.model_payload(), MAX_TOOL_OUTPUT_CHARS)
                    _trace_tool_output(trace, c["call_id"], rec, payload)
                    if omitted:
                        trace.add("model", "tool_output_compacted", call_id=c["call_id"], chars=len(full),
                                  chars_sent=len(payload), items_omitted=omitted)
                    items.append({"type": "function_call_output", "call_id": c["call_id"], "output": payload})
                if calls:
                    continue
                missing = self.d.required_missing()
                if missing and not nudged:
                    nudged = True
                    items.append({"role": "user", "content": f"Required tools not yet called: {missing}. Call them now."})
                    continue
                break
            timing = self._notice_timing(res)
            if timing is not None:
                trace.add("model", "notice_timing", required=timing["required_in_summary"],
                          notices=[n["doc_id"] for n in timing["notices"]])
                items.append({"role": "user", "content": "Notice timing computed by the controller (JSON):\n" +
                              json.dumps(timing, indent=1, ensure_ascii=False)})
            items.append({"role": "user", "content": prompt("synthesis")})
            draft, raw = self._structured(trace, "synthesis", synthesis_schema(res.intent), prompt("system"), items)
            mrep = as_model_report(draft)
            _trace_draft(trace, "synthesis", mrep)
        except BudgetExceeded as exc:
            trace.add("model", "budget_exceeded", reason=str(exc))
            return self._build(res, None, extra_missing=[f"Live run stopped: {exc}"])
        report = self._build(res, mrep if isinstance(mrep, ModelReport) else None,
                             extra_missing=stopped + ([] if mrep else ["Model output did not match the report schema."]))
        # -- 4. one bounded repair turn driven by the independent validator
        from ..validation import validate

        first = validate(report, self.reg, as_of=res.as_of, window=res.window, records=self.d.records,
                         required_tools=pb.required, event_kind=res.kind)
        if first.critical and self.usage.model_calls < config.MAX_MODEL_CALLS:
            # scoped when every violation names a draft item: the model may change only those items
            targets, unmapped = (repair_targets(first, mrep, self._summary_origin) if isinstance(mrep, ModelReport)
                                 else (set(), ["no valid first draft"]))
            scoped = bool(targets) and not unmapped
            texts = target_texts(mrep, targets) if scoped and isinstance(mrep, ModelReport) else None
            items += [{"role": "assistant", "content": raw or ""},
                      {"role": "user", "content": repair_message(first, report, texts)}]
            mrep2: BaseModel | None = None
            try:
                if scoped and isinstance(mrep, ModelReport):
                    patch, _ = self._structured(trace, "repair", RepairPatch, prompt("system"), items)
                    if isinstance(patch, RepairPatch):
                        mrep2, notes = apply_patch(mrep, patch, targets)
                        trace.add("model", "repair:scoped", targets=sorted(targets), notes=notes,
                                  patch=patch.model_dump())
                else:
                    trace.add("model", "repair:full", unmapped_codes=sorted(set(unmapped)))
                    rewrite, _ = self._structured(trace, "repair", synthesis_schema(res.intent), prompt("system"), items)
                    mrep2 = as_model_report(rewrite)
                _trace_draft(trace, "repair", mrep2)
            except BudgetExceeded as exc:
                mrep2 = None
                trace.add("model", "budget_exceeded", reason=str(exc))
            if isinstance(mrep2, ModelReport):
                report = self._build(res, mrep2, extra_missing=stopped)
            report = report.model_copy(update={"validation": {"repair_attempted": True,
                                                              "repair_mode": "scoped" if scoped else "full",
                                                              "pre_repair_codes": sorted({v.code for v in first.critical}),
                                                              "pre_repair": first.as_dict()}})
        return report

    def _run_issued_at(self, region: str, issued: datetime) -> dict[str, Any]:
        """The forecast run a question names by its issue time, looked up by code (never an as-of cutoff): the run issued
        nearest that time, within 10 minutes ("issued at about 07:57Z" is the run issued 07:57:01Z)."""
        assert self.d is not None
        rows = self.d.store.query(
            "SELECT run_id, MIN(issued_at_utc) AS issued_at_utc FROM opdemand_forecast WHERE region=? AND "
            "issued_at_utc BETWEEN ? AND ? GROUP BY run_id", [region, issued - timedelta(minutes=10),
                                                               issued + timedelta(minutes=10)])
        best = min(rows, key=lambda r: abs(r["issued_at_utc"] - issued)) if rows else None
        return {"issued_at_utc_asked": iso_utc(issued),
                "issued_at_utc": iso_utc(best["issued_at_utc"]) if best else None,
                "run_id": best["run_id"] if best else None,
                "note": ("The question names a forecast by its issue time. It is not an as-of cutoff: actuals may be "
                         "used. Select this run with compare_forecast_actual(run_selector='run_id', run_id=<run_id>); "
                         "its pairs give POE10, POE50 and POE90, and where the actual falls against that range."
                         if best else "No forecast run issued within 10 minutes of that time is held; say so rather "
                         "than use another run.")}

    def _notice_timing(self, res: Resolution) -> dict[str, Any] | None:
        """Each retrieved market notice for the investigated region, with its clock times set against the event's
        threshold intervals and price extreme by code, so NEM-time 'HHMM hrs' is never compared with UTC by eye.
        Held-out H13 asked whether an outage in a notice caused the spike, cited the notice, and never said that its
        time (1100 hrs NEM time, 01:00Z) came after every high-price interval."""
        assert self.d is not None
        if res.intent != "market_event_review" or res.event is None or not res.region or not res.window or \
                not asks_if_notice_event_caused(res.request.question):
            return None  # only where the question makes the notice's timing decisive; other answers are unchanged
        region, (w0, w1) = res.region, res.window
        notices: dict[str, dict[str, Any]] = {}
        for r in self.d.records:
            if r.name != "retrieve_public_evidence" or r.status != "ok":
                continue
            for h in r.view.get("results", []):
                if h.get("doc_type") == "market_notice" and h.get("event_region") == region and h.get("clock_times"):
                    notices.setdefault(h["chunk_id"], h)
        thr = self.d.selection.analysis_threshold
        high = res.event.kind == "high_price"
        label = ("5-minute interval at or above the analysis threshold" if high
                 else "5-minute interval below the low-price threshold")
        ends = sorted({parse_iso(s["interval_end_utc"]) for r in self.d.records
                       if r.name == "get_price_timeline" and r.status == "ok" for s in r.data.get("series", [])
                       if (s["rrp"] >= float(thr["high_price_rrp_at_or_above"]) if high
                           else s["rrp"] < float(thr["low_price_rrp_below"]))})
        ends = [t for t in ends if w0 < t <= w1]
        peak = parse_iso(res.event.peak_interval_end_utc)

        def at(t: datetime) -> str:
            return f"interval ending {iso_utc(t)} = {local_str(t, region)}"

        def vs_intervals(t: datetime) -> str:
            if not ends:
                return f"not compared: get_price_timeline returned no {label} in the event window"
            if t <= ends[0] - timedelta(minutes=5):
                return f"before the first {label}: {at(ends[0])}"
            if t <= ends[-1]:
                # not "during": the intervals may form several episodes with gaps between them
                return f"between the first and last {label}s: first {at(ends[0])}; last {at(ends[-1])}"
            return f"after the last {label}: {at(ends[-1])}"

        def vs_peak(t: datetime) -> str:
            if t <= peak - timedelta(minutes=5):
                return f"before the price extreme: {at(peak)}"
            return f"within the price extreme's interval: {at(peak)}" if t <= peak else f"after the price extreme: {at(peak)}"

        out = [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "title": h.get("title"),
                "times": [{"notice_text": c["text"], "utc": c["utc"], "local": c.get("local"),
                           "relative_to_threshold_intervals": vs_intervals(parse_iso(c["utc"])),
                           "relative_to_price_extreme": vs_peak(parse_iso(c["utc"]))} for c in h["clock_times"]]}
               for h in notices.values()]
        return {"required_in_summary": True,
                "note": ("Computed by the controller from each notice's clock_times (NEM time, UTC+10) and "
                         "get_price_timeline. The question asks whether something a market notice reports explains "
                         "the event: state this timing in the summary."
                         + ("" if out else f" No retrieved market notice for {region} states a clock time.")),
                "notices": out}

    def _timing_answer(self, res: Resolution) -> str | None:
        """The direct answer that notice timing supports, for a question asking whether an incident a market notice
        reports explains the event, or None. Only the region's retrieved notices that name what the question names
        ("Directlink", "Hazelwood") count; a question naming nothing gets no sentence (W19's "reserve" notices include
        a cancellation, whose time is not the incident's). If their earliest stated time is after the price extreme,
        timing rules the incident out. Otherwise it does not, and no record shows whether it was behind the price.
        Live check 2026-09-29, F04: the answer listed the observations but never answered the question; H13 and W18
        stated the notice timing and stopped there."""
        if self.d is None or res.intent != "market_event_review" or res.event is None or not res.region or \
                not asks_if_notice_event_caused(res.request.question):
            return None
        q, region = res.request.question, res.region
        terms = [t for t in dict.fromkeys(re.findall(r"\b[A-Z][A-Za-z0-9]+(?:-[A-Z][A-Za-z0-9]+)*\b", q))
                 if t.lower() not in _NOT_NAMES]
        from ..retrieval.corpus import cancelled_notices

        hits: dict[str, tuple[str, dict[str, Any]]] = {}
        peak = parse_iso(res.event.peak_interval_end_utc)
        for r in self.d.records:
            if r.name != "retrieve_public_evidence" or r.status != "ok":
                continue
            for h in r.view.get("results", []):
                if h.get("doc_type") != "market_notice" or h.get("event_region") != region or not h.get("clock_times"):
                    continue
                gone = h.get("cancelled_by")
                if cancelled_notices(h.get("title") or "", h.get("text") or "") or \
                        (gone and parse_iso(gone["published_utc"]) <= peak):
                    continue  # a cancellation, or a notice cancelled before the extreme, is not the incident (I-1b)
                said = f"{h.get('title') or ''} {h.get('text') or ''}"
                term = next((t for t in terms if re.search(rf"\b{re.escape(t)}\b", said, re.I)), None)
                if term:
                    hits.setdefault(h["chunk_id"], (term, h))
        if not hits:
            return None  # nothing the question names is in a notice with a time: no sentence at all
        term, first = min(((t, c) for t, h in hits.values() for c in h["clock_times"]), key=lambda x: x[1]["utc"])
        t0 = parse_iso(first["utc"])
        when = f"{_zoned(first.get('local') or '')} ({first['utc']})".strip()
        extreme = f"the price extreme (interval ending {iso_utc(peak)} = {_zoned(local_str(peak, region))})"
        notice = f"the AEMO market notice that mentions {term}"
        if t0 > peak:
            return f"Timing rules this out: {notice} gives {when}, after {extreme}, so what it reports came later."
        where = "before" if t0 <= peak - timedelta(minutes=5) else "within the 5-minute interval of"
        # two sentences: the timing statement is checked by the validator, which skips any sentence with "whether"
        return (f"The records cannot settle this: {notice} gives {when}, {where} {extreme}. Its timing does not rule "
                "it out, and no retrieved record shows that it was, or was not, behind the price.")

    def _cancellation_answer(self, res: Resolution, cited: list[str]) -> str | None:
        """For an event review citing market notices that a later retrieved notice cancelled before the price extreme,
        one sentence saying so, with when each was issued and when it was cancelled; otherwise None. Held-out v4 W19
        cited three SA reserve forecasts for 29/07, cancelled on 27 and 28/07, and relied on them as active."""
        if res.intent != "market_event_review" or res.event is None or not res.region or not cited:
            return None
        from ..validation import cancelled_notice_chunks

        peak, region = parse_iso(res.event.peak_interval_end_utc), res.region
        gone = cancelled_notice_chunks(self.reg)

        def at(t: datetime) -> str:
            return f"{_zoned(local_str(t, region))} ({t:%Y-%m-%dT%H:%M}Z)"
        parts = []
        for cid in dict.fromkeys(cited):
            ch = self.reg.chunks.get(cid)
            if ch is None or cid not in gone or gone[cid][1] > peak or not ch.publication_date:
                continue
            kind = (ch.section or "market").lower()
            kind = kind if kind.endswith("notice") else f"{kind} notice"
            parts.append(f"the {kind} issued {at(parse_iso(ch.publication_date))} was cancelled by one issued "
                         f"{at(gone[cid][1])}")
        if not parts:
            return None
        return (f"AEMO later cancelled what these cited notices announced, each before the price extreme (interval "
                f"ending {iso_utc(peak)} = {_zoned(local_str(peak, region))}): " + "; ".join(parts) + ".")

    def _question_retrieval(self, res: Resolution, trace: Any) -> str:
        """For a document question, one retrieval with the question itself, issued by the controller, so the
        passage that answers it is available even when the model's own queries miss it (held-out H07, H14)."""
        assert self.d is not None
        args: dict[str, Any] = {"query": res.request.question[:300], "region": res.region, "top_k": 8,
                                "event_start_utc": iso_utc(res.window[0]) if res.window and res.region else None,
                                "event_end_utc": iso_utc(res.window[1]) if res.window and res.region else None,
                                "as_of_utc": None, "doc_types": None}
        rec = self.d.call("retrieve_public_evidence", args, call_id="controller_question_retrieval", origin="controller")
        payload, _ = compact_json(rec.model_payload(), MAX_TOOL_OUTPUT_CHARS)
        _trace_tool_output(trace, "controller_question_retrieval", rec, payload)
        return ("Passages retrieved by the controller for the question itself (untrusted data, like any tool output; "
                "cite them by chunk_id as usual, and call retrieve_public_evidence for anything else):\n" + payload)

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
        # Document sentences are written by the controller: a quote is shown in quotation marks only when it is
        # verbatim in the cited passage; anything else is shown as the model's own words, so every check applies.
        summary: list[str] = []
        self._summary_origin = []
        not_verbatim: list[str] = []
        resolved: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        if m is not None:
            from ..validation import _norm

            for j, s in enumerate(m.document_statements):
                q = (s.quote or "").strip().strip('“”"')
                cit, how = resolve_statement_citation(s.citation_id, q, cites)
                if how == "passage" and cit is not None:
                    resolved.append({"statement": j, "cited": s.citation_id, "citation_id": cit.citation_id})
                elif cit is None:
                    unresolved.append({"statement": j, "cited": s.citation_id, "reason": how})
                ref = cit.citation_id if cit is not None else s.citation_id  # an unresolved ID stays, and fails
                ch = self.reg.chunks.get(cit.chunk_id) if cit else None
                if q and ch is not None and _norm(q) in _norm(ch.text):
                    text = f"“{q}” [{ref}]"
                elif s.paraphrase or q:
                    if q and cit is not None:
                        not_verbatim.append(ref)
                    text = f"{(s.paraphrase or q).strip()} [{ref}]"
                else:
                    continue
                summary.append(text)
                self._summary_origin.append(("document_statements", j))
            for j, line in enumerate(m.summary):
                summary.append(line)
                self._summary_origin.append(("summary", j))
            status = self._cancellation_answer(res, [c.chunk_id for c in cites])
            if status is not None:  # written by the controller from the notices; the status of what is cited
                summary.insert(0, status)
                self._summary_origin.insert(0, ("controller", 0))
                if self.d is not None:
                    self.d.trace.add("model", "cancellation_answer", text=status)
            answer = self._timing_answer(res)
            if answer is not None:  # written by the controller from the notice's time; first, as the direct answer
                summary.insert(0, answer)
                self._summary_origin.insert(0, ("controller", 0))
                if self.d is not None:
                    self.d.trace.add("model", "timing_answer", text=answer)
        if not_verbatim and self.d is not None:
            self.d.trace.add("model", "statement_not_verbatim", citation_ids=not_verbatim)
        if resolved and self.d is not None:
            self.d.trace.add("model", "statement_citation_resolved", statements=resolved)
        if unresolved and self.d is not None:
            self.d.trace.add("model", "statement_citation_unresolved", statements=unresolved)
        scope: list[SearchScope] = []
        for r in recs:
            if r.name != "retrieve_public_evidence" or r.status == "blocked":
                continue
            v = r.view or {}
            filt = v.get("filters") or {}
            ss = v.get("search_scope")
            mn = ("not requested" if "search_scope" in v and ss is None else
                  f"searched: {ss['outcome']}" if ss and ss["searched"] else
                  f"not searched: {ss['reason']}" if ss else f"not searched: {r.status}")
            scope.append(SearchScope(call_id=r.call_id, query=str(v.get("query") or (r.args or {}).get("query") or ""),
                                     region=filt.get("region"),
                                     event_window_utc=list(filt.get("event_window") or [None, None]),
                                     as_of_utc=filt.get("as_of_utc"), document_types=filt.get("doc_types"),
                                     results=int(v.get("n_results") or 0), market_notices=mn))
        fcomp = None
        if m is not None and m.forecast_mae_evidence_id:
            fcomp = _forecast_comparison(recs, m.forecast_mae_evidence_id)
            if fcomp is None:
                missing.append(f"model referenced forecast MAE evidence {m.forecast_mae_evidence_id}, which no "
                               "compare_forecast_actual call returned")
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
            summary=summary, observations=obs, search_scope=scope,
            numeric_claims=[NumericClaim(**c.model_dump()) for c in m.numeric_claims] if m else [],
            possible_explanations=[Hypothesis(statement=h.statement, supporting_evidence_ids=h.supporting_evidence_ids,
                                              what_would_test_it=h.what_would_test_it) for h in m.possible_explanations] if m else [],
            published_findings=findings,
            citations=cites, uncertainties=m.uncertainties if m else [], forecast_comparison=fcomp,
            missing_evidence=list(dict.fromkeys((m.missing_evidence if m else []) + missing)),
            source_manifest={"data_version": self.versions.data, "corpus_version": self.versions.corpus,
                             "model": self.model, "usage": self.usage.as_dict(), "transcript": self.transcript},
            status=status if status != "needs_clarification" else "needs_clarification",
            trace_id=self.d.trace.trace_id if self.d else "n/a", versions=self.versions,
            generator=f"live-model:{self.model}")
