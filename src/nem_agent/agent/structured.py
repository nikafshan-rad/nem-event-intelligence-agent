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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ..timeutil import UTC, half_hour_end_for, iso_utc, local_day_window, parse_iso, region_zone
from .request import (
    _EVENT_WINDOW_RE,
    _SUB_WINDOW_RE,
    AS_OF_Q_RE,
    HALF_HOUR_CLARIFICATION,
    ISSUED_AT_RE,
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


# What a forecast review asks about AEMO's forecasts, and the question's own words for it and for its half-hour or
# period (route contract v14, D28), with what is forecast and the words of the requested clause (v15, D29). Code
# converts every time from those words. A decision recorded before v15 has no domain: "not reported".
class RoutedForecast(_M):
    operation: Literal["none", "forecast_value", "single_interval_comparison", "window_comparison", "unclear"] = Field(
        description="what a forecast_review question asks about the forecasts: forecast_value = what a forecast said "
                    "(its values, or which run), not compared with actual demand; single_interval_comparison = a "
                    "forecast compared with actual demand for one half-hour; window_comparison = forecasts compared "
                    "with actual demand over a period; none = not a forecast question; unclear = whether the forecast "
                    "is compared with actual demand cannot be told")
    operation_text: str | None = Field(description="the question's exact words asking for it, copied verbatim")
    scope: Literal["half_hour", "event_peak_half_hour", "whole_local_day", "event", "explicit",
                   "unspecified"] | None = Field(
        description="the half-hour or period asked about: half_hour = one stated half-hour; event_peak_half_hour = a "
                    "price event's peak half-hour; whole_local_day = one whole local calendar day; event = a price "
                    "event's window; explicit = a stated start and end")
    scope_text: str | None = Field(
        description="the question's exact words naming the half-hour or period, copied verbatim")
    domain: Literal["none", "operational_demand", "weather", "price", "other", "unclear"] | None = Field(
        None, description="what the requested forecast is of: operational_demand = AEMO's operational demand "
                          "forecasts; weather, price or other = a forecast of another kind; none = no forecast is "
                          "asked about; unclear = what is forecast cannot be told")
    request_text: str | None = Field(
        None, description="the question's exact words of the requested forecast clause (what is forecast, what is "
                          "asked and its half-hour or period), copied verbatim")
    unsupported_text: str | None = Field(
        None, description="the question's exact words asking for a forecast of another kind, when the question also "
                          "asks for one; else null")


class RoutedRequest(_M):
    forecast_run: RoutedForecastRun
    maximum: RoutedMaximum
    # route contract v14 (D28); absent from a decision recorded before it: "not reported"
    forecast: RoutedForecast | None = None


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
    contract it was given in. ``legacy_cutoff``: a v12 decision gave a cutoff timestamp, which is detection only.
    ``plan``: a route contract v16 decision's request plan (``plan.RequestPlan``, D31 Amendment 1), compiled by
    ``plan.compile_plan`` instead of this module's resolvers; None for every earlier contract."""
    requested: RoutedRequest | None
    as_of_text: str | None = None
    contract: Literal["v16", "v15", "v14", "v13", "v12"] = "v15"
    legacy_cutoff: bool = False
    plan: Any = None


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
class ForecastAnalysis:
    """What a forecast review asks for (D28): its operation (``forecast_value``, ``single_interval_comparison`` or
    ``window_comparison``) and its scope, one half-hour (``half_hour``, ``event_peak_half_hour``: ``target``) or a
    period (``whole_local_day``, ``event``, ``explicit``: ``window``), as UTC bounds on the half-hour grid. Resolved like
    the other requests: absent, bound, unresolved (``missing``) or in conflict (``conflicts``)."""
    status: Status = "absent"
    operation: str | None = None
    scope: str | None = None
    target: tuple[datetime, datetime] | None = None
    window: tuple[datetime, datetime] | None = None
    domain: str | None = None  # what is forecast (D29): only operational_demand enters the demand workflow
    unsupported: list[str] = field(default_factory=list)  # forecasts of another kind also asked for: not answered
    provenance: dict[str, Source] = field(default_factory=dict)
    detected_by: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def bounds(self) -> tuple[datetime, datetime] | None:
        return self.target or self.window

    @property
    def intervals(self) -> int | None:
        """The half-hours in the bounds, derived from them (a whole local day has 46, 48 or 50)."""
        b = self.bounds
        return None if b is None else round((b[1] - b[0]) / timedelta(minutes=30))

    def as_dict(self) -> dict[str, Any]:
        b = self.bounds
        return {"status": self.status, "domain": self.domain, "unsupported": self.unsupported,
                "operation": self.operation, "scope": self.scope,
                "target_utc": [iso_utc(t) for t in self.target] if self.target else None,
                "window_utc": [iso_utc(t) for t in self.window] if self.window else None,
                "half_hours": self.intervals if b else None,
                "provenance": {k: v.as_dict() for k, v in self.provenance.items()}, "detected_by": self.detected_by,
                "missing": self.missing, "conflicts": self.conflicts, "spans": [x.as_dict() for x in self.spans],
                "notes": self.notes}


@dataclass
class RequestResolution:
    routed: Literal["reported", "not reported"] = "not reported"
    forecast_run: RunRequest = field(default_factory=RunRequest)
    maximum: MaxRequest = field(default_factory=MaxRequest)
    cutoff: CutoffRequest = field(default_factory=CutoffRequest)
    contract: str | None = None  # the routing contract the reading was given in ("v15", "v14", "v13", or "v12" via the
    # adapter)
    # question wording that conflicts with an authoritative request field, and parts not answered: shown with the answer
    notes: list[str] = field(default_factory=list)
    # tools that may not run for this request, with why (D29: the demand-forecast tools, for a forecast that is not a
    # resolved operational-demand request)
    ineligible_tools: dict[str, str] = field(default_factory=dict)
    # the operation and scope a forecast review asks for (D28)
    forecast: ForecastAnalysis = field(default_factory=lambda: ForecastAnalysis())
    # route contract v16 only (D31 Amendment 1): what the compiler read from the request plan; None otherwise, and then
    # not serialised, so earlier contracts' records keep their form
    plan: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {"routed": self.routed, "contract": self.contract, "forecast_run": self.forecast_run.as_dict(),
               "maximum": self.maximum.as_dict(), "cutoff": self.cutoff.as_dict(), "notes": self.notes,
               "forecast": self.forecast.as_dict(), "ineligible_tools": self.ineligible_tools}
        return out if self.plan is None else {**out, "plan": self.plan}


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


def resolve_run(q: str, region: str | None, routed: RoutedRequest | None, held: Sequence[Span] = ()) -> RunRequest:
    """The forecast run a question asks for, from the question parser and the routing model's grounded reading. Every
    time is converted by code from the question's words (the model's quoted words included): no model timestamp is
    read (D26). ``held``: other roles' located words (the cutoff's), which hold the times they contain."""
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
    elif _unheld_times(q, out, held):
        # a run named by its issue time, with no half-hour read: a time the question names that no role's words hold
        # (the issue time's, the cutoff's) may be the half-hour asked about, or narrow the window. The request is sent
        # back: never compared over a window in its place (D27, as a maximum's window under D26)
        out.status, out.missing = "unresolved", sorted(set(model_missing or ["half_hour"]))
        return out
    out.status = "bound"
    return out


def _unheld_times(q: str, run: RunRequest, held: Sequence[Span]) -> list[str]:
    """The times in the question that neither the run's issue-time words (the routing model's located selection words,
    or the question parser's own match) nor ``held`` hold (``unaccounted_times``)."""
    own = [sp for sp in run.spans if sp.role == "run_selection"]
    m = ISSUED_AT_RE.search(q)
    if m is not None:  # the words the question parser reads the issue time from (a conflicting reading returned earlier)
        own.append(Span("run_selection", m.group(0), ((m.start(), m.end()),), "question"))
    return unaccounted_times(q, [*held, *own])


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
# route contract v16 (D31 Amendment 1): a cutoff no asked request refers to, or as-of words the request plan leaves out
PLAN_CUTOFF_CLARIFICATION = (
    "The question names an as-of cutoff, but which request it limits is not shown, so no cutoff is applied in its "
    "place and nothing is run. Say which forecast or analysis the cutoff applies to.")


# a time's own zone and date written right after it ("6 pm AEST on 6 August 2026")
_TIME_QUALIFIERS_RE = re.compile(
    rf"(?:\s*,?\s*(?:(?:on\s+)?(?:\d{{4}}-\d\d-\d\d(?!T)|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_NAME}\b\.?(?:,?\s+20\d\d)?|"
    rf"{_MONTH_NAME}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+20\d\d)?)|(?:in\s+)?(?:UTC|GMT|AEST|AEDT|ACST|ACDT|"
    r"NEM\s+time|market\s+time|local\s+time)\b))*", re.I)


_LEAD_DATE_RE = re.compile(
    rf"(?:\bon\s+)?(?:\b\d{{4}}-\d\d-\d\d(?!T)|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_NAME}\b\.?(?:,?\s+20\d\d)?|"
    rf"\b{_MONTH_NAME}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+20\d\d)?)\s*,?\s*$", re.I)


def _cutoff_words_end(q: str, start: int) -> int:
    """Where the question parser's cutoff words end: after the first time of their clause, with that time's own zone
    and date (D28: the clause used to end at any colon, so "As of 2026-07-30T14:35:00Z" held only "As of 2026-07-30T14"
    and the cutoff's own time was read as unaccounted for), or at the end of the clause (a comma, a colon outside a
    time, a semicolon, a dash, a bracket or a question mark) when it states no time."""
    clause = re.split(r"[,?;(—–]|(?<!\d):(?!\d)| - ", q[start:])[0][:80]
    times = _time_expressions(clause)
    if not times:
        return start + len(clause)
    end = start + times[0][1]
    m = _TIME_QUALIFIERS_RE.match(q, end)
    return m.end() if m else end


def resolve_cutoff(q: str, given_as_of: str | None, region: str | None, day: date | None,
                   routed: Routed | None) -> CutoffRequest:
    """The as-of cutoff (D26): the request field when given (authoritative); else the question parser's reading and
    the routing model's quoted words, each converted by code. A cutoff the model detected (its words, or a v12
    timestamp) that cannot be pinned down is sent back; the model's timestamps are never read. The located words of
    the cutoff are kept, so that they never narrow an analysis window."""
    from .request import extract_as_of

    out = CutoffRequest()
    m = AS_OF_Q_RE.search(q)
    if m:  # the parser's as-of words through the time they state, with that time's own zone and date
        end = _cutoff_words_end(q, m.end())
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
# a run named by its issue time and a time the question names that cannot be read as its half-hour (D27): the field
# only, with no time or quotation for the answer checks to read
NAMED_RUN_HALF_HOUR_CLARIFICATION = (
    "Which half-hour is the forecast asked about? The question names a forecast run and a time that cannot be read as "
    "one half-hour, so nothing is compared: no other half-hour or window is reviewed in its place. Give the "
    "half-hour's date with its year, its end time, and the time zone (for example AEST, market time or UTC).")
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


# ------------------------------------------------------------------------------------------------ the forecast request
# D28: what a forecast review asks for, its operation and its half-hour or period. The routing model's reading (route
# contract v14) is used only when its quoted words are located once in the question, are not another role's words or
# quoted background, and show the reading by themselves; the question parser reads positive phrasings only. The bounded
# vocabularies below detect a reading's evidence and its conflicts: an absence proves nothing (no comparison word never
# makes a request forecast-only), and grounded words do not by themselves prove a reading (every check still applies).

SINGLE_SCOPES = ("half_hour", "event_peak_half_hour")
PERIOD_SCOPES = ("whole_local_day", "event", "explicit")
# a comparison of a forecast with actual demand asked for
_COMPARISON_RE = re.compile(
    r"\b(?:compar(?:e|es|ed|ing|ison|isons)|versus|vs\.?|against\s+(?:the\s+|what\s+)?(?:actual\w*|measured|recorded|"
    r"outturn|happened)|errors?|miss(?:ed|es)?|accura(?:te|cy)|inaccura(?:te|cy)|perform(?:ed|s|ance)?|how\s+(?:close|"
    r"well|far\s+off)|stack(?:ed|s)?\s+up|turn(?:ed|s)?\s+out|higher\s+or\s+lower|lower\s+or\s+higher|"
    r"differ(?:ed|s|ence|ences)?|bias(?:ed)?|deviat\w*|mae|mean\s+absolute\s+error|over-?forecast\w*|under-?forecast\w*|"
    r"track(?:ed|s)?\s+actual\w*|off\s+by)\b", re.I)
# actual demand asked for: with a forecast, a comparison
_ACTUAL_RE = re.compile(r"\b(?:actual(?:ly|s)?|outturn)\b", re.I)
# actual demand mentioned for whether it was published, not asked for ("had any actual demand been published")
_ACTUAL_CONTEXT_RE = re.compile(
    r"\b(?:actual(?:ly|s)?|outturn)\b(?:\s+[\w'’-]+){0,6}?\s+(?:had|has|have|was|were|is|are|been)\b(?:\s+(?:not|yet|"
    r"already|been|then))*\s+(?:published|available|public|released|out|known)\b|\b(?:before|until|till|once|when|"
    r"after|whether)\s+(?:any\s+|the\s+)?(?:actual(?:ly|s)?|outturn)\b[^.?;]{0,40}?\b(?:published|available|public|"
    r"released|out|known)\b", re.I)
# a comparison declined ("without comparing it with actual demand", "not how it compared", "no actuals")
_NEGATED_RE = re.compile(
    r"\b(?:not|no|never|without|rather\s+than|instead\s+of|don['’]?t|do\s+not|does\s+not|doesn['’]?t|nor|need\s+not|"
    r"needn['’]?t|leave\s+out|ignor(?:e|ing)|exclud(?:e|ing))\b(?:\s+[\w'’-]+){0,4}?\s+(?:compar\w*|against|versus|vs\.?|"
    r"actual\w*|outturn|errors?|accura\w*)\b[^.?;,]{0,40}", re.I)
# what a forecast said asked for
_VALUE_RE = re.compile(
    r"\bwhat\b(?:\s+[\w'’-]+){0,3}?\s+(?:did|does|do|was|were|is|are|had|has)\b[^?.;]{0,100}?\b(?:forecasts?|"
    r"forecasted|runs?|poe\s?\d\d|median|figures?|values?|predictions?|projections?|expect\w*|predict\w*|project\w*|"
    r"show\w*|give|gave|say|said)\b|\bwhich\b[^?.;]{0,80}?\b(?:forecasts?|runs?)\b|\bwhat\s+was\s+known\b|"
    r"\b(?:forecasts?|runs?|it)\b[^?.;]{0,60}?\b(?:say|says|said|predict(?:ed|s)?|project(?:ed|s)?|expect(?:ed|s)?|"
    r"forecast(?:ed|s)?|give|gives|gave|show(?:ed|s)?)\b|\bhow\s+much\b[^?.;]{0,80}?\b(?:forecast(?:ed|s)?|predict(?:ed|s)?|"
    r"project(?:ed|s)?|expect(?:ed|s)?)\b|\b(?:predicted|projected|forecast|expected)\b[^?.;]{0,40}?\bby\b[^?.;]{0,40}?"
    r"\b(?:runs?|forecasts?)\b|\b(?:give|show|pull|get|report|list|provide|tell)\s+(?:me\s+|us\s+)?(?:[\w'’-]+\s+){0,6}?"
    r"(?:forecasts?|poe\s?\d\d|projections?|predictions?)\b|\bpoe\s?10\b[^?.;]{0,40}?\bpoe\s?90\b", re.I)
_QUOTED_RE = re.compile(r"[\"“]([^\"“”]{3,})[\"”]")  # quoted background: context, never the request's own words
_PEAK_HALF_HOUR_RE = re.compile(r"\b(?:peak|highest)\s+(?:(?:demand|price)\s+)?half[- ]hour\b|\bhalf[- ]hour\s+(?:of|"
                                r"at)\s+(?:the\s+)?(?:[\w'’-]+\s+)?peak\b", re.I)
# a date's role, from the words right before it: a run's issue or publication date, or the analysis's own
_RUN_DATE_LEAD_RE = re.compile(r"\b(?:issued|published|released|produced|prepared|made|created)\s+(?:on\s+|at\s+)?$",
                               re.I)
_ANALYSIS_DATE_LEAD_RE = re.compile(r"(?:^|\b(?:on|for|over|across|throughout|during|in|whole\s+of|all\s+of|"
                                    r"entire))\s*(?:the\s+)?$", re.I)
_DATE_OCC_RE = re.compile(
    rf"\b20\d\d-\d\d-\d\d\b(?!T)|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_NAME}\b\.?(?:,?\s+20\d\d)?|"
    rf"\b{_MONTH_NAME}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+20\d\d)?", re.I)
_PAREN_RE = re.compile(r"\s*\(([^()]{1,90})\)")


def _blank(text: str, matches: Sequence[re.Match[str]]) -> str:
    for m in matches:
        text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return text


_FORECAST_VERB_RE = re.compile(r"\b(?:expect|predict|project)(?:s|ed|ing)?\b", re.I)


def _asks_about_forecasts(text: str) -> bool:
    """A forecast is asked about: a forecast or run word, or a forecasting verb ("what did AEMO expect")."""
    return bool(_FC_WORD_RE.search(text) or _RUN_ONLY_RE.search(text) or _FORECAST_VERB_RE.search(text))


def question_operation(q: str, masked: str) -> tuple[str | None, Span | None, list[str]]:
    """The operation the question's own words ask for, read from positive phrasings only (D28): ``comparison``
    (comparison words, or actual demand asked for with a forecast) or ``forecast_value`` (what a forecast said); None
    when neither is shown. ``masked``: the question without other roles' words and quoted background. A declined
    comparison and a mention of actual demand's availability are not requests; a comparison both asked for and
    declined is a conflict. Returns the reading, its words and any conflict."""
    neg = list(_NEGATED_RE.finditer(masked))
    text = _blank(masked, neg + list(_ACTUAL_CONTEXT_RE.finditer(masked)))
    cmp_m, act_m, val_m = _COMPARISON_RE.search(text), _ACTUAL_RE.search(text), _VALUE_RE.search(text)
    fc = _asks_about_forecasts(masked)
    m, op = None, None
    if cmp_m or (act_m and (val_m or fc)):
        m, op = cmp_m or act_m, "comparison"
    elif val_m and fc:
        m, op = val_m, "forecast_value"
    sp = Span("operation", q[m.start():m.end()], ((m.start(), m.end()),), "question") if m else None
    conflicts = (["operation: a comparison with actual demand is both asked for and declined"]
                 if op == "comparison" and neg else [])
    return op, sp, conflicts


def _model_operation(model: RoutedForecast | None, q: str, other: list[Span]) -> tuple[str | None, Span | None,
                                                                                       str | None]:
    """The routing model's operation when grounded and evidenced by its own words; else None, with why not."""
    if model is None or model.operation == "none":
        return None, None, None
    if model.operation == "unclear":
        return "unclear", None, None
    sp = span("operation", model.operation_text, q)
    if sp is None or sp.located is None:
        return None, sp, "operation: the routing model's words are not located once in the question"
    if any(_overlap(sp, o) for o in other):
        return None, sp, f"operation: '{sp.text}' are another role's words or quoted background"
    clean = _blank(sp.text, list(_NEGATED_RE.finditer(sp.text)) + list(_ACTUAL_CONTEXT_RE.finditer(sp.text)))
    if model.operation != "forecast_value" and not (_COMPARISON_RE.search(clean) or _ACTUAL_RE.search(clean)):
        return None, sp, f"operation: '{sp.text}' shows no comparison with actual demand"
    if model.operation == "forecast_value" and not (_FC_WORD_RE.search(sp.text) or _RUN_ONLY_RE.search(sp.text) or
                                                    _VALUE_RE.search(sp.text)):
        return None, sp, f"operation: '{sp.text}' names no forecast"
    return model.operation, sp, None


def _date_roles(q: str, held: list[tuple[int, int]]) -> tuple[list[tuple[date, tuple[int, int]]], list[str]]:
    """The dates that scope the requested analysis, with their words, and the dates whose role is not shown (D28). A
    date in another role's words (the cutoff's, the run's, the target half-hour's) or in quoted background is that
    role's; one right after an issue or publication word is a run's; one right after an analysis word ("on", "for",
    "over", "across", "throughout", "during", "in", "the whole of") or at the question's start scopes the analysis; any
    other date's role is not shown."""
    analysis: list[tuple[date, tuple[int, int]]] = []
    ambiguous: list[str] = []
    for m in _DATE_OCC_RE.finditer(q):
        a, b = m.span()
        if any(x <= a and b <= y for x, y in held):
            continue
        d = _day_of(m.group(0), q)
        before = q[:a]
        if _RUN_DATE_LEAD_RE.search(before):
            continue
        if d is not None and _ANALYSIS_DATE_LEAD_RE.search(before):
            analysis.append((d, (a, b)))
        else:
            ambiguous.append(m.group(0))
    return analysis, ambiguous


def _restates(text: str, instants: set[datetime], region: str | None) -> bool:
    """Whether a bracket restates one of the instants: its ISO time is one of them, or its one clock is one of them in
    the zone the bracket names (any NEM zone when it names none), on the day it names when it names one."""
    if (iso := _ISO_RE.search(text)) is not None:
        return parse_iso(iso.group(1)) in instants
    clocks = _clocks(text)
    if len(clocks) != 1:
        return False
    _, _, hh, mm, ap = clocks[0]
    zones = [tz for tz, _ in _zones(text, region)] or [timezone(timedelta(minutes=o)) for o in sorted(set(_FIXED.values()))]
    full = set(_dates(text))
    md = {(MONTHS[(g[1] or g[2])[:3].lower()], int(g[0] or g[3])) for g in _DAY_MONTH_RE.findall(text)}
    for t in instants:
        for tz in zones:
            loc = t.astimezone(tz)
            if (loc.hour, loc.minute) == (_h24(hh, ap), mm) and (not full or loc.date() in full) and \
                    (not md or (loc.month, loc.day) in md):
                return True
    return False


def _restatements(q: str, held: list[tuple[tuple[int, int], set[datetime]]], region: str | None
                  ) -> list[tuple[int, int]]:
    """A bracket right after held words that restates their time ("ends at 2026-07-30T21:30:00Z (7:30 am AEST on 31
    July)"): held too. A bracket that states another instant is not."""
    out = []
    for (_, y), instants in held:
        m = _PAREN_RE.match(q, y)
        if m is not None and instants and _restates(m.group(1), instants, region):
            out.append((m.start(1), m.end(1)))
    return out


def _with_dates(q: str, a: int, b: int) -> tuple[int, int]:
    """Words widened to the zone and date written right after them, and a date right before them ("on 2026-07-30
    from 21:00 to 21:30 UTC"): a date written with a time is that time's date."""
    m = _TIME_QUALIFIERS_RE.match(q, b)
    lead = _LEAD_DATE_RE.search(q[:a])
    return (lead.start() if lead else a), (m.end() if m else b)


def _instants_in(text: str, q: str, region: str | None) -> set[datetime]:
    out = {parse_iso(m.group(1)) for m in _ISO_RE.finditer(text)}
    t, _ = _first_instant(text, q, region)
    return out | ({t} if t is not None else set())


def _on_grid(b: tuple[datetime, datetime]) -> bool:
    return all(t.second == 0 and t.microsecond == 0 and t.minute in (0, 30) for t in b) and b[1] > b[0]


# -- the domain (D29): what is forecast. Only a resolved operational-demand request enters the demand workflow.
_FORECAST_NOUN_RE = re.compile(r"\b(?:forecasts?|predictions?|projections?|outlooks?)\b", re.I)
_POE_RE = re.compile(r"\bpoe\s?(?:10|50|90)\b", re.I)
# a negation and the few words it governs, when they name a forecast or its subject ("not the demand forecast")
_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|rather\s+than|instead\s+of|don['’]?t|do\s+not|does\s+not|nor)\b"
                          r"(?:\s+[\w'’-]+){0,4}?\s+[\w'’-]*(?:forecast|prediction|projection|outlook|demand|load|weather|"
                          r"temperature|price)\w*\b", re.I)


def _subjects(text: str) -> dict[str, list[tuple[int, int]]]:
    """What each forecast the text names is of, read from the words written with it (D29): a weather, price or demand
    word among the two words right before the forecast word ("the weather forecast", "AEMO's demand forecasts"), or
    right after "of" or "for" ("forecasts of temperature"). Only the existing vocabularies (the Replay controller's
    weather words, the keyword router's price words, the demand words); a forecast whose words name none of them has
    no subject read here. Returns each subject with the words it was read from."""
    from .request import PRICE_WORD_RE, WEATHER_WORDS

    out: dict[str, list[tuple[int, int]]] = {}
    for m in _FORECAST_NOUN_RE.finditer(text):
        seg_start = max(text.rfind(c, 0, m.start()) for c in ".?;!") + 1
        words = list(re.finditer(r"[\w'’-]+", text[seg_start:m.start()]))[-2:]
        a = seg_start + words[0].start() if words else m.start()
        after = re.match(r"\s+(?:of|for)\s+(?:the\s+)?[\w'’-]+(?:\s+[\w'’-]+)?", text[m.end():])
        b = m.end() + (after.end() if after else 0)
        near = text[a:m.start()] + " " + (after.group(0) if after else "")
        for kind, rx in (("weather", WEATHER_WORDS), ("price", PRICE_WORD_RE), ("operational_demand", _DEMAND_WORD_RE)):
            if rx.search(near):
                out.setdefault(kind, []).append((a, b))
    return out


def question_domain(masked: str, run: RunRequest) -> tuple[str | None, list[str], list[tuple[int, int]],
                                                         tuple[int, int] | None]:
    """The domain the question parser establishes positively (D29), from ``masked`` (without quoted background and
    negated mentions): ``operational_demand`` when a forecast's words name demand, a POE level is named, a forecast
    run is asked for (the runs held are AEMO's operational-demand runs), or demand is named and a forecast asked about; a
    weather or price domain when a forecast's own words name it. Returns the domain (None when nothing is shown; "mixed"
    when demand and another kind are both asked for, which Replay cannot split into clauses), the other kinds asked
    for, their words, and the words that show demand."""
    subj = _subjects(masked)
    others = sorted(k for k in subj if k != "operational_demand")
    run_words = [sp.located for sp in run.spans if sp.role == "run_selection" and sp.located is not None]
    poe, word = _POE_RE.search(masked), _DEMAND_WORD_RE.search(masked)
    shown = (subj["operational_demand"][0] if "operational_demand" in subj else poe.span() if poe else
             (run_words[0] if run_words else (0, 0)) if run.status == "bound" and
             run.selection in ("last_issued_before", "issued_at") else
             word.span() if word and _asks_about_forecasts(masked) else None)
    words = [w for k in others for w in subj[k]]
    if shown is not None and others:
        return "mixed", others, words, shown
    if others:
        return (others[0] if len(others) == 1 else "other"), others, words, None
    return ("operational_demand" if shown is not None else None), [], [], shown


def _negated_before(q: str, sp: Span) -> bool:
    """Words that a negation right before them (or at their start) declines."""
    assert sp.located is not None
    a, b = sp.located
    return bool(re.search(r"\b(?:not|no|never|without|rather\s+than|instead\s+of|don['’]?t|do\s+not|does\s+not|nor)"
                          r"\s+(?:[\w'’-]+\s+){0,2}$", q[:a], re.I) or
                re.match(r"\s*(?:not|no|never|without|don['’]?t|do\s+not|nor)\b", q[a:b], re.I))


@dataclass
class DomainReading:
    """What a requested forecast is of (D29), as ``resolve_domain`` reads it: ``absent`` when no forecast is asked
    about at all; ``bound`` only for an operational-demand request; ``unsupported`` for a forecast of another kind
    only; ``mixed`` when the parser alone shows demand and another kind both asked for; ``unresolved`` when what is
    forecast cannot be told; ``conflict`` when the readings disagree. ``others``: the other kinds asked for; ``leave``:
    their words, left out of the demand request's reading; ``source``: the words that establish the domain."""
    status: str
    domain: str | None = None
    others: list[str] = field(default_factory=list)
    leave: list[Span] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    source: Source | None = None


def resolve_domain(q: str, model: RoutedForecast | None, run: RunRequest, background: list[Span]) -> DomainReading:
    """What the requested forecast is of (D29), from the routing model's grounded reading (route contract v15) or, when
    it reports none (Replay, every decision recorded before v15), the question parser's positive reading. The model's
    words establish provenance, not correctness: the parser can only show a conflict."""
    masked = _blank(_masked(q, background), list(_NEGATION_RE.finditer(_masked(q, background))))
    p_dom, p_others, p_words, p_shown = question_domain(masked, run)
    m_dom = model.domain if model is not None else None
    if m_dom in (None, "none") and (model is None or model.operation == "none") and p_dom is None and \
            not _asks_about_forecasts(masked):
        return DomainReading("absent")  # no forecast asked about at all: no forecast request (D28)
    if m_dom is None:  # not reported: the question parser's positive reading alone
        if p_dom == "operational_demand":
            assert p_shown is not None
            words = q[p_shown[0]:p_shown[1]] or "the forecast run asked for"  # a bound run whose words are not located
            return DomainReading("bound", p_dom, source=Source("question", words, "question parser"))
        if p_dom in ("weather", "price", "other"):
            return DomainReading("unsupported", p_dom, p_others)
        # "mixed": without the routing model's reading of the clauses, the requests cannot be split
        return DomainReading("mixed" if p_dom == "mixed" else "unresolved", None, p_others)
    if m_dom in ("none", "unclear"):
        return DomainReading("unresolved", None, p_others)
    assert model is not None
    sp = span("request", model.request_text, q)
    why = ("the request's words are not located once in the question" if sp is None or sp.located is None else
           "the request's words are quoted background" if any(_overlap(sp, o) for o in background) else
           "the request's words are negated" if _negated_before(q, sp) else None)
    if why:
        return DomainReading("unresolved", None, p_others, notes=[f"domain: {why}"])
    assert sp is not None and sp.located is not None
    a, b = sp.located
    inside = question_domain(" " * a + masked[a:b] + " " * (len(q) - b), run)[0]  # the clause's own words
    src = Source("route_model", sp.text, "the requested clause")
    if m_dom != "operational_demand":
        if inside == "operational_demand":
            return DomainReading("conflict", conflicts=[f"domain: {m_dom} (the routing model) for words that ask for "
                                                        "an operational demand forecast"])
        return DomainReading("unsupported", m_dom, [m_dom], source=src)
    if inside in ("weather", "price", "other", "mixed"):
        return DomainReading("conflict", conflicts=["domain: operational demand (the routing model) for words that "
                                                    "ask for a forecast of another kind"])
    for role, text in (("operation", model.operation_text), ("scope", model.scope_text)):
        r = span(role, text, q) if text else None
        if r is not None and r.located is not None and not (a <= r.located[0] and r.located[1] <= b):
            return DomainReading("conflict", conflicts=[f"domain: the {role}'s words are outside the requested clause"])
    us = span("unsupported", model.unsupported_text, q) if model.unsupported_text else None
    leave = [us] if us is not None and us.located is not None and not _overlap(us, sp) else []
    others = sorted(set(p_others) | ({"other"} if leave and not p_others else set()))
    # the words outside the requested clause that the parser reads as another kind's forecast are left out too
    leave += [Span("unsupported", q[x:y], ((x, y),), "question") for x, y in p_words if not (a <= x and y <= b)]
    return DomainReading("bound", "operational_demand", others, leave, source=src)


DEMAND_FORECAST_TOOLS = ("get_forecast_runs", "compare_forecast_actual")


def other_forecasts(q: str, routed: Routed | None, run: RunRequest) -> tuple[bool, list[str] | None]:
    """What an event review (or a forecast review whose request is a demand maximum) does with a forecast its question
    asks about (D29), from the same domain resolution as a forecast request: whether the demand-forecast tools may
    serve it (yes when no forecast is asked about, or the one asked about is a resolved operational-demand request),
    and the forecasts not answered (their kinds; [] when which forecast is meant is not shown; None when none)."""
    model = routed.requested.forecast if routed is not None and routed.requested is not None else None
    background = [Span("background", m.group(0), ((m.start(), m.end()),), "question") for m in _QUOTED_RE.finditer(q)]
    d = resolve_domain(q, model, run, background)
    if d.status == "absent":
        return True, None
    if d.status == "bound":
        return True, d.others or None
    if d.status == "unsupported":
        return False, d.others or [str(d.domain)]
    return False, []  # mixed, unresolved or in conflict: which forecast is meant is not shown


FORECAST_DOMAIN_CLARIFICATION = (
    "Which forecast is the question about? This assistant reviews AEMO's operational demand forecasts, and the "
    "question does not show that it asks about one, so nothing is compared or given.")
FORECAST_MIXED_CLARIFICATION = (
    "The question asks about AEMO's operational demand forecasts and also about a forecast of another kind (for "
    "example weather or prices). This assistant gives operational demand forecasts only, and the two requests cannot "
    "be told apart here, so nothing is compared or given. Ask about the operational demand forecast on its own.")
FORECAST_DOMAIN_CONFLICT = (
    "Which forecast is the question about? It can be read as asking about AEMO's operational demand forecasts and as "
    "asking about a forecast of another kind (for example weather or prices). Neither is assumed, so nothing is "
    "compared or given.")
FORECAST_UNSUPPORTED_CLARIFICATION = (
    "The question asks about a forecast of something other than operational demand (for example weather or prices). "
    "This assistant reviews AEMO's operational demand forecasts only and gives no other forecast, so it is not "
    "answered. Ask about operational demand forecasts, or about a market event.")


def not_answered_note(kinds: list[str]) -> str:
    """The part of a question that is not answered (D29): the field only, no time, number or quotation. ``kinds``:
    the other kinds of forecast asked for; [] when which forecast is meant is not shown."""
    if not kinds:
        return ("The question also mentions a forecast without showing which, so no AEMO operational demand forecast "
                "is compared or given for it.")
    what = " and ".join(k for k in kinds if k != "other") or "another kind of"
    return (f"Not answered: the question also asks about a {what} forecast. This assistant reviews AEMO's operational "
            "demand forecasts only and gives no other forecast.")


def resolve_forecast(q: str, req: InvestigateRequest, region: str | None, event: Any, routed: Routed | None,
                     run: RunRequest, cutoff: CutoffRequest, target: tuple[datetime, datetime] | None,
                     target_source: Source | None, target_words: list[tuple[int, int]]) -> ForecastAnalysis:
    """The operation and scope a forecast review asks for (D28), from the request's window fields, the question parser
    and the routing model's grounded reading, each checked (``docs/decisions.md`` D28):

    - **the operation:** the model's reading, evidenced by its own words, or the parser's positive reading; readings
      that disagree, or a comparison both asked for and declined, are a conflict; none is unresolved, never a default;
    - **the scope:** the request's window (authoritative); a half-hour the question or the run pins; an event's peak
      half-hour or window (a held event); a whole local day, from a date that scopes the analysis (not a run's, a
      target's or a cutoff's date); or an explicit start and end the model's words give. Distinct scopes are a
      conflict, none is unresolved, and a period that only dates a pinned half-hour is that half-hour's;
    - **every time** the question names must be held by a role's words (the cutoff's, the run's, the target's, the
      scope's, or a bracket restating one of them), else the scope is unresolved;
    - **supported windows only:** bounds on the half-hour grid, at most the forecast tools' 24 hours (a 25-hour DST
      day or a 24.5-hour event window is sent back), never clipped;
    - **consistency:** a comparison of one half-hour is a single-interval comparison, of a period a window
      comparison."""
    from .. import config

    out = ForecastAnalysis(detected_by=["intent"])
    model = routed.requested.forecast if routed is not None and routed.requested is not None else None
    background = [Span("background", m.group(0), ((m.start(), m.end()),), "question") for m in _QUOTED_RE.finditer(q)]
    run_words = [sp for sp in run.spans if sp.role == "run_selection" or (sp.role == "run_half_hour" and run.half_hour)]
    if (mi := ISSUED_AT_RE.search(q)) is not None:
        run_words.append(Span("run_selection", mi.group(0), (mi.span(),), "question"))
    other = list(cutoff.spans) + run_words + background
    # -- the domain (D29): only an operational-demand request is read further; a forecast of another kind asked for
    # too is left out of its reading, and named as not answered
    dom = resolve_domain(q, model, run, background)
    if dom.status == "absent":
        return ForecastAnalysis()
    out.domain, out.unsupported, out.notes = dom.domain, dom.others, out.notes + dom.notes
    if dom.source is not None:
        out.provenance["domain"] = dom.source
    if dom.status != "bound":
        out.status = "conflict" if dom.status == "conflict" else "unresolved"
        out.conflicts = dom.conflicts
        out.missing = [] if dom.status == "conflict" else [{"unsupported": "domain_unsupported",
                                                          "mixed": "domain_mixed"}.get(dom.status, "domain")]
        return out
    q = _masked(q, dom.leave)
    # -- the operation: read without the cutoff's words and quoted background (a run's words may say what is asked:
    # "what the forecast run issued at 16:57 projected")
    p_op, p_span, p_conflicts = question_operation(q, _masked(q, list(cutoff.spans) + background))
    if p_op is None and run.status == "bound" and run.selection in ("last_issued_before", "issued_at"):
        # one forecast run asked for by its rule, and no comparison asked for: what that run said (a positive reading,
        # never an absence; comparison words would have made it a comparison)
        p_op = "forecast_value"
        p_span = next((sp for sp in run_words if sp.role == "run_selection"), None)
    m_op, m_span, why = _model_operation(model, q, other)
    out.notes += [why] if why else []
    out.spans += [x for x in (m_span, p_span) if x is not None]
    out.detected_by += [s for s, hit in (("route_model", m_op is not None), ("question", p_op is not None)) if hit]
    if m_op == "unclear":
        out.status, out.missing = "unresolved", ["operation"]
        return out
    m_cls = None if m_op is None else "forecast_value" if m_op == "forecast_value" else "comparison"
    if p_conflicts or (m_cls and p_op and m_cls != p_op):
        out.status = "conflict"
        out.conflicts = p_conflicts or ["operation: what the forecast said, or how it compared with actual demand"]
        return out
    cls = m_cls or p_op
    if cls is None:
        out.status, out.missing = "unresolved", ["operation"]
        return out
    out.provenance["operation"] = (Source("route_model", str(m_span.text)) if m_cls and m_span is not None else
                                   Source("question", str(p_span.text if p_span else q), "question parser"))
    # -- the scope
    tw = [Span("target", q[a:b], ((a, b),), "question") for a, b in (_with_dates(q, x, y) for x, y in target_words)]
    # every role's words, with the instants they state; a bracket right after them restating one is held too
    roles = [(sp, _instants_in(sp.text, q, region) | (set(target) if target and sp in tw else set()) |
              ({cutoff.as_of} if sp.role == "cutoff" and cutoff.as_of else set()) |
              ({run.issued_at} if sp.role == "run_selection" and run.issued_at else set()))
             for sp in list(cutoff.spans) + run_words + tw if sp.located is not None]
    restated = [Span("restatement", q[a:b], ((a, b),), "question")
                for a, b in _restatements(q, [(sp.located, inst) for sp, inst in roles if sp.located], region)]
    readings: list[tuple[str, tuple[datetime, datetime], Source, list[Span]]] = []
    if target is not None:
        readings.append(("half_hour", target, target_source or Source("question", q, "question parser"), tw))
    scope_text = _masked(q, other + tw)
    if (pk := _PEAK_HALF_HOUR_RE.search(scope_text)) is not None:
        if event is not None:
            end = half_hour_end_for(parse_iso(event.peak_interval_end_utc))
            readings.append(("event_peak_half_hour", (end - timedelta(minutes=30), end),
                             Source("question", pk.group(0), f"the peak half-hour of {event.event_id}"),
                             [Span("scope", pk.group(0), (pk.span(),), "question")]))
        else:
            out.notes.append("scope: a peak half-hour is named, but no price event is held for it")
    if (ev := _EVENT_WINDOW_RE.search(scope_text)) is not None and event is not None:
        readings.append(("event", (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)),
                         Source("question", ev.group(0), f"the window of {event.event_id}"),
                         [Span("scope", ev.group(0), (ev.span(),), "question")]))
    m_scope = span("scope", model.scope_text, q) if model is not None and model.scope in SINGLE_SCOPES + PERIOD_SCOPES \
        else None  # its own date is that scope's, never a separate analysis date
    analysis, ambiguous = _date_roles(q, [sp.located for sp in other + tw + restated + ([m_scope] if m_scope else [])
                                          if sp.located is not None])
    days = sorted({d for d, _ in analysis})
    if len(days) > 1:
        out.status = "conflict"
        out.conflicts = ["scope: several dates are given for the analysis"]
        return out
    if days and region:
        words = [Span("scope", q[a:b], ((a, b),), "question") for d, (a, b) in analysis]
        readings.append(("whole_local_day", local_day_window(days[0], region),
                         Source("question", words[0].text, f"whole local day {days[0]} in {region}"), words))
    out.notes += [f"scope: the role of the date '{d}' is not shown" for d in ambiguous]
    run_model = routed.requested.forecast_run if routed is not None and routed.requested is not None else None
    if target is None and run_model is not None and run_model.half_hour_text and \
            (sp := span("scope", run_model.half_hour_text, q)) is not None and sp.located is not None and \
            not any(_overlap(sp, o) for o in list(cutoff.spans) + background):
        hh, _, conv = half_hour_from_text(sp.text, q, region)  # the routing model's quoted half-hour, read by code
        if hh is not None:
            readings.append(("half_hour", hh, Source("route_model", sp.text, conv), [sp]))
    if model is not None and model.scope in SINGLE_SCOPES + PERIOD_SCOPES:
        sp = span("scope", model.scope_text, q)
        fail = None
        if sp is None or sp.located is None:
            fail = "the routing model's words are not located once in the question"
        elif any(_overlap(sp, o) for o in list(cutoff.spans) + background +
                 [r for r in run_words if r.role == "run_selection"]):
            fail = f"'{sp.text}' are another role's words or quoted background"
        else:
            text, got = sp.text, None
            if model.scope == "half_hour":
                hh, _, conv = half_hour_from_text(text, q, region)
                got = (hh, conv) if hh is not None else None
            elif model.scope == "event_peak_half_hour" and event is not None and _PEAK_HALF_HOUR_RE.search(text):
                end = half_hour_end_for(parse_iso(event.peak_interval_end_utc))
                got = ((end - timedelta(minutes=30), end), f"the peak half-hour of {event.event_id}")
            elif model.scope == "whole_local_day" and _day_span_ok(text) and region:
                d = _day_of(text, q)
                got = (local_day_window(d, region), f"whole local day {d} in {region}") if d is not None else None
            elif model.scope == "event" and event is not None and _EVENT_WORD_RE.search(text):
                got = ((parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)),
                       f"the window of {event.event_id}")
            elif model.scope == "explicit":
                w, conv = window_from_text(text, q, region)
                got = (w, conv) if w is not None else None
            if got is None:
                fail = f"'{text}' does not give a {model.scope.replace('_', ' ')} that code can read"
            else:
                readings.append((model.scope, got[0], Source("route_model", text, got[1]), [sp]))
        if fail:
            out.notes.append(f"scope: {fail}")
    chosen: tuple[str, tuple[datetime, datetime], Source, list[Span]]
    if req.window_start_utc and req.window_end_utc:  # the request's window is authoritative
        chosen = ("explicit", (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc)),
                  Source("request", "window_start_utc, window_end_utc"), [])
    else:
        singles = [r for r in readings if r[0] in SINGLE_SCOPES]
        periods = [r for r in readings if r[0] in PERIOD_SCOPES]
        if len({r[1] for r in singles}) > 1:
            out.status, out.conflicts = "conflict", ["scope: two different half-hours"]
            return out
        if singles:
            t = singles[0][1]
            # a period that only dates the half-hour ("on 31 July ... the half-hour ending 8:00": its local or UTC
            # date, or the event that holds it) is the half-hour's; another stated period is another scope
            def dates_it(p: tuple[str, tuple[datetime, datetime], Source, list[Span]]) -> bool:
                if p[0] == "event":
                    return p[1][0] <= t[0] and t[1] <= p[1][1]
                if p[0] != "whole_local_day" or not region:
                    return False
                day = p[1][0].astimezone(region_zone(region)).date()  # the day the period is
                inner = (t[0], t[1] - timedelta(minutes=1))
                return day in {x.astimezone(region_zone(region)).date() for x in inner} | {x.date() for x in inner}
            if not all(dates_it(p) for p in periods):
                out.status, out.conflicts = "conflict", ["scope: a half-hour and a period"]
                return out
            chosen = next((r for r in singles if r[2].source == "route_model"), singles[0])
        elif periods:
            distinct = {r[1] for r in periods}
            evs = [r for r in periods if r[0] == "event"]
            if len(distinct) > 1 and evs and all(r[0] in ("event", "whole_local_day") for r in periods) and \
                    all(event is not None and r[1][0] <= half_hour_end_for(parse_iso(event.peak_interval_end_utc))
                        <= r[1][1] for r in periods):
                chosen = evs[0]  # an event named on its date: the date identifies the event
            elif len(distinct) > 1:
                out.status, out.conflicts = "conflict", ["scope: " + " or ".join(sorted({r[0] for r in periods}))]
                return out
            else:
                chosen = next((r for r in periods if r[2].source == "route_model"), periods[0])
        else:
            out.status, out.missing = "unresolved", ["scope"]
            return out
    kind, bounds, src, words = chosen
    out.spans += [w for w in words if w not in out.spans]
    # every time the question names must be held by a role's words, or restate one (a time no role holds may be the
    # half-hour asked about or narrow the period: D26's rule, here for a forecast review)
    held = [sp.located for sp in other + tw + restated + [w for r in readings for w in r[3]] + words
            if sp.located is not None]
    loose = [q[a:b] for a, b in _time_expressions(q)
             if not any(x <= a and b - (q[b - 1] == ".") <= y for x, y in held)]  # "3:57 pm." ends a sentence
    if loose:
        out.status, out.missing = "unresolved", ["scope"]
        out.notes.append(f"scope: the question names {', '.join(repr(t) for t in loose)}, which no role's words hold")
        return out
    if kind in PERIOD_SCOPES and _narrows(_masked(_masked(q, other + tw), words)):
        out.status, out.missing = "unresolved", ["scope"]
        out.notes.append("scope: other words narrow the period")
        return out
    if not _on_grid(bounds) or bounds[1] - bounds[0] > timedelta(hours=config.MAX_FORECAST_TARGET_HOURS):
        out.status, out.missing = "unresolved", ["window_limit"]
        out.notes.append(f"scope: ({iso_utc(bounds[0])}, {iso_utc(bounds[1])}] is not whole half-hours within "
                         f"{config.MAX_FORECAST_TARGET_HOURS} hours")
        return out
    single = kind in SINGLE_SCOPES
    op = "forecast_value" if cls == "forecast_value" else "single_interval_comparison" if single else "window_comparison"
    if m_op is not None and m_op != op:
        out.status = "conflict"
        out.conflicts = [f"operation: {m_op.replace('_', ' ')} (the routing model) for a "
                         f"{'half-hour' if single else 'period'}"]
        return out
    out.status, out.operation, out.scope = "bound", op, kind
    out.target, out.window = (bounds, None) if single else (None, bounds)
    out.provenance["scope"] = src
    return out


FORECAST_OPERATION_CLARIFICATION = (
    "Is the question asking what AEMO's forecast said, or how the forecast compared with actual demand? It cannot be "
    "told from the question, so nothing is compared or given in its place.")
FORECAST_OPERATION_CONFLICT = (
    "The question can be read as asking what the forecast said and as asking how it compared with actual demand. "
    "Which is meant? Neither is assumed.")
FORECAST_SCOPE_CLARIFICATION = (
    "Which half-hour or period is the forecast question about? Give one half-hour, one whole local day, a price event, "
    "or a start and an end, with the date and time zone. No default period is reviewed in its place.")
FORECAST_SCOPE_CONFLICT = (
    "The forecast question can be read as asking about two different half-hours or periods. Which is meant? Neither is "
    "assumed.")
# the field only: no time, number or quotation for the answer checks to read
FORECAST_LIMIT_CLARIFICATION = (
    "The period asked about is longer than a forecast comparison covers (at most one day), or is not made of whole "
    "half-hours. Give a period of whole half-hours within one day. Nothing is compared over part of it.")


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
                   else TIME_ZONE_CLARIFICATION if miss == {"time_zone"}
                   else NAMED_RUN_HALF_HOUR_CLARIFICATION if fr.selection == "issued_at" else HALF_HOUR_CLARIFICATION)
    fa = r.forecast  # D28: what a forecast review asks for, its operation and its half-hour or period
    if fa.status == "conflict":
        out.append(FORECAST_DOMAIN_CONFLICT if any(c.startswith("domain") for c in fa.conflicts) else
                   FORECAST_OPERATION_CONFLICT if any(c.startswith("operation") for c in fa.conflicts)
                   else FORECAST_SCOPE_CONFLICT)
    elif fa.status == "unresolved":
        out.append(FORECAST_UNSUPPORTED_CLARIFICATION if "domain_unsupported" in fa.missing else
                   FORECAST_MIXED_CLARIFICATION if "domain_mixed" in fa.missing else
                   FORECAST_DOMAIN_CLARIFICATION if "domain" in fa.missing else
                   FORECAST_OPERATION_CLARIFICATION if "operation" in fa.missing else FORECAST_LIMIT_CLARIFICATION
                   if "window_limit" in fa.missing else FORECAST_SCOPE_CLARIFICATION)
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
        out.append(PLAN_CUTOFF_CLARIFICATION if "cutoff_reference" in co.missing else CUTOFF_CLARIFICATION)
    return out
