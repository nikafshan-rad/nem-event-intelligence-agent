"""Run one routing case of the Live check of the v12 routing extraction (PASS_RULE.md): the first step of a Live
investigation, exactly as `service.investigate` runs it, and nothing after it.

1. `LiveController.route`: one routing call to the hosted model, under the ledger's cap (`nem_agent.budget`);
2. `service.resolve_routed`: the merged resolution of the request, from the routing decision.

No tool runs and no answer is written. The record keeps the routing decision (with its `requested` field), the
resolution (status, reasons, intent, region, as-of cutoff, and the structured requests with their provenance), the
routing call's usage, and whether the routing output was cut off or invalid. Errors and budget stops are reported as
`scripts/live_diagnose.py` reports them (`ERROR`, `STOPPED:`), so the runner reads them the same way.

The API key is never read here, never printed and never written: the OpenAI SDK reads it from the environment.

Usage: python eval/livecheck_routing_v12/run_route.py --case Q01 --cases-file eval/livecheck_routing_v12/cases.json \
           --label LC-route-v12-fresh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config, paths  # noqa: E402
from nem_agent.agent.request import InvestigateRequest  # noqa: E402
from nem_agent.evidence import EvidenceRegistry  # noqa: E402
from nem_agent.report import Versions  # noqa: E402
from nem_agent.service import _shared, code_version, corpus_version, resolve_routed  # noqa: E402
from nem_agent.timeutil import iso_utc  # noqa: E402
from nem_agent.trace import Trace  # noqa: E402

INVALID_EVENTS = ("route:incomplete", "route:invalid_json")


def _case_note_files() -> int:
    """Files in the local case-note store: a routing case must never add any (H1)."""
    return sum(1 for f in paths.case_notes_dir().rglob("*") if f.is_file())


def route_case(case: dict[str, Any], client: Any = None, write_trace: bool = True) -> dict[str, Any]:
    """The record of one routing case. ``client``: a stand-in transport for offline tests (None: the hosted model);
    ``write_trace``: whether the trace is written to artifacts/traces (offline tests do not write it)."""
    from nem_agent.agent.live import LiveController

    store, selection = _shared()
    notes_before = _case_note_files()
    req = InvestigateRequest(question=case["question"], mode="live", **(case.get("request") or {}))
    live = LiveController(None, EvidenceRegistry(), Versions(code=code_version(), data=store.data_version,
                                                             corpus=corpus_version(), prompt=config.PROMPT_VERSION,
                                                             model=None, controller="live"), client=client)
    trace = Trace()
    decision = live.route(req.question, trace)
    res = resolve_routed(req, decision, selection, trace)
    trace.add("route", res.intent or "none", status=res.status, routing=res.routing, reasons=res.reasons,
              region=res.region, as_of=res.as_of.isoformat() if res.as_of else None)
    if write_trace:
        trace.write()
    events = trace.as_dict()["events"]
    calls = [e for e in events if e.get("kind") == "model" and e.get("name") == "route"]
    usage = (calls[0].get("usage") if calls else None) or {}
    invalid = [e["name"] for e in events if e.get("name") in INVALID_EVENTS]
    return {
        "case_id": case["case_id"], "question": case["question"], "request": case.get("request") or {},
        "route": decision.model_dump(mode="json") if decision is not None else None,
        "route_invalid": decision is None, "route_invalid_events": invalid,
        "route_call": {"status": calls[0].get("status") if calls else None,
                       "incomplete": calls[0].get("incomplete") if calls else None,
                       "max_output_tokens": calls[0].get("max_output_tokens") if calls else None,
                       "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                       "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                       "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
                       "cost_usd": calls[0].get("cost_usd") if calls else None,
                       "duration_ms": calls[0].get("duration_ms") if calls else None},
        "resolution": {"status": res.status, "reasons": res.reasons, "intent": res.intent, "region": res.region,
                       "as_of_utc": iso_utc(res.as_of) if res.as_of else None,
                       "target_utc": [iso_utc(t) for t in res.target] if res.target else None,
                       "requests": res.requests.as_dict() if res.requests is not None else None},
        "score": {"case_note_files_written": _case_note_files() - notes_before, "forbidden_calls": 0,
                  "model_calls": live.usage.model_calls, "trace_id": trace.trace_id},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--cases-file", required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: OPENAI_API_KEY is not set; nothing run")
        return 3
    cases = {c["case_id"]: c for c in json.loads((REPO / args.cases_file).read_text())["cases"]}
    case = cases[args.case]
    out = paths.artifacts_dir() / "live" / args.label
    out.mkdir(parents=True, exist_ok=True)
    before = budget.spent()
    try:
        rec = route_case(case)
    except budget.BudgetExceeded as exc:
        print(f"[{args.case}] STOPPED: {exc}")
        return 0
    except Exception as exc:  # an API failure ends this case; what it cost stays in the ledger
        err = {"case_id": args.case, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
               "ledger_cost_usd": round(budget.spent() - before, 6)}
        print(f"[{args.case}] ERROR {err['error']} (ledger cost {err['ledger_cost_usd']} USD, counted at worst case)")
        (out / f"{args.case}.error.json").write_text(json.dumps(err, indent=2) + "\n")
        return 0
    rec["score"]["ledger_cost_usd"] = round(budget.spent() - before, 6)
    (out / f"{args.case}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    c = rec["route_call"]
    print(f"[{args.case}] status={rec['resolution']['status']} invalid={rec['route_invalid']} "
          f"tokens={c['input_tokens']}/{c['output_tokens']} cost={c['cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
