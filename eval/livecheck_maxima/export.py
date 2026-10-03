"""The full-report exporter of the Live acceptance check of computed demand maxima (PROTOCOL.md, "The exporter"), and
the automatic checks of a saved record (criteria 2-6). Offline: it calls no model.

The frozen exporters (`scripts/live_diagnose.py`, `eval/livecheck_i15_17/run_case.py`) keep a fixed set of report
fields without `schema_version` or `answer`. This one saves the whole report as the API returns it
(`model_dump(mode="json")`), with:
- the display record the app derives from it: `result_provenance`, `report_format` and `summary_v1`;
- the run's own records: routing decision, tool records, model calls and drafts.

It is never used by the frozen checks, and they are not changed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from nem_agent.report import InvestigationReport, report_format, summary_v1  # noqa: E402
from nem_agent.results import verify_loaded  # noqa: E402
from nem_agent.ui_data import result_provenance  # noqa: E402

EXPORTER = "eval/livecheck_maxima/export.py/1"
EXPECTED_KEYS = ("intent", "status_in", "required_tools", "expected_outcome", "answerable")
INTERP_OK = {False: ("validated", "absent"), True: ("withheld",)}  # Live, by fallback_applied (criterion 4)


# ------------------------------------------------------------------------------------------------ the record
def record(case: dict[str, Any], row: dict[str, Any], result: Any, *, notes_written: int,
           ledger_cost: float | None) -> dict[str, Any]:
    """One case's full record: the report as the API returns it, the display record, the score fields and the run's
    own records. ``result`` is the ``InvestigationResult`` (``run_system_case``'s ``keep["result"]``)."""
    rep = result.report.model_dump(mode="json")
    tr = result.trace.as_dict()
    ev = tr["events"]
    outputs = {e.get("call_id"): e for e in ev if e["kind"] == "tool_output"}
    score = dict(row) | {"case_note_files_written": notes_written, "ledger_cost_usd": ledger_cost}
    return {
        "exporter": EXPORTER, "case_id": case["case_id"], "question": case["question"],
        "request": case.get("request", {}),
        "expected": {k: case["expected"].get(k) for k in EXPECTED_KEYS},
        "score": score,
        "report": rep,
        "display": {"result_provenance": result_provenance(rep, result.usage), "report_format": report_format(rep),
                    "summary_v1": summary_v1(rep)},
        "route": next((e.get("decision") for e in ev if e["name"] == "model_decision"), None),
        "tools": [{"name": r.name, "call_id": r.call_id, "origin": getattr(r, "origin", None), "status": r.status,
                   "args": r.args or r.raw_args, "blocked_reason": r.blocked_reason, "policy_notes": r.policy_notes,
                   "source_ids": list(r.source_row_ids), "output_excerpt": (outputs.get(r.call_id) or {}).get(
                       "output", "")[:2000]} for r in result.records],
        "model_calls": [{k: e.get(k) for k in ("name", "duration_ms", "cost_usd", "status", "incomplete")}
                        | {"usage": e.get("usage"), "function_calls": [c["name"] for c in e.get("function_calls") or []]}
                        for e in ev if e["kind"] == "model" and e.get("usage")],
        "drafts": {e["name"]: e.get("report") for e in ev if e["name"].endswith(":draft")},
        "trace_id": tr["trace_id"],
    }


# ------------------------------------------------------------------------------------------------ the checks
def _report(rec: dict[str, Any]) -> dict[str, Any]:
    return dict(rec.get("report") or {})


def format_problems(rec: dict[str, Any]) -> list[str]:
    """Criterion 4: format and separation."""
    rep = _report(rec)
    answer, results = rep.get("answer") or [], rep.get("results") or []
    v = rep.get("validation") or {}
    out = []
    if answer or results:
        if rep.get("schema_version") != "2":
            out.append(f"a computed answer with schema_version {rep.get('schema_version')!r}, not '2'")
        a_ids = sorted(a["result_id"] for a in answer)
        r_ids = sorted(r["result"]["result_id"] for r in results)
        if a_ids != r_ids:
            out.append(f"answer items {a_ids} are not one per reported result {r_ids}")
        shown = [str(s) for s in rep.get("summary") or []] + [str(rep.get("headline") or "")]
        for a in answer:
            if any(a["statement"] in s for s in shown):
                out.append(f"answer statement {a['result_id'][:12]} is repeated in summary or headline")
        fb = bool(v.get("fallback_applied"))
        interp = str(v.get("interpretation") or "")
        ok = INTERP_OK[fb] if rep.get("mode") == "live" else ("scripted",)  # Replay (offline dry runs) is scripted
        if not interp.startswith(ok):
            out.append(f"interpretation {interp!r} is not consistent with fallback_applied={fb}")
    else:
        if rep.get("schema_version") != "1":
            out.append(f"no computed answer, but schema_version {rep.get('schema_version')!r}")
    return out


def fallback_problems(rec: dict[str, Any]) -> list[str]:
    """Criterion 5 (the record's part): a fallback is labelled as one."""
    rep = _report(rec)
    v = rep.get("validation") or {}
    if not v.get("fallback_applied"):
        return []
    out = []
    if rep.get("answer") and not str(v.get("interpretation", "")).startswith("withheld"):
        out.append(f"a fallback with interpretation {v.get('interpretation')!r}")
    kind = ((rec.get("display") or {}).get("result_provenance") or {}).get("kind")
    if kind != "live_fallback":
        out.append(f"a fallback displayed as {kind!r}")
    return out


def _value_forms(x: float) -> set[str]:
    return {f"{x}", f"{x:.0f}", f"{x:.1f}", f"{x:.2f}", f"{x:,.0f}", f"{x:,.1f}", f"{x:,.2f}"}


def admitted(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """The results the runtime verifier admitted and the answer rendered as verified."""
    rep = _report(rec)
    rendered = {a["result_id"]: a for a in rep.get("answer") or []}
    return [r["result"] for r in rep.get("results") or []
            if r["server_verification"]["outcome"] == "verified"
            and rendered.get(r["result"]["result_id"], {}).get("verification") == "verified"]


def unadmitted_problems(rec: dict[str, Any]) -> tuple[list[str], int]:
    """Criterion 3 (the answer's part): a result the verifier did not admit renders with no value. Returns the problems
    and the number of unadmitted results (each one is reported as an anomaly)."""
    rep = _report(rec)
    rendered = {a["result_id"]: a for a in rep.get("answer") or []}
    out, n = [], 0
    for r in rep.get("results") or []:
        res, outcome = r["result"], r["server_verification"]["outcome"]
        a = rendered.get(res["result_id"])
        if outcome == "verified":
            if a is not None and a["status"] != res["status"]:
                out.append(f"an admitted {res['status']} result rendered as {a['status']}")
            continue
        n += 1
        if a is None:
            continue  # counted by criterion 4 (one item per result)
        if a["status"] != "not_verified" or a["verification"] not in ("failed", "unverifiable"):
            out.append(f"an unadmitted result rendered as {a['status']} ({a['verification']})")
        if a.get("limitations") or a.get("source_row_ids"):
            out.append("an unadmitted result rendered with limitations or source rows")
        for x in (res.get("maximum"), res.get("highest_held")):
            if x is not None and any(f in a["statement"] for f in _value_forms(float(x))):
                out.append(f"an unadmitted result's value {x} is in its statement")
    return out, n


def integrity_problems(rec: dict[str, Any], trace: dict[str, Any] | None, *, store: Any,
                       selection: Any = None) -> list[str]:
    """Criterion 6: export integrity (round trip, adapter, re-verification of admitted results, trace)."""
    rep = _report(rec)
    out = []
    for k in ("schema_version", "answer", "results", "validation"):
        if k not in rep:
            out.append(f"the saved report has no {k}")
    if (rep.get("answer") or rep.get("results")) and "interpretation" not in (rep.get("validation") or {}):
        out.append("the saved report has no validation.interpretation")
    try:
        again = InvestigationReport.model_validate(rep).model_dump(mode="json")
        if again != rep:
            out.append("the saved report does not round-trip: "
                       + ", ".join(sorted(k for k in set(again) | set(rep) if again.get(k) != rep.get(k))))
    except Exception as exc:  # any schema error is an integrity failure, not a crash of the scorer
        out.append(f"the saved report is not an InvestigationReport ({type(exc).__name__})")
    want = ([a["statement"] for a in rep.get("answer") or []] if rep.get("schema_version") == "2" else []) + list(
        rep.get("summary") or [])
    if summary_v1(rep) != want or (rec.get("display") or {}).get("summary_v1") != want:
        out.append("summary_v1 is not the answer statements followed by summary")
    for r in rep.get("results") or []:
        if r["server_verification"]["outcome"] == "verified":
            v = verify_loaded(r, store=store, selection=selection)
            if v.outcome != "verified":
                out.append(f"an admitted result does not re-verify on load: {v.outcome} {list(v.reasons)}")
    if trace is None:
        out.append("no trace saved")
        return out
    if trace.get("trace_id") != rep.get("trace_id") or rec.get("trace_id") != rep.get("trace_id"):
        out.append("the trace ID is not the report's")
    ev = trace.get("events") or []
    got = [(e.get("result_id"), e.get("status"), e.get("verification")) for e in ev if e.get("kind") == "result"]
    want_r = [(r["result"]["result_id"], r["result"]["status"], r["server_verification"]["outcome"])
              for r in rep.get("results") or []]
    if got != want_r:
        out.append(f"the trace's result events {got} do not match the results {want_r}")
    texts = [e.get("text") for e in ev if e.get("name") == "max_answer"]
    statements = [a["statement"] for a in rep.get("answer") or []]
    if statements and rep.get("mode") == "live" and (not texts or texts[-1] != statements):  # Live records it
        out.append("the trace's max_answer text is not the answer statements")
    return out


def result_problems(rec: dict[str, Any], gold_result: dict[str, Any] | None,
                    reading: dict[str, Any] | None) -> tuple[list[str], bool]:
    """Criterion 2: every admitted result matches the case's gold exactly. Returns the problems and whether the
    correct verified result was produced."""
    out, correct = [], False
    for r in admitted(rec):
        if gold_result is None or reading is None:
            out.append(f"an admitted {r['identity']['measure']} result in a case with no gold result")
            continue
        est = r["status"] == "established"
        got = {"status": r["status"], "value": r["maximum"] if est else r["highest_held"], "unit": r["unit"],
               "measure": r["identity"]["measure"], "region": r["identity"]["region"],
               "window_utc": list(r["identity"]["window_utc"] or []), "window_kind": r["identity"]["window_kind"],
               "cutoff_utc": r["identity"]["cutoff_utc"],
               "interval_ends_utc": list(r["interval_ends_utc"] if est else r["highest_held_interval_ends_utc"]),
               "interval_minutes": (r.get("coverage") or {}).get("interval_minutes"),
               "intervals_in_window": (r.get("coverage") or {}).get("intervals_in_window"),
               "intervals_held": (r.get("coverage") or {}).get("intervals_held"),
               "complete": (r.get("coverage") or {}).get("complete"),
               "excluded_rows_by_as_of": (r.get("coverage") or {}).get("excluded_by_as_of"),
               "source_row_ids": list(r["source_row_ids"])}
        want = {"status": gold_result["status"], "value": gold_result["value"], "unit": gold_result["unit"],
                "measure": reading["measure"], "region": reading["region"], "window_utc": list(reading["window_utc"]),
                "window_kind": reading["window_kind"], "cutoff_utc": reading["as_of_utc"],
                "interval_ends_utc": gold_result["interval_ends_utc"],
                "interval_minutes": 5 if reading["measure"] == "total demand" else 30,
                "intervals_in_window": gold_result["intervals_in_window"],
                "intervals_held": gold_result["intervals_held"], "complete": gold_result["complete"],
                "excluded_rows_by_as_of": gold_result["excluded_rows_by_as_of"],
                "source_row_ids": gold_result["source_row_ids"]}
        diff = sorted(k for k in want if got[k] != want[k])
        if diff:
            out.append(f"an admitted result differs from gold in {', '.join(diff)}: "
                       + "; ".join(f"{k} {got[k]!r} vs gold {want[k]!r}" for k in diff))
        else:
            correct = True
    return out, correct
