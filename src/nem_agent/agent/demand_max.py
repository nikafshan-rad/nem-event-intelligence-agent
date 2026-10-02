"""A demand measure's maximum over the window a question asks about, computed by code (I-17).

Held-out v6 Z04 asked "when did TAS1 total demand peak and at what level?" for one local day. The answer gave dispatch
TOTALDEMAND at the price peak and the maximum of operational demand, a different measure: TOTALDEMAND's own maximum
was in the retrieved series but no tool view or controller note gave it. Here the controller fetches the measure for
the requested window itself, takes its maximum (every tied interval kept), says whether the window is fully covered,
and records the result on the resolution, so the validator can hold the answer to it. Dispatch total demand
(TOTALDEMAND, 5-minute) and operational demand (half-hour) are never mixed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from ..timeutil import iso_utc, local_day_window, local_str, parse_iso
from .dispatcher import Dispatcher
from .request import Resolution, maximum_window_kind

# measure -> (tool, value field, evidence-ID field, registered metric, interval minutes, name in an answer)
MEASURES: dict[str, tuple[str, str, str, str, int, str]] = {
    "total demand": ("get_price_timeline", "totaldemand_mw", "totaldemand_evidence_id", "dispatch_totaldemand", 5,
                     "dispatch total demand (TOTALDEMAND)"),
    "operational demand": ("get_actual_demand", "operational_demand_mw", "evidence_id", "opdemand_actual", 30,
                           "operational demand"),
}
_LENGTH = {5: "5-minute interval", 30: "half-hour"}
_MEASURE_WORDS = {"total demand": r"(?:dispatch\s+)?(?:total[- ]?demand|TOTALDEMAND)(?:\s*\(TOTALDEMAND\))?",
                  "operational demand": r"(?:actual\s+)?operational[- ]demand"}
_MAX_WORD = r"(?:peak|highest|maximum|max|top)"
_QUALIFIER = r"(?:(?:5-minute|five-minute|half-hour(?:ly)?|30-minute|daily|day's|window|dispatch|actual)\s+)*"


def max_claim_re(measure: str) -> re.Pattern[str]:
    """A sentence stating the measure's maximum: "total demand peaked", "TOTALDEMAND was highest", "the peak total
    demand", "operational demand maximum". Not a value at the (price) peak: "total demand at the peak"."""
    m = _MEASURE_WORDS[measure]
    return re.compile(
        rf"\b{m}(?:(?!\bprices?\b|\bRRP\b)[^.;:,]){{0,25}}?\b(?:peaked|peaks|was (?:at its )?(?:highest|peak)|"
        rf"reached (?:its|a|the) (?:peak|maximum|high(?:est)?)|topped out|maxed out)\b"
        rf"|\b{_MAX_WORD}\s+{_QUALIFIER}{m}|\b{m}\s+(?:peak|maximum|max)\b(?!\s+(?:price|interval))", re.I)


def requested_window(res: Resolution) -> tuple[str, tuple[datetime, datetime] | None]:
    """The window a maximum is asked over, and how it is given (``request.maximum_window_kind``): exactly the request's
    explicit window; the event's window, from the event the resolution holds; or the whole local day of the question's
    one date in the region's time. Never the whole day in place of a window the question narrows or does not give
    (I-17 review): None then, and ``resolve`` has sent the question back."""
    req = res.request
    kind = maximum_window_kind(req.question, req)
    if kind == "explicit" and req.window_start_utc and req.window_end_utc:
        return kind, (parse_iso(req.window_start_utc), parse_iso(req.window_end_utc))
    if kind == "event" and res.event is not None:
        return kind, (parse_iso(res.event.window_start_utc), parse_iso(res.event.window_end_utc))
    days = res.routing.get("dates_found")
    if kind == "day" and isinstance(days, list) and len(days) == 1 and res.region:
        return kind, local_day_window(date.fromisoformat(str(days[0])), res.region)
    return kind, None


def compute(d: Dispatcher, res: Resolution, measure: str) -> dict[str, Any]:
    """The measure's maximum over the requested window, from the controller's own tool call (under the request's as-of
    cutoff). The binding: the window, the maximum's value and evidence IDs (each tied interval), whether every
    interval of the window is held, or why none can be given."""
    tool, field, eid_field, metric, minutes, _ = MEASURES[measure]
    kind, window = requested_window(res)
    out: dict[str, Any] = {"measure": measure, "metric": metric, "interval_minutes": minutes, "window_kind": kind,
                           "window_utc": [iso_utc(window[0]), iso_utc(window[1])] if window else None}
    if window is None or res.region is None:
        return out | {"unavailable": "the window is not pinned down"}
    w0, w1 = window
    rec = d.call(tool, {"region": res.region, "start_utc": iso_utc(w0), "end_utc": iso_utc(w1),
                        "as_of_utc": iso_utc(res.as_of) if res.as_of else None},
                 call_id=f"controller_requested_max_{metric}", origin="controller")
    out["call_id"] = rec.call_id
    if rec.status != "ok":
        return out | {"unavailable": f"the controller's {tool} call returned {rec.status}"
                                     + (f" ({rec.blocked_reason})" if rec.blocked_reason else "")}
    series = [x for x in (rec.data or {}).get("series", []) if x.get(field) is not None and x.get(eid_field)
              and w0 < parse_iso(x["interval_end_utc"]) <= w1]
    if not series:
        return out | {"unavailable": "no value of the measure is held for the window"}
    top = max(float(x[field]) for x in series)
    tied = [x for x in series if float(x[field]) == top]
    expected = round((w1 - w0) / timedelta(minutes=minutes))
    return out | {"value": top, "evidence_ids": [x[eid_field] for x in tied],
                  "interval_ends_utc": [x["interval_end_utc"] for x in tied], "intervals_held": len(series),
                  "intervals_in_window": expected, "complete": len(series) >= expected,
                  "excluded_by_as_of": int((rec.view or {}).get("excluded_not_yet_available_at_as_of") or 0)}


def sentence(b: dict[str, Any], region: str, num: Callable[[str], str], as_of: datetime | None) -> str:
    """The controller's statement of a binding. ``num(evidence_id)`` formats a value (and records its claim)."""
    _, _, _, _, minutes, name = MEASURES[b["measure"]]
    length = _LENGTH[minutes]
    subject = f"{region} {name}"
    if b.get("window_utc"):
        w0 = parse_iso(b["window_utc"][0])
        zone = local_str(w0, region).split(" ")[2]
        span = {"day": f"all of {local_str(w0, region)[:10]} ({zone})",
                "event": f"the event window, {b['window_utc'][0]} to {b['window_utc'][1]}"}.get(
                    str(b.get("window_kind")), f"the requested window, {b['window_utc'][0]} to {b['window_utc'][1]}")
    else:
        span = "the requested window"
    if "unavailable" in b:
        return f"The maximum of {subject} over {span} cannot be given: {b['unavailable']}."

    def at(t: str) -> str:
        return f"{t} = {re.sub(r' [(]UTC[^)]*[)]', '', local_str(parse_iso(t), region))}"
    ends = b["interval_ends_utc"]
    value = num(b["evidence_ids"][0])
    for e in b["evidence_ids"][1:]:
        num(e)  # each tied interval is claimed, so each stated time has its evidence
    if not b["complete"]:
        held = "held and public by the as-of cutoff" if as_of is not None else "held"
        where = f"the {length} ending {at(ends[0])}" if len(ends) == 1 else \
            f"the {length}s ending {', '.join(at(t) for t in ends[:-1])} and {at(ends[-1])}"
        return (f"Not every {length} of {span} is {held}, so the maximum of {subject} over it cannot be established; "
                f"the highest value {held} is {value}, in {where}.")
    if len(ends) == 1:
        return f"{subject[0].upper()}{subject[1:]} was highest at {value} in the {length} ending {at(ends[0])}, over {span}."
    return (f"{subject[0].upper()}{subject[1:]} was highest at {value} in more than one {length}, those ending "
            f"{', '.join(at(t) for t in ends[:-1])} and {at(ends[-1])}, over {span}.")
