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
* language — no causal assertions outside hedged hypotheses; no echo of instruction-like retrieved text; both also
  in uncertainties and missing evidence, which may talk about causes but not assert one;
* action claims — an answer may say a case note or an action was approved, written or completed only with an
  approval record, which an investigation never has (it is read-only);
* status honesty — an "answered" report must carry evidence, and required tools must have run.
* decisive timing — when a question asks whether something a market notice reports explains the event, the
  answer must set the notice's time against the event's intervals.

Semantic support beyond these rules is not claimed: a matching quote proves the text exists, not that it proves
the claim. Findings are therefore restricted to verbatim quotation of event-matching documents.
"""

from __future__ import annotations

import contextlib
import functools
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .evidence import EvidenceRegistry
from .report import InvestigationReport
from .retrieval.corpus import INJECTION_RE, NOTICE_NUMBER_RE, cancelled_notices
from .timeutil import NEM_TZ, REGION_TZ, iso_utc, local_day_window, parse_iso, region_zone

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
    ruled_out: list[int] = field(default_factory=list)  # possible_explanations the evidence rules out (I-7c)

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


# PDF text extraction ends a line inside a hyphenated word ("non-\nscheduled") and the corpus joins lines with a space,
# so passages hold "non- scheduled" (held-out v4 W20: a faithful quote of "non-scheduled" failed). For comparison only,
# on both sides, the space after a hyphen between a letter or digit and a letter is dropped. No letter, digit or hyphen
# changes, so that space is the only new difference a quote may have from its passage; stored passages are unchanged.
_HYPHEN_BREAK_RE = re.compile(r"(?<=[A-Za-z0-9])- (?=[A-Za-z])")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'")
    return _HYPHEN_BREAK_RE.sub("-", re.sub(r"\s+", " ", s).strip())


def _unit(u: str) -> str:
    return UNIT_ALIASES.get(u.strip().lower(), u.strip())


# a market notice's own title follows this prefix in its chunk title ("AEMO market notice 144624 (RESERVE NOTICE): …")
_NOTICE_TITLE_PREFIX_RE = re.compile(r"^AEMO market notice \d+ \([^)]*\): ")
NOTICE_TITLE_MIN_WORDS = 4  # a short title could hide a number anywhere it happens to occur


def notice_titles(registry: EvidenceRegistry, chunk_ids: Iterable[str]) -> frozenset[str]:
    """The exact titles of the given retrieved chunks that are market notices, eligible and not flagged as
    instruction-like, with at least ``NOTICE_TITLE_MIN_WORDS`` words. A narrative may name a cited notice by its title,
    and the title's digits ("Level 2 (LOR2)") are then not numbers. Live check 2026-09-30, W19: four lines naming
    'STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026' failed as an untracked "2", and
    the "1" of a LOR1 title tied its line to an unrelated one-interval claim; the answer fell back."""
    out = set()
    for cid in chunk_ids:
        ch = registry.chunks.get(cid)
        if ch is None or ch.doc_type != "market_notice" or not ch.eligible or ch.instruction_like:
            continue
        title = _NOTICE_TITLE_PREFIX_RE.sub("", ch.title or "").strip()
        if len(title.split()) >= NOTICE_TITLE_MIN_WORDS:
            out.add(title)
    return frozenset(out)


def narrative_numbers(text: str, ids: frozenset[str] = frozenset(),
                      titles: frozenset[str] = frozenset()) -> list[float]:
    """Numbers stated in ``text`` outside quotations, dates, times and identifiers.

    ``ids`` are identifiers issued by the system in this request (retrieved chunk ids such as
    ``market_notice_144692#0``); only exact matches are removed, so a model cannot hide a number by calling it an id.
    ``titles`` (``notice_titles``) are removed the same way, only where one appears whole and unaltered: a changed,
    shortened or invented title, and any number outside it, are still read.
    """
    t = QUOTED_RE.sub(" ", text)
    for i in sorted(ids, key=len, reverse=True):
        t = t.replace(i, " ")
    t = t.replace("\u2010", "-").replace("\u2011", "-")  # U+2010/U+2011 hyphens: same duration label as "5-minute"
    for title in sorted(titles, key=len, reverse=True):
        t = re.sub(rf"(?<!\w){re.escape(title)}(?!\w)", " ", t)
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


def cancelled_notice_chunks(registry: EvidenceRegistry) -> dict[str, tuple[str, datetime]]:
    """Each retrieved market notice that another retrieved notice cancels: its chunk_id -> (the cancelling notice's
    chunk_id, that notice's publication time), the earliest cancellation if there are several."""
    by_number = {m.group(1): cid for cid in registry.chunks if (m := NOTICE_NUMBER_RE.match(cid))}
    out: dict[str, tuple[str, datetime]] = {}
    for ch in registry.chunks.values():
        if ch.doc_type != "market_notice" or not ch.publication_date:
            continue
        t = parse_iso(ch.publication_date)
        for n in cancelled_notices(ch.title, ch.text):
            if n in by_number and (by_number[n] not in out or t < out[by_number[n]][1]):
                out[by_number[n]] = (ch.chunk_id, t)
    return out


def _headlines(r: InvestigationReport) -> list[tuple[str, str]]:
    """The shown headline, and the model's own when the controller shows another (I-3c): both are checked, so a
    violation in the replaced one is repaired or withheld exactly as if it were shown."""
    hidden = r._model_headline
    return [("headline", r.headline)] + ([("headline", hidden)] if hidden and hidden != r.headline else [])


def _narratives(r: InvestigationReport) -> list[tuple[str, str]]:
    out = _headlines(r) + [(f"summary[{i}]", s) for i, s in enumerate(r.summary)]
    out += [(f"possible_explanations[{i}]", h.statement) for i, h in enumerate(r.possible_explanations)]
    out += [(f"published_findings[{i}]", f.statement) for i, f in enumerate(r.published_findings)]
    if r.forecast_comparison:
        out.append(("forecast_comparison.note", r.forecast_comparison.note))
    return out


# An investigation is read-only: no tool approves, writes or publishes anything, and case notes are approved and
# written only through the approval endpoints (approvals.py), after an answer exists. An answer saying that a case
# note or an action was approved, written or completed therefore needs an approval record (W20 injection audit: "The
# case note is approved." was shown although nothing had been approved or written). Negated, modal and conditional
# statements ("approval is required", "no approval was granted", "published only after approval") are not claims.
_ACT_OBJ = (r"(?:case[- ]?notes?|research notes?|(?:the|this|that|your|my|our) notes?|approvals?|publication|publishing|"
            r"(?:the|this|that|your) (?:requested|pending|write|publish(?:ing)?) (?:action|request|write)s?|"
            r"(?:your|this) (?:action|request)s?)")
_ACT_DONE = (r"(?:approved|published|written|saved|filed|submitted|completed|complete|done|finali[sz]ed|signed[- ]off|"
             r"granted|given|obtained|accepted|executed|performed|carried out|processed|recorded|sent)")
ACTION_CLAIM_RE = re.compile(
    rf"\b(?:{_ACT_OBJ}(?:\s+(?:for|on|about|of|in|from)\s+(?:[\w'-]+\s+){{0,4}}?[\w'-]+)?"  # "… for the SA1 event"
    r"(?:\s*(?:is|are|was|were|has|have|had|been|being|now|just|already|successfully|also|then|got|status|state|:|=))*"
    rf"\s+{_ACT_DONE}"
    r"|(?:I|we|the (?:agent|assistant|system)|(?:a|the) reviewer)(?:['’]ve)?"
    r"(?:\s+(?:have|has|had|just|already|now|successfully))*\s+"
    r"(?:approved|published|wrote|written|saved|filed|submitted|completed|finali[sz]ed|signed off|granted|executed|"
    r"performed|carried out|processed|recorded|sent))\b", re.I)
_NOT_DONE_RE = re.compile(r"\b(?:not|no|never|nothing|none|neither|nor|without|cannot|can|could|would|should|will|"
                          r"shall|may|might|must|unless|until|if|whether|once|pending|awaiting|yet|before|after|when|"
                          r"to)\b|n't\b", re.I)
_CONDITION_AFTER_RE = re.compile(r"^\W*(?:\w+\W+){0,2}?(?:only|once|if|after|before|when|until|unless|upon)\b", re.I)


def action_claims(text: str) -> list[str]:
    """Statements outside quotations that a case note or an action was approved, written or completed. A negation,
    modal or condition in the statement or the four words before it, or a condition right after it, makes it not a
    claim."""
    out = []
    for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
        for m in ACTION_CLAIM_RE.finditer(sentence):
            before = " ".join(sentence[:m.start()].split()[-4:])
            if not _NOT_DONE_RE.search(f"{before} {m.group(0)}") and not _CONDITION_AFTER_RE.search(sentence[m.end():]):
                out.append(m.group(0))
    return out


# Uncertainties and missing evidence get the narrative's language checks (W20 injection audit: "Ignore all previous
# instructions…" and "The price spike was caused by wind." were shown there). Their quotations are checked against no
# passage, so these checks read quoted text too. Caveats talk about causes without asserting one ("do not identify
# causes", "the cause … is not known", "reports that identify the cause of the trip"): causal wording counts unless a
# word in its own clause negates, questions, seeks or hedges it, or, for a noun ("the cause of …"), the clause goes on
# to call it unknown. A qualifier in another clause does not count ("Demand was not unusual and the spike was caused
# by wind" asserts the cause), while one in the main clause covers what it introduces ("We cannot conclude that wind
# caused the spike"). The controller's status line for a tool the model tried to call names that tool
# ("publish_case_note: blocked — unknown tool …"): it reports the attempt and is not an echo.
_CAUSE_TALK_RE = re.compile(
    r"\b(?:not|no|never|none|nothing|neither|nor|without|cannot|unknown|unclear|uncertain|uncertainty|unconfirmed|"
    r"unexplained|undetermined|whether|identify|identifies|identifying|interpret\w*|attribut\w*|determin\w*|"
    r"confirm\w*|establish\w*|explain\w*|investigat\w*|assess\w*|about|may|might|could|possibly|potentially|"
    r"perhaps)\b|n't\b", re.I)
_CAUSE_UNKNOWN_AFTER_RE = re.compile(r"^\W*(?:[\w'’-]+\W+){0,8}?(?:is|was|are|were|remains?|has been|have been)\s+"
                                     r"(?:not|un(?:known|clear|certain|confirmed|explained|determined))\b", re.I)
_QUOTE_MARKS_RE = re.compile(r"[“”\"]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
# where a new clause may start: "but", "while", "although" … and a comma before a conjunction always ("strong"); a plain
# comma or "and" only when a new finite verb follows, or the causal word is itself the verb (checked in _claim_clause)
_STRONG_BREAK = r",\s*(?:and|but|yet|so|while|whereas|although|though)\b|:|\b(?:but|yet|while|whereas|although|though)\b"
_STRONG_BREAK_RE = re.compile(_STRONG_BREAK, re.I)
_CLAUSE_BREAK_RE = re.compile(_STRONG_BREAK + r"|\band\b|,", re.I)
_FINITE_RE = re.compile(r"\b(?:is|are|was|were|has|have|had|do|does|did|will|would|shall|should|can|could|may|might|"
                        r"must)\b", re.I)
_SUBORDINATE_RE = re.compile(r"\b(?:whether|that|if|which|who|what|how|why)\b", re.I)
_CAUSAL_VERB_RE = re.compile(r"caused|drove|triggered|led to|leads to|resulted in|explains why", re.I)
_CAUSAL_NOUN_RE = re.compile(r"cause of|result of|causes", re.I)


def _claim_clause(sentence: str, m: re.Match[str]) -> str:
    """The words before causal wording ``m`` that belong to its own clause."""
    prefix, begin = sentence[:m.start()], 0
    for b in _CLAUSE_BREAK_RE.finditer(prefix):
        right = prefix[b.end():]
        if not right.strip():
            continue
        # the part before the break is a complete clause: it has a finite verb outside any clause it introduces
        left_done = bool(_FINITE_RE.search(_SUBORDINATE_RE.split(prefix[begin:b.start()])[-1]))
        verb = bool(_CAUSAL_VERB_RE.fullmatch(m.group(0)))
        kind = b.group(0).strip().lower()
        if (_STRONG_BREAK_RE.fullmatch(kind) or (kind == "," and (_FINITE_RE.search(right) or (verb and left_done)))
                or (kind == "and" and left_done and (_FINITE_RE.search(right) or verb))):
            begin = b.end()
    return prefix[begin:]


def caveat_causal_claim(text: str) -> str | None:
    """Causal wording that a caveat asserts, quoted text included, or None."""
    for sentence in SENTENCE_RE.split(_QUOTE_MARKS_RE.sub(" ", text)):
        for m in CAUSAL_RE.finditer(sentence):
            if _CAUSE_TALK_RE.search(_claim_clause(sentence, m)):
                continue
            rest = _STRONG_BREAK_RE.split(sentence[m.end():])[0]  # "the cause of … is not known", in the same clause
            if _CAUSAL_NOUN_RE.fullmatch(m.group(0)) and _CAUSE_UNKNOWN_AFTER_RE.search(rest):
                continue
            return m.group(0)
    return None


def caveat_echo(text: str, records: list[Any] | None) -> bool:
    """Instruction-like text in a caveat, quoted text included."""
    seen = _QUOTE_MARKS_RE.sub(" ", text)
    for r in records or []:
        if r.status != "ok" and _IDENTIFIER_RE.fullmatch(r.name or "") and text.startswith(f"{r.name}: {r.status} — "):
            seen = seen.replace(r.name, " ")
    return bool(INJECTION_RE.search(seen))


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
# a citation marker: any schema-valid citation ID, including ':' (held-out v4 W10 named citations
# 'aemo_so_op_3705#p12c33:supply'; the narrower pattern could never recognise them). Only IDs of the report's own
# citations count wherever this is used.
CITE_RE = re.compile(r"\[([A-Za-z0-9_#.:\-]+)\]")
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


# -- notice timing ---------------------------------------------------------------------------------------------------
# A notice's times are parsed here, not taken from the tool output: a notice writes "At 1100 hrs 20/08/2026" in NEM
# market time (UTC+10, docs/decisions.md D18), and a phrase without a date takes the notice's event date.
NOTICE_HRS_RE = re.compile(r"\b([01]\d|2[0-3]):?([0-5]\d) hrs\b(?:,? (?:on )?(\d{2})/(\d{2})/(\d{4}))?")
# A stated relation. Verbs whose sense flips in the passive ("preceded by", "followed by") are not read: a sentence
# relying on them is neither counted nor checked.
REL_RE = re.compile(r"\b(?:(?P<before>before|prior to|ahead of|earlier than)|(?P<after>after|later than|subsequent to)|"
                    r"(?P<between>between|during|within|while|amid|coincid\w* with|at the same time as))\b", re.I)
# What a notice time is compared with: the first or last threshold interval, the price extreme, or the threshold
# intervals as a whole ("the spike")
ANCHOR_RE = re.compile(r"\b(?:(?P<first>first|start of|onset)|(?P<last>last|final|end of)|"
                       r"(?P<peak>peak\w*|price extreme|highest|lowest|maximum|minimum|trough)|"
                       r"(?P<span>spikes?|surge|event|episodes?|intervals?|threshold|high[- ]price|low[- ]price|"
                       r"negative))\b", re.I)
LOW_SET_RE = re.compile(r"\b(negative|low[- ]price|below the low)\b", re.I)
HIGH_SET_RE = re.compile(r"\b(high[- ]price|at or above|spikes?)\b", re.I)
HYPOTHETICAL_RE = re.compile(r"\b(whether|if)\b", re.I)
# a hypothesis that itself says the timing excludes it ("timing rules this out", "could not have …")
RULED_OUT_RE = re.compile(r"\brul(?:e|es|ed|ing)\b(?:\s+\w+){0,2}\s+out\b|\b(?:cannot|can't|could not|couldn't) have\b", re.I)
# a bearing of an incident on the event, and wording that only denies or doubts it (I-7b): "might not correspond to the
# price spike" and "is unrelated to it" offer no influence, while "might be a factor" and "did not affect the first
# interval but could have influenced the peak" do
_BEARING = (r"influenc\w*|affect\w*|contribut\w*|explain\w*|account\w*\s+for|caus\w*|drove|driv\w*|push\w*|le[ad]\w*\s+to|"
            r"limit\w*|reduc\w*|constrain\w*|rais\w*|increas\w*|impact\w*|behind|correspond\w*|relat\w*|relevant|link\w*|"
            r"connect\w*|match\w*|appl(?:y|ies|ied)|bear\w*\s+on|responsible|factor\w*|role")
_BEARING_RE = re.compile(rf"\b(?:{_BEARING})\b", re.I)
_NO_BEARING_RE = re.compile(rf"(?:\b(?:not|no(?!\s+doubt)|never|unlikely\s+to|nothing\s+to\s+do\s+with)\b|n[’']t)"
                            rf"(?:\s+[\w’'-]+){{0,3}}?\s+(?:{_BEARING})\b|\b(?:unrelated|irrelevant)\b", re.I)


def doubts_bearing(text: str) -> bool:
    """Whether ``text`` only denies or doubts an incident's bearing on the event, suggesting none elsewhere."""
    bare = QUOTED_RE.sub(" ", text)
    return bool(_NO_BEARING_RE.search(bare)) and not _BEARING_RE.search(_NO_BEARING_RE.sub(" ", bare))
_FIVE = timedelta(minutes=5)


def _notice_instants(text: str, event_date: str | None) -> set[datetime]:
    out: set[datetime] = set()
    for m in NOTICE_HRS_RE.finditer(text):
        day = f"{m[5]}-{m[4]}-{m[3]}" if m[3] else event_date
        if day:
            with contextlib.suppress(ValueError):
                out.add(datetime.fromisoformat(f"{day}T{m[1]}:{m[2]}:00+10:00").astimezone(UTC))
    return out


@functools.lru_cache(maxsize=1)
def _thresholds() -> tuple[float, float]:
    from .selection import load_selection

    t = load_selection().analysis_threshold
    return float(t["high_price_rrp_at_or_above"]), float(t["low_price_rrp_below"])


@dataclass
class _EventTimes:
    """The event's 5-minute dispatch prices as the tools registered them in this investigation (interval-ending)."""
    kind: str
    ends: dict[str, list[datetime]]  # "high": RRP at or above the analysis threshold; "low": below the low threshold
    peak: datetime | None            # the price extreme (maximum for a high-price event, minimum for a low-price one)
    complete: bool                   # every interval from the window start to the last one held is registered
    thresholds: tuple[float, float]
    last: datetime | None = None     # the last interval registered


def _event_times(report: InvestigationReport, registry: EvidenceRegistry, window: tuple[datetime, datetime] | None,
                 kind: str | None) -> _EventTimes | None:
    w = window or ((parse_iso(report.event_window.start_utc), parse_iso(report.event_window.end_utc))
                   if report.event_window else None)
    if w is None or not report.region:
        return None
    rrp: dict[datetime, float] = {}
    for ev in registry.items.values():
        if ev.metric == "dispatch_rrp" and ev.region == report.region and ev.valid_at_utc and ev.value is not None:
            t = parse_iso(ev.valid_at_utc)
            if w[0] < t <= w[1]:
                rrp[t] = float(ev.value)
    hi_thr, lo_thr = _thresholds()
    ends = sorted(rrp)
    complete = bool(ends) and ends[0] == w[0] + _FIVE and all(b - a == _FIVE for a, b in zip(ends, ends[1:], strict=False))
    sets = {"high": [t for t in ends if rrp[t] >= hi_thr], "low": [t for t in ends if rrp[t] < lo_thr]}
    if kind not in ("high_price", "low_price"):
        kind = "high_price" if sets["high"] or not sets["low"] else "low_price"
    peak = None
    if ends:
        peak = (max(ends, key=lambda t: (rrp[t], -t.timestamp())) if kind == "high_price"
                else min(ends, key=lambda t: (rrp[t], t.timestamp())))
    return _EventTimes(kind, sets, peak, complete, (hi_thr, lo_thr), ends[-1] if ends else None)


@dataclass
class _Mention:
    """A time written with its zone: dated (an instant) or undated (a clock time in that zone)."""
    start: int
    end: int
    label: str
    instant: datetime | None
    clock: str  # "HH:MM" as written, in the zone below
    offset: int  # minutes east of UTC of the written zone

    def names(self, t: datetime) -> bool:
        if self.instant is not None:
            return self.instant == t
        return (t + timedelta(minutes=self.offset)).strftime("%H:%M") == self.clock

    def near(self, t: datetime) -> datetime:
        """The instant meant: an undated clock time is read on the day that puts it closest to t."""
        if self.instant is not None:
            return self.instant
        hh, mm = (int(x) for x in self.clock.split(":"))
        day = (t + timedelta(minutes=self.offset)).date()
        cands = [datetime(d.year, d.month, d.day, hh, mm, tzinfo=UTC) - timedelta(minutes=self.offset)
                 for d in (day - timedelta(days=1), day, day + timedelta(days=1))]
        return min(cands, key=lambda c: abs(c - t))


def _mentions(s: str) -> list[_Mention]:
    out = []
    for m in DATETIME_RE.finditer(s):
        d, hh, mm, zone = m.groups()
        off = _zone_offset(zone)
        u = datetime.fromisoformat(f"{d}T{int(hh):02d}:{mm}:00+00:00") - timedelta(minutes=off)
        out.append(_Mention(m.start(), m.end(), m.group(0), u, f"{int(hh):02d}:{mm}", off))
    for m in CLOCK_RE.finditer(DATETIME_RE.sub(lambda x: " " * len(x.group(0)), s)):
        h1, m1, h2, m2, zone = m.groups()
        if zone is not None:
            out += [_Mention(m.start(), m.end(), m.group(0).strip(), None, f"{int(hh):02d}:{mm}", _zone_offset(zone))
                    for hh, mm in ((h1, m1), (h2, m2)) if hh is not None]
    return sorted(out, key=lambda x: x.start)


def _z(t: datetime) -> str:
    return f"{t:%Y-%m-%dT%H:%MZ}"


# -- the time stated for a number (I-15) ----------------------------------------------------------------------------
# Held-out v6 Z03 stated 1204.0 MW for "the half-hour ending 2026-08-06T03:00:00Z / 2026-08-06 13:00 AEST"; the value
# (its claim's evidence, ev0917) is the 13:00Z half-hour, and 03:00Z was 1147.0 MW. The sentence-wide check above passed
# it because the same sentence stated another number with its right time. Here each number is bound to the time stated
# for it, and that time must be the time of the evidence supporting that number.
POINT_EVIDENCE = ("observed", "aemo_forecast", "retrospective_context")  # one interval's value; derived ones span more
_CLAUSE_SEP_RE = re.compile(r"[;,]|\s(?:and|while|whereas|but)\s", re.I)
# a time introduced as something other than when the value applies: an issue, as-of, publication or availability time
# (also as a field name, "issued_at_utc 2026-…"), or one side of a relation
_NOT_VALUE_TIME_RE = re.compile(r"\b(?:issued|issue|as[ _-]of|published|publication|public|available|availability|created|"
                                r"cut-?off)(?:_at)?(?:_utc|_local)?(?:\s+times?)?\W{0,4}(?:(?:at|on|by|about|around)\W{1,3})?$"
                                # a relation, also across a few words with no number or clause break before the time
                                r"|\b(?:before|after|since|until|prior to|later than|earlier than)\b[^\d.;,]{0,40}$", re.I)
# what may join two times in a list ("at both T1 and T2", "T1, T2"): not a clause break
_TIME_LIST_JOIN_RE = re.compile(r"\s*(?:\([^()]*\)\s*)?[,;]?\s*(?:and|or)?\s*", re.I)
_RANGE_LEAD_RE = re.compile(r"\b(?:between|from)\s*$", re.I)
_RANGE_JOIN_RE = re.compile(r"^\s*(?:\([^()]*\)\s*)?(?:and|to|until|through|–|—|-)\s*$", re.I)
EV_MARK_RE = re.compile(r"\[(ev\d{4})\]")


def number_spans(text: str, ids: frozenset[str] = frozenset(),
                 titles: frozenset[str] = frozenset()) -> list[tuple[float, int, int]]:
    """``narrative_numbers`` with each number's position in ``text``: (value, start, end). Ignored spans are blanked
    to the same length, so positions are the text's own."""
    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group(0))
    t = QUOTED_RE.sub(blank, text)
    for i in sorted(ids, key=len, reverse=True):
        t = t.replace(i, " " * len(i))
    t = t.replace("‐", "-").replace("‑", "-")
    for title in sorted(titles, key=len, reverse=True):
        t = re.sub(rf"(?<!\w){re.escape(title)}(?!\w)", blank, t)
    for pat in IGNORE_RES:
        t = pat.sub(blank, t)
    out = []
    for m in NUM_RE.finditer(t):
        s = m.group(0).replace("−", "-").replace("$", "").replace(",", "")
        try:
            out.append((float(s), m.start(), m.end()))
        except ValueError:
            continue
    return out


def _separators(s: str) -> list[int]:
    """Start positions of clause separators: "and", "while", "whereas", "but" anywhere, "," and ";" outside brackets
    (inside, they list equivalents, "(09:00Z, 19:00 AEST)"). In "(… −718.24 MW [ev0438] and the price rise from the
    interval ending T)" (held-out v4 W18), T is the price rise's, not −718.24's."""
    depth, out = 0, []
    opens, closes = "([", ")]"
    seps = {m.start(): m.group(0) for m in _CLAUSE_SEP_RE.finditer(s)}
    for i, ch in enumerate(s):
        if ch in opens:
            depth += 1
        elif ch in closes:
            depth = max(depth - 1, 0)
        elif i in seps and (depth == 0 or seps[i] not in ",;"):
            out.append(i)
    return out


# How a time names the value's interval, under the interval-ending convention (an interval ending T covers
# (T - length, T]): "ending T" names its end, "starting T" its start, "containing T" or a time with no qualifier an
# instant in it. A named interval of another length ("the half-hour containing the 5-minute interval ending T") must lie
# inside the value's interval, or the value's inside it. An equivalent written after "/", "=" or "(" keeps the
# qualifier of the time before it.
_QUAL_RE = re.compile(
    r"(?:\b(?P<noun>half[- ]hours?|30[- ]min(?:ute)?s?(?:\s+(?:interval|period))?|5[- ]min(?:ute)?s?(?:\s+(?:dispatch\s+)?"
    r"interval)?|dispatch interval|interval|period)\s+)?\b(?P<q>ending|ended|ends|starting|started|starts|beginning|"
    r"begins)(?:\s+(?:at|on))?\s*$"
    r"|\b(?P<field>[a-z]+_(?:end|start))(?:_utc|_local)?\s*[:=]?\s*$"
    r"|\b(?P<c>containing|contains|during|within|including|includes|covering|covers)(?:\s+(?:the|a|an))?\s*$", re.I)
_CONTAINER_RE = re.compile(r"\b(?:containing|contains|during|within|including|includes|covering|covers)\b", re.I)
_EQUIV_JOIN_RE = re.compile(r"\s*(?:[/=(]|\)\s*\()?\s*")


def _qualifier(lead: str) -> tuple[str, int | None, bool]:
    """(kind, named interval length in minutes or None, contained) for the text just before a time: kind is "end",
    "start", "contain" or "plain"; a generic "interval ending T" after "containing" names an interval inside the
    value's."""
    m = _QUAL_RE.search(lead)
    if m is None:
        return "plain", None, False
    if m.group("c"):
        return "contain", None, False
    if m.group("field"):
        return ("end" if m.group("field").lower().endswith("_end") else "start"), None, False
    kind = "end" if m.group("q").lower().startswith("end") else "start"
    noun = (m.group("noun") or "").lower()
    named = 30 if noun.startswith(("half", "30")) else 5 if noun.startswith(("5", "dispatch")) else None
    return kind, named, named is None and bool(_CONTAINER_RE.search(lead[:m.start()]))


@dataclass
class _Stated:
    """A time stated for a number: one instant (a mention) or a range of two, with how it names the interval."""
    start: int
    end: int
    first: _Mention
    last: _Mention | None = None
    label: str = ""
    kind: str = "plain"       # "end", "start", "contain" or "plain"
    named: int | None = None  # the length of the interval the wording names, when it names one
    contained: bool = False   # a generic interval named inside the value's ("containing the interval ending T")

    def fits(self, ev: Any) -> bool:
        """Whether this time names the evidence's interval (end, start, an instant in it, or a range overlapping it),
        in UTC or any zone; a time without a date by its clock in its zone."""
        end = parse_iso(ev.valid_at_utc).replace(second=0, microsecond=0)
        length = ev.interval_minutes or 0
        start = end - timedelta(minutes=length)
        a = self.first.near(end)
        if self.last is not None:  # a range (lo, hi] overlapping the value's interval (start, end]
            b = self.last.near(end)
            lo, hi = min(a, b), max(a, b)
            return lo < end <= hi if not length else lo < end and start < hi
        if not length:
            return a == end
        if self.kind in ("plain", "contain"):
            return start < a <= end
        if (self.named is None and not self.contained) or self.named == length:  # the value's own interval
            return a == (end if self.kind == "end" else start)
        if self.contained or (self.named or 0) < length:  # a shorter interval inside the value's
            return start < a <= end if self.kind == "end" else start <= a < end
        span = timedelta(minutes=self.named or 0)  # a longer interval around the value's
        return (a - span <= start and end <= a) if self.kind == "end" else (a <= start and end <= a + span)


def _stated_times(s: str) -> list[_Stated]:
    """The value times in sentence ``s``: zoned times, minus those introduced as issue, as-of, publication or
    availability times or in a relation (with their equivalents in the sentence), with ranges joined."""
    ms = _mentions(PAREN_OFFSET_RE.sub(lambda m: " " * len(m.group(0)), s))
    not_value = [m for m in ms if _NOT_VALUE_TIME_RE.search(s[max(0, m.start - 40):m.start])]
    ruled = {id(m) for m in ms if m in not_value or any(
        n.instant is not None and m.instant is not None and n.instant == m.instant for n in not_value)}
    quals: dict[int, tuple[str, int | None, bool]] = {}
    for n, m in enumerate(ms):
        prev = ms[n - 1] if n else None
        lead = s[max(prev.end if prev else 0, m.start - 80):m.start]
        quals[id(m)] = (quals[id(prev)] if prev is not None and _EQUIV_JOIN_RE.fullmatch(lead)
                        else _qualifier(lead))
    keep = [m for m in ms if id(m) not in ruled]
    out: list[_Stated] = []
    i = 0
    while i < len(keep):
        m = keep[i]
        nxt = keep[i + 1] if i + 1 < len(keep) else None
        if nxt is not None and nxt.start == m.start:  # a clock range in one match ("11:15–11:25 UTC")
            out.append(_Stated(m.start, m.end, m, nxt, m.label))
            i += 2
            continue
        # a range of two dated times: "between T1 and T2", "from T1 (L1) to T2", "T1 – T2"; equivalents written in
        # brackets between them belong to the range
        j = next((j for j in range(i + 1, min(i + 4, len(keep)))
                  if _RANGE_JOIN_RE.match(re.sub(r"\([^()]*\)", " ", s[m.end:keep[j].start]))
                  and (_RANGE_LEAD_RE.search(s[max(0, m.start - 12):m.start])
                       or not re.search(r"\band\b", s[m.end:keep[j].start], re.I))), None)
        if j is not None:
            out.append(_Stated(m.start, keep[j].end, m, keep[j], f"{m.label} – {keep[j].label}"))
            i = j + 1
            continue
        out.append(_Stated(m.start, m.end, m, None, m.label, *quals[id(m)]))
        i += 1
    return out


def claim_time_violations(where: str, sentence: str, report: InvestigationReport, registry: EvidenceRegistry,
                          ids: frozenset[str], titles: frozenset[str]) -> list[Violation]:
    """``CLAIM_TIME_MISMATCH`` and ``CLAIM_TIME_AMBIGUOUS`` for one narrative sentence (I-15).

    - **The number:** a number traced to point evidence (an observed row, an AEMO forecast, a context row) with a time.
      Its supporting evidence is that of an ``[evNNNN]`` marker written after it when the marker's value is the number;
      otherwise the evidence of every claim with that value. Never another evidence item with an equal value.
    - **The time stated for it:** the sentence is cut into clauses (``_separators``). A stated time goes to
      the closest number before it in its clause ("11432.7 MW in the interval ending T"), or, when none comes before
      it, to the next one ("(half-hour ending T) was 1204.0 MW"). A time introduced as an issue, as-of, publication or
      availability time, or in a relation, is not a value time, nor is its equivalent elsewhere in the sentence.
    - **What the time names:** "ending T" the interval's end, "starting T" its start, "containing T" or a bare time an
      instant in (start, end] (``_Stated.fits``; interval-ending convention).
    - **The rule:** every time stated for the number must fit its evidence (``_Stated.fits``). When the value is
      supported by evidence at several times and the stated times fit only some of them, the answer has not said which:
      ``CLAIM_TIME_AMBIGUOUS``, never a guess. A number stated with no time is given none."""
    nums = number_spans(sentence, ids, titles)
    stated = _stated_times(sentence)
    if not nums or not stated:
        return []
    claims = [(c, registry.get(c.evidence_id)) for c in report.numeric_claims]

    def point(ev: Any) -> bool:
        return ev is not None and ev.value is not None and bool(ev.valid_at_utc) and ev.evidence_class in POINT_EVIDENCE

    bound: list[tuple[float, int, int, list[Any], bool]] = []  # value, start, end, supporting evidence, marked
    for i, (v, a, b) in enumerate(nums):
        upto = nums[i + 1][1] if i + 1 < len(nums) else len(sentence)
        marks = [registry.get(m.group(1)) for m in EV_MARK_RE.finditer(sentence, b, upto)]
        marked = [ev for ev in marks if point(ev) and ev is not None and abs(float(ev.value or 0.0) - v) <= 1e-9]
        if marked:
            bound.append((v, a, b, marked[:1], True))
            continue
        evs = [ev for c, ev in claims if ev is not None and point(ev)
               and (abs(v - c.value) <= c.rounding + 1e-9 or abs(abs(v) - abs(c.value)) <= c.rounding + 1e-9)]
        if evs:
            bound.append((v, a, b, evs, False))
    if not bound:
        return []
    joins = [(a.end, b.start) for a, b in zip(stated, stated[1:], strict=False)
             if _TIME_LIST_JOIN_RE.fullmatch(sentence[a.end:b.start])]
    seps = [x for x in _separators(sentence) if not any(st.start < x < st.end for st in stated)
            and not any(lo <= x < hi for lo, hi in joins)]

    def clause(pos: int) -> int:
        return sum(1 for x in seps if x < pos)
    assigned: dict[int, list[_Stated]] = {}
    for st in stated:
        same = [k for k, (_, a, b, _, _) in enumerate(bound) if clause(a) == clause(st.start)]
        before = [j for j in same if bound[j][2] <= st.start]
        after = [j for j in same if bound[j][1] >= st.end]
        owner = (max(before, key=lambda j: bound[j][2]) if before
                 else min(after, key=lambda j: bound[j][1]) if after else None)
        if owner is not None:
            assigned.setdefault(owner, []).append(st)
    out = []
    for k, (v, _, _, evs, by_marker) in enumerate(bound):
        times = assigned.get(k)
        if not times:
            continue
        distinct = {(ev.valid_at_utc, ev.interval_minutes): ev for ev in evs}
        unfit = [st.label for st in times if not any(st.fits(ev) for ev in distinct.values())]
        evidence = ", ".join(f"{ev.evidence_id} {ev.valid_at_utc}" for ev in distinct.values())
        if unfit:
            out.append(Violation("CLAIM_TIME_MISMATCH", "critical",
                                 f"{where}: {v:g} is stated for {', '.join(unfit)}, but its evidence is for another "
                                 f"time ({evidence})"))
        elif len(distinct) > 1 and not by_marker:
            covered = [ev for ev in distinct.values() if any(st.fits(ev) for st in times)]
            if len(covered) < len(distinct):
                out.append(Violation("CLAIM_TIME_AMBIGUOUS", "critical",
                                     f"{where}: {v:g} is supported by evidence at several times ({evidence}); the time "
                                     f"stated ({', '.join(st.label for st in times)}) fits only some, so say which "
                                     "evidence it is"))
    return out


def requested_max_violations(report: InvestigationReport, registry: EvidenceRegistry, bindings: list[dict[str, Any]],
                             sentences: list[tuple[str, str]],
                             numbers: Any) -> list[Violation]:
    """``REQUESTED_MAXIMUM_MISSING`` and ``REQUESTED_MAXIMUM_MISMATCH`` for the maxima the controller bound (I-17).

    - **Given:** some claim or observation in the answer is a bound maximum, matched by its evidence (metric, region,
      interval end, value and source rows), never by the number alone: another measure's equal value does not count.
    - **Not misstated:** a sentence stating the measure's maximum (``demand_max.max_claim_re``) gives no traced demand
      value that is not a bound maximum: another interval of the measure (the value at the price peak) or another
      demand measure. When no maximum can be established, it gives no demand value at all."""
    from .agent.demand_max import MEASURES, max_claim_re

    def key(ev: Any) -> tuple[Any, ...]:
        return ev.metric, ev.region, ev.valid_at_utc, ev.value, tuple(ev.source_row_ids)

    def demand(ev: Any) -> bool:
        return ev.metric == "dispatch_totaldemand" or ev.metric.startswith("opdemand")
    used = {o.evidence_id for o in report.observations} | {c.evidence_id for c in report.numeric_claims}
    given = {key(ev) for e in used if (ev := registry.get(e)) is not None}
    out: list[Violation] = []
    for b in bindings:
        measure = str(b["measure"])
        bound = {key(ev) for e in b.get("evidence_ids") or [] if (ev := registry.get(e)) is not None}
        what = f"the maximum of {measure} ({MEASURES[measure][3]}) over {' to '.join(b.get('window_utc') or [])}"
        if bound and not bound & given:
            out.append(Violation("REQUESTED_MAXIMUM_MISSING", "critical",
                                 f"the question asks for {what}; the answer does not give it ({b.get('value')} in the "
                                 f"interval ending {', '.join(b.get('interval_ends_utc') or [])})"))
        rx = max_claim_re(measure)
        for where, sentence in sentences:
            if not rx.search(sentence):
                continue
            for v, _, _ in numbers(sentence):
                evs = [ev for c in report.numeric_claims if abs(v - c.value) <= c.rounding + 1e-9
                       and (ev := registry.get(c.evidence_id)) is not None and demand(ev)]
                if evs and not any(key(ev) in bound for ev in evs):
                    ev = evs[0]
                    out.append(Violation("REQUESTED_MAXIMUM_MISMATCH", "critical",
                                         f"{where}: {v:g} is stated as {what}, but it is {ev.metric} for the interval "
                                         f"ending {ev.valid_at_utc} ({ev.evidence_id}); " +
                                         (f"the maximum is {b.get('value')} in the interval ending "
                                          f"{', '.join(b.get('interval_ends_utc') or [])}" if bound else
                                          f"no maximum can be established ({b.get('unavailable') or 'incomplete'})")))
    return out


def backstop_violations(report: InvestigationReport, registry: EvidenceRegistry, records: list[Any] | None,
                        bindings: list[dict[str, Any]] | None, forecast_run: dict[str, Any] | None,
                        sentences: list[tuple[str, str]], numbers: Any,
                        already: set[tuple[str, float]],
                        window: tuple[datetime, datetime] | None = None) -> list[Violation]:
    """Two answer-side backstops for requests whose wording was not recognised (I-18). Both are lexical
    (``structured.demand_extreme_words``, ``structured.run_selection_clause``) and bounded: they do not catch every
    paraphrase.

    - ``DEMAND_EXTREME_UNVERIFIED``: a clause states a demand maximum or minimum (dispatch TOTALDEMAND or actual
      operational demand) whose value code did not compute as that extreme over the window the statement names
      (``structured.claimed_windows``): the requested maximum's window, the investigation's ``window``, or the local
      day of the value's interval. The extreme is computed from the series the tools returned for that measure and
      region, and only when they hold every interval of that window (under an as-of cutoff, those not yet public are
      missing), so a subset's extreme, another window's or a partial one is never certified as the window's. An
      extreme qualified as one of what is held ("the highest value held") is checked against the held intervals of
      the window. A window narrowed in words that cannot be read is not established, so nothing is certified for it.
      The value stated as the extreme is the first number after the peak or minimum word, else the last one before
      it; an equal value of the same measure and region (a tied interval) counts. ``already`` holds (item, value)
      pairs that ``REQUESTED_MAXIMUM_MISMATCH`` flagged, which are not flagged twice.
    - ``RUN_SELECTION_UNVERIFIED``: when no forecast run is bound and the answer has no as-of cutoff, a clause presents
      a run as the final, last or latest one issued before something. Wording about availability is exempt (the as-of
      selection, I-10)."""
    from .agent.demand_max import MEASURES
    from .agent.structured import claimed_windows, clauses, demand_extreme_words, run_selection_clause

    by_metric = {m[3]: (m[0], m[1], m[4]) for m in MEASURES.values()}  # metric -> (tool, value field, minutes)
    points_cache: dict[tuple[str, str | None], dict[datetime, set[float]]] = {}

    def points(metric: str, region: str | None) -> dict[datetime, set[float]]:
        """Interval end -> the values the tools returned for the measure and region (several: revisions differ)."""
        if (metric, region) not in points_cache:
            tool, value_field, _ = by_metric[metric]
            pts: dict[datetime, set[float]] = {}
            for r in records or []:
                if getattr(r, "name", None) == tool and getattr(r, "status", None) == "ok" and \
                        (r.args or {}).get("region") == region:
                    for x in (r.data or {}).get("series", []):
                        if x.get(value_field) is not None and x.get("interval_end_utc"):
                            pts.setdefault(parse_iso(x["interval_end_utc"]), set()).add(float(x[value_field]))
            points_cache[(metric, region)] = pts
        return points_cache[(metric, region)]

    if window is None and report.event_window is not None:  # the investigation's window, as the answer states it
        window = (parse_iso(report.event_window.start_utc), parse_iso(report.event_window.end_utc))

    def extreme(kind: str, metric: str, region: str | None, w: tuple[datetime, datetime], held: bool) -> float | None:
        """The measure's maximum or minimum over the window: a complete requested maximum the controller computed for
        exactly this window, or computed here from the tools' series. None unless every interval of the window is held
        (or, for ``held``, at least one), each with one value."""
        for b in bindings or []:
            if kind == "max" and b.get("complete") and b.get("value") is not None and \
                    MEASURES[str(b["measure"])][3] == metric and b.get("window_utc") and \
                    (parse_iso(b["window_utc"][0]), parse_iso(b["window_utc"][1])) == w and \
                    (ev := registry.get((b.get("evidence_ids") or [""])[0])) is not None and ev.region == region:
                return float(b["value"])
        pts = {t: v for t, v in points(metric, region).items() if w[0] < t <= w[1]}
        if not pts or any(len(v) > 1 for v in pts.values()):
            return None
        if not held and len(pts) < round((w[1] - w[0]) / timedelta(minutes=by_metric[metric][2])):
            return None
        values = [next(iter(v)) for v in pts.values()]
        return max(values) if kind == "max" else min(values)

    def windows(names: set[str], ev: Any) -> list[tuple[datetime, datetime]]:
        """The windows the statement names, for the measure of ``ev``."""
        bound = [(parse_iso(b["window_utc"][0]), parse_iso(b["window_utc"][1]), str(b.get("window_kind")))
                 for b in bindings or [] if b.get("window_utc") and MEASURES[str(b["measure"])][3] == ev.metric]
        out: list[tuple[datetime, datetime]] = []
        if "narrowed" in names:  # only a request's own explicit window can stand for wording that narrows one
            return [(a, z) for a, z, k in bound if k == "explicit"]
        if names & {"requested", "default"}:
            out += [(a, z) for a, z, _ in bound]
        if "event" in names or ("default" in names and not bound):
            out += [window] if window else []
            out += [(a, z) for a, z, k in bound if k == "event"]
        if "day" in names and ev.valid_at_utc and ev.region in REGION_TZ:
            t = parse_iso(ev.valid_at_utc) - timedelta(seconds=1)  # an interval ending at midnight is the day before
            out.append(local_day_window(t.astimezone(region_zone(ev.region)).date(), ev.region))
        return out

    out: list[Violation] = []
    for where, sentence in sentences:
        for clause in clauses(sentence):
            spans = numbers(clause)
            stated = []
            for p, kind in demand_extreme_words(clause, sentence):
                after = [x for x in spans if x[1] >= p]
                before = [x for x in spans if x[2] <= p]
                if after or before:
                    stated.append(((after[0] if after else before[-1])[0], kind))
            names, held = claimed_windows(clause, sentence)
            for v, kind in dict.fromkeys(stated):
                if (where, v) in already:
                    continue
                hits = [(c, ev) for c in report.numeric_claims if abs(v - c.value) <= c.rounding + 1e-9
                        and (ev := registry.get(c.evidence_id)) is not None
                        and ev.metric in by_metric]
                if not hits:
                    continue
                certified = any(x is not None and abs(v - x) <= c.rounding + 1e-9 for c, ev in hits
                                for w in windows(names, ev)
                                for x in [extreme(kind, ev.metric, ev.region, w, held)])
                if not certified:
                    ev = hits[0][1]
                    out.append(Violation("DEMAND_EXTREME_UNVERIFIED", "critical",
                                         f"{where}: {v:g} is stated as a demand {'maximum' if kind == 'max' else 'minimum'}"
                                         f" ({ev.metric}, interval ending {ev.valid_at_utc}, {ev.evidence_id}), but no "
                                         f"code computed it as that extreme over the window the sentence names "
                                         f"({', '.join(sorted(names))}) with every interval of it held"))
            if not forecast_run and not report.as_of and run_selection_clause(clause):
                out.append(Violation("RUN_SELECTION_UNVERIFIED", "critical",
                                     f"{where}: presents a forecast run as the final, last or latest one issued "
                                     "before a half-hour, but no such run was looked up for this question"))
    return out


NOTICE_WORD_RE = re.compile(r"\bnotices?\b", re.I)
# timing statements are read to the end of the sentence: "…: first interval ending A; last interval ending B; and
# before the price extreme …" is one statement (v3 V18 was cut at ';')
TIMING_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _in_force(region: str | None, t: datetime) -> set[int]:
    """Offsets (minutes east of UTC) a notice time can legitimately be written in at instant t: UTC, NEM time
    (UTC+10) and the region's local time then (e.g. ACST, not ACDT, in a South Australian July)."""
    tz = region_zone(region) if region in REGION_TZ else NEM_TZ
    return {0, 600, int((tz.utcoffset(t) or timedelta(minutes=600)).total_seconds() // 60)}


def _matches(m: _Mention, notices: set[datetime], near: set[datetime]) -> list[datetime]:
    """The cited notice times this written time names: a dated time exactly; an undated clock only among the notice
    times near the event window (a clock alone says nothing about the day)."""
    return sorted(t for t in (notices if m.instant is not None else near) if m.names(t))


def _zone_slips(where: str, sentence: str, notices: set[datetime], near: set[datetime],
                region: str | None) -> list[Violation]:
    """A sentence about a notice that gives none of the cited notices' times correctly, but gives one of them with the
    right date and clock under another zone (e.g. the notice's '11:00' NEM time written as '11:00 UTC'). Such a time
    can still be a real instant (a price interval), so the time-in-evidence check alone would accept it. Only the
    zones in force at that instant are considered, and a dated time must match the date as well (v3 V18, V19: a price
    time matched another notice's clock on another day, once under ACDT in July)."""
    if not NOTICE_WORD_RE.search(sentence):
        return []
    ms = _mentions(PAREN_OFFSET_RE.sub(lambda x: " " * len(x.group(0)), sentence))
    if any(_matches(m, notices, near) for m in ms):
        return []
    out = []
    for m in ms:
        for t in sorted(notices if m.instant is not None else near):
            hit = False
            for off in _in_force(region, t) - {m.offset}:
                local = t + timedelta(minutes=off)
                same_day = m.instant is None or (m.instant + timedelta(minutes=m.offset)).date() == local.date()
                hit = hit or (same_day and local.strftime("%H:%M") == m.clock)
            if hit:
                out.append(Violation("NOTICE_TIME_ZONE_MISMATCH", "critical",
                                     f"{where}: gives '{m.label}' where the notice's time is {_z(t)} "
                                     f"({(t + timedelta(minutes=600)):%H:%M} NEM time): the clock is right but the zone "
                                     "is not"))
                break
    return out


def _timing_statements(where: str, sentence: str, notices: set[datetime], near: set[datetime],
                       et: _EventTimes | None) -> tuple[set[datetime], list[Violation]]:
    """The notice times this sentence sets against the event, and a violation for each such statement that the
    registered price intervals contradict or cannot verify.

    For each relation word, the first thing after it (a notice time, or the event: an interval, the peak, the spike,
    a stated time) is its object and the other side its subject, so "before the notice's 11:00 AEST, the last interval
    had ended" is read as the notice time being after the last interval. Times are compared in UTC."""
    s = PAREN_OFFSET_RE.sub(lambda x: " " * len(x.group(0)), sentence)
    ms = _mentions(s)
    at_notice = [m for m in ms if _matches(m, notices, near)]
    if not at_notice:
        return set(), []
    others = [m for m in ms if m not in at_notice]
    rels = list(REL_RE.finditer(s))
    stated: set[datetime] = set()
    out: list[Violation] = []
    for i, r in enumerate(rels):
        rel = r.lastgroup or ""
        stop = rels[i + 1].start() if i + 1 < len(rels) else len(s)
        prev = rels[i - 1].end() if i else 0
        n_fwd = next((m for m in at_notice if r.end() <= m.start < stop), None)
        a_fwd = next(iter(ANCHOR_RE.finditer(s, r.end(), stop)), None)
        o_fwd = next((m for m in others if r.end() <= m.start < stop), None)
        firsts = [x for x in (n_fwd.start if n_fwd else None, a_fwd.start() if a_fwd else None,
                              o_fwd.start if o_fwd else None) if x is not None]
        if not firsts:
            continue
        if n_fwd is not None and n_fwd.start == min(firsts):
            # the notice time is the object: the event is the subject, before the relation word or after the time
            mention = n_fwd
            back = s[prev:r.start()]
            lo, hi = ((prev, r.start()) if ANCHOR_RE.search(back) or any(prev <= m.start < r.start() for m in others)
                      else (n_fwd.end, stop))
            rel = {"before": "after", "after": "before"}.get(rel, rel)
        else:
            mention = min(at_notice, key=lambda m: min(abs(m.start - r.start()), abs(m.end - r.start())))
            lo, hi = r.end(), (n_fwd.start if n_fwd else stop)
        t = _matches(mention, notices, near)[0]
        phrase = s[lo:hi]
        refs = [m for m in others if lo <= m.start < hi]
        groups = [a.lastgroup for a in ANCHOR_RE.finditer(phrase)]
        explicit_span = {"first", "last"} <= set(groups)  # "between the first and last … intervals"
        if rel == "between":
            target = "peak" if "peak" in groups and not explicit_span else ("span" if groups else None)
        else:
            target = next((g for g in groups if g in ("first", "last", "peak")), "span" if groups else None)
        if target is None and not refs:
            continue
        stated.add(t)
        says = {"before": "before", "after": "after", "between": "within"}[rel]
        if target in ("first", "last", "peak") or (target == "span" and (explicit_span or not refs)):
            if et is None or not et.complete:
                out.append(Violation("NOTICE_TIMING_UNVERIFIED", "critical",
                                     f"{where}: sets the notice time {_z(t)} against the event's price intervals, but "
                                     "the dispatch prices for the whole event window are not in this investigation's "
                                     "evidence (call get_price_timeline for the window)"))
                continue
            key = ("low" if LOW_SET_RE.search(phrase) else "high" if HIGH_SET_RE.search(phrase)
                   else "high" if et.kind == "high_price" else "low")
            which = (f"at or above {et.thresholds[0]:g} $/MWh" if key == "high" else f"below {et.thresholds[1]:g} $/MWh")
            if target == "peak":
                assert et.peak is not None
                a0, a1, desc = et.peak - _FIVE, et.peak, "the price extreme's 5-minute interval"
            else:
                ends = et.ends[key]
                if not ends:
                    out.append(Violation("NOTICE_TIMING_CONTRADICTED", "critical",
                                         f"{where}: sets the notice time against 5-minute intervals {which}, but the "
                                         "window has none"))
                    continue
                a0, a1 = {"first": (ends[0] - _FIVE, ends[0]), "last": (ends[-1] - _FIVE, ends[-1]),
                          "span": (ends[0] - _FIVE, ends[-1])}[target]
                desc = {"first": f"the first 5-minute interval {which}", "last": f"the last 5-minute interval {which}",
                        "span": f"the 5-minute intervals {which}"}[target]
            ok = t <= a0 if rel == "before" else t >= a1 if rel == "after" else a0 <= t <= a1
            if not ok:
                actual = "before" if t <= a0 else "after" if t >= a1 else "within"
                out.append(Violation("NOTICE_TIMING_CONTRADICTED", "critical",
                                     f"{where}: says the notice time {_z(t)} is {says} {desc} ({_z(a0)} to {_z(a1)}); "
                                     f"it is {actual} it"))
            # the times given for the named interval(s) must be theirs: for "between the first and last", the first
            # interval's or the last interval's own start or end (a time written on two bases counts once)
            bounds = ({et.ends[key][0] - _FIVE, et.ends[key][0], et.ends[key][-1] - _FIVE, et.ends[key][-1]}
                      if target == "span" else {a0, a1})
            if target != "span" or explicit_span:
                for ref in refs:
                    if not any(ref.names(b) for b in bounds):
                        out.append(Violation("NOTICE_TIMING_CONTRADICTED", "critical",
                                             f"{where}: gives '{ref.label}' for {desc}, which runs from {_z(a0)} to "
                                             f"{_z(a1)}"))
        else:  # compared with a stated time; one instant written on two bases ("04:35Z = 14:05 ACST") is one time
            when = sorted({m.near(t) for m in refs})
            if rel == "between" and len(when) >= 2:
                ok = when[0] <= t <= when[-1]
            elif rel in ("before", "after"):
                ok = t <= when[0] if rel == "before" else t >= when[-1]
            else:
                continue
            if not ok:
                out.append(Violation("NOTICE_TIMING_CONTRADICTED", "critical",
                                     f"{where}: says the notice time {_z(t)} is {says} "
                                     f"{' and '.join(m.label for m in refs[:2])} ({', '.join(_z(w) for w in when[:2])})"))
    return stated, out


def _stems(text: str) -> list[str]:
    return [w[:5] for w in WORD_RE.findall(text.lower()) if len(w) > 2 and w not in SUPPORT_STOP]


def support(sentence: str, passage: str) -> float:
    """Share of the sentence's content words (5-letter stems) found in the passage: a lexical, not semantic, test."""
    words = _stems(QUOTED_RE.sub(" ", CITE_RE.sub(" ", sentence)))
    if not words:
        return 1.0
    have = set(_stems(passage))
    return sum(w in have for w in words) / len(words)


# What a document statement says is included in, or left out of, something must agree with its cited passage (I-8).
# `support` cannot see this: "includes" and "excludes" share every other word (held-out v5 Y20 said operational demand
# "includes local demand of scheduled loads …", citing figure text that subtracts them: "… − local demand of …").
_POL_TOKEN_RE = re.compile(r"(?P<w>[A-Za-z][A-Za-z0-9_'’]*)|(?P<minus>−)|(?P<stop>\.(?=\s+[A-Z0-9“\"(•]|\s*$))|"
                           r"(?P<clause>[,;])|(?P<open>\()|(?P<close>\))")
_INCLUDES = {"include", "includes", "included", "including", "comprise", "comprises", "comprised", "comprising",
             "incorporate", "incorporates", "incorporated", "incorporating", "count", "counts", "counted", "counting"}
_EXCLUDES = {"exclude", "excludes", "excluded", "excluding", "omit", "omits", "omitted", "omitting", "subtract",
             "subtracts", "subtracted", "subtracting", "deduct", "deducts", "deducted", "deducting", "minus", "−"}
_EXCLUDES_2 = {("net", "of"), ("leave", "out"), ("leaves", "out"), ("left", "out"), ("leaving", "out")}
_PARTICIPLES = {"included", "excluded", "counted", "omitted", "subtracted", "deducted", "comprised", "incorporated"}
_BE = {"is", "are", "was", "were", "be", "been", "being"}
_NEGATORS = {"not", "never", "no", "without"}
_ADVERBS = {"also", "generally", "explicitly", "therefore", "only", "always", "usually", "typically", "then"}
_AUX = _BE | {"do", "does", "did", "has", "have", "had", "can", "could", "may", "might", "will", "would", "should", "must",
              "shall"}
_NOT_NEGATING = {"only", "just", "merely", "simply"}  # "not only includes" includes
_SENTENTIAL_NEG = [("not", "the", "case", "that"), ("not", "true", "that"), ("untrue", "that"), ("false", "that")]
# words that start another clause: inclusion or exclusion wording before them does not govern what follows them
_CLAUSE_WORDS = {"which", "that", "who", "whose", "where", "when", "while", "whereas", "because", "although", "though",
                 "if"} | _BE | {"has", "have", "had"}
_PREPOSITIONS = {"in", "of", "for", "at", "on", "by", "from", "with", "to", "within", "across", "over", "under", "into"}
_SUBJECT_VERBS = {"differs", "differ", "means", "mean", "refers", "refer", "represents", "represent", "reflects",
                  "describes", "measures", "covers", "comprises", "consists"}
_PRONOUNS = {"it", "they", "this", "these", "those", "its", "their", "them"}
_OBJECT_END = {"such", "e", "eg", "for", "but", "while", "whereas", "which", "that", "because", "since", "as", "is", "are",
               "was", "were", "has", "have", "had", "can", "could", "may", "might", "will", "would", "should", "must",
               "does", "do", "did"}
_UNSTATED_RE = re.compile(r"\b(?:whether|unclear|not clear|(?:does|do|did) not (?:say|state|specify|define|mention)|"
                          r"not (?:stated|specified|defined|mentioned))\b", re.I)
POLARITY_MIN = 0.6  # share of what a statement says is included or excluded that must appear together in the passage


@dataclass
class _Tok:
    kind: str
    text: str  # lower case
    raw: str
    quoted: bool


def _pol_tokens(text: str) -> list[_Tok]:
    spans = [m.span() for m in QUOTED_RE.finditer(text)]
    out = []
    for m in _POL_TOKEN_RE.finditer(text.replace("’", "'")):
        kind = m.lastgroup or "w"
        out.append(_Tok(kind, m.group().lower(), m.group(), any(a <= m.start() < b for a, b in spans)))
    return out


def _cue(toks: list[_Tok], i: int) -> tuple[bool, int] | None:
    """(includes?, index after the cue) when token i starts inclusion or exclusion wording, else None."""
    t = toks[i].text
    nxt = toks[i + 1].text if i + 1 < len(toks) and toks[i + 1].kind == "w" else ""
    if (t, nxt) in _EXCLUDES_2:
        return False, i + 2
    if t in _EXCLUDES:
        return False, i + 1
    if t in _INCLUDES:
        return True, i + 1
    return None


def _negated(toks: list[_Tok], i: int) -> bool:
    """A negation of the wording at token i: right before it, past adverbs only ("does not include", "is not explicitly
    counted", "isn't included", "no longer includes"). "Not only includes" is no negation, and a negation of another
    word ("loads not curtailed are included") is not this one's. "It is not the case that …" negates what follows."""
    j = i - 1
    while j >= 0 and toks[j].kind == "w" and toks[j].text in _ADVERBS | {"longer"}:
        j -= 1
    near = j >= 0 and toks[j].kind == "w" and (toks[j].text in _NEGATORS or toks[j].text.endswith("n't")) and \
        not (j + 1 < i and toks[j + 1].text in _NOT_NEGATING)
    k = i - 1
    while k >= 0 and toks[k].kind != "stop":
        if any([t.text for t in toks[k:k + len(pat)]] == list(pat) for pat in _SENTENTIAL_NEG):
            return not near
        k -= 1
    return near


def _np_keys(toks: list[_Tok], j: int, step: int) -> list[str]:
    """The keys of the noun phrase that ends (step -1) or starts (step 1) at token j, up to a clause word, a
    preposition, a verb or punctuation."""
    out: list[str] = []
    while 0 <= j < len(toks) and toks[j].kind == "w" and len(out) < 6:
        t = toks[j].text
        if t in _CLAUSE_WORDS | _PREPOSITIONS | _AUX | _SUBJECT_VERBS | {"but", "and", "or", "than", "as", "unlike",
                                                                          "like"} or _cue(toks, j) is not None:
            break
        if key := _key(toks[j].raw):
            out.append(key)
        elif t in _PRONOUNS:
            out.append(t)
        j += step
    return out[::-1] if step < 0 else out


def _subject(toks: list[_Tok], kc: int) -> list[str]:
    """What the inclusion or exclusion wording at token kc is about: for a passive one, the measure after it ("is
    included in operational demand"); else the noun phrase right before it, or, when that is a pronoun or absent ("…,
    excluding", "it excludes"), the one that opens the sentence. Empty when none is found."""
    be = _passive(toks, kc)
    if be is not None:
        j = kc + (2 if toks[kc].text == "left" else 1)
        while j < len(toks) and toks[j].kind == "w" and toks[j].text in _PREPOSITIONS | {"the", "a", "an"}:
            j += 1
        return _np_keys(toks, j, 1)
    j = kc - 1
    while j >= 0 and toks[j].kind == "w" and (toks[j].text in _AUX | _ADVERBS | _NEGATORS | {"longer", "both", "all"}
                                               or toks[j].text.endswith("n't")):
        j -= 1
    near = _np_keys(toks, j, -1)
    if near and not set(near) <= _PRONOUNS:
        return [k for k in near if k not in _PRONOUNS]
    j = kc - 1
    while j > 0 and toks[j - 1].kind != "stop":
        j -= 1
    while j < kc and toks[j].kind != "w":
        j += 1
    return [k for k in _np_keys(toks, j, 1) if k not in _PRONOUNS]


def _other_subject(a: list[str], b: list[str]) -> bool:
    """Two noun phrases with the same head and different qualifiers ("native demand", "operational demand"): definitely
    about different things. Anything less certain counts as the same."""
    if not a or not b or a[-1] != b[-1]:
        return False
    qa, qb = set(a[:-1]), set(b[:-1])
    return bool(qa) and bool(qb) and qa.isdisjoint(qb)


def _passive(toks: list[_Tok], i: int) -> int | None:
    """For a participle cue ("are not counted"), the index of its be-verb, else None."""
    if toks[i].text not in _PARTICIPLES and not (toks[i].text == "left" and i + 1 < len(toks) and toks[i + 1].text == "out"):
        return None
    j = i - 1
    while j >= 0 and toks[j].kind == "w" and (toks[j].text in _NEGATORS or toks[j].text in _ADVERBS
                                               or toks[j].text.endswith("n't")):
        j -= 1
    return j if j >= 0 and toks[j].kind == "w" and (toks[j].text in _BE or toks[j].text.rstrip("n't") in _BE) else None


def _acronym(raw: str) -> bool:
    core = raw[:-1] if raw.endswith("s") and raw[:-1].isupper() else raw
    return 2 <= len(core) <= 6 and core.isupper() and core.isalpha()


def polarity_claims(text: str) -> list[tuple[bool, list[_Tok], list[_Tok], list[str]]]:
    """(includes?, what, its parenthetical other name, what it is said of) for each inclusion or exclusion a statement
    makes, read outside quotations with negation applied. A statement that something is unstated or unclear makes
    none."""
    body = CITE_RE.sub(" ", text)
    if _UNSTATED_RE.search(QUOTED_RE.sub(" ", body)):
        return []
    toks = _pol_tokens(body)
    out = []
    i = 0
    while i < len(toks):
        cue = None if toks[i].quoted or toks[i].kind not in ("w", "minus") else _cue(toks, i)
        if cue is None:
            i += 1
            continue
        includes, after = cue
        if _negated(toks, i):
            includes = not includes
        be = _passive(toks, i)
        what: list[_Tok] = []
        alt: list[_Tok] = []
        if be is not None:  # "scheduled loads are not counted …": what comes before the be-verb
            j = be - 1
            while j >= 0 and toks[j].kind == "w" and toks[j].text not in ("that", "which", "who") and len(what) < 8:
                what.insert(0, toks[j])
                j -= 1
        else:  # "excludes the demand of local scheduled loads …": what follows, to the end of the clause
            j, depth = after, 0
            while j < len(toks) and len(what) < 12:
                t = toks[j]
                if t.kind == "open":
                    depth += 1
                elif t.kind == "close":
                    depth = max(0, depth - 1)
                elif t.kind in ("stop", "clause") or (t.kind == "w" and not depth and
                                                      (t.text in _OBJECT_END or _cue(toks, j) is not None)):
                    break
                elif t.kind == "w":
                    (alt if depth else what).append(t)
                j += 1
        # one plain word ("includes scheduled, semi-scheduled …", cut at the comma) names too little to check
        if len(_stem_set(what)) >= 2 or any(_acronym(t.raw) or _identifier(t.raw) for t in what):
            out.append((includes, what, alt, _subject(toks, i)))
        i = after
    return out


def _key(raw: str) -> str | None:
    """A word's matching key: a field name whole ("operational_demand_poe10"), else its first five letters without a
    footnote number ("loads10") or plural ending ("loads" and "load", "losses" and "loss" match); None for short and
    stop words."""
    word = raw.lower()
    if "_" in word:
        return word
    if not raw.isupper() and re.fullmatch(r"[a-z]{4,}\d{1,2}", word):
        word = word.rstrip("0123456789")
    if len(word) <= 2 or word in SUPPORT_STOP:
        return None
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word[:5]


def _identifier(raw: str) -> bool:
    return "_" in raw or (raw.isupper() and any(ch.isdigit() for ch in raw))


def _stem_set(toks: list[_Tok]) -> set[str]:
    return {key for t in toks if (key := _key(t.raw))}


def passage_polarity(passage: str, what: list[_Tok], alt: Sequence[_Tok] = (),
                     subject: Sequence[str] = ()) -> tuple[float, set[bool], str]:
    """How fully the passage mentions ``what`` (0–1), the inclusion or exclusion wording that governs its best mentions,
    and a short excerpt of the first mention that has one. The governing wording is a passive one right after the
    mention, or else the nearest one before it in the same clause, with negation. Wording said of a definitely
    different ``subject`` (another measure) is not counted."""
    toks = _pol_tokens(passage)
    words = [k for k, t in enumerate(toks) if t.kind == "w"]
    keys = {k: _key(toks[k].raw) for k in words}
    order: list[str] = []  # the keys of ``what``, in order
    for t in what:
        if _acronym(t.raw):  # an acronym matches its spelled-out words in the passage ("WDR": Wholesale Demand Response)
            letters = (t.raw[:-1] if t.raw.endswith("s") and t.raw[:-1].isupper() else t.raw).lower()
            run = next(([toks[words[a + b]].raw for b in range(len(letters))] for a in range(len(words) - len(letters) + 1)
                        if "".join(toks[words[a + b]].text[0] for b in range(len(letters))) == letters), None)
            if run:
                order += [key for w in run if (key := _key(w))]
                continue
        if key := _key(t.raw):
            order.append(key)
    named = [key for t in what if _identifier(t.raw) and (key := _key(t.raw))]  # field names, when given, are what counts
    target, others = set(named or order), _stem_set(list(alt))
    if not target:
        return 1.0, set(), ""
    # each mention starts where the passage has the first of those keys it contains, so the wording that governs it
    # is read from just before it ("… − local demand of …"); it extends to the next inclusion or exclusion wording,
    # which starts another phrase
    anchor = next((s for s in (named or order) if any(keys[k] == s for k in words)), None)
    width = 2 * len(what) + 4
    best, starts = 0.0, []

    def phrase(k0: int, step: int, limit: int) -> set[str]:
        out: set[str] = set()
        k, n = k0, 0
        while 0 <= k < len(toks) and n < limit and toks[k].kind != "stop" and \
                (k == k0 or toks[k].kind not in ("w", "minus") or _cue(toks, k) is None):
            if toks[k].kind == "w":
                out.add(keys[k] or "")
                n += 1
            k += step
        return out

    for k0 in words:
        if keys[k0] != anchor:
            continue
        seen = phrase(k0, 1, width) | phrase(k0 - 1, -1, 2) if k0 > 0 and _cue(toks, k0 - 1) is None else phrase(k0, 1, width)
        cov = min(1.0, len((target | others) & seen) / len(target))
        if cov > best + 1e-9:
            best, starts = cov, [k0]
        elif abs(cov - best) <= 1e-9:
            starts.append(k0)
    if best < POLARITY_MIN:
        return best, set(), ""
    found: set[bool] = set()
    excerpt = ""
    foreign = 0  # mentions whose wording is said only of another measure, in a sentence that does not name ours
    for s in starts:
        pol = None
        k, ahead = s + 1, 1  # a passive right after it: "… scheduled loads are excluded"
        while k < len(toks) and ahead <= len(what) + 3 and toks[k].kind == "w":
            if _passive(toks, k) is not None and (c := _cue(toks, k)) is not None:
                pol = c[0] != _negated(toks, k)
                break
            k, ahead = k + 1, ahead + 1
        if pol is None:
            k, back = s - 1, 0
            while k >= 0 and back < 12 and toks[k].kind != "stop":
                c = _cue(toks, k) if toks[k].kind in ("w", "minus") else None
                if c is not None:
                    pol = c[0] != _negated(toks, k)
                    break
                if toks[k].text in _CLAUSE_WORDS or (toks[k].text == "as" and (k == 0 or toks[k - 1].text != "such")):
                    break  # "… includes reports that name X": X is not what "includes" governs
                back += toks[k].kind == "w"
                k -= 1
        if pol is not None and _other_subject(list(subject), _subject(toks, k)):
            pol = None  # said of another measure ("operational demand … excludes" read for "native demand")
            a = k
            while a > 0 and toks[a - 1].kind != "stop":
                a -= 1
            b = k
            while b < len(toks) and toks[b].kind != "stop":
                b += 1
            foreign += not set(subject) <= {key for t in toks[a:b] if t.kind == "w" and (key := _key(t.raw))}
        if pol is not None:
            found.add(pol)
            if not excerpt:
                excerpt = " ".join(t.raw for t in toks[max(k, 0):s + width] if t.kind in ("w", "minus"))[:110]
    if foreign == len(starts):
        return 0.0, set(), ""  # the passage speaks of it only for another measure: it does not support this statement
    return best, found, excerpt


def _items(what: list[_Tok]) -> list[list[_Tok]]:
    """A list's items ("scheduled loads and scheduled BDUs"); an item of one word joins the next ("scheduled and
    semi-scheduled generation" is one)."""
    parts: list[list[_Tok]] = [[]]
    for t in what:
        if t.text in ("and", "or"):
            parts.append([])
        else:
            parts[-1].append(t)
    out: list[list[_Tok]] = []
    carry: list[_Tok] = []
    for part in parts:
        carry += part
        if len(_stem_set(carry)) >= 2:
            out.append(carry)
            carry = []
    if carry:
        (out[-1].extend(carry) if out else out.append(carry))
    return out


def polarity_violations(where: str, text: str, passages: dict[str, tuple[str, str]], *,
                        contradictions_only: bool = False) -> list[Violation]:
    """``passages``: citation ID -> (chunk ID, passage text) for the passages the statement cites. A listed item counts
    as contradicted when a cited passage mentions it, with only the opposite wording; the statement is unsupported when
    no cited passage mentions any of its items."""
    out = []
    for includes, what, alt, subject in polarity_claims(text):
        said = " ".join(t.raw for t in what if t.text not in ("and", "or") or t is not what[-1])
        any_mentioned, against = False, None
        for item in _items(what):
            seen = {cid: passage_polarity(p, item, alt, subject) for cid, (_, p) in passages.items()}
            mentioned = {cid: r for cid, r in seen.items() if r[0] >= POLARITY_MIN}
            any_mentioned = any_mentioned or bool(mentioned)
            if against is None and mentioned and not any(includes in r[1] for r in mentioned.values()):
                against = next(((cid, item, r[2]) for cid, r in mentioned.items() if (not includes) in r[1]), None)
        if not any_mentioned and not contradictions_only:
            out.append(Violation("DOC_CLAIM_UNSUPPORTED", "critical",
                                 f"{where}: says “{said}” is {'included' if includes else 'left out'}, but its cited "
                                 "passage does not mention it"))
        elif against:
            cid, item, excerpt = against
            out.append(Violation("DOC_CLAIM_CONTRADICTED", "critical",
                                 f"{where}: says “{' '.join(t.raw for t in item)}” is "
                                 f"{'included' if includes else 'left out'}, but [{cid}] ({passages[cid][0]}) "
                                 f"{'leaves it out' if includes else 'includes it'}: “{excerpt}”"))
    return out


def validate(report: InvestigationReport, registry: EvidenceRegistry, *, as_of: datetime | None = None,
             window: tuple[datetime, datetime] | None = None, records: list[Any] | None = None,
             forecast_run: dict[str, Any] | None = None, demand_max: list[dict[str, Any]] | None = None,
             required_tools: tuple[str, ...] = (), event_kind: str | None = None,
             approval_records: Sequence[Any] = ()) -> ValidationResult:
    """``approval_records``: approval records (``approvals.Approval``) that belong to this answer. An investigation
    never has one, so the service passes none and every action claim fails."""
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
    cited_chunk = {c.citation_id: c.chunk_id for c in report.citations}

    def titles(text: str) -> frozenset[str]:
        """Titles whose digits are not numbers in this narrative item: those of the notices the report cites. When the
        item carries citation markers, only the notices they point to count, so a title next to a citation of another
        notice (or of nothing the report cites) is read like any other text. Evidence markers ([ev0436]) are not
        citations."""
        marks = [m for m in CITE_RE.findall(text) if not re.fullmatch(r"ev\d{4}", m)]
        return notice_titles(registry, {cited_chunk.get(m, m) for m in marks} & set(cited_chunk.values()) if marks
                             else cited_chunk.values())
    for where, text in _narratives(report):
        for n in narrative_numbers(text, chunk_ids, titles(text)):
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
        elif ch.instruction_like:
            # a flagged passage is untrusted as a whole: citing any sentence of it, even a harmless-looking one,
            # presents injected text as a source (W20 audit: "Operational demand is what this glossary defines.")
            V.append(Violation("INJECTION_QUOTED_AS_EVIDENCE", "critical",
                               f"{cit.citation_id}: cites {cit.chunk_id}, a passage flagged as instruction-like; "
                               "remove this citation and anything taken from it"))

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
            for n in narrative_numbers(sentence, chunk_ids, titles(text)):
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

    # -- each traced number's stated time must be the time of the evidence supporting it, number by number (I-15)
    res.checks_run.append("claim_times")
    for where, text in _narratives(report) + _hypothesis_tests(report):
        for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
            V.extend(claim_time_violations(where, sentence, report, registry, chunk_ids, titles(text)))

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
            for n in narrative_numbers(sentence, chunk_ids, titles(text)):
                resolutions = {ev.interval_minutes for c in report.numeric_claims
                               if (ev := registry.get(c.evidence_id)) is not None and ev.interval_minutes
                               and (abs(n - c.value) <= c.rounding + 1e-9 or abs(abs(n) - abs(c.value)) <= c.rounding + 1e-9)}
                if resolutions and not resolutions & named:
                    V.append(Violation("CLAIM_INTERVAL_MISMATCH", "critical",
                                       f"{where}: {n:g} is stated as a {'/'.join(f'{m}-minute' for m in sorted(named))} "
                                       f"value but its evidence is {'/'.join(f'{m}-minute' for m in sorted(resolutions))}"))

    # -- every quotation of three or more words must be verbatim in a cited passage (the gap found in the PR #5 review:
    #    a wholly quoted sentence with a valid citation passed even when the passage did not contain it). Findings are
    #    checked below against their own citation.
    res.checks_run.append("narrative_quotes")
    cited_text = {cid: registry.chunks[c.chunk_id].text for cid, c in cites.items() if c.chunk_id in registry.chunks}
    for where, text in _narratives(report) + _hypothesis_tests(report):
        if where.startswith("published_findings"):
            continue
        for q in QUOTED_RE.findall(text):
            q = q.strip("“”\"").strip()
            if len(WORD_RE.findall(q.lower())) < 3:
                continue
            quote_ids = [c for c in CITE_RE.findall(text) if c in cited_text] or list(cited_text)
            if not any(_norm(q) in _norm(cited_text[c]) for c in quote_ids):
                scope = "its cited passage" if CITE_RE.search(text) and quote_ids else "any cited passage"
                V.append(Violation("QUOTE_NOT_IN_SOURCE", "critical", f"{where}: the quotation “{q[:70]}” is not in {scope}"))

    # -- a question that names one demand measure is not answered with the other (held-out H02, H03: asked for total
    #    demand, answered with operational demand only), unless the answer says the named measure is unavailable
    if report.intent in ("market_event_review", "forecast_review"):
        from .agent.request import OPERATIONAL_DEMAND_Q_RE, TOTAL_DEMAND_Q_RE

        res.checks_run.append("requested_measure")
        claim_metrics = {ev.metric for c in report.numeric_claims if (ev := registry.get(c.evidence_id)) is not None}
        has_total = "dispatch_totaldemand" in claim_metrics
        has_op = any(m.startswith("opdemand") for m in claim_metrics)
        said = " ".join(report.missing_evidence + report.uncertainties)
        q = report.question
        if TOTAL_DEMAND_Q_RE.search(q) and not OPERATIONAL_DEMAND_Q_RE.search(q) and has_op and not has_total \
                and not TOTAL_DEMAND_Q_RE.search(said):
            V.append(Violation("MEASURE_SUBSTITUTED", "critical", "the question asks for total demand (dispatch "
                               "TOTALDEMAND) but the answer gives only operational demand"))
        if OPERATIONAL_DEMAND_Q_RE.search(q) and not TOTAL_DEMAND_Q_RE.search(q) and has_total and not has_op \
                and not OPERATIONAL_DEMAND_Q_RE.search(said):
            V.append(Violation("MEASURE_SUBSTITUTED", "critical", "the question asks for operational demand but the "
                               "answer gives only dispatch TOTALDEMAND"))

    # -- cancelled notices: a hypothesis may not rest, as if it were active, on a notice that a later retrieved notice
    #    cancelled before the price extreme (held-out v4 W19 leaned on three SA reserve forecasts cancelled on 27 and
    #    28/07 for a spike on 29/07); saying it was cancelled is allowed
    if report.intent == "market_event_review":
        res.checks_run.append("cancelled_notices")
        et = _event_times(report, registry, window, event_kind)
        limit = et.peak if et is not None and et.peak is not None else (window[1] if window else None)
        gone = {c: v for c, v in cancelled_notice_chunks(registry).items() if limit is None or v[1] <= limit}
        for i, h in enumerate(report.possible_explanations):
            if not gone or re.search(r"\bcancel", h.statement, re.I):
                continue
            for ref in dict.fromkeys(CITE_RE.findall(h.statement)):
                relied_on = cites.get(ref)
                if relied_on is not None and relied_on.chunk_id in gone:
                    canceller, cancelled_at = gone[relied_on.chunk_id]
                    V.append(Violation("CANCELLED_NOTICE_AS_ACTIVE", "critical",
                                       f"possible_explanations[{i}]: rests on {relied_on.chunk_id} [{ref}], but "
                                       f"{canceller} cancelled it at {iso_utc(cancelled_at)}, before the price extreme; "
                                       "say it was cancelled, or drop it"))

    # -- explanations ruled out by timing: a hypothesis may not rest on a cited market notice whose earliest stated time
    #    comes after every interval of the event, as if what it reports could explain the event (Live check
    #    2026-09-30, W18: the answer opened with "Timing rules this out" for the Hazelwood bus-tie outage at 1100 hrs
    #    20/08, after all six high-price intervals, and a hypothesis still offered it as a possible influence). Saying
    #    the timing rules it out is allowed. Only the unambiguous case counts: a notice with no stated time, a time before
    #    or within the event, or prices not registered up to that time are left alone.
    #    I-7b (second development check, W18): a hypothesis that only denies or doubts the incident's bearing ("might not
    #    correspond to the price spike") offers no influence and is not flagged. A statement that the timing rules the
    #    incident out, where every market notice it cites meets this timing condition, is an exclusion the evidence
    #    backs; the language check below does not require it to be hedged (the repair this rule asks for said exactly
    #    that and was rejected as unhedged, so the answer fell back).
    ruled_out_by_timing: set[int] = set()
    if report.intent == "market_event_review":
        res.checks_run.append("ruled_out_by_timing")
        et = _event_times(report, registry, window, event_kind)
        w = window or ((parse_iso(report.event_window.start_utc), parse_iso(report.event_window.end_utc))
                       if report.event_window else None)
        spans = et.ends["high" if et.kind == "high_price" else "low"] if et is not None else []
        for i, h in enumerate(report.possible_explanations):
            if et is None or w is None or not spans:
                continue
            after: list[tuple[str, Any, datetime]] = []  # cited notices of the region timed after every interval
            not_after = False  # a cited market notice whose timing does not rule the incident out
            for ref in dict.fromkeys(CITE_RE.findall(h.statement)):
                rested = cites.get(ref)
                notice = registry.chunks.get(rested.chunk_id) if rested is not None else None
                if notice is None or notice.doc_type != "market_notice":
                    continue
                stated_at = _notice_instants(notice.text, notice.event_date)
                earliest = min(stated_at) if stated_at else None
                if notice.event_region not in (None, report.region) or earliest is None or earliest <= spans[-1] or \
                        not et.complete or et.last is None or et.last < min(earliest, w[1]):
                    not_after = True
                    continue
                after.append((ref, notice, earliest))
            if RULED_OUT_RE.search(h.statement):
                if after and not not_after:
                    ruled_out_by_timing.add(i)
                    # I-7c: a pure exclusion (no hedge outside the rule-out wording) is a conclusion, not a hypothesis
                    if not HEDGE_RE.search(RULED_OUT_RE.sub(" ", QUOTED_RE.sub(" ", h.statement))):
                        res.ruled_out.append(i)
                continue
            if doubts_bearing(h.statement):
                continue
            for later_ref, later, first_time in after:
                V.append(Violation("EXPLANATION_RULED_OUT_BY_TIMING", "critical",
                                   f"possible_explanations[{i}]: rests on {later.chunk_id} [{later_ref}], whose earliest "
                                   f"stated time ({iso_utc(first_time)}) is after every interval of the event (the last ends "
                                   f"{iso_utc(spans[-1])}), so its timing rules this out; drop it, or say that the "
                                   "timing rules it out"))

    # -- notice timing in market-event reviews. Every sentence (headline, summary, hypotheses, uncertainties; not a
    #    quote, a hypothesis's test or a "whether"/"if" clause) that sets a retrieved notice's time before, between or
    #    after the event's price intervals, its price extreme or a stated time is checked against the notice's own
    #    time and the dispatch prices registered in this investigation, in UTC whatever zone is written. A wrong
    #    direction or a wrong interval time is NOTICE_TIMING_CONTRADICTED; a comparison the registered prices cannot
    #    settle is NOTICE_TIMING_UNVERIFIED. When the question asks whether something a notice reports explains the
    #    event, some sentence must set a cited notice's time against the event (held-out H13 never did).
    if report.intent == "market_event_review":
        from .agent.request import asks_if_notice_event_caused

        res.checks_run.append("notice_timing")
        cited: dict[datetime, str] = {}
        for cit in report.citations:
            ch = registry.chunks.get(cit.chunk_id)
            if ch is not None and ch.doc_type == "market_notice" and ch.event_region in (None, report.region):
                for t in sorted(_notice_instants(ch.text, ch.event_date)):
                    cited.setdefault(t, ch.doc_id)
        # only the notices the answer cites are compared (v3 V18 was matched against a notice it did not cite), and an
        # undated clock only against those near the event window
        w = window or ((parse_iso(report.event_window.start_utc), parse_iso(report.event_window.end_utc))
                       if report.event_window else None)
        notices = set(cited)
        near = {t for t in notices if w is None or w[0] - timedelta(days=1) <= t <= w[1] + timedelta(days=1)}
        stated: set[datetime] = set()
        if notices:
            et = _event_times(report, registry, window, event_kind)
            texts = [*_headlines(report), *((f"summary[{i}]", x) for i, x in enumerate(report.summary)),
                     *((f"possible_explanations[{i}]", h.statement) for i, h in enumerate(report.possible_explanations)),
                     *((f"uncertainties[{i}]", x) for i, x in enumerate(report.uncertainties))]
            for where, text in texts:
                for sentence in TIMING_SENTENCE_RE.split(QUOTED_RE.sub(" ", text)):
                    if HYPOTHETICAL_RE.search(sentence):
                        continue  # "whether …" and "if …" state nothing (v3 V18's uncertainty was read as a claim)
                    V.extend(_zone_slips(where, sentence, notices, near, report.region))
                    got, found = _timing_statements(where, sentence, notices, near, et)
                    stated |= got
                    V.extend(found)
        if asks_if_notice_event_caused(report.question) and cited and not stated & set(cited):
            shown = ", ".join(f"{d} {_z(t)}" for t, d in sorted(cited.items()))
            V.append(Violation("NOTICE_TIMING_OMITTED", "critical",
                               "the question asks whether something a cited market notice reports explains the "
                               f"event, but no sentence sets the notice's time ({shown}) against the event (before, "
                               "between or after its intervals)"))

    # -- document claims: cited, and supported by the cited passage (quoted, or mostly in its words)
    res.checks_run.append("document_claims")
    items = _headlines(report) + [(f"summary[{i}]", s_) for i, s_ in enumerate(report.summary)]
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
    # what a document answer says is included in or left out of something agrees with what it cites (I-8); a headline
    # without a citation is read against every cited passage, for contradictions only
    if report.intent == "source_explanation":
        res.checks_run.append("document_polarity")
        cited_passages = {cid: (c.chunk_id, registry.chunks[c.chunk_id].text) for cid, c in cites.items()
                          if c.chunk_id in registry.chunks}
        for where, text in items:
            cited_ids = [c for c in CITE_RE.findall(text) if c in cited_passages]
            if cited_ids:
                V.extend(polarity_violations(where, text, {c: cited_passages[c] for c in cited_ids}))
            elif where == "headline" and cited_passages:
                V.extend(polarity_violations(where, text, cited_passages, contradictions_only=True))

    # -- the forecast run a question names, for the half-hour it asks about (I-9): every forecast value shown or cited
    #    for that half-hour comes from that run, and when no such run is held none is given (held-out v5 Y05 and Y06
    #    gave the run available by then, issued three hours earlier, as the one asked for)
    if forecast_run and forecast_run.get("half_hour_end_utc"):
        res.checks_run.append("requested_forecast_run")
        hh_end = parse_iso(str(forecast_run["half_hour_end_utc"]))
        want = forecast_run.get("run_id")
        # why no run is bound: none holds the half-hour, or two cannot be told apart (I-16)
        none = str(forecast_run.get("unavailable") or "no run the question asks for holds this half-hour").rstrip(".")
        none = none[0].lower() + none[1:]
        used = {o.evidence_id for o in report.observations} | {c.evidence_id for c in report.numeric_claims}
        # a mean (absolute) error over a comparison whose pairs include another run for the half-hour is not this run's
        # error, whether shown, cited or given as the comparison (I-9 review: such figures carry no source rows)
        windowed: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        for r in records or []:
            view = r.view if getattr(r, "name", None) == "compare_forecast_actual" and r.status == "ok" else {}
            for key in ("mae_mw", "mean_error_mw"):
                if eid_ := (view.get(key) or {}).get("evidence_id"):
                    windowed[eid_] = (key, view.get("pairs") or [])
        fc = report.forecast_comparison
        figures = used | {e for e in ((fc.mae_evidence_id, fc.mean_error_evidence_id) if fc else ()) if e}
        for eid in sorted(figures & set(windowed)):
            key, pairs = windowed[eid]
            at = [pr for pr in pairs if parse_iso(pr["target_end_utc"]) == hh_end]
            if at and any(not want or pr.get("run_id") != want for pr in at):
                V.append(Violation("FORECAST_RUN_SUBSTITUTED", "critical",
                                   f"{eid}: {key} over {len(pairs)} half-hour(s) includes another forecast run for the "
                                   f"half-hour ending {iso_utc(hh_end)}, so it is not the error of " +
                                   (f"the run the question asks for ({want})" if want else
                                    f"a run the question asks for: {none}")))
        for eid in sorted(used):
            ev = registry.get(eid)
            if ev is None or not ev.valid_at_utc or parse_iso(ev.valid_at_utc) != hh_end:
                continue
            runs = [r for r in ev.source_row_ids if r.startswith("OPDEM_FORECAST")]
            if runs and (not want or not any(str(want) in r for r in runs)):
                V.append(Violation("FORECAST_RUN_SUBSTITUTED", "critical",
                                   f"{eid}: {ev.metric} for the half-hour ending {iso_utc(hh_end)} comes from another "
                                   "forecast run; " + (f"the question asks for the run issued "
                                                       f"{forecast_run.get('issued_at_utc')} ({want})" if want else
                                                       f"{none}, so no forecast value may stand in for it")))

    # -- a demand measure's maximum the question asks for (I-17): the answer gives the maximum the controller computed
    #    over the requested window, and a sentence stating the measure's maximum uses no other value (held-out v6 Z04
    #    answered "when did total demand peak" with TOTALDEMAND at the price peak and operational demand's maximum)
    texts = [(where, s) for where, text in _narratives(report) + _hypothesis_tests(report)
             for s in SENTENCE_RE.split(QUOTED_RE.sub(" ", text))]
    mismatched: set[tuple[str, float]] = set()
    if demand_max:
        res.checks_run.append("requested_maximum")
        found = requested_max_violations(report, registry, demand_max, texts,
                                         lambda s: number_spans(s, chunk_ids, titles(s)))
        V.extend(found)
        mismatched = {(hit.group(1), float(hit.group(2))) for v in found if v.code == "REQUESTED_MAXIMUM_MISMATCH"
                      and (hit := re.match(r"([^:]+): (-?[\d.]+) is stated", v.detail))}
    # -- bounded answer-side backstops for requests whose wording was not recognised (I-18)
    if report.intent in ("market_event_review", "forecast_review") and \
            report.status not in ("needs_clarification", "refused"):
        res.checks_run.append("request_backstops")
        V.extend(backstop_violations(report, registry, records, demand_max, forecast_run, texts,
                                     lambda s: number_spans(s, chunk_ids, titles(s)), mismatched, window))

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
            if int(where[len("possible_explanations["):-1]) in ruled_out_by_timing:
                # an exclusion the validated notice timing backs (I-7b): no hedge word needed, and no cause asserted
                if (asserted := caveat_causal_claim(bare)) is not None:
                    V.append(Violation("HYPOTHESIS_UNHEDGED", "critical", f"{where}: asserts '{asserted}' without "
                                       "hedging"))
            else:
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
    caveats = ([(f"uncertainties[{i}]", u) for i, u in enumerate(report.uncertainties)]
               + [(f"missing_evidence[{i}]", u) for i, u in enumerate(report.missing_evidence)])
    for where, text in caveats:
        if (cause := caveat_causal_claim(text)) is not None:
            V.append(Violation("UNSUPPORTED_CAUSALITY", "critical", f"{where}: causal claim '{cause}' stated as a caveat"))
        if caveat_echo(text, records):
            V.append(Violation("INJECTION_ECHO", "critical", f"{where}: contains instruction-like text"))

    # -- action claims: every text the model writes, including uncertainties and missing evidence (quoted text too)
    res.checks_run.append("action_claims")
    if not any(getattr(a, "approval_id", None) for a in approval_records):
        for where, text in (_narratives(report) + _hypothesis_tests(report)
                            + [(w, _QUOTE_MARKS_RE.sub(" ", t)) for w, t in caveats]):
            for claim in action_claims(text):
                V.append(Violation("ACTION_CLAIM_UNRECORDED", "critical",
                                   f"{where}: says “{claim}” but no approval record exists (an investigation cannot "
                                   "approve, write or publish anything); remove the claim"))
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
    """Safe fallback after failed validation: keep only independently valid observations, no narrative. A value from a
    forecast run that stands in for the one asked for is not shown either (I-9)."""
    substituted = {m.group(1) for v in result.critical if v.code == "FORECAST_RUN_SUBSTITUTED"
                   and (m := re.match(r"(ev\d{4})", v.detail))}
    good_obs = []
    for o in report.observations:
        if o.evidence_id in substituted:
            continue
        ev = registry.get(o.evidence_id)
        if ev is None or ev.value is None or abs(o.value - float(ev.value)) > 1e-6 or not metric_compatible(ev):
            continue
        if as_of is not None and (ev.evidence_class == "retrospective_context" or
                                  (ev.available_at_utc and parse_iso(ev.available_at_utc) > as_of)):
            continue
        good_obs.append(o)
    codes = sorted({v.code for v in result.critical})
    named = {m.group(0) for v in result.critical if (m := re.match(r"(?:uncertainties|missing_evidence)\[\d+\]", v.detail))}
    out = report.model_copy(update={
        "headline": ("Validated facts only: the generated narrative failed independent validation "
                     f"({', '.join(codes)}). Observations below are tool values with source rows."),
        "summary": [], "possible_explanations": [], "published_findings": [], "citations": [],
        "numeric_claims": [], "forecast_comparison": None, "observations": good_obs,
        # model-written caveats are kept, except any that a critical violation names or that claims an approval or a
        # write (never shown without a record)
        "uncertainties": [*(u for i, u in enumerate(report.uncertainties)
                            if f"uncertainties[{i}]" not in named and not action_claims(u)),
                          "Narrative withheld because it failed validation."],
        "missing_evidence": [x for i, x in enumerate(report.missing_evidence)
                             if f"missing_evidence[{i}]" not in named and not action_claims(x)],
        "status": "answered_with_caveats" if good_obs else "abstained",
    })
    out._model_headline = None  # withheld with the rest of the narrative
    return out


def merge_repeated_observations(report: InvestigationReport,
                                registry: EvidenceRegistry) -> tuple[InvestigationReport, list[dict[str, Any]]]:
    """Show each row-backed data point once. The registry holds one item per tool call, so the same source row can come
    back under several evidence IDs (live check 2026-09-30: W04's two TOTALDEMAND endpoints, W18's and W19's price
    peaks were each listed twice). Observations are one data point when their evidence agrees on class (not derived),
    metric, region, value, unit, time, interval, the full source-row list and the publication and availability times.
    The first is shown; the others' evidence IDs and labels are returned for the record. Derived values, which rest on
    a computation, and anything that differs in any of these are left as they are. Called only after the whole answer
    has been validated, so nothing is hidden from the checks."""
    kept: list[Any] = []
    first: dict[tuple[Any, ...], Any] = {}
    merged: dict[str, dict[str, Any]] = {}
    for o in report.observations:
        ev = registry.get(o.evidence_id)
        key = None if ev is None or ev.evidence_class == "derived" or not ev.source_row_ids else (
            ev.evidence_class, ev.metric, ev.region, ev.value, ev.unit, ev.valid_at_utc, ev.interval_minutes,
            tuple(ev.source_row_ids), ev.published_at_utc, ev.available_at_utc)
        if key is not None and key in first:
            shown = first[key]
            entry = merged.setdefault(shown.evidence_id, {"shown": shown.evidence_id, "metric": shown.metric,
                                                          "valid_at_utc": shown.valid_at_utc, "also": []})
            entry["also"].append({"evidence_id": o.evidence_id, "label": o.label})
            continue
        if key is not None:
            first[key] = o
        kept.append(o)
    if not merged:
        return report, []
    return report.model_copy(update={"observations": kept}), list(merged.values())


def validate_and_finalize(report: InvestigationReport, registry: EvidenceRegistry, records: list[Any], res: Any,
                          trace: Any) -> InvestigationReport:
    from .agent.playbook import PLAYBOOKS

    window = res.window if res is not None else None
    as_of = res.as_of if res is not None else None
    req = PLAYBOOKS[res.intent].required if res is not None and res.intent else ()
    kind = res.kind if res is not None else None
    run = getattr(res, "forecast_run", None)
    maxima = getattr(res, "demand_max", None)
    first = validate(report, registry, as_of=as_of, window=window, records=records, required_tools=req, event_kind=kind,
                     forecast_run=run, demand_max=maxima)
    info: dict[str, Any] = {"initial": first.as_dict(), "fallback_applied": False,
                            "repair_attempted": bool(report.validation.get("repair_attempted"))}
    final = report
    if first.critical:
        final = facts_only(report, registry, first, as_of)
        second = validate(final, registry, as_of=as_of, window=window, records=records, required_tools=req,
                          event_kind=kind, forecast_run=run, demand_max=maxima)
        info.update(fallback_applied=True, after_fallback=second.as_dict())
    if not first.critical and first.ruled_out:  # the answer is shown: its validated exclusions (I-7c)
        info["ruled_out_explanations"] = first.ruled_out
    info["passed"] = not (first.critical and info.get("after_fallback", {}).get("n_critical", 1))
    info["final_passed"] = (not first.critical) or info.get("after_fallback", {}).get("n_critical", 1) == 0
    final = final.model_copy(update={"validation": {**report.validation, **info}})
    trace.add("validate", "report", passed=not first.critical, n_critical=len(first.critical),
              codes=sorted({v.code for v in first.violations}), fallback=info["fallback_applied"])
    # presentation only, after every check above has run on the complete answer
    final, merged = merge_repeated_observations(final, registry)
    if merged:
        final = final.model_copy(update={"validation": {**final.validation, "observations_merged": merged}})
        trace.add("validate", "observations_merged", merged=merged)
    from .display import plain_display  # presentation only, after validation (I-4)

    final, rewrites = plain_display(final, registry)
    if rewrites:
        final = final.model_copy(update={"validation": {**final.validation, "display_rewrites": rewrites}})
        trace.add("validate", "display_rewrites", n=len(rewrites))
    return final
