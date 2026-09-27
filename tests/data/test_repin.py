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
    monkeypatch.setenv("NEM_AGENT_HOME", str(tmp_path))  # raw cache and pinned store stay inside the test
    (tmp_path / "data").mkdir()
    spec = importlib.util.spec_from_file_location("repin_source", REPO / "scripts" / "repin_source.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    sel = tmp_path / "source_selection.json"
    shutil.copy(REPO / "data" / "source_selection.json", sel)

    def run(source_id: str, expect: str, body: bytes, *extra: str, approver: str | None = "A. Reviewer") -> int:
        monkeypatch.setattr(http, "fetch", lambda url, **k: http.HttpResult(
            url=url, status=200, body=body, content_type="application/octet-stream", last_modified="Thu, 01 Oct 2026"))
        monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)
        monkeypatch.setattr(sys, "argv", ["repin", "--selection", str(sel), "--source-id", source_id, "--expect", expect,
                                          "--publisher-revision", "synthetic revision", "--reason", "synthetic test",
                                          *(["--approved-by", approver] if approver else []), *extra])
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


def test_approval_requires_a_named_reviewer(repin):
    run, _sel = repin
    with pytest.raises(SystemExit):
        run("aemo_so_op_3705", hashlib.sha256(b"%PDF-1.7 x").hexdigest(), b"%PDF-1.7 x", approver=None)


def test_approval_is_linked_to_the_refresh_report_and_keeps_old_bytes(repin, tmp_path):
    from tests.helpers import plant_cache

    run, sel = repin
    doc = json.loads(sel.read_text())
    e = next(s for s in doc["sources"] if s["source_id"] == "aemo_so_op_3705")
    old_bytes = b"%PDF-1.7 synthetic Version 97"
    e.update(sha256=hashlib.sha256(old_bytes).hexdigest(), size=len(old_bytes))
    sel.write_text(json.dumps(doc, indent=2) + "\n")
    plant_cache(tmp_path, "AEMO_PDF", e["url"], old_bytes)
    new_bytes = b"%PDF-1.7 synthetic Version 98"
    new_id = hashlib.sha256(new_bytes).hexdigest()
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"run_id": "R1", "generated_at": "2026-09-27T00:00:00Z", "sources": [
        {"source_id": "aemo_so_op_3705", "result": "changed", "new_identity": "f" * 64}]}))
    assert run("aemo_so_op_3705", new_id, new_bytes, "--report", str(report)) == 1  # report lists another version
    report.write_text(json.dumps({"run_id": "R1", "generated_at": "2026-09-27T00:00:00Z", "sources": [
        {"source_id": "aemo_so_op_3705", "result": "changed", "new_identity": new_id,
         "metadata": {"pinned": {"version": "97"}, "current": {"version": "98"}}}]}))
    assert run("aemo_so_op_3705", new_id, new_bytes, "--report", str(report)) == 0
    rec = _entry(sel, "aemo_so_op_3705")["superseded"][-1]
    assert rec["approved_by"] == "A. Reviewer" and rec["refresh_report"]["run_id"] == "R1"
    assert rec["refresh_report"]["sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert rec["metadata"]["current"]["version"] == "98" and rec["sha256"] == hashlib.sha256(old_bytes).hexdigest()
    kept = tmp_path / "data" / "pinned_store" / rec["sha256"]
    assert kept.read_bytes() == old_bytes and "kept on this machine only" in rec["old_bytes"]
    # the pull-request guard accepts exactly this change
    spec = importlib.util.spec_from_file_location("check_pin_changes", REPO / "scripts" / "check_pin_changes.py")
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
    assert g.check(doc, json.loads(sel.read_text())) == []


def test_old_bytes_not_held_is_stated(repin):
    run, sel = repin
    body = b"%PDF-1.7 another revision"
    assert run("aemo_so_op_3705", hashlib.sha256(body).hexdigest(), body) == 0
    assert _entry(sel, "aemo_so_op_3705")["superseded"][-1]["old_bytes"].startswith("not kept")
