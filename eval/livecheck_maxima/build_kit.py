"""Build the kits for the Live acceptance check of computed demand maxima (PROTOCOL.md, "Fresh questions" and "Gold"),
outside the repository. Adapted from eval/livecheck_i15_17/build_kit.py.

Two kits, built separately so neither agent sees the other's material:
- **writer:** `BRIEF.md`, `DATA.md`, the three store tables, `events.json`, `windows.json` (fully held windows and
  other data facts, computed here from the store), `development_material.json`, a Python environment with only
  `duckdb` and `pytz`, and the overlap checker with SHA-256 hashes of every 6-word sequence of the earlier evaluation
  questions and prompts v12 (no text);
- **checker:** `GOLD_CHECK_BRIEF.md`, `DATA.md`, the same tables and data facts, the same environment, and
  `questions.json`: the 12 maximum and must-clarify questions of `cases.json` (D01–D04, F01–F08) with their request
  fields only (no intended reading, no gold).

Usage:
    python eval/livecheck_maxima/build_kit.py writer KIT_DIR
    python eval/livecheck_maxima/build_kit.py checker KIT_DIR
    python eval/livecheck_maxima/build_kit.py cases WRITER_OUTPUT   # assemble cases.json
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STORE = REPO / "data" / "store"
TABLES = ["regionsum_5min", "opdemand_actual", "price_5min"]
TZ = {"NSW1": "Australia/Sydney", "QLD1": "Australia/Brisbane", "SA1": "Australia/Adelaide",
      "TAS1": "Australia/Hobart", "VIC1": "Australia/Melbourne"}
PRIOR = ["eval/cases.json", "eval/holdout_v2/cases.json", "eval/holdout_v3/cases.json", "eval/holdout_v4/cases.json",
         "eval/holdout_v5/cases.json", "eval/holdout_v6/cases.json", "eval/live_check_2026_09_29/cases.json",
         "eval/livecheck_i15_17/cases.json", "eval/livecheck_routing_v12/cases.json",
         "eval/structured_requests/matrix.json"]
EVENT_FIELDS = ["event_id", "region", "timezone", "kind", "peak_interval_end_utc", "peak_interval_end_market", "peak_rrp",
                "window_start_utc", "window_end_utc", "intervals_meeting_threshold_in_window"]
DEVELOPMENT = {
    "note": "Regions, days and windows used in developing or checking the assistant. Prefer other material; a question "
            "may use one only when its stratum cannot be met otherwise, and says so in its notes.",
    "items": [
        {"region": "NSW1", "measure": "total demand", "local_day": "2026-07-29"},
        {"region": "QLD1", "measure": "operational demand", "local_day": "2026-07-29"},
        {"region": "TAS1", "local_day": "2026-07-29"},
        {"region": "VIC1", "local_day": "2026-07-29"},
        {"region": "VIC1", "event_id": "VIC1-20260728T2120-lo"},
        {"region": "SA1", "event_id": "SA1-20260731T0235-hi"},
        {"region": "SA1", "local_day": "2026-07-31"},
        {"region": "TAS1", "local_day": "2026-08-06"},
        {"region": "NSW1", "half_hour_end_utc": "2026-07-28T21:30:00Z"},
        {"region": "NSW1", "half_hour_end_utc": "2026-07-30T21:30:00Z"},
        {"region": "SA1", "half_hour_end_utc": "2026-07-29T08:00:00Z"},
    ]}
CHECKER = '''"""Compare the 6-word sequences of each question in out/cases_maxima.json with hashed 6-word sequences of earlier
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


cases = json.loads((KIT / "out" / "cases_maxima.json").read_text())["cases"]
flagged = [c["case_id"] for c in cases
           if any(hashlib.sha256(g.encode()).hexdigest() in HASHES for g in grams(c["question"]))]
print("cases with overlap:", ", ".join(flagged) if flagged else "none")
'''


def grams(t: str, n: int = 6) -> set[str]:
    w = re.findall(r"[a-z0-9']+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _iso(t: datetime) -> str:
    return t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day(d: date, region: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(TZ[region])
    return (datetime.combine(d, datetime.min.time(), z).astimezone(ZoneInfo("UTC")),
            datetime.combine(d + timedelta(days=1), datetime.min.time(), z).astimezone(ZoneInfo("UTC")))


def _ranges(ends: list[datetime], step: timedelta) -> list[list[Any]]:
    out: list[list[Any]] = []
    for t in sorted(ends):
        if out and t - out[-1][1] == step:
            out[-1][1] = t
            out[-1][2] += 1
        else:
            out.append([t, t, 1])
    return [[_iso(a - step), _iso(b), n] for a, b, n in out]


def windows_facts(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Fully held windows per measure, computed from the store: held local days, contiguous held ranges, and the
    events' windows."""
    con = duckdb.connect()
    for t in ("regionsum_5min", "opdemand_actual"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(STORE / f'{t}.parquet').as_posix()}')")
    measures = {"total demand": ("regionsum_5min", 5), "operational demand": ("opdemand_actual", 30)}
    out: dict[str, Any] = {
        "conventions": {
            "interval": "a row's interval is identified by its end, interval_end_utc (UTC)",
            "window": "a window (start, end] holds the intervals with start < interval_end_utc <= end",
            "local_day": "from local midnight to the next local midnight in the region's time zone",
            "time_zones": TZ,
            "total_demand": "regionsum_5min.totaldemand_mw, dispatch TOTALDEMAND, one row per 5-minute interval",
            "operational_demand": "opdemand_actual.operational_demand_mw, half-hourly; up to two rows per half-hour: "
                                  "revision 'initial' (public a few hours after the half-hour) and 'updated' (public "
                                  "the next morning). available_at_utc is when a row was public.",
            "daylight_saving": "On 2026-04-05 clocks went back one hour in NSW1, VIC1, TAS1 and SA1, so that local "
                               "day is 25 hours (50 half-hours, 300 five-minute intervals). On 2025-10-05 they went "
                               "forward, a 23-hour day. QLD1 has no daylight saving.",
        }}
    for m, (table, minutes) in measures.items():
        step = timedelta(minutes=minutes)
        days, ranges = [], {}
        for r in TZ:
            ends = [x[0] for x in con.execute(f"SELECT DISTINCT interval_end_utc FROM {table} WHERE region=?",
                                              [r]).fetchall()]
            ranges[r] = _ranges(ends, step)
            for d in sorted({(t - timedelta(seconds=1)).astimezone(ZoneInfo(TZ[r])).date() for t in ends}):
                a, b = local_day(d, r)
                need = round((b - a) / step)
                held = sum(1 for t in ends if a < t <= b)
                if held == need:
                    days.append({"region": r, "local_day": str(d), "window_utc": [_iso(a), _iso(b)],
                                 "intervals": need})
        evs = []
        for e in events:
            a, b = e["window_start_utc"], e["window_end_utc"]
            need = round((datetime.fromisoformat(b.replace("Z", "+00:00"))
                          - datetime.fromisoformat(a.replace("Z", "+00:00"))) / step)
            held = (con.execute(f"SELECT count(DISTINCT interval_end_utc) FROM {table} WHERE region=? AND "
                               "interval_end_utc > ?::TIMESTAMPTZ AND interval_end_utc <= ?::TIMESTAMPTZ",
                               [e["region"], a, b]).fetchone() or (0,))[0]
            evs.append({"event_id": e["event_id"], "window_utc": [a, b], "intervals": need, "held": held,
                        "fully_held": held == need})
        out[m] = {"interval_minutes": minutes, "fully_held_local_days": days, "event_windows": evs,
                  "held_ranges_utc": {r: [{"start": x[0], "end": x[1], "intervals": x[2]} for x in v]
                                      for r, v in ranges.items()},
                  "note": "held_ranges_utc lists the contiguous runs of intervals that have at least one row; any "
                          "window inside one run is fully held. Days not listed in fully_held_local_days are only "
                          "partly held."}
    return out


def data_md() -> str:
    con = duckdb.connect()
    lines = ["# Data dictionary (generated mechanically from the files in data/store/)", "",
             "All times are UTC. `row_id` is the unique source-row identifier.", ""]
    for t in TABLES:
        p = (STORE / f"{t}.parquet").as_posix()
        n = (con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone() or (0,))[0]
        cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall()
        lines += [f"## data/store/{t}.parquet ({n} rows)", "", ", ".join(f"`{c[0]}` ({c[1]})" for c in cols), ""]
    return "\n".join(lines)


def _common(kit: Path, brief: str) -> None:
    if kit.exists() or REPO in kit.parents or kit == REPO:
        raise SystemExit("the kit directory must be new and outside the repository")
    (kit / "data" / "store").mkdir(parents=True)
    (kit / "out").mkdir()
    shutil.copy(HERE / brief, kit / brief)
    (kit / "DATA.md").write_text(data_md() + "\n")
    for t in TABLES:
        shutil.copy(STORE / f"{t}.parquet", kit / "data" / "store" / f"{t}.parquet")
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    events = [{k: e[k] for k in EVENT_FIELDS if k in e} for e in sel["events"]]
    (kit / "data" / "events.json").write_text(json.dumps(
        {"analysis_threshold": sel["analysis_threshold"], "events": events}, indent=1) + "\n")
    (kit / "data" / "windows.json").write_text(json.dumps(windows_facts(events), indent=1) + "\n")
    subprocess.run([sys.executable, "-m", "venv", str(kit / "venv")], check=True)
    lock = (REPO / "requirements.lock").read_text()
    pins = [ln.strip() for ln in lock.splitlines() if re.match(r"^(duckdb|pytz)==", ln.strip())]
    subprocess.run([str(kit / "venv" / "bin" / "pip"), "install", "-q", *pins], check=True)


def _manifest(kit: Path, extra: dict[str, Any]) -> None:
    files = {str(p.relative_to(kit)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(kit.rglob("*")) if p.is_file() and "venv" not in p.relative_to(kit).parts}
    (kit / "MANIFEST.json").write_text(json.dumps({**extra, "files": files}, indent=1) + "\n")


def writer(kit: Path) -> None:
    _common(kit, "BRIEF.md")
    (kit / "overlap").mkdir()
    (kit / "data" / "development_material.json").write_text(json.dumps(DEVELOPMENT, indent=1) + "\n")
    prior = [c["question"] for p in PRIOR for c in json.loads((REPO / p).read_text())["cases"]]
    prompts = [f.read_text() for f in sorted((REPO / "src" / "nem_agent" / "prompts" / "v12").glob("*.md"))]
    hashes = sorted({hashlib.sha256(g.encode()).hexdigest() for t in prior + prompts for g in grams(t)})
    (kit / "overlap" / "hashes.json").write_text(json.dumps({"questions": len(prior), "prompt_files": len(prompts),
                                                             "sha256": hashes}) + "\n")
    (kit / "overlap" / "check_overlap.py").write_text(CHECKER)
    _manifest(kit, {"kit": "writer", "earlier_questions": len(prior), "prompt_files": len(prompts)})
    print(f"writer kit built at {kit}: {len(prior)} earlier questions and {len(prompts)} prompt files hashed "
          f"({len(hashes)} 6-word sequences)")


def checker(kit: Path) -> None:
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    qs = [{"case_id": c["case_id"], "question": c["question"], "request": c.get("request", {})}
          for c in cases if c["check_group"] in ("development", "fresh")]
    _common(kit, "GOLD_CHECK_BRIEF.md")
    (kit / "questions.json").write_text(json.dumps({"questions": qs}, indent=1) + "\n")
    _manifest(kit, {"kit": "checker", "questions": len(qs),
                    "cases_json_sha256": hashlib.sha256((HERE / "cases.json").read_bytes()).hexdigest()})
    print(f"checker kit built at {kit}: {len(qs)} questions")


def _reused(rel: str, cid: str) -> dict[str, Any]:
    return dict(next(c for c in json.loads((REPO / rel).read_text())["cases"] if c["case_id"] == cid))


def _day(region: str) -> dict[str, Any]:
    return {"measure": None, "region": region, "window_kind": "day",
            "window_utc": ["2026-07-28T14:00:00Z", "2026-07-29T14:00:00Z"],
            "window_local": ["2026-07-29T00:00:00+10:00", "2026-07-30T00:00:00+10:00"], "event_id": None,
            "as_of_utc": None, "expected_outcome": "established"}


def assemble(writer_output: Path) -> None:
    """cases.json: the reused development cases and regression controls, copied unchanged but for their case ID
    (D04 adds Z04's cutoff), and the writer's fresh questions as written (PROTOCOL.md, "Sample")."""
    lc, v6 = "eval/livecheck_i15_17/cases.json", "eval/holdout_v6/cases.json"
    tools = _reused(lc, "K09")["expected"]["required_tools"]
    out: list[dict[str, Any]] = []
    for new, (rel, cid, measure, region) in {"D01": (lc, "K09", "total demand", "NSW1"),
                                             "D02": (lc, "K11", "operational demand", "QLD1"),
                                             "D03": (v6, "Z04", "total demand", "TAS1")}.items():
        out.append({**_reused(rel, cid), "case_id": new, "check_group": "development", "origin": {"file": rel, "case_id": cid},
                    "intended": {**_day(region), "measure": measure}})
    z04 = _reused(v6, "Z04")
    cutoff = "2026-07-29T05:00:00Z"
    out.append({**z04, "case_id": "D04", "check_group": "development",
                "origin": {"file": v6, "case_id": "Z04", "changed": {"request.as_of_utc": cutoff}},
                "request": {"as_of_utc": cutoff},
                "expected": {**{k: z04["expected"][k] for k in ("intent", "answerable", "status_in", "required_tools")},
                             "as_of_utc": cutoff, "expected_outcome": "supplied", "no_retrospective_evidence": True,
                             "check": "With the cutoff inside the day, the day's maximum total demand is not "
                                      "established: a correct answer says so and gives the highest value held by the "
                                      "cutoff only as that (GOLD.json)."},
                "intended": {**_day("TAS1"), "measure": "total demand", "as_of_utc": cutoff,
                             "expected_outcome": "not_established"}})
    for c in json.loads(writer_output.read_text())["cases"]:
        it = c["intended"]
        clar = it["expected_outcome"] == "clarification"
        out.append({"case_id": c["case_id"], "check_group": "fresh", "origin": {"writer": "out/cases_maxima.json"},
                    "category": "demand_max", "split": "livecheck_maxima", "stratum": c["stratum"],
                    "question": c["question"], "request": c["request"],
                    "expected": {"area": "demand_max", "expected_outcome": "clarification" if clar else "supplied",
                                 "intent": "market_event_review", "answerable": not clar,
                                 "status_in": ["needs_clarification"] if clar else ["answered", "answered_with_caveats"],
                                 "required_tools": [] if clar else tools,
                                 **({"as_of_utc": it["as_of_utc"], "no_retrospective_evidence": True}
                                    if it.get("as_of_utc") else {})},
                    "intended": it, "writer_notes": c.get("notes", "")})
    for new, cid in {"R01": "K05", "R02": "K06", "R03": "K07", "R04": "K14"}.items():
        out.append({**_reused(lc, cid), "case_id": new, "check_group": "control", "origin": {"file": lc, "case_id": cid}})
    (HERE / "cases.json").write_text(json.dumps({"version": "livecheck_maxima/1", "cases": out}, indent=1) + "\n")
    print(f"cases.json: {len(out)} cases")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("writer", "checker", "cases"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "cases":
        assemble(Path(sys.argv[2]).resolve())
        return 0
    {"writer": writer, "checker": checker}[sys.argv[1]](Path(sys.argv[2]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
