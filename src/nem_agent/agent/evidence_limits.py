"""Evidence limits for Standard Live's opt-in variant ``tool-turn-done/2`` (D37 amendment 1): what the tool records
establish about the evidence, computed by code after the tool loop.

Two uses, both only under the variant:

- ``limits_block``: a compact JSON block given to synthesis (and so to repair), alongside the controller's other
  computations. It states the window investigated and whether the request explicitly asked for that period, what each
  data tool actually covered, each tool's own caveats, gaps and failures, and the shortfalls the code has established.
  Whether a limitation matters to the question or to an explanation is the model's judgement, said in the report; the
  code does not claim to have checked it.
- ``status_shortfalls`` with ``lower_status``: an "answered" report is lowered to "answered_with_caveats", with the
  reasons recorded, only for shortfalls the records establish objectively: a required tool without a result, a
  requested computed result that was not established or not verified, and, for a period the request explicitly asked
  for, a required tool that did not cover it or that itself reports data absent within it. In the investigation's
  contextual window (the event's window or the local day) a narrower analysis or a gap in the data held is recorded,
  never a shortfall: analysing the part around the event can be the right analysis, and whether a gap matters to the
  question is not decided by code. Nothing here raises a status.

Coverage comes from the records (each successful call's own arguments and counts), never from a report's wording.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .. import config
from ..timeutil import iso_utc, local_str, parse_iso

# the period arguments of each data tool, and the most one call of it may cover (its own limit)
WINDOW_ARGS: dict[str, tuple[str, str]] = {
    "find_market_events": ("start_utc", "end_utc"), "get_price_timeline": ("start_utc", "end_utc"),
    "get_actual_demand": ("start_utc", "end_utc"), "get_generation_change": ("start_utc", "end_utc"),
    "get_weather_context": ("start_utc", "end_utc"), "get_forecast_runs": ("target_start_utc", "target_end_utc"),
    "compare_forecast_actual": ("target_start_utc", "target_end_utc")}
MAX_HOURS_PER_CALL: dict[str, float] = {
    "find_market_events": config.MAX_EVENT_SEARCH_DAYS * 24, "get_price_timeline": config.MAX_PRICE_WINDOW_HOURS,
    "get_actual_demand": config.MAX_ACTUAL_WINDOW_HOURS, "get_generation_change": config.MAX_GENERATION_WINDOW_HOURS,
    "get_weather_context": config.MAX_WEATHER_WINDOW_HOURS, "get_forecast_runs": config.MAX_FORECAST_TARGET_HOURS,
    "compare_forecast_actual": config.MAX_FORECAST_TARGET_HOURS}
# the interval grid of the series whose own counts show intervals absent from the data held
GRID_MINUTES = {"get_price_timeline": 5, "get_actual_demand": 30}
NOTE_CHARS = 220


def _label(tool: str) -> str:
    from ..display import TOOL_NAMES  # presentation labels, shared with the report's display

    return TOOL_NAMES.get(tool, tool)


def _hours(a: datetime, b: datetime) -> float:
    return round(max((b - a).total_seconds(), 0.0) / 3600, 2)


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _call_span(rec: Any) -> tuple[datetime, datetime] | None:
    keys = WINDOW_ARGS.get(rec.name) or (("event_start_utc", "event_end_utc") if rec.name == "retrieve_public_evidence"
                                         else None)
    args = rec.args if isinstance(rec.args, dict) else {}
    if keys is None or not args.get(keys[0]) or not args.get(keys[1]):
        return None
    return parse_iso(args[keys[0]]), parse_iso(args[keys[1]])


def covered_spans(records: list[Any], tool: str) -> list[tuple[datetime, datetime]]:
    """The periods a data tool covered: its successful calls' own periods, merged."""
    return _merge([s for r in records if r.name == tool and r.status == "ok" and (s := _call_span(r)) is not None])


def _within(spans: list[tuple[datetime, datetime]], w0: datetime, w1: datetime) -> float:
    return round(sum(max((min(b, w1) - max(a, w0)).total_seconds(), 0.0) for a, b in spans) / 3600, 2)


def _covers(spans: list[tuple[datetime, datetime]], w0: datetime, w1: datetime) -> bool:
    return any(a <= w0 and w1 <= b for a, b in spans)


def window_basis(res: Any) -> dict[str, Any] | None:
    """The window investigated and how it was given: explicitly requested (a window given with the request, or the
    forecast period the question asks about, as the resolver bound it) or contextual (the selected event's window, or
    the local day of the date or half-hour asked about)."""
    if not res.window:
        return None
    w0, w1 = res.window
    req = res.request
    forecast = getattr(getattr(res, "requests", None), "forecast", None)
    if req.window_start_utc and req.window_end_utc:
        source, explicit = "the window given with the request", True
    elif forecast is not None and forecast.status == "bound" and forecast.window is not None and \
            tuple(forecast.window) == (w0, w1):
        source, explicit = "the forecast period the question asks about", True
    elif res.event is not None and (parse_iso(res.event.window_start_utc), parse_iso(res.event.window_end_utc)) == (w0, w1):
        source, explicit = "the selected price event's window: context for the question, not a period it names", False
    else:
        source, explicit = "the local day of the date or half-hour asked about: context, not a period the question names", False
    out: dict[str, Any] = {"utc": [iso_utc(w0), iso_utc(w1)], "hours": _hours(w0, w1), "source": source,
                           "explicitly_requested": explicit}
    if res.region:
        out["local"] = [local_str(w0, res.region), local_str(w1, res.region)]
    return out


def _anchor(res: Any) -> tuple[datetime | None, str | None]:
    """The time a narrower analysis is centred on: the half-hour asked about, else the event's peak interval."""
    if getattr(res, "target", None):
        return res.target[1], "the half-hour asked about"
    if res.event is not None and res.intent in ("market_event_review", "forecast_review"):
        return parse_iso(res.event.peak_interval_end_utc), "the event's peak interval"
    return None, None


def coverage(records: list[Any], res: Any, playbook: Any) -> list[dict[str, Any]]:
    """What each data tool actually covered, against the window investigated."""
    if not res.window:
        return []
    w0, w1 = res.window
    basis = window_basis(res) or {}
    anchor, anchor_name = _anchor(res)
    out = []
    for tool in WINDOW_ARGS:
        spans = covered_spans(records, tool)
        if not spans:
            continue
        inside = _within(spans, w0, w1)
        whole = _covers(spans, w0, w1)
        role = "required" if tool in playbook.required else "optional"
        if whole:
            relation = "whole window"
        elif inside == 0:
            relation = "outside the window"
        elif basis.get("explicitly_requested"):
            relation = "part of the explicitly requested period: incomplete"
        elif anchor is not None and any(a < anchor <= b for a, b in spans):
            relation = f"part of the window, including {anchor_name}"
        else:
            relation = "part of the window"
        entry: dict[str, Any] = {"tool": tool, "role": role, "coverage": relation}
        if not whole:  # what it did cover, and the most one call of it may cover
            entry |= {"covered_utc": [[iso_utc(a), iso_utc(b)] for a, b in spans],
                      **({"covered_local": [[local_str(a, res.region), local_str(b, res.region)] for a, b in spans]}
                         if res.region else {}),
                      "hours_within_window": inside, "max_hours_per_call": MAX_HOURS_PER_CALL[tool],
                      "counts_for_status": bool(basis.get("explicitly_requested") and role == "required")}
        out.append(entry)
    return out


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= NOTE_CHARS else text[:NOTE_CHARS - 1].rstrip() + "…"


def tool_limits(records: list[Any], playbook: Any) -> list[dict[str, Any]]:
    """Each tool's own caveats, gaps and failures, as its records state them (compact; nothing inferred). A blocked call
    followed by a successful call of the same tool is left out: the retry replaced it."""
    out = []
    for i, r in enumerate(records):
        role = "required" if r.name in playbook.required else "optional"
        if r.status != "ok":
            if r.status == "blocked" and any(x.name == r.name and x.status == "ok" for x in records[i + 1:]):
                continue
            detail = (r.missing or [r.blocked_reason or ""])[0]
            out.append({"tool": r.name, "role": role, "status": r.status, "notes": [_clip(detail)] if detail else []})
            continue
        v = r.view or {}
        notes: list[str] = []
        for key in ("caveat", "threshold_note"):
            if isinstance(v.get(key), str):
                notes.append(v[key])
        scope = v.get("search_scope")
        if isinstance(scope, dict):
            notes.append(f"market notices: {scope['outcome']}" if scope.get("searched")
                         else f"market notices not searched: {scope.get('reason')}")
        hidden = v.get("excluded_not_yet_available_at_as_of") or v.get("actual_rows_hidden_by_as_of")
        if hidden:
            notes.append(f"{hidden} rows published after the as-of cutoff are excluded")
        if r.name in GRID_MINUTES and (gap := _series_gap(r)) is not None:  # the other tools say theirs in ``missing``
            notes.append(gap)
        notes += [m for m in r.missing[:3]]
        notes += [p for p in r.policy_notes[:2]]
        kept = list(dict.fromkeys(_clip(n) for n in notes if n))
        if kept:
            out.append({"tool": r.name, "role": role, "status": "ok", "notes": kept})
    return out


def _series_gap(rec: Any) -> str | None:
    """Intervals of a successful series call's own period that are not in the data held, from the tool's own counts
    (intervals withheld by an as-of cutoff are not a gap); None when nothing is absent or the tool gives no counts."""
    span = _call_span(rec)
    if span is None:
        return None
    v, label = rec.view or {}, _label(rec.name)
    if rec.name == "find_market_events":
        cov = v.get("coverage") or {}
        held, expected = cov.get("intervals_in_store"), cov.get("intervals_expected")
        if isinstance(held, int) and isinstance(expected, int) and held < expected:
            return f"{label}: {expected - held} of {expected} 5-minute intervals in its period are not in the data held"
    if rec.name in GRID_MINUTES:
        expected = int((span[1] - span[0]) / timedelta(minutes=GRID_MINUTES[rec.name]))
        got = int(v.get("n_intervals") or 0) + int(v.get("excluded_not_yet_available_at_as_of") or 0)
        if got < expected:
            return (f"{label}: {expected - got} of {expected} {GRID_MINUTES[rec.name]}-minute intervals in its period "
                    "are not in the data held")
    if rec.name == "compare_forecast_actual":
        lost = [x for x in (rec.data or {}).get("excluded") or [] if x.get("reason") != "not_public_by_cutoff"]
        if lost:
            return f"{label}: {len(lost)} target half-hours in its period have no forecast-actual pair"
    return None


def _data_gap(rec: Any, w0: datetime, w1: datetime) -> str | None:
    """A gap in a call that lies within the period given (a gap outside it is not that period's)."""
    span = _call_span(rec)
    if span is None or span[0] < w0 or span[1] > w1:
        return None
    return _series_gap(rec)


def status_shortfalls(records: list[Any], res: Any, playbook: Any, results: list[Any]) -> list[dict[str, Any]]:
    """The shortfalls the records establish objectively, each with a plain reason. Only these lower a status."""
    out: list[dict[str, Any]] = []
    for tool in playbook.required:
        tried = [r for r in records if r.name == tool]
        if not any(r.status == "ok" for r in tried):
            how = ("was not run" if not tried else
                   f"returned no result ({', '.join(sorted({r.status for r in tried}))})")
            out.append({"rule": "required_tool_without_result", "tool": tool,
                        "detail": f"{_label(tool)}, a required tool, {how}"})
    if res.window and (window_basis(res) or {}).get("explicitly_requested"):
        # only a period the request names: in a contextual window (the event's, or the local day) a gap or a narrower
        # analysis is disclosed in the limits, and whether it matters to the question is not decided by code
        w0, w1 = res.window
        for r in records:
            if r.name in playbook.required and r.status == "ok" and (gap := _data_gap(r, w0, w1)) is not None:
                out.append({"rule": "required_data_absent", "tool": r.name, "call_id": r.call_id,
                            "detail": f"{gap} (within the requested period)"})
        for tool in playbook.required:
            spans = covered_spans(records, tool) if tool in WINDOW_ARGS else []
            if spans and not _covers(spans, w0, w1):
                out.append({"rule": "requested_period_not_covered", "tool": tool,
                            "detail": f"{_label(tool)}, a required tool, covered {_within(spans, w0, w1):g} of the "
                                      f"{_hours(w0, w1):g} hours of the requested period"})
    for rr in results:
        result, verification = rr.result, rr.server_verification
        if verification.outcome != "verified" or result.status != "established":
            ident = result.identity
            what = getattr(ident, "kind", None) or getattr(ident, "measure", None) or "result"
            out.append({"rule": "requested_result_not_established", "result_id": result.result_id,
                        "detail": f"a requested computed result ({str(what).replace('_', ' ')}) is {result.status}"
                                  + ("" if verification.outcome == "verified" else
                                     f" and was not verified ({verification.outcome})")})
    return out


def limits_block(records: list[Any], res: Any, playbook: Any, results: list[Any]) -> dict[str, Any]:
    """The evidence limits given to synthesis: compact, from the records only."""
    return {
        "window": window_basis(res),
        "coverage": coverage(records, res, playbook),
        "tool_limits": tool_limits(records, playbook),
        "status_shortfalls": status_shortfalls(records, res, playbook, results),
        "note": "From the tool records only. The code lowers an 'answered' status for each status_shortfalls entry and "
                "records why; whether another limitation matters to the question or to an explanation is not checked "
                "by code."}


STATUS_NOTE = "The status is answered with caveats because the tool records show: "


def lower_status(report: Any, shortfalls: list[dict[str, Any]], variant: str) -> Any:
    """``report`` with an "answered" status lowered to "answered_with_caveats" when ``shortfalls`` is not empty, the
    reasons recorded in its validation details and said in one uncertainty. Any other status is returned unchanged:
    nothing is raised, and a status the model or the fallback already lowered stays as it is."""
    if report.status != "answered" or not shortfalls:
        return report
    reasons = [s["detail"] for s in shortfalls]
    return report.model_copy(update={
        "status": "answered_with_caveats",
        "uncertainties": [*report.uncertainties, STATUS_NOTE + "; ".join(reasons) + "."],
        "validation": {**report.validation, "status_lowered": {"from": "answered", "to": "answered_with_caveats",
                                                               "variant": variant, "shortfalls": shortfalls}}})
