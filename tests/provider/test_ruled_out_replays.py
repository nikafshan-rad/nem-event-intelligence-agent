"""Issue I-7 (docs/issue-tracker.md): saved Live runs replayed offline through the SYNTHETIC fake transport (their tool
calls, first draft and saved repair patch; no network, no key).

W18 (2026-09-30) opened with "Timing rules this out" for the Hazelwood notice, then kept a hypothesis resting on it.
The new check rejects that hypothesis:
- If the one scoped repair drops it, the answer passes with its opening and regional sentence.
- If the repair keeps it (the saved Live patch was never asked to), the answer falls back. That is the recorded risk.

F04 and W19, whose cited notices come before their events, are unchanged. W19's frozen Live verdict stays failed; these
replays only show what the code does offline.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
RUN = LIVE / "live-check-p1-dev"
CODE = "EXPLANATION_RULED_OUT_BY_TIMING"


def _replay(path: Path, *, first_draft: bool = True, delete: str | None = None):
    """``first_draft``: the run's first draft with its saved repair patch (a 2026-09-30 record); else the final draft.
    ``delete``: the saved patch deletes this target instead of rewriting it."""
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    patch: dict[str, Any] | None = None
    if first_draft:
        trace = json.loads((RUN / "traces" / f"{rec['score']['trace_id']}.json").read_text())
        patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
        if delete:
            patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                     [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                       "citation": None}]}
    draft = rec["drafts"]["synthesis:draft"] if first_draft else (rec["drafts"].get("repair:draft")
                                                                  or rec["drafts"]["synthesis:draft"])
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def _ruled_out(res) -> list[str]:
    v = res.report.validation
    return [x["detail"] for k in ("pre_repair", "initial") for x in (v.get(k) or {}).get("violations", [])
            if x["code"] == CODE]


def test_w18_is_shown_without_the_ruled_out_hypothesis_when_the_repair_drops_it():
    res = _replay(RUN / "W18.json", delete="possible_explanations[1]")
    rep, v = res.report, res.report.validation
    assert v["repair_attempted"] and not v["fallback_applied"] and v["final_passed"], v
    assert rep.summary[0].startswith("Timing rules this out: the AEMO market notice that mentions Hazelwood")
    assert "SA1 and TAS1 were also at or above the analysis threshold" in rep.summary[1]
    assert not any("[c1]" in h.statement for h in rep.possible_explanations)
    assert len(rep.possible_explanations) == 2  # the two unrelated hypotheses stay


def test_w18_falls_back_when_the_repair_keeps_the_ruled_out_hypothesis():
    res = _replay(RUN / "W18.json")  # the saved Live patch rewrote the hypothesis and kept [c1]
    assert res.report.validation["fallback_applied"] and not res.report.summary
    assert any(d.startswith("possible_explanations[1]: rests on market_notice_144893#0 [c1]") for d in _ruled_out(res))


@pytest.mark.parametrize("path,first_draft", [
    (RUN / "F04.json", True),
    (LIVE / "live-check-2026-09-29" / "F04.json", False),
    (RUN / "W19.json", True),
])
def test_notices_before_the_event_are_untouched(path, first_draft):
    res = _replay(path, first_draft=first_draft)
    assert _ruled_out(res) == []
    assert not res.report.validation["fallback_applied"] and res.report.validation["final_passed"]
    assert res.report.summary[0].startswith(("The records cannot settle this:", "AEMO later cancelled"))
