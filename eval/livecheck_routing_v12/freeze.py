"""Write FREEZE.json for the Live check of the v12 routing extraction (PASS_RULE.md, "What is frozen"). Offline; it
reads the ledger total, never a key, and makes no call.

It records:
- **the code under test:** the commit, its full tree, its `src/` tree and its prompts tree; the current checkout's
  `src/` must equal it;
- **the model and prompt version;**
- **the starting balance:** the real ledger total, and its line count;
- **the caps:** per case and per run, for each run, and the task cap they require;
- **the run plans:** each run's label, kind (routing only, or end to end) and cases, in order;
- **the SHA-256 of every protocol file,** and of every file the runs read (cases, gold, the reused runner and scorer).

Usage: python eval/livecheck_routing_v12/freeze.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget, config  # noqa: E402

CODE_COMMIT = "f2455ca33ca1f60293a4ccb849ebc2f00da61f51"
ROUTE_CASE_CAP, E2E_CASE_CAP = 0.01, 0.15
CAPS = {"R-dev": 0.10, "R-fresh": 0.15, "E-dev": 0.50}
LC = "eval/livecheck_i15_17/cases.json"
V6 = "eval/holdout_v6/cases.json"
FILES = ["PASS_RULE.md", "BRIEF.md", "VERIFY.md", "DEV_GOLD.json", "cases.json", "VERIFICATION.json", "PROVENANCE.md",
         "build_kit.py", "freeze.py", "run_eval.py", "run_route.py", "score.py"]
READ = [LC, V6, "eval/livecheck_i15_17/GOLD.json", "eval/livecheck_i15_17/run_case.py",
        "eval/livecheck_i15_17/score.py", "scripts/live_diagnose.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def plan() -> dict[str, dict[str, object]]:
    dev = [["Z03", V6], ["Z05", V6], ["Z04", V6]] + [[f"K{i:02d}", LC] for i in range(1, 16)]
    fresh = [[c["case_id"], "eval/livecheck_routing_v12/cases.json"]
             for c in json.loads((HERE / "cases.json").read_text())["cases"]]
    e2e = [[c, LC] for c in ("K05", "K06", "K07", "K09", "K10")]
    return {
        "R-dev": {"label": "LC-route-v12-dev", "kind": "route", "run_cap_usd": CAPS["R-dev"],
                  "case_cap_usd": ROUTE_CASE_CAP, "n_cases": len(dev), "cases": dev},
        "R-fresh": {"label": "LC-route-v12-fresh", "kind": "route", "run_cap_usd": CAPS["R-fresh"],
                    "case_cap_usd": ROUTE_CASE_CAP, "n_cases": len(fresh), "cases": fresh},
        "E-dev": {"label": "LC-route-v12-e2e", "kind": "e2e", "run_cap_usd": CAPS["E-dev"],
                  "case_cap_usd": E2E_CASE_CAP, "n_cases": len(e2e), "cases": e2e},
    }


def main() -> int:
    if os.environ.get("NEM_AGENT_BUDGET_LEDGER"):
        raise SystemExit("unset NEM_AGENT_BUDGET_LEDGER: the freeze records the real ledger")
    src_tree = git("rev-parse", f"{CODE_COMMIT}:src")
    if git("rev-parse", "HEAD:src") != src_tree or git("status", "--porcelain", "--", "src"):
        raise SystemExit("the checkout's src/ is not the code under test")
    ledger = budget.spent()
    lines = sum(1 for ln in budget.ledger_path().read_text().splitlines() if ln.strip())
    files = {f"eval/livecheck_routing_v12/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files |= {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in READ}
    freeze = {
        "protocol": "Live check of the v12 routing extraction (eval/livecheck_routing_v12/PASS_RULE.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": CODE_COMMIT, "code_tree": git("rev-parse", f"{CODE_COMMIT}^{{tree}}"), "src_tree": src_tree,
        "prompts_tree": git("rev-parse", f"{CODE_COMMIT}:src/nem_agent/prompts/v12"),
        "prompt_version": config.PROMPT_VERSION, "model": "gpt-5-mini",
        "ledger_start_usd": round(ledger, 6), "ledger_lines": lines,
        "runs": plan(), "order": list(CAPS),
        "required_task_cap_usd": round(ledger + sum(CAPS.values()), 6),
        "standing_task_cap_usd": config.LIVE_TOTAL_BUDGET_USD,
        "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: v for k, v in freeze.items() if k not in ("files_sha256", "runs")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
