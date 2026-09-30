"""Issue I-3c (docs/issue-tracker.md): the headline states the validated answer where the controller holds it.

Live check 2026-09-29: F04 asked whether Directlink drove the NSW1 spike and was headlined with the peak price. F03's
uncited headline named neither the outage time nor the constraint set. Now:
- **A causal question with the controller's timing answer (I-1a):** the headline is that answer's first sentence, so
  "Timing rules this out" and "The records cannot settle this" stay distinct.
- **A document answer:** the headline is the statement the model's own headline paraphrases, shown as rendered with
  its citation and any zone or unit note.
- **Every other answer** keeps the model's headline.

Replays use saved Live records through the SYNTHETIC fake transport (no network, no key). Scripted drafts replayed
offline are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import narrative_numbers
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
V4, C0929, C0930 = LIVE / "L3-holdout-v4", LIVE / "live-check-2026-09-29", LIVE / "live-check-p1-dev"
CANNOT_SETTLE = ("The records cannot settle this: the AEMO market notice that mentions Directlink gives 2026-07-27 07:00 "
                 "AEST (2026-07-26T21:00:00Z), before the price extreme (interval ending 2026-07-30T21:30:00Z = 2026-07-31 "
                 "07:30 AEST).")
RULES_OUT = ("Timing rules this out: the AEMO market notice that mentions Hazelwood gives 2026-08-20 11:00 AEST "
             "(2026-08-20T01:00:00Z), after the price extreme (interval ending 2026-08-19T23:10:00Z = 2026-08-20 09:10 "
             "AEST), so what it reports came later.")


def _replay(path: Path, *, first_draft: bool = False, delete: str | None = None, headline: str | None = None):
    rec = json.loads(path.read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    patch: dict[str, Any] | None = None
    if first_draft:
        trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
        patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
        if delete:
            patch = {**patch, "edits": [e for e in patch["edits"] if not e["target"].startswith(delete)] +
                     [{"target": delete, "action": "delete", "text": None, "statement": None, "claim": None,
                       "citation": None}]}
    draft = rec["drafts"]["synthesis:draft"] if first_draft else (rec["drafts"].get("repair:draft")
                                                                  or rec["drafts"]["synthesis:draft"])
    if headline is not None:
        draft = {**draft, "headline": headline}
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    res = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)
    return res, draft


def _passes(res) -> bool:
    return bool(res.report.validation["final_passed"]) and not res.report.validation["fallback_applied"]


# ------------------------------------------------------------------------------------------------ causal questions
@pytest.mark.parametrize("path,kw", [(C0929 / "F04.json", {}), (C0930 / "F04.json", {"first_draft": True})])
def test_insufficient_evidence_is_the_headline_of_f04(path, kw):
    res, _ = _replay(path, **kw)
    assert _passes(res) and res.report.headline == CANNOT_SETTLE
    assert res.report.summary[0].startswith(CANNOT_SETTLE + " Its timing does not rule it out")  # the full answer stays


@pytest.mark.parametrize("path,kw", [(V4 / "W18.json", {}),
                                     (C0930 / "W18.json", {"first_draft": True, "delete": "possible_explanations[1]"})])
def test_timing_that_rules_it_out_is_the_headline_of_w18(path, kw):
    res, _ = _replay(path, **kw)
    assert _passes(res) and res.report.headline == RULES_OUT == res.report.summary[0]


# ------------------------------------------------------------------------------------------------ document answers
@pytest.mark.parametrize("path,starts", [
    (C0929 / "F03.json", "“At 1630 hrs 30/07/2026 there was a short notice outage of Belalie-Davenport 275kV line.” [c1] "
                         "(NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30 16:00 ACST.)"),
    (V4 / "W10.json", "“When Wholesale Demand Response is dispatched, scheduled demand will decrease"),  # statement [2]
    (V4 / "W15.json", "“The outage has been completed and Directlink all 3 cables returned to service at 1430 hrs"),  # [1]
])
def test_a_document_answer_is_headlined_by_the_statement_its_headline_paraphrases(path, starts):
    res, _ = _replay(path)
    assert _passes(res) and res.report.headline.startswith(starts)
    assert res.report.headline in res.report.summary  # a validated statement, as rendered: nothing new


# ------------------------------------------------------------------------------------------------ unchanged
@pytest.mark.parametrize("path,kw,why", [
    (V4 / "W01.json", {}, "an event question"),
    (V4 / "W05.json", {}, "a forecast question"),
    (C0930 / "W04.json", {"first_draft": True}, "a change question (its model headline already states the rise)"),
    (C0930 / "W19.json", {"first_draft": True}, "a causal question the controller cannot answer"),
])
def test_other_answers_keep_the_models_headline(path, kw, why):
    res, draft = _replay(path, **kw)
    assert _passes(res), why
    rec = json.loads(path.read_text())
    shown = rec["drafts"].get("repair:draft") or draft  # the headline after the run's own repair
    assert res.report.headline in (draft["headline"], shown["headline"]), why


@pytest.mark.parametrize("path,kw", [(V4 / "W14.json", {}), (C0930 / "W18.json", {"first_draft": True})])
def test_fallback_answers_keep_the_facts_only_headline(path, kw):
    res, _ = _replay(path, **kw)
    assert res.report.validation["fallback_applied"] and res.report.headline.startswith("Validated facts only")


def test_no_headline_adds_a_number_the_answer_does_not_show():
    for path, kw in ((C0929 / "F04.json", {}), (V4 / "W18.json", {}), (C0929 / "F03.json", {}), (V4 / "W15.json", {})):
        res, _ = _replay(path, **kw)
        shown = set(narrative_numbers(" ".join(res.report.summary)))
        assert set(narrative_numbers(res.report.headline)) <= shown, path.name


def test_a_headline_the_language_checks_act_on_is_kept_for_the_validator():
    """A model headline stating a cause is not hidden behind the controller's answer: the validator still sees it, and
    the answer is repaired or withheld as before (here the scripted repair repeats it, so the answer falls back)."""
    res, _ = _replay(C0929 / "F04.json", headline="Directlink being out of service caused the NSW1 price spike.")
    v = res.report.validation
    assert "UNSUPPORTED_CAUSALITY" in set(v.get("pre_repair_codes") or [])
    assert v["fallback_applied"] and res.report.headline.startswith("Validated facts only")
