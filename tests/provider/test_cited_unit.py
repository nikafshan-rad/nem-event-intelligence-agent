"""Issue I-3b (docs/issue-tracker.md): a quoted table row is shown with the unit its table header states.

Live check 2026-09-29, F01: the answer quoted the row “New South Wales 150” from Table 5 of SO_OP_3710. In the cited
passage the unit is stated once, in the column header "Forecast Error Threshold (MW)". A verbatim quote cannot carry
it, and a paraphrase "150 MW" is an untracked number in a document answer.

Now, after a verbatim quote of one table row (a label, then one bare number), the controller notes the unit when the
cited passage places the row after a "Table N" caption whose header declares exactly one unit. The quote is never
changed, and no unit is inferred from the number or from another passage. Passages other than F01's are test fixtures.
Replays use saved Live records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from nem_agent.agent.live import LiveController
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import ChunkItem, EvidenceRegistry
from nem_agent.service import investigate
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "artifacts" / "live"
F01_CHUNK = "aemo_so_op_3710#p7c12"
F01_ROW = "New South Wales 150"
MW_NOTE = "(in MW, as the table header in the cited passage states)"


def _f01_passage() -> str:
    con = sqlite3.connect(REPO / "data" / "index" / "corpus.sqlite")
    return con.execute("SELECT text FROM chunks WHERE chunk_id = ?", [F01_CHUNK]).fetchone()[0]


def _note(quote: str, passage: str):
    from nem_agent.agent.live import table_unit_note

    return table_unit_note(quote, passage)


# ------------------------------------------------------------------------------------------------ the note
def test_f01s_row_takes_the_unit_its_table_header_states():
    assert _note(F01_ROW, _f01_passage()) == MW_NOTE


def test_another_unit_from_a_table_header():
    passage = "Table 2 Price caps Region Cap ($/MWh) Queensland 18600 New South Wales 18600 Victoria 18600"
    assert _note("New South Wales 18600", passage) == "(in $/MWh, as the table header in the cited passage states)"


@pytest.mark.parametrize("quote,passage,why", [
    ("New South Wales 150 MW", "Table 1 Limits Region Limit Queensland 100 MW New South Wales 150 MW",
     "the quote already states its unit"),
    ("New South Wales 150", "Table 3 Thresholds Region Threshold Queensland 100 New South Wales 150",
     "the header states no unit"),
    ("New South Wales 150", "Table 4 Limits Region Limit (MW) Price ($/MWh) Queensland 100 New South Wales 150",
     "the header states two units: which one is ambiguous"),
    ("New South Wales 150 250", "Table 6 Limits Region Summer (MW) Queensland 100 200 New South Wales 150 250",
     "a row with two numbers"),
    ("New South Wales 150", "The limit (MW) differs by region: Queensland 100 New South Wales 150",
     "no table caption before the row"),
    ("New South Wales 150", "Table 7 Limits Region Limit (MW) Queensland 100 Table 8 Counts Region Count "
                            "Queensland 3 New South Wales 150",
     "the nearest table's header states no unit; an earlier table's is not borrowed"),
])
def test_missing_ambiguous_or_already_stated_units_get_no_note(quote, passage, why):
    assert _note(quote, passage) is None, why


def test_a_sentence_after_the_table_gets_no_note():
    sentence = ("The load forecast for a region will be reviewed, whenever the forecast error is greater than the "
                "forecast error threshold in a region for two consecutive 30-minute periods.")
    assert _note(sentence, _f01_passage()) is None


def test_only_the_cited_passage_is_read_not_a_neighbour():
    reg = EvidenceRegistry()
    for cid, text in (("fixture#p1c1", "Table 9 Thresholds Region Threshold Queensland 100 New South Wales 150"),
                      ("fixture#p1c2", "Table 9 (continued) Region Threshold (MW) Victoria 100")):
        reg.add_chunk(ChunkItem(chunk_id=cid, doc_id="fixture", title="test fixture", url="https://example.invalid/",
                                text=text, section=None, page=1, publication_date="2026-01-01T00:00:00Z",
                                doc_type="procedure", event_region=None, event_date=None, eligible=True,
                                eligibility_reason="test fixture", tool_call_id="call-t"))
    ctl = LiveController(None, reg, None, client=FakeModel({}, [], None))  # type: ignore[arg-type]
    ctl.d = SimpleNamespace(records=[])
    assert ctl._quote_unit_note(F01_ROW, "fixture#p1c1") == ""  # its neighbour's "(MW)" is not used
    assert ctl._quote_unit_note("Victoria 100", "fixture#p1c2") == " " + MW_NOTE  # a row in the neighbour itself


# ------------------------------------------------------------------------------------------------ saved Live runs
def _replay(name: str):
    rec = json.loads((LIVE / "live-check-2026-09-29" / f"{name}.json").read_text())
    calls = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in rec["tools"]
             if not str(t["call_id"]).startswith("controller_") and t["status"] != "blocked"]
    draft = rec["drafts"].get("repair:draft") or rec["drafts"]["synthesis:draft"]
    return investigate(InvestigateRequest(question=rec["question"], mode="live"),
                       live_client=FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft)), write_trace=False)


def test_f01_shows_the_row_with_its_unit_and_its_other_statements_unchanged():
    res = _replay("F01")
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v
    label = res.report.validation.get("citation_labels", {}).get(F01_CHUNK, F01_CHUNK)  # I-3g: shown as [c1]
    assert res.report.summary[1] == f"“{F01_ROW}” [{label}] {MW_NOTE}"
    assert next(c.chunk_id for c in res.report.citations if c.citation_id == label) == F01_CHUNK
    labels = res.report.validation.get("citation_labels", {})  # I-3g: raw passage IDs are shown as [cN]
    assert res.report.summary[0].endswith(f"[{labels.get(F01_CHUNK, F01_CHUNK)}]")
    assert res.report.summary[2].endswith(f"[{labels.get('aemo_so_op_3704#p9c25', 'aemo_so_op_3704#p9c25')}]")


def test_f03s_time_zone_notes_are_intact():
    res = _replay("F03")
    assert res.report.validation["final_passed"] and not res.report.validation["fallback_applied"]
    note = "(NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30 16:00 ACST.)"
    assert all(s.endswith(note) for s in res.report.summary) and len(res.report.summary) == 2
