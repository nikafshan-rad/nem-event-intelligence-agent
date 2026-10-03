"""Score the Live check of the v12 routing extraction (PASS_RULE.md) from the saved records, offline. It never calls a
model.

- **Routing cases (R-dev, R-fresh):** each record's outcome label, mechanically, against the verified gold
  (`DEV_GOLD.json`, `cases.json`): CORRECT, WRONG, PARTIAL, SENT_BACK, UNBOUND, NO_REQUEST_OK or AS_OF_OK, and whether
  the routing call was ROUTE_INVALID (cut off or invalid output). Supply and containment are counted apart.
- **End-to-end cases (E-dev):** the automatic fields and the review sheet of the targeted check, reused unchanged
  (`eval/livecheck_i15_17/score.py`): H1–H5, status, repair, fallback, blocked flag, and the manual outcome S, U, C, F
  or X.
- **Review sheet** (`--sheet`): every routing label with its record and gold, for the developer and the independent
  reviewer to confirm or dispute; and the E-dev sheet.
- **Decision** (`--review`, given twice): the verdict by PASS_RULE.md, taking the stricter reading wherever two differ.

Usage:
    python eval/livecheck_routing_v12/score.py --sheet SHEET.json
    python eval/livecheck_routing_v12/score.py --review DEVELOPER.json --review REVIEWER.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("lc_i15_17_score", REPO / "eval" / "livecheck_i15_17" / "score.py")
assert _spec and _spec.loader
LC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LC)

MEASURE = {"dispatch_total_demand": "total demand", "operational_demand": "operational demand"}
KIND = {"whole_local_day": "day", "event": "event", "explicit": "explicit"}
DATA_INTENTS = ("market_event_review", "forecast_review")
PASSES = {"bound": "CORRECT", "clarify": "SENT_BACK", "no_request": "NO_REQUEST_OK", "as_of_availability": "AS_OF_OK"}
# R-dev's gated cases (PASS_RULE.md, "Acceptance criteria")
DEV_TARGET = ("K05", "K06", "K07", "K09", "K10")
DEV_REGRESSION = ("Z04", "Z05", "K11")
DEV_CLARIFY = ("K08", "K12")
DEV_NO_REQUEST = ("K01", "K02", "K03", "K04", "K13", "K15", "Z03")
FRESH_RUN = tuple(f"Q{i:02d}" for i in range(1, 9))
FRESH_MAX = tuple(f"Q{i:02d}" for i in range(9, 17))
FRESH_CLARIFY = ("Q17", "Q18", "Q19", "Q20")
FRESH_CONTROLS = ("Q21", "Q22", "Q23", "Q24")
E_SUPPLY = ("K05", "K06", "K09", "K10")
E_UNAVAILABLE = ("K07",)


def _t(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _near(a: str | None, b: str | None, seconds: int = 60) -> bool:
    ta, tb = _t(a), _t(b)
    return ta is not None and tb is not None and abs((ta - tb).total_seconds()) <= seconds


Query = Any  # (sql, params) -> list of row dicts, as `Store.query`


def _store_query() -> Query:
    from nem_agent.service import _shared

    return _shared()[0].query


def _dt(s: str) -> datetime:
    t = _t(s)
    assert t is not None
    return t


def run_identity(region: str | None, selection: str | None, target_end: str | None, issued_at: str | None,
                 query: Query | None = None) -> str | None:
    """The stored forecast run a run request identifies, by the controller's own lookups (`LiveController.
    _requested_run` and `_run_issued_at`), before any availability filter (an as-of cutoff is scored on its own):
    - **the last run issued before the half-hour:** the run issued last before the half-hour ending ``target_end``
      starts, among the runs that forecast it; two runs with that same issue time identify none;
    - **the run issued at a stated time:** the run issued nearest ``issued_at``, within 10 minutes; two equally near
      identify none. When a half-hour is bound too, the run must forecast it.
    None when no single stored run is identified."""
    q = query or _store_query()
    if not region:
        return None
    if selection == "last_issued_before" and target_end:
        end = _dt(target_end)
        rows = q("SELECT run_id, MIN(issued_at_utc) AS issued_at_utc FROM opdemand_forecast WHERE region=? AND "
                 "target_end_utc=? AND issued_at_utc < ? GROUP BY run_id ORDER BY issued_at_utc DESC LIMIT 2",
                 [region, end, end - timedelta(minutes=30)])
        if not rows or (len(rows) > 1 and rows[1]["issued_at_utc"] == rows[0]["issued_at_utc"]):
            return None
        return str(rows[0]["run_id"])
    if selection == "issued_at" and issued_at:
        t = _dt(issued_at)
        rows = q("SELECT run_id, MIN(issued_at_utc) AS issued_at_utc FROM opdemand_forecast WHERE region=? AND "
                 "issued_at_utc BETWEEN ? AND ? GROUP BY run_id",
                 [region, t - timedelta(minutes=10), t + timedelta(minutes=10)])
        if not rows:
            return None
        best = min(rows, key=lambda r: abs(r["issued_at_utc"] - t))
        if sum(abs(r["issued_at_utc"] - t) == abs(best["issued_at_utc"] - t) for r in rows) > 1:
            return None
        if target_end and not q("SELECT 1 FROM opdemand_forecast WHERE region=? AND run_id=? AND target_end_utc=? "
                                "LIMIT 1", [region, best["run_id"], _dt(target_end)]):
            return None
        return str(best["run_id"])
    return None


def route_label(exp: dict[str, Any], rec: dict[str, Any], query: Query | None = None) -> dict[str, Any]:
    """One routing case's outcome label (PASS_RULE.md, "Correct binding"), with what decided it.

    A bound run is correct only if it is the gold run itself: the stored run its bound fields identify
    (``run_identity``) must be the run the gold's fields identify. The 60-second tolerance applies only to comparing
    the issue-time value (a question may state the time to the minute, while the stored stamps carry seconds); a
    different run fails, however near its issue time."""
    res = rec.get("resolution") or {}
    rq = res.get("requests") or {}
    fr, mx = rq.get("forecast_run") or {}, rq.get("maximum") or {}
    out = exp["outcome"]
    g_run = exp.get("forecast_run") if out == "bound" else None
    g_max = exp.get("maximum") if out == "bound" else None
    wrong: list[str] = []
    partial: list[str] = []
    if fr.get("status") == "bound":
        if not g_run:
            wrong.append("a forecast run is bound; the gold has none")
        else:
            if fr.get("selection") != g_run["selection"]:
                wrong.append(f"rule {fr.get('selection')} (gold {g_run['selection']})")
            hh = fr.get("half_hour_utc")
            if g_run.get("target_half_hour_end_utc"):
                if not hh:
                    partial.append("the target half-hour is not bound")
                elif not _near(hh[1], g_run["target_half_hour_end_utc"], 0):
                    wrong.append(f"target end {hh[1]} (gold {g_run['target_half_hour_end_utc']})")
            if g_run.get("issued_at_utc"):
                if not fr.get("issued_at_utc"):
                    partial.append("the issue time is not bound")
                elif not _near(fr["issued_at_utc"], g_run["issued_at_utc"]):
                    wrong.append(f"issue time {fr['issued_at_utc']} (gold {g_run['issued_at_utc']})")
            if not wrong:  # the run itself: the stored run the bound fields identify must be the gold run
                gold_run = run_identity(exp.get("region"), g_run["selection"], g_run.get("target_half_hour_end_utc"),
                                        g_run.get("issued_at_utc"), query)
                if gold_run is None:
                    raise ValueError(f"the gold identifies no single stored run: {g_run}")
                bound_run = run_identity(res.get("region"), fr.get("selection"), (hh or [None, None])[1],
                                         fr.get("issued_at_utc"), query)
                if bound_run is not None and bound_run != gold_run:
                    wrong.append(f"run {bound_run} (gold {gold_run})")
                elif bound_run is None and not partial:
                    wrong.append(f"the bound fields identify no single stored run (gold {gold_run})")
    if mx.get("status") == "bound":
        if not g_max:
            wrong.append("a maximum is bound; the gold has none")
        else:
            if mx.get("measures") != [MEASURE[g_max["measure"]]]:
                wrong.append(f"measure {mx.get('measures')} (gold {g_max['measure']})")
            if mx.get("window_kind") != KIND[g_max["window_kind"]]:
                wrong.append(f"window kind {mx.get('window_kind')} (gold {g_max['window_kind']})")
            w, gw = mx.get("window_utc") or [], g_max.get("window_utc") or []
            if len(w) != 2 or len(gw) != 2 or not (_near(w[0], gw[0], 0) and _near(w[1], gw[1], 0)):
                wrong.append(f"window {w} (gold {gw})")
    proceeds = res.get("status") == "ok"
    if proceeds and res.get("intent") in DATA_INTENTS:
        if exp.get("region") and res.get("region") != exp["region"]:
            wrong.append(f"region {res.get('region')} (gold {exp['region']})")
        a, g = res.get("as_of_utc"), exp.get("as_of_utc")
        if (a or g) and not _near(a, g):
            wrong.append(f"as-of cutoff {a} (gold {g})")
    invalid = bool(rec.get("route_invalid"))
    if wrong:
        label = "WRONG"
    elif not proceeds:
        label = "SENT_BACK"
    elif out == "bound":
        missing = (g_run and fr.get("status") != "bound") or (g_max and mx.get("status") != "bound")
        label = "UNBOUND" if missing else "PARTIAL" if partial else "CORRECT"
    elif out == "clarify":
        label = "UNBOUND"  # proceeded with nothing bound where it should have been sent back
    else:
        label = "AS_OF_OK" if out == "as_of_availability" else "NO_REQUEST_OK"
    return {"label": label, "passes": label == PASSES[out], "route_invalid": invalid, "wrong": wrong,
            "partial": partial, "gold_outcome": out,
            "supply_miss": (out == "bound" and label in ("SENT_BACK", "UNBOUND", "PARTIAL"))
            or (out in ("no_request", "as_of_availability") and label == "SENT_BACK"),
            "containment_miss": out == "clarify" and label == "UNBOUND"}


def gold_of(run: str, freeze: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if run == "R-dev":
        return {c["case_id"]: c["expected"] for c in json.loads((HERE / "DEV_GOLD.json").read_text())["cases"]}
    return {c["case_id"]: c["expected"] for c in json.loads((HERE / "cases.json").read_text())["cases"]}


def score_routing(ids: list[str], gold: dict[str, dict[str, Any]], out: Path) -> dict[str, Any]:
    """The labels for the cases the run log records as saved; the rest are incomplete."""
    ended = {e["case"]: e for e in LC.read_log(out) if e.get("event") == "case_end"}
    rows, incomplete = {}, []
    for cid in ids:
        rec_p = out / f"{cid}.json"
        if ended.get(cid, {}).get("outcome") != "saved" or not rec_p.exists():
            incomplete.append(cid)
            continue
        rec = json.loads(rec_p.read_text())
        rows[cid] = route_label(gold[cid], rec) | {
            "H1": int((rec.get("score") or {}).get("case_note_files_written") or 0)
            + int((rec.get("score") or {}).get("forbidden_calls") or 0),
            "route_call": rec.get("route_call"), "cost_usd": (rec.get("score") or {}).get("ledger_cost_usd")}
    return {"complete": not incomplete, "incomplete": incomplete, "cases": rows}


def stricter(auto: dict[str, Any], readings: list[dict[str, Any]]) -> dict[str, Any]:
    """A routing case's label after review: the automatic label, unless a reviewer's label is stricter (a miss over a
    pass; WRONG over any other miss)."""
    labels = [auto["label"]] + [r["label"] for r in readings if r.get("label")]
    gold = auto["gold_outcome"]
    rank = {lab: (2 if lab == "WRONG" else 0 if lab == PASSES[gold] else 1) for lab in labels}
    worst = max(labels, key=lambda lab: rank[lab])
    return auto | {"label": worst, "passes": worst == PASSES[gold], "disagreement": len(set(labels)) > 1}


def decide(freeze: dict[str, Any], routing: dict[str, dict[str, Any]], e2e_auto: dict[str, Any],
           e2e_readings: dict[str, dict[str, Any]], route_readings: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The verdict by PASS_RULE.md, in its order:
    1. FAIL if any completed routing case is WRONG, more than 1 of the 42 routing calls is ROUTE_INVALID, or any
       completed E-dev case has an H1–H5 violation (regardless of X) or X;
    2. INCOMPLETE if any case did not complete (or an E-dev case is not yet reviewed);
    3. PASS if every criterion is met, else FAIL."""
    labels: dict[str, dict[str, Any]] = {}
    incomplete: list[str] = []
    for run in ("R-dev", "R-fresh"):
        incomplete += [f"{run}:{c}" for c in routing[run]["incomplete"]]
        for cid, row in routing[run]["cases"].items():
            labels[f"{run}:{cid}"] = stricter(row, route_readings.get(f"{run}:{cid}", []))
    e_rows: dict[str, dict[str, Any]] = {}
    for c in [c for c, _ in freeze["runs"]["E-dev"]["cases"]]:
        a = e2e_auto["cases"].get(c)
        if a is None:
            incomplete.append(f"E-dev:{c}")
            continue
        r = e2e_readings.get(c) or {"outcome": None, "H2_manual": 0, "H4_manual": 0}
        e_rows[c] = {"outcome": r["outcome"], "blocked": a["blocked"],
                     "H": {"H1": a["H1"], "H2": a["H2_auto"] + r["H2_manual"], "H3": a["H3"],
                           "H4": a["H4_auto"] + r["H4_manual"], "H5": a["H5"]}}
    invalid = sorted(k for k, v in labels.items() if v["route_invalid"])
    failures = [f"{k}: WRONG ({'; '.join(v['wrong']) or 'by review'})" for k, v in labels.items() if v["label"] == "WRONG"]
    failures += [f"{k}: H1" for k, v in labels.items() if v.get("H1")]
    if len(invalid) > 1:
        failures.append(f"{len(invalid)} routing calls ROUTE_INVALID (at most 1 allowed): {', '.join(invalid)}")
    failures += [f"E-dev:{c}: {h}" for c, r in e_rows.items() for h in LC.H if r["H"][h]]
    failures += [f"E-dev:{c}: incorrect targeted answer shown (X)" for c, r in e_rows.items() if r["outcome"] == "X"]
    unreviewed = [f"E-dev:{c}" for c, r in e_rows.items() if r["outcome"] is None]

    def passed(run: str, ids: tuple[str, ...]) -> list[bool]:
        return [labels.get(f"{run}:{c}", {}).get("passes", False) for c in ids]

    def count(run: str, ids: tuple[str, ...], label: str) -> int:
        return sum(labels.get(f"{run}:{c}", {}).get("label") == label for c in ids)

    criteria = {
        "fresh_forecast_run_correct": [sum(passed("R-fresh", FRESH_RUN)), 6, len(FRESH_RUN)],
        "fresh_demand_max_correct": [sum(passed("R-fresh", FRESH_MAX)), 6, len(FRESH_MAX)],
        "fresh_clarify_sent_back": [sum(passed("R-fresh", FRESH_CLARIFY)), 4, len(FRESH_CLARIFY)],
        "fresh_controls_over_clarified": [count("R-fresh", FRESH_CONTROLS, "SENT_BACK"), 1, len(FRESH_CONTROLS)],
        "dev_target_correct": [sum(passed("R-dev", DEV_TARGET)), 5, len(DEV_TARGET)],
        "dev_regression_correct": [sum(passed("R-dev", DEV_REGRESSION)), 3, len(DEV_REGRESSION)],
        "dev_clarify_sent_back": [sum(passed("R-dev", DEV_CLARIFY)), 2, len(DEV_CLARIFY)],
        "dev_no_request_over_clarified": [count("R-dev", DEV_NO_REQUEST, "SENT_BACK"), 1, len(DEV_NO_REQUEST)],
        "e2e_supplied": [sum(e_rows.get(c, {}).get("outcome") == "S" for c in E_SUPPLY), 4, len(E_SUPPLY)],
        "e2e_unavailable": [sum(e_rows.get(c, {}).get("outcome") == "U" for c in E_UNAVAILABLE), 1, len(E_UNAVAILABLE)],
    }
    at_most = {"fresh_controls_over_clarified", "dev_no_request_over_clarified"}
    met = all((n <= bar) if k in at_most else (n >= bar) for k, (n, bar, _) in criteria.items())
    if failures:
        verdict = "FAIL"
    elif incomplete or unreviewed:
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS" if met else "FAIL"
    report = {}
    for run in ("R-dev", "R-fresh"):
        rows = {k.split(":", 1)[1]: v for k, v in labels.items() if k.startswith(run + ":")}
        report[run] = {"labels": {c: v["label"] for c, v in rows.items()},
                       "supply_misses": sorted(c for c, v in rows.items() if v["supply_miss"]),
                       "containment_misses": sorted(c for c, v in rows.items() if v["containment_miss"]),
                       "route_invalid": sorted(c for c, v in rows.items() if v["route_invalid"])}
    report["E-dev"] = {c: r["outcome"] for c, r in e_rows.items()}
    return {"verdict": verdict, "failures": failures, "incomplete": incomplete, "unreviewed": unreviewed,
            "criteria": criteria, "runs": report, "e2e": e_rows,
            "disagreements": sorted(k for k, v in labels.items() if v.get("disagreement"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", help="write the review sheet to this file")
    ap.add_argument("--review", action="append", default=[], help="a filled review sheet (give two)")
    args = ap.parse_args()
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    live = REPO / "artifacts" / "live"
    routing = {run: score_routing([c for c, _ in freeze["runs"][run]["cases"]], gold_of(run, freeze),
                                  live / freeze["runs"][run]["label"]) for run in ("R-dev", "R-fresh")}
    e_cases = LC.load_plan(freeze["runs"]["E-dev"]["cases"])
    e_out = live / freeze["runs"]["E-dev"]["label"]
    e_auto = LC.score_run(e_cases, e_out)
    if args.sheet:
        rows = [{"run": run, "case_id": cid, "automatic": row, "fill": {"label": None, "note": ""}}
                for run in routing for cid, row in routing[run]["cases"].items()]
        Path(args.sheet).write_text(json.dumps({"reviewer": "", "routing": rows,
                                                "e2e": LC.sheet(e_cases, e_out, e_auto)}, indent=1) + "\n")
    e_readings: dict[str, dict[str, Any]] = {}
    route_readings: dict[str, list[dict[str, Any]]] = {}
    if args.review:
        sheets = [json.loads(Path(p).read_text()) for p in args.review]
        filled = [{r["case_id"]: r["fill"] for r in s["e2e"]} for s in sheets]
        for cid in set().union(*filled):
            e_readings[cid] = LC.merge([f[cid] for f in filled if cid in f])
        for s in sheets:
            for r in s["routing"]:
                route_readings.setdefault(f"{r['run']}:{r['case_id']}", []).append(r["fill"])
    print(json.dumps(decide(freeze, routing, e_auto, e_readings, route_readings), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
