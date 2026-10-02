"""The unused pool for run B (PASS_RULE.md, "Run B: composition, and familiar and unused material"), and its check at
the freeze.

"Unused" means not previously used in evaluation or fix development. It is decided by a search of every tracked file
outside `data/` (the source data), as the repository stood at the frozen code commit `6413076`: tests, docs, logs,
eval files, saved Live records and traces, and code. Later commits only define the pool and the protocol (the
proposal in `docs/live-gates.md`, the tracker, and `eval/holdout_v6/`), and they name pool members to do so, so they
are not searched; `--check` lists every file changed since `6413076`, to show that nothing else was added.
- **A market notice is unused** if no such file names its document ID or its notice number.
- **A region-day is unused** if it has a full day of 5-minute prices and no line of such a file names that region
  together with that date.

It prints IDs and counts only, never a question, gold value or answer, so the developer stays blind to the set.

Usage:
    python eval/holdout_v6/provenance_check.py --pool OUT.json       # write the pool (the writer's kit gets it)
    python eval/holdout_v6/provenance_check.py --check CASES.json    # at the freeze: each unused case against the pool
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

BASE = "64130767ea06e2cc7bfadb679adbc4da11a7502b"  # the frozen code commit (the merge of PR #46)
ROUTINE = ("PRICES UNCHANGED", "PRICES SUBJECT TO REVIEW")  # routine price-review notices (by section)
FULL_DAY = 216  # 5-minute intervals: at least 18 hours of prices on the local day
BINARY = (".parquet", ".npy", ".sqlite", ".png", ".pdf", ".zip", ".gz")


def texts(ref: str = BASE) -> list[str]:
    """The text of every tracked file outside data/ at ``ref``."""
    archive = subprocess.run(["git", "archive", ref], cwd=REPO, capture_output=True, check=True).stdout
    out = []
    with tempfile.TemporaryFile() as fh:
        fh.write(archive)
        fh.seek(0)
        with tarfile.open(fileobj=fh) as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name.startswith("data/") or m.name.endswith(BINARY):
                    continue
                f = tar.extractfile(m)
                if f is not None:
                    out.append(f.read().decode("utf-8", errors="ignore"))
    return out


def changed_since(ref: str = BASE) -> list[str]:
    """Files changed between ``ref`` and the working tree (committed or not)."""
    diff = subprocess.run(["git", "diff", "--name-only", ref], cwd=REPO, capture_output=True, text=True, check=True)
    new = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO, capture_output=True, text=True,
                         check=True)
    return sorted({f for f in (diff.stdout + new.stdout).split("\n") if f})


def unused_notices(all_text: list[str]) -> list[dict[str, object]]:
    db = sqlite3.connect(REPO / "data" / "index" / "corpus.sqlite")
    rows = db.execute("SELECT doc_id, chunk_id, title, section FROM chunks WHERE doc_type='market_notice' ORDER BY doc_id")
    blob = "\n".join(all_text)
    out = []
    for doc_id, chunk_id, title, section in rows:
        number = re.match(r"market_notice_(\d+)", doc_id)
        keys = [doc_id] + ([number.group(1)] if number else [])
        if not any(k in blob for k in keys):
            out.append({"doc_id": doc_id, "chunk_id": chunk_id, "title": title, "section": section,
                        "routine_price_review": (section or "").upper() in ROUTINE})
    return out


def unused_region_days(all_text: list[str]) -> list[dict[str, str]]:
    import duckdb

    from nem_agent.agent.request import REGION_TZ, extract_dates, extract_regions

    named: set[tuple[str, date]] = set()
    for text in all_text:
        for line in re.split(r"\n|\\n", text):
            line = line[:4000]
            regions = extract_regions(line)
            if not regions:
                continue
            days = set(extract_dates(line)) | {date.fromisoformat(d) for d in re.findall(r"\b(2026-\d\d-\d\d)", line)}
            named |= {(r, d) for r in regions for d in days}
    con = duckdb.connect()
    cov: Counter[tuple[str, date]] = Counter()
    for region, t in con.execute(f"SELECT region, interval_end_utc FROM '{REPO}/data/store/price_5min.parquet'").fetchall():
        cov[(region, t.astimezone(ZoneInfo(REGION_TZ[region])).date())] += 1
    out = []
    for (region, day), n in sorted(cov.items()):
        if n >= FULL_DAY and (region, day) not in named:
            out.append({"region": region, "local_date": str(day), "timezone": REGION_TZ[region], "intervals": str(n)})
    return out


def pool() -> dict[str, object]:
    t = texts()
    notices = unused_notices(t)
    return {"definition": "not previously used in evaluation or fix development: named in no tracked file outside "
                          f"data/ at the frozen code commit {BASE[:7]} (see eval/holdout_v6/provenance_check.py)",
            "searched_files": len(t), "notices": notices,
            "notice_counts": {"total": len(notices), "routine_price_review": sum(n["routine_price_review"] for n in notices)},
            "region_days": unused_region_days(t)}


def check(cases_path: Path) -> int:
    """Each unused case: its gold document is a pool notice, or its gold rows are on a pool region-day. IDs only."""
    import duckdb

    p = pool()
    docs = {n["doc_id"]: n for n in p["notices"]}  # type: ignore[union-attr]
    days = {(d["region"], d["local_date"]) for d in p["region_days"]}  # type: ignore[union-attr]
    cases = json.loads(cases_path.read_text())["cases"]
    con = duckdb.connect()
    tables = {"dispatch_rrp": "price_5min", "dispatch_totaldemand": "regionsum_5min", "opdemand_actual": "opdemand_actual",
              "opdemand_forecast_poe50": "opdemand_forecast"}
    from nem_agent.agent.request import REGION_TZ

    problems, routine, unused = [], 0, []
    for c in cases:
        if c.get("stratum") != "unused":
            continue
        cid, exp = c["case_id"], c.get("expected") or {}
        unused.append(cid)
        gc = exp.get("gold_citation")
        if gc:
            if gc.get("doc_id") not in docs:
                problems.append(f"{cid}: gold document not in the unused pool")
            elif docs[gc["doc_id"]]["routine_price_review"]:
                routine += 1
        for g in exp.get("gold_numbers") or []:
            if g.get("source_row_id") is None:
                continue
            table = tables.get(g.get("metric"))
            col = "target_end_utc" if table == "opdemand_forecast" else "interval_end_utc"
            rows = con.execute(f"SELECT region, {col} FROM '{REPO}/data/store/{table}.parquet' WHERE row_id=?",
                               [g["source_row_id"]]).fetchall() if table else []
            if not rows or not any((r, t.astimezone(ZoneInfo(REGION_TZ[r])).date().isoformat()) in days for r, t in rows):
                problems.append(f"{cid}: gold row not on an unused region-day")
        if not gc and not exp.get("gold_numbers"):
            problems.append(f"{cid}: no gold label to check against the pool")
    if routine > 1:
        problems.append(f"{routine} unused cases are on routine price-review notices (at most 1)")
    print(f"searched {p['searched_files']} files; pool: {p['notice_counts']} notices, region-days "
          f"{[(d['region'], d['local_date']) for d in p['region_days']]}")  # type: ignore[union-attr]
    print(f"unused cases: {unused} ({len(unused)}); on routine price-review notices: {routine}")
    since = changed_since()
    other = [f for f in since if not f.startswith("eval/holdout_v6/") and not f.startswith("tests/eval/test_holdout_v6")
             and f not in ("docs/live-gates.md", "docs/issue-tracker.md")]
    print(f"files changed since {BASE[:7]}: {len(since)}; outside the protocol and the two docs: {other or 'none'}")
    if other:
        problems.append(f"files other than the protocol and docs changed since {BASE[:7]}: {other}")
    print("PROBLEMS:", problems or "none")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pool", help="write the unused pool to this JSON file")
    g.add_argument("--check", help="check the unused cases of this case file against the pool")
    args = ap.parse_args()
    if args.pool:
        p = pool()
        Path(args.pool).write_text(json.dumps(p, indent=1) + "\n")
        print(f"searched {p['searched_files']} files; notices {p['notice_counts']}; region-days "
              f"{[(d['region'], d['local_date']) for d in p['region_days']]}")  # type: ignore[union-attr]
        return 0
    return check(Path(args.check))


if __name__ == "__main__":
    raise SystemExit(main())
