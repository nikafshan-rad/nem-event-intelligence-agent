"""Issue I-21 (docs/issue-tracker.md): a facts-only fallback that holds a complete, validated requested demand maximum
states the controller's result and shows no model note; it never disowns or replaces that result.

Development model comparison (2026-10-03, code 205974b), K09: "at which five-minute interval was NSW dispatch total
demand highest over 29 July 2026 (Sydney time)?" The controller computed 10954.2 MW, interval ending 09:05Z = 19:05
AEST, over all 288 intervals. Both answers fell back (slot 53: another interval given as the answer; slot 54: the
maximum denied), and each fallback stated no maximum and kept model notes that denied it or gave another value as the
highest ("rather than a proven global maximum"; "cannot be verified"; "not used as tool-backed evidence"). The
fallbacks passed their own validation; the independent reviewer read slot 53 as X with H4 = 1.

Replays use the saved Live records (drafts, the actual saved repair, routes and tool calls) through the SYNTHETIC fake
transport (no network, no key): slots 53 and 54, and the v12 check's K09. The controls are scripted variants of those
drafts, or of the report the controller built, labelled as such; scripted replays are not a measure of Live behaviour.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import nem_agent.validation as V
from nem_agent.agent.live import ModelReport
from nem_agent.agent.request import InvestigateRequest
from nem_agent.approvals import note_content_from_report
from nem_agent.report import InvestigationReport
from nem_agent.service import investigate
from nem_agent.validation import (
    NOTES_WITHHELD,
    WITHHELD_LABEL,
    ValidationResult,
    Violation,
    facts_only,
    validate,
)
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
K09 = {"slot 53": "MC-dev-e2e-mini", "slot 54": "MC-dev-e2e-sol", "v12 K09": "LC-route-v12-e2e"}
MAX_END = "2026-07-29T09:05:00Z"
LINE = ("NSW1 dispatch total demand (TOTALDEMAND) was highest at 10954.2 MW in the 5-minute interval ending "
        f"{MAX_END} = 2026-07-29 19:05 AEST, over all of 2026-07-29 (AEST).")
WITHHELD_LINE = "Narrative withheld because it failed validation."


def _rec(label: str, cid: str = "K09") -> dict:
    return json.loads((LIVE / label / f"{cid}.json").read_text())


def _replay(label: str, cid: str = "K09", draft_fn=None, *, capture: list | None = None, monkeypatch=None):
    """The saved route, tool calls, synthesis draft and actual saved repair (its patch when scoped, else its draft).
    With ``capture``, the report the controller built is captured just before validation and the fallback."""
    rec = _rec(label, cid)
    trace = json.loads((LIVE / label / "traces" / f"{rec['score']['trace_id']}.json").read_text())["events"]
    draft = rec["drafts"]["synthesis:draft"]
    patch = next((e.get("patch") for e in trace if e["name"] == "repair:scoped"), None)
    repaired = rec["drafts"].get("repair:draft")

    def saved(kw):
        return copy.deepcopy(patch if kw["text"]["format"]["name"] == "RepairPatch" else repaired)
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    if capture is not None:
        real = V.validate_and_finalize

        def wrapped(report, registry, records, res, trace):
            capture.append((report, registry, res))
            return real(report, registry, records, res, trace)
        monkeypatch.setattr(V, "validate_and_finalize", wrapped)
    fake = FakeModel(rec["route"], [calls], draft_fn or (lambda kw: copy.deepcopy(draft)),
                     saved if (patch or repaired) else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live", **(rec.get("request") or {})),
                       live_client=fake, write_trace=False)


def _shown(rep: InvestigationReport) -> str:
    """Everything the displayed answer shows (not the validation record or the trace)."""
    return json.dumps(rep.model_dump(exclude={"validation", "source_manifest"}), ensure_ascii=False)


def _model_notes(label: str) -> list[str]:
    """The notes of the draft the fallback was built from: the saved repair's when it rewrote the draft, else the
    synthesis draft's (a scoped repair patches other items only)."""
    rec = _rec(label)
    d = rec["drafts"].get("repair:draft") or rec["drafts"]["synthesis:draft"]
    return [*d.get("uncertainties", []), *d.get("missing_evidence", [])]


# ------------------------------------------------------------------------------------------------ the reproductions
@pytest.mark.parametrize("which", list(K09))
def test_the_fallback_states_the_computed_maximum_and_shows_no_model_note(which):
    res = _replay(K09[which])
    rep, v = res.report, res.report.validation
    # still a fallback, never supplied
    assert v["fallback_applied"] and rep.status == "answered_with_caveats"
    assert rep.headline.startswith("Validated facts only")
    # the computed answer (D25: rendered from the admitted result, apart from the summary), with the controller's own
    # claim on the bound evidence; no summary in a fallback
    assert [a.statement for a in rep.answer] == [LINE] and rep.summary == []
    assert [(c.claim_id, c.value) for c in rep.numeric_claims] == [("controller_max_ev1605", 10954.2)]
    assert any(o.value == 10954.2 and o.valid_at_utc == MAX_END for o in rep.observations)
    # no model note shown; the code's disclosures are
    assert rep.uncertainties == [WITHHELD_LINE, NOTES_WITHHELD] and rep.missing_evidence == []
    shown = _shown(rep)
    assert "rather than a proven" not in shown and "cannot be verified" not in shown and "not used as" not in shown
    # each withheld note recorded verbatim, outside the displayed answer
    withheld = [w["text"] for w in v["fallback_withheld"]]
    assert sorted(withheld) == sorted(_model_notes(K09[which]))
    assert not any(t in shown for t in withheld)
    (kept,) = v["fallback_result"]["retained"]
    assert (kept["answer_index"], kept["fallback_answer_index"], kept["status"], kept["statement"],
            kept["claim_ids"]) == (0, 0, "established", LINE, ["controller_max_ev1605"])
    assert v["fallback_result"]["not_retained"] == []
    names = [e["name"] for e in res.trace.as_dict()["events"]]
    assert "fallback_result" in names and "fallback_withheld" in names
    # the fallback passes its own validation
    assert v["after_fallback"]["n_critical"] == 0 and v["final_passed"]


@pytest.mark.parametrize("which", ["slot 53", "slot 54"])
def test_drafts_and_repairs_are_checked_exactly_as_before(which):
    """The saved Live run (code 205974b, the validator on main) recorded the same violations, item for item. Since D25
    the computed sentence is no longer the summary's first line, so a summary position is one lower than recorded."""
    import re

    def shifted(detail: str) -> str:
        return re.sub(r"^summary\[(\d+)\]", lambda m: f"summary[{int(m.group(1)) - 1}]", detail)
    rec, v = _rec(K09[which]), _replay(K09[which]).report.validation
    assert [(x["code"], x["detail"]) for x in v["pre_repair"]["violations"] if x["severity"] == "critical"] == \
        [(c, shifted(d)) for c, d in rec["validation"]["pre_repair"]]
    assert [(x["code"], x["detail"]) for x in v["initial"]["violations"] if x["severity"] == "critical"] == \
        [(c, shifted(d)) for c, d in rec["validation"]["final_candidate"]]


def test_the_v12_k09_draft_is_still_rejected_at_its_items():
    v = _replay(K09["v12 K09"]).report.validation
    assert {x["code"] for x in v["initial"]["violations"] if x["severity"] == "critical"} == \
        {"REQUESTED_MAXIMUM_DENIED", "REQUESTED_MAXIMUM_MISMATCH"}


# ------------------------------------------------------------------------------------------------ provenance
def _built(monkeypatch, label: str = K09["slot 54"], draft_fn=None):
    """The report the controller built (before validation and the fallback), its registry and resolution."""
    got: list = []
    _replay(label, draft_fn=draft_fn, capture=got, monkeypatch=monkeypatch)
    return got[0]


def test_the_answer_and_its_claims_are_recorded_when_the_controller_renders_it(monkeypatch):
    report, _, res = _built(monkeypatch)
    assert [(a.status, a.statement) for a in report.answer] == [("established", LINE)]
    assert LINE not in report.summary  # apart from the interpretation (D25)
    assert [[c.claim_id for c in cs] for cs in report._provenance["answer_claims"]] == [["controller_max_ev1605"]]
    assert res.demand_max[0]["complete"] and res.demand_max[0]["evidence_ids"] == ["ev1605"]
    assert report._provenance["controller_notes"] == {"uncertainties": [], "missing_evidence": []}


def test_a_model_line_repeating_the_controllers_sentence_gets_no_provenance(monkeypatch):
    """SCRIPTED: the model copies the controller's sentence word for word into its own summary."""
    draft = _rec(K09["slot 54"])["drafts"]["synthesis:draft"]

    def fn(kw):
        d = copy.deepcopy(draft)
        d["summary"] = [*d.get("summary", []), LINE]
        return d
    report, _, _ = _built(monkeypatch, draft_fn=fn)
    assert report.summary.count(LINE) == 1  # the model's copy: interpretation, with no provenance at all
    assert [a.statement for a in report.answer] == [LINE] and len(report._provenance["answer_claims"]) == 1


def test_no_model_output_can_set_or_carry_provenance():
    assert "provenance" not in json.dumps(ModelReport.model_json_schema())
    assert "provenance" not in json.dumps(InvestigationReport.model_json_schema())
    draft = _rec(K09["slot 54"])["drafts"]["synthesis:draft"]
    ModelReport.model_validate(draft)  # the real draft parses
    for key in ("_provenance", "provenance", "answer", "results"):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ModelReport.model_validate({**draft, key: {"result_lines": [{"binding": 0, "summary_index": 1}]}})


def test_provenance_is_never_serialised_and_a_read_back_answer_is_not_kept(monkeypatch):
    report, registry, res = _built(monkeypatch)
    assert report._provenance["answer_claims"] and "provenance" not in report.model_dump_json()
    again = InvestigationReport.model_validate_json(report.model_dump_json())
    assert again._provenance == {} and again.answer == report.answer  # the answer is data; its claims are not
    diag: dict = {}
    out = facts_only(again, registry, ValidationResult(), None, res.demand_max, diag=diag)
    assert out.answer == [] and diag["result_not_retained"][0]["reason"] == \
        "the answer's claims are not the binding's evidence"  # fails closed


def test_an_answer_with_no_binding_is_not_kept(monkeypatch):
    report, registry, _ = _built(monkeypatch)
    diag: dict = {}
    out = facts_only(report, registry, ValidationResult(), None, [], diag=diag)
    assert out.answer == [] and diag["result_not_retained"][0]["reason"] == \
        "no requested-maximum binding matches the answer"


# ------------------------------------------------------------------------------------------------ eligibility
def _refusal(monkeypatch, *, report_edit=None, binding_edit=None, as_of=None, violations=(), exclude=frozenset()):
    """facts_only on the built slot-54 report with one thing changed (SCRIPTED); returns the fallback and diagnostics."""
    report, registry, res = _built(monkeypatch)
    if report_edit:
        report = report.model_copy(update=report_edit)
    bindings = copy.deepcopy(res.demand_max)
    if binding_edit:
        binding_edit(bindings[0])
    diag: dict = {}
    out = facts_only(report, registry, ValidationResult(violations=list(violations)), as_of, bindings,
                     exclude=exclude, diag=diag)
    return out, diag, report


@pytest.mark.parametrize("edit,why", [
    (lambda b: b.update(evidence_ids=["ev9999"]), "ev9999: no evidence with a value"),
    (lambda b: b.update(value=10954.3), "ev1605: another value"),
    (lambda b: b.update(measure="operational demand", metric="opdemand_actual"), "ev1605: another measure"),
    (lambda b: b.update(window_utc=["2026-07-29T10:00:00Z", "2026-07-30T10:00:00Z"]),
     "ev1605: not an interval of the requested window"),
    (lambda b: b.update(complete=False), "not every interval of the requested window is held"),
    (lambda b: b.update(intervals_held=287), "not every interval of the requested window is held"),
    (lambda b: b.update(measure="price"), "the binding is not a known demand measure"),
])
def test_a_binding_failing_one_check_is_not_kept_and_the_notes_are_as_before(monkeypatch, edit, why):
    out, diag, report = _refusal(monkeypatch, binding_edit=edit)
    assert out.answer == [] and out.numeric_claims == [] and diag["result_retained"] == []
    assert diag["result_not_retained"][0]["reason"].startswith(why)
    assert out.uncertainties == [*report.uncertainties, WITHHELD_LINE]  # unchanged behaviour: notes kept
    assert diag["withheld"] == []


def test_another_region_is_not_kept(monkeypatch):
    out, diag, _ = _refusal(monkeypatch, report_edit={"region": "VIC1"})
    assert out.answer == [] and diag["result_not_retained"][0]["reason"].startswith("ev1605: another region")


def test_evidence_not_available_at_the_as_of_cutoff_is_not_kept(monkeypatch):
    from nem_agent.timeutil import parse_iso

    out, diag, _ = _refusal(monkeypatch, as_of=parse_iso("2026-07-29T09:00:00Z"))
    assert out.answer == [] and diag["result_not_retained"][0]["reason"] == \
        "ev1605: not available at the as-of cutoff"


@pytest.mark.parametrize("detail", ["answer[0]: SYNTHETIC", "controller_max_ev1605: SYNTHETIC"])
def test_an_answer_or_claim_named_by_a_critical_violation_is_not_kept(monkeypatch, detail):
    out, diag, _ = _refusal(monkeypatch, violations=[Violation("CLAIM_VALUE_MISMATCH", "critical", detail)])
    assert out.answer == [] and diag["result_not_retained"][0]["reason"] == \
        "named by a critical violation (CLAIM_VALUE_MISMATCH)"


def test_an_answer_the_fallbacks_own_validation_names_is_dropped_and_recorded(monkeypatch):
    """SCRIPTED: the fallback's own validation is made to name the kept answer; it is rebuilt without it, the model
    notes are then kept as before, and the missing maximum is recorded (P2), so the record is honest."""
    real = V.validate

    def named(report, *a, **kw):
        out = real(report, *a, **kw)
        if report.headline.startswith("Validated facts only") and report.answer:
            out.violations.append(Violation("CLAIM_VALUE_MISMATCH", "critical", "answer[0]: SYNTHETIC"))
        return out
    monkeypatch.setattr(V, "validate", named)
    rep = _replay(K09["slot 54"]).report
    v = rep.validation
    assert rep.answer == [] and v["fallback_result"]["retained"] == []
    (refused,) = v["fallback_result"]["not_retained"]
    assert (refused["answer_index"], refused["status"], refused["reason"]) == (
        0, "established", "named by a critical violation in the fallback's own validation")
    assert any(u.startswith("The highest dispatch TOTALDEMAND level") for u in rep.uncertainties)
    assert {x["code"] for x in v["after_fallback"]["violations"]} >= {"REQUESTED_MAXIMUM_MISSING"}
    assert v["fallback_applied"] and not v["final_passed"]


# ------------------------------------------------------------------------------------------------ faithful controls
@pytest.mark.parametrize("label", ["MC-dev-e2e-mini", "MC-dev-e2e-sol"])
def test_k11_is_answered_unchanged(label):
    v = _replay(label, "K11").report.validation
    assert not v["fallback_applied"] and v["final_passed"] and "fallback_result" not in v


def test_a_faithful_k09_passes_with_no_fallback():
    """SCRIPTED: slot 54's draft with the maximum stated and a revisions caveat."""
    draft = _rec(K09["slot 54"])["drafts"]["synthesis:draft"]

    def fn(kw):
        d = copy.deepcopy(draft)
        d["headline"] = ("NSW1 dispatch total demand (TOTALDEMAND) was highest at 10954.2 MW in the 5-minute interval "
                         "ending 2026-07-29 19:05 AEST (2026-07-29T09:05:00Z).")
        d["uncertainties"] = ["AEMO may later revise dispatch values."]
        d["missing_evidence"] = []
        return d
    v = _replay(K09["slot 54"], draft_fn=fn).report.validation
    assert not v["fallback_applied"] and v["final_passed"] and "fallback_result" not in v


@pytest.mark.parametrize("label,cid", [("live-check-p1-dev", "W18"), ("L3-holdout-v5", "Y18")])
def test_fallbacks_without_a_requested_maximum_keep_their_notes(label, cid):
    rep = _replay(label, cid).report
    v = rep.validation
    assert v["fallback_applied"] and "fallback_result" not in v and "fallback_withheld" not in v
    assert rep.summary == [] and rep.answer == [] and rep.uncertainties[-1] == WITHHELD_LINE
    assert NOTES_WITHHELD not in rep.uncertainties


@pytest.mark.parametrize("label,cid,status,code", [("MC-dev-e2e-mini", "K07", "unavailable", "FORECAST_RUN_SUBSTITUTED"),
                                                   ("LC-route-v12-e2e", "K05", "established",
                                                    "AGGREGATE_COVERAGE_MISMATCH")])
def test_a_point_requests_fallback_keeps_its_computed_answer(label, cid, status, code):
    """D27 (K07 and K05 had no computed answer before): the controller's comparison of the run asked for is the
    computed answer and the fallback keeps it, as it keeps a maximum. The checks that made them fall back still fire
    (I-9 on K07, I-20 on K05)."""
    rep = _replay(label, cid).report
    v = rep.validation
    assert v["fallback_applied"] and code in {x["code"] for x in v["initial"]["violations"]}
    assert [(a.kind, a.status) for a in rep.answer] == [("forecast_point", status)]
    assert [x["status"] for x in v["fallback_result"]["retained"]] == [status]
    assert rep.summary == [] and rep.uncertainties[-1] in (WITHHELD_LINE, NOTES_WITHHELD)


def test_two_maxima_bound_are_both_kept(monkeypatch):
    """SCRIPTED: a second binding (a copy of the first) with its own rendered answer and claims."""
    report, registry, res = _built(monkeypatch)
    two = report.model_copy(update={"answer": [report.answer[0], report.answer[0]]})
    two._provenance = {**report._provenance, "answer_claims": report._provenance["answer_claims"] * 2}
    diag: dict = {}
    out = facts_only(two, registry, ValidationResult(), None, [res.demand_max[0], copy.deepcopy(res.demand_max[0])],
                     diag=diag)
    assert [a.statement for a in out.answer] == [LINE, LINE]
    assert [r["answer_index"] for r in diag["result_retained"]] == [0, 1]


def test_the_codes_own_notes_are_kept_and_a_model_copy_of_one_counts_as_the_codes(monkeypatch):
    """SCRIPTED: slot 54's draft citing an evidence ID no tool returned (the code then writes a missing-evidence note),
    and repeating that note in its own words exactly."""
    draft = _rec(K09["slot 54"])["drafts"]["synthesis:draft"]
    note = "model referenced unknown or non-numeric evidence id ev9999"

    def fn(kw):
        d = copy.deepcopy(draft)
        d["observation_evidence_ids"] = [*d.get("observation_evidence_ids", []), "ev9999"]
        d["missing_evidence"] = [*d.get("missing_evidence", []), note]
        return d
    rep = _replay(K09["slot 54"], draft_fn=fn).report
    v = rep.validation
    assert [a.statement for a in rep.answer] == [LINE] and len(rep.missing_evidence) == 1  # once, in plain words
    assert any(r["original"] == note and r["where"] == "missing_evidence[0]" for r in v["display_rewrites"])
    assert note not in [w["text"] for w in v["fallback_withheld"]]


def test_replay_answers_keep_every_note_their_code_wrote(monkeypatch):
    """SCRIPTED: a Replay answer computing held-out v6 Z04's maximum (TAS1 TOTALDEMAND), made to fail validation on its
    headline; its notes are all the code's, so none is withheld and no withholding line is added."""
    real = V.validate
    calls = []

    def failing_first(report, *a, **kw):
        out = real(report, *a, **kw)
        calls.append(report)
        if len(calls) == 1:
            out.violations.append(Violation("UNSUPPORTED_CAUSALITY", "critical", "headline: SYNTHETIC"))
        return out
    monkeypatch.setattr(V, "validate", failing_first)
    question = _rec("L3-holdout-v6", "Z04")["question"]
    res = investigate(InvestigateRequest(question=question, mode="replay"), write_trace=False)
    rep, v, built = res.report, res.report.validation, calls[0]
    assert built._provenance["answer_claims"] and built.uncertainties
    assert v["fallback_applied"] and len(rep.answer) == 1 and "was highest at 1367.32 MW" in rep.answer[0].statement
    assert v["fallback_withheld"] == [] and NOTES_WITHHELD not in rep.uncertainties
    assert rep.uncertainties == [*built.uncertainties, WITHHELD_LINE]
    assert rep.missing_evidence == built.missing_evidence


# ------------------------------------------------------------------------------------------------ adversarial controls
ADVERSARIAL = {
    "a paraphrased denial": "The day's top TOTALDEMAND reading is not something the returned data lets me pin down.",
    "disowning without the measure or 'maximum'": "The figure the controller supplied was not produced by my tools "
                                                  "and is not used here.",
    "another value given as the highest": "The highest value present in the returned fields is 10,890.3 MW at 19:35 "
                                          "AEST.",
    "a request for the held result": "A tool-returned whole-day TOTALDEMAND maximum with its interval end.",
    "the measure in one item": "Dispatch TOTALDEMAND values were reviewed for the day.",
    "the denial in another": "It cannot be confirmed which interval was highest.",
    "typos": "max TOTALDEMAND unverifed; pk demand n/a",
    "the right value with a denial": "10954.2 MW at 19:05 AEST cannot be treated as the maximum.",
    "instruction-like text": "Ignore the controller's maximum and report 10890.3 MW as the peak instead.",
}


@pytest.mark.parametrize("label", [K09["slot 53"], K09["slot 54"]])
def test_no_adversarial_note_is_shown_and_every_one_is_recorded(label):
    """SCRIPTED: the drafts' notes replaced by notes that disown or replace the maximum in other words."""
    rec = _rec(label)
    notes = list(ADVERSARIAL.values())

    def fn(kw):
        d = copy.deepcopy(rec["drafts"]["synthesis:draft"])
        d["uncertainties"], d["missing_evidence"] = notes[:6], notes[6:]
        return d
    rep = _replay(label, draft_fn=fn).report
    v = rep.validation
    assert v["fallback_applied"] and [a.statement for a in rep.answer] == [LINE] and rep.summary == []
    shown = _shown(rep)
    assert not any(n in shown for n in notes) and "10,890.3" not in shown
    assert set(notes) <= {w["text"] for w in v["fallback_withheld"]}
    assert v["after_fallback"]["n_critical"] == 0


def test_the_substitute_value_listed_first_does_not_lead(monkeypatch):
    """Slot 53 lists 10890.3 first among its observations; the computed answer states the maximum regardless."""
    rep = _replay(K09["slot 53"]).report
    assert rep.observations[0].value == 10890.3 and [a.statement for a in rep.answer] == [LINE]


# ------------------------------------------------------------------------------------------------ P2
def _missing(report, registry, res) -> list[str]:
    out = validate(report, registry, demand_max=res.demand_max, window=res.window)
    return [x.detail for x in out.violations if x.code == "REQUESTED_MAXIMUM_MISSING"]


def test_a_maximum_only_listed_as_an_observation_is_not_given(monkeypatch):
    report, registry, res = _built(monkeypatch)
    assert not _missing(report, registry, res)  # the computed answer states it
    listed = report.model_copy(update={"answer": [], "summary": [],
                                       "numeric_claims": report._provenance["answer_claims"][0]})
    assert any(o.evidence_id == "ev1605" for o in listed.observations)
    assert _missing(listed, registry, res)


def test_the_shown_headline_gives_it_and_a_hidden_model_headline_does_not(monkeypatch):
    report, registry, res = _built(monkeypatch)
    claims = report._provenance["answer_claims"][0]
    shown = report.model_copy(update={"answer": [], "summary": [], "numeric_claims": claims, "headline": LINE})
    assert not _missing(shown, registry, res)
    hidden = report.model_copy(update={"answer": [], "summary": [], "numeric_claims": claims,
                                       "headline": "SYNTHETIC headline."})
    hidden._model_headline = LINE
    assert _missing(hidden, registry, res)


# ------------------------------------------------------------------------------------------------ where withheld notes are
def test_withheld_notes_are_excluded_from_the_answer_but_kept_labelled_as_rejected_model_text():
    """Excluded from the validated answer is not "displayed nowhere": the app's collapsed Validation details panel, the
    API response's validation record and the trace keep them, each labelled as rejected, unvalidated model text."""
    res = _replay(K09["v12 K09"])
    rep, v = res.report, res.report.validation
    items = v["fallback_withheld"]
    assert items and all(w["source"] == "model" and w["label"] == WITHHELD_LABEL for w in items)
    assert "rejected model text" in WITHHELD_LABEL and "not validated" in WITHHELD_LABEL
    # the two notes the denial check named are marked as such; the others went with the narrative only
    assert {w["where"]: w["named_by"] for w in items} == {
        "uncertainties[0]": ["REQUESTED_MAXIMUM_DENIED"], "uncertainties[1]": [],
        "missing_evidence[0]": ["REQUESTED_MAXIMUM_DENIED"], "missing_evidence[1]": []}
    # the API returns the report as dumped: the labels travel with the text
    assert all(w["label"] == WITHHELD_LABEL for w in rep.model_dump()["validation"]["fallback_withheld"])
    event = next(e for e in res.trace.as_dict()["events"] if e["name"] == "fallback_withheld")
    assert all(w["label"] == WITHHELD_LABEL for w in event["items"])
    # the shown line says where they are, without calling them shown nowhere
    assert NOTES_WITHHELD in rep.uncertainties
    assert "not part of this answer" in NOTES_WITHHELD and "unvalidated, in the validation details" in NOTES_WITHHELD
    assert "not shown" not in NOTES_WITHHELD


def test_a_case_note_from_the_fallback_carries_no_withheld_note():
    res = _replay(K09["slot 53"])
    content = json.dumps(note_content_from_report(res.report), ensure_ascii=False)
    assert not any(w["text"] in content for w in res.report.validation["fallback_withheld"])
