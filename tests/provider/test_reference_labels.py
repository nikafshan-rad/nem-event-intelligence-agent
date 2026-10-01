"""Issue I-4b (docs/issue-tracker.md): a reference label without a colon is not shown as "the listed observation".

Live, second development check (2026-09-30), F04: the model wrote "There were 14 five-minute intervals at or above the
analysis threshold of 300.0 $/MWh in the window (ev0876; threshold ev0878)." The display step (I-4) showed "… in the
window (threshold the listed observation)." A label with no colon before an evidence ID ("threshold ev0878") matched
none of its marker rules, so the ID was read as a noun.

Now a bracket of nothing but evidence references is removed whole, including IDs after a lower-case label. An ID right
after a label is removed and the label kept. An ID used as a noun keeps "the listed observation". Quotations, source
identifiers and every number stay. Replays use saved Live records through the SYNTHETIC fake transport (no network, no
key).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import narrative_numbers
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

DEV2 = Path(__file__).resolve().parents[2] / "artifacts" / "live" / "live-check-dev2"
F04_SENTENCE = ("There were 14 five-minute intervals at or above the analysis threshold of 300.0 $/MWh in the window "
                "(ev0876; threshold ev0878).")


def plain_text(text: str) -> str:
    from nem_agent.display import plain_text as plain

    return plain(text)


def _replay(path: Path, summary_update=None):
    """A saved run's first draft and actual saved repair; ``summary_update`` edits the repaired draft's summary."""
    rec = json.loads(path.read_text())
    trace = json.loads((path.parent / "traces" / f"{rec['score']['trace_id']}.json").read_text())
    draft = next(e for e in trace["events"] if e["name"] == "synthesis:draft")["report"]
    patch = next(e for e in trace["events"] if e["name"] == "repair:scoped")["patch"]
    if summary_update:
        draft = {**draft, "summary": summary_update(draft["summary"])}
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft), lambda kw: copy.deepcopy(patch))
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


# ------------------------------------------------------------------------------------------------ the saved example
def test_f04s_sentence_keeps_its_threshold_and_loses_its_references():
    out = plain_text(F04_SENTENCE)
    assert out == "There were 14 five-minute intervals at or above the analysis threshold of 300.0 $/MWh in the window."
    assert set(narrative_numbers(out)) == set(narrative_numbers(F04_SENTENCE)) >= {14.0, 300.0}


def test_f04s_replayed_answer_shows_no_listed_observation():
    """F04's own first draft and actual repair: the repaired summary carries the sentence above."""
    res = _replay(DEV2 / "F04.json")
    v, rep = res.report.validation, res.report
    assert v["final_passed"] and not v["fallback_applied"]
    line = next(s for s in rep.summary if s.startswith("There were 14 five-minute intervals"))
    assert line.endswith("analysis threshold of 300.0 $/MWh in the window.") and "listed observation" not in line
    original = next(r["original"] for r in v["display_rewrites"] if r["original"].startswith("There were 14"))
    assert "(ev0876; threshold ev0878)" in original  # the original stays in the record
    assert {"ev0876", "ev0878"} <= {c.evidence_id for c in rep.numeric_claims}  # and the claims keep their evidence


# ------------------------------------------------------------------------------------------------ the forms
@pytest.mark.parametrize("before,after", [
    # colon and colon-less labels in a bracket of references only: removed whole
    ("Six intervals (threshold ev0878).", "Six intervals."),
    ("Six intervals (threshold: ev0878).", "Six intervals."),
    ("Six intervals (ev0945; threshold ev0946).", "Six intervals."),
    ("Six intervals (evidence: ev0003; threshold evidence: ev0004).", "Six intervals."),
    ("Six intervals (count ev0876, threshold: ev0878 and ev0879).", "Six intervals."),
    ("Six intervals (net interchange ev0438) were seen.", "Six intervals were seen."),
    # a label right before the IDs: the IDs go, the label stays
    ("Compare it with the net interchange value ev0438.", "Compare it with the net interchange value."),
    ("Check the runs ev0568 and ev0064, and the notes.", "Check the runs, and the notes."),
    ("the POE50 = 1508.0 MW run ev0568 and the POE50 = 1510.0 MW run ev0064",
     "the POE50 = 1508.0 MW run and the POE50 = 1510.0 MW run"),
])
def test_reference_labels_with_and_without_a_colon(before, after):
    assert plain_text(before) == after


@pytest.mark.parametrize("before,after", [
    # mixed: substance in the bracket stays
    ("Units changed (examples: GPWFEST2 ev0978, GPWFEST1 ev0981, YENDONWF ev0984, MRNBESS1 ev0996; see observations).",
     "Units changed (examples: GPWFEST2, GPWFEST1, YENDONWF, MRNBESS1; see observations)."),
    ("Prices rose (excluding Tasmania ev0441).", "Prices rose (excluding Tasmania)."),
    ("Demand was 1105.32 MW (dispatch TOTALDEMAND ev0435).", "Demand was 1105.32 MW (dispatch TOTALDEMAND)."),
    # in a bracket that also holds substance, a colon-less label may be substance too: only its IDs go
    ("Units changed (examples: wind ev0978, solar ev0981).", "Units changed (examples: wind, solar)."),
    ("The error was −319.0 MW (evidence_id: ev0625; error_pct −4.68%, threshold ev0626).",
     "The error was −319.0 MW (percentage error −4.68%, threshold)."),
    ("Interchange (DISPATCH NETINTERCHANGE −82.59 MW ev0438) was negative.",
     "Interchange (DISPATCH NETINTERCHANGE −82.59 MW) was negative."),
])
def test_mixed_brackets_keep_their_substance(before, after):
    assert plain_text(before) == after


@pytest.mark.parametrize("before,after", [
    ("compare those values to ev0538; then", "compare those values to the listed observation; then"),
    ("greater than ev0538, or less than ev0540.", "greater than the listed observation, or less than the listed observation."),
    ("intervals flagged in ev0884 and the interval ending", "intervals flagged in the listed observation and the interval ending"),
])
def test_an_id_used_as_a_noun_keeps_its_wording(before, after):
    assert plain_text(before) == after


@pytest.mark.parametrize("text", [
    "The notice says “threshold ev0878 applies” [c1].",
    "The table says [aemo_so_op_3710#p7c12] that dispatch continued [c2].",
    "AEMO market notice market_notice_144693 (threshold notice) reports it.",
    "PRICE_STATUS is \"NOT FIRM\" [mms_dm_elec21#DISPATCHPRICE#1]; constraint S-DVBL_BC-2CP bound (V-S-MNSP1, V-SA).",
    "Run PUBLIC_FORECAST_OPERATIONAL_DEMAND_HH_202607302330_20260730230149 (threshold run) gave POE50 7942.0 MW.",
])
def test_quotations_citations_and_source_identifiers_are_unchanged(text):
    assert plain_text(text) == text


def test_no_number_is_added_or_removed_except_evidence_ids():
    for before in (F04_SENTENCE, "Demand was 1105.32 MW (dispatch TOTALDEMAND ev0435).",
                   "Six intervals (count ev0876, threshold: ev0878 and ev0879).",
                   "the POE50 = 1508.0 MW run ev0568 and the POE50 = 1510.0 MW run ev0064"):
        ids = {float(x[2:]) for x in re.findall(r"ev\d{4}", before)}
        assert set(narrative_numbers(plain_text(before))) == set(narrative_numbers(before)) - ids


# ------------------------------------------------------------------------------------------------ validation first
@pytest.mark.parametrize("sentence,why", [
    ("There were 14 five-minute intervals at or above the analysis threshold of 350.0 $/MWh in the window "
     "(ev0876; threshold ev0878).", "a threshold the evidence does not hold, beside colon-less references"),
    ("The analysis threshold was 999.0 $/MWh (threshold 999.0 $/MWh ev0878).", "an unsupported number in the bracket"),
])
def test_an_unsupported_number_beside_a_reference_is_still_rejected(sentence, why):
    """Validation reads the answer as written, references included, before any display cleanup: the scripted repair
    repeats the error, so the answer falls back and the sentence is never shown."""
    res = _replay(DEV2 / "F04.json", summary_update=lambda s: [*s, sentence])
    v = res.report.validation
    assert "NUMERIC_UNTRACKED" in set(v.get("pre_repair_codes") or []) or v["fallback_applied"], why
    shown = [res.report.headline, *res.report.summary]
    assert not any(t.startswith(sentence[:40]) or plain_text(sentence)[:40] in t for t in shown), why
