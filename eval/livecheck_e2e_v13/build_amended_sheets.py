"""Build the review sheets of the end-to-end Live check of v13 request resolution with the disclosed amended review kit
(`AMENDMENT_1.md`, `kit_amended.py`). Offline: it reads the saved records read-only and the pinned store, and calls no
model.

It replaces only the frozen `score.py --sheet` step. That step uses the frozen `kit.py`, which refused for want of
item-level times. The records are found as the frozen scorer finds them (`score.saved`), and the brief is the frozen
`REVIEW_BRIEF.md`, unchanged. The verdict is computed by the unchanged frozen `score.py --review`.

Usage: python eval/livecheck_e2e_v13/build_amended_sheets.py DIR
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
KIT_NOTE = ("amended review kit (eval/livecheck_e2e_v13/AMENDMENT_1.md): observations without item-level times carry "
            "their exact pinned source rows' times, labelled 'from pinned source rows; not recorded on the evidence item'")


def _sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"livecheck_e2e_v13_{name}", HERE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


score = _sibling("score")
kit_amended = _sibling("kit_amended")


def build(out_dir: Path, live: Path = score.LIVE) -> tuple[dict[str, Any], dict[str, Any]]:
    from nem_agent.service import _shared

    store, _ = _shared()
    freeze = score.freeze_of()
    got = score.saved(freeze, live)
    dev, blind = kit_amended.build(score.cases_of(), score.gold_of(), {cid: g["record"] for cid, g in got.items()},
                                   freeze["review_blind_order"], store)
    dev, blind = {"kit": KIT_NOTE, **dev}, {"kit": KIT_NOTE, **blind}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "developer_sheet.json").write_text(json.dumps(dev, indent=1, default=str) + "\n")
    (out_dir / "blind_sheet.json").write_text(json.dumps(blind, indent=1, default=str) + "\n")
    shutil.copy(HERE / "REVIEW_BRIEF.md", out_dir / "REVIEW_BRIEF.md")
    return dev, blind


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    args = ap.parse_args()
    build(Path(args.out_dir))
    print(f"review sheets written to {args.out_dir} with the amended review kit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
