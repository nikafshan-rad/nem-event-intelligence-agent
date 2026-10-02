"""Write FREEZE.json for the targeted Live check (PASS_RULE.md, "What is frozen"). Offline; it reads the ledger total,
never a key, and makes no call.

It records:
- **the code under test:** the commit, its full tree, its `src/` tree and its prompts tree, which must equal the
  current checkout's `src/`;
- **the model and prompt version;**
- **the starting balance:** the real ledger total, and its line count;
- **the caps,** and the task cap they require;
- **the run plans;**
- **the SHA-256 of every protocol file** and of the case files the runs read.

Usage: python eval/livecheck_i15_17/freeze.py
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

CODE_COMMIT = "cf9558e9e16ab170fe7b4683a2c803c06a8ec4da"
CASE_CAP, D1_CAP, D2_CAP = 0.15, 0.45, 1.00
FILES = ["PASS_RULE.md", "DEVCHECK.json", "BRIEF.md", "VERIFY.md", "cases.json", "VERIFICATION.json", "PROVENANCE.md",
         "GOLD.json", "LABELS.json", "build_kit.py", "labels.py", "freeze.py", "run_eval.py", "run_case.py", "score.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    if os.environ.get("NEM_AGENT_BUDGET_LEDGER"):
        raise SystemExit("unset NEM_AGENT_BUDGET_LEDGER: the freeze records the real ledger")
    src_tree = git("rev-parse", f"{CODE_COMMIT}:src")
    if git("rev-parse", "HEAD:src") != src_tree or git("status", "--porcelain", "--", "src"):
        raise SystemExit("the checkout's src/ is not the code under test")
    ledger = budget.spent()
    lines = sum(1 for ln in budget.ledger_path().read_text().splitlines() if ln.strip())
    dev = json.loads((HERE / "DEVCHECK.json").read_text())
    fresh = json.loads((HERE / "cases.json").read_text())["cases"]
    runs = {
        "D1": {"label": dev["label"], "run_cap_usd": D1_CAP, "n_cases": len(dev["cases"]),
               "cases": [[c["case_id"], dev["cases_file"]] for c in dev["cases"]]},
        "D2": {"label": "LC-i15-17-fresh", "run_cap_usd": D2_CAP, "n_cases": len(fresh),
               "cases": [[c["case_id"], "eval/livecheck_i15_17/cases.json"] for c in fresh]},
    }
    files = {f"eval/livecheck_i15_17/{f}": hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in FILES}
    files[dev["cases_file"]] = hashlib.sha256((REPO / dev["cases_file"]).read_bytes()).hexdigest()
    freeze = {
        "protocol": "targeted Live check of I-15, I-16 and I-17 (eval/livecheck_i15_17/PASS_RULE.md)",
        "frozen_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": CODE_COMMIT, "code_tree": git("rev-parse", f"{CODE_COMMIT}^{{tree}}"), "src_tree": src_tree,
        "prompts_tree": git("rev-parse", f"{CODE_COMMIT}:src/nem_agent/prompts/v11"),
        "prompt_version": config.PROMPT_VERSION, "model": "gpt-5-mini",
        "ledger_start_usd": round(ledger, 6), "ledger_lines": lines,
        "case_cap_usd": CASE_CAP, "runs": runs,
        "required_task_cap_usd": round(ledger + D1_CAP + D2_CAP, 6),
        "standing_task_cap_usd": config.LIVE_TOTAL_BUDGET_USD,
        "files_sha256": files,
    }
    (HERE / "FREEZE.json").write_text(json.dumps(freeze, indent=1) + "\n")
    print(json.dumps({k: v for k, v in freeze.items() if k != "files_sha256"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
