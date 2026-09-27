"""SYNTHETIC: a pin moves only to the reviewed hash, keeps its history, and never follows what the server returns."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from nem_agent import http, rawstore
from nem_agent.selection import load_selection

pytestmark = pytest.mark.synthetic
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def repin(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("repin_source", REPO / "scripts" / "repin_source.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    sel = tmp_path / "source_selection.json"
    shutil.copy(REPO / "data" / "source_selection.json", sel)

    def run(source_id: str, expect: str, body: bytes) -> int:
        monkeypatch.setattr(http, "fetch", lambda url, **k: http.HttpResult(
            url=url, status=200, body=body, content_type="application/octet-stream", last_modified="Thu, 01 Oct 2026"))
        monkeypatch.setattr(sys, "argv", ["repin", "--selection", str(sel), "--source-id", source_id, "--expect", expect,
                                          "--publisher-revision", "synthetic revision", "--reason", "synthetic test"])
        return mod.main()

    return run, sel


def _entry(sel: Path, source_id: str) -> dict:
    return next(s for s in json.loads(sel.read_text())["sources"] if s["source_id"] == source_id)


def test_unreviewed_content_is_refused_and_nothing_is_written(repin):
    run, sel = repin
    before = sel.read_bytes()
    assert run("aemo_so_op_3705", "0" * 64, b"%PDF-1.7 revised") == 1
    assert run("aemo_so_op_3705", hashlib.sha256(b"not a pdf").hexdigest(), b"not a pdf") == 1
    assert sel.read_bytes() == before and not (sel.parent / "SOURCES.md").exists()


def test_reviewed_revision_moves_the_pin_and_keeps_history(repin):
    run, sel = repin
    old = _entry(sel, "aemo_so_op_3705")
    body = b"%PDF-1.7 synthetic revision"
    assert run("aemo_so_op_3705", hashlib.sha256(body).hexdigest(), body) == 0
    new = _entry(sel, "aemo_so_op_3705")
    assert new["sha256"] == hashlib.sha256(body).hexdigest() and new["size"] == len(body)
    hist = new["superseded"][-1]
    assert hist["sha256"] == old["sha256"] and hist["new_sha256"] == new["sha256"]
    assert hist["publisher_revision"] == "synthetic revision"
    assert load_selection(sel).sources  # still valid under the strict schema
    assert "Pin revisions" in (sel.parent / "SOURCES.md").read_text()
    others = {s["source_id"]: s for s in json.loads((REPO / "data" / "source_selection.json").read_text())["sources"]}
    assert all(s == others[s["source_id"]] for s in json.loads(sel.read_text())["sources"]
               if s["source_id"] != "aemo_so_op_3705")


def test_api_sources_are_pinned_by_their_content_hash(repin):
    run, sel = repin
    sid = next(s["source_id"] for s in json.loads(sel.read_text())["sources"] if s["dataset"] == "NASA_POWER_HOURLY")
    body = json.dumps({"header": {"sources": ["MERRA2"]}, "properties": {"parameter": {"T2M": {"2099010100": 1.0}}},
                       "times": {"data": 0.3}}).encode()
    content = rawstore.content_sha256("NASA_POWER_HOURLY", body)
    assert run(sid, hashlib.sha256(body).hexdigest(), body) == 1  # the raw hash is not the API identity
    assert run(sid, content, body) == 0
    e = _entry(sel, sid)
    assert e["content_sha256"] == content and e["superseded"][-1]["content_sha256"]
