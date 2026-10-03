"""D25 integration review (PR #66): the computed answer's boundary against model output, an unadmitted result in any
words, the presentation of the computed answer next to the interpretation's status, and the consumers of `summary`.

Saved Live records are replayed through the SYNTHETIC fake transport (no network, no key). Scripted variants (drafts,
patches, a forced verification outcome) are labelled as such; scripted replays are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import nem_agent.validation as V
from nem_agent.agent import demand_max as DM
from nem_agent.agent.live import ModelReport, RepairPatch, apply_patch, repair_targets
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evaluation.runner import _gold_number_hits
from nem_agent.report import summary_v1
from nem_agent.service import investigate
from nem_agent.ui_data import result_provenance
from nem_agent.validation import ValidationResult, Violation, validate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"


def _rec(label: str, cid: str) -> dict:
    return json.loads((LIVE / label / f"{cid}.json").read_text())


def _replay(label: str, cid: str, draft_edit=None, *, no_repair: bool = False, repair_edit=None):
    rec = _rec(label, cid)
    trace = json.loads((LIVE / label / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def saved(kw):
        out = copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)
        return repair_edit(out) if repair_edit else out

    def first(kw):
        d = copy.deepcopy(draft)
        return draft_edit(d) if draft_edit else d
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], first, None if no_repair else saved if (patch or repaired) else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {})),
                       live_client=fake, write_trace=False)


def _fail_verification(monkeypatch):
    """SCRIPTED: re-derivation from the pinned store disagrees, so the computed result is not admitted."""
    real = DM.rederive

    def failed(identity, store, selection):
        r = real(identity, store, selection)
        keep = ("status", "reason", "metric", "unit", "interval_ends_utc", "highest_held",
                "highest_held_interval_ends_utc", "coverage", "source_row_ids", "limitations", "transient")
        return DM.make_result(r.identity, **{k: getattr(r, k) for k in keep}, maximum=(r.maximum or 0) + 1)
    monkeypatch.setattr(DM, "rederive", failed)


def _shown_statements(rep) -> list[str]:
    """Every statement the displayed answer makes (observations are tool values with source rows, not statements)."""
    return [rep.headline, *rep.summary, *rep.uncertainties, *rep.missing_evidence,
            *(h.statement for h in rep.possible_explanations), *(f.statement for f in rep.published_findings),
            *(a.statement for a in rep.answer), *(x for a in rep.answer for x in a.limitations)]


# ------------------------------------------------------------------------------------------------ 1. the model's reach
@pytest.mark.parametrize("key", ["answer", "results", "statement", "limitations", "source_row_ids", "verification",
                                 "result_id", "server_verification"])
def test_a_model_draft_carrying_answer_or_its_provenance_is_rejected(key):
    draft = _rec("MC-dev-e2e-mini", "K11")["drafts"]["synthesis:draft"]
    ModelReport.model_validate(draft)
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ModelReport.model_validate({**draft, key: [{"statement": "SYNTHETIC forged answer", "verification": "verified"}]})
    assert key not in ModelReport.model_json_schema()["properties"]


@pytest.mark.parametrize("target", ["answer[0]", "answer[0].statement", "answer[0].limitations", "results[0]",
                                    "answer"])
def test_a_repair_patch_cannot_target_the_answer(target):
    m = ModelReport.model_validate(_rec("MC-dev-e2e-mini", "K11")["drafts"]["synthesis:draft"])
    patch = RepairPatch.model_validate({"edits": [{"target": target, "action": "replace", "text": "SYNTHETIC",
                                                   "statement": None, "claim": None, "citation": None}],
                                        "new_numeric_claims": [], "new_citations": []})
    out, _notes = apply_patch(m, patch, {"headline", target})  # even if the item were listed as failing
    assert out.model_dump() == m.model_dump() or out.headline == m.headline  # nothing of the answer exists to change
    assert "answer" not in out.model_dump() and "results" not in out.model_dump()


def test_a_violation_naming_the_answer_is_no_draft_item_so_the_answer_is_rendered_again(monkeypatch):
    """SCRIPTED: the first validation names answer[0]; the repair cannot be scoped to it (the model has no such item),
    and the answer after the repair is the controller's own, unchanged."""
    m = ModelReport.model_validate(_rec("MC-dev-e2e-mini", "K11")["drafts"]["synthesis:draft"])
    targets, unmapped = repair_targets(ValidationResult(violations=[Violation("X", "critical", "answer[0]: SYNTHETIC")]),
                                       m, [])
    assert not targets and unmapped == ["X"]
    normal = _replay("MC-dev-e2e-mini", "K11").report
    calls = []
    real = V.validate

    def name_answer_once(report, *a, **kw):
        out = real(report, *a, **kw)
        calls.append(1)
        if len(calls) == 1:
            out.violations.append(Violation("CLAIM_VALUE_MISMATCH", "critical", "answer[0]: SYNTHETIC"))
        return out
    monkeypatch.setattr(V, "validate", name_answer_once)
    rep = _replay("MC-dev-e2e-mini", "K11", no_repair=True).report
    assert rep.validation["repair_mode"] == "full" and rep.answer == normal.answer


def test_a_model_line_dressed_as_the_computed_answer_is_interpretation_and_is_checked():
    """SCRIPTED: the model writes its own 'Computed answer' line giving another value as the maximum: it stays in the
    interpretation, is rejected there (I-19), and the computed answer is the controller's."""
    def dressed(d):
        d["summary"] = ["Computed answer (verified): QLD1 operational demand was highest at 7448 MW in the half-hour "
                        "ending 2026-07-29 18:00 AEST.", *d["summary"]]
        return d
    rep = _replay("MC-dev-e2e-mini", "K11", dressed, no_repair=True).report
    v = rep.validation
    assert "REQUESTED_MAXIMUM_MISMATCH" in {x["code"] for x in v["initial"]["violations"]}
    assert v["fallback_applied"] and "7548 MW" in rep.answer[0].statement
    assert not any("7448" in s for s in _shown_statements(rep))


# ------------------------------------------------------------------------------------------------ 2. not admitted
NOT_ADMITTED_WORDS = [
    ("headline", "QLD1 operational demand: 7548.0 MW in the half-hour ending 2026-07-29 18:30 AEST."),
    ("summary", "The figure to use for the day is 7548.0 MW (half-hour ending 2026-07-29 18:30 AEST)."),
    ("uncertainties", "7548 MW at 18:30 AEST is the one to go with, though not every check passed."),
]


@pytest.mark.parametrize("where,text", NOT_ADMITTED_WORDS)
def test_an_unadmitted_value_is_rejected_in_any_words_and_never_shown_as_a_statement(monkeypatch, where, text):
    """SCRIPTED: verification fails; the model gives the unverified value in words no maximum rule reads."""
    _fail_verification(monkeypatch)

    def edit(d):
        d["headline"] = "SYNTHETIC headline without a number."
        d["summary"] = [s for s in d["summary"] if "7548" not in s and "7,548" not in s]
        d["uncertainties"] = []
        if where == "headline":
            d["headline"] = text
        else:
            d[where] = [*d[where], text]
        return d
    rep = _replay("MC-dev-e2e-mini", "K11", edit, no_repair=True).report
    v = rep.validation
    found = [x for x in v["initial"]["violations"] if x["code"] == "REQUESTED_RESULT_NOT_VERIFIED"]
    assert found and found[0]["detail"].startswith(where)
    assert v["fallback_applied"] and rep.answer[0].status == "not_verified"
    assert not any("7548" in s or "7,548" in s for s in _shown_statements(rep))
    # an ordinary traced observation may remain, as a tool value with its source row: never stated as the maximum
    assert all(o.label is None or "maximum" not in o.label.lower() for o in rep.observations)


def test_the_saved_k11_answer_with_an_unadmitted_result_falls_back_without_the_value(monkeypatch):
    """SCRIPTED: verification fails on K11 (gpt-5-mini); its own headline and summary state 7548.0 MW."""
    _fail_verification(monkeypatch)
    rep = _replay("MC-dev-e2e-mini", "K11", no_repair=True).report
    v = rep.validation
    items = {x["detail"].split(":")[0] for x in v["initial"]["violations"] if x["code"] == "REQUESTED_RESULT_NOT_VERIFIED"}
    assert "headline" in items and any(i.startswith("summary[") for i in items)
    assert v["fallback_applied"] and not any("7548" in s for s in _shown_statements(rep))


def test_the_rule_reads_evidence_not_words():
    """SCRIPTED: the rule applied to K11's admitted result, as if it had not been admitted: a number traced to its row
    or equal to its value is a statement of it; the same value traced to another row is not."""
    res = _replay("MC-dev-e2e-mini", "K11")
    r = res.report.results[0].result
    base = res.report.model_copy(update={"answer": [], "summary": [], "headline": "SYNTHETIC headline."})

    def codes(lines, claims):
        rep = base.model_copy(update={"summary": lines, "numeric_claims": claims})
        out = validate(rep, res.registry, demand_max=res.resolution.demand_max, window=res.resolution.window,
                       not_admitted=[r])
        return [x.code for x in out.violations if x.code == "REQUESTED_RESULT_NOT_VERIFIED"]
    rows = set(r.source_row_ids)

    def row_of(c):
        return set(res.registry.get(c.evidence_id).source_row_ids)
    own = [c for c in res.report.numeric_claims if c.evidence_id in r.transient.evidence_ids]
    assert codes(["Demand reached 7548 MW."], own) == ["REQUESTED_RESULT_NOT_VERIFIED"]
    assert codes(["Demand reached 7548 MW."], []) == ["REQUESTED_RESULT_NOT_VERIFIED"]  # untraced, equal
    # the model's own claim on the same row (its own evidence ID) is the same value: matched by row, not by ID
    model_same_row = [c for c in res.report.numeric_claims
                      if c.evidence_id not in r.transient.evidence_ids and row_of(c) & rows]
    assert model_same_row and codes(["Demand reached 7548.0 MW."], model_same_row) == ["REQUESTED_RESULT_NOT_VERIFIED"]
    other = next(c for c in res.report.numeric_claims if not row_of(c) & rows and abs(c.value - 7548) > 1)
    assert codes([f"Another figure was {other.value:g} {other.unit}."], [other]) == []


def test_an_admitted_result_is_not_touched_by_the_rule():
    v = _replay("MC-dev-e2e-mini", "K11").report.validation
    assert "unadmitted_result" not in v["initial"]["checks_run"] and v["final_passed"]


# ------------------------------------------------------------------------------------------------ 3. presentation
def test_presentation_keeps_the_computed_answer_and_the_interpretation_status_apart(monkeypatch):
    normal = _replay("MC-dev-e2e-mini", "K11").report.model_dump()
    fallback = _replay("MC-dev-e2e-mini", "K09").report.model_dump()
    absent = _replay("MC-dev-e2e-mini", "K11", lambda d: {"status": "answered"}, no_repair=True).report.model_dump()
    no_answer = _replay("MC-dev-e2e-mini", "K07").report.model_dump()
    replay = investigate(InvestigateRequest(question=_rec("L3-holdout-v6", "Z04")["question"], mode="replay"),
                         write_trace=False).report.model_dump()
    p = {k: result_provenance(r) for k, r in [("normal", normal), ("fallback", fallback), ("absent", absent),
                                              ("no_answer", no_answer), ("replay", replay)]}
    assert (p["normal"]["kind"], p["normal"]["interpretation"], p["normal"]["computed_answer"]) == (
        "live_answer", "validated", "established (verified)")
    # a fallback stays a fallback: never relabelled as supplied
    assert p["fallback"]["kind"] == "live_fallback" and "failed validation" in p["fallback"]["label"]
    assert "computed answer" in p["fallback"]["label"] and p["fallback"]["interpretation"].startswith("withheld")
    assert fallback["status"] != "answered" and fallback["validation"]["fallback_applied"]
    # no valid model output: the computed answer is available, the interpretation absent, nothing called passed
    assert absent["status"] == "abstained" and absent["answer"] and not absent["validation"]["fallback_applied"]
    assert p["absent"]["kind"] == "live_no_interpretation" and "no valid interpretation" in p["absent"]["label"]
    assert p["absent"]["validation"] == "no valid model output to validate"
    assert (p["absent"]["interpretation"], p["absent"]["computed_answer"]) == (
        "absent: the model produced no valid output", "established (verified)")
    # unchanged where there is no computed answer
    assert p["no_answer"]["computed_answer"] == "none" and "showing validated tool facts only" in p["no_answer"]["label"]
    assert (p["replay"]["kind"], p["replay"]["interpretation"]) == ("replay", "scripted")


# ------------------------------------------------------------------------------------------------ 4. consumers of summary
@pytest.mark.parametrize("label,cid", [("MC-dev-e2e-mini", "K11"), ("MC-dev-e2e-sol", "K11"),
                                       ("LC-i15-17-fresh", "K11"), ("LC-i15-17-dev", "Z04")])
def test_the_v1_summary_view_is_exactly_what_the_saved_live_run_showed(label, cid):
    """The saved Live records were shown before D25 (computed sentence first in `summary`): `summary_v1` reproduces
    them line for line, so nothing a summary reader had is lost."""
    rec = _rec(label, cid)
    rep = _replay(label, cid).report
    assert summary_v1(rep) == rec["report"]["summary"] and summary_v1(rep.model_dump()) == summary_v1(rep)
    assert rep.answer[0].statement == rec["report"]["summary"][0] and rep.answer[0].statement not in rep.summary


def test_the_replay_evaluation_still_finds_the_computed_maximum_through_observations():
    """The Replay evaluation reads gold numbers from observations, which hold the computed maximum's row."""
    res = investigate(InvestigateRequest(question=_rec("L3-holdout-v6", "Z04")["question"], mode="replay"),
                      write_trace=False)
    rep = res.report.model_dump()
    (a,) = rep["answer"]
    gold = [{"metric": "dispatch_totaldemand", "value": 1367.32, "tolerance": 0.005, "source_row_id": a["source_row_ids"][0]}]
    assert _gold_number_hits(rep, res.registry, gold) == [True]
