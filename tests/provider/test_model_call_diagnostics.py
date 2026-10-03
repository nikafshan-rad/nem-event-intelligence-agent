"""Bounded diagnostics of hosted-model calls (preparation for the development model comparison).

- Requested and response-reported model, reasoning effort and output cap are recorded apart; a field the response does
  not carry is "not reported", and an effort the request did not send is "not sent".
- A response that did not finish is described (length, bounded head and tail, whitespace share, repeated runs, the JSON
  field open at the cutoff) and still rejected before parsing, exactly as before. Its cause is "unknown" unless the
  visible text establishes it; token usage alone never does. The open field is "uncertain" unless the text is a valid
  JSON prefix that stops inside a value whose key is known.

All SYNTHETIC: unit inputs, and held-out v5 Y02's saved records through the fake transport (no network, no key), with
one stage answered by script.
"""

from __future__ import annotations

import json
import time

import pytest

from nem_agent.agent import diagnostics as D
from nem_agent.agent.live import LiveController
from nem_agent.agent.request import InvestigateRequest
from nem_agent.evidence import EvidenceRegistry
from nem_agent.service import investigate
from nem_agent.trace import Trace
from tests.provider import fake_model
from tests.provider.test_incomplete_response import CUT, RUNAWAY, Y02, Scripted

pytestmark = pytest.mark.synthetic


# ------------------------------------------------------------------------------------------------ settings
def test_requested_and_reported_settings_are_kept_apart():
    resp = {"model": "gpt-5-mini-2025-08-07", "reasoning": {"effort": "medium", "summary": None}, "max_output_tokens": 2000}
    got = D.settings("gpt-5-mini", {"input": "x"}, 2000, resp)
    assert got["requested"] == {"model": "gpt-5-mini", "max_output_tokens": 2000, "reasoning_effort": D.NOT_SENT}
    assert got["reported"] == {"model": "gpt-5-mini-2025-08-07", "max_output_tokens": 2000, "reasoning_effort": "medium"}


def test_a_field_the_response_does_not_carry_is_not_reported_and_a_sent_effort_is_recorded():
    got = D.settings("m", {"reasoning": {"effort": "low"}}, 8000, {"reasoning": {"summary": "auto"}})
    assert got["requested"]["reasoning_effort"] == "low"
    assert got["reported"] == {"model": D.NOT_REPORTED, "max_output_tokens": D.NOT_REPORTED,
                               "reasoning_effort": D.NOT_REPORTED}
    assert "reported" not in D.settings("m", {}, 8000, None)  # no response (an error): nothing is reported


# ------------------------------------------------------------------------------------------------ cut-off output
def _resp(text: str) -> dict:
    return {**fake_model.msg(text), **CUT}


def test_a_whitespace_runaway_is_described_and_its_repetition_established_by_the_text():
    text = '{"intent": "forecast_review", "region": "NSW1",' + " " * 3000
    d = D.incomplete_output(_resp(text))
    assert d["visible_chars"] == len(text) and d["whitespace_share"] > 0.9
    assert d["longest_char_run"] == {"char": " ", "length": 3000, "start": len(text) - 3000, "ends_at_cutoff": True}
    assert d["cause"] == "repetition at the cutoff" and "repeat one character" in d["cause_evidence"]
    assert d["open_json_field"]["certainty"] == "uncertain" and "between tokens" in d["open_json_field"]["reason"]


def test_mixed_whitespace_up_to_the_cutoff_is_established_by_the_text():
    """Y02's repair broke off into spaces, tabs and newlines: no single character or line repeats, but the text ends in
    whitespace."""
    d = D.incomplete_output(_resp('{"edits": [{"target": "summary[6]",' + RUNAWAY))
    assert d["cause"] == "whitespace at the cutoff" and d["trailing_whitespace_chars"] >= 3000


def test_repeated_lines_up_to_the_cutoff_are_repetition():
    text = '{"clarification": "x' + "\nthe same line again" * 40
    d = D.incomplete_output(_resp(text))
    assert d["longest_line_run"]["count"] == 40 and d["longest_line_run"]["ends_at_cutoff"]
    assert d["cause"] == "repetition at the cutoff"


@pytest.mark.parametrize("text,why", [
    ("", "no visible text was returned"),
    ('{"intent": "forecast_review", "requested": {"maximum": {"window_text": "Between 10 pm on Wednesday', "does not"),
    ("abc" * 100 + " " * 150, "does not"),  # a short run, not half the text
])
def test_otherwise_the_cause_is_unknown(text, why):
    d = D.incomplete_output(_resp(text))
    assert d["cause"] == "unknown" and why in d["cause_evidence"]


def test_token_usage_alone_never_sets_a_cause():
    """A response whose usage shows every output token spent on reasoning, with no visible text: still unknown."""
    resp = {**_resp(""), "usage": {"output_tokens": 2000, "output_tokens_details": {"reasoning_tokens": 2000}}}
    d = D.incomplete_output(resp)
    assert d["cause"] == "unknown" and "token usage alone" in d["cause_evidence"]


def test_excerpts_are_bounded_and_do_not_overlap():
    text = "".join(chr(65 + i % 26) for i in range(70_000))
    t0 = time.monotonic()
    d = D.incomplete_output(_resp(text))
    assert time.monotonic() - t0 < 5
    assert d["head"] == text[:300] and d["tail"] == text[-300:] and len(d["head"]) == len(d["tail"]) == 300
    short = D.incomplete_output(_resp("x" * 450))
    assert short["head"] + short["tail"] == "x" * 450  # no character twice


def test_function_call_arguments_count_as_visible_output():
    resp = {"output": [{"type": "reasoning", "summary": []},
                       {"type": "function_call", "name": "get_price_timeline", "arguments": '{"region": "SA'}], **CUT}
    d = D.incomplete_output(resp)
    assert d["head"] == '{"region": "SA' and d["open_json_field"]["path"] == "region"


@pytest.mark.parametrize("text,path,certainty", [
    ('{"requested": {"maximum": {"window_text": "Between 10 pm', "requested.maximum.window_text", "established"),
    ('{"a": [1, 2, "x', "a[2]", "established"),
    ('{"a": [{"b": "c', "a[0].b", "established"),
    ('{"a": 12', "a", "established"),
    ('{"a": nu', "a", "established"),
    ('{"inte', None, "uncertain"),  # inside a key
    ('{"a": 1, ' + " " * 50, None, "uncertain"),  # between tokens
    ('{"a"   ', "a", "uncertain"),  # after a key, before its colon
    ('{"a": 1}' + " " * 20, None, "uncertain"),  # after the complete value
    ('{"a": 1} trailing', None, "uncertain"),  # not a JSON prefix
    ('{"a" 1', None, "uncertain"),
    ('{"q": "bad \\x escape', None, "uncertain"),
    ("not json at all", None, "uncertain"),
])
def test_the_open_field_is_established_only_inside_a_value_of_a_valid_prefix(text, path, certainty):
    got = D.open_json_field(text)
    assert (got["path"], got["certainty"]) == (path, certainty), got
    assert got["reason"]


# ------------------------------------------------------------------------------------------------ in the controller
def _run(fake):
    res = investigate(InvestigateRequest(question=Y02["question"], mode="live"), live_client=fake, write_trace=False)
    return res, res.trace.as_dict()["events"]


def test_a_cut_off_routing_response_is_described_and_still_not_used():
    res, events = _run(Scripted("RouteDecision", '{"intent": "forecast_review", "region": "SA1",' + RUNAWAY, **CUT))
    names = [e["name"] for e in events]
    assert res.report.status == "needs_clarification" and res.records == []  # rejected before parsing, as before
    assert "route:incomplete" in names and "route:invalid_json" not in names and "model_decision" not in names
    d = next(e for e in events if e["name"] == "route:incomplete_output")
    assert d["cause"] == "whitespace at the cutoff" and d["open_json_field"]["certainty"] == "uncertain"
    assert d["trailing_whitespace_chars"] == len(RUNAWAY)  # all of it, after the last comma
    assert Y02["question"][:40] not in json.dumps(d)  # only the response's own output, never the request
    route = next(e for e in events if e["name"] == "route")
    assert route["requested"] == {"model": "gpt-5-mini", "max_output_tokens": 2000, "reasoning_effort": D.NOT_SENT}
    assert route["reported"] == {"model": D.NOT_REPORTED, "max_output_tokens": D.NOT_REPORTED,
                                 "reasoning_effort": D.NOT_REPORTED}
    assert "not the billed amount" in route["cost_basis"]


def test_the_reported_settings_are_recorded_as_the_response_gives_them():
    fake = Scripted("RouteDecision", json.dumps(Y02["route"]), model="gpt-5-mini-2025-08-07",
                    reasoning={"effort": "medium"}, max_output_tokens=2000)
    _, events = _run(fake)
    route = next(e for e in events if e["name"] == "route")
    assert route["reported"] == {"model": "gpt-5-mini-2025-08-07", "max_output_tokens": 2000, "reasoning_effort": "medium"}
    assert route["requested"]["model"] == "gpt-5-mini"
    assert not any(e["name"].endswith(":incomplete_output") for e in events)  # finished: nothing to describe


def test_every_model_call_records_its_settings_and_a_finished_answer_is_unchanged():
    _, events = _run(Scripted("ModelReport", json.dumps(Y02["drafts"]["synthesis:draft"])))
    calls = [e for e in events if e.get("kind") == "model" and "usage" in e]
    assert calls and all("requested" in e and "reported" in e for e in calls)
    assert {e["name"] for e in calls} >= {"route", "tools", "synthesis"}


def test_a_failed_call_records_the_requested_settings():
    class Failing:
        def create(self, **kw):
            raise RuntimeError("SYNTHETIC transport failure")
    ctl = LiveController(None, EvidenceRegistry(), None, client=Failing(), model="gpt-5-mini")  # type: ignore[arg-type]
    trace = Trace()
    with pytest.raises(RuntimeError):
        ctl.route("SYNTHETIC question", trace)
    err = next(e for e in trace.as_dict()["events"] if e["name"] == "route:error")
    assert err["requested"] == {"model": "gpt-5-mini", "max_output_tokens": 2000, "reasoning_effort": D.NOT_SENT}
    assert "reported" not in err


def test_a_cut_off_tools_turn_is_described():
    class CutTools(Scripted):
        def create(self, **kw):
            out = super().create(**kw)
            if kw.get("tools") and any(i.get("type") == "function_call" for i in out.get("output", [])):
                out.update(CUT)
            return out
    _, events = _run(CutTools("ModelReport", json.dumps(Y02["drafts"]["synthesis:draft"])))
    assert any(e["name"] == "tools:incomplete_output" for e in events)
