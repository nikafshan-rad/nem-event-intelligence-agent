"""Build the writer's or the verifier's kit for the Live check of the v12 routing extraction (PASS_RULE.md), outside
the repository. Adapted from eval/structured_requests/build_kit.py.

- **Writer kit:** `BRIEF.md`; `DATA.md` (byte-identical to v5's); `data/` (copies of the pinned store tables and
  `events.json`); `venv/` (only `duckdb` and `pytz`, at the locked versions); `overlap/` (SHA-256 hashes of every
  6-word sequence in every earlier evaluation question, including the I-18 paraphrase matrix and the targeted check, and
  in prompts v11 and v12, with a checker); `out/`, empty. No parser pattern, fix code, development question or earlier
  question text.
- **Verifier kit:** `BRIEF.md`, `VERIFY.md`, `DATA.md`, `data/`, `venv/`; `dev/questions.json` (the 18 development
  questions and request fields) and `dev/DEV_GOLD.json`; `out/cases.json` (the writer's output, copied in).

Usage:
    python eval/livecheck_routing_v12/build_kit.py writer KIT_DIR
    python eval/livecheck_routing_v12/build_kit.py verifier KIT_DIR --cases WRITER_KIT/out/cases.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRIOR = ["eval/cases.json", "eval/holdout_v2/cases.json", "eval/holdout_v3/cases.json", "eval/holdout_v4/cases.json",
         "eval/holdout_v5/cases.json", "eval/holdout_v6/cases.json", "eval/live_check_2026_09_29/cases.json",
         "eval/livecheck_i15_17/cases.json", "eval/structured_requests/matrix.json"]
TABLES = ["price_5min", "regionsum_5min", "opdemand_actual", "opdemand_forecast"]
EVENT_FIELDS = ["event_id", "region", "timezone", "kind", "peak_interval_end_utc", "peak_interval_end_market", "peak_rrp",
                "window_start_utc", "window_end_utc", "intervals_meeting_threshold_in_window"]
DEV = [("Z03", "eval/holdout_v6/cases.json"), ("Z05", "eval/holdout_v6/cases.json"), ("Z04", "eval/holdout_v6/cases.json")] + \
    [(f"K{i:02d}", "eval/livecheck_i15_17/cases.json") for i in range(1, 16)]

CHECKER = '''"""Compare the 6-word sequences of each question in out/cases.json with hashed 6-word sequences of earlier
evaluation questions and the assistant's instructions. Only SHA-256 hashes are stored; no earlier text is in the kit."""
import hashlib
import json
import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
HASHES = set(json.loads((KIT / "overlap" / "hashes.json").read_text())["sha256"])


def grams(t, n=6):
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


cases = json.loads((KIT / "out" / "cases.json").read_text())["cases"]
flagged = [c["case_id"] for c in cases if any(hashlib.sha256(g.encode()).hexdigest() in HASHES for g in grams(c["question"]))]
print("cases with overlap:", ", ".join(flagged) if flagged else "none")
'''


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _common(kit: Path) -> None:
    (kit / "data" / "store").mkdir(parents=True)
    (kit / "out").mkdir()
    shutil.copy(HERE / "BRIEF.md", kit / "BRIEF.md")
    shutil.copy(REPO / "eval" / "holdout_v5" / "DATA.md", kit / "DATA.md")
    for t in TABLES:
        shutil.copy(REPO / "data" / "store" / f"{t}.parquet", kit / "data" / "store" / f"{t}.parquet")
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    (kit / "data" / "events.json").write_text(json.dumps(
        {"analysis_threshold": sel["analysis_threshold"],
         "events": [{k: e[k] for k in EVENT_FIELDS if k in e} for e in sel["events"]]}, indent=1) + "\n")
    subprocess.run([sys.executable, "-m", "venv", str(kit / "venv")], check=True)
    lock = (REPO / "requirements.lock").read_text()
    pins = [ln.strip() for ln in lock.splitlines() if re.match(r"^(duckdb|pytz)==", ln.strip())]
    subprocess.run([str(kit / "venv" / "bin" / "pip"), "install", "-q", *pins], check=True)


def _manifest(kit: Path, extra: dict[str, object]) -> None:
    files = {str(p.relative_to(kit)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(kit.rglob("*")) if p.is_file() and "venv" not in p.relative_to(kit).parts}
    (kit / "MANIFEST.json").write_text(json.dumps({**extra, "files": files}, indent=1) + "\n")


def writer(kit: Path) -> None:
    _common(kit)
    (kit / "overlap").mkdir()
    prior = [c["question"] for p in PRIOR for c in json.loads((REPO / p).read_text())["cases"]]
    prompts = [f.read_text() for v in ("v11", "v12")
               for f in sorted((REPO / "src" / "nem_agent" / "prompts" / v).glob("*.md"))]
    hashes = sorted({hashlib.sha256(g.encode()).hexdigest() for t in prior + prompts for g in grams(t)})
    (kit / "overlap" / "hashes.json").write_text(json.dumps({"questions": len(prior), "prompt_files": len(prompts),
                                                             "sha256": hashes}) + "\n")
    (kit / "overlap" / "check_overlap.py").write_text(CHECKER)
    _manifest(kit, {"role": "writer", "earlier_questions": len(prior), "prompt_files": len(prompts)})
    print(f"writer kit at {kit}: {len(prior)} earlier questions and {len(prompts)} prompt files hashed "
          f"({len(hashes)} 6-word sequences)")


def verifier(kit: Path, cases: Path) -> None:
    _common(kit)
    shutil.copy(HERE / "VERIFY.md", kit / "VERIFY.md")
    (kit / "dev").mkdir()
    files: dict[str, dict[str, dict[str, object]]] = {}
    qs = []
    for cid, rel in DEV:
        if rel not in files:
            files[rel] = {c["case_id"]: c for c in json.loads((REPO / rel).read_text())["cases"]}
        c = files[rel][cid]
        qs.append({"case_id": cid, "question": c["question"], "request": c.get("request") or {}})
    (kit / "dev" / "questions.json").write_text(json.dumps({"cases": qs}, indent=1) + "\n")
    shutil.copy(HERE / "DEV_GOLD.json", kit / "dev" / "DEV_GOLD.json")
    shutil.copy(cases, kit / "out" / "cases.json")
    _manifest(kit, {"role": "verifier", "dev_questions": len(qs)})
    print(f"verifier kit at {kit}: {len(qs)} development questions; cases from {cases}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("role", choices=["writer", "verifier"])
    ap.add_argument("kit")
    ap.add_argument("--cases", help="verifier: the writer's out/cases.json")
    args = ap.parse_args()
    kit = Path(args.kit).resolve()
    if kit.exists() or REPO in kit.parents or kit == REPO:
        raise SystemExit("the kit directory must be new and outside the repository")
    if args.role == "writer":
        writer(kit)
    else:
        if not args.cases:
            raise SystemExit("--cases is required for the verifier kit")
        verifier(kit, Path(args.cases).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
