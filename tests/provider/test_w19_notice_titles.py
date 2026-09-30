"""Issue I-6 (docs/issue-tracker.md): W19's Live answer from 2026-09-30, replayed offline.

The Live run (artifacts/live/live-check-p1-dev/W19.json, trace tr-b09af6da7d95) built a correct cancellation
sentence, then fell back: its repaired draft named reserve notices by their exact titles, and the numeric check read
the "2" of "Level 2 (LOR2)" and the "1" of "Level 1 (LOR1)" as numbers. These replays use the run's saved tool calls,
its first draft and its saved repair patch through the SYNTHETIC fake transport (no network, no key). The frozen run's
outcome stays failed; this only shows what the fix changes offline.
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

RUN = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-p1-dev"
REC = json.loads((RUN / "W19.json").read_text())
TRACE = json.loads((RUN / "traces" / f"{REC['score']['trace_id']}.json").read_text())
PATCH = next(e for e in TRACE["events"] if e["name"] == "repair:scoped")["patch"]
SENTENCE = [e["text"] for e in TRACE["events"] if e["name"] == "cancellation_answer"][-1]
LOR2 = "Level 2 (LOR2)"


def _replay(edit=lambda s: s):
    """The Live run's calls, first draft and repair patch, with ``edit`` applied to every draft and patch line."""
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in REC["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    draft: dict[str, Any] = copy.deepcopy(REC["drafts"]["synthesis:draft"])
    draft["summary"] = [edit(s) for s in draft["summary"]]
    patch = copy.deepcopy(PATCH)
    for e in patch["edits"]:
        e["text"] = edit(e["text"]) if e.get("text") else e.get("text")
    fake = FakeModel(REC["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    return investigate(InvestigateRequest(question=REC["question"], mode="live"), live_client=fake, write_trace=False)


def _critical(v: dict[str, Any], key: str) -> list[tuple[str, str]]:
    return [(x["code"], x["detail"]) for x in (v.get(key) or {}).get("violations", []) if x["severity"] == "critical"]


def test_w19s_live_answer_is_displayed_with_its_correct_cancellation_sentence():
    res = _replay()
    v = res.report.validation
    assert v["repair_attempted"] and not v["fallback_applied"] and v["final_passed"], v
    assert res.report.summary[0] == SENTENCE  # identical to the sentence the Live run built but never displayed
    assert sum(LOR2 in s for s in res.report.summary) == 4  # the title lines are shown as the model wrote them
    # the first draft's two genuine faults are still caught, and no title digit is
    first = _critical(v, "pre_repair")
    assert {c for c, _ in first} == {"NOTICE_TIMING_CONTRADICTED", "NUMERIC_UNTRACKED"}
    assert [d for c, d in first if c == "NUMERIC_UNTRACKED"] == ["summary[14]: number 29 is not a registered claim"]


def test_altered_titles_still_fall_back():
    res = _replay(lambda s: s.replace(LOR2, "Level 3 (LOR3)"))
    v = res.report.validation
    assert v["fallback_applied"] and not res.report.summary
    assert any(c == "NUMERIC_UNTRACKED" and "number 3 " in d for c, d in _critical(v, "initial"))


def test_a_number_outside_a_title_still_falls_back():
    res = _replay(lambda s: s.replace("in the SA Region on 29/07/2026' lists", "in the SA Region on 29/07/2026' (a 2 MW "
                                      "shortfall) lists"))
    v = res.report.validation
    assert v["fallback_applied"] and not res.report.summary
    assert any(c == "NUMERIC_UNTRACKED" and "number 2 " in d for c, d in _critical(v, "initial"))
