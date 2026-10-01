"""Size the case cap from the spending ledger (read-only; the ledger is git-ignored, so the output is committed as
artifacts/logs/live_check_dev2_budget.log).

A case's **peak committed** amount is the most the ledger holds for it at any moment: the settled cost of its earlier
calls plus the worst-case reservation of the call being made. A hard case cap below that peak would refuse a call the
case needs. It is not the case's final cost, which is lower. The ledger's case segments start at each routing call. The
six cases' last Live runs are found by the exact token counts of their first call.

Usage: python eval/live_check_dev2/ledger_peaks.py
"""

from __future__ import annotations

import glob
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from nem_agent import budget  # noqa: E402

SYNTHETIC_FROM = "2026-09-30T07:50:00Z"  # four offline replays, run outside pytest, wrote here (explained in PROTOCOL.md)
RUNS = ["live-check-2026-09-29/F01.json", "live-check-2026-09-29/F03.json", "live-check-p1-dev/W18.json",
        "live-check-p1-dev/W19.json", "live-check-p1-dev/F04.json", "live-check-p1-dev/W04.json",
        "live-check-2026-09-29/F04.json", "L3-holdout-v4/W18.json", "L3-holdout-v4/W19.json", "L3-holdout-v4/W04.json"]


def main() -> int:
    path = budget.ledger_path()
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    print(f"# ledger {path.relative_to(REPO)}: {len(rows)} entries; committed USD {budget.spent()}")
    syn = [r for r in rows if r["at"] >= SYNTHETIC_FROM]
    print(f"# entries from {SYNTHETIC_FROM}: {len(syn)}, settled total USD "
          f"{round(sum(r['usd'] for r in syn if r['kind'] == 'settle'), 6)}; token counts "
          f"{sorted({(r.get('input_tokens'), r.get('output_tokens')) for r in syn if r['kind'] == 'settle'})} "
          "(the fake transport's; no API call)")
    rows = [r for r in rows if r["at"] < SYNTHETIC_FROM]
    res = {r["id"]: r for r in rows if r["kind"] == "reserve"}
    settle = {r["id"]: r for r in rows if r["kind"] == "settle"}
    real = [(res[i], s) for i, s in settle.items() if i in res and s.get("input_tokens") is not None]
    over = sum(s["usd"] > res[i]["usd"] + 1e-9 for i, s in settle.items() if i in res)
    print(f"# reservations as a bound: {len(real)} settled calls with usage; settled above the reservation: {over}; "
          f"largest settled/reserved ratio {max(s['usd'] / r['usd'] for r, s in real):.3f}")
    print(f"# open (never settled) reservations, counted at worst case: "
          f"{[(r['stage'], r['usd'], r['at']) for i, r in res.items() if i not in settle]}")
    print(f"# charges (unreserved attempts recorded at worst case): "
          f"{[(r['stage'], r['usd'], r['at']) for r in rows if r['kind'] == 'charge']}")
    segs: list[list[dict]] = []
    for r in rows:
        if r["kind"] != "reserve":
            continue
        if r["stage"] == "route" or not segs:
            segs.append([])
        s = settle.get(r["id"])
        segs[-1].append({"stage": r["stage"], "reserve": r["usd"], "actual": s["usd"] if s else r["usd"],
                         "tok": (s or {}).get("input_tokens"), "out": (s or {}).get("output_tokens")})

    def peak(seg: list[dict]) -> tuple[float, float]:
        spent = top = 0.0
        for c in seg:
            top, spent = max(top, spent + c["reserve"]), spent + c["actual"]
        return round(top, 6), round(spent, 6)
    peaks = sorted(peak(s)[0] for s in segs)
    costs = sorted(peak(s)[1] for s in segs)

    def q(xs: list[float], p: float) -> float:
        return xs[min(len(xs) - 1, int(p * len(xs)))]
    print(f"# all {len(segs)} case segments: peak committed max {peaks[-1]:.6f}, p99 {q(peaks, .99):.6f}, p90 "
          f"{q(peaks, .9):.6f}, median {statistics.median(peaks):.6f}; final cost max {costs[-1]:.6f}, p90 "
          f"{q(costs, .9):.6f}; segments with a peak above 0.10: {sum(p > 0.10 for p in peaks)}, above 0.15: "
          f"{sum(p > 0.15 for p in peaks)}")
    first = {}
    for f in glob.glob(str(REPO / "artifacts" / "live" / "**" / "*.json"), recursive=True):
        try:
            rec = json.loads(Path(f).read_text())
        except (ValueError, OSError):
            continue
        mc = rec.get("model_calls") if isinstance(rec, dict) else None
        if isinstance(mc, list) and mc and mc[0].get("input_tokens"):
            first[(mc[0]["input_tokens"], mc[0]["output_tokens"], len(mc))] = str(Path(f).relative_to(REPO / "artifacts" / "live"))
    found = {first.get((s[0]["tok"], s[0]["out"], len(s))): s for s in segs}
    print("# the six cases' last Live runs (reservation/settled per call, USD):")
    for run in RUNS:
        s = found.get(run)
        if s is None:
            print(f"{run}: not matched")
            continue
        p, c = peak(s)
        print(f"{run:34s} calls {len(s)}  cost {c:.6f}  peak committed {p:.6f}  " +
              " ".join(f"{x['stage']}:{x['reserve']:.6f}/{x['actual']:.6f}" for x in s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
