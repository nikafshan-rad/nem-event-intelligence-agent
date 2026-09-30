"""Issue I-3a (docs/issue-tracker.md): a quoted notice time is shown with its source-backed zone.

Live check 2026-09-29, F03: both summary lines and both published findings quoted notice 144693's "1630 hrs 30/07/2026"
with no zone. The notice writes none. retrieve_public_evidence had returned the passage's clock_times: NEM market time
(UTC+10; docs/decisions.md D18) = 2026-07-30T06:30:00Z = 16:00 ACST. A document answer has no free text, so only the
controller could show it.

Now, where the controller renders a verbatim market-notice quote (a document statement or a published finding), a
note after the quote gives the basis, and each time's UTC and local equivalents when every time in the quote carries
its date. The quote is never changed, and no zone or date is guessed. Clock times below come from the tool's own
notice_clock_times. Replays use saved Live records through the SYNTHETIC fake transport (no network, no key).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nem_agent.agent.live import LiveController
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.service import investigate
from nem_agent.tools.impl import notice_clock_times
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
F03_1 = "At 1630 hrs 30/07/2026 there was a short notice outage of Belalie-Davenport 275kV line."
F03_2 = "The following constraint set(s) invoked at 1630 hrs 30/07/2026 S-DVBL_BC-2CP"
F03_NOTE = "(NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30 16:00 ACST.)"


def _note(quote: str, notice_text: str | None = None, event_date: str = "2026-07-30", region: str = "SA1"):
    from nem_agent.agent.live import notice_time_note

    return notice_time_note(quote, notice_clock_times(notice_text or quote, event_date, region))


# ------------------------------------------------------------------------------------------------ the note
def test_f03s_time_gets_its_basis_and_utc_and_local_equivalents():
    assert _note(F03_1) == F03_NOTE


@pytest.mark.parametrize("quote,region,event_date,note", [
    # two times, in order (F04's Directlink notice, NSW1)
    ("A planned outage of Directlink all 3 cables in the NSW region was scheduled from 0700 hrs 27/07/2026 to "
     "1700 hrs 31/07/2026.", "NSW1", "2026-07-31",
     "(NEM market time, UTC+10: 2026-07-26T21:00:00Z = 2026-07-27 07:00 AEST; 2026-07-31T07:00:00Z = 2026-07-31 17:00 AEST.)"),
    # daylight saving: NEM time stays UTC+10, the local zone becomes AEDT (test fixture notice)
    ("At 1630 hrs 15/01/2026 there was a short notice outage of a 220 kV line.", "VIC1", "2026-01-15",
     "(NEM market time, UTC+10: 2026-01-15T06:30:00Z = 2026-01-15 17:30 AEDT.)"),
])
def test_utc_and_local_conversions_are_the_tools(quote, region, event_date, note):
    assert _note(quote, event_date=event_date, region=region) == note


@pytest.mark.parametrize("quote,notice_text,expected,why", [
    ("Outage Duration: 10:30 am - 2:30 pm AEST", None, None, "the notice writes its own zone"),
    ("At 1630 hrs AEST on the day there was an outage.", None, None, "a notice time already zoned"),
    ("There was a short notice outage of Belalie-Davenport 275kV line.", None, None, "no clock time"),
    ("At 1630 hrs there was a short notice outage.", None, "(Notice times are NEM market time, UTC+10.)",
     "the date is not in the phrase: the basis only"),
    ("At 1630 hrs", F03_1, "(Notice times are NEM market time, UTC+10.)", "the quote stops before the notice's date"),
])
def test_explicit_ambiguous_or_missing_zone_information(quote, notice_text, expected, why):
    assert _note(quote, notice_text) == expected, why


def test_a_time_without_a_clock_times_entry_gets_no_note():
    from nem_agent.agent.live import notice_time_note

    assert notice_time_note(F03_1, []) is None


def test_only_market_notice_quotes_get_a_note():
    ctl = LiveController(None, EvidenceRegistry(), None, client=FakeModel({}, [], None))  # type: ignore[arg-type]
    view = {"results": [{"chunk_id": "x#0", "clock_times": notice_clock_times(F03_1, "2026-07-30", "SA1")}]}
    ctl.d = SimpleNamespace(records=[SimpleNamespace(name="retrieve_public_evidence", status="ok", view=view)])
    assert ctl._quote_time_note(F03_1, "x#0", "market_notice") == " " + F03_NOTE
    assert ctl._quote_time_note(F03_1, "x#0", "definition") == ""
    assert ctl._quote_time_note(F03_1, "y#0", "market_notice") == ""  # no clock_times returned for that passage


# ------------------------------------------------------------------------------------------------ saved Live runs
def _replay(path: Path, *, first_draft: bool = False, delete: str | None = None):
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
    fake = FakeModel(rec["route"], [calls], lambda kw: copy.deepcopy(draft),
                     (lambda kw: copy.deepcopy(patch)) if patch else None)
    return investigate(InvestigateRequest(question=rec["question"], mode="live"), live_client=fake, write_trace=False)


def test_f03_shows_each_quoted_notice_time_with_its_zone_and_the_quotes_unchanged():
    res = _replay(LIVE / "live-check-2026-09-29" / "F03.json")
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v
    assert res.report.summary == [f"“{F03_1}” [c1] {F03_NOTE}", f"“{F03_2}” [c2] {F03_NOTE}"]
    assert [f.statement for f in res.report.published_findings] == [
        f"An AEMO market notice for SA1 [c1] says: “{F03_1}” {F03_NOTE}",
        f"An AEMO market notice for SA1 [c2] says: “{F03_2}” {F03_NOTE}"]


@pytest.mark.parametrize("path,kw", [
    (LIVE / "live-check-p1-dev" / "F04.json", {"first_draft": True}),
    (LIVE / "live-check-2026-09-29" / "F04.json", {}),
    (LIVE / "live-check-p1-dev" / "W18.json", {"first_draft": True, "delete": "possible_explanations[1]"}),
    (LIVE / "live-check-p1-dev" / "W19.json", {"first_draft": True}),
])
def test_other_live_answers_pass_as_before_with_their_notice_quotes_zoned(path, kw):
    res = _replay(path, **kw)
    v = res.report.validation
    assert v["final_passed"] and not v["fallback_applied"], v
    findings = [f.statement for f in res.report.published_findings if " hrs " in f.statement]
    assert findings and all("NEM market time, UTC+10" in f for f in findings)
