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
from datetime import date
from importlib import resources
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
                if i >= len(origin):
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
    "CLAIM_INTERVAL_MISMATCH": "Describe each number at its tool's resolution: a 5-minute value (dispatch RRP, "
                               "including the hourly samples of it) is not a half-hour value, and half-hour "
                               "operational demand is not a 5-minute value. Fix the label or delete the number.",
    "DOC_CLAIM_UNCITED": "In a document answer, end every summary sentence with the [citation_id] of the passage it "
                         "relies on.",
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
        context = {
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
        if res.window and res.region and res.intent in ("forecast_review", "market_event_review"):
            lo, hi = forecast_focus(res)  # the same forecast-review scope the replay controller uses
            context["forecast_targets_utc"] = [iso_utc(lo), iso_utc(hi)]
            context["forecast_targets_local"] = [local_str(lo, res.region), local_str(hi, res.region)]
            context["forecast_note"] = ("A forecast review compares the 24 half-hours around the event peak: use "
                                        "forecast_targets_utc as target_start_utc/target_end_utc (forecast tools accept "
                                        "at most 24 h).")
        items: list[Any] = [{"role": "user", "content": "Investigation context (JSON):\n" +
                             json.dumps(context, indent=1, ensure_ascii=False)}]
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
                    mrep2, _ = self._structured(trace, "repair", ModelReport, prompt("system"), items)
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
        if m is not None:
            from ..validation import _norm

            for j, s in enumerate(m.document_statements):
                cit = by_id.get(s.citation_id)
                ch = self.reg.chunks.get(cit.chunk_id) if cit else None
                q = (s.quote or "").strip().strip('“”"')
                if q and ch is not None and _norm(q) in _norm(ch.text):
                    text = f"“{q}” [{s.citation_id}]"
                elif s.paraphrase or q:
                    if q:
                        not_verbatim.append(s.citation_id)
                    text = f"{(s.paraphrase or q).strip()} [{s.citation_id}]"
                else:
                    continue
                summary.append(text)
                self._summary_origin.append(("document_statements", j))
            for j, line in enumerate(m.summary):
                summary.append(line)
                self._summary_origin.append(("summary", j))
        if not_verbatim and self.d is not None:
            self.d.trace.add("model", "statement_not_verbatim", citation_ids=not_verbatim)
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
