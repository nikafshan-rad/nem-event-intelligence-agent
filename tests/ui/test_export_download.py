"""Test that a completed investigation exposes a downloadable JSON report matching the displayed report.

The Streamlit download button serialises ``res.report.model_dump()`` — the same dict used to render
every UI element (headline, observations, charts, validation badge).  It does NOT read from the API's
``_REPORTS`` cache; the report lives in the Streamlit session state for the duration of the browser session.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nem_agent.agent.request import InvestigateRequest
from nem_agent.service import investigate

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def result(real_store):
    return investigate(InvestigateRequest(question="What happened around the SA1 price spike on 2026-07-31?"),
                       write_trace=False)


def test_download_report_json_matches_displayed_report(result):
    """Strict json.dumps (no default=str) round-trips the report the UI displays.

    model_dump() may contain tuples (e.g. source_manifest.documents) which JSON
    deserialises as lists; the round-trip check uses model_dump(mode="json") for
    the baseline so the comparison is type-stable.
    """
    rep = result.report.model_dump()
    report_json = json.dumps(rep, indent=2)
    restored = json.loads(report_json)
    assert restored == result.report.model_dump(mode="json")


def test_streamlit_download_button_appears_after_investigation(real_store):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120).run()
    assert not at.download_button, "no download button before investigation"
    at.button[0].click().run()
    assert not at.exception
    dl = [b for b in at.download_button if b.label == "Download report (JSON)"]
    assert len(dl) == 1
