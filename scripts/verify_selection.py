#!/usr/bin/env python
"""G0 verifier: re-check every recorded source against the publisher and the parsed-schema contract.

Usage: python scripts/verify_selection.py data/source_selection.json [--allow-cached] [--no-self-test]
Exit code 0 only if every check passes AND every self-test mutation is rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nem_agent.verify import load, self_test, verify


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("selection")
    ap.add_argument("--allow-cached", action="store_true",
                    help="accept URLs that have since rolled off NEMWeb Current if a verified cached copy exists")
    ap.add_argument("--allow-rolled-off", action="store_true",
                    help="treat HTTP 404 from NEMWeb Current (rolling retention) as a warning, not a failure")
    ap.add_argument("--no-live", action="store_true", help="skip HTTP liveness checks")
    ap.add_argument("--no-self-test", action="store_true")
    ap.add_argument("--report", default=None, help="write the JSON report here")
    args = ap.parse_args()

    sel = load(args.selection)
    rep = verify(sel, live=not args.no_live, allow_cached=args.allow_cached, allow_rolled_off=args.allow_rolled_off)
    for line in rep.failed:
        print(f"FAIL  {line}")
    for line in rep.warnings:
        print(f"WARN  {line}")
    print(f"checks: {len(rep.passed)} passed, {len(rep.failed)} failed, {len(rep.warnings)} warnings")
    ok = rep.ok
    st = []
    if not args.no_self_test:
        st = self_test(sel)
        for name, rejected, why in st:
            print(f"self-test {'REJECTED (good)' if rejected else 'ACCEPTED (BAD)'}: {name} :: {why[:160]}")
        ok = ok and all(r for _, r, _ in st)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(
            {**rep.as_dict(), "self_test": [{"mutation": n, "rejected": r, "reason": w} for n, r, w in st]}, indent=2))
    print("G0 VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
