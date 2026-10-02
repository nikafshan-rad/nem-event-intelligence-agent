"""Issue I-14 (docs/issue-tracker.md): a model response that did not finish is rejected, even when its text parses.

Held-out v5 Y02 (Live, 2026-10-02): the first draft put the retrieval tool's status text in quotation marks ("no notice
held for this region and window"), which is in no cited passage, so validation rejected it (QUOTE_NOT_IN_SOURCE; no
code change: quotation marks certify document text). The one scoped repair then ran to max_output_tokens: 16,000
output tokens, 384 of them reasoning, the rest a JSON patch breaking off into whitespace. The controller never checked
the response's status: Y02's text failed to parse, so the answer fell back, but a repair cut off after its closing brace
was applied as if finished.

Now a structured response whose status is not 'completed' (or that carries incomplete details) is rejected without
being parsed, on the existing fail-closed path. No retry, budget or validation change. Replays use Y02's saved records
through the SYNTHETIC fake transport (no network, no key), with the repair (or another stage) answered by script.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nem_agent import config
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from tests.provider import fake_model
from tests.provider.fake_model import FakeModel

pytestmark = pytest.mark.synthetic

LIVE = Path(__file__).resolve().parents[2] / "artifacts" / "live"
Y02 = json.loads((LIVE / "L3-holdout-v5" / "Y02.json").read_text())
CALLS = [(t["name"], json.loads(t["args"]) if isinstance(t["args"], str) else t["args"]) for t in Y02["tools"]
         if not str(t["call_id"]).startswith("controller_")]
DRAFT = Y02["drafts"]["synthesis:draft"]
QUOTED = '"no notice held for this region and window"'
RESTATED = DRAFT["summary"][6].replace(QUOTED, "no notice held for this region and window")
FALLBACK = "Validated facts only: the generated narrative failed independent validation."
CUT = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
RUNAWAY = "    \n   \t     \n   \t" * 200  # what Y02's repair broke off into


def _patch(text: str) -> dict:
    return {"edits": [{"target": "summary[6]", "action": "replace", "text": text, "statement": None, "claim": None,
                       "citation": None}], "new_numeric_claims": [], "new_citations": []}


class Scripted(FakeModel):
    """Answers the calls of one response format (RouteDecision, ModelReport or RepairPatch) with a scripted text and
    status; everything else as FakeModel does with Y02's saved route, tool calls and draft."""

    def __init__(self, fmt: str, text: str, **resp: object) -> None:
        super().__init__(Y02["route"], [CALLS], lambda kw: copy.deepcopy(DRAFT))
        self.fmt, self.text, self.resp, self.scripted = fmt, text, resp, []

    def create(self, **kw):
        if (kw.get("text") or {}).get("format", {}).get("name") == self.fmt:
            self.requests.append(copy.deepcopy(kw))
            self.scripted.append(kw)
            out = fake_model.msg(self.text)
            out.update(self.resp)
            return out
        return super().create(**kw)


def _run(fake: Scripted):
    res = investigate(InvestigateRequest(question=Y02["question"], mode="live"), live_client=fake, write_trace=False)
    return res, [e["name"] for e in res.trace.as_dict()["events"]]


def _repair(text: str, **resp: object):
    fake = Scripted("RepairPatch", text, **resp)
    res, names = _run(fake)
    assert len(fake.scripted) == 1  # one bounded repair call, never retried
    return res, names, fake


# ------------------------------------------------------------------------------------------------ Y02
def test_y02s_first_draft_fails_only_on_the_quoted_tool_text():
    res, _, _ = _repair(json.dumps(_patch(RESTATED)))
    first = [v for v in res.report.validation["pre_repair"]["violations"] if v["severity"] == "critical"]
    assert [v["code"] for v in first] == ["QUOTE_NOT_IN_SOURCE"] and "summary[6]" in first[0]["detail"]


def test_y02s_cut_off_repair_is_rejected_as_cut_off():
    """As in Live: status incomplete (max_output_tokens), a patch breaking off into whitespace. It is not parsed; the
    answer falls back, and the trace names the reason."""
    res, names, _ = _repair('{\n  "edits": [\n    {\n      "target": "summary[6]",\n' + RUNAWAY, **CUT)
    rep = res.report
    assert rep.validation["fallback_applied"] and rep.headline.startswith(FALLBACK)
    cut = next(e for e in res.trace.as_dict()["events"] if e["name"] == "repair:incomplete")
    assert cut["incomplete"] == {"reason": "max_output_tokens"} and cut["status"] == "incomplete"
    assert "repair:invalid_json" not in names and "repair:scoped" not in names


# ------------------------------------------------------------------------------------------------ the repair, three ways
def test_a_successful_bounded_repair_is_applied():
    """A completed scoped patch, within the unchanged cap, that restates the line without quotation marks."""
    res, names, fake = _repair(json.dumps(_patch(RESTATED)))
    rep = res.report
    assert fake.scripted[0]["max_output_tokens"] == config.MAX_OUTPUT_TOKENS["repair"] == 16_000
    assert rep.validation["final_passed"] and not rep.validation["fallback_applied"]
    assert "repair:scoped" in names and "repair:incomplete" not in names
    assert not any(QUOTED in s or "“no notice held" in s for s in rep.summary)
    assert any("450.08" in s for s in rep.summary)  # the draft's answer is shown


@pytest.mark.parametrize("resp", [CUT, {"status": "failed", "incomplete_details": None},
                                  {"status": "completed", "incomplete_details": {"reason": "content_filter"}}])
def test_a_repair_that_did_not_finish_is_rejected_even_when_it_parses(resp):
    """The same valid patch, but cut off after its closing brace (or failed): rejected, so the answer falls back. On
    main, the cut-off one was applied and the answer passed."""
    res, names, _ = _repair(json.dumps(_patch(RESTATED)) + RUNAWAY, **resp)
    assert res.report.validation["fallback_applied"] and res.report.headline.startswith(FALLBACK)
    assert "repair:incomplete" in names and "repair:scoped" not in names


def test_a_repair_that_keeps_the_unsupported_quote_falls_back():
    """Completed, but the line still quotes the tool's text: re-validation fails, and the answer falls back."""
    kept = DRAFT["summary"][6].replace("A public-document search", "The document search")
    assert QUOTED in kept
    res, names, _ = _repair(json.dumps(_patch(kept)))
    rep = res.report
    assert "repair:scoped" in names
    assert rep.validation["fallback_applied"] and rep.headline.startswith(FALLBACK)
    assert "QUOTE_NOT_IN_SOURCE" in {v["code"] for v in rep.validation["initial"]["violations"]}


# ------------------------------------------------------------------------------------------------ other stages
def test_a_cut_off_routing_response_is_not_used():
    """A complete routing decision, but the response was cut off: treated as invalid routing output; no tool runs."""
    res, names = _run(Scripted("RouteDecision", json.dumps(Y02["route"]) + RUNAWAY, **CUT))
    assert res.report.status == "needs_clarification" and "could not be interpreted" in res.report.headline
    assert res.records == [] and "route:incomplete" in names


def test_a_cut_off_synthesis_gives_no_model_narrative():
    """Y02's whole draft, but the response was cut off: no model report is used, and the answer abstains."""
    res, names = _run(Scripted("ModelReport", json.dumps(DRAFT) + RUNAWAY, **CUT))
    rep = res.report
    assert "synthesis:incomplete" in names and "synthesis:draft" not in names
    assert not any(line in rep.summary for line in DRAFT["summary"])
    assert rep.status == "abstained" and rep.headline == "Abstained: the live model did not produce a valid report."
