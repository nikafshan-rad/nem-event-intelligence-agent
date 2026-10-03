"""Structured request resolution for forecast-run selection and demand maxima (I-18).

The targeted Live check of I-15–I-17 (2026-10-02) showed the I-16 and I-17 bindings engaging only on the wording their
patterns read: "the final forecast run issued ahead of it", "5:30 to 6:00 pm (AEST)", "total demand highest" and "hit
its highest point" left the requests unbound, and wrong runs and maxima were shown. Here each request is resolved from
three sources, and every resolved field records where it came from:
- **explicit request fields** (authoritative; question wording that conflicts with one is shown, never ignored);
- **the existing question parsers** (``request.requested_forecast``, ``half_hour_asked``, ``requested_maxima``,
  ``maximum_window_kind``);
- **the routing model's structured reading** (``RouteDecision.requested``), used only when grounded: its quoted words
  are in the question, the relationship (which bound of a half-hour, which measure's peak, which window) is shown by
  those words, and every time follows from the question's own times, dates and zones by a recorded conversion. A
  keyword alone establishes nothing.

A request is **absent**, **bound** (every required field resolved), **unresolved** (detected, but a required field is
missing) or in **conflict** (two readings disagree after normalising dates, times and zones to UTC instants). It is
detected by any source, or by a conservative lexical cue with contextual controls. A missing ``requested`` field
(every historical route, and Replay mode) means "not reported", never "no requirement". A detected request that is
not bound is sent back with a clarification naming the missing or conflicting field; it never proceeds unbound.

The cues and the answer-side backstops (``demand_extreme_clause``, ``run_selection_clause``) are lexical safeguards
with a bounded vocabulary: they do not recognise every paraphrase.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ..timeutil import UTC, iso_utc, local_day_window, parse_iso, region_zone
from .request import (
    _EVENT_WINDOW_RE,
    _SUB_WINDOW_RE,
    AS_OF_Q_RE,
    HALF_HOUR_CLARIFICATION,
    MAXIMUM_CLARIFICATION,
    MAXIMUM_EVENT_CLARIFICATION,
    MAXIMUM_WINDOW_CLARIFICATION,
    MONTHS,
    OPERATIONAL_DEMAND_Q_RE,
    TOTAL_DEMAND_Q_RE,
    ForecastRequest,
    InvestigateRequest,
    extract_dates,
    forecast_issue_time,
    maximum_window_kind,
    requested_forecast,
    requested_maxima,
)
from .route_v12 import RoutedRequest as RoutedRequestV12

# ------------------------------------------------------------------------------------------------ the routed schema


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# The forecast run a question asks for (route contract v13): the rule, and the question's own words for it. Code converts
# every time from those words. (Model-facing schemas carry no docstring: it would enter the schema.)
class RoutedForecastRun(_M):
    selection: Literal["none", "last_issued_before", "issued_at", "as_of_availability", "unclear"] = Field(
        description="the one forecast run the question asks for: last_issued_before = the last run issued before the "
                    "target half-hour starts; issued_at = the run issued at a stated time; as_of_availability = what "
                    "was public or known at a cutoff; none = no specific run is asked for; unclear = one specific run "
                    "is asked for, but which cannot be told")
    selection_text: str | None = Field(
        description="the question's exact words asking for this run, copied verbatim (for issued_at, with the issue "
                    "time as written)")
    half_hour_text: str | None = Field(
        description="the question's exact words naming the target half-hour, copied verbatim (with its clock times, "
                    "and its date and time zone where they are written next to it)")


# The demand maximum a question asks for (route contract v13): what is asked, and the question's own words for the
# measure, the peak and the window. Code builds the window from those words.
class RoutedMaximum(_M):
    kind: Literal["none", "maximum", "unclear"] = Field(
        description="maximum = the question asks when, or at what level, a demand measure reached its maximum over a "
                    "window; none = it does not (demand AT the price peak or in a named interval, the peak price); "
                    "unclear = a demand peak is asked for, but what is meant cannot be told")
    measure: Literal["dispatch_total_demand", "operational_demand", "unspecified"] | None = Field(
        description="dispatch total demand (TOTALDEMAND, 5-minute) or operational demand (half-hourly)")
    measure_text: str | None = Field(description="the question's exact words naming the measure, copied verbatim")
    peak_text: str | None = Field(
        description="the question's exact words asking for the measure's highest level or time, copied verbatim (for "
                    "example 'highest', 'peak', 'how high')")
    window: Literal["whole_local_day", "event", "explicit", "unspecified"] | None = Field(
        description="whole_local_day = one whole local calendar day; event = a price event's window; explicit = a "
                    "start and an end")
    window_text: str | None = Field(description="the question's exact words naming the window, copied verbatim")


class RoutedRequest(_M):
    forecast_run: RoutedForecastRun
    maximum: RoutedMaximum


def requested_from_v12(r: RoutedRequestV12) -> RoutedRequest:
    """A v12 reading in the v13 form. Its timestamps are not read: code converts every time from the quoted words
    (D26). Its ``measure_text`` asked for the measure and its peak in one quote, so it serves as both spans."""
    fr, mx = r.forecast_run, r.maximum
    return RoutedRequest(
        forecast_run=RoutedForecastRun(selection=fr.selection, selection_text=fr.selection_text,
                                       half_hour_text=fr.half_hour_text),
        maximum=RoutedMaximum(kind=mx.kind, measure=mx.measure, measure_text=mx.measure_text,
                              peak_text=mx.measure_text, window=mx.window, window_text=mx.window_text))


@dataclass(frozen=True)
class Routed:
    """What the resolver takes from a routing decision: its reading of the requests, the cutoff's words, and the
    contract it was given in. ``legacy_cutoff``: a v12 decision gave a cutoff timestamp, which is detection only."""
    requested: RoutedRequest | None
    as_of_text: str | None = None
    contract: Literal["v13", "v12"] = "v13"
    legacy_cutoff: bool = False


# ------------------------------------------------------------------------------------------------ provenance


@dataclass
class Source:
    """Where a resolved field came from (the request, the question parser or the routing model), the supporting words
    or request field, and any deterministic conversion."""
    source: Literal["request", "question", "route_model"]
    text: str
    conversion: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "text": self.text, "conversion": self.conversion}


Status = Literal["absent", "bound", "unresolved", "conflict", "as_of_availability"]


@dataclass
class RunRequest:
    status: Status = "absent"
    selection: str | None = None
    half_hour: tuple[datetime, datetime] | None = None
    issued_at: datetime | None = None
    provenance: dict[str, Source] = field(default_factory=dict)
    detected_by: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)

    def forecast_request(self) -> ForecastRequest | None:
        """A bound request in the form the existing run lookup takes (``LiveController._requested_run``)."""
        if self.status != "bound" or self.selection not in ("last_issued_before", "issued_at"):
            return None
        return ForecastRequest(self.selection, self.issued_at, self.half_hour)  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "selection": self.selection,
                "half_hour_utc": [iso_utc(t) for t in self.half_hour] if self.half_hour else None,
                "issued_at_utc": iso_utc(self.issued_at) if self.issued_at else None,
                "provenance": {k: v.as_dict() for k, v in self.provenance.items()},
                "detected_by": self.detected_by, "missing": self.missing, "conflicts": self.conflicts,
                "spans": [x.as_dict() for x in self.spans]}


@dataclass
class MaxRequest:
    status: Status = "absent"
    measures: list[str] = field(default_factory=list)  # keys of demand_max.MEASURES
    window_kind: str | None = None  # "day", "event" or "explicit", as demand_max names them
    window: tuple[datetime, datetime] | None = None
    provenance: dict[str, Source] = field(default_factory=dict)
    detected_by: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    unread: bool = False  # a measure is named, but no maximum of it could be read
    stated: tuple[str, tuple[datetime, datetime]] | None = None  # the window the question's own words give, if one
    spans: list[Span] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)  # the model's spans not used, and why (role, location)

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "measures": self.measures, "window_kind": self.window_kind,
                "window_utc": [iso_utc(t) for t in self.window] if self.window else None,
                "provenance": {k: v.as_dict() for k, v in self.provenance.items()},
                "detected_by": self.detected_by, "missing": self.missing, "conflicts": self.conflicts,
                "spans": [x.as_dict() for x in self.spans], "unused": self.unused}


@dataclass(frozen=True)
class Span:
    """Quoted words located in the question (D26): their role, and every occurrence's character offsets (start, end).
    A span that occurs once is located; a repeated one is read (identical words read identically) but locates
    nothing, so it covers no other words of the question."""
    role: str
    text: str
    occurrences: tuple[tuple[int, int], ...]
    source: Literal["route_model", "question"] = "route_model"

    @property
    def located(self) -> tuple[int, int] | None:
        return self.occurrences[0] if len(self.occurrences) == 1 else None

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "text": self.text, "source": self.source,
                "occurrences": [list(o) for o in self.occurrences], "located": self.located is not None}


@dataclass
class CutoffRequest:
    """The as-of cutoff (D26): from the request field (authoritative), the routing model's quoted words or the
    question parser, every time converted by code. A cutoff that is detected but cannot be pinned down is sent back."""
    status: Status = "absent"
    as_of: datetime | None = None
    provenance: dict[str, Source] = field(default_factory=dict)
    detected_by: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stated: datetime | None = None  # with a request field: what the question's own quoted cutoff words read as
    stated_words: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "as_of_utc": iso_utc(self.as_of) if self.as_of else None,
                "provenance": {k: v.as_dict() for k, v in self.provenance.items()}, "detected_by": self.detected_by,
                "missing": self.missing, "conflicts": self.conflicts, "spans": [x.as_dict() for x in self.spans],
                "notes": self.notes}


@dataclass
class RequestResolution:
    routed: Literal["reported", "not reported"] = "not reported"
    forecast_run: RunRequest = field(default_factory=RunRequest)
    maximum: MaxRequest = field(default_factory=MaxRequest)
    cutoff: CutoffRequest = field(default_factory=CutoffRequest)
    contract: str | None = None  # the routing contract the reading was given in ("v13", or "v12" via the adapter)
    # question wording that conflicts with an authoritative request field: shown with the answer
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"routed": self.routed, "contract": self.contract, "forecast_run": self.forecast_run.as_dict(),
                "maximum": self.maximum.as_dict(), "cutoff": self.cutoff.as_dict(), "notes": self.notes}


# ------------------------------------------------------------------------------------------------ reading times

_FIXED = {"utc": 0, "gmt": 0, "z": 0, "aest": 600, "aedt": 660, "acst": 570, "acdt": 630, "market time": 600,
          "nem time": 600}
_PLACE = {"sydney": "Australia/Sydney", "canberra": "Australia/Sydney", "new south wales": "Australia/Sydney",
          "nsw": "Australia/Sydney", "melbourne": "Australia/Melbourne", "victoria": "Australia/Melbourne",
          "victorian": "Australia/Melbourne", "brisbane": "Australia/Brisbane", "queensland": "Australia/Brisbane",
          "qld": "Australia/Brisbane", "hobart": "Australia/Hobart", "tasmania": "Australia/Hobart",
          "tasmanian": "Australia/Hobart", "adelaide": "Australia/Adelaide", "south australia": "Australia/Adelaide",
          "south australian": "Australia/Adelaide"}
_ZONE_RE = re.compile(r"\b(UTC|GMT|AEST|AEDT|ACST|ACDT|market time|NEM time)\b|(?<=\d)(Z)\b|\b("
                      + "|".join(sorted(_PLACE, key=len, reverse=True)) + r")(?:(?:\s+local)?\s+time\b|['’]s\b)|"
                      r"\b(local)(?:\s+time)?\b", re.I)
_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))")
_DATE_ONLY_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CLOCK_RE = re.compile(r"(?<![\w:.])(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d:])(?![a-z])", re.I)
_MONTH_NAME = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|"
               r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DAY_MONTH_RE = re.compile(rf"(?<![:\d./-])\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME})\b\.?|\b({_MONTH_NAME})\.?\s+"
                           r"(\d{1,2})(?:st|nd|rd|th)?\b(?![:\d])", re.I)
# which bound of a half-hour a clock is: an end or start word up to eight words before it, or a short end word ("to",
# "until") right before it
_END_REL = (r"end|ends|ended|ending|finish|finishes|finished|finishing|close|closes|closed|closing|conclude|concludes|"
            r"concluded|concluding")
_START_REL = (r"start|starts|started|starting|begin|begins|began|beginning|open|opens|opened|opening|commence|commences|"
              r"commenced|commencing|from")
_REL_WORD_RE = re.compile(rf"\b(?:({_END_REL})|({_START_REL}))\b", re.I)
_SHORT_END_RE = re.compile(r"\b(?:to|until|till|through|up to)\s+(?:at\s+)?$", re.I)
_RANGE_JOIN = re.compile(r"^\s*(?:to|-|–|—|until|till|through|and)\s*$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-").replace("’", "'")).strip().lower()


def quoted_in(text: str | None, question: str) -> bool:
    """The model's quoted words appear in the question (ignoring case, spacing and dash and apostrophe styles)."""
    return bool(text) and len(_norm(str(text))) >= 3 and _norm(str(text)) in _norm(question)


def _normalized(s: str) -> tuple[str, list[int]]:
    """``_norm(s)`` with, for each of its characters, the index of the character of ``s`` it comes from."""
    out: list[str] = []
    idx: list[int] = []
    space = True  # leading space is dropped
    for i, ch in enumerate(s):
        ch = {"–": "-", "—": "-", "’": "'"}.get(ch, ch)
        if ch.isspace():
            if not space:
                out.append(" ")
                idx.append(i)
            space = True
            continue
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
        idx.append(i)
        space = False
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def locate(text: str | None, question: str) -> tuple[tuple[int, int], ...]:
    """Every occurrence of the quoted words in the question, as character offsets (start, end) in the question, each
    verified to hold exactly those words (ignoring case, spacing and dash and apostrophe styles). Empty when the words
    are not in the question, or too short to locate (fewer than three characters)."""
    t, _ = _normalized(str(text or ""))
    if len(t) < 3:
        return ()
    nq, idx = _normalized(question)
    out: list[tuple[int, int]] = []
    k = nq.find(t)
    while k != -1:
        start, end = idx[k], idx[k + len(t) - 1] + 1
        if _normalized(question[start:end])[0] == t:  # the offsets identify exactly the quoted words
            out.append((start, end))
        k = nq.find(t, k + 1)
    return tuple(out)


def span(role: str, text: str | None, question: str, source: Literal["route_model", "question"] = "route_model"
         ) -> Span | None:
    """The quoted words as a span of the question, or None when they are absent or not in it."""
    occ = locate(text, question)
    return Span(role, str(text), occ, source) if text and occ else None


def _masked(question: str, spans: list[Span]) -> str:
    """The question with the located spans blanked out (same length, so positions are kept)."""
    out = question
    for sp in spans:
        if sp.located is not None:
            a, b = sp.located
            out = out[:a] + " " * (b - a) + out[b:]
    return out


def _overlap(a: Span, b: Span) -> bool:
    return a.located is not None and b.located is not None and a.located[0] < b.located[1] and b.located[0] < a.located[1]


def _zones(text: str, region: str | None) -> list[tuple[tzinfo, str]]:
    """Each time zone a text names: a fixed offset (AEST, ACST, UTC, market time ...), a place's zone (Sydney time,
    Adelaide local time, Brisbane's ...) or local time (the region's zone)."""
    found: dict[str, tzinfo] = {}
    for m in _ZONE_RE.finditer(text):
        if m.group(1) or m.group(2):
            word = (m.group(1) or m.group(2)).lower()
            found[word.upper() if len(word) <= 4 else word] = timezone(timedelta(minutes=_FIXED[word]))
        elif m.group(3):
            found[f"{m.group(3)} time ({_PLACE[m.group(3).lower()]})"] = ZoneInfo(_PLACE[m.group(3).lower()])
        elif m.group(4) and region:
            found[f"local time ({region_zone(region)})"] = region_zone(region)
    return [(tz, label) for label, tz in found.items()]


def _clocks(text: str) -> list[tuple[int, int, int, int, str | None]]:
    """(start, end, hour, minute, 'a'/'p'/None) for each clock time in ``text``: "07:30", "7:30 pm", "6 pm". A number
    with neither minutes nor am/pm is not a clock; ISO timestamps and dates are skipped."""
    blank = _ISO_RE.sub(lambda m: " " * len(m.group(0)), text)
    blank = _DATE_ONLY_RE.sub(lambda m: " " * len(m.group(0)), blank)
    out = []
    for m in _CLOCK_RE.finditer(blank):
        hh, mm, ap = int(m.group(1)), m.group(2), m.group(3)
        if (mm is None and ap is None) or hh > 23 or (ap and not 1 <= hh <= 12):
            continue
        out.append((m.start(), m.end(), hh, int(mm or 0), ap.lower()[0] if ap else None))
    return out


def _h24(hh: int, ap: str | None) -> int:
    return hh if ap is None else hh % 12 + (12 if ap == "p" else 0)


_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")


def _dates(text: str) -> list[date]:
    """``extract_dates``, and a day/month/year written with slashes when only one reading is a date (29/07/2026)."""
    out = set(extract_dates(text))
    for a, b, y in _NUMERIC_DATE_RE.findall(text):
        readings = set()
        for d, m in ((int(a), int(b)), (int(b), int(a))):
            with contextlib.suppress(ValueError):
                readings.add(date(int(y), m, d))
        if len(readings) == 1:
            out |= readings
    return sorted(out)


def _day_of(text: str, question: str) -> date | None:
    """The one date the text states. A day and month written without the year take the year the question gives, when
    it gives one year only; with no date in the text, the question's one date. None when not pinned down."""
    own = _dates(text)
    q = _dates(question)
    years = {d.year for d in q}
    for g in _DAY_MONTH_RE.findall(_NUMERIC_DATE_RE.sub(" ", text)):
        mon, d = (g[1], g[0]) if g[0] else (g[2], g[3])
        if mon[:3].lower() in MONTHS and len(years) == 1:
            try:
                own.append(date(next(iter(years)), MONTHS[mon[:3].lower()], int(d)))
            except ValueError:
                return None
    own = sorted(set(own))
    if len(own) == 1:
        return own[0]
    if own:
        return None
    return q[0] if len(q) == 1 else None


def _instants(day: date, hh: int, mm: int, zones: list[tuple[tzinfo, str]]) -> set[datetime]:
    return {datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(UTC) for tz, _ in zones}


def _zone_for(text: str, question: str, region: str | None) -> list[tuple[tzinfo, str]]:
    """The zones the text names, else those the question names."""
    return _zones(text, region) or _zones(question, region)


def _relation(before: str) -> str | None:
    """'end' or 'start' from the words before a clock: a short end word ("to", "until") right before it, else the
    nearest end or start word within eight words."""
    if _SHORT_END_RE.search(before):
        return "end"
    rel = None
    for m in _REL_WORD_RE.finditer(" ".join(before.split()[-8:])):
        rel = "end" if m.group(1) else "start"
    return rel


def _is_range(text: str, clocks: list[tuple[int, int, int, int, str | None]]) -> bool:
    """Two clock times joined as one range ("5:30 to 6:00 pm", "between 5:30 and 6:00"), not a list of two ends or
    starts ("ending 12:30 and 13:00")."""
    join = text[clocks[0][1]:clocks[1][0]]
    if not _RANGE_JOIN.match(join) or _relation(text[:clocks[0][0]]) == "end":
        return False
    return not re.match(r"^\s*and\s*$", join, re.I) or bool(re.search(r"\bbetween\s*$", text[:clocks[0][0]], re.I))


def half_hour_from_text(text: str, question: str, region: str | None
                        ) -> tuple[tuple[datetime, datetime] | None, list[str], str]:
    """The half-hour a quoted phrase names, read deterministically: a 30-minute range of two clock times; one clock
    with an end or start word; or an ISO time with one. Its date (with the year) and zone come from the phrase, else
    from the question's only date and zone; equivalent zones ("Adelaide time, ACST") must give the same instant.
    Returns (half-hour or None, what is missing or ambiguous, the conversion)."""
    isos = [(m.start(), parse_iso(m.group(1))) for m in _ISO_RE.finditer(text)]
    clocks = _clocks(text)
    if isos and not clocks:
        if len({t for _, t in isos}) != 1:
            return None, ["half_hour"], ""
        pos, t = isos[0]
        rel = _relation(text[:pos])
        if rel is None:
            return None, ["start_or_end"], ""
        span = (t - timedelta(minutes=30), t) if rel == "end" else (t, t + timedelta(minutes=30))
        return span, [], f"'{text}': {rel} {iso_utc(t)} -> ({iso_utc(span[0])}, {iso_utc(span[1])}]"
    if not clocks:
        return None, ["half_hour"], ""
    day = _day_of(text, question)
    zones = _zone_for(text, question, region)
    missing = (["date"] if day is None else []) + (["time_zone"] if not zones else [])
    if missing:
        return None, missing, ""
    assert day is not None
    label = " = ".join(z for _, z in zones)
    if len(clocks) == 2 and _is_range(text, clocks):
        (_, _, h1, m1, a1), (_, _, h2, m2, a2) = clocks
        if a1 is None and a2 is not None:  # "5:30 to 6:00 pm": the first time shares the second's half of the day
            a1 = a2 if _h24(h1, a2) * 60 + m1 < _h24(h2, a2) * 60 + m2 else ("a" if a2 == "p" else "p")
        starts, ends = _instants(day, _h24(h1, a1), m1, zones), _instants(day, _h24(h2, a2), m2, zones)
        if len(starts) != 1 or len(ends) != 1:
            return None, ["time_zone"], ""  # the zones named disagree
        start, end = next(iter(starts)), next(iter(ends))
        if end <= start:
            end += timedelta(days=1)
        if end - start != timedelta(minutes=30):
            return None, ["half_hour"], ""
        return (start, end), [], f"'{text}' on {day} in {label} -> ({iso_utc(start)}, {iso_utc(end)}]"
    if len(clocks) != 1:
        return None, ["half_hour"], ""
    pos, _, hh, mm, ap = clocks[0]
    ts = _instants(day, _h24(hh, ap), mm, zones)
    if len(ts) != 1:
        return None, ["time_zone"], ""  # the zones named disagree
    t = next(iter(ts))
    if any(it != t for _, it in isos):
        return None, ["half_hour"], ""  # an ISO restatement that is not the clock's instant
    rel = _relation(text[:pos])
    if rel is None:
        return None, ["start_or_end"], ""
    out = (t - timedelta(minutes=30), t) if rel == "end" else (t, t + timedelta(minutes=30))
    return out, [], f"'{text}' on {day} in {label}: {rel} {iso_utc(t)} -> ({iso_utc(out[0])}, {iso_utc(out[1])}]"


_ISSUE_WORD_RE = re.compile(r"\b(?:issued|issue(?:[- ]?(?:time|timestamp|stamp))?|issuing|produced|prepared|released|"
                            r"vintage|stamped|timestamped)\b", re.I)


def _first_instant(seg: str, question: str, region: str | None) -> tuple[datetime | None, str]:
    """The first ISO time, or the first clock with its date and zone, in ``seg``."""
    iso = _ISO_RE.search(seg)
    clocks = _clocks(seg)
    if iso and (not clocks or iso.start() < clocks[0][0]):
        t = parse_iso(iso.group(1))
        return t, f"'{seg.strip()}' -> {iso_utc(t)}"
    if not clocks:
        return None, ""
    _, _, hh, mm, ap = clocks[0]
    day, zones = _day_of(seg, question), _zone_for(seg, question, region)
    ts = _instants(day, _h24(hh, ap), mm, zones) if day is not None and zones else set()
    if len(ts) != 1:
        return None, ""
    t = next(iter(ts))
    return t, f"'{seg.strip()}' on {day} in {' = '.join(z for _, z in zones)} -> {iso_utc(t)}"


def issue_time_from_text(text: str, question: str, region: str | None) -> tuple[datetime | None, str]:
    """The issue time a quoted phrase states: the first time after an issue word. None when it is not pinned down."""
    m = _ISSUE_WORD_RE.search(text)
    return _first_instant(text[m.end():], question, region) if m else (None, "")


_NEXT_DAY_RE = re.compile(r"\b(?:next|following)\s+(?:morning|day)\b|\bovernight\b", re.I)


def window_from_text(text: str, question: str, region: str | None) -> tuple[tuple[datetime, datetime] | None, str]:
    """An explicit window a quoted phrase states: two ISO times, or two clock times joined as a range, with date and
    zone. None otherwise."""
    isos = [parse_iso(m.group(1)) for m in _ISO_RE.finditer(text)]
    clocks = _clocks(text)
    if len(isos) == 2 and not clocks and isos[0] < isos[1]:
        return (isos[0], isos[1]), f"'{text}' -> ({iso_utc(isos[0])}, {iso_utc(isos[1])}]"
    if len(clocks) != 2 or isos or not _is_range(text, clocks):
        return None, ""
    day, zones = _day_of(text, question), _zone_for(text, question, region)
    if day is None or not zones:
        return None, ""
    (_, _, h1, m1, a1), (_, _, h2, m2, a2) = clocks
    if a1 is None and a2 is not None:
        a1 = a2 if _h24(h1, a2) * 60 + m1 < _h24(h2, a2) * 60 + m2 else ("a" if a2 == "p" else "p")
    starts, ends = _instants(day, _h24(h1, a1), m1, zones), _instants(day, _h24(h2, a2), m2, zones)
    if len(starts) != 1 or len(ends) != 1:
        return None, ""
    start, end = next(iter(starts)), next(iter(ends))
    if end <= start and _NEXT_DAY_RE.search(text):  # "5 pm through 1 am the next morning"
        end += timedelta(days=1)
    if end <= start:
        return None, ""
    return (start, end), f"'{text}' on {day} in {' = '.join(z for _, z in zones)} -> ({iso_utc(start)}, {iso_utc(end)}]"


def question_as_of(question: str, region: str | None) -> tuple[datetime | None, str]:
    """The as-of time the question's own words state ("as of 6 pm AEST on 6 August 2026"): the first time after the
    as-of words, up to the end of that clause. (None, words) when it is not pinned down; (None, "") when there is
    none."""
    m = AS_OF_Q_RE.search(question)
    if m is None:
        return None, ""
    seg = re.split(r"[?;]", question[m.end():])[0][:80]
    return _first_instant(seg, question, region)[0], seg.strip()


# ------------------------------------------------------------------------------------------------ cues (bounded)

_FC_WORD_RE = re.compile(r"\b(?:forecasts?|poe ?(?:10|50|90)|predictions?|projections?|outlooks?|pre-?dispatch)\b", re.I)
_ORDINAL_RE = re.compile(r"\b(?:last|latest|final|most recent|newest|freshest|closing)\b", re.I)
_RUN_WORD_RE = re.compile(r"\b(?:forecast|run|prediction|projection|outlook|vintage|issued|issue)\b", re.I)
_RUN_ONLY_RE = re.compile(r"\bruns?\b", re.I)
# a run ordered before the half-hour, an interval, a slot or a time ("issued just ahead of it", "prior to the 6 pm
# half-hour", "issued before the start of the half-hour ending 13:00")
_BEFORE_TARGET_RE = re.compile(
    r"\b(?:before|ahead of|prior to|preceding)\s+(?:it\b|(?:the|that|this|its)\s+(?:\S+\s+){0,3}?(?:half[- ]hours?|"
    r"intervals?|periods?|slots?|targets?|window|start)\b|\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)?(?!\S*/)|"
    r"\d{4}-\d\d-\d\dT)|\bpre[- ]?interval\b", re.I)
_ISSUED_AT_CUE_RE = re.compile(r"\b(?:issued|produced|prepared|released)\s+(?:(?:at|on)\b|(?:(?:about|around|"
                               r"approximately|roughly|circa)\s+)?\d)|\bissue[- ]?(?:time|timestamp|stamp)\b", re.I)
_AVAILABILITY_RE = re.compile(r"\b(?:available|availability|public|publicly|published|publication|known|know|knew|"
                              r"knows|as[ -]of)\b", re.I)
_DEMAND_WORD_RE = re.compile(r"\b(?:demand|totaldemand|load)\b", re.I)
_EXTREME_WORD_RE = re.compile(r"\b(?:peak|peaks|peaked|peaking|highest|maximum|max|maxed|top|topped|topping|greatest|"
                              r"largest|busiest|high[- ]?point|high[- ]?water|crest|crested|summit|zenith|apex|ceiling)\b"
                              # "record" only as a level ("record high", "the record operational demand level")
                              r"|\brecord\b(?=(?:\W+\w+){0,3}?\W+(?:high|level|peak|demand|load)\b)", re.I)
_MIN_WORD_RE = re.compile(r"\b(?:lowest|minimum|min|trough|troughed|bottomed|bottom|least)\b", re.I)
_EXTREME = (r"(?:peak(?:ed|s|ing)?|spik(?:e|ed|es|ing)|high(?:est)?|maximum|max|extreme|top(?:ped)?|record|lowest|"
            r"minimum|bottom(?:ed)?|trough|low)")
# contexts in which a peak word does not ask for (or state) a demand maximum: the price's own extreme; a value at, near
# or before a peak, or in a named interval; an event's peak half-hour or interval; the largest change or error
_NOT_DEMAND_PEAK = [
    re.compile(r"\b(?:highest|peak|maximum|max|top|record|greatest|largest|lowest|minimum|extreme)\s+(?:[\w$/'’-]+\s+)"
               r"{0,3}?(?:prices?|rrps?|spot prices?)\b", re.I),
    re.compile(rf"\b(?:prices?|rrps?)\b(?:\s+[\w$/'’-]+){{0,3}}?\s+{_EXTREME}\b", re.I),
    # ("at its peak", "at its maximum" is the measure's own extreme, and stays)
    re.compile(r"\b(?:at|in|during|for|around|near|nearest|within|with|of|to|into|towards?|up to|until|till|against|"
               r"before|after|across|over|containing|including|covering|spanning)\s+(?:the|that|this|each|a)\s+"
               r"(?:same\s+)?"
               r"(?:[\w'’-]+\s+){0,2}?(?:peak|maximum|spike|extreme|minimum|trough|high)s?\b", re.I),
    # an interval labelled as the (price) peak in brackets: "(the 5-minute peak)"
    re.compile(r"\(\s*(?:the|that|this|its)\s+(?:[\w'’-]+\s+){0,2}?(?:peak|maximum|spike|extreme|minimum)\s*\)", re.I),
    re.compile(r"\b(?:peak|maximum|high-price|price)\s+(?:half[- ]hours?|intervals?|periods?|5-minute|five-minute|"
               r"dispatch intervals?|prices?|rrps?|times?|moments?)\b", re.I),
    re.compile(r"\b(?:largest|biggest|greatest|highest|maximum|max|peak)\s+(?:[\w'’-]+\s+){0,2}?(?:change|rise|"
               r"increase|drop|fall|decrease|swing|ramp|jump|error|difference|gap|deviation|miss|shortfall|overshoot)s?\b",
               re.I),
]


def _without_contexts(text: str) -> str:
    text = text.replace("‑", "-").replace("‐", "-")  # one character each, so positions are kept
    for rx in _NOT_DEMAND_PEAK:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _near(text: str, a: re.Pattern[str], b: re.Pattern[str], words: int) -> bool:
    """A match of ``a`` and one of ``b`` within ``words`` words of each other, in one sentence."""
    for sentence in re.split(r"(?<=[.?!;])\s+", text):
        toks = [(m.start(), m.end()) for m in re.finditer(r"\S+", sentence)]

        def idx(pos: int, toks: list[tuple[int, int]] = toks) -> int:
            return next((i for i, (s, e) in enumerate(toks) if s <= pos < e), len(toks))
        ia = [idx(m.start()) for m in a.finditer(sentence)]
        ib = [idx(m.start()) for m in b.finditer(sentence)]
        if any(abs(x - y) <= words for x in ia for y in ib):
            return True
    return False


def forecast_run_cue(question: str) -> str | None:
    """A bounded lexical cue that one forecast run is asked for, in a question about forecasts (a forecast word, or a
    run near an issue or order word): a run named by its issue time ("issued_at"), or singled out by an ordinal near a
    run or issue word, or ordered before the half-hour or a time ("last_issued_before"). Wording about availability,
    publication or what was known asks for another selection (I-10) and does not count."""
    if _AVAILABILITY_RE.search(question):
        return None
    if not (_FC_WORD_RE.search(question) or _near(question, _RUN_ONLY_RE, _ISSUE_WORD_RE, 3)
            or _near(question, _RUN_ONLY_RE, _ORDINAL_RE, 3)):
        return None
    if _ISSUED_AT_CUE_RE.search(question):
        return "issued_at"
    if _near(question, _ORDINAL_RE, _RUN_WORD_RE, 4) or (_BEFORE_TARGET_RE.search(question) and
                                                         _near(question, _RUN_WORD_RE, _BEFORE_TARGET_RE, 4)):
        return "last_issued_before"
    return None


def maximum_cue(question: str, measure: re.Pattern[str] | None = None) -> bool:
    """A bounded lexical cue that a demand measure's maximum is asked for: a demand word (or the given measure's
    words) within twelve words of a peak or extreme word, once price extremes, values at a peak or in an interval, and
    largest changes are set aside."""
    return _near(_without_contexts(question), measure or _DEMAND_WORD_RE, _EXTREME_WORD_RE, 12)


_CLAUSE_SPLIT_RE = re.compile(r";|,?\s+\b(?:while|whereas|but|compared (?:with|to)|against|versus|vs\.?|than)\b", re.I)


def clauses(sentence: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(sentence) if c and c.strip()]


def demand_extreme_words(clause: str, sentence: str) -> list[tuple[int, str]]:
    """For the answer backstop: where a clause states a demand maximum or minimum ((position, "max" or "min") of its
    peak, maximum or minimum words, when its sentence names demand), once price extremes, values at a peak and largest
    changes are set aside. Positions are the clause's own."""
    if not _DEMAND_WORD_RE.search(sentence):
        return []
    c = _without_contexts(clause)
    return sorted([(m.start(), "max") for m in _EXTREME_WORD_RE.finditer(c)] +
                  [(m.start(), "min") for m in _MIN_WORD_RE.finditer(c)])


_CLAIM_REQUESTED_RE = re.compile(r"\brequested window\b", re.I)
_CLAIM_WINDOW_RE = re.compile(r"\b(?:event|spike|episode|excursion|window)\b", re.I)
_CLAIM_DAY_RE = re.compile(r"\b(?:day|daily|day['’]s)\b|\bmidnight to midnight\b|\ball of \d{4}-\d{2}-\d{2}\b", re.I)
_CLAIM_HELD_RE = re.compile(r"\b(?:held|available|retrieved|returned|public|published)\b", re.I)
_CLAIM_NARROW_RE = re.compile(r"\bleading (?:into|up to)\b|\brun-up\b", re.I)


def claimed_windows(clause: str, sentence: str) -> tuple[set[str], bool]:
    """For the answer backstop: the windows a demand-extreme statement names, from its clause, else its sentence:
    "requested" (the requested maximum's window), "event" (the investigation's window: "the event window", "the
    window"), "day" (the local day of the value's interval: "the day's", "daily", "all of <date>") or "default" (no
    window named: the requested window, else the investigation's). Wording that narrows the window ("between ... and",
    "in the evening", "leading into the spike") names one that cannot be established: "narrowed". Also whether the
    extreme is qualified as one of what is held ("the highest value held"), which needs no full coverage."""
    t = _MIDNIGHT_TO_MIDNIGHT_RE.sub("whole-day", clause)
    if _SUB_WINDOW_RE.search(t) or _PART_OF_DAY_RE.search(t) or _RELATIVE_NARROW_RE.search(t) or \
            _CLAIM_NARROW_RE.search(t):
        return {"narrowed"}, bool(_CLAIM_HELD_RE.search(clause))
    names: set[str] = set()
    for text in (clause, sentence):
        if _CLAIM_REQUESTED_RE.search(text):
            names.add("requested")
        elif _CLAIM_WINDOW_RE.search(text):
            names.add("event")
        if _CLAIM_DAY_RE.search(text):
            names.add("day")
        if names:
            break
    return names or {"default"}, bool(_CLAIM_HELD_RE.search(clause))


_RUN_CLAIM_RE = re.compile(r"\b(?:final|last|latest|most recent|newest)\b(?:\s+[\w()'’-]+){0,4}?\s+(?:forecast|run)s?\b"
                           r"|\bpre[- ]?interval (?:forecast|run)\b", re.I)
_BEFORE_RE = re.compile(r"\b(?:before|ahead of|prior to|preceding)\b|\bpre[- ]?interval\b", re.I)


def run_selection_clause(clause: str) -> bool:
    """For the answer backstop: a clause presenting a forecast run as the final, last or latest one issued before
    something, without wording about availability (which names the as-of selection, I-10)."""
    return bool(_RUN_CLAIM_RE.search(clause) and _BEFORE_RE.search(clause) and not _AVAILABILITY_RE.search(clause))


# ------------------------------------------------------------------------------------------------ resolution

_MEASURE_OF = {"dispatch_total_demand": "total demand", "operational_demand": "operational demand"}
_MEASURE_WORDS = {"total demand": re.compile(r"\b(?:total[- ]?demand|totaldemand|dispatch demand)\b", re.I),
                  "operational demand": re.compile(r"\boperational[- ]demand\b", re.I)}
_EVENT_WORD_RE = re.compile(r"\b(?:event|spike|episode|excursion)\b", re.I)
_DAY_WORD_RE = re.compile(r"\b(?:day|daily|date)\b|\b(?:on|across|for|throughout|over)\s+(?:\w+\s+)?(?:\d{1,2}(?:st|nd|"
                          r"rd|th)?\s+[A-Za-z]{3,9}|[A-Za-z]{3,9}\s+\d{1,2}|\d{4}-\d{2}-\d{2})", re.I)
_ORDER_RE = re.compile(r"\b(?:before|ahead|prior|preceding|earlier|last|latest|final|most recent|newest|previous|"
                       r"pre-?interval|closing|freshest)\b", re.I)


def _same(a: tuple[datetime, datetime] | None, b: tuple[datetime, datetime] | None) -> bool:
    return a is not None and b is not None and a[0] == b[0] and a[1] == b[1]


def _span(w: tuple[datetime, datetime]) -> str:
    return f"({iso_utc(w[0])}, {iso_utc(w[1])}]"


def _grounded_rule(model: RoutedForecastRun | None, q: str) -> bool:
    """Whether the routing model's selection rule is shown by the question's own words: quoted verbatim; for the last
    run issued before the half-hour, an order word and no availability wording, in a question about forecasts or runs;
    for a run named by its issue time, an issue word."""
    if model is None or model.selection not in ("last_issued_before", "issued_at"):
        return False
    text = str(model.selection_text or "")
    if not quoted_in(text, q):
        return False
    if model.selection == "issued_at":
        return bool(_ISSUE_WORD_RE.search(text) or _ISSUED_AT_CUE_RE.search(text))
    return bool(_ORDER_RE.search(text)) and not _AVAILABILITY_RE.search(text) and \
        bool(_FC_WORD_RE.search(q) or _RUN_ONLY_RE.search(text))


def resolve_run(q: str, region: str | None, routed: RoutedRequest | None) -> RunRequest:
    """The forecast run a question asks for, from the question parser and the routing model's grounded reading. Every
    time is converted by code from the question's words (the model's quoted words included): no model timestamp is
    read (D26)."""
    out = RunRequest()
    model = routed.forecast_run if routed is not None else None
    if model is not None:
        out.spans = [sp for sp in (span("run_selection", model.selection_text, q),
                                   span("run_half_hour", model.half_hour_text, q)) if sp is not None]
    cue_q = q
    if AS_OF_Q_RE.search(q):
        # what was public as of a cutoff is the availability selection (I-10), unless the question also singles out a
        # run by issue order ("as of 14:00, which was the latest run issued before it"): that run, under the cutoff,
        # as with a cutoff given in the request (K07)
        cue_q = AS_OF_Q_RE.sub(lambda m: " " * len(m.group(0)), q)
        by_issue = (forecast_run_cue(cue_q) == "last_issued_before" and bool(_BEFORE_TARGET_RE.search(cue_q))) or (
            _grounded_rule(model, q) and model is not None and model.selection == "last_issued_before"
            and bool(_BEFORE_TARGET_RE.search(str(model.selection_text))))
        if not by_issue:  # "the newest run as of 22:00" is the newest public by then
            out.status, out.detected_by = "as_of_availability", ["question"]
            return out
    parsed = requested_forecast(q)
    out.detected_by = [s for s, hit in (("question", parsed is not None),
                                        ("route_model", model is not None and model.selection != "none"),
                                        ("cue", forecast_run_cue(cue_q) is not None)) if hit]
    if not out.detected_by:
        return out
    # -- the selection rule
    rules: dict[str, Source] = {}
    if parsed is not None:
        rules[parsed.run] = Source("question", q, "question parser")
    if model is not None and _grounded_rule(model, q):
        rules.setdefault(model.selection, Source("route_model", str(model.selection_text)))
    elif model is not None and model.selection == "as_of_availability" and not rules:
        text = str(model.selection_text or "")
        if quoted_in(text, q) and _AVAILABILITY_RE.search(text):
            out.status = "as_of_availability"
            return out
    if len(rules) > 1:
        out.status, out.conflicts = "conflict", [f"which run: {' or '.join(sorted(rules))}"]
        return out
    if not rules:  # the cue names no rule by itself; for a run named by an issue time, the issue time is what is missing
        cue = forecast_run_cue(cue_q)
        out.status, out.missing = "unresolved", ["issue_time" if cue == "issued_at" else "run_rule"]
        return out
    out.selection, out.provenance["selection"] = next(iter(rules.items()))
    # -- the issue time
    if out.selection == "issued_at":
        if parsed is not None and parsed.issued_at is not None:
            out.issued_at = parsed.issued_at
            out.provenance["issued_at"] = Source("question", q, "question parser")
        if model is not None and model.selection == "issued_at" and quoted_in(model.selection_text, q):
            t, conv = issue_time_from_text(str(model.selection_text or ""), q, region)
            if t is not None:
                if out.issued_at is not None and abs(out.issued_at - t) > timedelta(minutes=1):
                    out.status = "conflict"
                    out.conflicts = [f"issue time: {iso_utc(out.issued_at)} (question parser) or {iso_utc(t)} (route "
                                     "model)"]
                    return out
                if out.issued_at is None:
                    out.issued_at = t
                    out.provenance["issued_at"] = Source("route_model", str(model.selection_text), conv)
        if out.issued_at is None:
            out.status, out.missing = "unresolved", ["issue_time"]
            return out
    # -- the target half-hour
    found: dict[str, tuple[tuple[datetime, datetime], Source]] = {}
    if parsed is not None and parsed.half_hour is not None:
        found["question"] = (parsed.half_hour, Source("question", q, "question parser"))
    model_missing: list[str] = []
    if model is not None and model.half_hour_text:
        text = str(model.half_hour_text)
        if not quoted_in(text, q):
            model_missing = ["half_hour"]
        else:
            hh, model_missing, conv = half_hour_from_text(text, q, region)
            if hh is not None:  # read by code from the model's quoted words
                found["route_model"] = (hh, Source("route_model", text, conv))
    if len(found) == 2 and not _same(found["question"][0], found["route_model"][0]):
        out.status = "conflict"
        out.conflicts = [f"target half-hour: {_span(found['question'][0])} (question parser) or "
                         f"{_span(found['route_model'][0])} (route model)"]
        return out
    if found:
        out.half_hour, out.provenance["half_hour"] = found.get("question") or found["route_model"]
    elif out.selection == "last_issued_before":
        out.status, out.missing = "unresolved", sorted(set(model_missing or ["half_hour"]))
        return out
    out.status = "bound"
    return out


_WHOLE_DAY_RE = re.compile(r"\b(?:whole|entire|full)\s+(?:of\s+)?(?:the\s+)?day\b|\bthe\s+whole\s+of\b|\ball\s+(?:of\s+)?"
                           r"(?:the\s+)?day\b|\bdaily\b|\bthroughout\s+the\s+day\b|\b(?:the|that)\s+day['’]s\b|"
                           r"\b(?:over|across)\s+the\s+day\b|\bmidnight\s+to\s+midnight\b", re.I)
_MIDNIGHT_TO_MIDNIGHT_RE = re.compile(r"\bmidnight\s+to\s+midnight\b", re.I)
_PART_OF_DAY_RE = re.compile(r"\b(?:morning|afternoon|evening|night|overnight|midday|noon|midnight|early hours|"
                             r"peak hours|business hours)\b", re.I)
_RELATIVE_NARROW_RE = re.compile(r"\b(?:first|last|opening|closing)\s+(?:\w+\s+)?(?:hours?|minutes?|intervals?|"
                                 r"half[- ]hours?)\b|\bhours?\s+(?:before|after|around)\b", re.I)


def _day_span_ok(text: str) -> bool:
    """Words that show one whole local day by themselves: day wording or a date, with no clock time, event, part of
    the day or narrowing in them. "Midnight to midnight" is whole-day wording."""
    t = _MIDNIGHT_TO_MIDNIGHT_RE.sub(" ", text)
    dated = bool(_WHOLE_DAY_RE.search(text) or _DAY_WORD_RE.search(t) or _dates(t) or _DAY_MONTH_RE.search(t))
    return dated and not _clocks(t) and not _EVENT_WORD_RE.search(t) and not _PART_OF_DAY_RE.search(t) and \
        not _RELATIVE_NARROW_RE.search(t) and not _SUB_WINDOW_RE.search(t)


def _time_expressions(q: str) -> list[tuple[int, int]]:
    """Every clock time and ISO time code reads in the question, as offsets (dates alone are not times)."""
    return sorted({(m.start(), m.end()) for m in _ISO_RE.finditer(q)} | {(a, b) for a, b, *_ in _clocks(q)})


def unaccounted_times(q: str, spans: list[Span]) -> list[str]:
    """The times in the question that no located role span holds (the cutoff's, a bound forecast run's, the window's
    own words, an event's identifying words among them): each may narrow a window, so none may be passed over (D26).
    A time is held only where it is written inside such words, never because its instant matches something resolved:
    "after 02:35" would otherwise pass as the event's 02:35 peak. A repeated span locates nothing, so it holds none."""
    located = [sp.located for sp in spans if sp.located is not None]
    return [q[a:b] for a, b in _time_expressions(q) if not any(x <= a and b <= y for x, y in located)]


def _narrows(scope: str) -> bool:
    """Wording in ``scope`` that narrows a window ("between … and", parts of the day, "around the peak" …)."""
    return bool(_SUB_WINDOW_RE.search(_MIDNIGHT_TO_MIDNIGHT_RE.sub(" ", scope)))


# a peak span's role: an extreme word ("highest", "peak", "top", "how high"), outside a price's own extreme or a value
# at the peak (closed vocabulary, D26)
_PEAK_SPAN_RE = re.compile(_EXTREME_WORD_RE.pattern + r"|\bhigh(?:er)?\b", re.I)


def _model_measure(model: RoutedMaximum | None, q: str) -> tuple[str | None, Span | None, str | None]:
    """The measure the model's reading names, when its quoted words show that role: they name exactly that one
    measure (a verbatim span proves the words exist, not their role). Returns (measure, span, why not used)."""
    if model is None or model.kind != "maximum" or model.measure not in _MEASURE_OF:
        return None, None, None
    want = _MEASURE_OF[str(model.measure)]
    sp = span("measure", model.measure_text, q)
    if sp is None:
        return None, None, "measure: the model's words are not in the question"
    named = [m for m, rx in _MEASURE_WORDS.items() if rx.search(sp.text)]
    if named != [want]:
        return None, sp, f"measure: the words '{sp.text}' name {' and '.join(named) or 'no measure'}, the reading {want}"
    return want, sp, None


def _peak_span(model: RoutedMaximum | None, q: str) -> tuple[Span | None, str | None]:
    """The model's peak words, when they show that role: an extreme word in them, at a place in the question that is
    not a price's own extreme or a value at the peak."""
    if model is None or not model.peak_text:
        return None, None
    sp = span("peak", model.peak_text, q)
    if sp is None:
        return None, "peak: the model's words are not in the question"
    masked = _without_contexts(q)
    if _PEAK_SPAN_RE.search(sp.text) and any(_PEAK_SPAN_RE.search(masked[x:y]) for x, y in sp.occurrences):
        return sp, None
    return None, f"peak: the words '{sp.text}' ask for no extreme of demand"


def resolve_maximum(q: str, req: InvestigateRequest, region: str | None, day: date | None, event: Any,
                    routed: RoutedRequest | None, other_spans: list[Span] | None = None) -> MaxRequest:
    """The demand measure's maximum a question asks for, and its window, from the request's window fields, the
    question parser and the routing model's reading, each of its quoted words located and checked for its role (D26).

    - **The measure:** the parser's, or the model's when its words name exactly that measure and a peak is evidenced
      (the model's peak words, the parser or the bounded cue). A detected maximum that is not bound is sent back.
    - **The window:** narrowing is looked for in the question without the located words of other temporal roles
      (``other_spans``: the cutoff, the forecast run's selection and half-hour): a cutoff never narrows the window.
      The model's window words must show their kind by themselves, and must not be another role's words."""
    out = MaxRequest()
    other = list(other_spans or [])
    scope = _masked(q, other)  # the question without the other temporal roles' located words
    parsed = requested_maxima(q)
    model = routed.maximum if routed is not None else None
    out.detected_by = [s for s, hit in (("question", bool(parsed)),
                                        ("route_model", model is not None and model.kind != "none"),
                                        ("cue", maximum_cue(q))) if hit]
    if not out.detected_by:
        return out
    # -- the measure
    measures: dict[str, Source] = {m: Source("question", q, "question parser") for m in parsed if m in _MEASURE_WORDS}
    m_model, m_span, why = _model_measure(model, q)
    p_span, p_why = _peak_span(model, q)
    out.spans += [x for x in (m_span, p_span) if x is not None]
    out.unused += [w for w in (why, p_why) if w]
    if m_model is not None:
        if p_span is not None or parsed or maximum_cue(q):
            measures.setdefault(m_model, Source("route_model", str(m_span.text if m_span else ""),
                                                "peak evidenced by " + ("the model's peak words" if p_span else
                                                                        "the question parser" if parsed else "the cue")))
        else:
            out.unused.append("measure: no peak is evidenced (the model's peak words, the parser or the cue)")
    # a measure with a peak word attached ("the top 5-minute TOTALDEMAND") whose maximum was not read: not dropped
    unread = [m for m, rx in _MEASURE_WORDS.items() if m not in measures and
              _near(_without_contexts(q), rx, _EXTREME_WORD_RE, 4)]
    if not measures or unread:
        out.status, out.missing = "unresolved", ["measure"]
        # a measure is named, but no maximum of it was read: the wording was not read, rather than the measure missing
        out.unread = bool(unread) or (parsed != ["demand"] and bool(TOTAL_DEMAND_Q_RE.search(q) or
                                                                    OPERATIONAL_DEMAND_Q_RE.search(q)))
        return out
    out.measures = list(measures)
    out.provenance["measure"] = next(iter(measures.values()))
    # -- the window
    kinds: dict[str, tuple[tuple[datetime, datetime] | None, Source]] = {}
    ev_window = (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)) if event is not None else None
    parsed_kind = maximum_window_kind(scope, InvestigateRequest(question=q)) if parsed else "unresolved"
    if parsed_kind == "day":
        kinds["day"] = (local_day_window(day, region) if day is not None and region else None,
                        Source("question", q, f"whole local day {day} in {region}"))
    elif parsed_kind == "event":
        kinds["event"] = (ev_window, Source("question", q, "the window of the event the resolution holds"))
    if "day" not in kinds and _WHOLE_DAY_RE.search(scope) and not _EVENT_WINDOW_RE.search(scope) and \
            not _narrows(scope):  # "over the whole of 20 August 2026"
        kinds["day"] = (local_day_window(day, region) if day is not None and region else None,
                        Source("question", q, f"whole-day wording: whole local day {day} in {region}"))
    if _WHOLE_DAY_RE.search(scope) and _EVENT_WINDOW_RE.search(scope):  # both named: two windows, unless they are one
        kinds.setdefault("day", (local_day_window(day, region) if day is not None and region else None,
                                 Source("question", q, f"whole local day {day} in {region}")))
        kinds.setdefault("event", (ev_window, Source("question", q, "the window of the event the resolution holds")))
        if not _same(kinds["day"][0], kinds["event"][0]):
            out.status, out.conflicts = "conflict", ["window: the whole local day or the event window"]
            return out
    if model is not None and model.kind == "maximum" and model.window in ("whole_local_day", "event", "explicit"):
        w_span = span("window", model.window_text, q)
        if w_span is None:
            out.unused.append("window: the model's words are not in the question")
        elif any(_overlap(w_span, o) for o in other):
            role = next(o.role for o in other if _overlap(w_span, o))
            out.status = "conflict"
            out.conflicts = [f"window: the words '{w_span.text}' are read as the window and as the {role}"]
            out.spans.append(w_span)
            return out
        else:
            out.spans.append(w_span)
            text = w_span.text
            if model.window == "whole_local_day":
                if _day_span_ok(text) and not _narrows(_masked(scope, [w_span])):
                    d = _day_of(text, q)
                    if d is not None and region and (day is None or d == day):
                        kinds.setdefault("day", (local_day_window(d, region),
                                                 Source("route_model", text, f"whole local day {d} in {region}")))
                    else:
                        out.unused.append(f"window: the day of '{text}' is not pinned down")
                else:
                    out.unused.append(f"window: '{text}' is not a whole day by itself, or other words narrow it")
            elif model.window == "event":
                if _EVENT_WORD_RE.search(text) and not _RELATIVE_NARROW_RE.search(text):
                    kinds.setdefault("event", (ev_window, Source("route_model", text, "the window of the event held")))
                else:
                    out.unused.append(f"window: '{text}' names no event window by itself")
            else:
                w, conv = window_from_text(text, q, region)
                if w is not None:
                    kinds.setdefault("explicit", (w, Source("route_model", text, conv)))
                else:
                    out.unused.append(f"window: '{text}' gives no start and end that code can read")
    windows = {k: (w, src) for k, (w, src) in kinds.items() if w is not None}
    if len(windows) == 1:
        kind, (w, _) = next(iter(windows.items()))
        out.stated = (kind, w)
    if req.window_start_utc and req.window_end_utc:  # the request's window is authoritative
        out.window_kind, out.status = "explicit", "bound"
        out.window = (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
        out.provenance["window"] = Source("request", "window_start_utc, window_end_utc")
        return out
    if len({w for w, _ in windows.values()}) > 1:
        out.status = "conflict"
        out.conflicts = ["window: " + " or ".join(f"{k} {_span(w)}" for k, (w, _) in sorted(windows.items()))]
        return out
    if not windows:
        out.status = "unresolved"
        out.missing = ["event"] if "event" in kinds else ["date"] if "day" in kinds else ["window"]
        return out
    # every time the question names must be held by a role's words: the cutoff's, a forecast run's, or this window's
    # own; a time that none holds may narrow the window ("after 6 pm"), so no whole-day or event window is bound
    # in its place (D26). Its words are the model's window span, when that is what the window was read from.
    kind, (w, src) = next(iter(windows.items()))
    own = [x for x in out.spans if x.role == "window" and src.source == "route_model" and x.text == src.text]
    loose = unaccounted_times(q, other + own)
    if loose:
        out.status, out.missing = "unresolved", ["window"]
        out.unused.append(f"window: the question names {', '.join(repr(t) for t in loose)}, which no role's words hold; "
                          "it may narrow the window")
        return out
    out.window_kind, out.window, out.provenance["window"], out.status = kind, w, src, "bound"
    return out


CUTOFF_CLARIFICATION = (
    "Which time is the as-of cutoff? The question names one, but its time, date or time zone cannot be read, so no "
    "cutoff is assumed. Give it with its date and time zone.")


def resolve_cutoff(q: str, given_as_of: str | None, region: str | None, day: date | None,
                   routed: Routed | None) -> CutoffRequest:
    """The as-of cutoff (D26): the request field when given (authoritative); else the question parser's reading and
    the routing model's quoted words, each converted by code. A cutoff the model detected (its words, or a v12
    timestamp) that cannot be pinned down is sent back; the model's timestamps are never read. The located words of
    the cutoff are kept, so that they never narrow an analysis window."""
    from .request import extract_as_of

    out = CutoffRequest()
    m = AS_OF_Q_RE.search(q)
    if m:  # the parser's as-of words, up to the first comma, colon, semicolon, dash, bracket or question mark
        end = m.end() + len(re.split(r"[,?;:(—–]| - ", q[m.end():])[0][:80])
        out.spans.append(Span("cutoff", q[m.start():end], ((m.start(), end),), "question"))
    model_t: datetime | None = None
    model_src: Source | None = None
    if routed is not None and routed.as_of_text:
        sp = span("cutoff", routed.as_of_text, q)
        if sp is None:
            out.notes.append("cutoff: the routing model's words are not in the question; not used")
        elif _ISSUE_WORD_RE.search(sp.text):  # an issue time names a forecast run, never a cutoff
            out.notes.append(f"cutoff: '{sp.text}' names a forecast's issue time, not an as-of cutoff; not used")
        else:
            # a cutoff the model quoted is never dropped: a dropped cutoff lets later data in. Words with no wording about
            # what was public or known ("As at 9:00 pm", "Put yourself at 16:30") cannot have that role verified: they
            # are still applied when code can read their time (applying a cutoff can only narrow the evidence), but they
            # hold no time of the question, so a narrowing time quoted as a cutoff ("after 6 pm") still blocks a window
            verified = bool(_AVAILABILITY_RE.search(sp.text) or AS_OF_Q_RE.search(sp.text))
            if verified:
                out.spans.append(sp)
            else:
                out.notes.append(f"cutoff: '{sp.text}' has no wording about what was public or known; applied as the "
                                 "cutoff, but it holds no other time of the question")
            model_t, conv = _first_instant(sp.text, q, region)
            model_src = Source("route_model", sp.text, conv)
            out.detected_by.append("route_model" if verified else "route_model_unverified")
    legacy = routed is not None and routed.legacy_cutoff
    if legacy and forecast_issue_time(q) is not None:
        legacy = False
        out.notes.append("cutoff: the v12 routing decision's cutoff is the forecast's issue time, not an as-of cutoff; "
                         "not applied")
    if legacy:
        out.detected_by.append("route_model_v12")
    if given_as_of:
        out.detected_by.insert(0, "request")
        out.status, out.as_of = "bound", parse_iso(given_as_of)
        out.provenance["as_of"] = Source("request", "as_of_utc")
        if model_src is not None:  # the question's own cutoff words, as the model quoted them: compared, never applied
            out.stated = model_t
            out.stated_words = model_src.text
        return out
    parser_t = extract_as_of(q, region, day) or question_as_of(q, region)[0]
    if m is not None:
        out.detected_by.insert(0, "question")
    if parser_t is not None and model_t is not None and abs(parser_t - model_t) > timedelta(seconds=59):
        out.status = "conflict"
        out.conflicts = [f"cutoff: {iso_utc(parser_t)} (question parser) or {iso_utc(model_t)} (route model's words)"]
        return out
    if parser_t is not None:
        out.status, out.as_of = "bound", parser_t
        out.provenance["as_of"] = Source("question", q, "question parser")
    elif model_t is not None and model_src is not None:
        out.status, out.as_of = "bound", model_t
        out.provenance["as_of"] = model_src
    elif m is not None or model_src is not None or legacy:
        # detected (the parser's as-of words, the model's quoted words, or a v12 timestamp) but not pinned down: sent
        # back before any tool runs, never ignored (D26; dropping a cutoff would let later data in)
        out.status, out.missing = "unresolved", ["cutoff"]
    return out


def request_field_notes(q: str, req: InvestigateRequest, region: str | None, day: date | None,
                        maximum: MaxRequest, cutoff: CutoffRequest | None = None) -> list[str]:
    """Question wording that conflicts with an authoritative request field (an as-of cutoff, an explicit window): the
    request field is used, and this is said with the answer."""
    notes: list[str] = []
    if req.as_of_utc:
        given = parse_iso(req.as_of_utc)
        stated, words = question_as_of(q, region)
        if not words and cutoff is not None and cutoff.stated_words:  # the cutoff words the routing model quoted
            stated, words = cutoff.stated, cutoff.stated_words
        if stated is not None and abs(stated - given) > timedelta(seconds=59):
            notes.append(f"The as-of cutoff given with the request, {iso_utc(given)}, is applied. The question's own "
                         f"wording ('{words}') names {iso_utc(stated)}, which differs.")
        elif stated is None and words and (_clocks(words) or _PART_OF_DAY_RE.search(words)):
            notes.append(f"The as-of cutoff given with the request, {iso_utc(given)}, is applied. The question's own "
                         f"wording ('{words}') also names an as-of time, which could not be compared with it.")
    if req.window_start_utc and req.window_end_utc and maximum.status == "bound" and maximum.stated is not None:
        given_w = (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
        kind, stated_w = maximum.stated
        if not _same(stated_w, given_w):
            what = {"day": "the whole local day", "event": "the event window"}.get(kind, "another window")
            notes.append(f"The maximum is taken over the window given with the request, {_span(given_w)}. The "
                         f"question's own wording names {what}, {_span(stated_w)}, which differs.")
    return notes


RUN_RULE_CLARIFICATION = (
    "Which forecast run is asked for? The question seems to ask for one specific forecast run but does not say which "
    "in a way that can be read: the last run issued before a stated half-hour, the run issued at a stated time, or "
    "what was public as of a stated time. No run is chosen in its place.")
START_OR_END_CLARIFICATION = (
    "Is the time given the start or the end of the half-hour asked about? Say, for example, the half-hour ending at "
    "that time or the half-hour starting at it, with its date and time zone. No half-hour is assumed.")
TIME_ZONE_CLARIFICATION = (
    "Which time zone is the half-hour given in (for example AEST, ACST, market time or UTC)? The question does not "
    "pin it down, so no half-hour is assumed.")
ISSUE_TIME_CLARIFICATION = (
    "Which issue time names the forecast run asked for? Give it with its date and time zone. No run is chosen in its "
    "place.")
MAXIMUM_UNREAD_CLARIFICATION = (
    "The question seems to ask when, or at what level, a demand measure peaked, but its wording could not be read "
    "reliably. Say which measure (dispatch total demand or operational demand) and which window (a whole local day, "
    "a price event's window, or a start and an end with their time zone). No maximum is given in place of the one "
    "asked for.")


def _fields(conflicts: list[str]) -> str:
    """The fields in conflict, as their descriptions name them before the colon ("target half-hour", "window")."""
    names = list(dict.fromkeys(c.split(":")[0].replace("which run", "forecast run") for c in conflicts))
    return " and ".join(names) or "request"


def clarifications(r: RequestResolution) -> list[str]:
    """For each detected request that is not bound: a clarification naming what is missing or which readings
    conflict. A maximum's missing date is left to the resolver's own question."""
    out: list[str] = []
    fr, mx = r.forecast_run, r.maximum
    # the readings themselves (with their times) are in the trace; the clarification names the field only, so its
    # text carries no time or quotation for the answer checks to read
    if fr.status == "conflict":
        out.append(f"The {_fields(fr.conflicts)} asked about can be read in two ways: the question's wording and the "
                   "routing model's reading disagree. Which is meant? Neither is chosen.")
    elif fr.status == "unresolved":
        miss = set(fr.missing)
        out.append(RUN_RULE_CLARIFICATION if "run_rule" in miss else ISSUE_TIME_CLARIFICATION if "issue_time" in miss
                   else START_OR_END_CLARIFICATION if miss == {"start_or_end"}
                   else TIME_ZONE_CLARIFICATION if miss == {"time_zone"} else HALF_HOUR_CLARIFICATION)
    if mx.status == "conflict":
        out.append(f"The {_fields(mx.conflicts)} of the demand peak asked about can be read in two ways: the "
                   "question's wording and the routing model's reading disagree. Which is meant? Neither is chosen.")
    elif mx.status == "unresolved" and mx.missing != ["date"]:
        out.append(MAXIMUM_UNREAD_CLARIFICATION if mx.unread else MAXIMUM_CLARIFICATION if "measure" in mx.missing
                   else MAXIMUM_EVENT_CLARIFICATION if "event" in mx.missing else MAXIMUM_WINDOW_CLARIFICATION)
    co = r.cutoff
    if co.status == "conflict":
        out.append("The as-of cutoff can be read in two ways: the question's wording and the routing model's reading "
                   "disagree. Which is meant? Neither is applied.")
    elif co.status == "unresolved":
        out.append(CUTOFF_CLARIFICATION)
    return out
