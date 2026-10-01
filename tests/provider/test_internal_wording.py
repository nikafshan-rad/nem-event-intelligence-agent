"""Issue I-4c (docs/issue-tracker.md): the system's own workflow is described in plain words in displayed answers.

Live, second development check (2026-09-30), W19, summary[8]: "… were published in the retrieved set (see published
findings); their published times … are before the price extreme as shown in the notice timings returned to the
controller." Other records show "not present in the returned tool results", "the measure data were not provided by the
tools", and the controller's own "The model judged the question out of scope or ambiguous." and "Observations below
are tool values with source rows."

Now, after validation and outside quotations, these phrases become plain wording with the same meaning. Domain words
("generation output", "SCADA traces", "the forecast model", "frequency controller") and quoted text are unchanged.
Replays use saved Live records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.validation import QUOTED_RE, narrative_numbers
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
DEV2, C0930, V4 = LIVE / "live-check-dev2", LIVE / "live-check-p1-dev", LIVE / "L3-holdout-v4"
W19_LINE = ("Other reserve notices and cancellations for 29/07/2026 were published among the retrieved documents (see "
            "published findings); their published times (local and UTC) are before the price extreme as shown in the "
            "notice timings retrieved in this investigation.")


def plain_text(text: str) -> str:
    from nem_agent.display import plain_text as plain

    return plain(text)


def plain_note(text: str) -> str | None:
    from nem_agent.display import plain_note as note

    return note(text)


def _replay(path: Path, summary_update=None):
    """A saved run's first draft and actual saved repair through the fake transport."""
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


def _shown(rep) -> list[str]:
    return [rep.headline, *rep.summary, *[h.statement for h in rep.possible_explanations],
            *[h.what_would_test_it for h in rep.possible_explanations], *[f.statement for f in rep.published_findings],
            *rep.uncertainties, *rep.missing_evidence]


# ------------------------------------------------------------------------------------------------ the saved example
def test_w19s_displayed_sentence_from_the_live_record():
    rec = json.loads((DEV2 / "W19.json").read_text())
    assert "returned to the controller" in rec["report"]["summary"][8]  # the record is unchanged
    assert plain_text(rec["report"]["summary"][8]) == W19_LINE


def test_w19s_replayed_answer_describes_no_internal_workflow():
    """W19's own first draft and actual repair: the answer passes as before, and nothing internal is shown."""
    res = _replay(DEV2 / "W19.json")
    v, rep = res.report.validation, res.report
    assert v["final_passed"] and not v["fallback_applied"]
    assert W19_LINE in rep.summary
    bare = " ".join(QUOTED_RE.sub(" ", t) for t in _shown(rep))
    assert "controller" not in bare and "retrieved set" not in bare
    assert any("returned to the controller" in r["original"] for r in v["display_rewrites"])  # the original is kept


# ------------------------------------------------------------------------------------------------ the other examples
@pytest.mark.parametrize("before,after", [
    ("Unit offers during 2026-08-19T23:00:00Z–2026-08-19T23:20:00Z are not present in the returned tool results.",
     "Unit offers during 2026-08-19T23:00:00Z–2026-08-19T23:20:00Z are not present in the retrieved data."),
    ("No tool output here shows offer-stack, rebid logs, or constraint binding.",
     "No retrieved data here shows offer-stack, rebid logs, or constraint binding."),
    ("Their times are not available in these tool outputs.", "Their times are not available in these retrieved data."),
    ("No tool result in this report directly attributes causes.", "No retrieved data in this report directly attributes causes."),
    ("The comparison returned no aligned pairs; the tool reported that actuals were not provably public by "
     "2026-07-30T16:00:00Z.", "The comparison returned no aligned pairs; the retrieved data reported that actuals were "
     "not provably public by 2026-07-30T16:00:00Z."),
    ("The requested values were not returned; the measure data were not provided by the tools.",
     "The requested values were not returned; the measure data were not retrieved in this investigation."),
    ("The change was computed by the controller from both rows.", "The change was computed in this investigation from "
     "both rows."),
    ("Tool outputs do not show rebids.", "The retrieved data do not show rebids."),
    ("Refused: The model judged the question out of scope or ambiguous.",
     "Refused: The question was judged out of scope or ambiguous."),
    ("Needs clarification: The routing model returned invalid output.",
     "Needs clarification: The question could not be interpreted."),
])
def test_workflow_wording_becomes_plain(before, after):
    assert plain_text(before) == after


def test_the_controllers_own_notes_are_plain():
    assert plain_note("The model judged the question out of scope or ambiguous.") == \
        "The question was judged out of scope or ambiguous."
    rec = json.loads((V4 / "W17.json").read_text())  # the routing refusal, replayed
    fake = FakeModel(rec["route"], [], lambda kw: {})
    rep = investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False).report
    assert rep.status == "refused" and rep.headline == "Refused: The question was judged out of scope or ambiguous."
    assert not any("model" in t for t in _shown(rep))


def test_the_fallback_headline_names_no_tool():
    """W18's first check (2026-09-30), replayed with its actual saved repair, falls back (I-7); every fallback shows
    this headline."""
    res = _replay(C0930 / "W18.json")
    assert res.report.validation["fallback_applied"]
    assert res.report.headline == ("Validated facts only: the generated narrative failed independent validation. "
                                   "Observations below are retrieved values with source rows.")
    assert any(r["where"] == "headline" and "tool values" in r["original"] for r in res.report.validation["display_rewrites"])


# ------------------------------------------------------------------------------------------------ controls
@pytest.mark.parametrize("text", [
    "Generation output fell; SCADA traces show MURRAY at -277.2 MW; the forecast model gave POE50 7942.0 MW.",
    "The unit's frequency controller and the controller settings are not in the evidence.",
    "The procedure says “the controller returned to the controller state when tool results were provided by the "
    "tools” [c1].",
    "AEMO's MT PASA tool flagged a possible shortfall [c2].",
    "Unit dispatch outputs and constraint binding records were not retrieved.",
    "A planned outage of Directlink was scheduled [market_notice_144695#0] (aemo_so_op_3710#p7c12).",
])
def test_legitimate_wording_quotations_and_identifiers_are_unchanged(text):
    assert plain_text(text) == text


@pytest.mark.parametrize("note,shown", [
    ("get_generation_change: blocked — invalid arguments: range 24.5 h exceeds the 12 h bound",
     "A request to the generation-change data was blocked: the request was invalid, so it was not run."),
    ("Market notices were not searched: market notices are searched only for a stated region and event window; call "
     "again with region, event_start_utc and event_end_utc (one call per region)",
     "Market notices were not searched: market notices are searched only for a stated region and event window."),
    ("Constraint binding records for the interval were not present in the returned tool results.",
     "Constraint binding records for the interval were not present in the retrieved data."),
])
def test_warnings_keep_their_meaning(note, shown):
    assert plain_note(note) == shown


def test_no_number_is_added_or_removed():
    for t in ("Unit offers during 2026-08-19T23:00:00Z are not present in the returned tool results; 406.00544 $/MWh.",
              "The change of 1385.98 MW was computed by the controller.",
              W19_LINE.replace("retrieved in this investigation", "returned to the controller")):
        assert set(narrative_numbers(plain_text(t))) == set(narrative_numbers(t))


# ------------------------------------------------------------------------------------------------ validation first
def test_an_unsupported_number_beside_workflow_wording_is_still_rejected():
    """Validation reads the answer as written before display cleanup: the scripted repair repeats the error, so the
    answer falls back and the sentence is never shown."""
    line = "The notice timings returned to the controller give the price extreme as 999.0 $/MWh."
    res = _replay(DEV2 / "W19.json", summary_update=lambda s: [*s, line])
    v = res.report.validation
    assert "NUMERIC_UNTRACKED" in set(v.get("pre_repair_codes") or [])
    assert not any("999" in t for t in _shown(res.report))
