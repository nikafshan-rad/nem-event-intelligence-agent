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

import contextlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .evidence import EvidenceRegistry
from .report import InvestigationReport
from .retrieval.corpus import INJECTION_RE
from .timeutil import NEM_TZ, REGION_TZ, parse_iso, region_zone

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
    # hyphenated upper-case identifiers (e.g. constraint set S-DVBL_BC-2CP): names, like the pattern above, not numbers
    r"\b[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+\b",
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


def _hypothesis_tests(r: InvestigationReport) -> list[tuple[str, str]]:
    return [(f"possible_explanations[{i}].what_would_test_it", h.what_would_test_it)
            for i, h in enumerate(r.possible_explanations)]


def _narratives(r: InvestigationReport) -> list[tuple[str, str]]:
    out = [("headline", r.headline)] + [(f"summary[{i}]", s) for i, s in enumerate(r.summary)]
    out += [(f"possible_explanations[{i}]", h.statement) for i, h in enumerate(r.possible_explanations)]
    out += [(f"published_findings[{i}]", f.statement) for i, f in enumerate(r.published_findings)]
    if r.forecast_comparison:
        out.append(("forecast_comparison.note", r.forecast_comparison.note))
    return out


ZONE_OFFSET_MIN = {"UTC": 0, "Z": 0, "AEST": 600, "AEDT": 660, "ACST": 570, "ACDT": 630, "AWST": 480, "NEM": 600}
DATETIME_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?\s*(UTC|Z|AEST|AEDT|ACST|ACDT|AWST|NEM)\b")
SENTENCE_RE = re.compile(r"(?<=[.;!?])\s+")
ISO_Z_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z\b")
_CLOCK = r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\b"
_ZONE = r"(UTC(?:[+-]\d{1,2}(?::?\d{2})?)?|Z|AEST|AEDT|ACST|ACDT|AWST|NEM)\b"
# a clock time, optionally a range ("11:15–11:25", "between 15:00 and 18:00"), optionally followed by its zone
CLOCK_RE = re.compile(_CLOCK + r"(?:\s*(?:–|—|-|to|and|until)\s*" + _CLOCK + r")?(?:\s*" + _ZONE + r")?")
PAREN_OFFSET_RE = re.compile(r"\(UTC[+-]\d{1,2}:?\d{0,2}\)")
PART_OF_DAY = {"morning": (5, 12), "midday": (11, 14), "noon": (11, 14), "afternoon": (12, 18), "evening": (17, 22),
               "overnight": (20, 7), "night": (20, 6), "dawn": (4, 7), "dusk": (17, 20)}
PART_OF_DAY_RE = re.compile(r"\b(" + "|".join(PART_OF_DAY) + r")s?\b", re.I)


def _zone_offset(zone: str) -> int:
    """Minutes east of UTC for a zone label (UTC, Z, AEST ... or an explicit UTC+10 / UTC+0930)."""
    m = re.fullmatch(r"UTC([+-])(\d{1,2})(?::?(\d{2}))?", zone)
    if m:
        return (1 if m[1] == "+" else -1) * (int(m[2]) * 60 + int(m[3] or 0))
    return ZONE_OFFSET_MIN[zone]


def _in_band(hour: int, lo: int, hi: int) -> bool:
    return lo <= hour < hi if lo < hi else (hour >= lo or hour < hi)


_DASH = "[-\u2010\u2011\u2012\u2013 ]?"
DURATION_RES = ((30, re.compile(rf"\bhalf{_DASH}hour|\b30{_DASH}min", re.I)),
                (5, re.compile(rf"\b(?:5|five){_DASH}min", re.I)))


def _durations(text: str) -> set[int]:
    """Interval lengths (minutes) a text names: 'half-hour'/'30-minute' and '5-minute'."""
    return {m for m, rx in DURATION_RES if rx.search(text)}
CITE_RE = re.compile(r"\[([A-Za-z0-9_#.\-]+)\]")
WORD_RE = re.compile(r"[a-z][a-z0-9]+")
SUPPORT_STOP = {"the", "and", "for", "that", "this", "with", "from", "which", "are", "was", "were", "has", "have",
                "its", "their", "into", "than", "then", "also", "such", "any", "all", "not", "can", "may", "might",
                "could", "aemo", "says", "said", "states", "stated", "according", "defines", "defined", "definition",
                "document", "passage", "text", "retrieved", "notice", "notices", "market", "reported", "published"}
SUPPORT_MIN = 0.6  # share of a cited sentence's content words that must appear in the cited passage


def _known_instants(registry: EvidenceRegistry, records: list[Any] | None, report: InvestigationReport,
                    window: tuple[datetime, datetime] | None) -> set[datetime]:
    """Every instant the tools or the request produced: a narrative time must be one of these."""
    out: set[datetime] = set()

    def add(v: Any) -> None:
        with contextlib.suppress(ValueError, TypeError):
            out.add(parse_iso(str(v)).replace(second=0, microsecond=0))
    for ev in registry.items.values():
        for v in (ev.valid_at_utc, ev.published_at_utc, ev.available_at_utc):
            if v:
                add(v)
                if v == ev.valid_at_utc and ev.interval_minutes:
                    add(parse_iso(v) - timedelta(minutes=ev.interval_minutes))  # interval start
    for r in records or []:
        for m in ISO_Z_RE.finditer(repr(getattr(r, "view", "")) + repr(getattr(r, "args", ""))):
            add(m.group(0))
    for v in (report.as_of, *(window or ()), *((report.event_window.start_utc, report.event_window.end_utc)
                                               if report.event_window else ())):
        if v:
            add(v.isoformat() if isinstance(v, datetime) else v)
    return out


def _stems(text: str) -> list[str]:
    return [w[:5] for w in WORD_RE.findall(text.lower()) if len(w) > 2 and w not in SUPPORT_STOP]


def support(sentence: str, passage: str) -> float:
    """Share of the sentence's content words (5-letter stems) found in the passage: a lexical, not semantic, test."""
    words = _stems(QUOTED_RE.sub(" ", CITE_RE.sub(" ", sentence)))
    if not words:
        return 1.0
    have = set(_stems(passage))
    return sum(w in have for w in words) / len(words)


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
        if report.region and ev.region and ev.region != report.region:
            V.append(Violation("CLAIM_REGION_MISMATCH", "critical",
                               f"{c.claim_id}: {c.evidence_id} is for {ev.region}, the report is about {report.region}"))
        named = _durations(c.text)
        if named and ev.interval_minutes and ev.interval_minutes not in named:
            V.append(Violation("CLAIM_INTERVAL_MISMATCH", "critical",
                               f"{c.claim_id}: labelled {'/'.join(f'{m}-minute' for m in sorted(named))} but "
                               f"{c.evidence_id} is a {ev.interval_minutes}-minute value"))

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

    # -- times written in the narrative: a time stated with a traced number must be that evidence's time, and every
    #    time must be an instant the tools or the request produced (times without a date are not checked)
    res.checks_run.append("narrative_times")
    known = _known_instants(registry, records, report, window)
    for where, text in _narratives(report) + _hypothesis_tests(report):
        for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
            times = []
            for m in DATETIME_RE.finditer(sentence):
                d, hh, mm, zone = m.groups()
                local = datetime.fromisoformat(f"{d}T{int(hh):02d}:{mm}:00+00:00")
                times.append((m.group(0), local - timedelta(minutes=ZONE_OFFSET_MIN[zone])))
            if not times:
                continue
            tied: set[datetime] = set()
            for n in narrative_numbers(sentence, chunk_ids):
                for c in report.numeric_claims:
                    ev = registry.get(c.evidence_id)
                    if ev is not None and ev.valid_at_utc and (abs(n - c.value) <= c.rounding + 1e-9 or
                                                               abs(abs(n) - abs(c.value)) <= c.rounding + 1e-9):
                        t = parse_iso(ev.valid_at_utc).replace(second=0, microsecond=0)
                        tied |= {t, t - timedelta(minutes=ev.interval_minutes or 0)}
            if tied and not any(u in tied for _, u in times):
                V.append(Violation("TIME_NOT_IN_EVIDENCE", "critical",
                                   f"{where}: {', '.join(t for t, _ in times)} does not match the evidence time of the "
                                   f"number(s) stated with it ({', '.join(sorted(f'{x:%Y-%m-%dT%H:%MZ}' for x in tied))})"))
            for label, utc in times:
                if utc not in known:
                    V.append(Violation("TIME_NOT_IN_EVIDENCE", "critical",
                                       f"{where}: '{label}' ({utc:%Y-%m-%dT%H:%MZ}) is not a time any tool returned"))

    # -- clock times and parts of the day in event and forecast answers (headline, summary, hypotheses and their
    #    tests). A clock time needs an explicit zone and must be an instant a tool produced in that zone; a word such
    #    as "morning" or "night" needs a time in the same sentence whose region-local hour shows it. Otherwise the
    #    description is removed. L3 live: EV09 put a notice's "11:00" (NEM time) beside UTC times and called
    #    05:30–17:30 UTC "the morning window"; EV02 called a 02:05 ACST peak "afternoon". Only the clock is compared
    #    for times written without a date.
    if report.intent in ("market_event_review", "forecast_review"):
        res.checks_run.append("narrative_clock_times")
        tz = region_zone(report.region) if report.region in REGION_TZ else NEM_TZ
        ref = window[0] if window else (min(known) if known else None)
        local_off = int((tz.utcoffset(ref) or timedelta(minutes=600)).total_seconds() // 60) if ref else 600
        clocks: dict[int, set[str]] = {}
        for where, text in _narratives(report) + _hypothesis_tests(report):
            for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
                s = PAREN_OFFSET_RE.sub(" ", sentence)
                local_hours: list[int] = []
                for m in DATETIME_RE.finditer(s):
                    day_s, hh, mm, zone = m.groups()
                    u = datetime.fromisoformat(f"{day_s}T{int(hh):02d}:{mm}:00+00:00") - timedelta(minutes=_zone_offset(zone))
                    local_hours.append(u.astimezone(tz).hour)
                for m in CLOCK_RE.finditer(DATETIME_RE.sub(" ", s)):
                    h1, m1, h2, m2, zone = m.groups()
                    if zone is None:
                        V.append(Violation("TIME_ZONE_MISSING", "critical",
                                           f"{where}: '{m.group(0).strip()}' has no time zone"))
                        continue
                    off = _zone_offset(zone)
                    known_clock = clocks.setdefault(off, {(u + timedelta(minutes=off)).strftime("%H:%M") for u in known})
                    for hh, mm in ((h1, m1), (h2, m2)):
                        if hh is None:
                            continue
                        clock = f"{int(hh):02d}:{mm}"
                        if clock not in known_clock:
                            V.append(Violation("TIME_NOT_IN_EVIDENCE", "critical",
                                               f"{where}: '{clock} {zone}' is not a time any tool returned"))
                        local_hours.append(((int(hh) * 60 + int(mm) - off + local_off) // 60) % 24)
                for word in sorted({w.lower() for w in PART_OF_DAY_RE.findall(s)}):
                    band_lo, band_hi = PART_OF_DAY[word]
                    if not any(_in_band(h, band_lo, band_hi) for h in local_hours):
                        shown = ", ".join(f"{h:02d}h" for h in sorted(set(local_hours))) or "none"
                        V.append(Violation("TIME_OF_DAY_UNVERIFIED", "critical",
                                           f"{where}: '{word}' is not shown by a region-local time in the sentence "
                                           f"(local hours stated: {shown})"))

    # -- a number stated with an interval length ("half-hour", "5-minute") must come from evidence of that resolution
    res.checks_run.append("narrative_intervals")
    for where, text in _narratives(report):
        for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
            named = _durations(sentence)
            if not named:
                continue
            for n in narrative_numbers(sentence, chunk_ids):
                resolutions = {ev.interval_minutes for c in report.numeric_claims
                               if (ev := registry.get(c.evidence_id)) is not None and ev.interval_minutes
                               and (abs(n - c.value) <= c.rounding + 1e-9 or abs(abs(n) - abs(c.value)) <= c.rounding + 1e-9)}
                if resolutions and not resolutions & named:
                    V.append(Violation("CLAIM_INTERVAL_MISMATCH", "critical",
                                       f"{where}: {n:g} is stated as a {'/'.join(f'{m}-minute' for m in sorted(named))} "
                                       f"value but its evidence is {'/'.join(f'{m}-minute' for m in sorted(resolutions))}"))

    # -- document claims: cited, and supported by the cited passage (quoted, or mostly in its words)
    res.checks_run.append("document_claims")
    items = [("headline", report.headline)] + [(f"summary[{i}]", s_) for i, s_ in enumerate(report.summary)]
    for where, text in items:
        cited_ids = [c for c in CITE_RE.findall(text) if c in cites]
        if report.intent == "source_explanation" and where != "headline" and not cited_ids and \
                QUOTED_RE.sub(" ", text).strip() and _stems(QUOTED_RE.sub(" ", text)):
            V.append(Violation("DOC_CLAIM_UNCITED", "critical", f"{where}: a document answer states this without citing "
                                                               "a retrieved passage"))
        quoted = [q.strip("“”\"") for q in QUOTED_RE.findall(text)]
        for cid in cited_ids:
            ch = registry.chunks.get(cites[cid].chunk_id)
            if ch is None or any(q and _norm(q) in _norm(ch.text) for q in quoted):
                continue
            sc = support(text, ch.text)
            if sc < SUPPORT_MIN:
                V.append(Violation("DOC_CLAIM_UNSUPPORTED", "critical",
                                   f"{where}: only {sc:.0%} of its content words appear in [{cid}] ({cites[cid].chunk_id})"))

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
