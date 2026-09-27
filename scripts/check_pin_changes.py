#!/usr/bin/env python
"""Fail when a pin changed without a reviewed history entry (run by CI on pull requests and pushes).

Compares ``data/source_selection.json`` with the version at ``--base`` (a git revision). For every source whose
``sha256``, ``content_sha256`` or ``url`` changed, the new entry must carry exactly one more ``superseded`` record
whose old hash equals the base pin and whose ``new_sha256`` equals the new pin, with a reason, the publisher's
revision and the approving reviewer (``scripts/repin_source.py`` writes all of these). Sources may not be added or
removed silently. Every history chain must also end at the current pin.

Usage: python scripts/check_pin_changes.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SELECTION = "data/source_selection.json"


def check(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    b = {s["source_id"]: s for s in base["sources"]}
    h = {s["source_id"]: s for s in head["sources"]}
    for sid in sorted(set(b) - set(h)):
        problems.append(f"{sid}: removed from the selection without a documented probe re-run")
    for sid in sorted(set(h) - set(b)):
        problems.append(f"{sid}: added to the selection without a documented probe re-run")
    for sid in sorted(set(b) & set(h)):
        old, new = b[sid], h[sid]
        if all(old.get(k) == new.get(k) for k in ("sha256", "content_sha256", "url")):
            if old.get("superseded", []) != new.get("superseded", []):
                problems.append(f"{sid}: pin history edited although the pin did not change")
            continue
        hist_old, hist_new = old.get("superseded", []), new.get("superseded", [])
        if len(hist_new) != len(hist_old) + 1 or hist_new[: len(hist_old)] != hist_old:
            problems.append(f"{sid}: pin changed without exactly one new `superseded` entry (use scripts/repin_source.py)")
            continue
        rec = hist_new[-1]
        if rec.get("sha256") != old["sha256"] or rec.get("new_sha256") != new["sha256"]:
            problems.append(f"{sid}: history entry does not connect the old pin {old['sha256'][:12]} to the new "
                            f"{new['sha256'][:12]}")
        if old.get("url") != new.get("url"):
            problems.append(f"{sid}: URL changed; a new URL is a new source, not a revision")
        for field in ("reason", "publisher_revision", "approved_by"):
            if not str(rec.get(field) or "").strip():
                problems.append(f"{sid}: history entry lacks `{field}`")
    for sid, s in sorted(h.items()):
        hist = s.get("superseded", [])
        if hist and hist[-1].get("new_sha256") != s["sha256"]:
            problems.append(f"{sid}: last history entry does not end at the current pin")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="git revision to compare with, e.g. origin/main or HEAD^")
    args = ap.parse_args()
    shown = subprocess.run(["git", "show", f"{args.base}:{SELECTION}"], cwd=REPO, capture_output=True, text=True)
    if shown.returncode != 0:
        print(f"PIN-CHECK: cannot read {SELECTION} at {args.base}: {shown.stderr.strip()[:200]}")
        return 2
    base, head = json.loads(shown.stdout), json.loads((REPO / SELECTION).read_text())
    problems = check(base, head)
    changed = sum(1 for s in head["sources"] for o in base["sources"]
                  if o["source_id"] == s["source_id"] and o["sha256"] != s["sha256"])
    for p in problems:
        print(f"PIN-CHECK: {p}")
    print(f"PIN-CHECK: {'FAIL' if problems else 'PASS'} ({changed} pin(s) changed since {args.base}, "
          f"{len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
