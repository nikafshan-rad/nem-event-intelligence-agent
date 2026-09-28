#!/usr/bin/env python
"""Run frozen evaluation cases with the REAL hosted model and save a redacted diagnostic record per case.

Uses the existing cases in eval/cases.json unchanged and the evaluation's own scoring (run_system_case), with the
task-wide spending cap in nem_agent.budget. For each case it writes:

- the question, the routing decision, and each tool call: its name, the arguments as validated and executed, its
  status, source IDs and output excerpt, plus the ranked retrieval candidates;
- the model drafts (first and after repair), the independent validator findings, and the final report;
- usage: model calls, input/output tokens, latency and list-price cost; and the gold checks.

The API key is never read here, never printed and never written: the OpenAI SDK reads it from the environment.

Usage: python scripts/live_diagnose.py --cases DOC01,FC01,EV01 --label L1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, paths  # noqa: E402
from nem_agent.evaluation.runner import load_cases, run_system_case  # noqa: E402

KEEP = ("case_id", "category", "split", "status", "status_ok", "accepted", "routed_intent", "expected_intent",
        "required_tools", "required_tools_executed", "blocked_calls", "n_claims", "n_citations", "critical_final",
        "fallback_applied", "gold_numbers_hit", "gold_numbers_total", "gold_forecast_ok", "gold_forecast_detail",
        "gold_citation_hit", "corpus_unavailable", "as_of_leaks", "causal_violations", "latency_ms", "model_calls",
        "input_tokens", "output_tokens", "cost_usd", "trace_id", "forbidden_calls", "claim_violations_final",
        "citation_violations_final", "wrong_region_findings", "retrospective_used", "injection_followed",
        "injection_quoted", "generator")


def _case_note_files() -> int:
    """Files in the local case-note store (proposals, approvals, notes): an investigation must never add any."""
    return sum(1 for f in paths.case_notes_dir().rglob("*") if f.is_file())


def diagnose(case: dict[str, Any]) -> dict[str, Any]:
    keep: dict[str, Any] = {}
    notes_before = _case_note_files()
    row = run_system_case(case, "live", keep=keep)
    res = keep.get("result")
    rec: dict[str, Any] = {"question": case["question"], "request": case.get("request", {}),
                           "expected": {k: case["expected"].get(k) for k in ("intent", "status_in", "required_tools")},
                           "score": {k: row.get(k) for k in KEEP if k in row}}
    rec["score"]["case_note_files_written"] = _case_note_files() - notes_before
    if res is None:  # approval scenarios never reach the model
        return rec
    tr = res.trace.as_dict()
    ev = tr["events"]
    rec["route"] = next((e.get("decision") for e in ev if e["name"] == "model_decision"), None)
    outputs = {e.get("call_id"): e for e in ev if e["kind"] == "tool_output"}
    rec["tools"] = [{"name": r.name, "call_id": r.call_id, "status": r.status, "args": r.args or r.raw_args,
                     "blocked_reason": r.blocked_reason, "policy_notes": r.policy_notes,
                     "source_ids": r.source_row_ids[:12], "n_source_ids": len(r.source_row_ids),
                     "output_excerpt": (outputs.get(r.call_id) or {}).get("output", "")[:800],
                     "retrieval_candidates": (outputs.get(r.call_id) or {}).get("candidates")} for r in res.records]
    rec["model_calls"] = [{k: e.get(k) for k in ("name", "duration_ms", "cost_usd", "status", "incomplete")} |
                          {"input_tokens": (e.get("usage") or {}).get("input_tokens"),
                           "output_tokens": (e.get("usage") or {}).get("output_tokens"),
                           "reasoning_tokens": ((e.get("usage") or {}).get("output_tokens_details") or {}).get("reasoning_tokens"),
                           "cached_tokens": ((e.get("usage") or {}).get("input_tokens_details") or {}).get("cached_tokens"),
                           "function_calls": [c["name"] for c in e.get("function_calls") or []]}
                          for e in ev if e["kind"] == "model" and e.get("usage")]
    rec["drafts"] = {e["name"]: e.get("report") for e in ev if e["name"].endswith(":draft")}
    rep = res.report.model_dump()
    v = rep["validation"]
    rec["validation"] = {"pre_repair": [(x["code"], x["detail"]) for x in (v.get("pre_repair") or {}).get("violations", [])],
                         "final_candidate": [(x["code"], x["detail"]) for x in v.get("initial", {}).get("violations", [])],
                         "repair_attempted": v.get("repair_attempted", False),
                         "fallback_applied": v.get("fallback_applied", False), "final_passed": v.get("final_passed"),
                         "shown": [(x["code"], x["detail"]) for x in
                                   v.get("after_fallback", v.get("initial", {})).get("violations", [])]}
    rec["report"] = {k: rep.get(k) for k in ("status", "headline", "summary", "numeric_claims", "possible_explanations",
                                              "published_findings", "citations", "uncertainties", "missing_evidence",
                                              "as_of", "event_window", "search_scope")}
    rec["report"]["observations"] = [{k: o.get(k) for k in ("metric", "value", "unit", "valid_at_utc", "valid_at_local",
                                                           "evidence_id", "source_row_ids")} for o in rep["observations"]]
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="comma-separated case ids, or 'all' (with --cases-file)")
    ap.add_argument("--cases-file", default=None, help="a case file other than eval/cases.json (e.g. a frozen "
                                                       "held-out set); its questions are never printed")
    ap.add_argument("--label", required=True, help="gate label, e.g. L1")
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: OPENAI_API_KEY is not set; nothing run")
        return 3
    cases = {c["case_id"]: c for c in load_cases(Path(args.cases_file) if args.cases_file else None)["cases"]}
    ids = list(cases) if args.cases == "all" else [x.strip() for x in args.cases.split(",") if x.strip()]
    out_dir = paths.artifacts_dir() / "live" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    start = budget.spent()
    summary = []
    for cid in ids:
        before = budget.spent()
        try:
            rec = diagnose(cases[cid])
        except budget.BudgetExceeded as exc:
            print(f"[{cid}] STOPPED: {exc}")
            summary.append({"case_id": cid, "stopped": str(exc)})
            break
        except Exception as exc:  # an API failure ends this case, not the run; what it cost stays in the ledger
            err = {"case_id": cid, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                   "ledger_cost_usd": round(budget.spent() - before, 6)}
            print(f"[{cid}] ERROR {err['error']} (ledger cost {err['ledger_cost_usd']} USD, counted at worst case)")
            (out_dir / f"{cid}.error.json").write_text(json.dumps(err, indent=2) + "\n")
            summary.append(err)
            continue
        rec["score"]["ledger_cost_usd"] = round(budget.spent() - before, 6)
        (out_dir / f"{cid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
        s = rec["score"]
        summary.append(s | {"validation": rec.get("validation", {})})
        print(f"[{cid}] status={s.get('status')} fallback={s.get('fallback_applied')} calls={s.get('model_calls')} "
              f"tokens={s.get('input_tokens')}/{s.get('output_tokens')} cost={s.get('cost_usd')} "
              f"latency_ms={s.get('latency_ms')}")
    total = round(budget.spent() - start, 6)
    (out_dir / "summary.json").write_text(json.dumps({"cases": summary, "cost_usd_this_run": total,
                                                      "task_spent_usd": budget.spent(),
                                                      "task_budget_usd": budget.total_budget()}, indent=2) + "\n")
    print(f"cost this run {total} USD; task spent {budget.spent()} of {budget.total_budget()} USD -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
