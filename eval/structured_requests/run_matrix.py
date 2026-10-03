"""Run the I-18 paraphrase matrix three ways, offline (no model call, no key, no ledger entry).

Each case's question and request fields go through the Live routing path (``live.checked_route``,
``service.resolve_routed``) with a routing decision from ``fields.json``, written independently from the routing
instructions (prompts v12) without access to the code:
- **(a) absent:** the decision without its ``requested`` field, as in every route recorded before prompts v12;
- **(b) correct:** the decision as written;
- **(c) adversarial:** the decision with its ``requested`` field mutated: unquoted words, shifted times, a flipped
  start or end, a swapped measure, window or rule, and requests invented for questions that make none.

Each run is scored against the matrix's expected resolution. Containment and supply are counted separately; a
clarification is never counted as supplied:
- **WRONG:** a binding that differs from the expected one, or a binding where none is expected (fails every mode);
- **SUPPLIED:** bound exactly as expected (with the conflict note when one is expected);
- **CONTAINED:** sent back although a binding was expected (containment holds, supply lost);
- **CLARIFIED:** sent back, as expected;
- **OVER_CLARIFIED:** sent back although no request was made;
- **UNBOUND, NOTE_MISSING, AS_OF_WRONG:** proceeded without the expected binding, note or cutoff (fail);
- **AS_OF_OK, NO_REQUEST_OK:** as expected.

Pass rules (docs/issue-tracker.md, I-18 acceptance 1): (a) and (c) pass when no case is WRONG, UNBOUND, NOTE_MISSING
or AS_OF_WRONG; (b) passes when, in addition, every expected binding is SUPPLIED.

Usage: python eval/structured_requests/run_matrix.py OUT.json
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nem_agent.agent.live import RouteDecision, checked_route
from nem_agent.agent.request import InvestigateRequest
from nem_agent.selection import load_selection
from nem_agent.service import resolve_routed
from nem_agent.timeutil import iso_utc, parse_iso

HERE = Path(__file__).resolve().parent
KIND = {"whole_local_day": "day", "event": "event", "explicit": "explicit"}
MEASURE = {"dispatch_total_demand": "total demand", "operational_demand": "operational demand"}
BOUND = ("bound", "bound_with_conflict_note")
FAILING = {"WRONG", "UNBOUND", "NOTE_MISSING", "AS_OF_WRONG"}


def _t(s: str | None) -> datetime | None:
    return parse_iso(s) if s else None


def _near(a: datetime | None, b: datetime | None, seconds: int = 60) -> bool:
    return a is not None and b is not None and abs(a - b) <= timedelta(seconds=seconds)


def score(case: dict[str, Any], res: Any) -> tuple[str, str]:
    exp = case["expected"]
    out = exp["outcome"]
    rq = res.requests
    fr, mx = (rq.forecast_run, rq.maximum) if rq is not None else (None, None)
    want_run = exp.get("forecast_run") if case["path"] == "forecast_run" and out in BOUND else None
    want_max = exp.get("maximum") if case["path"] == "demand_max" and out in BOUND else None
    detail = []
    run_ok = max_ok = None
    if fr is not None and fr.status == "bound":
        run_ok = bool(want_run) and fr.selection == want_run.get("selection") and (
            not want_run.get("target_half_hour_end_utc") or (fr.half_hour is not None and
                                                              fr.half_hour[1] == _t(want_run["target_half_hour_end_utc"])))
        if want_run and want_run.get("issued_at_utc"):
            run_ok = run_ok and _near(fr.issued_at, _t(want_run["issued_at_utc"]))
        detail.append(f"run {fr.selection} {fr.as_dict()['half_hour_utc']} {fr.as_dict()['issued_at_utc']}")
    if mx is not None and mx.status == "bound":
        max_ok = bool(want_max) and mx.measures == [MEASURE.get(want_max.get("measure"), "?")] and \
            mx.window_kind == KIND.get(want_max.get("window_kind"), "?") and mx.window is not None and \
            [iso_utc(t) for t in mx.window] == [iso_utc(parse_iso(t)) for t in want_max.get("window_utc") or []]
        detail.append(f"max {mx.measures} {mx.window_kind} {mx.as_dict()['window_utc']}")
    if run_ok is False or max_ok is False:
        return "WRONG", "; ".join(detail)
    if res.status != "ok":
        why = (" | ".join(res.reasons))[:160]
        return {"clarify": "CLARIFIED", "no_request": "OVER_CLARIFIED"}.get(out, "CONTAINED"), why
    as_of_ok = (exp.get("as_of_utc") is None and res.as_of is None) or _near(res.as_of, _t(exp.get("as_of_utc")))
    if out in BOUND:
        if (want_run and not run_ok) or (want_max and not max_ok):
            return "UNBOUND", f"run {fr and fr.status} {fr and fr.missing}; max {mx and mx.status} {mx and mx.missing}"
        if want_run and not as_of_ok:
            return "AS_OF_WRONG", f"as_of {res.as_of}"
        if out == "bound_with_conflict_note" and not (rq and rq.notes):
            return "NOTE_MISSING", "; ".join(detail)
        if out == "bound_with_conflict_note" and case["path"] == "forecast_run" and not as_of_ok:
            return "AS_OF_WRONG", f"as_of {res.as_of}"
        return "SUPPLIED", "; ".join(detail)
    if out == "clarify":
        return "UNBOUND", f"run {fr and fr.status}; max {mx and mx.status}"
    if out == "as_of_availability":
        return ("AS_OF_OK" if as_of_ok else "AS_OF_WRONG"), f"run {fr and fr.status} as_of {res.as_of}"
    return "NO_REQUEST_OK", ""


def _shift(s: str | None, minutes: int) -> str | None:
    return iso_utc(parse_iso(s) + timedelta(minutes=minutes)) if s else None


def mutations(route: dict[str, Any], question: str) -> dict[str, dict[str, Any]]:
    """Adversarial variants of a routing decision's ``requested`` field."""
    req = route["requested"]
    fr, mx = req["forecast_run"], req["maximum"]
    out: dict[str, dict[str, Any]] = {}

    def variant(name: str, f: Any) -> None:
        r = copy.deepcopy(route)
        f(r["requested"]["forecast_run"], r["requested"]["maximum"])
        if r != route:
            out[name] = r

    def unquote(a: dict[str, Any], b: dict[str, Any]) -> None:
        for d in (a, b):
            for k in [k for k in d if k.endswith("_text") and d[k]]:
                d[k] = f"{d[k]} (as the analyst meant it)"
    variant("unquoted_words", unquote)
    variant("time_plus_30", lambda a, b: a.update(target_half_hour_end_utc=_shift(a["target_half_hour_end_utc"], 30),
                                                  issued_at_utc=_shift(a["issued_at_utc"], 120))
            or b.update(window_start_utc=_shift(b["window_start_utc"], 60), window_end_utc=_shift(b["window_end_utc"], 60)))
    variant("start_end_flipped", lambda a, b: a.update(target_half_hour_end_utc=_shift(a["target_half_hour_end_utc"], -30)))
    variant("measure_swapped", lambda a, b: b.update(measure={"dispatch_total_demand": "operational_demand",
                                                              "operational_demand": "dispatch_total_demand"}
                                                     .get(b["measure"], b["measure"])))
    variant("window_swapped", lambda a, b: b.update(window={"whole_local_day": "event", "event": "whole_local_day",
                                                            "explicit": "whole_local_day"}.get(b["window"], b["window"])))
    variant("rule_swapped", lambda a, b: a.update(
        selection={"last_issued_before": "issued_at", "issued_at": "last_issued_before"}.get(a["selection"], a["selection"]),
        issued_at_utc=a["issued_at_utc"] or _shift(a["target_half_hour_end_utc"], -90)))
    if fr["selection"] == "none":  # a run request invented, citing the whole question
        variant("run_invented", lambda a, b: a.update(selection="last_issued_before", selection_text=question,
                                                      half_hour_text=question,
                                                      target_half_hour_end_utc="2026-07-30T08:00:00Z"))
    if mx["kind"] == "none":  # a maximum request invented, citing the whole question
        variant("maximum_invented", lambda a, b: b.update(kind="maximum", measure="dispatch_total_demand",
                                                          measure_text=question, window="whole_local_day",
                                                          window_text=question))
    return out


def run() -> dict[str, Any]:
    """Every case three ways: the rows and the summary per mode."""
    matrix = json.loads((HERE / "matrix.json").read_text())
    fields = {c["id"]: c["route"] for c in json.loads((HERE / "fields.json").read_text())["cases"]}
    sel = load_selection()
    rows: list[dict[str, Any]] = []
    for case in matrix["cases"]:
        req = InvestigateRequest(question=case["question"], mode="live", **(case.get("request") or {}))
        route = fields[case["id"]]
        runs = {"a_absent": {**route, "requested": None}, "b_correct": route}
        runs |= {f"c_{k}": v for k, v in mutations(route, case["question"]).items()}
        for mode, r in runs.items():
            res = resolve_routed(req, checked_route(RouteDecision.model_validate(r)), sel)
            verdict, why = score(case, res)
            rows.append({"id": case["id"], "path": case["path"], "expected": case["expected"]["outcome"],
                         "mode": mode, "verdict": verdict, "detail": why,
                         "requests": res.requests.as_dict() if res.requests is not None else None})
    summary: dict[str, Any] = {}
    for mode in ("a", "b", "c"):
        rs = [r for r in rows if r["mode"].startswith(mode)]
        counts: dict[str, int] = {}
        for r in rs:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        failing = sorted({f"{r['id']}:{r['mode']}:{r['verdict']}" for r in rs if r["verdict"] in FAILING})
        if mode == "b":
            failing += sorted(f"{r['id']}:{r['mode']}:{r['verdict']}" for r in rs
                              if r["expected"] in BOUND and r["verdict"] != "SUPPLIED" and r["verdict"] not in FAILING)
        summary[mode] = {"runs": len(rs), "counts": dict(sorted(counts.items())), "failing": failing,
                         "passes": not failing}
    expected_bound = sum(c["expected"]["outcome"] in BOUND for c in matrix["cases"])
    for mode in ("a", "b"):
        rs = [r for r in rows if r["mode"].startswith(mode)]
        summary[mode]["supplied_of_expected_bound"] = f"{sum(r['verdict'] == 'SUPPLIED' for r in rs)}/{expected_bound}"
    return {"matrix_sha256": hashlib.sha256((HERE / "matrix.json").read_bytes()).hexdigest(),
            "fields_sha256": hashlib.sha256((HERE / "fields.json").read_bytes()).hexdigest(),
            "summary": summary, "rows": rows}


def main() -> int:
    out = run()
    summary = out["summary"]
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str) + "\n")
    for mode, s in summary.items():
        print(mode, "passes" if s["passes"] else "FAILS", s["counts"], s.get("supplied_of_expected_bound", ""))
        for f in s["failing"]:
            print("   ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
