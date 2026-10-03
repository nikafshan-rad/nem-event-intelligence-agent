"""Write FREEZE.json for the development comparison of gpt-5-mini and gpt-6.1-sol (PROTOCOL.md). Offline: it reads the
ledger's total, line count and hash, never a key, and makes no call.

It records:
- **the code:** the commit, its full tree, its `src/` tree and its prompts tree (the checkout's `src/` must equal it);
- **the models:** their IDs, the accounting prices the ledger uses, and the documented prices, with sources;
- **the caps:** per slot and per run, checked against exact routing reservations and bounded end-to-end reservations;
- **the slots:** the interleaved order of every routing and end-to-end execution;
- **the starting ledger:** total, line count and SHA-256 prefix;
- **the blind review order:** the end-to-end slots' anonymous answer IDs, shuffled once here;
- **the SHA-256 of every protocol file** and of every file the runs read.

Usage: python eval/model_comparison_dev/freeze.py [--code-commit COMMIT]

``--code-commit`` (default HEAD) names the commit whose code is under test; its `src/` tree must be the checkout's.
"""

from __future__ import annotations

import argparse
import glob
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

LC, V6, RV12 = "eval/livecheck_i15_17/cases.json", "eval/holdout_v6/cases.json", "eval/livecheck_routing_v12/cases.json"
ROUTE_CASES = [["K04", LC], ["Z04", V6], ["Q01", RV12], ["Q05", RV12], ["Q02", RV12], ["Q16", RV12], ["Q17", RV12],
               ["Q21", RV12]]
E2E_CASES = [["K05", LC], ["K07", LC], ["K09", LC], ["K06", LC], ["K11", LC]]
REPEATS = 3
DOCS_READ = "2026-10-03"
MODELS: dict[str, dict[str, Any]] = {
    "mini": {"id": "gpt-5-mini",
             # USD per 1M tokens: input, cached input, output (the ledger's terms); equal to the config table
             "accounting_prices": [0.25, 0.025, 2.00],
             "documented_prices": {"input": 0.25, "cached_input": 0.025, "cache_write": None, "output": 2.00},
             "default_reasoning_effort": "medium (GPT-5 cookbook: 'If no reasoning effort is supplied, the default "
                                         "value is medium')",
             "identifier": "alias of gpt-5-mini-2025-08-07"},
    "sol": {"id": "gpt-6.1-sol",
            # uncached input at the cache-write rate (2.50 > 2.00): the ledger has no cache-write term, so this bounds it
            "accounting_prices": [2.50, 0.10, 10.00],
            "documented_prices": {"input": 2.00, "cached_input": 0.10, "cache_write": 2.50, "output": 10.00},
            "default_reasoning_effort": "medium (model page: 'defaults to medium'; none and minimal unsupported)",
            "identifier": "alias gpt-6.1-sol (no dated snapshot listed)"},
}
SOURCES = ["https://developers.openai.com/api/docs/pricing", "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
           "https://developers.openai.com/api/docs/models/gpt-5-mini",
           "https://developers.openai.com/api/docs/guides/reasoning",
           "https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools"]
CASE_CAPS = {"R-mini": 0.006, "R-sol": 0.031, "E-mini": 0.15, "E-sol": 0.75}
E2E_INPUT_MARGIN = 1.25  # end-to-end inputs may exceed the v12 check's largest by this factor
E2E_SPEND_MARGIN = 2.0  # spend before the repair may be this multiple of the v12 check's, repriced
V12_E2E_TRACES = "artifacts/live/LC-route-v12-e2e/traces/*.json"
FILES = ["PROTOCOL.md", "freeze.py", "run_eval.py", "score.py"]
READ = [LC, V6, RV12, "eval/livecheck_routing_v12/DEV_GOLD.json", "eval/livecheck_i15_17/GOLD.json",
        "eval/livecheck_routing_v12/run_route.py", "eval/livecheck_routing_v12/score.py",
        "eval/livecheck_i15_17/run_case.py", "eval/livecheck_i15_17/score.py", "scripts/live_diagnose.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def slots() -> list[dict[str, Any]]:
    """Every execution, in order: routing, then end to end; the first model alternates (PROTOCOL.md, "Order")."""
    out: list[dict[str, Any]] = []
    for ci, (cid, rel) in enumerate(ROUTE_CASES):
        for rep in range(1, REPEATS + 1):
            for m in (("mini", "sol") if (ci + rep) % 2 == 1 else ("sol", "mini")):
                out.append({"run": f"R-{m}", "kind": "route", "model": m, "case": cid, "cases_file": rel,
                            "repeat": rep, "label": f"MC-dev-route-{m}-r{rep}"})
    for ci, (cid, rel) in enumerate(E2E_CASES):
        for m in (("mini", "sol") if ci % 2 == 0 else ("sol", "mini")):
            out.append({"run": f"E-{m}", "kind": "e2e", "model": m, "case": cid, "cases_file": rel, "repeat": 1,
                        "label": f"MC-dev-e2e-{m}"})
    for n, s in enumerate(out, 1):
        s["slot"] = n
    return out


def _cost(prices: list[float], fresh_in: float, cached_in: float, out: float) -> float:
    return (fresh_in * prices[0] + cached_in * prices[1] + out * prices[2]) / 1e6


def routing_reservations() -> dict[str, dict[str, float]]:
    """The exact worst-case reservation of each routing case's one call, per model: ``budget.worst_case_cost`` over
    the request the controller sends (route prompt, question, strict schema), at the model's accounting prices."""
    from nem_agent.agent.live import RouteDecision, prompt
    from nem_agent.tools.args import strict_json_schema

    fmt = {"type": "json_schema", "name": "RouteDecision", "schema": strict_json_schema(RouteDecision), "strict": True}
    cases: dict[str, str] = {}
    for cid, rel in ROUTE_CASES + E2E_CASES:
        cases[cid] = next(c["question"] for c in json.loads((REPO / rel).read_text())["cases"] if c["case_id"] == cid)
    out: dict[str, dict[str, float]] = {}
    for m, spec in MODELS.items():
        p = spec["accounting_prices"]
        out[m] = {}
        for cid, q in cases.items():
            req = {"instructions": prompt("route"), "input": [{"role": "user", "content": q}], "text": {"format": fmt}}
            chars = len(json.dumps(req, default=str))
            out[m][cid] = round((chars / 2 * p[0] + config.MAX_OUTPUT_TOKENS["route"] * p[2]) / 1e6, 6)
    return out


def e2e_bounds() -> dict[str, dict[str, float]]:
    """Bounded end-to-end reservations per model, from the v12 check's saved end-to-end traces: each stage's largest
    input (times ``E2E_INPUT_MARGIN``, counted as the ledger counts it, two characters per token at four characters
    per token) with that stage's output cap; and the largest spend before the repair, repriced (times
    ``E2E_SPEND_MARGIN``). The case cap must hold that spend plus the repair reservation."""
    largest: dict[str, int] = {}
    before_repair: list[dict[str, list[float]]] = []
    for f in sorted(glob.glob(str(REPO / V12_E2E_TRACES))):
        calls = [e for e in json.loads(Path(f).read_text())["events"] if e.get("kind") == "model" and e.get("usage")]
        tok = {"pre": [0.0, 0.0, 0.0]}
        for e in calls:
            u = e["usage"]
            largest[e["name"]] = max(largest.get(e["name"], 0), int(u["input_tokens"]))
            if e["name"] != "repair":
                cached = float((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
                tok["pre"][0] += float(u["input_tokens"]) - cached
                tok["pre"][1] += cached
                tok["pre"][2] += float(u["output_tokens"])
        before_repair.append(tok)
    out: dict[str, dict[str, float]] = {}
    for m, spec in MODELS.items():
        p = spec["accounting_prices"]
        res = {stage: round((2 * largest[stage] * E2E_INPUT_MARGIN * p[0]
                             + config.MAX_OUTPUT_TOKENS[stage] * p[2]) / 1e6, 6) for stage in largest}
        spend = max(_cost(p, *t["pre"]) for t in before_repair)
        need = round(E2E_SPEND_MARGIN * spend + max(res.get("repair", 0.0), res.get("synthesis", 0.0)), 6)
        out[m] = {**{f"reservation_{k}": v for k, v in res.items()}, "spend_before_repair_v12_repriced": round(spend, 6),
                  "case_cap_required": need}
    return out


def caps(route: dict[str, dict[str, float]], e2e: dict[str, dict[str, float]], plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Case and run caps (run cap = slots x case cap, so the start guard admits every slot even at its worst), checked
    against the reservations they must hold."""
    out: dict[str, Any] = {}
    for run, cap in CASE_CAPS.items():
        kind, m = run.split("-")
        n = sum(1 for s in plan if s["run"] == run)
        need = max(route[m].values()) if kind == "R" else e2e[m]["case_cap_required"]
        if cap < need:
            raise SystemExit(f"{run}: the case cap {cap} is below the {need} it must hold")
        out[run] = {"kind": "route" if kind == "R" else "e2e", "model": m, "slots": n, "case_cap_usd": cap,
                    "run_cap_usd": round(n * cap, 6), "case_cap_must_hold_usd": need}
    return out


def ledger_fingerprint() -> dict[str, Any]:
    p = budget.ledger_path()
    data = p.read_bytes()
    return {"ledger_start_usd": round(budget.spent(), 6), "ledger_lines": sum(1 for ln in data.splitlines() if ln.strip()),
            "ledger_sha256_prefix": hashlib.sha256(data).hexdigest()[:16]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-commit", default="HEAD")
    args = ap.parse_args()
    if os.environ.get("NEM_AGENT_BUDGET_LEDGER"):
        raise SystemExit("unset NEM_AGENT_BUDGET_LEDGER: the freeze records the real ledger")
    commit = git("rev-parse", args.code_commit)
    src_tree = git("rev-parse", f"{commit}:src")
    if src_tree != git("rev-parse", "HEAD:src") or git("status", "--porcelain", "--", "src"):
        raise SystemExit("the checkout's src/ is not the code commit's src/ tree, or is modified")
    plan = slots()
    route, e2e = routing_reservations(), e2e_bounds()
    runs = caps(route, e2e, plan)
    ledger = ledger_fingerprint()
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    e2e_slots = [s["slot"] for s in plan if s["kind"] == "e2e"]
    blind = rng.sample(e2e_slots, len(e2e_slots))
    files = {f"eval/model_comparison_dev/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files |= {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in READ}
    freeze = {
        "protocol": "Development comparison of gpt-5-mini and gpt-6.1-sol (eval/model_comparison_dev/PROTOCOL.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": commit, "code_tree": git("rev-parse", f"{commit}^{{tree}}"), "src_tree": src_tree,
        "prompts_tree": git("rev-parse", f"{commit}:src/nem_agent/{config.PROMPT_VERSION}"),
        "prompt_version": config.PROMPT_VERSION,
        "changes_before_any_run": ["2026-10-03, at the owner's request: S1 made absolute (zero H1-H5 violations for "
                                   "gpt-6.1-sol, automatic and both reviews); comparative safety reported separately; "
                                   "re-frozen against main 205974b (src/ tree unchanged)"],
        "max_output_tokens": config.MAX_OUTPUT_TOKENS, "max_model_calls": config.MAX_MODEL_CALLS,
        "reasoning_effort_sent": "not sent (each provider default applies)",
        "models": MODELS, "price_sources": SOURCES, "docs_read": DOCS_READ,
        "cost_labels": {"ledger": "ledger accounting at the accounting prices (conservative; not the billed amount)",
                        "documented": "documented list-price estimate from reported usage, cache writes included",
                        "billed": "actual billed cost: not observed (the API response does not carry it)"},
        **ledger,
        "runs": runs, "required_task_cap_usd": round(ledger["ledger_start_usd"] + sum(r["run_cap_usd"]
                                                                                      for r in runs.values()), 6),
        "routing_reservations_usd": route, "e2e_bounds_usd": e2e,
        "slots": plan, "review_blind_order": {f"A{i + 1:02d}": slot for i, slot in enumerate(blind)},
        "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: freeze[k] for k in ("code_commit", "src_tree", "prompt_version", "ledger_start_usd",
                                            "ledger_lines", "ledger_sha256_prefix", "required_task_cap_usd")}, indent=1))
    print(json.dumps({r: {k: v for k, v in x.items()} for r, x in runs.items()}, indent=1))
    print(json.dumps(e2e, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
