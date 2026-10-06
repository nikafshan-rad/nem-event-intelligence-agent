"""D38: generation changes labelled with their unit, period and measurement basis, and one reporting instruction added
to every Live synthesis. SYNTHETIC fake model and scratch ledgers only (conftest).

What code does, and what stays the model's judgement:

- code: each SCADA change carries a label naming the unit, the two readings' intervals (local time) and what the number
  is (the end reading minus the start reading; not when the change occurred or what caused it), shown with the
  observation; the tool's caveat, which the model reads, says the same and that the range of readings has no times;
- the model: whether each part of the question is answered by an observation with its period, or said not to be
  answered (``prompts/additions/requested_areas_v1.md``, added after the synthesis prompt), and keeping observations
  out of explanations. No structured request field names the areas a question asks about, so code does not check
  this. The versioned prompt files keep their bytes, but the effective synthesis and repair instructions change: the
  base version and the addition are recorded on each synthesis and repair call and in each report.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nem_agent import config
from nem_agent.agent.live import prompt, synthesis_instructions, synthesis_prompt
from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.timeutil import iso_utc, local_str, parse_iso
from tests.provider.fake_model import FakeModel, outputs
from tests.provider.test_live_loop import _good_report, _required_turn, _route, _w

pytestmark = pytest.mark.synthetic
ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "src" / "nem_agent" / "prompts"
QUESTION = "What happened around the SA1 price spike on 2026-07-31? How did price, operational demand and generation move?"
SECTION = """What the question asks
- Address each part of the question (for example, each quantity whose movement it asks about) with a factual
  observation from a tool result, in the summary (in `document_statements` for a document answer), giving the
  period or interval it covers; when a tool covered only part of the window, give the part it covered. If no tool
  result answers a part, say in `missing_evidence` that this part was not answered.
- Keep observations and hypotheses apart: state an observation in the summary, not only inside
  `possible_explanations`; an explanation may refer to an observation the summary states.
"""


@pytest.fixture
def ev(selection):
    return selection.primary


def _generation_turn(ev: Any) -> list[tuple[str, dict[str, Any]]]:
    peak = parse_iso(ev.peak_interval_end_utc)
    start = max(parse_iso(ev.window_start_utc), peak - timedelta(hours=6))
    return [("get_generation_change", {**_w(ev), "start_utc": iso_utc(start), "end_utc": iso_utc(peak + timedelta(hours=1)),
                                       "top_n": 3, "as_of_utc": None})]


def _generation(kw: dict[str, Any]) -> dict[str, Any]:
    return next(v["result"] for v in outputs(kw).values() if v["status"] == "ok" and "largest_changes" in v["result"])


def _with_generation(kw: dict[str, Any]) -> dict[str, Any]:
    """The draft lists two SCADA changes among its observations."""
    r = _good_report(kw)
    r["observation_evidence_ids"] = [*r["observation_evidence_ids"],
                                     *(u["change_mw"]["evidence_id"] for u in _generation(kw)["largest_changes"][:2])]
    return r


def _run(fake: FakeModel) -> Any:
    return investigate(InvestigateRequest(question=QUESTION, mode="live"), live_client=fake, write_trace=False)


def _label(unit: dict[str, Any], region: str) -> str:
    first, last = (local_str(parse_iso(unit[k]["interval_end_utc"]), region) for k in ("start", "end"))
    name = unit["duid"] if unit["station"] in (None, unit["duid"]) else f"{unit['duid']} ({unit['station']})"
    return (f"{name} SCADA MW change between the readings for the intervals ending {first} and {last}: the end "
            "reading minus the start reading; it does not show when the change occurred or what caused it")


# -- the reporting instruction (an addition after the synthesis prompt) -------------------------------------------------
def test_the_instruction_follows_each_versions_synthesis_prompt_which_stays_unchanged():
    """The versioned prompts stay as released and frozen (v16 by default, v17 under the opt-in request plan): the
    instruction is one file the controller adds after either."""
    assert config.PROMPT_VERSION == "prompts/v16"
    assert (PROMPTS / "additions" / "requested_areas_v1.md").read_text() == SECTION
    for version in ("prompts/v16", "prompts/v17"):
        assert synthesis_prompt(version) == f"{prompt('synthesis', version)}\n\n{SECTION}"
        assert synthesis_instructions(version) == {
            "prompt_version": version, "base": f"{version}/synthesis.md",
            "additions": ["prompts/additions/requested_areas_v1.md"], "stages": ["synthesis", "repair"]}


def test_every_live_synthesis_reads_the_instruction_and_the_report_records_it(ev):
    fake = FakeModel(_route(ev), [_required_turn(ev)], _good_report)
    res = _run(fake)
    synthesis = next(kw for kw in fake.requests if ((kw.get("text") or {}).get("format") or {}).get("name") == "ModelReport")
    assert synthesis["input"][-1]["content"] == f"{prompt('synthesis', 'prompts/v16')}\n\n{SECTION}"
    # the base version is kept and the addition is recorded: in the report and on the synthesis call, and on no other
    assert res.report.versions.prompt == "prompts/v16"
    assert res.report.source_manifest["synthesis_instructions"] == synthesis_instructions("prompts/v16")
    calls = [e for e in res.trace.events if e["kind"] == "model" and e.get("response_id")]
    assert [e["name"] for e in calls] == ["route", "tools", "tools", "synthesis"]
    assert [e.get("synthesis_instructions") for e in calls] == [None, None, None, synthesis_instructions("prompts/v16")]


# -- generation changes: label and measurement basis -------------------------------------------------------------------
def test_a_generation_change_observation_names_its_unit_period_and_basis(ev):
    fake = FakeModel(_route(ev), [_required_turn(ev), _generation_turn(ev)], _with_generation)
    res = _run(fake)
    assert res.report.validation["final_passed"] is True
    gen = _generation(fake.requests[-1])
    shown = {o.evidence_id: o for o in res.report.observations if o.metric == "scada_change_mw"}
    assert len(shown) == 2
    for unit in gen["largest_changes"][:2]:
        o = shown[unit["change_mw"]["evidence_id"]]
        assert o.label == _label(unit, ev.region)
        assert o.value == round(unit["end"]["mw"] - unit["start"]["mw"], 2) == unit["change_mw"]["value"]
        assert o.valid_at_utc == unit["end"]["interval_end_utc"]  # the end reading's interval, as before
        assert len(o.label) < 300  # shown whole (labels are cut at 300 characters)
    # the readings themselves keep their labels
    reading = res.registry.get(gen["largest_changes"][0]["start"]["evidence_id"])
    assert reading.label == f"{gen['largest_changes'][0]['duid']} SCADA MW (reading at start of interval)"


def test_the_tool_tells_the_model_what_a_change_is_and_is_not(ev):
    fake = FakeModel(_route(ev), [_required_turn(ev), _generation_turn(ev)], _good_report)
    _run(fake)
    gen = _generation(fake.requests[-1])
    assert gen["caveat"] == (
        "Descriptive SCADA observations only. A change in output does not by itself show an outage, a bidding decision "
        "or a cause of the price; SCADAVALUE is an instantaneous reading at interval start. Each change_mw is the end "
        "reading minus the start reading for the period: it does not show when within the period the output changed, "
        "or what caused it. min_mw_in_window and max_mw_in_window are the range of readings in the period, without "
        "their times.")
    assert "label" not in json.dumps(gen)  # the label is shown with the observation; the model's input is the caveat


# -- a scoped repair cannot silently remove an established observation -------------------------------------------------
def test_a_scoped_repair_keeps_an_observation_it_was_not_asked_to_change(ev):
    """The draft's summary line has an untracked number: only that line may change. The patch also tries to delete a
    generation change from the observations; the edit is ignored and recorded, and the observation stays, labelled. A
    rewritten summary line can drop the values it stated (as in the 2026-10-06 trial, T2-1): the observation remains."""
    state: dict[str, str] = {}

    def draft(kw: dict[str, Any]) -> dict[str, Any]:
        r = _with_generation(kw)
        state["gen"] = r["observation_evidence_ids"][-1]
        r["summary"] = ["The fake model only restates tool values.",
                        "Generation output shifted by 12,345 MW across the largest units."]
        return r

    def patch(kw: dict[str, Any]) -> dict[str, Any]:
        none = {"statement": None, "claim": None, "citation": None}
        return {"edits": [{"target": "summary[1]", "action": "replace",
                           "text": "Generation output shifted across the largest units.", **none},
                          {"target": f"observation_evidence_ids[{state['gen']}]", "action": "delete", "text": None,
                           **none}],
                "new_numeric_claims": [], "new_citations": []}

    fake = FakeModel(_route(ev), [_required_turn(ev), _generation_turn(ev)], draft, patch)
    res = _run(fake)
    v = res.report.validation
    assert v["repair_attempted"] is True and v["repair_mode"] == "scoped" and v["final_passed"] is True
    scoped = next(e for e in res.trace.events if e["name"] == "repair:scoped")
    assert scoped["targets"] == ["summary[1]"]
    assert f"ignored an edit to observation_evidence_ids[{state['gen']}]: only the failing items may change" in scoped["notes"]
    assert res.report.summary[1] == "Generation output shifted across the largest units."
    # the repair continues the synthesis conversation, so it has the same instructions, and its call records them
    sent = [i.get("content") for i in fake.requests[-1]["input"] if isinstance(i, dict)]
    assert f"{prompt('synthesis', 'prompts/v16')}\n\n{SECTION}" in sent
    repair = [e for e in res.trace.events if e["kind"] == "model" and e["name"] == "repair" and e.get("response_id")]
    assert [e["synthesis_instructions"] for e in repair] == [synthesis_instructions("prompts/v16")]
    kept = {o.evidence_id: o for o in res.report.observations}
    assert state["gen"] in kept and "SCADA MW change between the readings" in kept[state["gen"]].label
