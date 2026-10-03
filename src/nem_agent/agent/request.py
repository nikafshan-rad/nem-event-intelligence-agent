"""Investigation requests: explicit fields first, then conservative extraction from the question text.

The replay path uses a *scripted, rule-based router* (keyword rules below). It is labelled as such in every
report and in the evaluation; it is not presented as model reasoning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..selection import EventSelection, Selection
from ..timeutil import REGION_TZ, UTC, iso_utc, local_day_window, parse_iso, region_zone
from .playbook import INTENTS, Intent

ROUTER_VERSION = "scripted-router/3"  # 2: as-of forecast questions; 3: questions about notices


class InvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1000)
    region: Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"] | None = None
    event_date: date | None = Field(None, description="calendar date in the region's local time")
    window_start_utc: str | None = None
    window_end_utc: str | None = None
    as_of_utc: str | None = None
    mode: Literal["replay", "live"] = "replay"
    intent: Literal["market_event_review", "forecast_review", "source_explanation"] | None = None


REGION_WORDS: dict[str, tuple[str, ...]] = {
    "SA1": ("sa1", "south australia", "south australian", "adelaide"),
    "NSW1": ("nsw1", "new south wales", "nsw", "sydney"),
    "VIC1": ("vic1", "victoria", "victorian", "melbourne"),
    "QLD1": ("qld1", "queensland", "qld", "brisbane"),
    "TAS1": ("tas1", "tasmania", "tasmanian", "hobart"),
}
REGION_CODE_ONLY = {"SA1": r"\bSA\b", "VIC1": r"\bVIC\b", "TAS1": r"\bTAS\b"}
NON_NEM = re.compile(r"\b(western australia|wa1|wem|northern territory|nt1|perth|darwin)\b", re.I)
OUT_OF_SCOPE = re.compile(
    r"\b(place (a )?(trade|bid)|submit (a )?bid|rebid|should i (buy|sell)|buy|sell|hedge|trading strategy|"
    r"predict (the |tomorrow'?s |next week'?s )?price|price forecast for (tomorrow|next)|dispatch (a|the) unit|"
    r"switch off|control (the )?(grid|plant))\b", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class Resolution:
    request: InvestigateRequest
    intent: Intent | None
    region: str | None
    event: EventSelection | None
    window: tuple[datetime, datetime] | None
    as_of: datetime | None
    kind: Literal["high_price", "low_price"] = "high_price"
    status: Literal["ok", "needs_clarification", "refused"] = "ok"
    reasons: list[str] = field(default_factory=list)
    routing: dict[str, object] = field(default_factory=dict)
    # the forecast run a question names for the half-hour it asks about, as the controller resolved it (I-9); the
    # validator holds the answer to it
    forecast_run: dict[str, object] | None = None
    # the half-hour a forecast question asks about (start, end UTC), when it is pinned down (I-10)
    target: tuple[datetime, datetime] | None = None
    # each demand measure's maximum the question asks for, as the controller computed it (I-17); the validator holds
    # the answer to it
    demand_max: list[dict[str, object]] | None = None
    # the computed results the runtime verifier did not admit (D25): their bindings carry no value, and no statement may
    # give their value (``validation.unadmitted_result_violations``)
    results_not_admitted: list[Any] | None = None
    # the forecast-run and demand-maximum requests as resolved, with provenance (``structured.RequestResolution``,
    # I-18); None only for a resolution built elsewhere (tests)
    requests: Any = None


def extract_regions(text: str) -> list[str]:
    low = text.lower()
    found = []
    for code, words in REGION_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            found.append(code)
    for code, pat in REGION_CODE_ONLY.items():
        if code not in found and re.search(pat, text):
            found.append(code)
    return found


def extract_dates(text: str) -> list[date]:
    out: list[date] = []
    for y, m, d in re.findall(r"\b(20\d\d)-(\d\d)-(\d\d)\b", text):
        out.append(date(int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?\s+(20\d\d)\b", text):
        if mon[:3].lower() in MONTHS:
            out.append(date(int(y), MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", text):
        if mon[:3].lower() in MONTHS:
            out.append(date(int(y), MONTHS[mon[:3].lower()], int(d)))
    return sorted(set(out))


def extract_as_of(text: str, region: str | None, day: date | None) -> datetime | None:
    """``as of <ISO timestamp with offset>`` or ``as of/known at HH:MM`` (region local time on the event date)."""
    m = re.search(r"\bas of\s+(20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))", text, re.I)
    if m:
        return parse_iso(m.group(1))
    m = re.search(r"\b(?:as of|known at|known by|available by)\s+(\d{1,2}):(\d\d)\b", text, re.I)
    if m and region and day:
        local = datetime.combine(day, time(int(m.group(1)), int(m.group(2))), tzinfo=region_zone(region))
        return local.astimezone(UTC)
    return None


AS_OF_Q_RE = re.compile(r"\b(as of|known at|known by|available by)\b", re.I)
FORECAST_WORD_RE = re.compile(r"\bforecasts?\b|\bpoe ?(10|50|90)\b", re.I)


# "What did AEMO's market notices say ...", "According to the market notice ...": a question about what a document
# says is a source explanation, even when it mentions a price event, a forecast or a reserve condition (held-out H10,
# regression ADV02 were routed as forecast and event reviews). "... the outage AEMO put out a notice about" is not.
NOTICE_Q_RE = re.compile(r"\b(?:what did|what does|what do|according to)\b[^?]*\bnotices?\b|"
                         r"\bnotices?\b[^?]*\b(?:say|said|state[sd]?|report(?:ed)?)\b", re.I)
# "the forecast AEMO issued at 2026-07-30T11:56:59Z": an issue time names a forecast run; it is not an as-of cutoff
# (held-out H05 treated it as one and hid the actuals the question asked about)
# "issued at about <time>" names the same thing, approximately (held-out v3 V07, V08 were read as as-of cutoffs)
ISSUED_AT_RE = re.compile(r"\bissued\s+(?:at\s+|on\s+)?(?:(?:about|around|approximately|approx\.?|roughly|circa|"
                          r"near|~)\s*)?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)", re.I)


TOTAL_DEMAND_Q_RE = re.compile(r"\btotal[- ]?demand\b", re.I)
OPERATIONAL_DEMAND_Q_RE = re.compile(r"\boperational[- ]demand\b", re.I)


# "when did TAS1 total demand peak", "peak total demand", "the highest operational demand": a demand measure's
# maximum (held-out v6 Z04); not a value at the (price) peak ("total demand at the peak"). The peak or maximum word must
# be attached to the measure. A bare "demand" names no measure.
_MAX_MEASURES = {"total demand": r"(?:dispatch\s+)?(?:total[- ]?demand|TOTALDEMAND)",
                 "operational demand": r"(?:actual\s+)?operational[- ]demand",
                 "demand": r"(?<!total )(?<!total-)(?<!operational )(?<!operational-)\bdemand"}


def _max_of_re(m: str) -> re.Pattern[str]:
    return re.compile(
        rf"\bwhen\s+did\s+(?:[\w'’]+\s+){{0,3}}?{m}\s+(?:peak|top out|max out|reach (?:its|a) (?:peak|maximum|high))\b"
        rf"|\b{m}\s+(?:peaked|peaks|topped out|maxed out)\b"
        rf"|\b(?:peak|highest|maximum|max|top)\s+(?:(?:5-minute|five-minute|half-hour(?:ly)?|30-minute|daily|day's|"
        rf"dispatch)\s+)*{m}\b|\b{m}\s+(?:peak|maximum|max)\b(?!\s+(?:price|interval))", re.I)


_MAX_OF_RES = {k: _max_of_re(v) for k, v in _MAX_MEASURES.items()}
MAXIMUM_CLARIFICATION = (
    "Which demand measure is the peak asked about: dispatch total demand (TOTALDEMAND, a dispatch quantity) or "
    "operational demand (half-hourly)? They are different measures with different peaks.")


# The window a maximum is asked over (I-17 review). Only these are taken as given; anything else is sent back:
# - an explicit window in the request's own fields: exactly that window;
# - "during the event / spike / episode", "the event window": the event's window, when the resolution holds one;
# - a whole day ("the day's", "across 29 July 2026", "on 2026-07-29", "the whole day", "daily") with no wording that
#   narrows it (parts of the day, "between … and", "from … to", "around the peak" …): that local day.
_EVENT_WINDOW_RE = re.compile(r"\b(?:during|in|over|within|across|throughout|for)\s+(?:the|that|this)\s+(?:[\w$/-]+\s+){0,3}?"
                              r"(?:event|spike|episode|excursion)(?:'s)?(?:\s+window)?\b|\bevent(?:'s)?\s+window\b", re.I)
_WHOLE_DAY_RE = re.compile(r"\b(?:the|that) day's\b|\b(?:whole|entire|full)\s+day\b|\ball\s+(?:of\s+)?(?:the\s+)?day\b|"
                           r"\bdaily\b|\bthroughout\s+the\s+day\b|\b(?:on|across|for|throughout|over)\s+(?:\d{1,2}(?:st|nd|rd|th)?\s+"
                           r"[A-Za-z]{3,9}|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?|20\d\d-\d\d-\d\d)\b", re.I)
_SUB_WINDOW_RE = re.compile(r"\bbetween\b[^?.;]{0,40}?\band\b|\bfrom\s+[^?.;]{0,30}?\b(?:to|until|till)\b|\b(?:morning|"
                            r"afternoon|evening|night|overnight|midday|noon|midnight|early hours|peak hours|business hours)\b|"
                            r"\b(?:around|near|before|after|leading up to|following)\s+(?:the\s+)?(?:price\s+)?(?:peak|spike|"
                            r"event|extreme)\b|\b(?:first|last|next|previous)\s+(?:\d+\s+)?(?:hours?|minutes?|intervals?)\b|"
                            r"\bhours?\s+(?:before|after|around)\b", re.I)
MAXIMUM_WINDOW_CLARIFICATION = (
    "Over which window is the demand peak asked: the whole local day of the date given, the price event's window, or "
    "an explicit start and end with their time zone? The question does not pin it down, so no maximum is given in "
    "place of the one asked for.")
MAXIMUM_EVENT_CLARIFICATION = (
    "The question asks for the demand peak during an event, but no event is held for that region and date, so its "
    "window cannot be established. Give the window's start and end with their time zone, or ask for the whole day.")


def maximum_window_kind(question: str, req: InvestigateRequest) -> str:
    """How the window of a requested maximum is given: "explicit" (the request's window fields), "event" (relative to
    the event), "day" (a whole local day, with nothing narrowing it) or "unresolved"."""
    if req.window_start_utc and req.window_end_utc:
        return "explicit"
    if _EVENT_WINDOW_RE.search(question):
        return "event"
    if _WHOLE_DAY_RE.search(question) and not _SUB_WINDOW_RE.search(question):
        return "day"
    return "unresolved"


def requested_maxima(question: str) -> list[str]:
    """The demand measures whose maximum a question asks for ("total demand", "operational demand"), or ["demand"]
    when it asks for a demand peak without naming the measure."""
    named = [k for k in ("total demand", "operational demand") if _MAX_OF_RES[k].search(question)]
    return named or (["demand"] if _MAX_OF_RES["demand"].search(question) else [])


def requested_measures(question: str) -> dict[str, str]:
    """Which demand measure(s) a question names, and where each is found, so an answer does not substitute one for
    the other (held-out H02, H03 answered 'total demand' with operational demand; H14 the reverse)."""
    out: dict[str, str] = {}
    if TOTAL_DEMAND_Q_RE.search(question):
        out["total demand"] = ("dispatch TOTALDEMAND, 5-minute: get_price_timeline fields totaldemand_at_peak, "
                               "totaldemand_at_minimum, totaldemand_around_peak, totaldemand_around_minimum")
    if OPERATIONAL_DEMAND_Q_RE.search(question):
        out["operational demand"] = "half-hour operational demand: get_actual_demand (and forecasts: get_forecast_runs)"
    return out


def asks_about_notices(question: str) -> bool:
    return bool(NOTICE_Q_RE.search(question))


# Whether a question asks if something of the kind AEMO reports in a market notice (an outage, trip, fault,
# constraint, transfer limit, reserve shortfall, direction ...) caused, influenced or mattered for the event: then the
# notice's time against the event's intervals is the decisive observation (held-out H13 cited the notice but never said
# that its time came after every high-price interval). Two general vocabularies, one of influence and one of grid
# incidents, both required. They were written before the blind paraphrase set in tests/provider/data/ was read, and
# are not H13's wording: "did the transformer trip matter for the spike?" matches, "did low wind cause it?" does not.
INFLUENCE_Q_RE = re.compile(
    r"\b(caus\w*|because|due to|owing to|on account of|responsib\w*|driv\w*|drove|behind|trigger\w*|lead to|led to|"
    r"leading to|result(?:s|ed)? (?:of|from|in)|as a result|down to|stem\w* from|ar[io]s\w* from|blam\w*|culprit|"
    r"attribut\w*|explain\w*|explanat\w*|contribut\w*|factors?|matter(?:s|ed)?|significan\w*|bearing|bear on|"
    r"affect\w*|impact\w*|influenc\w*|role|part in|hand in|effects?|to do with|relat(?:ed|ion|e) to|link\w*|"
    r"connected (?:to|with)|connection (?:to|with|between)|tied to|trace\w* (?:back )?to|(?:feeds?|fed|feeding) into|"
    r"account(?:s|ed)? for|how much of|why|set off|spark\w*|push\w*|prompt\w*|tighten\w*|worsen\w*|exacerbat\w*|"
    r"amplif\w*|consequen\w*|knock-on|flow-on|on the back of|in response to|respond\w*|react\w*|correlat\w*|"
    r"coincid\w*|reasons?|but for|if not for|rule (?:\w+ )?out|chang\w* (?:how|the way|what))\b"
    # counterfactuals: "would prices have spiked without the trip?", "if AEMO hadn't invoked it, would ... still ..."
    r"|\bwould\b[^?]*\b(?:without|still|otherwise)\b|\bwithout\b[^?]*\bwould\b"
    r"|\bif\b[^?]*\b(?:hadn't|had not|wasn't|was not|weren't|were not|didn't|did not)\b", re.I)
INCIDENT_Q_RE = re.compile(
    r"\b(notices?|outages?|trip(?:s|ped|ping)?|faults?|failures?|lines?|transformers?|constraints?|contingenc\w*|"
    r"bus[- ]?ties?|bus ?bars?|interconnectors?|transfers?|transmission|breakers?|circuits?|substations?|feeders?|reclassif\w*|"
    r"lack of reserve|LOR ?\d?|reserves?|direct(?:ions?|ed|ing)|interventions?|limits?|islanding|separation|"
    r"switching|maintenance|de-?rat\w*|load[- ]?shed\w*|suspen\w*|administered|RERT|system strength|"
    # "Was Directlink being out of service what drove …?" (live check 2026-09-29, F04); not "offline", which a unit
    # kept off for commercial reasons also is (a blind negative)
    r"out of service|not in service|(?:returned|back) (?:to|in) service)\b", re.I)


def asks_if_notice_event_caused(question: str) -> bool:
    return bool(INFLUENCE_Q_RE.search(question) and INCIDENT_Q_RE.search(question))


# "Was AEMO's forecast lack of reserve the reason South Australia's price spiked …?": a question asking whether
# something caused, drove or explains a price event is an event review, whatever else it names (held-out v5 Y18 was
# routed as a forecast question for "forecast lack of reserve"). A question about forecast accuracy is not one, nor is
# an as-of question.
PRICE_EVENT_Q_RE = re.compile(
    r"\b(?:prices?|RRPs?|spot prices?)\b[^?.;]{0,40}?\b(?:spik\w*|jump\w*|surg\w*|soar\w*|peak\w*|extremes?|plung\w*|"
    r"crash\w*|negative|high(?:s|est)?|climb\w*|rose|rise|rising)\b|\bprice\s+(?:spikes?|jumps?|surges?|peaks?|extremes?|"
    r"events?)\b", re.I)
FORECAST_ACCURACY_Q_RE = re.compile(
    r"\bpoe ?(?:10|50|90)\b|\bforecast(?:s|ing)?\s+(?:errors?|accuracy|miss\w*|bias)\b|\bhow (?:close|accurate|far off)\b|"
    r"\baccura(?:te|cy)\b|\b(?:over|under)-?forecast\w*|\boperational[- ]demand forecasts?\b", re.I)


def asks_cause_of_price_event(question: str) -> bool:
    return bool(INFLUENCE_Q_RE.search(question) and PRICE_EVENT_Q_RE.search(question)
                and not FORECAST_ACCURACY_Q_RE.search(question) and not AS_OF_Q_RE.search(question))


def forecast_issue_time(question: str) -> datetime | None:
    """The issue time of a forecast run the question names, when it names one and asks nothing 'as of'."""
    m = ISSUED_AT_RE.search(question)
    return parse_iso(m.group(1)) if m and not AS_OF_Q_RE.search(question) else None


# "the final forecast issued before the half-hour from 21:00 to 21:30 UTC", "the last pre-interval forecast for the
# 07:30 to 08:00 UTC half-hour": a forecast run named by when it was issued relative to the half-hour asked about. It is
# the last run issued before that half-hour starts, not the last one available by then (held-out v5 Y05, Y06 were given
# the run available by then, issued three hours earlier). Wording about availability or publication ("the latest
# forecast available before the half-hour", "published before") asks for another selection and is not read here.
_NOT_ISSUE_TIME = r"(?!\w*(?:availab|public|publish|known|released))"
ISSUED_BEFORE_RE = re.compile(
    r"\b(?:issued|produced|made)\s+(?:just\s+|immediately\s+|right\s+)?(?:before|ahead of|prior to)"
    r"\s+(?:the|that|this)\s+(?:half[- ]hour|interval|target|period)\b|\bpre[- ]?interval\b|"
    rf"\b(?:last|latest|final|most recent)\b(?:\s+{_NOT_ISSUE_TIME}[\w'’-]+){{0,8}}?\s+(?:before|ahead of|prior to)\s+"
    r"(?:the|that|this)\s+(?:half[- ]hour|interval|period)\b", re.I)
_ZONE = r"(UTC|AEST|AEDT|ACST|ACDT|NEM time|market time)"
_HALF_HOUR_RANGE_RE = re.compile(rf"(?<![\d:T])([01]?\d|2[0-3]):([0-5]\d)\s*{_ZONE}?\s*(?:to|-|–|—|until)\s*"
                                 rf"([01]?\d|2[0-3]):([0-5]\d)\s*{_ZONE}?", re.I)
_HALF_HOUR_ENDING_RE = re.compile(rf"\b(?:ending|ends)\s+(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\s*{_ZONE}", re.I)
_END_WORD = r"(?:ending|ends|ended|finishing|finishes|finished)"
_ISO_Z = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z"
_HALF_HOUR_ENDING_ISO_RE = re.compile(rf"\b{_END_WORD}\s+(?:at\s+)?({_ISO_Z})", re.I)
# "the half-hour finishing at 07:30 on 31 July in market time (UTC 2026-07-30T21:30:00Z)" (held-out v6 Z05): a clock
# that ends the half-hour, its own date and zone written after it in either order, and an ISO instant in brackets right
# after that restates it (alone, or labelled only "UTC", "=" or "i.e."; a bracketed time labelled anything else, such as
# a publication or issue time, is another time)
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")
_DATE_WORDS = (rf"(?:20\d\d-\d\d-\d\d(?!T)|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+20\d\d)?|"
               rf"{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+20\d\d)?)")
_HALF_HOUR_END_CLOCK_RE = re.compile(
    rf"\b{_END_WORD}\s+(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)(?![\d:])"
    rf"((?:\s*,?\s*(?:(?:on\s+)?{_DATE_WORDS}|(?:in\s+)?(?:UTC|AEST|AEDT|ACST|ACDT|NEM time|market time)\b))*)"
    rf"(?:\s*\(\s*(?:(?:UTC|=|i\.e\.,?)\s*)?({_ISO_Z})\s*\))?", re.I)
_ZONE_WORD_RE = re.compile(r"\b(UTC|AEST|AEDT|ACST|ACDT|NEM time|market time)\b", re.I)
# alternatives after one ending word ("finishing at 07:30 or 08:00 AEST"): more than one half-hour
_END_CLOCK_LIST_RE = re.compile(rf"\b{_END_WORD}\s+(?:at\s+)?\d{{1,2}}:\d\d(?![\d:])[^.;:?()]{{0,40}}?\b(?:or|and)\s+"
                                r"(?:at\s+)?\d{1,2}:\d\d", re.I)
_DAY_MONTH_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})|\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)


@dataclass(frozen=True)
class ForecastRequest:
    """The forecast run a question names: by its issue time ("issued at …Z") or as the last one issued before the
    half-hour asked about; with that half-hour (start, end UTC), or None when the question does not pin it down."""
    run: Literal["issued_at", "last_issued_before"]
    issued_at: datetime | None
    half_hour: tuple[datetime, datetime] | None


def half_hour_asked(question: str) -> tuple[datetime, datetime] | None:
    """The one half-hour a question asks about (start, end UTC): a clock range with its zone on one date ("from 21:00
    to 21:30 UTC on 2026-07-30"), a clock that ends it with its zone and date ("the half-hour ending HH:MM <zone> on
    <date>", "finishing at 07:30 on 31 July 2026 in market time"), or an ISO end time ("ends at 2026-07-30T21:30:00Z",
    or in brackets right after the clock it restates). Nothing is guessed: a date without its year, or a clock without
    its zone, only checks the ISO time that restates it. None when it is not pinned down: no zone, no date, not 30
    minutes, several half-hours (also "ending 07:30 or 08:00"), an ending clock that cannot be dated or zoned, or a
    clock and its restatement that disagree."""
    issued = ISSUED_AT_RE.search(question)
    text = question if issued is None else question[:issued.start()] + " " * (issued.end() - issued.start()) + \
        question[issued.end():]
    if _END_CLOCK_LIST_RE.search(text):
        return None
    days = extract_dates(text)
    found: set[tuple[datetime, datetime]] = set()

    def at(day: date, hh: str, mm: str, zone: str) -> datetime:
        tz = timezone(timedelta(minutes=_CLOCK_ZONE_MIN[zone.lower()]))
        return datetime.combine(day, time(int(hh), int(mm)), tzinfo=tz).astimezone(UTC)

    for m in _HALF_HOUR_ENDING_ISO_RE.finditer(text):
        end = parse_iso(m.group(1))
        found.add((end - timedelta(minutes=30), end))
    if len(days) == 1:
        for m in _HALF_HOUR_RANGE_RE.finditer(text):
            zone = m.group(6) or m.group(3)
            if zone:
                a, b = at(days[0], m.group(1), m.group(2), zone), at(days[0], m.group(4), m.group(5), zone)
                found.add((a, b if b > a else b + timedelta(days=1)))
    for m in _HALF_HOUR_END_CLOCK_RE.finditer(text):
        hh, mm, quals, iso = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        offsets = {_CLOCK_ZONE_MIN[z.lower()] for z in _ZONE_WORD_RE.findall(quals)}
        own = extract_dates(quals)  # a full date written with the clock
        md = {(MONTHS[(g[1] or g[2])[:3].lower()], int(g[0] or g[3])) for g in _DAY_MONTH_RE.findall(quals)}
        if len(offsets) > 1 or len(own) > 1 or len(md) > 1:
            return None  # two zones or two dates for one clock
        day = own[0] if own else (next(iter(d for d in days if (d.month, d.day) in md), None) if md
                                  else days[0] if len(days) == 1 else None)
        if not iso and not (offsets and day is not None):
            return None  # a half-hour named by a clock that is not pinned down: not skipped in favour of another
        if offsets and day is not None:
            off = next(iter(offsets))
            end = datetime.combine(day, time(hh, mm), tzinfo=timezone(timedelta(minutes=off))).astimezone(UTC)
            found.add((end - timedelta(minutes=30), end))
        if iso:
            end = parse_iso(iso)
            local = [end + timedelta(minutes=o) for o in (offsets or set(_CLOCK_ZONE_MIN.values()))]
            if not any((t.hour, t.minute) == (hh, mm) and (day is None or t.date() == day)
                       and (not md or (t.month, t.day) in md) for t in local):
                return None  # the restatement is not the clock's instant
            found.add((end - timedelta(minutes=30), end))
    found = {(a, b) for a, b in found if b - a == timedelta(minutes=30) and b.minute in (0, 30) and b.second == 0}
    return next(iter(found)) if len(found) == 1 else None


def half_hour_after_cutoff(question: str, as_of: datetime) -> tuple[datetime, datetime] | None:
    """A clock-only half-hour with its zone ("the 23:00 to 23:30 UTC half-hour"), in a question that names no date,
    dated by an explicit as-of cutoff: its occurrence on the cutoff's own date in that zone, when that starts at or
    after the cutoff (the forecast is of a time still to come). Anything else is not safe to date: None (held-out v5
    Y07: cutoff 2026-08-19T20:00Z, half-hour 23:00-23:30Z on the 19th)."""
    if extract_dates(question) or _HALF_HOUR_ENDING_ISO_RE.search(question):
        return None
    found: set[tuple[datetime, datetime]] = set()
    for m in _HALF_HOUR_RANGE_RE.finditer(question):
        zone = m.group(6) or m.group(3)
        if zone:
            tz = timezone(timedelta(minutes=_CLOCK_ZONE_MIN[zone.lower()]))
            day = as_of.astimezone(tz).date()
            a = datetime.combine(day, time(int(m.group(1)), int(m.group(2))), tzinfo=tz).astimezone(UTC)
            b = datetime.combine(day, time(int(m.group(4)), int(m.group(5))), tzinfo=tz).astimezone(UTC)
            found.add((a, b if b > a else b + timedelta(days=1)))
    for m in _HALF_HOUR_ENDING_RE.finditer(question):
        tz = timezone(timedelta(minutes=_CLOCK_ZONE_MIN[m.group(3).lower()]))
        day = as_of.astimezone(tz).date()
        end = datetime.combine(day, time(int(m.group(1)), int(m.group(2))), tzinfo=tz).astimezone(UTC)
        found.add((end - timedelta(minutes=30), end))
    found = {(a, b) for a, b in found if b - a == timedelta(minutes=30)}
    if len(found) != 1:
        return None
    a, b = next(iter(found))
    return (a, b) if a >= as_of else None


HALF_HOUR_CLARIFICATION = (
    "Which half-hour is the forecast asked about? The question asks for the last forecast run issued before a "
    "half-hour, but does not pin that half-hour down, so no run can be chosen. Give the half-hour's date with its "
    "year, its end time, and the time zone (for example AEST, market time or UTC).")


def requested_forecast(question: str) -> ForecastRequest | None:
    """The forecast run a question names, for the half-hour it asks about. An as-of question names none: the run public
    by then is chosen by availability."""
    if AS_OF_Q_RE.search(question):
        return None
    issued = forecast_issue_time(question)
    if issued is None and not ISSUED_BEFORE_RE.search(question):
        return None
    return ForecastRequest("issued_at" if issued else "last_issued_before", issued, half_hour_asked(question))


def asks_forecast_as_of(question: str) -> bool:
    """An as-of question about forecasts asks what issued forecasts said at that time: a forecast review, even when it
    also names an event or a price spike (L3 live: AMB06 was routed as an event review; the replay router tied)."""
    return bool(AS_OF_Q_RE.search(question) and FORECAST_WORD_RE.search(question))


# "By how much did total demand climb from 06:30 to 07:30?", "how much did it fall", "the change in demand from ...":
# a question asking for the change between two values (held-out v4 W04 gave both values and no rise)
CHANGE_Q_RE = re.compile(
    r"\bby how much\b|\bhow (?:much|far) (?:did|does|has|had|was|were|is)\b[^?]*\b(?:rise|rose|risen|climb|increase|"
    r"grow|grew|jump|fall|fell|drop|decrease|decline|change|move)\w*|\b(?:rise|climb|increase|fall|drop|decrease|decline|"
    r"change|jump)\s+(?:in|of)\b[^?]*\bfrom\b|\bdifference between\b", re.I)
# a clock time named in a question ("06:30 AEST", "7:30 am market time"); not inside an ISO timestamp
QUESTION_CLOCK_RE = re.compile(r"(?<![\d:T])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])\s*(am|pm|a\.m\.|p\.m\.)?(?![a-z])"
                               r"\s*(AEST|AEDT|ACST|ACDT|UTC|NEM time|market time)?\b", re.I)
QUESTION_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z\b")
_CLOCK_ZONE_MIN = {"aest": 600, "aedt": 660, "acst": 570, "acdt": 630, "utc": 0, "nem time": 600, "market time": 600}
# a time that is an as-of cutoff or a forecast's issue time, not a time the question asks about
_CUTOFF_BEFORE_RE = re.compile(r"\b(?:as of|known at|known by|available by|issued(?: at| on)?)\s+(?:(?:about|around|"
                               r"approximately|roughly|circa|near|~)\s*)?(?:(?:on\s+)?\d{1,2}(?:st|nd|rd|th)?\s+"
                               r"[A-Za-z]{3,9}\.?\s+20\d\d,?\s+(?:at\s+)?)?$", re.I)


def asks_for_change(question: str) -> bool:
    return bool(CHANGE_Q_RE.search(question))


def named_instants(question: str, region: str, day: date) -> list[datetime]:
    """The distinct instants (UTC) a question names, in order: ISO timestamps, and clock times on ``day`` in the zone
    they state (AEST, "market time", UTC ...) or else the region's local time. As-of cutoffs and issue times are left
    out."""
    out: list[datetime] = []
    for m in QUESTION_ISO_RE.finditer(question):
        if not _CUTOFF_BEFORE_RE.search(question[:m.start()]):
            out.append(parse_iso(m.group(0)))
    for m in QUESTION_CLOCK_RE.finditer(question):
        if _CUTOFF_BEFORE_RE.search(question[:m.start()]):
            continue
        hh, mm, half, zone = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower(), (m.group(4) or "").lower()
        if half and not 1 <= hh <= 12:
            continue  # "14:00 pm" names no time
        if half:
            hh = hh % 12 + (12 if half.startswith("p") else 0)
        tz = timezone(timedelta(minutes=_CLOCK_ZONE_MIN[zone])) if zone else region_zone(region)
        out.append(datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(UTC))
    return list(dict.fromkeys(out))


def route(question: str) -> tuple[Intent | None, dict[str, object]]:
    """Scripted keyword router. Returns (intent or None when out of scope, diagnostics)."""
    q = question.lower()
    scores = {i: 0 for i in INTENTS}
    if re.search(r"\b(forecast|forecasts|poe ?50|poe ?10|poe ?90|predicted|prediction|forecast error|miss(ed)?|"
                 r"under-?forecast|over-?forecast|issued|as of|known at)\b", q):
        scores["forecast_review"] += 2
    if re.search(r"\b(price|prices|spike|rrp|\$/mwh|what happened|negative|high-price|low-price|expensive|cheap|"
                 r"generation|interconnector|event)\b", q):
        scores["market_event_review"] += 2
    if re.search(r"\b(what (does|is|are|do)|define|definition|meaning|mean by|difference between|explain (the )?term|"
                 r"what did aemo('s)? (say|notice|report)|market notice|notice say|according to aemo|documentation)\b", q):
        scores["source_explanation"] += 3
    if re.search(r"\b(did|how did|what happened|compare|versus|vs\.?|against)\b", q):
        scores["market_event_review"] += 1 if scores["market_event_review"] else 0
        scores["forecast_review"] += 1 if scores["forecast_review"] else 0
    if asks_about_notices(question):  # also when no keyword scored ("market notices" is not "market notice")
        return "source_explanation", {"scores": scores, "router": ROUTER_VERSION, "rule": "question about notices"}
    best = max(scores.values())
    if best == 0:
        return None, {"scores": scores, "router": ROUTER_VERSION}
    ranked = sorted(scores, key=lambda k: (-scores[k], INTENTS.index(k)))
    if ranked[0] == "market_event_review" and asks_forecast_as_of(question):
        return "forecast_review", {"scores": scores, "router": ROUTER_VERSION, "rule": "as-of forecast question"}
    return ranked[0], {"scores": scores, "router": ROUTER_VERSION}


def _event_for(sel: Selection, region: str, day: date) -> EventSelection | None:
    for ev in sel.events:
        if ev.region != region:
            continue
        a, b = parse_iso(ev.window_start_utc), parse_iso(ev.window_end_utc)
        d0, d1 = local_day_window(day, region)
        peak_local = parse_iso(ev.peak_interval_end_utc).astimezone(region_zone(region)).date()
        if peak_local == day or (a < d1 and d0 < b and peak_local == day):
            return ev
    for ev in sel.events:  # a window overlapping the day
        if ev.region == region:
            a, b = parse_iso(ev.window_start_utc), parse_iso(ev.window_end_utc)
            d0, d1 = local_day_window(day, region)
            if a < d1 and d0 < b:
                return ev
    return None


def resolve(req: InvestigateRequest, sel: Selection, routed: Any = None,
            given: InvestigateRequest | None = None) -> Resolution:
    """``routed``: the routing model's structured reading of the request (``structured.RoutedRequest``), or None when
    it reported none (Replay mode, a route without the field). None is "not reported", never "no requirement".
    ``given``: the request as the user gave it, when ``req`` also carries the routing model's values (Live); only the
    user's own fields are request fields whose conflict with the question's wording is noted."""
    from .structured import (
        RequestResolution,
        clarifications,
        request_field_notes,
        resolve_maximum,
        resolve_run,
    )

    q = req.question
    if NON_NEM.search(q):
        return Resolution(req, None, None, None, None, None, status="refused",
                          reasons=["The question refers to a market outside the NEM regions covered (NSW1, QLD1, SA1, "
                                   "TAS1, VIC1). No data is loaded for it."])
    if OUT_OF_SCOPE.search(q):
        return Resolution(req, None, None, None, None, None, status="refused",
                          reasons=["Out of scope: this is a read-only research assistant. It does not trade, bid, "
                                   "control assets or forecast future prices."])
    diag: dict[str, object] = {"router": "explicit"}
    intent: Intent | None = req.intent
    if intent is None:
        intent, diag = route(q)
    if intent is None:
        return Resolution(req, None, None, None, None, None, status="needs_clarification", routing=diag,
                          reasons=["The question does not match a supported investigation (market event review, "
                                   "forecast review, or public-document explanation). Please rephrase."])
    regions = [req.region] if req.region else extract_regions(q)
    reasons: list[str] = []
    region = regions[0] if len(regions) == 1 else None
    if len(regions) > 1:
        reasons.append(f"Several regions are mentioned ({', '.join(regions)}); choose one region.")
    dates = [req.event_date] if req.event_date else extract_dates(q)
    day = dates[0] if len(dates) == 1 else None
    if len(dates) > 1:
        reasons.append(f"Several dates are mentioned ({', '.join(map(str, dates))}); choose one event date.")
    kind: Literal["high_price", "low_price"] = "low_price" if re.search(r"\b(negative|low[- ]price|cheap)\b", q, re.I) else "high_price"
    window: tuple[datetime, datetime] | None = None
    event = None
    if req.window_start_utc and req.window_end_utc:
        window = (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
    elif region and day:
        event = _event_for(sel, region, day)
        if event:
            window = (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc))
            kind = event.kind
        else:
            window = local_day_window(day, region)
    as_of = parse_iso(req.as_of_utc) if req.as_of_utc else extract_as_of(q, region, day)
    # the forecast run and the demand maximum the question asks for: from the request, the question parsers and the
    # routing model's grounded reading, with provenance; a detected request that is not bound is sent back (I-18)
    data_intent = intent in ("market_event_review", "forecast_review")
    requests = RequestResolution(routed="reported" if routed is not None else "not reported")
    if data_intent:
        requests.forecast_run = resolve_run(q, region, routed)
    target = None
    if intent == "forecast_review" and region:
        # the half-hour asked about is the target; an as-of cutoff only says what was public (I-10). An explicit date or
        # ISO time names the target; a clock-only half-hour is dated by the cutoff only when that is safe. A bound
        # forecast-run request names it too (I-18)
        target = half_hour_asked(q)
        if target is None and requests.forecast_run.status == "bound" and requests.forecast_run.half_hour:
            target = requests.forecast_run.half_hour
        if target is None and not dates and as_of is not None:
            target = half_hour_after_cutoff(q, as_of)
            if target is not None:
                diag["target_dated_by_cutoff"] = [iso_utc(target[0]), iso_utc(target[1])]
        if target is not None and not (window and window[0] <= target[0] and target[1] <= window[1]):
            # the window reviewed is the target's: its local day, or that day's event window when it contains it
            day = target[0].astimezone(region_zone(region)).date()
            event = _event_for(sel, region, day)
            if event and parse_iso(event.window_start_utc) <= target[0] and target[1] <= parse_iso(event.window_end_utc):
                window, kind = (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc)), event.kind
            else:
                event, window = None, local_day_window(day, region)
            diag["window_from_target"] = str(day)
        if window is None and not dates and as_of is not None:
            reasons.append("Which date is the half-hour (or period) asked about? The as-of cutoff says what was public "
                           "by then, not which day the forecast is for.")
    if data_intent:
        requests.maximum = resolve_maximum(q, req, region, day, event, routed)
        requests.notes = request_field_notes(q, given or req, region, day, requests.maximum)
        # a run named relative to a half-hour that is not pinned down (held-out v6 Z05, I-16), a demand peak without
        # its measure, or over a window that is not given (I-17), and any other detected request that is not bound
        # (I-18): sent back, naming what is missing, rather than guessed
        reasons += clarifications(requests)
    needs_data = intent in ("market_event_review", "forecast_review")
    if needs_data and region is None and not reasons:
        reasons.append("Which NEM region (NSW1, QLD1, SA1, TAS1 or VIC1)?")
    if needs_data and window is None and not dates and not any("date" in r for r in reasons):
        reasons.append("Which date (or UTC window) should be investigated?")
    if needs_data and window is not None and window[1] - window[0] > timedelta(hours=48):
        reasons.append("The requested window is longer than the 48-hour investigation bound.")
    status: Literal["ok", "needs_clarification", "refused"] = "needs_clarification" if reasons else "ok"
    if intent == "source_explanation" and len(regions) <= 1 and len(dates) <= 1:
        status, reasons = "ok", []
    return Resolution(req, intent, region, event, window, as_of, kind=kind, status=status, reasons=reasons,
                      routing={**diag, "regions_found": regions, "dates_found": [str(d) for d in dates],
                               "region_tz": REGION_TZ.get(region or "", None), "requests": requests.as_dict()},
                      target=target, requests=requests)
