"""Build the writer's and the reviewer's kits for the comparison (PROTOCOL.md, "The gold"), outside the repository.
Offline; no model call. Adapted from eval/livecheck_route_v15/build_kit.py (frozen, unchanged).

- **writer:** `WRITER_BRIEF.md`, `CAPABILITIES.md`, `GOLD_FORMAT.md`, the data facts, and the overlap checker. The
  checker holds SHA-256 hashes of every 6-word sequence in the earlier questions (every `question` in `eval/` and
  `artifacts/live/`), in the prompts v16 and v17 files, in the D31 test files and in `docs/decisions.md`. No earlier
  text is in the kit.
- **reviewer:** `REVIEW_BRIEF.md`, `CAPABILITIES.md`, `GOLD_FORMAT.md`, the data facts, and `questions.json`: all 69
  questions with their request fields under neutral IDs (R01–R69, in an order shuffled once), with no gold, family or
  set. The ID mapping is written to this directory (`REVIEW_IDS.json`), never to the kit. Needs `WRITER_OUTPUT.json`.

The agents use the machine's Python (standard library and `zoneinfo`); the kit holds no environment of its own.
Each kit gets a `MANIFEST.json` with the SHA-256 of every file it holds.

Usage: python eval/compare_route_v15_v16/build_kit.py writer|reviewer KIT_DIR
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"compare_route_v15_v16_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EVENT_FIELDS = ["event_id", "region", "timezone", "kind", "peak_interval_end_utc", "peak_interval_end_market",
                "window_start_utc", "window_end_utc"]
OVERLAP_TEXTS = ["tests/provider/test_request_plan.py", "tests/provider/test_request_plan_review.py",
                 "tests/provider/test_forecast_domain.py", "tests/provider/test_forecast_request.py",
                 "docs/decisions.md"]
CHECKER = '''"""Compare the 6-word sequences of each question in out/heldout.json with hashed 6-word sequences of earlier
questions and of the assistant's instructions. Only SHA-256 hashes are stored; no earlier text is in the kit."""
import hashlib
import json
import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
HASHES = set(json.loads((KIT / "overlap" / "hashes.json").read_text())["sha256"])


def grams(t, n=6):
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


cases = json.loads((KIT / "out" / "heldout.json").read_text())["cases"]
flagged = [c["config"] for c in cases
           if any(hashlib.sha256(g.encode()).hexdigest() in HASHES for g in grams(c["question"]))]
print("cases with overlap:", ", ".join(flagged) if flagged else "none")
'''
COVERAGE = """# The period the data covers

- **AEMO operational demand forecasts:** target half-hours ending between 2026-07-27T23:30:00Z and
  2026-08-20T11:30:00Z, in every region. Not every half-hour in that span is held.
- **Actual operational demand:** half-hours ending between 2025-10-03T18:30:00Z and 2026-08-20T11:30:00Z. Not every
  half-hour in that span is held.
- **Dispatch total demand and prices:** around the eight events in `events.json`.

So forecast questions should name a date between 28 July 2026 and 20 August 2026. The comparison does not answer any
question, so the data does not need to hold the answer.
"""
REVIEW_ORDER_SEED = 20261005


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _questions(o: Any) -> list[str]:
    if isinstance(o, dict):
        return [v for k, v in o.items() if k == "question" and isinstance(v, str)] + \
            [q for v in o.values() for q in _questions(v)]
    if isinstance(o, list):
        return [q for v in o for q in _questions(v)]
    return []


def earlier_questions() -> list[str]:
    out: set[str] = set()
    for root in (REPO / "eval", REPO / "artifacts" / "live"):
        for p in sorted(root.rglob("*.json")):
            if HERE in p.parents:
                continue
            try:
                out.update(_questions(json.loads(p.read_text())))
            except (ValueError, UnicodeDecodeError):
                continue
    return sorted(out)


def _common(kit: Path, brief: str) -> None:
    if kit.exists() or REPO in kit.parents or kit == REPO:
        raise SystemExit("the kit directory must be new and outside the repository")
    for d in ("data", "work", "out"):
        (kit / d).mkdir(parents=True)
    for f in (brief, "CAPABILITIES.md", "GOLD_FORMAT.md"):
        shutil.copy(HERE / f, kit / f)
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    events = [{k: e[k] for k in EVENT_FIELDS if k in e} for e in sel["events"]]
    (kit / "data" / "events.json").write_text(json.dumps({"events": events}, indent=1) + "\n")
    (kit / "data" / "coverage.md").write_text(COVERAGE)


def _manifest(kit: Path, extra: dict[str, Any]) -> None:
    files = {str(p.relative_to(kit)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(kit.rglob("*")) if p.is_file()}
    (kit / "MANIFEST.json").write_text(json.dumps({**extra, "files": files}, indent=1) + "\n")


def writer(kit: Path) -> None:
    _common(kit, "WRITER_BRIEF.md")
    (kit / "overlap").mkdir()
    prior = earlier_questions()
    prompts = [f.read_text() for v in ("v16", "v17")
               for f in sorted((REPO / "src" / "nem_agent" / "prompts" / v).glob("*.md"))]
    texts = [(REPO / rel).read_text() for rel in OVERLAP_TEXTS]
    hashes = sorted({hashlib.sha256(g.encode()).hexdigest() for t in prior + prompts + texts for g in grams(t)})
    (kit / "overlap" / "hashes.json").write_text(json.dumps({"questions": len(prior), "prompt_files": len(prompts),
                                                             "other_texts": OVERLAP_TEXTS, "sha256": hashes}) + "\n")
    (kit / "overlap" / "check_overlap.py").write_text(CHECKER)
    _manifest(kit, {"kit": "writer", "earlier_questions": len(prior), "prompt_files": len(prompts)})
    print(f"writer kit built at {kit}: {len(prior)} earlier questions, {len(prompts)} prompt files and "
          f"{len(texts)} other texts hashed ({len(hashes)} 6-word sequences)")


def reviewer(kit: Path) -> None:
    cfg = _sibling("configs")
    written = json.loads((HERE / "WRITER_OUTPUT.json").read_text())["cases"]
    qs = [{"question": c["question"], "request": c.get("request") or {}, "_config": c["config"]}
          for c in [*cfg.development_cases(), *written]]
    if len(qs) != 69:
        raise SystemExit(f"expected 69 questions, got {len(qs)}")
    random.Random(REVIEW_ORDER_SEED).shuffle(qs)
    ids = {f"R{i:02d}": q.pop("_config") for i, q in enumerate(qs, 1)}
    for i, q in enumerate(qs, 1):
        q["config"] = f"R{i:02d}"
    _common(kit, "REVIEW_BRIEF.md")
    (kit / "questions.json").write_text(json.dumps({"questions": [{"config": q["config"], "question": q["question"],
                                                                     "request": q["request"]} for q in qs]},
                                                   indent=1) + "\n")
    (HERE / "REVIEW_IDS.json").write_text(json.dumps({"seed": REVIEW_ORDER_SEED, "ids": ids}, indent=1) + "\n")
    _manifest(kit, {"kit": "reviewer", "questions": len(qs),
                    "writer_output_sha256": hashlib.sha256((HERE / "WRITER_OUTPUT.json").read_bytes()).hexdigest()})
    print(f"reviewer kit built at {kit}: {len(qs)} questions under neutral IDs; mapping in REVIEW_IDS.json")


def main() -> int:
    modes = {"writer": writer, "reviewer": reviewer}
    if len(sys.argv) != 3 or sys.argv[1] not in modes:
        raise SystemExit("usage: build_kit.py writer|reviewer KIT_DIR")
    os.umask(0o022)
    modes[sys.argv[1]](Path(sys.argv[2]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
