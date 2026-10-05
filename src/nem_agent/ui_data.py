"""Pure helpers that turn an investigation result into chart/table data (tested without a browser).

Charts follow the project's rules: native resolutions (5-minute price, half-hour demand), interval-ending steps
(`step-before`: the value stamped T covers the interval ending at T), region-local wall time on the x-axis, one
y-axis per chart (price and demand are separate charts, never a dual axis).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import altair as alt
import pandas as pd

from .evidence import aggregate_coverage
from .timeutil import parse_iso, to_local

# Validated categorical slots (dataviz reference palette; validator: all checks pass, light and dark)
SERIES = {"light": {"actual": "#2a78d6", "forecast": "#eb6834", "price": "#2a78d6"},
          "dark": {"actual": "#3987e5", "forecast": "#d95926", "price": "#3987e5"}}
LABEL_ACTUAL = "Actual"
LABEL_FORECAST = "AEMO POE50 forecast"


def _local_naive(ts: str, region: str) -> str:
    # wall-clock time in the region, serialised with 'Z' so Vega does not shift it into the browser timezone
    return to_local(parse_iso(ts), region).strftime("%Y-%m-%dT%H:%M:%SZ")


def frames(records: list[Any], region: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_rows: list[dict[str, Any]] = []
    demand_rows: list[dict[str, Any]] = []
    if not region:
        return pd.DataFrame(), pd.DataFrame()
    for r in records:
        if r.status != "ok":
            continue
        if r.name == "get_price_timeline" and not price_rows:
            for s in r.data["series"]:
                price_rows.append({"t": _local_naive(s["interval_end_utc"], region), "utc": s["interval_end_utc"],
                                   "rrp": s["rrp"], "status": s["price_status"], "evidence_id": s["rrp_evidence_id"],
                                   "row_id": s["row_id"]})
        elif r.name == "get_actual_demand":
            have = {d["utc"] for d in demand_rows if d["series"] == LABEL_ACTUAL}
            for s in r.data["series"]:
                if s["interval_end_utc"] not in have:
                    demand_rows.append({"t": _local_naive(s["interval_end_utc"], region), "utc": s["interval_end_utc"],
                                        "series": LABEL_ACTUAL, "mw": s["operational_demand_mw"],
                                        "evidence_id": s["evidence_id"], "detail": f"revision: {s['revision']}"})
        elif r.name == "compare_forecast_actual" and r.args and r.args.get("run_selector") in (
                "latest_before_target", "latest_available_as_of"):
            have = {d["utc"] for d in demand_rows if d["series"] == LABEL_FORECAST}
            for p in r.data["pairs"]:
                if p["target_end_utc"] not in have:
                    demand_rows.append({"t": _local_naive(p["target_end_utc"], region), "utc": p["target_end_utc"],
                                        "series": LABEL_FORECAST, "mw": p["poe50_mw"], "evidence_id": p["poe50_evidence_id"],
                                        "detail": f"run {p['run_id'][-28:]}, lead {p['lead_hours']} h"})
    return pd.DataFrame(price_rows), pd.DataFrame(demand_rows)


def price_chart(df: pd.DataFrame, region: str, tz_name: str, theme: str = "light",
                peak_utc: str | None = None) -> Any:
    color = SERIES[theme]["price"]
    x = alt.X("t:T", title=f"Interval end, local time ({tz_name})", scale=alt.Scale(type="utc"),
              axis=alt.Axis(format="%d %b %H:%M", labelOverlap=True, grid=False))
    base = alt.Chart(df)
    line = base.mark_line(interpolate="step-before", strokeWidth=2, color=color).encode(
        x=x, y=alt.Y("rrp:Q", title="RRP ($/MWh)", axis=alt.Axis(gridOpacity=0.35)))
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["t"], empty=False, clear="pointerout")
    points = base.mark_point(size=80, filled=True, color=color).encode(
        x=x, y="rrp:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("t:T", title="Interval end (local)", format="%d %b %H:%M", timeUnit="utcyearmonthdatehoursminutes"),
                 alt.Tooltip("rrp:Q", title="RRP $/MWh", format=",.2f"), alt.Tooltip("status:N", title="Price status"),
                 alt.Tooltip("evidence_id:N", title="Evidence"), alt.Tooltip("row_id:N", title="Source row")],
    ).add_params(hover)
    layers: list[Any] = [line, points]
    if peak_utc is not None:
        pk = df[df["utc"] == peak_utc]
        if not pk.empty:
            rule = alt.Chart(pk).mark_rule(strokeDash=[4, 3], strokeWidth=1, opacity=0.6).encode(x=x)
            label = alt.Chart(pk).mark_text(align="left", dx=6, dy=-6, fontSize=12).encode(
                x=x, y="rrp:Q", text=alt.Text("rrp:Q", format="$,.0f"))
            layers += [rule, label]
    return alt.layer(*layers).properties(height=320, title=alt.TitleParams(
        f"{region} dispatch price (5-minute, interval-ending)", anchor="start"))


def demand_chart(df: pd.DataFrame, region: str, tz_name: str, theme: str = "light",
                 no_forecast: str = "no forecast runs were retrieved") -> Any:
    """``no_forecast``: what the title says when no forecast line is drawn. The finished page keeps the default; the
    Live progress panel says what is known at its stage (D36), since forecasts may still be retrieved."""
    colors = SERIES[theme]
    x = alt.X("t:T", title=f"Half-hour end, local time ({tz_name})", scale=alt.Scale(type="utc"),
              axis=alt.Axis(format="%d %b %H:%M", labelOverlap=True, grid=False))
    # legend only for series that are drawn (a live run may fetch no forecasts); each keeps its fixed colour and dash
    present = [s for s in (LABEL_ACTUAL, LABEL_FORECAST) if s in set(df["series"])]
    hue = {LABEL_ACTUAL: colors["actual"], LABEL_FORECAST: colors["forecast"]}
    stroke = {LABEL_ACTUAL: [1, 0], LABEL_FORECAST: [6, 3]}
    color = alt.Color("series:N", title=None, scale=alt.Scale(domain=present, range=[hue[s] for s in present]),
                      legend=alt.Legend(orient="top", direction="horizontal", symbolType="stroke", symbolStrokeWidth=2))
    dash = alt.StrokeDash("series:N", scale=alt.Scale(domain=present, range=[stroke[s] for s in present]), legend=None)
    base = alt.Chart(df)
    lines = base.mark_line(interpolate="step-before", strokeWidth=2).encode(
        x=x, y=alt.Y("mw:Q", title="MW (half-hour average)", scale=alt.Scale(zero=False),
                     axis=alt.Axis(gridOpacity=0.35)), color=color, strokeDash=dash)
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["t"], empty=False, clear="pointerout")
    points = base.mark_point(size=80, filled=True).encode(
        x=x, y="mw:Q", color=color, opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("series:N", title="Series"),
                 alt.Tooltip("t:T", title="Half-hour end (local)", format="%d %b %H:%M", timeUnit="utcyearmonthdatehoursminutes"),
                 alt.Tooltip("mw:Q", title="MW", format=",.0f"), alt.Tooltip("detail:N", title="Detail"),
                 alt.Tooltip("evidence_id:N", title="Evidence")],
    ).add_params(hover)
    last = df.sort_values("t").groupby("series").tail(1)
    labels = alt.Chart(last).mark_text(align="left", dx=6, fontSize=11).encode(
        x=x, y="mw:Q", text=alt.Text("series:N"), color=alt.value("#52514e" if theme == "light" else "#c3c2b7"))
    # Streamlit sizes charts with autosize=fit: title, legend and axes come out of `height`, so leave room.
    return alt.layer(lines, points, labels).properties(
        height=380, title=alt.TitleParams(
            f"{region} operational demand: actual vs latest AEMO forecast (half-hourly)" if LABEL_FORECAST in present
            else f"{region} operational demand: actual (half-hourly; {no_forecast})", anchor="start"))


def observation_table(report: dict[str, Any]) -> pd.DataFrame:
    rows = [{"metric": o["metric"], "value": o["value"], "unit": o["unit"], "valid at (local)": o.get("valid_at_local"),
             "class": o["evidence_class"], "evidence": o["evidence_id"], "source row": ", ".join(o["source_row_ids"][:2]),
             "label": o["label"]} for o in report["observations"]]
    return pd.DataFrame(rows)


NO_MODEL_ANSWER = "not applicable: no model answer was produced (stopped at a budget limit)"


def result_provenance(rep: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Who wrote the report on screen, taken from the report itself (never from the UI's mode selector).

    A replay report is always labelled REPLAY; a live report is labelled by what actually reached the user: the
    model's validated answer, or the facts-only fallback shown when the model's answer failed validation.
    """
    v = rep.get("validation") or {}
    versions = rep.get("versions") or {}
    model = versions.get("model")
    fallback = bool(v.get("fallback_applied"))
    repaired = bool(v.get("repair_attempted"))
    generated = str(rep.get("generator", "")).startswith("live-model:")
    # D25: the computed answer (code, from verified results) and the interpretation are reported apart
    answers = rep.get("answer") or []
    absent = str(v.get("interpretation", "")).startswith("absent")
    stopped = v.get("stopped") or {}  # D34: a budget limit stopped the run before the model wrote an answer
    computed = ("; ".join(f"{a['status'].replace('_', ' ')} ({a['verification']})" for a in answers) if answers
                else "none")
    if rep.get("mode") != "live":
        label, kind = "REPLAY — scripted controller over real data, no LLM", "replay"
    elif fallback:
        label, kind = ((f"LIVE ({model}) — the model's interpretation failed validation; showing the computed answer "
                        "and validated tool facts only") if answers else
                       f"LIVE ({model}) — the model's answer failed validation; showing validated tool facts only",
                       "live_fallback")
    elif generated and absent and stopped:
        label, kind = (f"LIVE ({model}) — stopped at a budget limit before the model wrote an answer: no model answer "
                       "was produced" + ("; showing only the answer computed by code" if answers else ""),
                       "live_stopped")
    elif generated and absent:
        label, kind = ((f"LIVE ({model}) — the model produced no valid interpretation; showing only the answer "
                        "computed by code") if answers else
                       f"LIVE ({model}) — the model produced no valid answer"), "live_no_interpretation"
    elif generated:
        label, kind = f"LIVE — answer written by {model}, checked by the independent validator", "live_answer"
    else:
        label, kind = f"LIVE ({model or 'model'}) — routing only; no answer was generated", "live_no_answer"
    if rep.get("mode") != "live":
        validation = "passed" if v.get("final_passed", v.get("passed")) else "failed"
    elif not generated:
        validation = "no generated answer"
    elif fallback:
        validation = "rejected after one repair: facts-only fallback" if repaired else "rejected: facts-only fallback"
        if v.get("repair_stopped"):
            validation += " (the repair was not run: stopped at a budget limit)"
    elif absent and stopped:
        validation = NO_MODEL_ANSWER
    elif absent:
        validation = "no valid model output to validate"
    else:
        validation = "passed after one repair" if repaired else "passed on the first draft"
    u = usage or {}
    return {"kind": kind, "label": label, "model": model, "prompt": versions.get("prompt"),
            "generator": rep.get("generator"), "validation": validation, "computed_answer": computed,
            "interpretation": v.get("interpretation") or ("scripted" if rep.get("mode") != "live" else "unknown"),
            "model_calls": u.get("model_calls", 0), "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0), "cost_usd": u.get("cost_usd"),
            "cost_note": u.get("cost_note")}


# -- D36: what a standard Live run has retrieved so far, drawn while it runs ------------------------------------------
EARLY_DATA_LABEL = ("**Retrieved data from the pinned snapshot**, drawn as the tools return it. This is not a validated "
                    "model answer and not a verified analytical result: the answer is still being written and checked.")
EARLY_DATA_FAILED = ("**Retrieved data from the pinned snapshot, before the run failed.** No answer was produced: this is "
                     "not an answer and not a verified analytical result.")
CHART_TOOLS = {"get_price_timeline": "price timeline", "get_actual_demand": "actual demand",
               "compare_forecast_actual": "forecast comparison"}


def _span(r: Any) -> tuple[datetime, datetime] | None:
    a = r.args or {}
    start, end = a.get("start_utc") or a.get("target_start_utc"), a.get("end_utc") or a.get("target_end_utc")
    return (parse_iso(start), parse_iso(end)) if start and end else None


def matches_request(r: Any, region: str | None, window: tuple[datetime, datetime] | None,
                    as_of: datetime | None) -> bool:
    """A chart tool's call for the resolved region and cutoff (none, or the same instant), over the resolved window or
    part of it. A call that failed validation has no arguments and matches nothing."""
    span = _span(r) if r.name in CHART_TOOLS else None
    cutoff = (r.args or {}).get("as_of_utc")
    return (span is not None and window is not None and (r.args or {}).get("region") == region
            and window[0] <= span[0] < span[1] <= window[1] and (parse_iso(cutoff) if cutoff else None) == as_of)


def early_chart_records(records: Any, region: str | None, window: tuple[datetime, datetime] | None,
                        as_of: datetime | None) -> list[Any]:
    """The tool results an early chart may draw (D36): successful chart-tool results that match the resolved request
    (``matches_request``). Anything else waits for the final page."""
    return [r for r in records if r.status == "ok" and matches_request(r, region, window, as_of)]


def early_chart_notes(records: Any, region: str | None, window: tuple[datetime, datetime] | None,
                      as_of: datetime | None) -> list[str]:
    """Partial coverage and data limitations of what the early charts draw, in the tools' own terms (D36):
    - how many intervals of the resolved window each drawn series holds, when not all, and how many a cutoff left out;
    - what the drawn results report missing;
    - a chart tool whose last call returned no data, or whose data is for another region, window or cutoff (not drawn).
    """
    if not region or window is None:
        return []
    used = early_chart_records(records, region, window, as_of)
    notes: list[str] = []

    def coverage(label: str, unit: str, minutes: int, ends: set[datetime], excluded: int) -> None:
        cov = aggregate_coverage(window, minutes, ends)
        if cov["intervals_included"] < cov["intervals_expected"] or excluded:
            notes.append(f"{label}: {cov['intervals_included']} of the {cov['intervals_expected']} {unit} of the "
                         "requested window are drawn" + (f"; {excluded} published after the cutoff are left out"
                                                          if excluded else "") + ".")

    price = next((r for r in used if r.name == "get_price_timeline"), None)  # the one series ``frames`` draws
    if price is not None:
        coverage("Price", "five-minute intervals", 5, {parse_iso(s["interval_end_utc"]) for s in price.data["series"]},
                 int(price.view.get("excluded_not_yet_available_at_as_of") or 0))
    demand = [r for r in used if r.name == "get_actual_demand"]
    if demand:
        coverage("Actual demand", "half-hours", 30,
                 {parse_iso(s["interval_end_utc"]) for r in demand for s in r.data["series"]},
                 sum(int(r.view.get("excluded_not_yet_available_at_as_of") or 0) for r in demand))
    drawn_fc = [r for r in used if r.name == "compare_forecast_actual"
                and (r.args or {}).get("run_selector") in ("latest_before_target", "latest_available_as_of")]
    if drawn_fc:
        ends = {parse_iso(p["target_end_utc"]) for r in drawn_fc for p in r.data.get("pairs", [])}
        cov = aggregate_coverage(window, 30, ends)
        if cov["intervals_included"] < cov["intervals_expected"]:
            notes.append(f"AEMO forecast: {cov['intervals_included']} of the {cov['intervals_expected']} half-hours of "
                         "the requested window have a forecast/actual pair; the forecast line covers those only.")
    for r in used:
        notes += [f"{CHART_TOOLS[r.name].capitalize()}: {m}" for m in r.missing[:3]]
    for name, label in CHART_TOOLS.items():
        tried = [r for r in records if r.name == name]
        if not tried or any(u is r for u in used for r in tried):
            continue
        last = tried[-1]
        if last.status != "ok":
            why = (last.missing[0] if last.missing else last.blocked_reason or "").strip()
            notes.append(f"{label.capitalize()}: no data drawn; its last call returned {last.status}"
                         + (f" ({why[:160]})" if why else "") + ".")
        elif name != "compare_forecast_actual":  # a named run's comparison is never drawn as the forecast line
            notes.append(f"{label.capitalize()}: retrieved for another region, window or cutoff than the request, so "
                         "not drawn here.")
    return list(dict.fromkeys(notes))
