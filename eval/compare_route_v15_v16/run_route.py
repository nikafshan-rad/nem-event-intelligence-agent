"""One slot of the comparison (PROTOCOL.md): one routing call in arm A (route contract v15, prompts v16) or arm B
(route contract v16, prompts v17, policy V1), then code's request resolution, exactly as `service.investigate` runs its
first step, and nothing after it. Adapted from eval/livecheck_route_v15/run_route.py (frozen, unchanged).

No dispatcher is created, no tool runs, nothing is computed or written as an answer. It records the decision (v15 or
the v16 plan), the contract and prompts the controller used, the full resolution with its plan record, the tools Live
would offer, the routing call's status, usage and duration, and the reported model. An API error of any kind is
recorded (``api_error``), never retried; the slot then has no reading.

The arm is set by the environment the runner gives the process (``ARM_ENV``) and checked here. ``CMP_ROUTE_FAKE`` names
a scripted transport for offline tests only; the runner refuses to start a paid run while it is set. The API key is
never read here, printed or written: the OpenAI SDK reads it from the environment.

Usage: python eval/compare_route_v15_v16/run_route.py --slot 3 --label CMP-route-v15-v16-run
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

from nem_agent import budget, paths  # noqa: E402
from nem_agent.agent.playbook import PLAYBOOKS  # noqa: E402
from nem_agent.agent.request import InvestigateRequest  # noqa: E402
from nem_agent.evidence import EvidenceRegistry  # noqa: E402
from nem_agent.report import Versions  # noqa: E402
from nem_agent.service import _shared, code_version, corpus_version, resolve_routed  # noqa: E402
from nem_agent.timeutil import iso_utc  # noqa: E402
from nem_agent.trace import Trace  # noqa: E402

ARM_ENV = {"A": {}, "B": {"NEM_AGENT_ROUTE_PLAN": "1", "NEM_AGENT_PLAN_POLICY": "V1"}}
PLAN_SETTINGS = ("NEM_AGENT_ROUTE_PLAN", "NEM_AGENT_PLAN_POLICY")
INVALID_EVENTS = ("route:incomplete", "route:invalid_json")
FAKE = "CMP_ROUTE_FAKE"


def arm_ok(arm: str, env: dict[str, str] | os._Environ[str] = os.environ) -> bool:
    """The process's route-plan settings are exactly its arm's."""
    return all(env.get(k) == ARM_ENV[arm].get(k) for k in PLAN_SETTINGS)


def case_note_files() -> int:
    return sum(1 for f in paths.case_notes_dir().rglob("*") if f.is_file())


def tools_offered(res: Any) -> list[str]:
    """What Live would offer this resolution (``LiveController.run``): nothing unless it proceeds; otherwise the
    intent's playbook, less the tools the resolution makes ineligible (D29)."""
    if res.status != "ok" or res.intent is None:
        return []
    pb = PLAYBOOKS[res.intent]
    ineligible = res.requests.ineligible_tools if res.requests is not None else {}
    return [t for t in (*pb.required, *pb.optional) if t not in ineligible]


def resolution_record(res: Any) -> dict[str, Any]:
    """The resolution as recorded (and as the scorer reads it, also for the offline V0 recompilation)."""
    return {"status": res.status, "reasons": res.reasons, "intent": res.intent, "region": res.region,
            "as_of_utc": iso_utc(res.as_of) if res.as_of else None,
            "window_utc": [iso_utc(t) for t in res.window] if res.window else None,
            "target_utc": [iso_utc(t) for t in res.target] if res.target else None,
            "requests": res.requests.as_dict() if res.requests is not None else None}


class ScriptedTransport:
    """Offline tests only: the response (or the exception) scripted for this slot."""

    def __init__(self, script: dict[str, Any]) -> None:
        self.script = script

    def create(self, **kw: Any) -> dict[str, Any]:
        if "raise" in self.script:
            err = RuntimeError(self.script["raise"].get("message", "scripted failure"))
            if self.script["raise"].get("status_code") is not None:
                err.status_code = self.script["raise"]["status_code"]  # type: ignore[attr-defined]
            raise err
        return self.script["response"]


def route_call(case: dict[str, Any], arm: str, client: Any = None, write_trace: bool = True) -> dict[str, Any]:
    """The record of one slot. ``client``: a stand-in transport for offline tests (None: the hosted model)."""
    from nem_agent.agent.live import LiveController

    if not arm_ok(arm):
        raise SystemExit(f"the route-plan settings are not arm {arm}'s")
    store, selection = _shared()
    notes_before = case_note_files()
    req = InvestigateRequest(question=case["question"], mode="live", **(case.get("request") or {}))
    live = LiveController(None, EvidenceRegistry(), Versions(code=code_version(), data=store.data_version,
                                                             corpus=corpus_version(), prompt="(set by the arm)",
                                                             model=None, controller="live"), client=client)
    trace = Trace()
    api_error = None
    decision = res = None
    try:
        decision = live.route(req.question, trace)
    except budget.BudgetExceeded:
        raise
    except Exception as exc:  # any API failure: recorded, never retried; the ledger keeps what it settled
        api_error = {"type": type(exc).__name__, "status_code": getattr(exc, "status_code", None),
                     "message": str(exc)[:200]}
    if api_error is None:
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
    err_ev: dict[str, Any] = next((e for e in events if e.get("name") == "route:error"), {})
    return {
        "config": case["config"], "arm": arm, "question": case["question"], "request": case.get("request") or {},
        "route_contract": "v16" if live.request_plan else "v15", "prompt_version": live.prompt_version,
        "decision": decision.model_dump(mode="json") if decision is not None else None,
        "decision_contract": decision.contract if decision is not None else None,
        "route_invalid": api_error is None and decision is None,
        "route_invalid_events": [e["name"] for e in events if e.get("name") in INVALID_EVENTS],
        "api_error": None if api_error is None else {**api_error, "settled_usd": err_ev.get("settled_usd")},
        "route_call": {"status": call.get("status"), "incomplete": call.get("incomplete"),
                       "max_output_tokens": call.get("max_output_tokens") or err_ev.get("max_output_tokens"),
                       "requested": call.get("requested"), "reported": call.get("reported"),
                       "input_tokens": usage.get("input_tokens"),
                       "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
                       "output_tokens": usage.get("output_tokens"),
                       "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                       "usage_cost_usd": call.get("cost_usd") if call else None,
                       "duration_ms": call.get("duration_ms") or err_ev.get("duration_ms")},
        "resolution": None if res is None else resolution_record(res),
        "tools_offered": tools_offered(res) if res is not None else [],
        "score": {"case_note_files_written": case_note_files() - notes_before, "tools_executed": 0,
                  "model_calls": live.usage.model_calls, "trace_id": trace.trace_id},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", default=None, help=argparse.SUPPRESS)  # offline tests: the record directory
    args = ap.parse_args()
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    slot = next(s for s in freeze["slots"] if s["slot"] == args.slot)
    case = next(c for c in json.loads((HERE / "cases.json").read_text())["cases"] if c["config"] == slot["config"])
    fake = os.environ.get(FAKE)
    client = None
    if fake:
        script = json.loads(Path(fake).read_text())
        client = ScriptedTransport(script.get(slot["case"]) or script["default"][slot["arm"]])
    elif not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: OPENAI_API_KEY is not set; nothing run")
        return 3
    out = Path(args.out) if args.out else paths.artifacts_dir() / "live" / args.label
    out.mkdir(parents=True, exist_ok=True)
    name = slot["case"]
    try:
        rec = route_call(case, slot["arm"], client=client, write_trace=not fake)
    except budget.BudgetExceeded as exc:
        print(f"[{name}] STOPPED: {exc}")
        return 0
    rec["slot"] = args.slot
    (out / f"{name}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    c = rec["route_call"]
    print(f"[{name}] arm={rec['arm']} status={(rec['resolution'] or {}).get('status')} invalid={rec['route_invalid']} "
          f"api_error={bool(rec['api_error'])} call={c['status']} tokens={c['input_tokens']}/{c['output_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
