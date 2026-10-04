"""Typed forecast-comparison results (D27): the comparison a question asks for is the computed answer.

The end-to-end Live check of v13 failed on R02: its answer said "The run/actual pair for the review yields a mean
absolute error (MAE) of 149.81 MW", an aggregate over 21 half-hour pairs of a 12-hour window, while the pair asked
about had an error of 27 MW. Replay showed the same promotion by code: for a question naming one run (K14) it
headlined a 24-half-hour MAE under another run policy. Here the resolved request decides the comparison, and code
computes, verifies and states it:

- **Point** (``forecast_point``): one half-hour a bound forecast-run request names, its run chosen by issue time (the
  last run issued before the half-hour starts, or the run issued at a named time), compared with the actual.
- **Aggregate** (``forecast_aggregate``): a forecast review with no point request; MAE and mean error over today's
  12-hour focus window under the project's default policy, over an explicitly listed set of pairs.

Each result carries its run selection, target or window, every pair (its own run, times and rows), every half-hour
without a pair (with its reason), the revision policy, the cutoff and its source rows. Nothing stands in for an
unavailable comparison: no other run, half-hour or window is computed or stated in its place.

The error convention is fixed: error = POE50 - actual, so a positive error means the forecast was above the actual.

``scope_of`` gives the validator what the primary result owns, so a value from any other comparison is not stated in
the interpretation (``FORECAST_SCOPE_NOT_PRIMARY``). That is a provenance restriction, not a semantic check: the
existing checks still read every sentence, and citing the primary does not make a sentence true.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from ..results import (
    ExcludedTarget,
    ForecastIdentity,
    ForecastPair,
    ForecastResult,
    Limitation,
    Transient,
    make_forecast_result,
    request_digest,
)
from ..timeutil import iso_utc, local_str, parse_iso
from .request import ForecastRequest, Resolution, requested_forecast

if TYPE_CHECKING:
    from ..evidence import EvidenceRegistry
    from ..selection import Selection
    from ..store import Store
    from .dispatcher import Dispatcher

CALCULATION_VERSION = "forecast_compare/1"  # change it whenever the calculation below changes
TOOL = "compare_forecast_actual"
_RUNTIME_ONLY = ("blocked", "error")  # call statuses the dispatcher sets at run time; a tool alone never returns them
POINT_CALL_ID = "controller_requested_run"
WINDOW_CALL_ID = "controller_requested_comparison"
# evidence a comparison registers, by the scope it belongs to
PAIR_METRICS = frozenset({"opdemand_forecast_poe50", "opdemand_forecast_poe10", "opdemand_forecast_poe90",
                          "opdemand_actual", "forecast_error_mw", "forecast_error_pct"})
AGGREGATE_METRICS = frozenset({"mae_mw", "mean_error_mw", "n_aligned_half_hours"})
TIED_RUNS = ("Two forecast runs fit the run the question asks for equally (the same issue time, or equally near the "
             "time named), so it cannot be told which one is meant")
POLICY_TEXT = {
    "last_issued_before": "the last run issued before the half-hour began (chosen by issue time, not availability)",
    "issued_at": "the run issued at the time the question names (within ten minutes)",
    # stated with the result: no completeness wording ("for each half-hour"), which the coverage check (I-20) reads
    # as a claim that every half-hour of the window is paired
    "run_id": "one named run (no other run is used)",
    "latest_before_target": "the latest run available before each half-hour began (so the run can differ between "
                            "half-hours)",
    "min_lead_hours": "the latest run available at least the stated lead time before each half-hour began",
    "latest_available_as_of": "the latest run holding each half-hour that was provably public by the as-of cutoff",
}
_REASON_TEXT = {
    "run_not_held": "no forecast run the question asks for holds this half-hour",
    "tied_runs": TIED_RUNS[0].lower() + TIED_RUNS[1:],
    "run_not_public_by_cutoff": "the run the question asks for is not provably public by the as-of cutoff",
    "no_forecast_for_selection": "no forecast run under the selection holds the half-hour",
    "no_actual": "no actual is held for the half-hour",
    "not_public_by_cutoff": "the forecast or the actual is not provably public by the as-of cutoff",
    "no_data_held": "no forecast row and no actual row is held for the half-hour",
}


# -- what the request asks for ---------------------------------------------------------------------------------------
def point_request(res: Resolution) -> ForecastRequest | None:
    """The one half-hour a forecast-run request names, decided from the resolved request alone (never from whether a
    run lookup succeeded): a bound run with its half-hour pinned down."""
    if res.requests is not None:
        wanted = res.requests.forecast_run.forecast_request()
    else:  # a resolution built elsewhere (tests), read as the controller reads it
        wanted = requested_forecast(res.request.question)
    return wanted if wanted is not None and wanted.half_hour is not None else None


def window_review(res: Resolution) -> bool:
    """A forecast review asking about a window: no point request, and no demand maximum asked for (a maximum is then
    the requested result, D24, and is unchanged). Its primary is an aggregate over the focus window."""
    from . import demand_max

    return res.intent == "forecast_review" and point_request(res) is None and res.window is not None \
        and res.region is not None and not demand_max.requested_measures(res)


# -- the run a request names, by issue time (shared by Live, Replay and the verifier) ---------------------------------
def select_run(store: Store, region: str, wanted: ForecastRequest, as_of: datetime | None) -> dict[str, Any]:
    """The run a request names, chosen by issue time, never by availability: the run issued nearest a named time
    (within 10 minutes), or the last run issued before the half-hour starts that forecasts it. Two runs equally fit are
    a tie (none is chosen); under a cutoff, a run not public by then is not chosen. Returns ``best`` (or None), ``tied``,
    ``not_public`` and ``rows_found``, as the existing lookups read them."""
    if wanted.run == "issued_at":
        assert wanted.issued_at is not None
        issued = wanted.issued_at
        rows = store.query(
            "SELECT run_id, MIN(issued_at_utc) AS issued_at_utc, MIN(published_at_utc) AS published_at_utc, "
            "MAX(available_at_utc) AS available_at_utc FROM opdemand_forecast WHERE region=? AND issued_at_utc BETWEEN "
            "? AND ? GROUP BY run_id", [region, issued - timedelta(minutes=10), issued + timedelta(minutes=10)])
        best = min(rows, key=lambda r: abs(r["issued_at_utc"] - issued)) if rows else None
        tied = best is not None and sum(abs(r["issued_at_utc"] - issued) == abs(best["issued_at_utc"] - issued)
                                        for r in rows) > 1
    else:
        hh = wanted.half_hour
        assert hh is not None
        rows = store.query(
            "SELECT run_id, MIN(issued_at_utc) AS issued_at_utc, MIN(published_at_utc) AS published_at_utc, "
            "MAX(available_at_utc) AS available_at_utc FROM opdemand_forecast WHERE region=? AND target_end_utc=? "
            "AND issued_at_utc < ? GROUP BY run_id ORDER BY issued_at_utc DESC LIMIT 2", [region, hh[1], hh[0]])
        best = rows[0] if rows else None
        tied = len(rows) > 1 and rows[1]["issued_at_utc"] == rows[0]["issued_at_utc"]
    if tied:
        best = None
    not_public = best is not None and as_of is not None and best["available_at_utc"] > as_of
    if not_public:
        best = None
    return {"best": best, "tied": tied, "not_public": not_public, "rows_found": bool(rows)}


def run_holds(store: Store, region: str, run_id: str, target_end: datetime) -> bool:
    return bool(store.query("SELECT 1 FROM opdemand_forecast WHERE region=? AND run_id=? AND target_end_utc=? LIMIT 1",
                            [region, run_id, target_end]))


def _lookup(store: Store, region: str, wanted: ForecastRequest, as_of: datetime | None,
            target_end: datetime | None) -> tuple[dict[str, Any] | None, str | None]:
    """(the chosen run, or None; the reason code when there is none)."""
    sel = select_run(store, region, wanted, as_of)
    best = sel["best"]
    if best is None:
        return None, "tied_runs" if sel["tied"] else "run_not_public_by_cutoff" if sel["not_public"] else \
            "run_not_held"
    if target_end is not None and not run_holds(store, region, best["run_id"], target_end):
        return None, "run_not_held"
    return best, None


# -- identity --------------------------------------------------------------------------------------------------------
def _ts(t: Any) -> str:
    return iso_utc(t) if isinstance(t, datetime) else str(t)


def point_identity(res: Resolution, wanted: ForecastRequest, data_version: str) -> ForecastIdentity:
    assert wanted.half_hour is not None and res.region is not None
    return ForecastIdentity(
        request_digest=request_digest(res.request), kind="forecast_point", measure="operational demand",
        region=res.region,
        target_utc=(iso_utc(wanted.half_hour[0]), iso_utc(wanted.half_hour[1])), window_utc=None,
        run_selection=wanted.run, named_issued_at_utc=iso_utc(wanted.issued_at) if wanted.issued_at else None,
        actual_revision_policy="latest_available", cutoff_utc=iso_utc(res.as_of) if res.as_of else None,
        calculation_version=CALCULATION_VERSION, data_version=data_version)


def window_identity(res: Resolution, data_version: str) -> ForecastIdentity:
    """The aggregate a forecast review asks for: today's focus window, under the project's default policy: the run a
    request names by its issue time; else, under a cutoff, the latest run provably public by it; else, for each
    half-hour, the latest run available before it."""
    from .replay import forecast_focus

    assert res.region is not None
    lo, hi = forecast_focus(res)
    named = res.requests.forecast_run.forecast_request() if res.requests is not None else \
        requested_forecast(res.request.question)
    named_at = named.issued_at if named is not None and named.run == "issued_at" else None
    policy: Literal["run_id", "latest_available_as_of", "latest_before_target"] = \
        "run_id" if named_at else "latest_available_as_of" if res.as_of else "latest_before_target"
    return ForecastIdentity(
        request_digest=request_digest(res.request), kind="forecast_aggregate", measure="operational demand",
        region=res.region, target_utc=None, window_utc=(iso_utc(lo), iso_utc(hi)), run_selection=policy,
        named_issued_at_utc=iso_utc(named_at) if named_at else None, actual_revision_policy="latest_available",
        cutoff_utc=iso_utc(res.as_of) if res.as_of else None, calculation_version=CALCULATION_VERSION,
        data_version=data_version)


def _span(identity: ForecastIdentity) -> tuple[datetime, datetime]:
    w = identity.target_utc if identity.kind == "forecast_point" else identity.window_utc
    assert w is not None
    return parse_iso(w[0]), parse_iso(w[1])


def _ends(identity: ForecastIdentity) -> list[str]:
    w0, w1 = _span(identity)
    n = round((w1 - w0) / timedelta(minutes=30))
    return [iso_utc(w0 + timedelta(minutes=30 * (i + 1))) for i in range(n)]


# -- the result from one comparison ------------------------------------------------------------------------------------
def _limitations(identity: ForecastIdentity, status: str, pairs: list[ForecastPair],
                 excluded: list[ExcludedTarget]) -> tuple[Limitation, ...]:
    out = [Limitation(code="PINNED_DATA", text=f"Computed from the values held in the pinned data snapshot "
                                                f"{identity.data_version}; it is only as complete and accurate as that "
                                                "data."),
           Limitation(code="ERROR_CONVENTION", text="The error is the POE50 forecast minus the actual: positive means "
                                                    "the forecast was above the actual."),
           Limitation(code="POE_BAND", text="POE10 and POE90 are AEMO-published values derived from POE50 by scaling "
                                            "factors: band context only, not compared and not calibrated intervals."),
           Limitation(code="ACTUALS_RETROSPECTIVE", text="Actuals are retrospective observations published after the "
                                                         "forecast was issued.")]
    if identity.cutoff_utc is not None:
        out.append(Limitation(code="AS_OF_CUTOFF", text=f"Only forecasts and actuals provably public by "
                                                        f"{identity.cutoff_utc} are used."))
    if identity.kind == "forecast_aggregate" and status != "unavailable":
        out.append(Limitation(code="PAIRS", text=f"{len(pairs)} of the window's {len(pairs) + len(excluded)} "
                                                 "half-hours have a forecast/actual pair."))
        runs = sorted({p.run_id for p in pairs})
        if len(runs) > 1:
            out.append(Limitation(code="RUNS_DIFFER", text=f"Under the selection policy the run differs between "
                                                           f"half-hours ({len(runs)} runs); each pair names its own."))
    if status == "partial":
        out.append(Limitation(code="INCOMPLETE_WINDOW", text="Not every half-hour of the window has a pair, so the "
                                                             "statistics cover the listed pairs only, not the whole "
                                                             "window."))
    if excluded and status != "unavailable":
        by: dict[str, int] = {}
        for x in excluded:
            by[x.reason] = by.get(x.reason, 0) + 1
        out.append(Limitation(code="EXCLUDED", text="Half-hours without a pair: " + "; ".join(
            f"{n} ({_REASON_TEXT[k]})" for k, n in sorted(by.items())) + "."))
    return tuple(out)


def _unavailable(identity: ForecastIdentity, reason: str, excluded: list[ExcludedTarget],
                 call_id: str | None) -> ForecastResult:
    return make_forecast_result(identity, status="unavailable", reason=reason, excluded=tuple(excluded),
                                targets_expected=len(_ends(identity)),
                                limitations=_limitations(identity, "unavailable", [], excluded),
                                transient=Transient(evidence_ids=(), tool_call_id=call_id))


def _unavailable_all(identity: ForecastIdentity, code: Any, call_id: str | None, detail: str | None = None) -> \
        ForecastResult:
    text = detail or _REASON_TEXT[code]
    excluded = [ExcludedTarget(target_end_utc=e, reason=code, detail=text) for e in _ends(identity)]
    return _unavailable(identity, text, excluded, call_id)


def result_from_output(identity: ForecastIdentity, status: str, data: dict[str, Any] | None,
                       view: dict[str, Any] | None, registry: EvidenceRegistry, call_id: str | None,
                       blocked_reason: str | None = None) -> ForecastResult:
    """The result of one ``compare_forecast_actual`` call over the identity's target or window: every pair in it (its
    own run, times and rows, from the call's evidence), every half-hour without one (with its reason) and, for an
    aggregate, MAE and mean error recomputed from the listed pairs."""
    if status == "unavailable" and "excluded" not in (data or {}):  # the tool found no row at all for the span
        return _unavailable_all(identity, "no_data_held", call_id)
    if status not in ("ok", "unavailable"):  # a run-time status (a policy block, a tool error): not re-derivable
        why = f"the controller's {TOOL} call returned {status}" + (f" ({blocked_reason})" if blocked_reason else "")
        return _unavailable(identity, why, [], call_id)
    w0, w1 = _span(identity)
    raw = [p for p in (data or {}).get("pairs") or [] if w0 < parse_iso(p["target_end_utc"]) <= w1]
    pairs: list[ForecastPair] = []
    owned: list[str] = []
    for p in sorted(raw, key=lambda x: x["target_end_utc"]):
        f_ev, a_ev = registry.get(p["poe50_evidence_id"]), registry.get(p["actual_evidence_id"])
        assert f_ev is not None and a_ev is not None
        pairs.append(ForecastPair(
            target_end_utc=p["target_end_utc"], run_id=p["run_id"], run_issued_at_utc=p["run_issued_at_utc"],
            run_published_at_utc=f_ev.published_at_utc, run_available_at_utc=p["run_available_at_utc"],
            lead_hours=p["lead_hours"], poe50_mw=p["poe50_mw"], poe10_mw=p.get("poe10_mw"), poe90_mw=p.get("poe90_mw"),
            forecast_row_id=f_ev.source_row_ids[0], actual_mw=p["actual_mw"], actual_revision=p["actual_revision"],
            actual_row_id=a_ev.source_row_ids[0], error_mw=p["error_mw"], abs_error_mw=abs(p["error_mw"]),
            error_pct=p.get("error_pct")))
        owned += [e for e in (p["poe50_evidence_id"], p.get("poe10_evidence_id"), p.get("poe90_evidence_id"),
                              p["actual_evidence_id"], p["error_evidence_id"], p.get("error_pct_evidence_id")) if e]
    paired = {p.target_end_utc for p in pairs}
    given = {x["target_end_utc"]: x for x in (data or {}).get("excluded") or []}
    excluded = [ExcludedTarget(target_end_utc=e, reason=given[e]["reason"], detail=given[e]["detail"]) if e in given
                else ExcludedTarget(target_end_utc=e, reason="no_data_held", detail=_REASON_TEXT["no_data_held"])
                for e in _ends(identity) if e not in paired]
    rows = tuple(r for p in pairs for r in (p.forecast_row_id, p.actual_row_id))
    if identity.kind == "forecast_point":
        if not pairs:
            return _unavailable(identity, excluded[0].detail if excluded else _REASON_TEXT["no_data_held"], excluded,
                                call_id)
        return make_forecast_result(identity, status="established", pairs=tuple(pairs), excluded=(),
                                    targets_expected=1, source_row_ids=rows,
                                    limitations=_limitations(identity, "established", pairs, []),
                                    transient=Transient(evidence_ids=tuple(owned), tool_call_id=call_id))
    if not pairs:
        return _unavailable(identity, "no half-hour of the window has a forecast/actual pair", excluded, call_id)
    errs = [p.error_mw for p in pairs]
    status_ = "established" if not excluded else "partial"
    v = view or {}
    owned += [e for e in ((v.get("mae_mw") or {}).get("evidence_id"), (v.get("mean_error_mw") or {}).get("evidence_id"),
                          v.get("n_pairs_evidence_id")) if e]
    return make_forecast_result(
        identity, status=status_, reason=None if status_ == "established" else
        "not every half-hour of the window has a forecast/actual pair", pairs=tuple(pairs), excluded=tuple(excluded),
        targets_expected=len(_ends(identity)), mae_mw=round(statistics.fmean(abs(e) for e in errs), 2),
        mean_error_mw=round(statistics.fmean(errs), 2), source_row_ids=rows,
        limitations=_limitations(identity, status_, pairs, excluded),
        transient=Transient(evidence_ids=tuple(owned), tool_call_id=call_id))


def _call_args(identity: ForecastIdentity, run_id: str | None) -> dict[str, Any]:
    w0, w1 = _span(identity)
    args: dict[str, Any] = {"target_start_utc": iso_utc(w0), "target_end_utc": iso_utc(w1),
                            "run_selector": "run_id" if identity.kind == "forecast_point" else identity.run_selection,
                            "as_of_utc": identity.cutoff_utc}
    if args["run_selector"] == "run_id":
        args["run_id"] = run_id
    if identity.run_selection == "min_lead_hours":
        args["min_lead_hours"] = identity.min_lead_hours
    if identity.actual_revision_policy != "latest_available":
        args["actual_revision"] = identity.actual_revision_policy
    return args


def _named(identity: ForecastIdentity) -> ForecastRequest | None:
    if identity.kind == "forecast_point":
        t = _span(identity)
        return ForecastRequest(identity.run_selection,  # type: ignore[arg-type]
                               parse_iso(identity.named_issued_at_utc) if identity.named_issued_at_utc else None, t)
    if identity.named_issued_at_utc:
        return ForecastRequest("issued_at", parse_iso(identity.named_issued_at_utc), None)
    return None


def _compute(identity: ForecastIdentity, store: Store, call: Callable[[dict[str, Any]], Any],
             registry: EvidenceRegistry) -> ForecastResult:
    """The result for an identity: the run lookup where the request names a run, then one comparison call (``call``
    runs the tool: through the dispatcher in a run, directly when re-deriving)."""
    named = _named(identity)
    run_id = identity.named_run_id
    if named is not None:
        cutoff = parse_iso(identity.cutoff_utc) if identity.cutoff_utc else None
        best, code = _lookup(store, identity.region, named, cutoff,
                             _span(identity)[1] if identity.kind == "forecast_point" else None)
        if best is None:
            assert code is not None
            return _unavailable_all(identity, code, None)
        run_id = best["run_id"]
    rec = call({"region": identity.region, **_call_args(identity, run_id)})
    return result_from_output(identity, rec.status, rec.data, rec.view, registry, rec.call_id,
                              getattr(rec, "blocked_reason", None))


def forecast_run_record(store: Store, region: str, wanted: ForecastRequest, as_of: datetime | None) -> dict[str, Any]:
    """The run a point request names, recorded on the resolution exactly as the Live controller records it (I-9), so
    the same checks hold an answer to it (Replay, D27)."""
    hh = wanted.half_hour
    assert hh is not None
    sel = select_run(store, region, wanted, as_of)
    best = sel["best"]
    run_id = best["run_id"] if best else None
    if run_id and not run_holds(store, region, run_id, hh[1]):
        run_id = None  # the named run holds no forecast for this half-hour
    out: dict[str, Any] = {"half_hour_utc": [iso_utc(hh[0]), iso_utc(hh[1])], "half_hour_end_utc": iso_utc(hh[1]),
                           "run_id": run_id, "issued_at_utc": iso_utc(best["issued_at_utc"]) if best else None}
    if sel["tied"] and not run_id:
        out["unavailable"] = TIED_RUNS
    return out


def matching_record(identity: ForecastIdentity, records: list[Any]) -> Any:
    """The comparison call already made over exactly the identity's window and policy (a Replay plan's), or None."""
    w = identity.window_utc
    for r in records:
        a = r.args or {}
        if r.name == TOOL and w is not None and a.get("region") == identity.region and \
                (a.get("target_start_utc"), a.get("target_end_utc")) == w and \
                a.get("run_selector") == identity.run_selection and a.get("as_of_utc") == identity.cutoff_utc and \
                (a.get("actual_revision") or "latest_available") == identity.actual_revision_policy and \
                identity.named_issued_at_utc is None:
            return r
    return None


def compute(d: Dispatcher, identity: ForecastIdentity) -> ForecastResult:
    call_id = POINT_CALL_ID if identity.kind == "forecast_point" else WINDOW_CALL_ID
    return _compute(identity, d.store, lambda args: d.call(TOOL, args, call_id=call_id, origin="controller"),
                    d.registry)


def rederive(identity: ForecastIdentity, store: Store, selection: Selection) -> ForecastResult:
    """The same result computed again from the pinned store with the same tool code, outside any investigation (its
    in-run references are this computation's own). Used by the verifier (``results``)."""
    from ..evidence import EvidenceRegistry as _Registry
    from ..tools import TOOLS
    from ..tools.impl import ToolContext

    reg = _Registry()
    spec = TOOLS[TOOL]
    cutoff = parse_iso(identity.cutoff_utc) if identity.cutoff_utc else None

    class _Rec:
        def __init__(self, out: Any) -> None:
            self.status, self.data, self.view, self.call_id = out.status, out.data, out.view, "rederive"

    def call(args: dict[str, Any]) -> _Rec:
        out = spec.handler(ToolContext(store=store, selection=selection, registry=reg, call_id="rederive",
                                       request_as_of=cutoff), spec.args_model.model_validate(args))
        return _Rec(out)
    return _compute(identity, store, call, reg)


def not_rederivable(r: ForecastResult) -> str | None:
    if r.status == "unavailable" and any(re.search(rf"call returned {s}\b", r.reason or "") for s in _RUNTIME_ONLY):
        return "a run-time call status (a policy block or a tool error) cannot be re-derived from the store"
    return None


# -- consistency (the verifier's integrity check) ------------------------------------------------------------------------
def integrity(r: ForecastResult) -> list[str]:
    out = []
    i = r.identity
    ends = _ends(i)
    if r.targets_expected != len(ends):
        out.append("targets_expected is not the number of half-hours in the target or window")
    if r.status != "unavailable" or r.excluded:
        if sorted([p.target_end_utc for p in r.pairs] + [x.target_end_utc for x in r.excluded]) != ends:
            out.append("the pairs and the excluded half-hours are not exactly the half-hours of the target or window")
    elif not_rederivable(r) is None:
        out.append("an unavailable result lists every half-hour without a pair, unless a run-time status caused it")
    for p in r.pairs:
        if abs(p.error_mw - round(p.poe50_mw - p.actual_mw, 2)) > 1e-9 or abs(p.abs_error_mw - abs(p.error_mw)) > 1e-9:
            out.append(f"the pair ending {p.target_end_utc} has an error that is not POE50 minus actual")
    if r.source_row_ids != tuple(x for p in r.pairs for x in (p.forecast_row_id, p.actual_row_id)):
        out.append("the source rows are not the pairs' forecast and actual rows")
    if i.kind == "forecast_point":
        if r.status == "partial" or r.mae_mw is not None or r.mean_error_mw is not None:
            out.append("a point result is established or unavailable, and carries no aggregate")
        if r.status == "established" and len(r.pairs) != 1:
            out.append("an established point result has exactly one pair")
    else:
        errs = [p.error_mw for p in r.pairs]
        if r.status == "established" and r.excluded:
            out.append("an established aggregate pairs every half-hour of its window")
        if r.status == "partial" and not (r.pairs and r.excluded):
            out.append("a partial aggregate lists its pairs and the half-hours without one")
        if r.status != "unavailable" and (r.mae_mw is None or r.mean_error_mw is None or
                                          abs(r.mae_mw - round(statistics.fmean(abs(e) for e in errs), 2)) > 1e-9 or
                                          abs(r.mean_error_mw - round(statistics.fmean(errs), 2)) > 1e-9):
            out.append("the aggregate's MAE or mean error is not recomputed from its pairs")
    if r.status == "unavailable" and (r.pairs or r.mae_mw is not None or not r.reason):
        out.append("an unavailable result carries no pair and no value, only its reason")
    return out


def in_run_problems(r: ForecastResult, evidence: EvidenceRegistry) -> list[str]:
    """The in-run evidence the result names agrees with it: each pair's forecast, actual and error, and the aggregate's
    MAE and mean error."""
    out = []
    items = [evidence.get(e) for e in r.transient.evidence_ids]
    if any(x is None for x in items):
        return ["in-run evidence the result names is not in the run's registry"]
    by = [x for x in items if x is not None]
    for p in r.pairs:
        want = {("opdemand_forecast_poe50", p.poe50_mw, (p.forecast_row_id,)), ("opdemand_actual", p.actual_mw,
                                                                               (p.actual_row_id,))}
        for metric, value, rows in want:
            if not any(x.metric == metric and x.valid_at_utc == p.target_end_utc and x.value is not None and
                       abs(float(x.value) - value) <= 1e-9 and tuple(x.source_row_ids) == rows for x in by):
                out.append(f"in-run evidence does not hold the pair ending {p.target_end_utc} ({metric})")
        if not any(x.metric == "forecast_error_mw" and x.valid_at_utc == p.target_end_utc and x.value is not None and
                   abs(float(x.value) - p.error_mw) <= 1e-9 for x in by):
            out.append(f"in-run evidence does not hold the error of the pair ending {p.target_end_utc}")
    for name, agg in (("mae_mw", r.mae_mw), ("mean_error_mw", r.mean_error_mw)):
        if agg is not None and not any(x.metric == name and x.value is not None and
                                       abs(float(x.value) - agg) <= 1e-9 for x in by):
            out.append(f"in-run evidence does not hold the aggregate's {name}")
    return out


# -- submission: the primary, as the validator and the model's context read it -------------------------------------------
def submit(d: Dispatcher, res: Resolution, r: ForecastResult) -> dict[str, Any]:
    """Submit the primary to the investigation's verified-result registry and record on the resolution what it owns
    (``scope_of``), admitted or not."""
    v = d.results.submit_in_run(r, store=d.store, selection=d.selection, evidence=d.registry, trace=d.trace)
    res.forecast_primary = scope_of(r, v.outcome == "verified")
    return res.forecast_primary


def scope_of(r: ForecastResult, admitted: bool) -> dict[str, Any]:
    """What the primary owns, as the validator and the fallback read it: its pairs' rows and its own evidence. An
    aggregate's own MAE, mean error and pair count are the last three evidence IDs it names (``result_from_output``)."""
    eids = list(r.transient.evidence_ids)
    aggregate = r.identity.kind == "forecast_aggregate" and r.status != "unavailable"
    return {"result_id": r.result_id, "kind": r.identity.kind, "status": r.status, "admitted": admitted,
            "call_id": r.transient.tool_call_id, "evidence_ids": eids,
            "pair_rows": [[p.forecast_row_id, p.actual_row_id] for p in r.pairs],
            "mae_evidence_id": eids[-3] if aggregate else None, "cutoff_utc": r.identity.cutoff_utc,
            "target_utc": list(r.identity.target_utc or r.identity.window_utc or ())}


def pair_set(rec: Any, registry: EvidenceRegistry) -> frozenset[tuple[str, str]]:
    """The (forecast row, actual row) pairs a comparison call was computed from."""
    out = set()
    for p in (rec.data or {}).get("pairs") or []:
        f, a = registry.get(p["poe50_evidence_id"]), registry.get(p["actual_evidence_id"])
        if f is not None and a is not None and f.source_row_ids and a.source_row_ids:
            out.add((f.source_row_ids[0], a.source_row_ids[0]))
    return frozenset(out)


def out_of_scope(ev: Any, primary: dict[str, Any], calls: dict[str, Any], registry: EvidenceRegistry) -> str | None:
    """Why an evidence item a forecast comparison registered is outside the primary's scope, or None. Read from its
    metric and source rows, never from wording or value."""
    rec = calls.get(ev.tool_call_id)
    if rec is None or ev.metric not in PAIR_METRICS | AGGREGATE_METRICS:
        return None  # not comparison evidence: the existing checks apply to it
    pairs = {(f, a) for f, a in primary["pair_rows"]}
    if not primary["admitted"]:
        return "the comparison the question asks for was not verified, so none of its values may be given"
    if ev.metric in PAIR_METRICS:
        rows = set(ev.source_row_ids)
        if ev.metric.startswith("opdemand_forecast_"):
            ok = bool(rows) and rows <= {f for f, _ in pairs}
        elif ev.metric == "opdemand_actual":
            ok = bool(rows) and rows <= {a for _, a in pairs}
        else:
            ok = any(rows == {f, a} for f, a in pairs)
        return None if ok else "it belongs to another half-hour or run than the comparison the question asks for"
    return None if pair_set(rec, registry) == frozenset(pairs) else \
        "it is an aggregate over other pairs than the comparison the question asks for"


# -- the controller's statement (rendered by ``render.render_result``) ----------------------------------------------------
def _at(t: str, region: str) -> str:
    return f"{t} = {re.sub(r' [(]UTC[^)]*[)]', '', local_str(parse_iso(t), region))}"


def _signed(text: str, value: float) -> str:
    return f"+{text}" if value > 0 else text


def _subject(i: ForecastIdentity, region: str) -> str:
    if i.kind == "forecast_point":
        assert i.target_utc is not None
        return f"For {region} operational demand in the half-hour ending {_at(i.target_utc[1], region)}"
    assert i.window_utc is not None
    return (f"For {region} operational demand over the half-hours ending after {_at(i.window_utc[0], region)} and by "
            f"{_at(i.window_utc[1], region)}")


def statement(r: ForecastResult, region: str, num: Callable[[str], str]) -> str:
    """The controller's statement of an admitted result. ``num(evidence_id)`` formats a value and records its claim, so
    every number stated traces to the result's own in-run evidence."""
    i = r.identity
    if r.status == "unavailable":
        return f"{_subject(i, region)}, the comparison asked for cannot be given: {r.reason}. " + \
            ("No other forecast run or half-hour is given in its place." if i.kind == "forecast_point" else
             "No other window or run selection is given in its place.")
    # the evidence IDs are in ``result_from_output``'s order: each pair's POE50, POE10, POE90 (when held), actual, error
    # and percentage error (when the actual is not 0); then an aggregate's MAE, mean error and pair count
    eids = r.transient.evidence_ids
    if i.kind == "forecast_point":
        p = r.pairs[0]
        f_id, a_id, e_id, pct_id = eids[0], eids[-3 if p.error_pct is not None else -2], \
            eids[-2 if p.error_pct is not None else -1], eids[-1] if p.error_pct is not None else None
        pct = f" ({num(pct_id)} of the actual)" if pct_id else ""
        return (f"{_subject(i, region)}, forecast run {p.run_id} gave a POE50 of {num(f_id)} and the actual "
                f"({p.actual_revision} revision) was {num(a_id)}: an error of {_signed(num(e_id), p.error_mw)}{pct}, "
                "the POE50 minus the actual (positive means the forecast was above the actual). "
                f"That run was issued at {p.run_issued_at_utc}, {POLICY_TEXT[i.run_selection]}. "
                "This is one forecast/actual pair.")
    mae_id, bias_id, n_id = eids[-3], eids[-2], eids[-1]
    assert r.mean_error_mw is not None
    partial = (", not every half-hour of the window: these statistics cover those pairs only"
               if r.status == "partial" else "")
    return (f"{_subject(i, region)}, {POLICY_TEXT[i.run_selection]}, compared with the actuals "
            f"({i.actual_revision_policy.replace('_', ' ')}): a mean absolute error of {num(mae_id)} and a mean error "
            f"of {_signed(num(bias_id), r.mean_error_mw)} (POE50 minus actual; positive means the forecasts were "
            f"above the actuals), over the {num(n_id)} that have a forecast/actual pair{partial}.")


NOT_VERIFIED = "the computed result could not be verified against the pinned data ({})"


def statement_not_verified(identity: ForecastIdentity, region: str, outcome: str) -> str:
    return f"{_subject(identity, region)}, the comparison asked for cannot be given: {NOT_VERIFIED.format(outcome)}."
