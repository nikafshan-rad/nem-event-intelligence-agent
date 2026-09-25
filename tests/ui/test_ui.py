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
