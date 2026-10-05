"""The experimental confirmed-request workflow: question, request preview, confirmation or correction, computed answer.

Opt-in in the app ("Experimental: confirm the request first"); the default workflow is unchanged. It builds on the D31
path and adds no request-understanding of its own:

- **Interpretation** is one routing call (route contract v16, prompts v17, V1) and the D31 compiler
  (``service.interpret_request``). Its compiled request becomes a structured draft (``from_resolution``): what it bound,
  what it left unresolved, and the parts it names as not answered. The draft is the system's interpretation of the
  request, not proof that the question was understood.
- **Clarification is incremental.** Code finds the next missing, conflicting or invalid field (``issues``), in
  dependency order, and asks one question about it, with choices where the values are bounded. A choice maps straight
  into the draft (``apply``); a typed answer is read by the existing request parsers (``parse_reply``); a reply they
  cannot read may be given to the routing model in one call for that turn, and only fills fields still open
  (``merge``). Fields already resolved are kept, any can be revised, and dependent fields are revalidated. Nothing
  unresolved is invented, and no consequential default is applied silently: what a value means is shown with it.
- **Confirmation** applies to one exact revision (``revision_id``); any edit makes a new revision. A complete draft
  becomes an ``Executable`` (``executable``); an unfinished one never does. The confirmed request is executed as it was
  shown (``to_resolution``, ``service.execute_confirmed``): no second model call, by the scripted controller with the
  existing calculations, runtime verification and computed-answer renderer.
- **Scope:** demand maxima, and forecast comparisons (a named run for one half-hour, or the accuracy over a period of at
  most 24 hours). Anything else is shown as not computed here, and nothing runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from .. import config
from ..selection import EventSelection, Selection
from ..timeutil import (
    REGION_TZ,
    UTC,
    half_hour_end_for,
    iso_utc,
    local_day_window,
    local_str,
    parse_iso,
    region_zone,
)
from .replay import Composer, ReplayController
from .request import Resolution, extract_dates, extract_regions

Operation = Literal["demand_maximum", "single_interval_comparison", "window_comparison"]
OPERATIONS: tuple[str, ...] = ("demand_maximum", "single_interval_comparison", "window_comparison")
OPERATION_LABEL = {
    "demand_maximum": "Demand maximum: when, and how high, a demand measure peaked",
    "single_interval_comparison": "Forecast vs actual for one half-hour, under a named forecast run",
    "window_comparison": "Forecast accuracy over a period (MAE and mean error against actual operational demand)",
    "forecast_value": "A forecast's values, with no comparison",
}
MEASURES = ("operational demand", "total demand")
MEASURE_LABEL = {"operational demand": "Operational demand (half-hourly)",
                 "total demand": "Dispatch total demand (TOTALDEMAND, 5-minute)"}
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
REGION_LABEL = {"NSW1": "NSW1 (New South Wales)", "QLD1": "QLD1 (Queensland)", "SA1": "SA1 (South Australia)",
                "TAS1": "TAS1 (Tasmania)", "VIC1": "VIC1 (Victoria)"}
SCOPE_LABEL = {"half_hour": "one half-hour", "day": "the whole local day", "event": "the price event's window",
               "explicit": "a stated period"}
RUN_LABEL = {"latest_before_each": "no single run: for each half-hour, the latest run issued before it began",
             "last_issued_before": "the last run issued before the half-hour began",
             "issued_at": "the run issued at a stated time"}
FIELDS = ("operation", "measure", "region", "date", "scope_kind", "half_hour_end", "period", "run", "issued_at",
          "cutoff")
FORECAST_OPS = ("single_interval_comparison", "window_comparison")
INTERPRETATION_LABEL = ("System interpretation of the request (the routing model's reading, compiled by code). It is "
                        "not proof that the question was understood.")
STRUCTURED_LABEL = ("Guided structured input: this request is built from your choices only. Your question was not "
                    "read by any model, so nothing here is an interpretation of it, and no natural-language "
                    "extraction took place.")
MIXED_LABEL = ("Guided structured input, with fields read from your replies by the routing model (marked "
               "\"interpretation (reply)\"). It is not proof that the question was understood.")


class Draft(BaseModel):
    """The request as it stands: every field with its source ("interpretation", "request field", "you" or "rule"),
    and why a field the interpretation could not settle is open (``blocked``)."""
    model_config = ConfigDict(extra="forbid")
    question: str
    operation: str | None = None
    measure: str | None = None
    region: str | None = None
    date: str | None = None  # the local date, YYYY-MM-DD, in the region's time
    scope_kind: Literal["half_hour", "day", "event", "explicit"] | None = None
    half_hour_end: str | None = None  # HH:MM local: the end of the half-hour
    start_time: str | None = None  # HH:MM local
    end_time: str | None = None  # HH:MM local; 24:00 ends the day
    run: Literal["latest_before_each", "last_issued_before", "issued_at"] | None = None
    issued_at_utc: str | None = None
    cutoff: Literal["absent", "set", "unresolved"] = "absent"
    cutoff_utc: str | None = None
    not_answered: list[str] = Field(default_factory=list)
    operation_options: list[str] = Field(default_factory=list)  # the operations still possible; [] = all
    sources: dict[str, str] = Field(default_factory=dict)
    blocked: dict[str, str] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)  # why the interpretation was sent back, shown in the preview
    refused: str | None = None
    origin: Literal["interpretation", "structured"] = "interpretation"  # structured: no model reading of the question
    revision: int = 0


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class Issue:
    """The next thing to settle: one field, why, and the choices offered (none: a typed answer)."""
    field: str
    message: str
    choices: tuple[Choice, ...] = ()
    hint: str | None = None


class Executable(BaseModel):
    """A complete, validated request: exactly what runs when it is confirmed."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: str
    operation: Operation
    measure: Literal["operational demand", "total demand"]
    region: Literal["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]
    date: str
    scope_kind: Literal["half_hour", "day", "event", "explicit"]
    start_utc: str
    end_utc: str
    start_local: str
    end_local: str
    half_hours: int
    event_id: str | None
    run: Literal["latest_before_each", "last_issued_before", "issued_at"] | None
    issued_at_utc: str | None
    cutoff_utc: str | None
    not_answered: tuple[str, ...]
    intent: Literal["forecast_review", "market_event_review"]
    revision: int


# ------------------------------------------------------------------------------------------------ times
_CLOCK_RE = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*$", re.I)


def parse_clock(text: str) -> str | None:
    """A clock time as HH:MM (24-hour; 24:00 ends the day), or None."""
    m = _CLOCK_RE.match(text or "")
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "")
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "pm" else 0)
    if mi > 59 or h > 24 or (h == 24 and mi):
        return None
    return f"{h:02d}:{mi:02d}"


def parse_period(text: str) -> tuple[str, str] | None:
    parts = re.split(r"\s*(?:-|–|—|\bto\b|\buntil\b)\s*", (text or "").strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    a, b = parse_clock(parts[0]), parse_clock(parts[1])
    return (a, b) if a and b else None


def _at(day: str, hhmm: str, region: str) -> datetime:
    d = date.fromisoformat(day)
    if hhmm == "24:00":
        d, hhmm = d + timedelta(days=1), "00:00"
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=region_zone(region)).astimezone(UTC)


def _hhmm(t: datetime, region: str, day: str) -> str:
    loc = t.astimezone(region_zone(region))
    if loc.date() == date.fromisoformat(day) + timedelta(days=1) and (loc.hour, loc.minute) == (0, 0):
        return "24:00"
    return loc.strftime("%H:%M")


def event_for(sel: Selection, region: str | None, day: str | None) -> EventSelection | None:
    """The verified price event on that local date in that region, as the resolver finds it (``request._event_for``)."""
    from .request import _event_for

    if not region or not day:
        return None
    return _event_for(sel, region, date.fromisoformat(day))


def bounds(d: Draft, sel: Selection) -> tuple[datetime, datetime] | None:
    """The UTC bounds of the draft's half-hour or period, from its local fields (None while they are incomplete)."""
    if not d.region or not d.date or not d.scope_kind:
        return None
    if d.scope_kind == "half_hour":
        if not d.half_hour_end:
            return None
        end = _at(d.date, d.half_hour_end, d.region)
        return end - timedelta(minutes=30), end
    if d.scope_kind == "day":
        return local_day_window(date.fromisoformat(d.date), d.region)
    if d.scope_kind == "event":
        ev = event_for(sel, d.region, d.date)
        return (parse_iso(ev.window_start_utc), parse_iso(ev.window_end_utc)) if ev else None
    if not d.start_time or not d.end_time:
        return None
    return _at(d.date, d.start_time, d.region), _at(d.date, d.end_time, d.region)


def _on_grid(t: datetime) -> bool:
    return t.second == 0 and t.microsecond == 0 and t.minute in (0, 30)


# ------------------------------------------------------------------------------------------------ from the compile
def from_resolution(res: Resolution, question: str, decision: dict[str, Any] | None = None,
                    given: dict[str, Any] | None = None) -> Draft:
    """The draft of a compiled request: what the D31 compiler bound, what it left open and why, and the parts it names
    as not answered. Values come from the resolution only (and, for an operation the compiler left open, the plan's
    own operation kind); nothing open is filled in. ``given``: the request fields the user gave, which are labelled
    as such."""
    d = Draft(question=question)
    src: dict[str, str] = {}
    req = res.request.model_copy(update={k: (given or {}).get(k) for k in ("region", "as_of_utc", "window_start_utc")})
    if res.status == "refused":
        d.refused = " ".join(res.reasons) or "Refused as out of scope."
        return d
    if res.status != "ok":
        d.reasons = list(res.reasons)
    rq = res.requests
    regions = [str(x) for x in cast(list[Any], res.routing.get("regions_found") or [])]
    dates = [str(x) for x in cast(list[Any], res.routing.get("dates_found") or [])]
    if res.region:
        d.region, src["region"] = res.region, "request field" if req.region else "interpretation"
    elif len(regions) > 1:
        d.blocked["region"] = f"Several regions are named ({', '.join(regions)})."
    if rq is None:
        d.blocked["operation"] = " ".join(res.reasons) or "The request could not be read."
        d.sources = src
        return d
    plan = rq.plan or {}
    fa, mx, fr, co = rq.forecast, rq.maximum, rq.forecast_run, rq.cutoff
    d.not_answered = sorted(set(plan.get("not_answered") or []) | set(fa.unsupported or []))
    window: tuple[datetime, datetime] | None = None
    if any("several asked operations" in p for p in plan.get("problems") or []):
        d.blocked["operation"] = ("The question asks for more than one analysis. This workflow runs one at a time and "
                                  "does not choose between them.")
    elif plan.get("problems"):
        d.blocked["operation"] = "The routing model returned an invalid request plan, so nothing in it is used."
    elif mx.status != "absent":
        d.operation, src["operation"] = "demand_maximum", "interpretation"
        if len(mx.measures) == 1 and mx.measures[0] in MEASURES and "measure" not in mx.missing:
            d.measure, src["measure"] = mx.measures[0], "interpretation"
        elif "measure" in mx.missing or not mx.measures:
            d.blocked["measure"] = "The question does not say which demand measure."
        if mx.status == "bound" and mx.window:
            window = mx.window
            d.scope_kind = {"day": "day", "event": "event"}.get(str(mx.window_kind), "explicit")  # type: ignore[assignment]
        elif mx.status in ("unresolved", "conflict") and set(mx.missing) - {"measure"}:
            d.blocked["scope_kind"] = "The window of the demand peak is not pinned down."
    elif fa.status != "absent" or rq.forecast_run.status != "absent" or res.intent == "forecast_review":
        if fa.operation in OPERATION_LABEL:
            d.operation, src["operation"] = fa.operation, "interpretation"
        if fa.status in ("unresolved", "conflict"):
            miss = set(fa.missing)
            if miss & {"domain", "domain_unsupported", "domain_mixed", "operation"} or fa.conflicts:
                d.operation = None
                d.blocked["operation"] = " ".join(res.reasons) or "What the forecast request asks for is not shown."
            elif d.operation is None and _plan_kind(decision, plan) == "forecast_comparison":
                # a comparison whose half-hour or period is open: one half-hour or a period is what decides it
                d.operation_options = ["single_interval_comparison", "window_comparison"]
                d.blocked["operation"] = ("The question asks for a forecast comparison, but its half-hour or period "
                                          "is not pinned down.")
            else:
                d.blocked["scope_kind"] = "The half-hour or period asked about is not pinned down."
        if fa.status == "bound":
            window = fa.target or fa.window
            d.scope_kind = {"half_hour": "half_hour", "event_peak_half_hour": "half_hour", "whole_local_day": "day",  # type: ignore[assignment]
                            "event": "event"}.get(str(fa.scope), "explicit")
        if fr.status == "bound" and fr.selection in ("last_issued_before", "issued_at"):
            d.run, src["run"] = fr.selection, "interpretation"
            if fr.issued_at:
                d.issued_at_utc = iso_utc(fr.issued_at)
        elif fr.status == "as_of_availability" and fa.operation == "window_comparison":
            d.run, src["run"] = "latest_before_each", "interpretation"  # the latest run public by the cutoff
        elif fr.status == "as_of_availability":
            d.blocked["run"] = ("The newest run public by the cutoff is not one named run, which a comparison for "
                                "one half-hour needs here.")
        elif fr.status in ("unresolved", "conflict"):
            d.blocked["run"] = "The forecast run asked for is not pinned down."
        elif fa.status == "bound" and fa.operation == "window_comparison":
            # no run named: the existing definition of a period comparison, shown as such in the preview
            d.run, src["run"] = "latest_before_each", "rule (no run named)"
    else:
        d.blocked["operation"] = " ".join(res.reasons) or "No demand maximum or forecast comparison is asked for."
    if window is not None and d.region:
        lo, hi = window
        day = lo.astimezone(region_zone(d.region)).date().isoformat()
        if d.scope_kind == "event" and res.event is not None:  # an event is dated by its peak
            day = parse_iso(res.event.peak_interval_end_utc).astimezone(region_zone(d.region)).date().isoformat()
        d.date, src["date"] = day, "interpretation"
        if d.scope_kind == "half_hour":
            d.half_hour_end = _hhmm(hi, d.region, day)
        elif d.scope_kind == "explicit":
            d.start_time, d.end_time = _hhmm(lo, d.region, day), _hhmm(hi, d.region, day)
            if d.end_time != "24:00" and hi.astimezone(region_zone(d.region)).date().isoformat() != day:
                d.start_time = d.end_time = None
                d.blocked["period"] = "The stated period runs into the next day; state it within one local day."
        for f in ("scope_kind", "half_hour_end", "period"):
            src[f] = "request field" if req.window_start_utc and f != "half_hour_end" else "interpretation"
    elif len(dates) == 1:
        d.date, src["date"] = dates[0], "interpretation"
    elif len(dates) > 1:
        d.blocked["date"] = f"Several dates are named ({', '.join(dates)})."
    if co.status == "bound" and co.as_of:
        d.cutoff, d.cutoff_utc = "set", iso_utc(co.as_of)
        src["cutoff"] = "request field" if req.as_of_utc else "interpretation"
    elif co.status in ("unresolved", "conflict"):
        d.cutoff = "unresolved"
        d.blocked["cutoff"] = "The question states an as-of cutoff that could not be pinned down."
    d.sources = src
    return d


def _plan_kind(decision: dict[str, Any] | None, plan: dict[str, Any]) -> str | None:
    """The kind of the plan's primary operation, as the routing model gave it (None without a v16 decision)."""
    ops = ((decision or {}).get("plan") or {}).get("operations") or []
    return next((o.get("kind") for o in ops if o.get("id") == plan.get("primary")), None)


# ------------------------------------------------------------------------------------------------ what is open
def _dates_with_events(sel: Selection, region: str | None) -> list[str]:
    days = {parse_iso(e.peak_interval_end_utc).astimezone(region_zone(e.region)).date().isoformat()
            for e in sel.events if region is None or e.region == region}
    return sorted(days)


def issues(d: Draft, sel: Selection) -> list[Issue]:
    """What still has to be settled before the request can run, in dependency order; [] when it is complete. Computed
    by code from the draft alone."""
    out: list[Issue] = []
    if d.refused:
        return [Issue("refused", d.refused)]
    op = d.operation
    if op not in OPERATIONS:
        why = d.blocked.get("operation") or (
            f"The request reads as {OPERATION_LABEL[op].lower()}, which this experimental workflow does not compute."
            if op in OPERATION_LABEL else "What should be worked out?")
        return [Issue("operation", why + (" Choose one analysis:" if op in OPERATION_LABEL or d.blocked.get("operation")
                                          else ""),
                      tuple(Choice(o, OPERATION_LABEL[o]) for o in (d.operation_options or OPERATIONS)))]
    if op == "demand_maximum" and d.measure not in MEASURES:
        out.append(Issue("measure", (d.blocked.get("measure", "") + " Which demand measure?").strip(),
                         tuple(Choice(m, MEASURE_LABEL[m]) for m in MEASURES)))
    if d.region not in REGIONS:
        out.append(Issue("region", (d.blocked.get("region", "") + " Which NEM region?").strip(),
                         tuple(Choice(r, REGION_LABEL[r]) for r in REGIONS)))
    if not d.date:
        days = _dates_with_events(sel, d.region)
        out.append(Issue("date", (d.blocked.get("date", "") + " Which date (the region's local date)?").strip(),
                         tuple(Choice(x, f"{x} (a verified price event)") for x in days),
                         "or type a date, e.g. 29 July 2026"))
    if out:
        return out[:1]
    assert d.region and d.date
    ev = event_for(sel, d.region, d.date)
    if op == "single_interval_comparison":
        if d.scope_kind not in (None, "half_hour"):
            return [Issue("half_hour_end", "A comparison for one half-hour needs one half-hour. Which half-hour? Give "
                                           "the time it ends, in the region's local time.", (), "e.g. 18:30")]
        if not d.half_hour_end:
            choices: tuple[Choice, ...] = ()
            if ev is not None:
                end = _hhmm(half_hour_end_for(parse_iso(ev.peak_interval_end_utc)), d.region, d.date)
                choices = (Choice(end, f"The half-hour ending {end}, which holds the price event's peak"),)
            return [Issue("half_hour_end", (d.blocked.get("scope_kind", "") + " Which half-hour? Give the time it "
                                            "ends, in the region's local time.").strip(), choices, "e.g. 18:30")]
    else:
        cap = timedelta(hours=config.MAX_FORECAST_TARGET_HOURS if op in FORECAST_OPS else config.MAX_PRICE_WINDOW_HOURS)
        day_lo, day_hi = local_day_window(date.fromisoformat(d.date), d.region)
        allowed = [Choice("day", f"The whole local day ({d.date})")] if day_hi - day_lo <= cap else []
        if ev is not None and parse_iso(ev.window_end_utc) - parse_iso(ev.window_start_utc) <= cap:
            allowed.append(Choice("event", "The price event's window on that date"))
        allowed.append(Choice("explicit", "A period you state (start and end time)"))
        if d.scope_kind is None or d.scope_kind == "half_hour" or (d.scope_kind == "event" and ev is None):
            why = d.blocked.get("scope_kind", "")
            if d.scope_kind == "event" and ev is None:
                why = "No verified price event is held for that region and date."
            return [Issue("scope_kind", (why + " Over which period?").strip(), tuple(allowed))]
        if d.scope_kind == "explicit" and not (d.start_time and d.end_time):
            return [Issue("period", (d.blocked.get("period", "") + " Give the start and end times, in the region's "
                                     "local time.").strip(), (), "e.g. 17:00-21:00")]
    b = bounds(d, sel)
    assert b is not None
    lo, hi = b
    if not (_on_grid(lo) and _on_grid(hi)) or hi <= lo:
        field_ = "half_hour_end" if d.scope_kind == "half_hour" else "period"
        return [Issue(field_, "That is not a whole half-hour, or the period ends before it starts. Times must be on "
                              "the hour or half-hour.", (), "e.g. 18:30" if field_ == "half_hour_end" else
                      "e.g. 17:00-21:00")]
    limit = config.MAX_FORECAST_TARGET_HOURS if op in FORECAST_OPS else config.MAX_PRICE_WINDOW_HOURS
    if hi - lo > timedelta(hours=limit):
        # only periods that fit are offered: never the one just found too long
        cap = timedelta(hours=limit)
        day_lo, day_hi = local_day_window(date.fromisoformat(d.date), d.region)
        fits = []
        if d.scope_kind != "day" and day_hi - day_lo <= cap:
            fits.append(Choice("day", f"The whole local day ({d.date})"))
        if d.scope_kind != "event" and ev is not None and \
                parse_iso(ev.window_end_utc) - parse_iso(ev.window_start_utc) <= cap:
            fits.append(Choice("event", "The price event's window on that date"))
        fits.append(Choice("explicit", "A period you state (start and end time)"))
        return [Issue("scope_kind", f"The period is longer than the {limit}-hour limit for this analysis; it is never "
                                    "cut short. Choose a shorter period.", tuple(fits))]
    if op == "single_interval_comparison" and d.run not in ("last_issued_before", "issued_at"):
        return [Issue("run", (d.blocked.get("run", "") + " Which forecast run should be compared with the actual?")
                      .strip(), (Choice("last_issued_before", RUN_LABEL["last_issued_before"]),
                                 Choice("issued_at", RUN_LABEL["issued_at"])))]
    if op == "window_comparison" and d.run not in ("latest_before_each", "issued_at"):
        return [Issue("run", (d.blocked.get("run", "") + " Which forecast runs should be compared with the actuals?")
                      .strip(), (Choice("latest_before_each", RUN_LABEL["latest_before_each"]),
                                 Choice("issued_at", RUN_LABEL["issued_at"])))]
    if op in FORECAST_OPS and d.run == "issued_at":
        issued = parse_iso(d.issued_at_utc) if d.issued_at_utc else None
        if issued is None:
            return [Issue("issued_at", "When was the run issued? Give an ISO time with its zone, or a local time on "
                                       f"{d.date}.", (), "e.g. 2026-07-30T18:56:59Z or 05:00")]
        if issued >= lo:
            return [Issue("issued_at", "That run would be issued after the half-hour or period begins; a forecast run "
                                       "must be issued before it. When was the run issued?", (),
                          "e.g. 2026-07-30T18:56:59Z or 05:00")]
    if d.cutoff == "unresolved" or (d.cutoff == "set" and not d.cutoff_utc):
        return [Issue("cutoff", (d.blocked.get("cutoff", "") + " Give the as-of cutoff as an ISO time with its zone, "
                                 "or run without one.").strip(),
                      (Choice("absent", "Run without an as-of cutoff (all data held is used)"),),
                      "e.g. 2026-07-30T14:35:00Z")]
    return []


# ------------------------------------------------------------------------------------------------ answers
def apply(d: Draft, field_: str, value: Any, sel: Selection) -> Draft:
    """The draft with one field set by the user (a new revision). Dependent fields that no longer fit are cleared, so
    they are asked again; the rest are kept and revalidated by ``issues``."""
    n = d.model_copy(deep=True)
    n.revision += 1
    n.blocked.pop(field_, None)
    n.sources[field_] = "you"
    if field_ == "operation":
        if value not in OPERATIONS:
            raise ValueError(f"unsupported operation {value!r}")
        old, n.operation = n.operation, value
        n.operation_options = []
        if value != old:
            n.blocked = {k: v for k, v in n.blocked.items() if k in ("region", "date", "cutoff")}
            if value != "demand_maximum":
                n.measure = None
            if value == "single_interval_comparison" and n.scope_kind != "half_hour":
                n.scope_kind = None
            if value != "single_interval_comparison" and n.scope_kind == "half_hour":
                n.scope_kind, n.half_hour_end = None, None
            n.run, n.issued_at_utc = None, None
            for f in ("measure", "scope_kind", "half_hour_end", "period", "run", "issued_at"):
                n.sources.pop(f, None)
    elif field_ == "measure":
        if value not in MEASURES:
            raise ValueError(f"unsupported measure {value!r}")
        n.measure = value
    elif field_ == "region":
        if value not in REGIONS:
            raise ValueError(f"unknown region {value!r}")
        n.region = value  # local times are kept and converted again; an event scope is checked again
    elif field_ == "date":
        date.fromisoformat(value)
        n.date = value
    elif field_ == "scope_kind":
        if value not in ("day", "event", "explicit"):
            raise ValueError(f"unsupported scope {value!r}")
        n.scope_kind = value
        n.half_hour_end = None
        if value != "explicit":
            n.start_time = n.end_time = None
    elif field_ == "half_hour_end":
        if parse_clock(value) != value:
            raise ValueError(f"not a clock time: {value!r}")
        n.scope_kind, n.half_hour_end = "half_hour", value
        n.sources["scope_kind"] = "you"
    elif field_ == "period":
        a, b = value
        if parse_clock(a) != a or parse_clock(b) != b:
            raise ValueError(f"not a period: {value!r}")
        n.scope_kind, n.start_time, n.end_time = "explicit", a, b
        n.sources["scope_kind"] = "you"
    elif field_ == "run":
        if value not in RUN_LABEL:
            raise ValueError(f"unsupported run selection {value!r}")
        n.run = value
        if value != "issued_at":
            n.issued_at_utc = None
    elif field_ == "issued_at":
        n.issued_at_utc = iso_utc(parse_iso(value))
        n.run = "issued_at"
    elif field_ == "cutoff":
        if value in (None, "absent"):
            n.cutoff, n.cutoff_utc = "absent", None
        else:
            n.cutoff, n.cutoff_utc = "set", iso_utc(parse_iso(value))
    else:
        raise ValueError(f"unknown field {field_!r}")
    return n


def parse_reply(field_: str, text: str, d: Draft) -> Any:
    """A typed answer to the question about ``field_``, read by the existing parsers; None when it cannot be read."""
    t = (text or "").strip()
    if field_ == "region":
        found = extract_regions(t) or [r for r in REGIONS if r.lower() == t.lower()]
        return found[0] if len(found) == 1 else None
    if field_ == "date":
        try:
            return date.fromisoformat(t).isoformat()
        except ValueError:
            days = extract_dates(t)
            return days[0].isoformat() if len(days) == 1 else None
    if field_ == "half_hour_end":
        return parse_clock(t)
    if field_ == "period":
        return parse_period(t)
    if field_ in ("issued_at", "cutoff"):
        if field_ == "cutoff" and t.lower() in ("none", "no", "no cutoff", "without", "absent"):
            return "absent"
        try:
            return iso_utc(parse_iso(t))
        except ValueError:
            hhmm = parse_clock(t)
            if hhmm and d.date and d.region:
                return iso_utc(_at(d.date, hhmm, d.region))
            return None
    choices = {c.value: c for c in (Choice(o, o) for o in [*OPERATIONS, *MEASURES, *RUN_LABEL, "day", "event",
                                                            "explicit"])}
    return t if t in choices else None


def merge(d: Draft, new: Draft) -> Draft:
    """A new interpretation (a typed reply read by the routing model) merged into the draft: it fills only fields that
    are still open; a field already resolved, by the user or otherwise, is kept."""
    n = d.model_copy(deep=True)
    n.revision += 1
    pairs = {"operation": ("operation",), "measure": ("measure",), "region": ("region",), "date": ("date",),
             "scope_kind": ("scope_kind", "half_hour_end", "start_time", "end_time"),
             "run": ("run", "issued_at_utc")}
    for key, attrs in pairs.items():
        if getattr(n, key) is None and getattr(new, key) is not None:
            for a in attrs:
                setattr(n, a, getattr(new, a))
            n.sources[key] = "interpretation (reply)"
            n.blocked.pop(key, None)
    if n.cutoff == "unresolved" and new.cutoff == "set":
        n.cutoff, n.cutoff_utc = "set", new.cutoff_utc
        n.sources["cutoff"] = "interpretation (reply)"
        n.blocked.pop("cutoff", None)
    n.not_answered = sorted(set(n.not_answered) | set(new.not_answered))
    return n


# ------------------------------------------------------------------------------------------------ the request that runs
def executable(d: Draft, sel: Selection) -> Executable | None:
    """The complete request, validated, or None while anything is open. Only this ever reaches execution."""
    if issues(d, sel):
        return None
    b = bounds(d, sel)
    assert b is not None and d.region and d.date and d.operation and d.scope_kind
    lo, hi = b
    ev = event_for(sel, d.region, d.date) if d.scope_kind == "event" else None
    measure = d.measure if d.operation == "demand_maximum" else "operational demand"
    return Executable(
        question=d.question, operation=d.operation, measure=measure, region=d.region, date=d.date,
        scope_kind=d.scope_kind, start_utc=iso_utc(lo), end_utc=iso_utc(hi), start_local=local_str(lo, d.region),
        end_local=local_str(hi, d.region), half_hours=round((hi - lo) / timedelta(minutes=30)),
        event_id=ev.event_id if ev else None, run=d.run if d.operation in FORECAST_OPS else None,
        issued_at_utc=d.issued_at_utc if d.run == "issued_at" and d.operation in FORECAST_OPS else None,
        cutoff_utc=d.cutoff_utc if d.cutoff == "set" else None, not_answered=tuple(d.not_answered),
        intent="market_event_review" if d.operation == "demand_maximum" and d.scope_kind == "event" else
        "forecast_review", revision=d.revision)


def revision_id(x: Executable) -> str:
    """The identity of one exact request revision: confirmation applies to it alone."""
    return hashlib.sha256(json.dumps(x.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:12]


def preview_label(d: Draft) -> str:
    """What the preview is: the routing model's reading, or guided structured input (no model read the question)."""
    if d.origin == "interpretation":
        return INTERPRETATION_LABEL
    return MIXED_LABEL if any(s.startswith("interpretation") for s in d.sources.values()) else STRUCTURED_LABEL


def preview(d: Draft, sel: Selection) -> list[tuple[str, str]]:
    """The compact request preview: what the draft holds now, with each field's source; open fields say so."""
    def tag(f: str) -> str:
        s = d.sources.get(f)
        return f" ({s})" if s else ""
    b = bounds(d, sel) if d.region and d.date else None
    rows = [("Operation", (OPERATION_LABEL.get(d.operation or "", "not settled") + tag("operation"))),
            ("Measure / domain", (MEASURE_LABEL[d.measure] + tag("measure") if d.operation == "demand_maximum" and
                                  d.measure else "AEMO operational demand forecasts against actual operational demand"
                                  if d.operation in FORECAST_OPS else "not settled")),
            ("Region", (REGION_LABEL[d.region] + tag("region")) if d.region else "not settled"),
            ("Interval / window", (f"{SCOPE_LABEL[d.scope_kind]}: {local_str(b[0], str(d.region))} to "
                                   f"{local_str(b[1], str(d.region))} ({iso_utc(b[0])} to {iso_utc(b[1])})"
                                   + tag("scope_kind")) if b and d.scope_kind else
             (f"{SCOPE_LABEL[d.scope_kind]} on {d.date}" if d.scope_kind and d.date else
              f"date {d.date}, period not settled" if d.date else "not settled"))]
    if d.operation in FORECAST_OPS:
        run = RUN_LABEL.get(d.run or "", "not settled")
        if d.run == "latest_before_each" and d.cutoff == "set":
            run = "no single run: for each half-hour, the latest run provably public by the cutoff"
        if d.run == "issued_at":
            run += f" ({d.issued_at_utc or 'time not settled'})"
        rows.append(("Forecast run", run + tag("run")))
    cut = {"absent": "none", "set": f"as of {d.cutoff_utc}", "unresolved": "stated but not pinned down"}[d.cutoff]
    rows.append(("Cutoff", cut + tag("cutoff")))
    overrides = sorted(f for f, s in d.sources.items() if s == "request field")
    rows.append(("Request-field overrides", ", ".join(overrides) if overrides else "none"))
    yours = sorted(f for f, s in d.sources.items() if s == "you")
    rows.append(("Your corrections", ", ".join(yours) if yours else "none"))
    rows.append(("Not answered (other kinds of forecast)", ", ".join(d.not_answered) if d.not_answered else "none"))
    if d.reasons:
        rows.append(("Interpretation notes", " ".join(d.reasons)))
    open_ = issues(d, sel)
    rows.append(("Needs clarification", "; ".join(i.message for i in open_) if open_ else "nothing"))
    return rows


# ------------------------------------------------------------------------------------------------ to the resolver's form
def to_resolution(x: Executable, sel: Selection) -> Resolution:
    """The confirmed request as the resolver's ``Resolution``, built from its fields alone (no model call, no text
    reading), with the same request objects the D31 compiler produces; its status is decided by the resolver's own
    ``_finish``."""
    from .request import InvestigateRequest, _event_for, _finish
    from .structured import (
        DEMAND_FORECAST_TOOLS,
        CutoffRequest,
        ForecastAnalysis,
        MaxRequest,
        RequestResolution,
        RunRequest,
        Source,
        not_answered_note,
    )

    lo, hi = parse_iso(x.start_utc), parse_iso(x.end_utc)
    day = date.fromisoformat(x.date)
    src = Source("request", f"the confirmed request (revision {x.revision})", "confirmed by the user")
    rr = RequestResolution(routed="reported", contract="confirmed")
    as_of = parse_iso(x.cutoff_utc) if x.cutoff_utc else None
    if as_of is not None:
        rr.cutoff = CutoffRequest(status="bound", as_of=as_of, provenance={"as_of": src}, detected_by=["request"])
    event = next((e for e in sel.events if e.event_id == x.event_id), None) if x.event_id else _event_for(
        sel, x.region, day)
    if x.operation == "demand_maximum":
        event = None  # the maximum's window is the confirmed one; no event context is reviewed
    target: tuple[datetime, datetime] | None = None
    if x.operation == "demand_maximum":
        rr.maximum = MaxRequest(status="bound", measures=[x.measure], window_kind=x.scope_kind if x.scope_kind != "half_hour"
                                else "explicit", window=(lo, hi), provenance={"measure": src, "window": src},
                                detected_by=["request"])
        window = (lo, hi)
        if x.not_answered and x.intent == "market_event_review":
            rr.ineligible_tools = {t: "the forecast asked about is not a resolved operational-demand request (D29)"
                                   for t in DEMAND_FORECAST_TOOLS}
    else:
        single = x.operation == "single_interval_comparison"
        scope = {"half_hour": "half_hour", "day": "whole_local_day", "event": "event", "explicit": "explicit"}
        rr.forecast = ForecastAnalysis(
            status="bound", operation=x.operation, scope=scope[x.scope_kind], target=(lo, hi) if single else None,
            window=None if single else (lo, hi), domain="operational_demand", unsupported=list(x.not_answered),
            provenance={"operation": src, "scope": src, "domain": src}, detected_by=["request"])
        if x.run in ("last_issued_before", "issued_at"):
            rr.forecast_run = RunRequest(status="bound", selection=x.run, half_hour=(lo, hi) if single else None,
                                         issued_at=parse_iso(x.issued_at_utc) if x.issued_at_utc else None,
                                         provenance={"selection": src}, detected_by=["request"])
        if single:
            target = (lo, hi)
            if event and parse_iso(event.window_start_utc) <= lo and hi <= parse_iso(event.window_end_utc):
                window = (parse_iso(event.window_start_utc), parse_iso(event.window_end_utc))
            else:
                event, window = None, local_day_window(day, x.region)
        else:
            window = (lo, hi)
    if x.not_answered:
        rr.notes.append(not_answered_note(list(x.not_answered)))
    req = InvestigateRequest(question=x.question, mode="replay", region=x.region, event_date=day,
                             as_of_utc=x.cutoff_utc, intent=x.intent)
    kind = event.kind if event is not None else "high_price"
    return _finish(req, x.intent, x.region, event, window, as_of, kind, [], [x.region], [day],
                   {"router": "confirmed request (experimental)", "region_tz": REGION_TZ[x.region]}, target, rr)


# ------------------------------------------------------------------------------------------------ the confirmed analysis alone
WHAT_RAN = {"demand_maximum": "the demand maximum",
            "single_interval_comparison": "the forecast/actual comparison for the confirmed half-hour, under the "
                                          "confirmed run",
            "window_comparison": "the forecast accuracy over the confirmed period, under the confirmed run policy"}


RESULT_KIND = {"demand_maximum": "demand_maximum", "single_interval_comparison": "forecast_point",
               "window_comparison": "forecast_aggregate"}
CALL_OUTCOME = {"unavailable": "was unavailable", "error": "failed", "refused": "was refused", "blocked": "was blocked"}


def scope_note(x: Executable) -> str:
    """What ran: the confirmed analysis alone."""
    return (f"Only the analysis in the confirmed request ran: {WHAT_RAN[x.operation]}, computed by code from the "
            "pinned data. No other comparison, price review or document search was run, so none is reported.")


def requirement(x: Executable) -> Any:
    """What an "answered" status needs for this confirmed request (``validation.ConfirmedRequirement``), derived by code
    from the confirmed operation and measure alone, never from the model or the user: the operation's own tool (the
    measure's tool for a demand maximum, the forecast/actual comparison for a forecast point or aggregate) and the kind
    of the one result it computes. It is never empty."""
    from ..validation import ConfirmedRequirement
    from . import forecast_compare
    from .demand_max import MEASURES

    tool = MEASURES[x.measure][0] if x.operation == "demand_maximum" else forecast_compare.TOOL
    return ConfirmedRequirement(operation=x.operation, tools=(tool,), result_kind=RESULT_KIND[x.operation])


def confirmed_playbook(x: Executable) -> Any:
    """The dispatcher's playbook for a confirmed request: exactly the tool its computation calls (``requirement``),
    once, and nothing else (any other tool is blocked before it runs)."""
    from .playbook import PLAYBOOKS, Playbook

    return Playbook(PLAYBOOKS[x.intent].intent, required=requirement(x).tools, optional=(),
                    max_calls_per_required_tool=1)


def shortfall(x: Executable, records: list[Any], results: Any) -> list[str]:
    """Why a confirmed request's report is not "answered", in plain words, or [] when it is. "Answered" needs the
    operation's own tool run successfully and its one result, of the confirmed kind, verified in the run (admitted)
    and established: a tool executing is not enough. A partial, unavailable, not established or unverified result
    keeps its status. A point whose named run cannot be used (for example, not public by the confirmed cutoff) makes
    no comparison call, and none is forced to meet the rule: its report says so."""
    req = requirement(x)
    tool = req.tools[0]
    reported = results.reported()
    one = reported[0] if len(reported) == 1 and reported[0].result.identity.kind == req.result_kind else None
    out: list[str] = []
    calls = [r for r in records if r.name == tool]
    if not calls:
        why = f", because {one.result.reason}; no other run is substituted" if one and one.result.reason else ""
        out.append(f"{tool} did not run{why}")
    elif not any(r.status == "ok" for r in calls):
        out.append(f"{tool} " + " and ".join(sorted({CALL_OUTCOME.get(r.status, r.status) for r in calls})))
    if one is None:
        out.append(f"no single {req.result_kind.replace('_', ' ')} result was computed")
    else:
        if results.verified(one.result.result_id) is None:
            out.append(f"the result is not verified ({one.server_verification.outcome})")
        if one.result.status != "established":
            out.append(f"the result is {one.result.status.replace('_', ' ')}")
    return out


def status_note(reasons: list[str]) -> str:
    """Why a confirmed report is "answered with caveats" (``shortfall``)."""
    return "The status is \"answered with caveats\", not \"answered\": " + "; ".join(reasons) + "."


class ConfirmedOnly(ReplayController):
    """The confirmed request's computation and nothing else, with the existing calculations, runtime verification and
    renderer:

    - **a demand maximum:** the measure's maximum over the confirmed window (``demand_max.compute``);
    - **a forecast point:** the run the request names, chosen by issue time under the confirmed cutoff and recorded as
      the controller records it, compared with the actual for the confirmed half-hour (``forecast_compare``);
    - **a forecast aggregate:** the MAE and mean error over exactly the confirmed period, under the confirmed run policy
      and cutoff.

    No supplementary comparison, forecast-run listing, price review or document search runs, so none is reported. An
    unavailable result stays unavailable: nothing is computed in its place. The status is "answered" only when the
    operation's own tool ran successfully and its one result is verified and established (``shortfall``); otherwise
    it is "answered with caveats", and the report says why."""

    def __init__(self, dispatcher: Any, registry: Any, versions: Any, x: Executable) -> None:
        super().__init__(dispatcher, registry, versions)
        self.x = x

    def run(self, res: Resolution) -> Any:
        from . import forecast_compare
        from .demand_max import MEASURES

        x = self.x
        comp = Composer(self.reg, res.region)
        if x.operation == "demand_maximum":
            headline = (f"{res.region} {MEASURES[x.measure][5]}: the maximum over the confirmed window is given in "
                        "the computed answer.")
        else:
            point = forecast_compare.point_request(res)
            store = self.d.store
            if x.operation == "single_interval_comparison":
                assert point is not None and res.region is not None
                res.forecast_run = forecast_compare.forecast_run_record(store, res.region, point, res.as_of)
                ident = forecast_compare.point_identity(res, point, store.data_version)
                headline = (f"{res.region} operational demand: the forecast run the confirmed request names is "
                            "compared with the actual for the confirmed half-hour, in the computed answer.")
            else:
                assert forecast_compare.window_review(res)
                ident = forecast_compare.window_identity(res, store.data_version)
                headline = (f"{res.region} operational demand: the forecast accuracy over the confirmed period, under "
                            "the confirmed run policy, is given in the computed answer.")
            forecast_compare.submit(self.d, res, forecast_compare.compute(self.d, ident))
        self._render_maxima(res, comp)  # computes a requested maximum, and renders every reported result
        held = shortfall(x, self.d.records, self.d.results)
        uncertainties = [scope_note(x), *([status_note(held)] if held else [])]
        if res.as_of:
            uncertainties.append(self._standard_uncertainties(res)[-1])  # the as-of view
        return self._base(res, comp, headline, [], forecast_comparison=None, possible_explanations=[],
                          published_findings=[], uncertainties=uncertainties,
                          status="answered_with_caveats" if held else "answered")


# ------------------------------------------------------------------------------------------------ the conversation
@dataclass
class Interpretation:
    """One routing call's reading of a question, compiled by code, with what the trace needs."""
    resolution: Resolution
    decision: dict[str, Any] | None
    usage: dict[str, Any]
    trace_id: str
    model: str | None
    prompt: str
    contract: str = "v16"
    extra: dict[str, Any] = field(default_factory=dict)


Interpreter = Callable[[str], Interpretation]


def new_state() -> dict[str, Any]:
    """One session's conversation: the draft, the history, the original interpretation, the revision confirmed and
    the results by revision. Kept in the session only (``st.session_state``)."""
    return {"draft": None, "history": [], "original": None, "interpretations": [], "confirmed": None,
            "pending": None, "results": {}}


def _say(state: dict[str, Any], role: str, text: str) -> None:
    state["history"].append({"role": role, "text": text})


def draft_of(state: dict[str, Any]) -> Draft | None:
    """The session's current draft, or None."""
    return Draft.model_validate(state["draft"]) if state["draft"] is not None else None


def _set(state: dict[str, Any], d: Draft) -> None:
    state["draft"] = d.model_dump()
    state["confirmed"] = None  # any edit invalidates an earlier confirmation
    state["pending"] = None


def _record(i: Interpretation) -> dict[str, Any]:
    res = i.resolution
    return {"question": res.request.question, "status": res.status, "reasons": res.reasons, "intent": res.intent,
            "region": res.region, "requests": res.requests.as_dict() if res.requests is not None else None,
            "decision": i.decision, "usage": i.usage, "trace_id": i.trace_id, "model": i.model, "prompt": i.prompt,
            "contract": i.contract}


INVALID_OUTPUT = ("The routing model returned invalid or incomplete output, so nothing is read from it (nothing is "
                  "salvaged from a truncated response). Settle the request with the choices, or rephrase it.")


def _from_interpretation(i: Interpretation, question: str) -> Draft:
    """The draft of one interpretation. Without a valid routing decision nothing is read: not the routing model's
    output, and not the question parser's fallback reading either."""
    if i.decision is None:
        return Draft(question=question, blocked={"operation": INVALID_OUTPUT}, origin="structured")
    return from_resolution(i.resolution, question, i.decision, i.extra.get("given"))


def start(state: dict[str, Any], question: str, interpreter: Interpreter | None) -> None:
    """A new question. With an interpreter: one routing call, compiled into the draft. Without one (no model
    available): an empty draft, settled by structured choices alone. A failed call raises and leaves the session as it
    was."""
    i = interpreter(question) if interpreter is not None else None
    state.update(new_state())
    _say(state, "user", question)
    if i is None:
        d = Draft(question=question, origin="structured")
        _say(state, "assistant", "No routing model is available: this is guided structured input. Your question is "
                                 "kept for the record but not read; the request is built from your choices only.")
    else:
        state["original"] = _record(i)
        state["interpretations"].append(state["original"])
        d = _from_interpretation(i, question)
        _say(state, "assistant", d.refused or (INVALID_OUTPUT if i.decision is None else
                                               "Here is how the request was read."))
    _set(state, d)


def choose(state: dict[str, Any], revision: int, field_: str, value: Any, sel: Selection) -> bool:
    """A choice made on the question shown for ``revision``; a choice from an older revision is ignored."""
    d = draft_of(state)
    if d is None or d.revision != revision:
        return False
    _say(state, "user", _describe(field_, value))
    _set(state, apply(d, field_, value, sel))
    return True


def reply(state: dict[str, Any], text: str, sel: Selection, interpreter: Interpreter | None = None) -> bool:
    """A typed answer to the current question: read by the existing parsers; if they cannot read it and an
    interpreter is given, one routing call reads the question with the reply, and fills only open fields."""
    d = draft_of(state)
    if d is None:
        return False
    open_ = issues(d, sel)
    _say(state, "user", text)
    if not open_:
        _say(state, "assistant", "The request is complete; confirm it, or change a field.")
        return False
    f = open_[0].field
    value = parse_reply(f, text, d) if f != "refused" else None
    if value is not None:
        try:
            _set(state, apply(d, f, value, sel))
            return True
        except ValueError:
            pass
    if interpreter is not None:
        i = interpreter(f"{d.question}\n{text}")
        state["interpretations"].append(_record(i))
        if i.decision is None:
            _say(state, "assistant", INVALID_OUTPUT)
            return False
        _set(state, merge(d, from_resolution(i.resolution, d.question, i.decision, i.extra.get("given"))))
        _say(state, "assistant", "The routing model read your reply; only fields still open were filled.")
        return True
    _say(state, "assistant", "That answer could not be read. Please choose an option, or follow the example.")
    return False


def edit(state: dict[str, Any], new: Draft) -> None:
    """A draft changed through the optional form (each field already applied with ``apply``): a new revision."""
    old = draft_of(state)
    if old is None or new.revision <= old.revision:
        return
    changed = [f for f in ("operation", "measure", "region", "date", "scope_kind", "half_hour_end", "start_time",
                           "end_time", "run", "issued_at_utc", "cutoff", "cutoff_utc")
               if getattr(new, f) != getattr(old, f)]
    _say(state, "user", "Edited: " + (", ".join(changed) or "nothing"))
    _set(state, new)


def confirm(state: dict[str, Any], rid: str, sel: Selection) -> bool:
    """Confirm one exact revision: accepted only if it is the current, complete request."""
    d = draft_of(state)
    x = executable(d, sel) if d is not None else None
    if x is None or revision_id(x) != rid:
        return False
    state["confirmed"] = rid
    if rid not in state["results"]:
        state["pending"] = rid
    _say(state, "user", f"Confirmed request revision {rid}.")
    return True


def take_pending(state: dict[str, Any], sel: Selection) -> Executable | None:
    """The confirmed request to execute now, once: None if nothing is pending, the draft changed since, or it has run."""
    rid = state.get("pending")
    state["pending"] = None
    d = draft_of(state)
    x = executable(d, sel) if d is not None else None
    if rid is None or x is None or revision_id(x) != rid or rid in state["results"] or state["confirmed"] != rid:
        return None
    return x


def _describe(field_: str, value: Any) -> str:
    if field_ == "operation":
        return OPERATION_LABEL.get(value, str(value))
    if field_ == "measure":
        return MEASURE_LABEL.get(value, str(value))
    if field_ == "region":
        return REGION_LABEL.get(value, str(value))
    if field_ == "scope_kind":
        return SCOPE_LABEL.get(value, str(value))
    if field_ == "run":
        return RUN_LABEL.get(value, str(value))
    if field_ == "period":
        return f"{value[0]} to {value[1]}"
    if field_ == "cutoff" and value in (None, "absent"):
        return "No as-of cutoff"
    return str(value)
