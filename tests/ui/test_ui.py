"""G7: chart data/specs and the Streamlit page (headless AppTest) on real data."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate
from nem_agent.timeutil import parse_iso
from nem_agent.ui_data import LABEL_ACTUAL, LABEL_FORECAST, demand_chart, frames, price_chart

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def result(real_store):
    return investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?"),
                       write_trace=False)


def test_frames_keep_native_resolution(result):
    pdf, ddf = frames(result.records, "SA1")
    t = sorted(parse_iso(x) for x in pdf["utc"])
    assert all(b - a == timedelta(minutes=5) for a, b in zip(t, t[1:], strict=False))
    act = sorted(parse_iso(x) for x in ddf[ddf.series == LABEL_ACTUAL]["utc"])
    assert all(b - a == timedelta(minutes=30) for a, b in zip(act, act[1:], strict=False))
    assert set(ddf.series) == {LABEL_ACTUAL, LABEL_FORECAST}
    # local wall time for SA1 in July is UTC+09:30
    first = pdf.iloc[0]
    assert parse_iso(first["t"]) - parse_iso(first["utc"]) == timedelta(hours=9, minutes=30)


def test_chart_specs_single_axis_step_lines_and_tooltips(result):
    pdf, ddf = frames(result.records, "SA1")
    p = price_chart(pdf, "SA1", "Australia/Adelaide", "light", result.report.observations[0].valid_at_utc).to_dict()
    d = demand_chart(ddf, "SA1", "Australia/Adelaide", "dark").to_dict()
    for spec in (p, d):
        marks = [layer["mark"] for layer in spec["layer"]]
        lines = [m for m in marks if isinstance(m, dict) and m.get("type") == "line"]
        assert lines and all(m["interpolate"] == "step-before" and m["strokeWidth"] == 2 for m in lines)
        assert "resolve" not in spec  # no independent (dual) y-axes
        assert any("tooltip" in layer.get("encoding", {}) for layer in spec["layer"])
    assert d["layer"][0]["encoding"]["color"]["scale"]["range"] == ["#3987e5", "#d95926"]


def test_streamlit_page_runs_and_investigates(real_store):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception
    assert any("REPLAY" in m.value for m in at.markdown)
    at.button[0].click().run()
    assert not at.exception
    assert any(m.label == "Status" and "answered" in m.value for m in at.metric)
    assert any("4,981.00/MWh" in s.value for s in at.subheader)


def test_result_label_comes_from_the_report_not_the_selector(result):
    """L0 finding: the badge followed the mode radio, so a replay report could sit under a LIVE label."""
    from nem_agent.ui_data import result_provenance

    rep = result.report.model_dump()
    assert result_provenance(rep)["kind"] == "replay" and "no LLM" in result_provenance(rep)["label"]
    live = rep | {"mode": "live", "generator": "live-model:gpt-5-mini",
                  "versions": rep["versions"] | {"model": "gpt-5-mini", "prompt": "prompts/v5"}}
    usage = {"model_calls": 5, "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01, "cost_note": "estimate"}
    ok = result_provenance(live | {"validation": {"repair_attempted": True, "fallback_applied": False}}, usage)
    assert ok["kind"] == "live_answer" and ok["validation"] == "passed after one repair" and ok["model_calls"] == 5
    first = result_provenance(live | {"validation": {"repair_attempted": False, "fallback_applied": False}}, usage)
    assert first["validation"] == "passed on the first draft"
    fb = result_provenance(live | {"validation": {"repair_attempted": True, "fallback_applied": True}}, usage)
    assert fb["kind"] == "live_fallback" and "facts only" in fb["label"] and "fallback" in fb["validation"]
    routed = result_provenance(live | {"generator": "live-responses-controller/1", "status": "refused"}, usage)
    assert routed["kind"] == "live_no_answer" and routed["validation"] == "no generated answer"


def test_a_replay_result_is_never_shown_under_the_live_selector(real_store, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-not-a-key")  # enables the selector; no live call is made
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120).run()
    at.button[0].click().run()  # replay is the default mode
    assert any("Result shown: REPLAY" in m.value for m in at.info)
    at.sidebar.radio[0].set_value("live").run()  # switch the selector without running again
    assert not at.exception
    assert any("Result shown: REPLAY" in m.value for m in at.info)
    assert not any("Result shown: LIVE" in m.value for m in [*at.info, *at.success, *at.warning])
    assert any("produced in REPLAY mode" in m.value for m in at.warning)


def test_demand_legend_lists_only_series_that_are_drawn(result):
    """L4 live screenshot: the legend showed 'AEMO POE50 forecast' although the live run fetched no forecasts."""
    _, ddf = frames(result.records, "SA1")
    actual_only = ddf[ddf["series"] == LABEL_ACTUAL]
    d = demand_chart(actual_only, "SA1", "Australia/Adelaide", "light").to_dict()
    scale = d["layer"][0]["encoding"]["color"]["scale"]
    assert scale["domain"] == [LABEL_ACTUAL] and scale["range"] == ["#2a78d6"]  # same colour as when both are drawn
    assert "no forecast runs were retrieved" in d["title"]["text"]
