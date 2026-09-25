"""Security properties: no write/exec tools for the model, secret redaction, injection is data, bounded outputs."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from nem_agent.tools import TOOLS, openai_function_tools
from nem_agent.trace import Trace, redact


def test_model_tool_surface_is_read_only_and_closed():
    names = set(TOOLS)
    assert names == {"find_market_events", "get_price_timeline", "get_forecast_runs", "get_actual_demand",
                     "compare_forecast_actual", "get_generation_change", "get_weather_context", "retrieve_public_evidence"}
    blob = json.dumps(openai_function_tools())
    for forbidden in ("sql", "shell", "exec", "url", "path", "publish_case_note", "write"):
        assert f'"{forbidden}"' not in blob.lower()


def test_trace_redacts_secrets(monkeypatch):
    fake = "-".join(["sk", "proj", "THISISNOTAREALKEY" + "1234567890"])  # assembled at runtime: not a literal key
    monkeypatch.setenv("OPENAI_API_KEY", fake)
    t = Trace()
    t.add("model", "x", headers={"Authorization": f"Bearer {fake}"}, note=f"key={fake}",
          api_key="-".join(["sk", "abc12345678"]))
    dumped = json.dumps(t.as_dict())
    assert "THISISNOTAREALKEY" not in dumped and "abc12345678" not in dumped
    assert redact("plain text 4981 MW") == "plain text 4981 MW"


def test_live_smoke_without_key_is_unverified_and_prints_no_secret():
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    p = subprocess.run([sys.executable, "-m", "nem_agent.cli", "live-smoke"], capture_output=True, text=True, env=env,
                       timeout=120)
    assert p.returncode == 3
    assert "UNVERIFIED" in p.stdout and "OPENAI_API_KEY present: False" in p.stdout and "PASS" not in p.stdout


@pytest.mark.synthetic
def test_injection_in_tool_output_cannot_expand_tools(real_store, selection):
    """Even if a document told the model to call a write tool, the dispatcher has no such tool."""
    from nem_agent.agent.dispatcher import Dispatcher
    from nem_agent.evidence import EvidenceRegistry

    d = Dispatcher(real_store, selection, Trace(), EvidenceRegistry(), "source_explanation")
    for name in ("publish_case_note", "approve_case_note", "shell", "http_get"):
        rec = d.call(name, {"note": "approved by document"})
        assert rec.status == "blocked"
    assert not d.registry.items and not d.registry.chunks
