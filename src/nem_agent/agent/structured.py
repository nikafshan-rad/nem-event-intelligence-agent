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

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ..timeutil import UTC, iso_utc, local_day_window, parse_iso, region_zone
from .request import (
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
    maximum_window_kind,
    requested_forecast,
    requested_maxima,
)

# ------------------------------------------------------------------------------------------------ the routed schema


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutedForecastRun(_M):
    selection: Literal["none", "last_issued_before", "issued_at", "as_of_availability", "unclear"] = Field(
        description="the one forecast run the question asks for: last_issued_before = the last run issued before the "
                    "target half-hour starts; issued_at = the run issued at a stated time; as_of_availability = what "
                    "was public or known at a cutoff; none = no specific run is asked for; unclear = one specific run "
                    "is asked for, but which cannot be told")
    selection_text: str | None = Field(description="the question's exact words asking for this run, copied verbatim")
    half_hour_text: str | None = Field(
        description="the question's exact words naming the target half-hour, copied verbatim (with its clock times, "
                    "and its date and time zone where they are written next to it)")
    target_half_hour_end_utc: str | None = Field(description="the target half-hour's END, ISO-8601 UTC ending in Z")
    issued_at_utc: str | None = Field(description="issued_at only: the stated issue time, ISO-8601 UTC ending in Z")


class RoutedMaximum(_M):
    kind: Literal["none", "maximum", "unclear"] = Field(
        description="maximum = the question asks when, or at what level, a demand measure reached its maximum over a "
                    "window; none = it does not (demand AT the price peak or in a named interval, the peak price); "
                    "unclear = a demand peak is asked for, but what is meant cannot be told")
    measure: Literal["dispatch_total_demand", "operational_demand", "unspecified"] | None = Field(
        description="dispatch total demand (TOTALDEMAND, 5-minute) or operational demand (half-hourly)")
    measure_text: str | None = Field(
        description="the question's exact words asking for the measure's maximum, copied verbatim (measure and peak "
                    "word)")
    window: Literal["whole_local_day", "event", "explicit", "unspecified"] | None = Field(
        description="whole_local_day = one whole local calendar day; event = a price event's window; explicit = a "
                    "start and an end")
    window_text: str | None = Field(description="the question's exact words naming the window, copied verbatim")
    window_start_utc: str | None = Field(description="explicit only: the window start, ISO-8601 UTC ending in Z")
    window_end_utc: str | None = Field(description="explicit only: the window end, ISO-8601 UTC ending in Z")


class RoutedRequest(_M):
    forecast_run: RoutedForecastRun
    maximum: RoutedMaximum


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
                "detected_by": self.detected_by, "missing": self.missing, "conflicts": self.conflicts}


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

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "measures": self.measures, "window_kind": self.window_kind,
                "window_utc": [iso_utc(t) for t in self.window] if self.window else None,
                "provenance": {k: v.as_dict() for k, v in self.provenance.items()},
                "detected_by": self.detected_by, "missing": self.missing, "conflicts": self.conflicts}


@dataclass
class RequestResolution:
    routed: Literal["reported", "not reported"] = "not reported"
    forecast_run: RunRequest = field(default_factory=RunRequest)
    maximum: MaxRequest = field(default_factory=MaxRequest)
    # question wording that conflicts with an authoritative request field: shown with the answer
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"routed": self.routed, "forecast_run": self.forecast_run.as_dict(),
                "maximum": self.maximum.as_dict(), "notes": self.notes}


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
                      + "|".join(sorted(_PLACE, key=len, reverse=True)) + r")(?:\s+local)?\s+time\b|\b(local time)\b",
                      re.I)
_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))")
_DATE_ONLY_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CLOCK_RE = re.compile(r"(?<![\w:.])(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d:])(?![a-z])", re.I)
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\b|\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|"
                           r"th)?\b")
# which bound of a half-hour a clock is: an end or start word up to eight words before it, or a short end word ("to",
# "until") right before it
_END_REL = (r"end|ends|ended|ending|finish|finishes|finished|finishing|close|closes|closed|closing|conclude|concludes|"
            r"concluded|concluding")
_START_REL = (r"start|starts|started|starting|begin|begins|began|beginning|open|opens|opened|opening|commence|commences|"
              r"commenced|commencing|from")
_REL_WORD_RE = re.compile(rf"\b(?:({_END_REL})|({_START_REL}))\b", re.I)
_SHORT_END_RE = re.compile(r"\b(?:to|until|till|through|up to)\s+(?:at\s+)?$", re.I)
_RANGE_JOIN = re.compile(r"^\s*(?:to|-|–|—|until|till|through|and)\s*$", re.I)
_NARROW = re.compile(r"\b(?:morning|afternoon|evening|night|overnight|midday|noon|midnight|early hours|peak hours|"
                     r"business hours|first|last|hours? (?:before|after|around))\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").replace("—", "-").replace("’", "'")).strip().lower()


def quoted_in(text: str | None, question: str) -> bool:
    """The model's quoted words appear in the question (ignoring case, spacing and dash and apostrophe styles)."""
    return bool(text) and len(_norm(str(text))) >= 3 and _norm(str(text)) in _norm(question)


def _zones(text: str, region: str | None) -> list[tuple[tzinfo, str]]:
    """Each time zone a text names: a fixed offset (AEST, ACST, UTC, market time ...), a place's zone (Sydney time,
    Adelaide local time ...) or 'local time' (the region's zone)."""
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


def _day_of(text: str, question: str) -> date | None:
    """The one date (with its year) the text states, else the question's one date, provided a day and month the
    text writes without a year agree with it. None when not pinned down."""
    own = extract_dates(text)
    if len(own) == 1:
        return own[0]
    if own:
        return None
    q = extract_dates(question)
    if len(q) != 1:
        return None
    for g in _DAY_MONTH_RE.findall(text):
        mon, d = (g[1], g[0]) if g[0] else (g[2], g[3])
        if mon[:3].lower() in MONTHS and (MONTHS[mon[:3].lower()], int(d)) != (q[0].month, q[0].day):
            return None
    return q[0]


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
    if len(clocks) == 2 and _RANGE_JOIN.match(text[clocks[0][1]:clocks[1][0]]):
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


_ISSUE_WORD_RE = re.compile(r"\b(?:issued|issue|issuing|produced|prepared|released|vintage|stamped|timestamped)\b",
                            re.I)


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


def window_from_text(text: str, question: str, region: str | None) -> tuple[tuple[datetime, datetime] | None, str]:
    """An explicit window a quoted phrase states: two ISO times, or two clock times joined as a range, with date and
    zone. None otherwise."""
    isos = [parse_iso(m.group(1)) for m in _ISO_RE.finditer(text)]
    clocks = _clocks(text)
    if len(isos) == 2 and not clocks and isos[0] < isos[1]:
        return (isos[0], isos[1]), f"'{text}' -> ({iso_utc(isos[0])}, {iso_utc(isos[1])}]"
    if len(clocks) != 2 or isos or not _RANGE_JOIN.match(text[clocks[0][1]:clocks[1][0]]):
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
# one run singled out: an ordinal before a singular run word; a singular run word ordered before the half-hour, an
# interval or a time ("issued ahead of it", "prior to the 6 pm half-hour"); or a run named by its issue time
_TARGET = (r"(?:it|(?:the|that|this|its)\s+(?:[\w:.()-]+\s+){0,3}?(?:half[- ]hours?|intervals?|periods?|slots?|targets?|"
           r"window)\b|\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)?|\d{4}-\d\d-\d\dT)")
_RUN_SELECT_RE = re.compile(
    r"\b(?:last|latest|final|most recent|newest|freshest|closing)\b(?:\s+[\w()'’-]+){0,5}?\s+"
    r"(?:forecast|run|prediction|projection|outlook|vintage|issue)\b"
    r"|\b(?:forecast|run|prediction|projection|outlook)\b(?:\s+[\w'’-]+){0,3}?\s+(?:just\s+|immediately\s+|right\s+)?"
    rf"(?:before|ahead of|prior to|preceding)\s+{_TARGET}|\bpre[- ]?interval\b", re.I)
_ISSUED_AT_CUE_RE = re.compile(r"\b(?:forecast|run|prediction|projection|outlook|vintage)\b(?:\s+[\w'’-]+){0,4}?\s+"
                               r"(?:issued|produced|prepared|released)\s+(?:(?:at|on)\b|(?:(?:about|around|approximately|"
                               r"roughly|circa)\s+)?\d)", re.I)
_AVAILABILITY_RE = re.compile(r"\b(?:available|availability|public|publicly|published|publication|known|as[ -]of)\b",
                              re.I)
_DEMAND_WORD_RE = re.compile(r"\b(?:demand|totaldemand|load)\b", re.I)
_EXTREME_WORD_RE = re.compile(r"\b(?:peak|peaks|peaked|peaking|highest|maximum|max|maxed|top|topped|topping|greatest|"
                              r"largest|record[- ](?:high|level|peak)|busiest|high[- ]?point|high[- ]?water|crest|"
                              r"crested|summit|zenith|apex|ceiling)\b", re.I)
_MIN_WORD_RE = re.compile(r"\b(?:lowest|minimum|min|trough|troughed|bottomed|bottom|least)\b", re.I)
_EXTREME = (r"(?:peak(?:ed|s|ing)?|spik(?:e|ed|es|ing)|high(?:est)?|maximum|max|extreme|top(?:ped)?|record|lowest|"
            r"minimum|bottom(?:ed)?|trough|low)")
# contexts in which a peak word does not ask for (or state) a demand maximum: the price's own extreme; a value at, near
# or before a peak, or in a named interval; an event's peak half-hour or interval; the largest change or error
_NOT_DEMAND_PEAK = [
    re.compile(r"\b(?:highest|peak|maximum|max|top|record|greatest|largest|lowest|minimum|extreme)\s+(?:[\w$/'’-]+\s+)"
               r"{0,3}?(?:prices?|rrps?|spot prices?)\b", re.I),
    re.compile(rf"\b(?:prices?|rrps?)\b(?:\s+[\w$/'’-]+){{0,3}}?\s+{_EXTREME}\b", re.I),
    re.compile(r"\b(?:at|in|during|for|around|near|nearest|within|with|of|to|against|before|after|across|over|"
               r"containing|including|covering|spanning)\s+(?:the|that|this|its|their|each|a)\s+(?:same\s+)?"
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


def forecast_run_cue(question: str) -> str | None:
    """A bounded lexical cue that one forecast run is asked for: a forecast word, and one run singled out by an
    ordinal, by being before the half-hour or a time ("last_issued_before"), or by its issue time ("issued_at").
    Wording about availability or publication asks for another selection (I-10) and does not count."""
    if not _FC_WORD_RE.search(question) or _AVAILABILITY_RE.search(question):
        return None
    if _ISSUED_AT_CUE_RE.search(question):
        return "issued_at"
    return "last_issued_before" if _RUN_SELECT_RE.search(question) else None


def _near(text: str, a: re.Pattern[str], b: re.Pattern[str], words: int = 8) -> bool:
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


def maximum_cue(question: str) -> bool:
    """A bounded lexical cue that a demand measure's maximum is asked for: a demand word within eight words of a peak
    or extreme word, once price extremes, values at a peak or in an interval, and largest changes are set aside."""
    return _near(_without_contexts(question), _DEMAND_WORD_RE, _EXTREME_WORD_RE)


_CLAUSE_SPLIT_RE = re.compile(r";|,?\s+\b(?:while|whereas|but|compared (?:with|to)|against|versus|vs\.?|than)\b", re.I)


def clauses(sentence: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(sentence) if c and c.strip()]


def demand_extreme_words(clause: str, sentence: str) -> list[int]:
    """For the answer backstop: where a clause states a demand maximum or minimum (the positions of its peak, maximum
    or minimum words, when its sentence names demand), once price extremes, values at a peak and largest changes are
    set aside. Positions are the clause's own."""
    if not _DEMAND_WORD_RE.search(sentence):
        return []
    c = _without_contexts(clause)
    return sorted(m.start() for rx in (_EXTREME_WORD_RE, _MIN_WORD_RE) for m in rx.finditer(c))


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


def _iso_or_none(s: str | None) -> datetime | None:
    try:
        return parse_iso(s) if s else None
    except ValueError:
        return None


def resolve_run(q: str, region: str | None, routed: RoutedRequest | None) -> RunRequest:
    """The forecast run a question asks for, from the question parser and the routing model's grounded reading."""
    out = RunRequest()
    if AS_OF_Q_RE.search(q):  # what was public as of a cutoff: the availability selection (I-10)
        out.status, out.detected_by = "as_of_availability", ["question"]
        return out
    parsed = requested_forecast(q)
    model = routed.forecast_run if routed is not None else None
    out.detected_by = [s for s, hit in (("question", parsed is not None),
                                        ("route_model", model is not None and model.selection != "none"),
                                        ("cue", forecast_run_cue(q) is not None)) if hit]
    if not out.detected_by:
        return out
    # -- the selection rule
    rules: dict[str, Source] = {}
    if parsed is not None:
        rules[parsed.run] = Source("question", q, "question parser")
    if model is not None and model.selection in ("last_issued_before", "issued_at"):
        text = str(model.selection_text or "")
        if model.selection == "last_issued_before":
            ok = (quoted_in(text, q) and bool(_ORDER_RE.search(text)) and not _AVAILABILITY_RE.search(text)
                  and bool(_FC_WORD_RE.search(q) or re.search(r"\brun\b", text, re.I)))
        else:
            ok = quoted_in(text, q) and bool(_ISSUE_WORD_RE.search(text))
        if ok:
            rules.setdefault(model.selection, Source("route_model", text))
    elif model is not None and model.selection == "as_of_availability" and not rules:
        text = str(model.selection_text or "")
        if quoted_in(text, q) and _AVAILABILITY_RE.search(text):
            out.status = "as_of_availability"
            return out
    if len(rules) > 1:
        out.status, out.conflicts = "conflict", [f"which run: {' or '.join(sorted(rules))}"]
        return out
    if not rules:  # the cue names no rule by itself; for a run named by an issue time, the issue time is what is missing
        cue = forecast_run_cue(q)
        out.status, out.missing = "unresolved", ["issue_time" if cue == "issued_at" else "run_rule"]
        return out
    out.selection, out.provenance["selection"] = next(iter(rules.items()))
    # -- the issue time
    if out.selection == "issued_at":
        if parsed is not None and parsed.issued_at is not None:
            out.issued_at = parsed.issued_at
            out.provenance["issued_at"] = Source("question", q, "question parser")
        if model is not None and model.selection == "issued_at":
            t, conv = issue_time_from_text(str(model.selection_text or ""), q, region)
            claimed = _iso_or_none(model.issued_at_utc)
            if t is not None and claimed is not None and abs(t - claimed) <= timedelta(minutes=1):
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
            claimed_end = _iso_or_none(model.target_half_hour_end_utc)
            if hh is not None and claimed_end is not None and hh[1] != claimed_end:
                out.status = "conflict"
                out.conflicts = [f"target half-hour: the words '{text}' read as {_span(hh)}, the route model gave an "
                                 f"end of {iso_utc(claimed_end)}"]
                return out
            if hh is not None:
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


def resolve_maximum(q: str, req: InvestigateRequest, region: str | None, day: date | None, event: Any,
                    routed: RoutedRequest | None) -> MaxRequest:
    """The demand measure's maximum a question asks for, and its window, from the request's window fields, the
    question parser and the routing model's grounded reading."""
    out = MaxRequest()
    parsed = requested_maxima(q)
    model = routed.maximum if routed is not None else None
    out.detected_by = [s for s, hit in (("question", bool(parsed)),
                                        ("route_model", model is not None and model.kind != "none"),
                                        ("cue", maximum_cue(q))) if hit]
    if not out.detected_by:
        return out
    # -- the measure
    measures: dict[str, Source] = {m: Source("question", q, "question parser") for m in parsed if m in _MEASURE_WORDS}
    if model is not None and model.kind == "maximum" and model.measure in _MEASURE_OF:
        m = _MEASURE_OF[str(model.measure)]
        text = str(model.measure_text or "")
        if quoted_in(text, q) and _MEASURE_WORDS[m].search(text) and _EXTREME_WORD_RE.search(_without_contexts(text)):
            measures.setdefault(m, Source("route_model", text))
    if not measures:
        out.status, out.missing = "unresolved", ["measure"]
        # a measure is named, but no maximum of it was read: the wording was not read, rather than the measure missing
        out.unread = parsed != ["demand"] and bool(TOTAL_DEMAND_Q_RE.search(q) or OPERATIONAL_DEMAND_Q_RE.search(q))
        return out
    out.measures = list(measures)
    out.provenance["measure"] = next(iter(measures.values()))
    # -- the window
    kinds: dict[str, tuple[tuple[datetime, datetime] | None, Source]] = {}
    ev_window = (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)) if event is not None else None
    parsed_kind = maximum_window_kind(q, InvestigateRequest(question=q)) if parsed else "unresolved"
    if parsed_kind == "day":
        kinds["day"] = (local_day_window(day, region) if day is not None and region else None,
                        Source("question", q, f"whole local day {day} in {region}"))
    elif parsed_kind == "event":
        kinds["event"] = (ev_window, Source("question", q, "the window of the event the resolution holds"))
    if model is not None and model.kind == "maximum" and model.window in ("whole_local_day", "event", "explicit"):
        text = str(model.window_text or "")
        if quoted_in(text, q) and not _NARROW.search(text):
            if model.window == "whole_local_day" and _DAY_WORD_RE.search(text):
                d = _day_of(text, q)
                if d is not None and region and (day is None or d == day):
                    kinds.setdefault("day", (local_day_window(d, region),
                                             Source("route_model", text, f"whole local day {d} in {region}")))
            elif model.window == "event" and _EVENT_WORD_RE.search(text):
                kinds.setdefault("event", (ev_window, Source("route_model", text, "the window of the event held")))
            elif model.window == "explicit":
                w, conv = window_from_text(text, q, region)
                c0, c1 = _iso_or_none(model.window_start_utc), _iso_or_none(model.window_end_utc)
                if w is not None and c0 is not None and c1 is not None and not _same(w, (c0, c1)):
                    out.status = "conflict"
                    out.conflicts = [f"window: the words '{text}' read as {_span(w)}, the route model gave "
                                     f"{_span((c0, c1))}"]
                    return out
                if w is not None and c0 is not None:
                    kinds.setdefault("explicit", (w, Source("route_model", text, conv)))
    if req.window_start_utc and req.window_end_utc:  # the request's window is authoritative
        out.window_kind, out.status = "explicit", "bound"
        out.window = (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
        out.provenance["window"] = Source("request", "window_start_utc, window_end_utc")
        return out
    windows = {k: (w, src) for k, (w, src) in kinds.items() if w is not None}
    if len({w for w, _ in windows.values()}) > 1:
        out.status = "conflict"
        out.conflicts = ["window: " + " or ".join(f"{k} {_span(w)}" for k, (w, _) in sorted(windows.items()))]
        return out
    if not windows:
        out.status = "unresolved"
        out.missing = ["event"] if "event" in kinds else ["date"] if "day" in kinds else ["window"]
        return out
    kind, (w, src) = next(iter(windows.items()))
    out.window_kind, out.window, out.provenance["window"], out.status = kind, w, src, "bound"
    return out


def request_field_notes(q: str, req: InvestigateRequest, region: str | None, day: date | None,
                        maximum: MaxRequest) -> list[str]:
    """Question wording that conflicts with an authoritative request field (an as-of cutoff, an explicit window): the
    request field is used, and this is said with the answer."""
    notes: list[str] = []
    if req.as_of_utc:
        given = parse_iso(req.as_of_utc)
        stated, words = question_as_of(q, region)
        if stated is not None and abs(stated - given) > timedelta(seconds=59):
            notes.append(f"The as-of cutoff given with the request, {iso_utc(given)}, is applied. The question's own "
                         f"wording ('{words}') names {iso_utc(stated)}, which differs.")
        elif stated is None and words and _clocks(words):
            notes.append(f"The as-of cutoff given with the request, {iso_utc(given)}, is applied. The question's own "
                         f"wording ('{words}') also names an as-of time, which could not be compared with it.")
    if req.window_start_utc and req.window_end_utc and maximum.status == "bound":
        given_w = (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
        kind = maximum_window_kind(q, InvestigateRequest(question=q))
        other = local_day_window(day, region) if kind == "day" and day is not None and region else None
        if kind in ("day", "event") and not _same(other, given_w):
            notes.append(f"The maximum is taken over the window given with the request, {_span(given_w)}. The "
                         f"question's own wording names {'the whole day' if kind == 'day' else 'the event window'}"
                         + (f" {_span(other)}" if other else "") + ", which differs.")
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
    return out
