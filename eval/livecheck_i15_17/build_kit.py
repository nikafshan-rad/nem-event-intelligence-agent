"""Build the writer's and verifier's kit for the targeted Live check of I-15, I-16 and I-17, outside the repository
(PASS_RULE.md, "Preparation"). Adapted from eval/holdout_v6/build_kit.py.

The kit holds only:
- `BRIEF.md` and `VERIFY.md` (this directory's copies);
- `DATA.md`, byte-identical to v5's (the data files are the same);
- `data/`: copies of the pinned store (seven tables) and `corpus.sqlite`, byte-identical to the repository's;
  `events.json` (the 8 verified events and the analysis threshold); `development_material.json` (regions and intervals
  used in developing I-15 to I-17, from PASS_RULE.md);
- `venv/`: a fresh Python environment with only `duckdb` and `pytz`, at the repository's locked versions (the project
  package cannot be imported);
- `overlap/`: SHA-256 hashes of every 6-word sequence in the 138 earlier evaluation questions and in prompts v11, and a
  checker. No question text is in the kit;
- `out/`, empty.

Usage: python eval/livecheck_i15_17/build_kit.py KIT_DIR
"""

from __future__ import annotations

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
         "eval/holdout_v5/cases.json", "eval/holdout_v6/cases.json", "eval/live_check_2026_09_29/cases.json"]
TABLES = ["price_5min", "regionsum_5min", "opdemand_actual", "opdemand_forecast", "scada_5min", "duid_region",
          "weather_hourly"]
EVENT_FIELDS = ["event_id", "region", "timezone", "kind", "peak_interval_end_utc", "peak_interval_end_market", "peak_rrp",
                "window_start_utc", "window_end_utc", "intervals_meeting_threshold_in_window"]
# PASS_RULE.md, "Overlap with development material"
DEVELOPMENT = {
    "note": "Regions and intervals used in developing or testing the assistant's recent changes. Prefer other material; "
            "a case may use these only when its scenario cannot be met otherwise, and says so.",
    "items": [
        {"region": "TAS1", "local_day": "2026-08-06", "utc": ["2026-08-05T14:00:00Z", "2026-08-06T14:00:00Z"]},
        {"region": "NSW1", "half_hour_end_utc": "2026-07-28T21:30:00Z"},
        {"region": "NSW1", "half_hour_end_utc": "2026-07-30T21:30:00Z"},
        {"region": "SA1", "half_hour_end_utc": "2026-07-29T08:00:00Z"},
        {"region": "TAS1", "local_day": "2026-07-29", "utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]},
        {"region": "VIC1", "event_window_utc": ["2026-07-27T23:00:00Z", "2026-07-28T23:30:00Z"]},
        {"region": "VIC1", "local_day": "2026-07-29", "utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"]},
        {"region": "SA1", "event_window_utc": ["2026-07-30T04:30:00Z", "2026-07-31T05:00:00Z"]},
        {"region": "SA1", "local_day": "2026-07-31", "utc": ["2026-07-30T14:30:00Z", "2026-07-31T14:30:00Z"]},
    ]}

CHECKER = '''"""Compare the 6-word sequences of each question in out/cases_livecheck.json with hashed 6-word sequences of earlier
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


cases = json.loads((KIT / "out" / "cases_livecheck.json").read_text())["cases"]
flagged = [c["case_id"] for c in cases
           if any(hashlib.sha256(g.encode()).hexdigest() in HASHES for g in grams(c["question"]))]
print("cases with overlap:", ", ".join(flagged) if flagged else "none")
'''


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def main() -> int:
    kit = Path(sys.argv[1]).resolve()
    if kit.exists() or REPO in kit.parents or kit == REPO:
        raise SystemExit("the kit directory must be new and outside the repository")
    (kit / "data" / "store").mkdir(parents=True)
    (kit / "out").mkdir()
    (kit / "overlap").mkdir()
    shutil.copy(HERE / "BRIEF.md", kit / "BRIEF.md")
    shutil.copy(HERE / "VERIFY.md", kit / "VERIFY.md")
    shutil.copy(REPO / "eval" / "holdout_v5" / "DATA.md", kit / "DATA.md")
    for t in TABLES:
        shutil.copy(REPO / "data" / "store" / f"{t}.parquet", kit / "data" / "store" / f"{t}.parquet")
    shutil.copy(REPO / "data" / "index" / "corpus.sqlite", kit / "data" / "corpus.sqlite")
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    (kit / "data" / "events.json").write_text(json.dumps(
        {"analysis_threshold": sel["analysis_threshold"],
         "events": [{k: e[k] for k in EVENT_FIELDS if k in e} for e in sel["events"]]}, indent=1) + "\n")
    (kit / "data" / "development_material.json").write_text(json.dumps(DEVELOPMENT, indent=1) + "\n")
    prior = [c["question"] for p in PRIOR for c in json.loads((REPO / p).read_text())["cases"]]
    prompts = [f.read_text() for f in sorted((REPO / "src" / "nem_agent" / "prompts" / "v11").glob("*.md"))]
    hashes = sorted({hashlib.sha256(g.encode()).hexdigest() for t in prior + prompts for g in grams(t)})
    (kit / "overlap" / "hashes.json").write_text(json.dumps({"questions": len(prior), "prompt_files": len(prompts),
                                                             "sha256": hashes}) + "\n")
    (kit / "overlap" / "check_overlap.py").write_text(CHECKER)
    subprocess.run([sys.executable, "-m", "venv", str(kit / "venv")], check=True)
    lock = (REPO / "requirements.lock").read_text()
    pins = [ln.strip() for ln in lock.splitlines() if re.match(r"^(duckdb|pytz)==", ln.strip())]
    subprocess.run([str(kit / "venv" / "bin" / "pip"), "install", "-q", *pins], check=True)
    manifest = {str(p.relative_to(kit)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(kit.rglob("*")) if p.is_file() and "venv" not in p.relative_to(kit).parts}
    (kit / "MANIFEST.json").write_text(json.dumps({"earlier_questions": len(prior), "pins": pins, "files": manifest},
                                                  indent=1) + "\n")
    print(f"kit built at {kit}: {len(prior)} earlier questions and {len(prompts)} prompt files hashed "
          f"({len(hashes)} 6-word sequences); pins {pins}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
