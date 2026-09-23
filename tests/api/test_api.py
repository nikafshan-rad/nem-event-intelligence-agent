"""G7: API contract via FastAPI's TestClient (same process, real data)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nem_agent.api import app
from nem_agent.report import InvestigationReport


@pytest.fixture(scope="module")
def client(real_store):
    return TestClient(app)


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["replay_available"] is True and h["data_version"]


def test_investigate_real_event(client, selection):
    ev = selection.primary
    r = client.post("/investigate", json={"question": f"What happened around the {ev.region} price spike on 2026-07-31?"})
    assert r.status_code == 200
    rep = InvestigationReport.model_validate(r.json()["report"])
    assert rep.status == "answered" and rep.validation["final_passed"]
    assert rep.observations[0].value == pytest.approx(ev.peak_rrp)
    ev_row = client.get(f"/evidence/{rep.observations[0].source_row_ids[0]}").json()
    assert ev_row["raw_line"].startswith("D,DISPATCH,PRICE")
    assert client.get(f"/trace/{rep.trace_id}").status_code == 200


@pytest.mark.parametrize("body", [{"question": "x"}, {"question": "valid question here", "region": "WA1"},
                                  {"question": "valid question", "as_of_utc": 5, "extra": 1}])
def test_bad_input_is_bounded_422(client, body):
    r = client.post("/investigate", json=body)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request" and "Traceback" not in r.text


def test_live_without_key_is_400(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/investigate", json={"question": "What happened in SA1 on 2026-07-31?", "mode": "live"})
    assert r.status_code == 400


def test_unknown_trace_and_evidence_404(client):
    assert client.get("/trace/tr-000000000000").status_code == 404
    assert client.get("/evidence/NOT:A:ROW").status_code == 404


@pytest.mark.synthetic
def test_case_note_flow_over_http(client, tmp_path, monkeypatch):
    import nem_agent.paths as P

    monkeypatch.setattr(P, "case_notes_dir", lambda: tmp_path / "notes")
    rep = client.post("/investigate", json={"question": "What does operational demand mean?"}).json()["report"]
    prop = client.post("/case-notes/propose", json={"trace_id": rep["trace_id"], "author": "analyst-1"}).json()
    no = client.post(f"/case-notes/{prop['proposal_id']}/publish", json={"approval_id": None})
    assert no.status_code == 403
    self_ = client.post(f"/case-notes/{prop['proposal_id']}/approve", json={"approved_sha256": prop["content_sha256"]},
                        headers={"X-Mock-Reviewer": "analyst-1"})
    assert self_.status_code == 403
    ok = client.post(f"/case-notes/{prop['proposal_id']}/approve", json={"approved_sha256": prop["content_sha256"]},
                     headers={"X-Mock-Reviewer": "mock-reviewer-a"}).json()
    first = client.post(f"/case-notes/{prop['proposal_id']}/publish", json={"approval_id": ok["approval_id"]}).json()
    again = client.post(f"/case-notes/{prop['proposal_id']}/publish", json={"approval_id": ok["approval_id"]}).json()
    assert first["status"] == "written" and again["status"] == "already_published"
    assert len(list((tmp_path / "notes" / "notes").glob("*.json"))) == 1
