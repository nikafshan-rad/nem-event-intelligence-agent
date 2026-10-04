"""Write FREEZE.json for the routing-only Live check of route contract v13 (PROTOCOL.md). Offline: it reads the
ledger's total, line count and hash, never a key, and makes no call.

It records:
- **the code:** the commit, its tree, its `src/` tree and its prompts v13 tree (the checkout's `src/` must equal it);
- **the model:** the model, the routing output cap and the accounting prices;
- **the caps:** the per-call cap, checked against the exact worst-case reservation of every configuration's routing
  call; the run cap; the required task cap;
- **the plan:** 32 calls in five rounds, each round's order shuffled once here;
- **the starting ledger:** total, line count and SHA-256 prefix, which must equal the protocol's;
- **the SHA-256 of every protocol file** and of every gold source.

Usage: python eval/livecheck_route_v13/freeze.py [--code-commit COMMIT]
"""

from __future__ import annotations

import argparse
import hashlib
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
CODE_COMMIT = "a648269"
CALL_CAP = 0.006
LABEL = "LC-route-v13-run"
LEDGER_START = (8.895359, 3023, "8dfcdd5e914830cb")  # PROTOCOL.md, "Caps"
ROUNDS = [["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11"],
          ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11"],
          ["C01", "C02", "C03", "C04", "C05", "C06"], ["C01", "C02"], ["C01", "C02"]]
FILES = ["PROTOCOL.md", "cases.json", "GOLD.json", "gold.py", "run_route.py", "run_eval.py", "score.py", "freeze.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def plan(rng: random.Random | None = None) -> list[dict[str, Any]]:
    """The 32 calls: five rounds, each round's configurations in an order shuffled once (PROTOCOL.md, "Scope")."""
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


def reservations() -> dict[str, float]:
    """The exact worst-case reservation of each configuration's routing call (``budget.worst_case_cost`` over the
    request the controller sends: the v13 route prompt, the question and the strict schema)."""
    from nem_agent.agent.live import RouteDecision, prompt
    from nem_agent.tools.args import strict_json_schema

    fmt = {"type": "json_schema", "name": "RouteDecision", "schema": strict_json_schema(RouteDecision), "strict": True}
    out = {}
    for c in json.loads((HERE / "cases.json").read_text())["cases"]:
        req = {"instructions": prompt("route"), "input": [{"role": "user", "content": c["question"]}],
               "text": {"format": fmt}}
        out[c["config"]] = budget.worst_case_cost(MODEL, len(json.dumps(req, default=str)),
                                                  config.MAX_OUTPUT_TOKENS["route"])
    return out


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
    commit = git("rev-parse", args.code_commit)
    src_tree = git("rev-parse", f"{commit}:src")
    if src_tree != git("rev-parse", "HEAD:src") or git("status", "--porcelain", "--", "src"):
        raise SystemExit("the checkout's src/ is not the code commit's src/ tree, or is modified")
    if config.PROMPT_VERSION != "prompts/v13":
        raise SystemExit(f"the prompts are {config.PROMPT_VERSION}, not v13")
    res = reservations()
    if max(res.values()) > CALL_CAP:
        raise SystemExit(f"the call cap {CALL_CAP} is below the worst-case reservation {max(res.values())}")
    ledger = ledger_fingerprint()
    got = (ledger["ledger_start_usd"], ledger["ledger_lines"], ledger["ledger_sha256_prefix"])
    if got != LEDGER_START:
        raise SystemExit(f"the ledger {got} is not the protocol's starting ledger {LEDGER_START}")
    seed = int.from_bytes(os.urandom(8), "big")
    slots = plan(random.Random(seed))
    gold = json.loads((HERE / "GOLD.json").read_text())
    files = {f"eval/livecheck_route_v13/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files |= {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in gold["sources_sha256"]}
    for rel, want in gold["sources_sha256"].items():
        if files[rel] != want:
            raise SystemExit(f"{rel} changed since GOLD.json was built")
    p = budget.prices(MODEL)
    run_cap = round(len(slots) * CALL_CAP, 6)
    freeze = {
        "protocol": "Routing-only Live check of route contract v13 (eval/livecheck_route_v13/PROTOCOL.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": commit, "code_tree": git("rev-parse", f"{commit}^{{tree}}"), "src_tree": src_tree,
        "prompts_tree": git("rev-parse", f"{commit}:src/nem_agent/{config.PROMPT_VERSION}"),
        "prompt_version": config.PROMPT_VERSION, "model": MODEL,
        "route_max_output_tokens": config.MAX_OUTPUT_TOKENS["route"],
        "reasoning_effort_sent": "not sent (the provider default applies)",
        "accounting_prices_per_mtok": {"input": p[0], "cached_input": p[1], "output": p[2]} if p else None,
        **ledger,
        "reservations_usd": res, "call_cap_usd": CALL_CAP,
        "runs": {"RT": {"cases": len(slots), "case_cap_usd": CALL_CAP, "run_cap_usd": run_cap}},
        "required_task_cap_usd": round(ledger["ledger_start_usd"] + run_cap, 6),
        "interruption_note": "an interrupted attempt's cost stays counted against the run cap; no retry allowance is "
                             "added, so interrupted attempts may exhaust it (then INCOMPLETE)",
        "label": LABEL, "order_seed": seed, "slots": slots, "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: freeze[k] for k in ("code_commit", "src_tree", "prompts_tree", "prompt_version", "model",
                                            "ledger_start_usd", "ledger_lines", "ledger_sha256_prefix", "call_cap_usd",
                                            "runs", "required_task_cap_usd")}, indent=1))
    print("max reservation:", max(res.values()), "| order:", " ".join(s["case"] for s in slots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
