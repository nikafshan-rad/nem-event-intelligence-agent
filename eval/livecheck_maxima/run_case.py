"""Run one case of the Live acceptance check of computed demand maxima (PROTOCOL.md) and save its full record with
the new exporter (`export.py`). The frozen exporters are not used.

It runs the case with the evaluation's own `run_system_case` (which also produces the automatic score fields). It
counts the case-note files before and after, and saves:
- `<label>/<case>.json`: the full record;
- `<label>/traces/<trace_id>.json`: the trace.

Its output lines are read by the runner:
- `STOPPED:` a budget stop; nothing is saved;
- `ERROR`: an API or other failure, with `<case>.error.json` saved;
- otherwise one summary line.

The API key is never read here, never printed and never written: the OpenAI SDK reads it from the environment.

Usage: python eval/livecheck_maxima/run_case.py --case D01 --label LC-maxima-run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
from nem_agent import budget, paths  # noqa: E402
from nem_agent.evaluation import runner  # noqa: E402


def _sibling(name: str) -> Any:
    """A module of this directory, loaded under a name of its own (never a bare top-level name such as `score`, which
    other evaluation directories use)."""
    spec = importlib.util.spec_from_file_location(f"livecheck_maxima_{name}", HERE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export = _sibling("export")



def case_note_files() -> int:
    """Files in the local case-note store (proposals, approvals, notes): an investigation must never add any."""
    return sum(1 for f in paths.case_notes_dir().rglob("*") if f.is_file())


def cases() -> dict[str, dict[str, Any]]:
    return {c["case_id"]: c for c in json.loads((HERE / "cases.json").read_text())["cases"]}


def run_one(case: dict[str, Any], out_dir: Path, mode: str = "live") -> str:
    """Run and save one case; returns the line the runner reads. ``mode`` is "live" in the check (tests use the fake
    transport through it)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cid = case["case_id"]
    before, notes = budget.spent(), case_note_files()
    keep: dict[str, Any] = {}
    try:
        row = runner.run_system_case(case, mode, keep=keep)
    except budget.BudgetExceeded as exc:
        return f"[{cid}] STOPPED: {exc}"
    except Exception as exc:  # an API failure ends this case; what it cost stays in the ledger
        err = {"case_id": cid, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
               "ledger_cost_usd": round(budget.spent() - before, 6)}
        (out_dir / f"{cid}.error.json").write_text(json.dumps(err, indent=2) + "\n")
        return f"[{cid}] ERROR {err['error']} (ledger cost {err['ledger_cost_usd']} USD, counted at worst case)"
    res = keep["result"]
    rec = export.record(case, row, res, notes_written=case_note_files() - notes,
                        ledger_cost=round(budget.spent() - before, 6))
    (out_dir / f"{cid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    src = paths.artifacts_dir() / "traces" / f"{rec['trace_id']}.json"
    (out_dir / "traces").mkdir(exist_ok=True)
    if src.exists():
        shutil.copy(src, out_dir / "traces" / src.name)
    else:  # a trace not written to disk (tests): saved from the result itself
        (out_dir / "traces" / src.name).write_text(json.dumps(res.trace.as_dict(), indent=1, default=str) + "\n")
    s = rec["score"]
    return (f"[{cid}] status={s.get('status')} format={rec['report'].get('schema_version')} "
            f"answer={len(rec['report'].get('answer') or [])} fallback={s.get('fallback_applied')} "
            f"calls={s.get('model_calls')} cost={s.get('ledger_cost_usd')} latency_ms={s.get('latency_ms')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        print("UNVERIFIED: OPENAI_API_KEY is not set; nothing run")
        return 3
    line = run_one(cases()[args.case], paths.artifacts_dir() / "live" / args.label)
    print(line)
    print(f"task spent {budget.spent()} of {budget.total_budget()} USD")
    return 1 if "] ERROR" in line else 0


if __name__ == "__main__":
    raise SystemExit(main())
