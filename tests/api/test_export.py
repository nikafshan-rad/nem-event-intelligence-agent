"""Tests for GET /report/{trace_id}/export."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nem_agent.api import _REPORTS, app


@pytest.fixture()
def client():
    return TestClient(app)


_FAKE_TRACE = "tr-aabbccddeeff"
_FAKE_REPORT: dict = {"trace_id": _FAKE_TRACE, "status": "answered", "headline": "test",
                       "region": "SA1", "observations": [], "summary": [], "citations": [],
                       "validation": {"final_passed": True}}


@pytest.fixture(autouse=True)
def _seed_cache():
    _REPORTS[_FAKE_TRACE] = _FAKE_REPORT.copy()
    yield
    _REPORTS.pop(_FAKE_TRACE, None)


def test_export_success(client):
    r = client.get(f"/report/{_FAKE_TRACE}/export")
    assert r.status_code == 200
    assert r.json()["trace_id"] == _FAKE_TRACE


def test_export_unknown_trace_id(client):
    r = client.get("/report/tr-000000000000/export")
    assert r.status_code == 404
    assert "unknown trace id" in r.json()["detail"]


def test_export_invalid_trace_id_format(client):
    r = client.get("/report/not-a-valid-id/export")
    assert r.status_code == 404
    assert "invalid trace id format" in r.json()["detail"]


def test_export_json_equivalence(client):
    """The export endpoint returns exactly the dict stored by POST /investigate."""
    body = client.get(f"/report/{_FAKE_TRACE}/export").json()
    assert body == _FAKE_REPORT


def test_export_strict_json_serializable(client):
    """The response round-trips through json.dumps without a default fallback."""
    body = client.get(f"/report/{_FAKE_TRACE}/export").json()
    raw = json.dumps(body)
    assert json.loads(raw) == body


@pytest.mark.parametrize("bad_id", ["", "tr-short", "tr-zzzzzzzzzzzz", "TR-AABBCCDDEEFF",
                                     "../etc/passwd", "tr-aabbccddeeff; rm -rf /"])
def test_export_rejects_malformed_ids(client, bad_id):
    r = client.get(f"/report/{bad_id}/export")
    assert r.status_code == 404
