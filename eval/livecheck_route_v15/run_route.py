"""One call of the routing-only Live check of route contract v15 (PROTOCOL.md). It is the first step of a Live
investigation, exactly as `service.investigate` runs it, and nothing after it:
1. `LiveController.route`: one routing call to the hosted model, under the ledger's cap (`nem_agent.budget`);
2. `service.resolve_routed`: request resolution from the routing decision.

No dispatcher is created, no tool runs, nothing is calculated or synthesised, and no answer is written. Adapted from
`eval/livecheck_route_v13/run_route.py` (frozen, and unchanged). It records:
- the full v15 decision, with its contract;
- every routing event of the trace;
- the full resolution, with every request's provenance, spans and offsets, its notes and ineligible tools;
- `tools_offered`: the tools Live would offer this resolution (none unless it proceeds: the intent's playbook, less
  the tools the resolution makes ineligible). Tool eligibility is scored from this.

Errors and budget stops print `ERROR` and `STOPPED:` as the earlier scripts do. The API key is never read here, never
printed and never written: the OpenAI SDK reads it from the environment.

Usage: python eval/livecheck_route_v15/run_route.py --slot 3 --label LC-route-v15-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config, paths  # noqa: E402
from nem_agent.agent.playbook import PLAYBOOKS  # noqa: E402
from nem_agent.agent.request import InvestigateRequest  # noqa: E402
from nem_agent.evidence import EvidenceRegistry  # noqa: E402
from nem_agent.report import Versions  # noqa: E402
from nem_agent.service import _shared, code_version, corpus_version, resolve_routed  # noqa: E402
from nem_agent.timeutil import iso_utc  # noqa: E402
from nem_agent.trace import Trace  # noqa: E402

INVALID_EVENTS = ("route:incomplete", "route:invalid_json")


def case_note_files() -> int:
    """Files in the local case-note store: a routing call must never add any."""
    return sum(1 for f in paths.case_notes_dir().rglob("*") if f.is_file())


def tools_offered(res: Any) -> list[str]:
    """What Live would offer this resolution (``LiveController.run``): nothing unless it proceeds; otherwise the
    intent's playbook, less the tools the resolution makes ineligible (D29)."""
    if res.status != "ok" or res.intent is None:
        return []
    pb = PLAYBOOKS[res.intent]
    ineligible = res.requests.ineligible_tools if res.requests is not None else {}
    return [t for t in (*pb.required, *pb.optional) if t not in ineligible]


def route_call(config_case: dict[str, Any], client: Any = None, write_trace: bool = True) -> dict[str, Any]:
    """The record of one routing call. ``client``: a stand-in transport for offline tests (None: the hosted model);
    ``write_trace``: whether the trace is written to artifacts/traces (offline tests do not write it)."""
    from nem_agent.agent.live import LiveController

    store, selection = _shared()
    notes_before = case_note_files()
    req = InvestigateRequest(question=config_case["question"], mode="live", **(config_case.get("request") or {}))
    live = LiveController(None, EvidenceRegistry(), Versions(code=code_version(), data=store.data_version,
                                                             corpus=corpus_version(), prompt=config.PROMPT_VERSION,
                                                             model=None, controller="live"), client=client)
    trace = Trace()
    decision = live.route(req.question, trace)
    res = resolve_routed(req, decision, selection, trace)
    trace.add("route", res.intent or "none", status=res.status, routing=res.routing, reasons=res.reasons,
              region=res.region, as_of=res.as_of.isoformat() if res.as_of else None,
              window=[w.isoformat() for w in res.window] if res.window else None)
    if write_trace:
        trace.write()
    events = trace.as_dict()["events"]
    calls = [e for e in events if e.get("kind") == "model" and e.get("name") == "route"]
    call = calls[0] if calls else {}
    usage = call.get("usage") or {}
    diag = next((e for e in events if e.get("name") == "route:incomplete_output"), None)
    return {
        "config": config_case["config"], "question": config_case["question"],
        "request": config_case.get("request") or {},
        "route": decision.model_dump(mode="json") if decision is not None else None,
        "route_contract": decision.contract if decision is not None else None,
        "route_invalid": decision is None,
        "route_invalid_events": [e["name"] for e in events if e.get("name") in INVALID_EVENTS],
        "route_call": {"status": call.get("status"), "incomplete": call.get("incomplete"),
                       "max_output_tokens": call.get("max_output_tokens"), "requested": call.get("requested"),
                       "reported": call.get("reported"), "input_tokens": usage.get("input_tokens"),
                       "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
                       "output_tokens": usage.get("output_tokens"),
                       "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                       "cost_usd": call.get("cost_usd"), "duration_ms": call.get("duration_ms")},
        "incomplete_diagnostics": diag,
        "routing_events": [e for e in events if e.get("kind") in ("model", "route")],
        "resolution": {"status": res.status, "reasons": res.reasons, "intent": res.intent, "region": res.region,
                       "as_of_utc": iso_utc(res.as_of) if res.as_of else None,
                       "window_utc": [iso_utc(t) for t in res.window] if res.window else None,
                       "target_utc": [iso_utc(t) for t in res.target] if res.target else None,
                       "requests": res.requests.as_dict() if res.requests is not None else None},
        "tools_offered": tools_offered(res),
        "score": {"case_note_files_written": case_note_files() - notes_before, "forbidden_calls": 0,
                  "model_calls": live.usage.model_calls, "trace_id": trace.trace_id},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: OPENAI_API_KEY is not set; nothing run")
        return 3
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    slot = next(s for s in freeze["slots"] if s["slot"] == args.slot)
    config_case = next(c for c in json.loads((HERE / "cases.json").read_text())["cases"] if c["config"] == slot["config"])
    out = paths.artifacts_dir() / "live" / args.label
    out.mkdir(parents=True, exist_ok=True)
    name = slot["record"]
    before = budget.spent()
    try:
        rec = route_call(config_case)
    except budget.BudgetExceeded as exc:
        print(f"[{name}] STOPPED: {exc}")
        return 0
    except Exception as exc:  # an API failure ends this call; what it cost stays in the ledger
        err = {"slot": args.slot, "config": slot["config"], "error": f"{type(exc).__name__}: {str(exc)[:200]}",
               "ledger_cost_usd": round(budget.spent() - before, 6)}
        print(f"[{name}] ERROR {err['error']} (ledger cost {err['ledger_cost_usd']} USD, counted at worst case)")
        (out / f"{name}.error.json").write_text(json.dumps(err, indent=2) + "\n")
        return 1
    rec["slot"] = args.slot
    rec["score"]["ledger_cost_usd"] = round(budget.spent() - before, 6)
    (out / f"{name}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    c = rec["route_call"]
    print(f"[{name}] status={rec['resolution']['status']} invalid={rec['route_invalid']} call={c['status']} "
          f"tokens={c['input_tokens']}/{c['output_tokens']} reasoning={c['reasoning_tokens']} cost={c['cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
