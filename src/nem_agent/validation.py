"""Independent validation of an `InvestigationReport` against the per-request evidence registry (Gate G5).

Nothing here trusts the controller or the model. Checks (all deterministic):

* numeric traceability — every number in narrative text is a registered numeric claim; every claim resolves to
  an evidence item with the same unit and a value within the declared rounding;
* observations — value/unit/source rows equal the registered evidence;
* citations — the chunk was retrieved (and eligible) in this request, metadata matches, and the quotation is an
  exact substring of the chunk text; published findings must cite an event-specific document for the same region
  and window and quote it verbatim;
* time — in an as-of view, no referenced evidence or cited document became available after the cutoff, and no
  retrospective context is used;
* metric compatibility — forecast errors derive only from operational-demand forecast/actual rows;
* language — no causal assertions outside hedged hypotheses; no echo of instruction-like retrieved text;
* status honesty — an "answered" report must carry evidence, and required tools must have run.

Semantic support beyond these rules is not claimed: a matching quote proves the text exists, not that it proves
the claim. Findings are therefore restricted to verbatim quotation of event-matching documents.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .evidence import EvidenceRegistry
from .report import InvestigationReport
from .retrieval.corpus import INJECTION_RE
from .timeutil import NEM_TZ, parse_iso

CAUSAL_RE = re.compile(r"\b(caused|causes|causing|cause of|due to|because of|led to|leads to|resulted in|result of|"
                       r"drove|driven by|triggered|responsible for|was the reason|explains why)\b", re.I)
HEDGE_RE = re.compile(r"\b(may|might|could|possibly|potentially|perhaps|cannot be tested|not established)\b", re.I)
OVERCONFIDENT_RE = re.compile(r"\b(definitely|certainly|clearly caused|proves?|confirmed that)\b", re.I)
QUOTED_RE = re.compile(r"“[^”]*”|\"[^\"]*\"")
IGNORE_RES = [re.compile(p) for p in (
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?",
    r"\b\d{4}/\d{2}/\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?",
    r"\b(?:0[1-9]|[12]\d|3[01])/(?:0[1-9]|1[0-2])/20\d{2}\b",  # DD/MM/YYYY, as AEMO notices write dates
    r"\bUTC[+-]\d{2,4}(?::\d{2})?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
    r"\b(?:NSW|QLD|SA|TAS|VIC)1\b",
    r"\bPOE ?\d{2}\b",
    r"\b\d+(?:\.\d+)?-(?:minute|min|hour|hr|day|week)s?\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2}\b",
    r"\bSO_OP_\d+\b",
    r"\b(?:s\d{2}|ev\d{4}|c\d{3}|tr-[0-9a-f]+)\b",
    r"\b[A-Z][A-Z0-9_]*\d[A-Z0-9_]*\b",
    r"\b[a-z]+[0-9]+[a-z0-9]*\b",
)]
NUM_RE = re.compile(r"(?<![\w.])[-+−]?\$?\d[\d,]*(?:\.\d+)?")
UNIT_ALIASES = {"$/mwh": "$/MWh", "mw": "MW", "%": "%", "intervals": "intervals", "\u00b0c": "C"}  # degree sign


@dataclass
class Violation:
    code: str
    severity: str  # critical | warning
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail[:500]}


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    numbers_checked: int = 0
    claims_checked: int = 0
    citations_checked: int = 0

    @property
    def critical(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "critical"]

    def as_dict(self) -> dict[str, Any]:
        return {"passed": not self.critical, "n_critical": len(self.critical),
                "n_warnings": sum(v.severity == "warning" for v in self.violations),
                "violations": [v.as_dict() for v in self.violations], "checks_run": self.checks_run,
                "numbers_checked": self.numbers_checked, "claims_checked": self.claims_checked,
                "citations_checked": self.citations_checked}


OPDEM_ROW_PREFIXES = ("OPDEM_FORECAST_HH:", "OPDEM_ACTUAL_HH:", "OPDEM_ACTUAL_DAILY:")


def metric_compatible(ev: Any) -> bool:
    """Forecast errors may only derive from operational-demand forecast/actual rows."""
    if ev.metric in ("forecast_error_mw", "forecast_error_pct"):
        return all(r.startswith(OPDEM_ROW_PREFIXES) for r in ev.source_row_ids)
    return True


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip()


def _unit(u: str) -> str:
    return UNIT_ALIASES.get(u.strip().lower(), u.strip())


def narrative_numbers(text: str, ids: frozenset[str] = frozenset()) -> list[float]:
    """Numbers stated in ``text`` outside quotations, dates, times and identifiers.

    ``ids`` are identifiers issued by the system in this request (retrieved chunk ids such as
    ``market_notice_144692#0``); only exact matches are removed, so a model cannot hide a number by calling it an id.
    """
    t = QUOTED_RE.sub(" ", text)
    for i in sorted(ids, key=len, reverse=True):
        t = t.replace(i, " ")
    t = t.replace("\u2010", "-").replace("\u2011", "-")  # U+2010/U+2011 hyphens: same duration label as "5-minute"
    for pat in IGNORE_RES:
        t = pat.sub(" ", t)
    out = []
    for m in NUM_RE.finditer(t):
        s = m.group(0).replace("−", "-").replace("$", "").replace(",", "")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def _narratives(r: InvestigationReport) -> list[tuple[str, str]]:
    out = [("headline", r.headline)] + [(f"summary[{i}]", s) for i, s in enumerate(r.summary)]
    out += [(f"possible_explanations[{i}]", h.statement) for i, h in enumerate(r.possible_explanations)]
    out += [(f"published_findings[{i}]", f.statement) for i, f in enumerate(r.published_findings)]
    if r.forecast_comparison:
        out.append(("forecast_comparison.note", r.forecast_comparison.note))
    return out


def validate(report: InvestigationReport, registry: EvidenceRegistry, *, as_of: datetime | None = None,
             window: tuple[datetime, datetime] | None = None, records: list[Any] | None = None,
             required_tools: tuple[str, ...] = ()) -> ValidationResult:
    res = ValidationResult()
    V = res.violations
    as_of = as_of or (parse_iso(report.as_of) if report.as_of else None)

    # -- numeric claims -> evidence
    res.checks_run.append("numeric_claims")
    for c in report.numeric_claims:
        res.claims_checked += 1
        ev = registry.get(c.evidence_id)
        if ev is None or ev.value is None:
            V.append(Violation("CLAIM_EVIDENCE_MISSING", "critical", f"{c.claim_id} cites unknown evidence {c.evidence_id}"))
            continue
        if _unit(c.unit) != _unit(ev.unit):
            V.append(Violation("CLAIM_UNIT_MISMATCH", "critical", f"{c.claim_id}: unit {c.unit!r} vs evidence {ev.unit!r}"))
        if abs(float(c.value) - float(ev.value)) > max(c.rounding, 1e-9) + 1e-9:
            V.append(Violation("CLAIM_VALUE_MISMATCH", "critical",
                               f"{c.claim_id}: claimed {c.value} {c.unit} but {c.evidence_id} = {ev.value} {ev.unit}"))

    # -- every number in narrative text must be a claim
    res.checks_run.append("narrative_numbers")
    claim_vals = [(float(c.value), c.rounding) for c in report.numeric_claims]
    chunk_ids = frozenset(registry.chunks)
    for where, text in _narratives(report):
        for n in narrative_numbers(text, chunk_ids):
            res.numbers_checked += 1
            if not any(abs(n - v) <= tol + 1e-9 or abs(abs(n) - abs(v)) <= tol + 1e-9 for v, tol in claim_vals):
                V.append(Violation("NUMERIC_UNTRACKED", "critical", f"{where}: number {n:g} is not a registered claim"))

    # -- observations
    res.checks_run.append("observations")
    for o in report.observations:
        ev = registry.get(o.evidence_id)
        if ev is None or ev.value is None:
            V.append(Violation("OBS_EVIDENCE_MISSING", "critical", f"observation {o.metric} cites {o.evidence_id}"))
            continue
        if abs(o.value - float(ev.value)) > 1e-6 or _unit(o.unit) != _unit(ev.unit):
            V.append(Violation("OBS_MISMATCH", "critical", f"{o.evidence_id}: {o.value} {o.unit} vs {ev.value} {ev.unit}"))
        if ev.source_row_ids and not set(o.source_row_ids) <= set(ev.source_row_ids):
            V.append(Violation("OBS_SOURCE_MISMATCH", "critical", f"{o.evidence_id}: source rows not from the evidence"))

    # -- citations
    res.checks_run.append("citations")
    cites = {c.citation_id: c for c in report.citations}
    for cit in report.citations:
        res.citations_checked += 1
        ch = registry.chunks.get(cit.chunk_id)
        if ch is None:
            V.append(Violation("CITATION_UNKNOWN_CHUNK", "critical", f"{cit.citation_id}: chunk {cit.chunk_id} was not retrieved"))
            continue
        if not ch.eligible:
            V.append(Violation("CITATION_INELIGIBLE", "critical", f"{cit.citation_id}: {ch.eligibility_reason}"))
        if ch.url != cit.url or ch.doc_id != cit.doc_id:
            V.append(Violation("CITATION_METADATA_MISMATCH", "critical", f"{cit.citation_id}: url/doc_id differ from chunk"))
        if len(_norm(cit.quote)) < 10:
            V.append(Violation("CITATION_QUOTE_TOO_SHORT", "critical", f"{cit.citation_id}: quotation under 10 characters"))
        if _norm(cit.quote) not in _norm(ch.text):
            V.append(Violation("CITATION_QUOTE_NOT_FOUND", "critical", f"{cit.citation_id}: quotation is not in {cit.chunk_id}"))
        if as_of is not None and (not ch.publication_date or parse_iso(ch.publication_date) > as_of):
            V.append(Violation("ASOF_LEAK_DOCUMENT", "critical",
                               f"{cit.citation_id}: {cit.doc_id} published {ch.publication_date} after as_of {as_of.isoformat()}"))
        if INJECTION_RE.search(cit.quote):
            V.append(Violation("INJECTION_QUOTED_AS_EVIDENCE", "critical", f"{cit.citation_id}: quotes instruction-like text"))

    # -- published findings: event-specific, same region/window, verbatim quote
    res.checks_run.append("published_findings")
    for i, f in enumerate(report.published_findings):
        quoted = [q.strip("“”\"") for q in QUOTED_RE.findall(f.statement)]
        if not any(_norm(q) for q in quoted):  # without a quotation nothing below can check it is verbatim
            V.append(Violation("FINDING_NOT_QUOTED", "critical", f"finding {i}: states the document without quoting it"))
        for cid in f.citation_ids:
            fcit = cites.get(cid)
            if fcit is None:
                V.append(Violation("FINDING_CITATION_MISSING", "critical", f"finding {i}: citation {cid} not in report"))
                continue
            ch = registry.chunks.get(fcit.chunk_id)
            if ch is None:
                continue
            if ch.doc_type not in ("market_notice", "event_report"):
                V.append(Violation("FINDING_NOT_EVENT_SPECIFIC", "critical",
                                   f"finding {i}: {ch.doc_type} document cannot be a published finding about the event"))
            if report.region and ch.event_region != report.region:
                V.append(Violation("FINDING_WRONG_REGION", "critical", f"finding {i}: document region {ch.event_region}"))
            if window and ch.event_date:
                d = datetime.fromisoformat(ch.event_date).date()
                lo = (window[0].astimezone(NEM_TZ) - timedelta(days=1)).date()
                hi = (window[1].astimezone(NEM_TZ) + timedelta(days=1)).date()
                if not lo <= d <= hi:
                    V.append(Violation("FINDING_WRONG_DATE", "critical", f"finding {i}: document dated {ch.event_date}"))
            if quoted and not all(_norm(q) in _norm(ch.text) for q in quoted):
                V.append(Violation("FINDING_QUOTE_MISMATCH", "critical", f"finding {i}: quoted text differs from the source"))

    # -- as-of leakage of numeric evidence
    if as_of is not None:
        res.checks_run.append("as_of")
        ids = {c.evidence_id for c in report.numeric_claims} | {o.evidence_id for o in report.observations}
        for eid in ids:
            ev = registry.get(eid)
            if ev is None:
                continue
            if ev.evidence_class == "retrospective_context":
                V.append(Violation("ASOF_LEAK_RETROSPECTIVE", "critical",
                                   f"{eid}: retrospective weather used in an as-of view"))
            elif ev.available_at_utc and parse_iso(ev.available_at_utc) > as_of:
                V.append(Violation("ASOF_LEAK", "critical",
                                   f"{eid} ({ev.metric}) available {ev.available_at_utc} after as_of {as_of.isoformat()}"))

    # -- metric compatibility for forecast errors (evidence the report actually references)
    res.checks_run.append("metric_compatibility")
    referenced = ({c.evidence_id for c in report.numeric_claims} | {o.evidence_id for o in report.observations} |
                  ({report.forecast_comparison.mae_evidence_id, report.forecast_comparison.mean_error_evidence_id}
                   if report.forecast_comparison else set()))
    for eid in sorted(e for e in referenced if e):
        ev = registry.get(eid)
        if ev is not None and not metric_compatible(ev):
            V.append(Violation("METRIC_INCOMPATIBLE", "critical",
                               f"{eid} ({ev.metric}) derived from non-operational-demand rows {ev.source_row_ids[:2]}"))
    for o in report.observations:
        if o.metric.startswith("forecast_error") and "totaldemand" in o.label.lower():
            V.append(Violation("METRIC_INCOMPATIBLE", "critical", f"{o.evidence_id}: forecast error labelled with TOTALDEMAND"))

    # -- language: causality, hedging, injection echo
    res.checks_run.append("language")
    for where, text in _narratives(report):
        bare = QUOTED_RE.sub(" ", text)
        if where.startswith("possible_explanations"):
            if CAUSAL_RE.search(bare) and not HEDGE_RE.search(bare):
                V.append(Violation("HYPOTHESIS_UNHEDGED", "critical", f"{where}: causal wording without hedging"))
            if not HEDGE_RE.search(bare):
                V.append(Violation("HYPOTHESIS_UNHEDGED", "critical", f"{where}: a hypothesis must be hedged"))
            if OVERCONFIDENT_RE.search(bare):
                V.append(Violation("HYPOTHESIS_OVERCONFIDENT", "critical", f"{where}: overconfident wording"))
        elif (m_causal := CAUSAL_RE.search(bare)) is not None:
            V.append(Violation("UNSUPPORTED_CAUSALITY", "critical",
                               f"{where}: causal claim '{m_causal.group(0)}' outside a hedged hypothesis"))
        if INJECTION_RE.search(bare):
            V.append(Violation("INJECTION_ECHO", "critical", f"{where}: contains instruction-like text"))
    for h in report.possible_explanations:
        for eid in h.supporting_evidence_ids:
            if registry.get(eid) is None:
                V.append(Violation("HYPOTHESIS_EVIDENCE_MISSING", "critical", f"hypothesis cites unknown {eid}"))

    # -- status honesty
    res.checks_run.append("status")
    if report.status == "answered" and not report.observations and not report.citations:
        V.append(Violation("EMPTY_ANSWER", "critical", "status 'answered' without observations or citations"))
    if records is not None and required_tools and report.status == "answered":
        ran = {r.name for r in records if r.status not in ("blocked",)}
        miss = [t for t in required_tools if t not in ran]
        if miss:
            V.append(Violation("STATUS_OVERCLAIMS", "critical", f"required tools not run: {miss}"))
    if any(ch.instruction_like for ch in registry.chunks.values()):
        V.append(Violation("INSTRUCTION_LIKE_TEXT_RETRIEVED", "warning",
                           "retrieved text contained instruction-like phrases; treated as data only"))
    return res


def facts_only(report: InvestigationReport, registry: EvidenceRegistry, result: ValidationResult,
               as_of: datetime | None) -> InvestigationReport:
    """Safe fallback after failed validation: keep only independently valid observations, no narrative."""
    good_obs = []
    for o in report.observations:
        ev = registry.get(o.evidence_id)
        if ev is None or ev.value is None or abs(o.value - float(ev.value)) > 1e-6 or not metric_compatible(ev):
            continue
        if as_of is not None and (ev.evidence_class == "retrospective_context" or
                                  (ev.available_at_utc and parse_iso(ev.available_at_utc) > as_of)):
            continue
        good_obs.append(o)
    codes = sorted({v.code for v in result.critical})
    return report.model_copy(update={
        "headline": ("Validated facts only: the generated narrative failed independent validation "
                     f"({', '.join(codes)}). Observations below are tool values with source rows."),
        "summary": [], "possible_explanations": [], "published_findings": [], "citations": [],
        "numeric_claims": [], "forecast_comparison": None, "observations": good_obs,
        "uncertainties": [*report.uncertainties, "Narrative withheld because it failed validation."],
        "status": "answered_with_caveats" if good_obs else "abstained",
    })


def validate_and_finalize(report: InvestigationReport, registry: EvidenceRegistry, records: list[Any], res: Any,
                          trace: Any) -> InvestigationReport:
    from .agent.playbook import PLAYBOOKS

    window = res.window if res is not None else None
    as_of = res.as_of if res is not None else None
    req = PLAYBOOKS[res.intent].required if res is not None and res.intent else ()
    first = validate(report, registry, as_of=as_of, window=window, records=records, required_tools=req)
    info: dict[str, Any] = {"initial": first.as_dict(), "fallback_applied": False,
                            "repair_attempted": bool(report.validation.get("repair_attempted"))}
    final = report
    if first.critical:
        final = facts_only(report, registry, first, as_of)
        second = validate(final, registry, as_of=as_of, window=window, records=records, required_tools=req)
        info.update(fallback_applied=True, after_fallback=second.as_dict())
    info["passed"] = not (first.critical and info.get("after_fallback", {}).get("n_critical", 1))
    info["final_passed"] = (not first.critical) or info.get("after_fallback", {}).get("n_critical", 1) == 0
    final = final.model_copy(update={"validation": {**report.validation, **info}})
    trace.add("validate", "report", passed=not first.critical, n_critical=len(first.critical),
              codes=sorted({v.code for v in first.violations}), fallback=info["fallback_applied"])
    return final
