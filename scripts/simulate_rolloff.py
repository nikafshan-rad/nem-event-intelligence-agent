#!/usr/bin/env python
"""Simulate a fresh setup AFTER NEMWeb's rolling "Current" folder has dropped every file pinned there.

What it does:

1. Builds an isolated project home (``--home``) containing the committed selection, the evaluation cases and the
   already-verified Archive/document/API bytes. These bytes are identical to what a fresh download returns and are
   reused only to save bandwidth. **No file from NEMWeb Current is copied.**
2. Runs the README steps and the evaluation with ``NEM_AGENT_SIMULATE_ROLLED_OFF=1``, so every NEMWeb
   ``Reports/Current`` URL answers a simulated 404. That covers the 198 market notices, the 4 August next-day
   actual-demand files and the 60 probe-only price files.
3. Records exit codes and the key outputs in ``--out`` (JSON). Nothing is fabricated; every value is read back from
   the commands' own outputs.

Usage: python scripts/simulate_rolloff.py --home /tmp/rolloff_home --out artifacts/rolloff_simulation.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import rawstore  # noqa: E402
from nem_agent.selection import load_selection  # noqa: E402

DOC07 = "What did AEMO's market notice say about the City West transformer in SA1 on 2026-07-30?"


def _link_or_copy(src: str | Path, dst: str | Path) -> None:
    try:
        os.link(src, dst)
    except OSError:  # different filesystem: copy the bytes instead
        shutil.copy2(src, dst)


def prepare(home: Path) -> dict[str, int]:
    if home.exists():
        shutil.rmtree(home)
    (home / "data").mkdir(parents=True)
    for f in ("source_selection.json", "SOURCES.md"):
        shutil.copy2(REPO / "data" / f, home / "data" / f)
    shutil.copytree(REPO / "eval", home / "eval")
    if (REPO / "data" / "models").exists():
        shutil.copytree(REPO / "data" / "models", home / "data" / "models", copy_function=_link_or_copy)
    sel = load_selection(REPO / "data" / "source_selection.json")
    copied = skipped = 0
    for s in sel.sources:
        if s.container_kind == "current":
            skipped += 1
            continue
        src = rawstore.local_path_for(s.dataset, s.url)  # REPO cache (NEM_AGENT_HOME unset here)
        if not src.exists():
            continue
        rel = src.relative_to(REPO / "data" / "raw")
        dst = home / "data" / "raw" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        _link_or_copy(src, dst)
        _link_or_copy(src.with_name(src.name + ".meta.json"), dst.with_name(dst.name + ".meta.json"))
        copied += 1
    return {"verified_non_current_files_reused": copied, "current_files_not_copied": skipped}


def run(cmd: list[str], env: dict[str, str], keep: tuple[str, ...]) -> dict:
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=3600)
    out = (p.stdout + p.stderr).splitlines()
    lines = [ln for ln in out if any(k in ln for k in keep)]
    return {"cmd": " ".join(cmd[2:] if cmd[1] == "-m" else cmd[1:]), "exit": p.returncode,
            "seconds": round(time.monotonic() - t0, 1), "key_lines": lines[-12:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", default="artifacts/rolloff_simulation.json")
    args = ap.parse_args()
    home = Path(args.home).resolve()
    prep = prepare(home)
    env = {**os.environ, "NEM_AGENT_HOME": str(home), "NEM_AGENT_SIMULATE_ROLLED_OFF": "1"}
    env.pop("OPENAI_API_KEY", None)
    py = sys.executable
    keep = ("WARNING", "ROLLED OFF", "RECOVERED", "data_version", "corpus_version", "FAIL", "PASS", "passed", "failed",
            "skipped", "Traceback", "Error", "status")
    steps = [
        run([py, "-m", "nem_agent.cli", "build-data"], env, keep),
        run([py, "-m", "nem_agent.cli", "data-check"], env, ("DATA-CHECK", "rolled_off", "no_failed_sources")),
        run([py, "-m", "nem_agent.cli", "build-index"], env, keep),
        run([py, "-m", "nem_agent.cli", "investigate", "--region", "SA1", "--event", "2026-07-31",
             "--out", str(home / "artifacts" / "replay_case.json")], env, keep),
        run([py, "-m", "nem_agent.cli", "investigate", "--question", DOC07,
             "--out", str(home / "artifacts" / "notice_question.json")], env, keep),
        run([py, "-m", "nem_agent.cli", "eval", "--out", str(home / "artifacts" / "eval" / "offline.json")], env,
            ("EVAL",)),
        run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], env, ("passed", "failed", "error")),
    ]
    failed_steps = [s for s in steps if s["exit"] != 0]
    if failed_steps:  # record what happened instead of crashing on missing outputs
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"preparation": prep, "steps": steps, "status": "incomplete"}, indent=2))
        print(json.dumps({s["cmd"][:60]: s["exit"] for s in steps}, indent=2))
        return 1
    rep = json.loads((home / "artifacts" / "replay_case.json").read_text())["report"]
    q = json.loads((home / "artifacts" / "notice_question.json").read_text())["report"]
    ev = json.loads((home / "artifacts" / "eval" / "offline.json").read_text())
    snap = json.loads((home / "data" / "store" / "snapshot.json").read_text())
    man = json.loads((home / "data" / "index" / "index_manifest.json").read_text())
    ret = json.loads(subprocess.run(
        [py, "-c", "import json; from nem_agent.evaluation.retrieval_eval import evaluate; r=evaluate(); "
                   "print(json.dumps({k: r[k] for k in ('recall_at_k','hit_at_k','mrr_at_k',"
                   "'labelled_items_unavailable_in_corpus','queries_unavailable_in_corpus')}))"],
        cwd=REPO, env=env, capture_output=True, text=True).stdout)
    t = ev["summary"]["system_test"]
    result = {
        "simulation": "NEM_AGENT_SIMULATE_ROLLED_OFF=1: every NEMWeb Reports/Current URL answers a simulated 404",
        "preparation": prep,
        "steps": steps,
        "store": {"data_version": snap["data_version"], "row_counts": snap["row_counts"],
                  "failed_sources": sorted(snap["failed_sources"]), "rolled_off_sources": sorted(snap["rolled_off_sources"])},
        "index": {"corpus_version": man["corpus_version"], "n_chunks": man["n_chunks"],
                  "chunks_by_doc_type": man["chunks_by_doc_type"], "rolled_off_sources": len(man["rolled_off_sources"]),
                  "failed_sources": man["failed_sources"]},
        "primary_event_report": {"status": rep["status"], "headline": rep["headline"],
                                 "published_findings": len(rep["published_findings"]),
                                 "notice_gap_message": [m for m in rep["missing_evidence"] if "market notices" in m],
                                 "uncertainties_about_notices": [u for u in rep["uncertainties"] if "notice" in u],
                                 "validation_passed": rep["validation"].get("final_passed")},
        "notice_question_report": {"status": q["status"], "headline": q["headline"][:300],
                                   "citations": [c["doc_id"] for c in q["citations"]],
                                   "notice_gap_message": [m for m in q["missing_evidence"] if "market notices" in m]},
        "evaluation_test_split": {"gate_checks_all_true": all(ev["gate_checks"].values()),
                                  "failed_gate_checks": [k for k, v in ev["gate_checks"].items() if not v],
                                  "status_ok": t["status_ok"], "gold_numbers": t["gold_numbers"],
                                  "gold_forecast": t["gold_forecast"], "gold_citation": t["gold_citation"],
                                  "corpus_unavailable_cases": t["corpus_unavailable_cases"], "as_of_leaks": t["as_of_leaks"]},
        "retrieval_eval": ret,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2).replace(str(home), "<sim-home>") + "\n")
    print(json.dumps({s["cmd"][:60]: s["exit"] for s in steps}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
