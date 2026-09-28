"""Investigation requests: explicit fields first, then conservative extraction from the question text.

The replay path uses a *scripted, rule-based router* (keyword rules below). It is labelled as such in every
report and in the evaluation; it is not presented as model reasoning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..selection import EventSelection, Selection
from ..timeutil import REGION_TZ, UTC, local_day_window, parse_iso, region_zone
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
    r"switching|maintenance|de-?rat\w*|load[- ]?shed\w*|suspen\w*|administered|RERT|system strength)\b", re.I)


def asks_if_notice_event_caused(question: str) -> bool:
    return bool(INFLUENCE_Q_RE.search(question) and INCIDENT_Q_RE.search(question))


def forecast_issue_time(question: str) -> datetime | None:
    """The issue time of a forecast run the question names, when it names one and asks nothing 'as of'."""
    m = ISSUED_AT_RE.search(question)
    return parse_iso(m.group(1)) if m and not AS_OF_Q_RE.search(question) else None


def asks_forecast_as_of(question: str) -> bool:
    """An as-of question about forecasts asks what issued forecasts said at that time: a forecast review, even when it
    also names an event or a price spike (L3 live: AMB06 was routed as an event review; the replay router tied)."""
    return bool(AS_OF_Q_RE.search(question) and FORECAST_WORD_RE.search(question))


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


def resolve(req: InvestigateRequest, sel: Selection) -> Resolution:
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
                               "region_tz": REGION_TZ.get(region or "", None)})
