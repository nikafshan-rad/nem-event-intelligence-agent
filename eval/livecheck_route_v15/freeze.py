"""Write FREEZE.json for the routing-only Live check of route contract v15 (PROTOCOL.md). Offline: it reads the
ledger's total, line count and hash, never a key, and makes no model call and no ledger write.

It records:
- **the code:** the commit and, separately, its `src/` tree (the checkout's `src/` must equal it), its tree, and the
  prompts v16 tree;
- **the contract and model:** route contract v15 (as the code reads a new decision), the model, the routing output cap
  (2,000 tokens, unchanged) and the accounting prices;
- **the caps:** each configuration's worst-case reservation, measured on its actual routing request (the real
  `LiveController.route` with a capturing stub transport and the ledger's `reserve` captured, not written), which must
  be at most the per-call cap; the run cap; the required task cap;
- **the plan:** 34 calls in two rounds of all 17 configurations, each round's order shuffled once here;
- **the starting ledger:** total, line count and SHA-256 prefix, which must equal the protocol's;
- **the SHA-256 of every protocol file** and of every source a question or a cross-check is read from.

If any reservation exceeds the per-call cap, nothing is written: that is a blocker to report, and the cap is not
raised.

Usage: python eval/livecheck_route_v15/freeze.py [--code-commit COMMIT]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config  # noqa: E402

MODEL = "gpt-5-mini"
CODE_COMMIT = "d38eb4d"
ROUTE_CONTRACT = "v15"
PROMPT_VERSION = "prompts/v16"
CALL_CAP = 0.006
LABEL = "LC-route-v15-run"
LEDGER_START = (9.227365, 3158, "4250ef88a8ad3d35")  # PROTOCOL.md, "Caps"
CONFIGS = [c["config"] for c in json.loads((HERE / "cases.json").read_text())["cases"]]
ROUNDS = [CONFIGS, CONFIGS]
FILES = ["PROTOCOL.md", "CAPABILITIES.md", "GOLD_FORMAT.md", "WRITER_BRIEF.md", "WRITER_BRIEF_FAMILIAR.md",
         "REVIEW_BRIEF.md", "WRITER_OUTPUT.json", "WRITER_FAMILIAR.json", "WRITER_REPORT.md", "REVIEW.json",
         "REVIEW_D08.json", "REVIEW_REPORT.md", "PROVENANCE.md", "cases.json", "GOLD.json", "configs.py", "build_kit.py", "gold.py",
         "run_route.py", "run_eval.py", "score.py", "freeze.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def plan(rng: random.Random | None = None) -> list[dict[str, Any]]:
    """The 34 calls: two rounds of the 17 configurations, each round in an order shuffled once (PROTOCOL.md)."""
    out: list[dict[str, Any]] = []
    for r, configs in enumerate(ROUNDS, 1):
        order = list(configs)
        if rng is not None:
            rng.shuffle(order)
        for cfg in order:
            n = len(out) + 1
            out.append({"slot": n, "run": "RT", "round": r, "config": cfg, "case": f"{n:02d}-{cfg}",
                        "record": f"{n:02d}-{cfg}"})
    return out


class _Stub:
    """A transport that records the request and returns a minimal valid decision: no network, no model."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def create(self, **kw: Any) -> dict[str, Any]:
        self.kwargs = kw
        text = json.dumps({"intent": None, "region": None, "event_date": None, "as_of_text": None,
                           "needs_clarification": True, "clarification_reason": "unclear_question",
                           "clarification": "x", "out_of_scope": False, "requested": None})
        return {"id": "stub", "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text}]}], "usage": {"input_tokens": 0, "output_tokens": 0}}


def reservations(cases: list[dict[str, Any]]) -> dict[str, float]:
    """Each configuration's worst-case reservation, measured on its actual routing request: the real route call with
    a stub transport, and ``budget.reserve`` captured (nothing is written to any ledger)."""
    from nem_agent.agent.live import LiveController
    from nem_agent.evidence import EvidenceRegistry
    from nem_agent.report import Versions
    from nem_agent.trace import Trace

    seen: list[float] = []

    def capture(model: str, stage: str, worst_case_usd: float) -> str:
        seen.append(worst_case_usd)
        return "captured"

    def nothing(*a: Any, **k: Any) -> None:
        return None

    real_reserve, real_settle = budget.reserve, budget.settle
    budget.reserve, budget.settle = capture, nothing
    try:
        out = {}
        for c in cases:
            stub = _Stub()
            live = LiveController(None, EvidenceRegistry(), Versions(code="freeze", data="freeze", corpus=None,
                                                                     prompt=config.PROMPT_VERSION, model=MODEL,
                                                                     controller="live"), client=stub, model=MODEL)
            seen.clear()
            live.route(c["question"], Trace())
            assert len(seen) == 1, f"{c['config']}: expected one routing reservation, got {len(seen)}"
            sent = {k: v for k, v in stub.kwargs.items() if k not in ("model", "store", "max_output_tokens")}
            recomputed = budget.worst_case_cost(MODEL, len(json.dumps(sent, default=str)),
                                                config.MAX_OUTPUT_TOKENS["route"])
            assert seen[0] == recomputed, f"{c['config']}: reservation {seen[0]} != recomputed {recomputed}"
            out[c["config"]] = seen[0]
        return out
    finally:
        budget.reserve, budget.settle = real_reserve, real_settle


def ledger_fingerprint() -> dict[str, Any]:
    p = budget.ledger_path()
    data = p.read_bytes()
    return {"ledger_start_usd": round(budget.spent(), 6), "ledger_lines": sum(1 for ln in data.splitlines() if ln.strip()),
            "ledger_sha256_prefix": hashlib.sha256(data).hexdigest()[:16]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-commit", default=CODE_COMMIT)
    args = ap.parse_args()
    if any(os.environ.get(k) for k in ("NEM_AGENT_BUDGET_LEDGER", "NEM_AGENT_MODEL", "NEM_AGENT_PRICE_INPUT_PER_MTOK",
                                       "NEM_AGENT_PRICE_OUTPUT_PER_MTOK", "NEM_AGENT_PRICE_CACHED_INPUT_PER_MTOK")):
        raise SystemExit("unset the ledger, model and price overrides: the freeze records the real ledger and prices")
    spec = importlib.util.spec_from_file_location("livecheck_route_v15_run_eval", HERE / "run_eval.py")
    assert spec is not None and spec.loader is not None
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)
    route_contract = run_eval.route_contract

    commit = git("rev-parse", args.code_commit)
    src_tree = git("rev-parse", f"{commit}:src")
    if src_tree != git("rev-parse", "HEAD:src") or git("status", "--porcelain", "--", "src"):
        raise SystemExit("the checkout's src/ is not the code commit's src/ tree, or is modified")
    if config.PROMPT_VERSION != PROMPT_VERSION:
        raise SystemExit(f"the prompts are {config.PROMPT_VERSION}, not {PROMPT_VERSION}")
    if route_contract() != ROUTE_CONTRACT:
        raise SystemExit(f"the route contract is {route_contract()}, not {ROUTE_CONTRACT}")
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    res = reservations(cases)
    over = {c: r for c, r in res.items() if r > CALL_CAP}
    if over:
        raise SystemExit(f"BLOCKER: the per-call cap {CALL_CAP} is below these worst-case reservations: {over}. "
                         "Nothing is frozen and the cap is not raised; report it.")
    ledger = ledger_fingerprint()
    got = (ledger["ledger_start_usd"], ledger["ledger_lines"], ledger["ledger_sha256_prefix"])
    if got != LEDGER_START:
        raise SystemExit(f"the ledger {got} is not the protocol's starting ledger {LEDGER_START}")
    seed = int.from_bytes(os.urandom(8), "big")
    slots = plan(random.Random(seed))
    gold = json.loads((HERE / "GOLD.json").read_text())
    files = {f"eval/livecheck_route_v15/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files |= {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in gold["sources_sha256"]}
    for rel, want in gold["sources_sha256"].items():
        if files[rel] != want:
            raise SystemExit(f"{rel} changed since GOLD.json was built")
    p = budget.prices(MODEL)
    run_cap = round(len(slots) * CALL_CAP, 6)
    freeze = {
        "protocol": "Routing-only Live check of route contract v15 (eval/livecheck_route_v15/PROTOCOL.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": commit, "src_tree": src_tree, "code_tree": git("rev-parse", f"{commit}^{{tree}}"),
        "prompts_tree": git("rev-parse", f"{commit}:src/nem_agent/{config.PROMPT_VERSION}"),
        "prompt_version": config.PROMPT_VERSION, "route_contract": ROUTE_CONTRACT, "model": MODEL,
        "route_max_output_tokens": config.MAX_OUTPUT_TOKENS["route"],
        "reasoning_effort_sent": "not sent (the provider default applies)",
        "accounting_prices_per_mtok": {"input": p[0], "cached_input": p[1], "output": p[2]} if p else None,
        **ledger,
        "reservations_usd": res, "reservation_method": "measured on each configuration's actual routing request "
                                                        "(LiveController.route with a stub transport; reserve captured)",
        "call_cap_usd": CALL_CAP,
        "runs": {"RT": {"cases": len(slots), "case_cap_usd": CALL_CAP, "run_cap_usd": run_cap}},
        "required_task_cap_usd": round(ledger["ledger_start_usd"] + run_cap, 6),
        "interruption_note": "an interrupted attempt's cost stays counted against the run cap; no retry allowance is "
                             "added, so interrupted attempts may exhaust it (then INCOMPLETE)",
        "label": LABEL, "order_seed": seed, "slots": slots, "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: freeze[k] for k in ("code_commit", "src_tree", "prompts_tree", "prompt_version",
                                            "route_contract", "model", "ledger_start_usd", "ledger_lines",
                                            "ledger_sha256_prefix", "call_cap_usd", "runs", "required_task_cap_usd")},
                     indent=1))
    print("max reservation:", max(res.values()), "| order:", " ".join(s["case"] for s in slots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
