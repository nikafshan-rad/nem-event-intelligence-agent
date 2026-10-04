"""Build the writer's and the reviewer's kits for the routing-only Live check of route contract v15 (PROTOCOL.md,
"Gold"), outside the repository. Offline; no model call.

- **writer:** `WRITER_BRIEF.md`, `CAPABILITIES.md`, `GOLD_FORMAT.md`, the data facts, a Python environment with the
  standard library only, and the overlap checker. The checker holds SHA-256 hashes of every 6-word sequence in the
  earlier questions (every `question` in `eval/` and `artifacts/live/`), in the prompts v16 files, in D28's and D29's
  test files and in `docs/decisions.md`. No earlier text is in the kit.
- **familiar:** adds `WRITER_BRIEF_FAMILIAR.md` and `familiar/questions.json` to an existing writer kit, after the
  writer's fresh questions are fixed. It refuses if `out/fresh.json` is missing.
- **reviewer:** `REVIEW_BRIEF.md`, `CAPABILITIES.md`, `GOLD_FORMAT.md`, the data facts, the same environment, and
  `questions.json`: the 17 questions with their request fields. It holds no gold, no intended reading and no set.

Each kit gets a `MANIFEST.json` with the SHA-256 of every file it holds (the environment aside).

Usage: python eval/livecheck_route_v15/build_kit.py writer|familiar|reviewer KIT_DIR
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
def _sibling(name: str) -> Any:
    """A module of this check, loaded by path under a unique name: this directory never goes on ``sys.path``, so
    another check's runner importing its own ``score`` or ``run_eval`` is never handed this one's."""
    spec = importlib.util.spec_from_file_location(f"livecheck_route_v15_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CFG = _sibling("configs")
FRESH, familiar_cases = _CFG.FRESH, _CFG.familiar_cases

EVENT_FIELDS = ["event_id", "region", "timezone", "kind", "peak_interval_end_utc", "peak_interval_end_market",
                "window_start_utc", "window_end_utc"]
OVERLAP_TEXTS = ["tests/provider/test_forecast_domain.py", "tests/provider/test_forecast_request.py",
                 "docs/decisions.md"]
CHECKER = '''"""Compare the 6-word sequences of each question in out/fresh.json with hashed 6-word sequences of earlier
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


cases = json.loads((KIT / "out" / "fresh.json").read_text())["cases"]
flagged = [c["config"] for c in cases
           if any(hashlib.sha256(g.encode()).hexdigest() in HASHES for g in grams(c["question"]))]
print("cases with overlap:", ", ".join(flagged) if flagged else "none")
'''
COVERAGE = """# The period the data covers

- **AEMO operational demand forecasts:** target half-hours ending between 2026-07-27T23:30:00Z and
  2026-08-20T11:30:00Z, in every region. Not every half-hour in that span is held.
- **Actual operational demand:** half-hours ending between 2025-10-03T18:30:00Z and 2026-08-20T11:30:00Z. Not every
  half-hour in that span is held.
- **Prices:** around the eight events in `events.json`.

So questions about forecasts should name a date between 28 July 2026 and 20 August 2026. The check does not answer
any question, so the data does not need to hold the answer.
"""


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _questions(o: Any) -> list[str]:
    """Every value of a `question` key, at any depth."""
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
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(kit / "venv")], check=True)


def _manifest(kit: Path, extra: dict[str, Any]) -> None:
    files = {str(p.relative_to(kit)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(kit.rglob("*")) if p.is_file() and "venv" not in p.relative_to(kit).parts}
    (kit / "MANIFEST.json").write_text(json.dumps({**extra, "files": files}, indent=1) + "\n")


def writer(kit: Path) -> None:
    _common(kit, "WRITER_BRIEF.md")
    (kit / "overlap").mkdir()
    prior = earlier_questions()
    prompts = [f.read_text() for f in sorted((REPO / "src" / "nem_agent" / "prompts" / "v16").glob("*.md"))]
    texts = [(REPO / rel).read_text() for rel in OVERLAP_TEXTS]
    hashes = sorted({hashlib.sha256(g.encode()).hexdigest() for t in prior + prompts + texts for g in grams(t)})
    (kit / "overlap" / "hashes.json").write_text(json.dumps({"questions": len(prior), "prompt_files": len(prompts),
                                                             "other_texts": OVERLAP_TEXTS, "sha256": hashes}) + "\n")
    (kit / "overlap" / "check_overlap.py").write_text(CHECKER)
    _manifest(kit, {"kit": "writer", "earlier_questions": len(prior), "prompt_files": len(prompts),
                    "fresh": [c for c, *_ in FRESH]})
    print(f"writer kit built at {kit}: {len(prior)} earlier questions, {len(prompts)} prompt files and "
          f"{len(texts)} other texts hashed ({len(hashes)} 6-word sequences)")


def familiar(kit: Path) -> None:
    if not (kit / "out" / "fresh.json").exists():
        raise SystemExit("the writer's fresh questions (out/fresh.json) are not written yet")
    if (kit / "familiar").exists():
        raise SystemExit("the familiar step was already added")
    fresh_sha = hashlib.sha256((kit / "out" / "fresh.json").read_bytes()).hexdigest()
    (kit / "familiar").mkdir()
    qs = [{"config": c["config"], "set": c["set"], "question": c["question"], "request": c["request"]}
          for c in familiar_cases()]
    (kit / "familiar" / "questions.json").write_text(json.dumps({"questions": qs}, indent=1) + "\n")
    shutil.copy(HERE / "WRITER_BRIEF_FAMILIAR.md", kit / "WRITER_BRIEF_FAMILIAR.md")
    (kit / "FAMILIAR_MANIFEST.json").write_text(json.dumps({
        "fresh_json_sha256_at_step_2": fresh_sha,
        "familiar/questions.json": hashlib.sha256((kit / "familiar" / "questions.json").read_bytes()).hexdigest(),
        "WRITER_BRIEF_FAMILIAR.md": hashlib.sha256((kit / "WRITER_BRIEF_FAMILIAR.md").read_bytes()).hexdigest()},
        indent=1) + "\n")
    print(f"familiar step added to {kit}: {len(qs)} questions; out/fresh.json SHA-256 {fresh_sha}")


def reviewer(kit: Path) -> None:
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    qs = [{"config": c["config"], "question": c["question"], "request": c["request"]} for c in cases]
    _common(kit, "REVIEW_BRIEF.md")
    (kit / "questions.json").write_text(json.dumps({"questions": qs}, indent=1) + "\n")
    _manifest(kit, {"kit": "reviewer", "questions": len(qs),
                    "cases_json_sha256": hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest()})
    print(f"reviewer kit built at {kit}: {len(qs)} questions")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("writer", "familiar", "reviewer"):
        raise SystemExit("usage: build_kit.py writer|familiar|reviewer KIT_DIR")
    kit = Path(sys.argv[2]).resolve()
    {"writer": writer, "familiar": familiar, "reviewer": reviewer}[sys.argv[1]](kit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
