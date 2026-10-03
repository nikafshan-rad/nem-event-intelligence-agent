"""Write FREEZE.json for the Live acceptance check of computed demand maxima (PROTOCOL.md). Offline: it reads the
ledger's total, line count and hash, never a key, and makes no call.

It records:
- **the code:** the commit under test, its full tree, its `src/` tree and its prompts tree (the checkout's `src/` must
  equal it);
- **the model** and its accounting prices;
- **the caps:** per case and per run, checked against a bound on the end-to-end reservation, from saved traces;
- **the plan:** the 16 cases in their frozen order, with their runs;
- **the starting ledger:** total, line count and SHA-256 prefix, which must equal the protocol's;
- **the blind review order:** A01-A16, shuffled once here;
- **the SHA-256 of every protocol file** and of every file the run reads.

It refuses to freeze unless `GOLD.json` and the independent check (`GOLD_CHECK.json`) agree exactly.

Usage: python eval/livecheck_maxima/freeze.py [--code-commit COMMIT]
"""

from __future__ import annotations

import argparse
import glob
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


def _sibling(name: str) -> Any:
    """A module of this directory, loaded under a name of its own (never a bare top-level name such as `score`, which
    other evaluation directories use)."""
    spec = importlib.util.spec_from_file_location(f"livecheck_maxima_{name}", HERE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gold_mod = _sibling("gold")


MODEL = "gpt-5-mini"
CODE_COMMIT = "761290d"
CASE_CAP = 0.15
RUN_OF = {"development": "D", "fresh": "F", "control": "R"}
LABEL = "LC-maxima-run"
LEDGER_START = (8.52205, 2905, "e8bcc3be401caec5")  # PROTOCOL.md, "Caps"
E2E_INPUT_MARGIN = 1.25  # end-to-end inputs may exceed the largest seen by this factor
E2E_SPEND_MARGIN = 2.0  # spend before the repair may be this multiple of the largest seen
E2E_TRACES = ["artifacts/live/LC-route-v12-e2e/traces/*.json", "artifacts/live/MC-dev-e2e-mini/traces/*.json"]
FILES = ["PROTOCOL.md", "BRIEF.md", "GOLD_CHECK_BRIEF.md", "REVIEW_BRIEF.md", "PROVENANCE.md", "cases.json", "GOLD.json",
         "GOLD_CHECK.json", "gold.py", "export.py", "run_case.py", "run_eval.py", "score.py", "build_kit.py", "freeze.py",
         "WRITER_OUTPUT.json", "WRITER_REPORT.md", "GOLD_CHECK_REPORT.md"]
READ = ["eval/livecheck_i15_17/cases.json", "eval/holdout_v6/cases.json", "eval/livecheck_i15_17/PASS_RULE.md"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def plan(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every case once, in cases.json's order (D01-D04, F01-F08, R01-R04), with its run."""
    return [{"slot": n, "run": RUN_OF[c["check_group"]], "case": c["case_id"]} for n, c in enumerate(cases, 1)]


def e2e_bound() -> dict[str, Any]:
    """A bound on one case's spend, at the model's accounting prices, from saved gpt-5-mini end-to-end traces: each
    stage's largest input (times ``E2E_INPUT_MARGIN``, counted as the ledger counts it, two characters per token at
    four characters per token) with that stage's output cap, and the largest spend before the repair (times
    ``E2E_SPEND_MARGIN``). The case cap must hold that spend plus the repair (or synthesis) reservation."""
    p = budget.prices(MODEL)
    assert p is not None
    largest: dict[str, int] = {}
    spends: list[float] = []
    files = sorted(f for g in E2E_TRACES for f in glob.glob(str(REPO / g)))
    for f in files:
        calls = [e for e in json.loads(Path(f).read_text())["events"] if e.get("kind") == "model" and e.get("usage")]
        pre = 0.0
        for e in calls:
            u = e["usage"]
            largest[e["name"]] = max(largest.get(e["name"], 0), int(u["input_tokens"]))
            if e["name"] != "repair":
                cached = float((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
                pre += ((float(u["input_tokens"]) - cached) * p[0] + cached * p[1] + float(u["output_tokens"]) * p[2]) / 1e6
        spends.append(pre)
    res = {stage: round((2 * n * E2E_INPUT_MARGIN * p[0] + config.MAX_OUTPUT_TOKENS[stage] * p[2]) / 1e6, 6)
           for stage, n in largest.items()}
    need = round(E2E_SPEND_MARGIN * max(spends) + max(res.get("repair", 0.0), res.get("synthesis", 0.0)), 6)
    return {"traces": len(files), "reservations_usd": res, "largest_spend_before_repair_usd": round(max(spends), 6),
            "case_cap_required_usd": need}


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
    diffs = gold_mod.compare(json.loads((HERE / "GOLD.json").read_text()),
                             json.loads((HERE / "GOLD_CHECK.json").read_text()))
    if diffs:
        raise SystemExit("GOLD.json and the independent check disagree:\n" + "\n".join(diffs))
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    slots = plan(cases)
    bound = e2e_bound()
    if bound["case_cap_required_usd"] > CASE_CAP:
        raise SystemExit(f"the case cap {CASE_CAP} is below the {bound['case_cap_required_usd']} it must hold")
    runs = {}
    for r in ("D", "F", "R"):
        n = sum(1 for s in slots if s["run"] == r)
        runs[r] = {"cases": n, "case_cap_usd": CASE_CAP, "run_cap_usd": round(n * CASE_CAP, 6)}
    ledger = ledger_fingerprint()
    got = (ledger["ledger_start_usd"], ledger["ledger_lines"], ledger["ledger_sha256_prefix"])
    if got != LEDGER_START:
        raise SystemExit(f"the ledger {got} is not the protocol's starting ledger {LEDGER_START}")
    rng = random.Random(int.from_bytes(os.urandom(8), "big"))
    blind = rng.sample([s["case"] for s in slots], len(slots))
    files = {f"eval/livecheck_maxima/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files |= {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in READ}
    p = budget.prices(MODEL)
    freeze = {
        "protocol": "Live acceptance check of computed demand maxima (eval/livecheck_maxima/PROTOCOL.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": commit, "code_tree": git("rev-parse", f"{commit}^{{tree}}"), "src_tree": src_tree,
        "prompts_tree": git("rev-parse", f"{commit}:src/nem_agent/{config.PROMPT_VERSION}"),
        "prompt_version": config.PROMPT_VERSION, "model": MODEL,
        "accounting_prices_per_mtok": {"input": p[0], "cached_input": p[1], "output": p[2]} if p else None,
        "max_output_tokens": config.MAX_OUTPUT_TOKENS, "max_model_calls": config.MAX_MODEL_CALLS,
        "reasoning_effort_sent": "not sent (the provider default applies)",
        **ledger,
        "runs": runs, "run_caps_total_usd": round(sum(r["run_cap_usd"] for r in runs.values()), 6),
        "required_task_cap_usd": round(ledger["ledger_start_usd"] + sum(r["run_cap_usd"] for r in runs.values()), 6),
        "e2e_bound": bound, "label": LABEL, "slots": slots,
        "review_blind_order": {f"A{i + 1:02d}": cid for i, cid in enumerate(blind)},
        "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: freeze[k] for k in ("code_commit", "src_tree", "prompts_tree", "prompt_version", "model",
                                            "ledger_start_usd", "ledger_lines", "ledger_sha256_prefix", "runs",
                                            "required_task_cap_usd", "e2e_bound")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
