"""Run one case through scripts/live_diagnose.py, unchanged, keeping the whole shown answer in the saved record.

The standard record keeps the report's sections as they were before PR #36. It omits `ruled_out_explanations`, which
the app shows under "Ruled out by the evidence (validated)", and the display record. So an explanation that the display
moved out of the hypotheses would be missing from what the reviewer reads. This adds, to the same record:
- `report.ruled_out_explanations`;
- `display`: `display_rewrites`, `citation_labels`, and the validator's `ruled_out_explanations` indices.

Everything else is live_diagnose.py's own code: its scoring, its error and budget-stop handling, and its output files.
The API key is never read here, never printed and never written.

Usage: python eval/holdout_v5/run_case.py --cases Y01 --cases-file eval/holdout_v5/cases.json --label L3-holdout-v5
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import live_diagnose as ld  # noqa: E402
from nem_agent.evaluation import runner  # noqa: E402

DISPLAY = ("display_rewrites", "citation_labels", "ruled_out_explanations")
_standard = ld.diagnose


def diagnose(case: dict[str, Any]) -> dict[str, Any]:
    """live_diagnose's record, plus the parts of the shown answer it omits."""
    held: dict[str, Any] = {}

    def run_and_hold(c: dict[str, Any], mode: str, keep: dict[str, Any] | None = None) -> dict[str, Any]:
        row = runner.run_system_case(c, mode, keep=keep)
        held.update(keep or {})
        return row

    ld.run_system_case = run_and_hold  # live_diagnose.diagnose looks it up when it runs
    rec = _standard(case)
    res = held.get("result")
    if res is not None and "report" in rec:
        rep = res.report.model_dump(mode="json")
        rec["report"]["ruled_out_explanations"] = rep.get("ruled_out_explanations", [])
        rec["display"] = {k: rep["validation"].get(k) for k in DISPLAY}
    return rec


if __name__ == "__main__":
    ld.diagnose = diagnose
    raise SystemExit(ld.main())
