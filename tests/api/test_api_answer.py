"""D25 API migration: a question with a computed maximum returns it in `answer` (rendered from a verified result, with
its limitations and source rows), `summary` holds the interpretation only, and `summary_v1` gives the pre-D25 reading.
Questions without a computed maximum are unchanged (no `answer`). Same process, real data, Replay mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nem_agent.api import app
from nem_agent.report import InvestigationReport, summary_v1

Z04 = json.loads((Path(__file__).resolve().parents[2] / "artifacts" / "live" / "L3-holdout-v6" / "Z04.json")
                 .read_text())["question"]


@pytest.fixture(scope="module")
def client(real_store):
    return TestClient(app)


def test_a_computed_maximum_is_in_answer_and_not_in_summary(client):
    body = client.post("/investigate", json={"question": Z04}).json()
    raw = body["report"]
    (a,) = raw["answer"]
    assert (a["kind"], a["status"], a["verification"]) == ("demand_maximum", "established", "verified")
    assert a["statement"].startswith("TAS1 dispatch total demand (TOTALDEMAND) was highest at 1367.32 MW")
    assert a["limitations"] and a["source_row_ids"]
    assert a["statement"] not in raw["summary"] and summary_v1(raw)[0] == a["statement"]
    assert raw["validation"]["interpretation"] == "scripted"
    rep = InvestigationReport.model_validate(raw)  # the response round-trips through the published schema
    assert rep.answer[0].statement == a["statement"] and summary_v1(rep) == summary_v1(raw)
    # the typed result behind it travels with the server's statement
    assert raw["results"][0]["result"]["result_id"] == a["result_id"]
    assert raw["results"][0]["server_verification"]["outcome"] == "verified"


def test_the_published_schema_documents_answer(client):
    schema = client.get("/schema/report").json()
    assert "answer" in schema["properties"] and "RenderedResult" in json.dumps(schema)
    assert "interpretation" in schema["properties"]["answer"]["description"]


def test_a_question_without_a_computed_maximum_is_unchanged(client, selection):
    ev = selection.primary
    raw = client.post("/investigate",
                      json={"question": f"What happened around the {ev.region} price spike on 2026-07-31?"}).json()["report"]
    assert raw["answer"] == [] and raw["results"] == [] and summary_v1(raw) == raw["summary"]
