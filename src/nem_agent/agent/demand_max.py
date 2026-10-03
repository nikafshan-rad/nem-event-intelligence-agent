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
from typing import TYPE_CHECKING, Any

from ..results import (
    AnalyticalResult,
    Coverage,
    Limitation,
    ResultIdentity,
    Transient,
    make_result,
    request_digest,
)
from ..timeutil import iso_utc, local_day_window, local_str, parse_iso
from .dispatcher import Dispatcher
from .request import Resolution, maximum_window_kind, requested_maxima

if TYPE_CHECKING:
    from ..evidence import EvidenceRegistry
    from ..selection import Selection
    from ..store import Store

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


def requested_measures(res: Resolution) -> list[str]:
    """The measures whose maximum is asked for and bound (I-18: from the request, the question parser or the routing
    model's grounded reading). A resolution built elsewhere (tests) falls back to the question parser."""
    if res.requests is not None:
        mx = res.requests.maximum
        return [m for m in mx.measures if m in MEASURES] if mx.status == "bound" else []
    return [m for m in requested_maxima(res.request.question) if m in MEASURES]


def requested_window(res: Resolution) -> tuple[str, tuple[datetime, datetime] | None]:
    """The window a maximum is asked over, and how it is given (``request.maximum_window_kind``): exactly the request's
    explicit window; the event's window, from the event the resolution holds; or the whole local day of the question's
    one date in the region's time. Never the whole day in place of a window the question narrows or does not give
    (I-17 review): None then, and ``resolve`` has sent the question back. A bound request's window (I-18) is used as
    resolved."""
    if res.requests is not None and res.requests.maximum.status == "bound" and res.requests.maximum.window:
        return str(res.requests.maximum.window_kind), res.requests.maximum.window
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


# -- the typed result (D24) and today's binding, derived from it --------------------------------------------------------
CALCULATION_VERSION = "demand_max/1"  # change it whenever the calculation below changes
_RUNTIME_ONLY = ("blocked", "error")  # call statuses the dispatcher sets at run time; a tool alone never returns them
_DEFINITION = {"total demand": ("MEASURE_DEFINITION", "Dispatch total demand (TOTALDEMAND) is a 5-minute dispatch "
                                "quantity, not operational demand."),
               "operational demand": ("MEASURE_DEFINITION", "Operational demand is the half-hour measure, not dispatch "
                                      "total demand (TOTALDEMAND).")}


def result_identity(res: Resolution, measure: str, data_version: str) -> ResultIdentity:
    """Everything the result is a function of: the request, measure, region, window, cutoff, calculation and data."""
    kind, window = requested_window(res)
    return ResultIdentity(
        request_digest=request_digest(res.request), kind="demand_maximum", measure=measure, region=res.region,
        window_utc=(iso_utc(window[0]), iso_utc(window[1])) if window else None, window_kind=kind,
        cutoff_utc=iso_utc(res.as_of) if res.as_of else None, calculation_version=CALCULATION_VERSION,
        data_version=data_version)


def _limitations(identity: ResultIdentity, status: str, excluded: int) -> tuple[Limitation, ...]:
    """Deterministic limitations of a result: what it was computed from, and what it cannot say."""
    out = [Limitation(code="PINNED_DATA", text=f"Computed from the values held in the pinned data snapshot "
                                                f"{identity.data_version} for the requested window; it is only as "
                                                "complete and accurate as that data.")]
    out.append(Limitation(code=_DEFINITION[identity.measure][0], text=_DEFINITION[identity.measure][1]))
    if identity.cutoff_utc is not None:
        out.append(Limitation(code="AS_OF_CUTOFF", text=f"Only intervals provably public by {identity.cutoff_utc} are "
                                                        f"used; {excluded} interval(s) of the window were excluded by it."))
    if status == "not_established":
        out.append(Limitation(code="INCOMPLETE_WINDOW", text="Not every interval of the window is held, so no maximum "
                                                             "is established; the highest value held is not a maximum."))
    return tuple(out)


def _unavailable(identity: ResultIdentity, reason: str, call_id: str | None) -> AnalyticalResult:
    metric = MEASURES[identity.measure][3]
    return make_result(identity, status="unavailable", reason=reason, metric=metric,
                       limitations=_limitations(identity, "unavailable", 0),
                       transient=Transient(evidence_ids=(), tool_call_id=call_id))


def result_from_output(identity: ResultIdentity, status: str, data: dict[str, Any] | None, view: dict[str, Any] | None,
                       registry: EvidenceRegistry, call_id: str | None,
                       blocked_reason: str | None = None) -> AnalyticalResult:
    """The result of one call of the measure's tool over the identity's window: its maximum (every tied interval kept)
    when every interval is held, else the highest value held apart, else why there is no value."""
    tool, field, eid_field, metric, minutes, _ = MEASURES[identity.measure]
    if status != "ok":
        return _unavailable(identity, f"the controller's {tool} call returned {status}"
                            + (f" ({blocked_reason})" if blocked_reason else ""), call_id)
    assert identity.window_utc is not None
    w0, w1 = parse_iso(identity.window_utc[0]), parse_iso(identity.window_utc[1])
    series = [x for x in (data or {}).get("series", []) if x.get(field) is not None and x.get(eid_field)
              and w0 < parse_iso(x["interval_end_utc"]) <= w1]
    if not series:
        return _unavailable(identity, "no value of the measure is held for the window", call_id)
    top = max(float(x[field]) for x in series)
    tied = [x for x in series if float(x[field]) == top]
    expected = round((w1 - w0) / timedelta(minutes=minutes))
    excluded = int((view or {}).get("excluded_not_yet_available_at_as_of") or 0)
    complete = len(series) >= expected
    eids = tuple(x[eid_field] for x in tied)
    ends = tuple(x["interval_end_utc"] for x in tied)
    evs = [registry.get(e) for e in eids]
    rows = tuple(r for ev in evs if ev is not None for r in ev.source_row_ids)
    status_ = "established" if complete else "not_established"
    return make_result(
        identity, status=status_, reason=None if complete else "not every interval of the window is held",
        metric=metric, unit=next((ev.unit for ev in evs if ev is not None), None),
        **({"maximum": top, "interval_ends_utc": ends} if complete else
           {"highest_held": top, "highest_held_interval_ends_utc": ends}),
        coverage=Coverage(interval_minutes=minutes, intervals_in_window=expected, intervals_held=len(series),
                          complete=complete, excluded_by_as_of=excluded),
        source_row_ids=rows, limitations=_limitations(identity, status_, excluded),
        transient=Transient(evidence_ids=eids, tool_call_id=call_id))


def compute_result(d: Dispatcher, res: Resolution, measure: str) -> AnalyticalResult:
    """The measure's maximum over the requested window, from the controller's own tool call (under the request's as-of
    cutoff), as a typed result."""
    tool, _, _, metric, _, _ = MEASURES[measure]
    identity = result_identity(res, measure, d.store.data_version)
    if identity.window_utc is None or res.region is None:
        return _unavailable(identity, "the window is not pinned down", None)
    rec = d.call(tool, {"region": res.region, "start_utc": identity.window_utc[0], "end_utc": identity.window_utc[1],
                        "as_of_utc": identity.cutoff_utc},
                 call_id=f"controller_requested_max_{metric}", origin="controller")
    return result_from_output(identity, rec.status, rec.data, rec.view, d.registry, rec.call_id, rec.blocked_reason)


def rederive(identity: ResultIdentity, store: Store, selection: Selection) -> AnalyticalResult:
    """The same result computed again from the pinned store, with the same tool code, outside any investigation (its
    in-run references are this computation's own). Used by the verifier (``results``)."""
    from ..evidence import EvidenceRegistry as _Registry
    from ..tools import CONTROLLER_TOOLS, TOOLS
    from ..tools.impl import ToolContext

    tool = MEASURES[identity.measure][0]
    if identity.window_utc is None or identity.region is None:
        return _unavailable(identity, "the window is not pinned down", None)
    spec = TOOLS.get(tool) or CONTROLLER_TOOLS[tool]
    reg = _Registry()
    cutoff = parse_iso(identity.cutoff_utc) if identity.cutoff_utc else None
    args = spec.args_model.model_validate({"region": identity.region, "start_utc": identity.window_utc[0],
                                           "end_utc": identity.window_utc[1], "as_of_utc": identity.cutoff_utc})
    out = spec.handler(ToolContext(store=store, selection=selection, registry=reg, call_id="rederive",
                                   request_as_of=cutoff), args)
    return result_from_output(identity, out.status, out.data, out.view, reg, "rederive")


def not_rederivable(r: AnalyticalResult) -> str | None:
    """Why a result cannot be re-derived from the store at all: an unavailable result caused by a run-time call status
    (a policy block, a tool error) that a tool alone never returns."""
    if r.status == "unavailable" and any(re.search(rf"call returned {s}\b", r.reason or "") for s in _RUNTIME_ONLY):
        return "a run-time call status (a policy block or a tool error) cannot be re-derived from the store"
    return None


def binding_from_result(r: AnalyticalResult) -> dict[str, Any]:
    """Today's binding dict (I-17), exactly as the validator, the controller's sentence and the fallback read it: the
    compatibility adapter. An incomplete window's highest value held is the binding's ``value``, with ``complete``
    false, as before."""
    _, _, _, metric, minutes, _ = MEASURES[r.identity.measure]
    out: dict[str, Any] = {"measure": r.identity.measure, "metric": metric, "interval_minutes": minutes,
                           "window_kind": r.identity.window_kind,
                           "window_utc": list(r.identity.window_utc) if r.identity.window_utc else None}
    if r.transient.tool_call_id is None:
        return out | {"unavailable": r.reason}
    out["call_id"] = r.transient.tool_call_id
    if r.status == "unavailable":
        return out | {"unavailable": r.reason}
    assert r.coverage is not None
    established = r.status == "established"
    return out | {"value": r.maximum if established else r.highest_held,
                  "evidence_ids": list(r.transient.evidence_ids),
                  "interval_ends_utc": list(r.interval_ends_utc if established else r.highest_held_interval_ends_utc),
                  "intervals_held": r.coverage.intervals_held, "intervals_in_window": r.coverage.intervals_in_window,
                  "complete": r.coverage.complete, "excluded_by_as_of": r.coverage.excluded_by_as_of}


NOT_VERIFIED = "the computed result could not be verified against the pinned data ({})"


def binding_not_verified(r: AnalyticalResult, outcome: str) -> dict[str, Any]:
    """The binding for a result the verifier did not admit (D25): the unavailable form, with no value, so neither the
    validator nor the model's context reads a value the verifier did not admit."""
    _, _, _, metric, minutes, _ = MEASURES[r.identity.measure]
    out: dict[str, Any] = {"measure": r.identity.measure, "metric": metric, "interval_minutes": minutes,
                           "window_kind": r.identity.window_kind,
                           "window_utc": list(r.identity.window_utc) if r.identity.window_utc else None}
    if r.transient.tool_call_id is not None:
        out["call_id"] = r.transient.tool_call_id
    return out | {"unavailable": NOT_VERIFIED.format(outcome)}


def compute(d: Dispatcher, res: Resolution, measure: str) -> dict[str, Any]:
    """The measure's maximum over the requested window: the typed result, submitted to the investigation's
    verified-result registry (``Dispatcher.results``, D24), and returned as the binding the validator and the model's
    context read: today's (``binding_from_result``) for an admitted result, else the unavailable form (D25)."""
    r = compute_result(d, res, measure)
    v = d.results.submit_in_run(r, store=d.store, selection=d.selection, evidence=d.registry, trace=d.trace)
    if v.outcome == "verified":
        return binding_from_result(r)
    res.results_not_admitted = [*(res.results_not_admitted or []), r]
    return binding_not_verified(r, v.outcome)


# -- the controller's statement: one wording, from a result (D25) or from a binding (the validator's tests) ------------
def _text(measure: str, region: str, window_utc: Any, window_kind: str | None, cutoff: bool, *,
          unavailable: str | None = None, value: str | None = None, ends: Any = (), complete: bool = True) -> str:
    _, _, _, _, minutes, name = MEASURES[measure]
    length = _LENGTH[minutes]
    subject = f"{region} {name}"
    if window_utc:
        w0 = parse_iso(window_utc[0])
        zone = local_str(w0, region).split(" ")[2]
        span = {"day": f"all of {local_str(w0, region)[:10]} ({zone})",
                "event": f"the event window, {window_utc[0]} to {window_utc[1]}"}.get(
                    str(window_kind), f"the requested window, {window_utc[0]} to {window_utc[1]}")
    else:
        span = "the requested window"
    if unavailable is not None:
        return f"The maximum of {subject} over {span} cannot be given: {unavailable}."

    def at(t: str) -> str:
        return f"{t} = {re.sub(r' [(]UTC[^)]*[)]', '', local_str(parse_iso(t), region))}"
    ends = list(ends)
    if not complete:
        held = "held and public by the as-of cutoff" if cutoff else "held"
        where = f"the {length} ending {at(ends[0])}" if len(ends) == 1 else \
            f"the {length}s ending {', '.join(at(t) for t in ends[:-1])} and {at(ends[-1])}"
        return (f"Not every {length} of {span} is {held}, so the maximum of {subject} over it cannot be established; "
                f"the highest value {held} is {value}, in {where}.")
    if len(ends) == 1:
        return f"{subject[0].upper()}{subject[1:]} was highest at {value} in the {length} ending {at(ends[0])}, over {span}."
    return (f"{subject[0].upper()}{subject[1:]} was highest at {value} in more than one {length}, those ending "
            f"{', '.join(at(t) for t in ends[:-1])} and {at(ends[-1])}, over {span}.")


def statement(r: AnalyticalResult, region: str, num: Callable[[str], str]) -> str:
    """The controller's statement of an admitted result (``render.render_result``). ``num(evidence_id)`` formats a
    value and records its claim: each tied interval is claimed, so each stated time has its evidence."""
    i = r.identity
    if r.status == "unavailable":
        return _text(i.measure, region, i.window_utc, i.window_kind, i.cutoff_utc is not None, unavailable=r.reason)
    value = num(r.transient.evidence_ids[0])
    for e in r.transient.evidence_ids[1:]:
        num(e)
    established = r.status == "established"
    return _text(i.measure, region, i.window_utc, i.window_kind, i.cutoff_utc is not None, value=value,
                 ends=r.interval_ends_utc if established else r.highest_held_interval_ends_utc, complete=established)


def statement_not_verified(identity: ResultIdentity, region: str, outcome: str) -> str:
    """The statement for a result the verifier did not admit: no value, only why it is not given."""
    return _text(identity.measure, region, identity.window_utc, identity.window_kind, identity.cutoff_utc is not None,
                 unavailable=NOT_VERIFIED.format(outcome))


def sentence(b: dict[str, Any], region: str, num: Callable[[str], str], as_of: datetime | None) -> str:
    """The controller's statement of a binding, in the same words as ``statement`` (kept for the validator's tests).
    ``num(evidence_id)`` formats a value (and records its claim)."""
    if "unavailable" in b:
        return _text(b["measure"], region, b.get("window_utc"), b.get("window_kind"), as_of is not None,
                     unavailable=b["unavailable"])
    value = num(b["evidence_ids"][0])
    for e in b["evidence_ids"][1:]:
        num(e)  # each tied interval is claimed, so each stated time has its evidence
    return _text(b["measure"], region, b.get("window_utc"), b.get("window_kind"), as_of is not None, value=value,
                 ends=b["interval_ends_utc"], complete=b["complete"])
