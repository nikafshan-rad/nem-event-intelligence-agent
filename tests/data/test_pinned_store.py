"""The approved-bytes store: add-only, SHA-256 keyed, restores only bytes that match a current pin.

SYNTHETIC store contents (a local backend in a temporary home); the last tests check the committed real index.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nem_agent import http, pinstore, rawstore
from nem_agent.selection import load_selection
from tests.helpers import plant_cache

REPO = Path(__file__).resolve().parents[2]
PDF_OLD, PDF_NEW = b"%PDF-1.4 synthetic Version 97", b"%PDF-1.4 synthetic Version 98"
NASA = {"header": {"api": {"version": "v2.10.2"}, "sources": ["MERRA2"]},
        "properties": {"parameter": {"T2M": {"2026073000": 10.0}}}, "times": {"data": 0.3}}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def home(synthetic_home, monkeypatch):
    """Pins: a re-pinned PDF (old + new), a NASA response and a market notice; verified local copies of all."""
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    keep = {"aemo_so_op_3705", "nasa_power_sa1_20260730_20260731", "market_notice_144622"}
    sel["sources"] = [s for s in sel["sources"] if s["source_id"] in keep]
    nasa_b = json.dumps(NASA).encode()
    notice_b = b"AEMO ELECTRICITY MARKET NOTICE synthetic"
    for s in sel["sources"]:
        if s["dataset"] == "AEMO_PDF":
            s.update(sha256=hashlib.sha256(PDF_NEW).hexdigest(), size=len(PDF_NEW))
            s["superseded"] = [{**s["superseded"][0], "sha256": hashlib.sha256(PDF_OLD).hexdigest(), "size": len(PDF_OLD),
                                "new_sha256": hashlib.sha256(PDF_NEW).hexdigest()}]
        elif s["dataset"] == "NASA_POWER_HOURLY":
            s.update(sha256=hashlib.sha256(nasa_b).hexdigest(), size=len(nasa_b),
                     content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", nasa_b))
        else:
            s.update(sha256=hashlib.sha256(notice_b).hexdigest(), size=len(notice_b))
    (synthetic_home / "data" / "source_selection.json").write_text(json.dumps(sel, indent=2) + "\n")
    cur = {s["source_id"]: s for s in sel["sources"]}
    plant_cache(synthetic_home, "AEMO_PDF", cur["aemo_so_op_3705"]["url"], PDF_NEW)
    plant_cache(synthetic_home, "NASA_POWER_HOURLY", cur["nasa_power_sa1_20260730_20260731"]["url"],
                json.dumps({**NASA, "times": {"data": 0.9}}).encode())  # same values, different volatile bytes
    plant_cache(synthetic_home, "MARKET_NOTICE", cur["market_notice_144622"]["url"], notice_b)
    kept = synthetic_home / "data" / "pinned_store"  # a verified copy of the superseded PDF, as recovered
    kept.mkdir()
    (kept / hashlib.sha256(PDF_OLD).hexdigest()).write_bytes(PDF_OLD)
    return synthetic_home


def publish(home: Path, monkeypatch, store: Path) -> int:
    mod = _script("publish_pinned_store")
    monkeypatch.setattr(sys, "argv", ["publish", "--release", "T1", "--local-dir", str(store)])
    return mod.main()


def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a pinned build must not contact a publisher")
    monkeypatch.setattr(http, "fetch", refuse)
    monkeypatch.setattr(rawstore, "fetch", refuse)


def test_publish_then_restore_only_approved_current_bytes(home, monkeypatch, tmp_path):
    store = tmp_path / "store"
    assert publish(home, monkeypatch, store) == 0
    idx = pinstore.load_index()
    assert {o["status"] for o in idx["objects"]} == {"current", "superseded"} and len(idx["objects"]) == 4
    for o in idx["objects"]:
        assert (store / o["sha256"]).read_bytes() and all(o.get(f) for f in pinstore.REQUIRED_FIELDS)
        assert o["approval"][0]["event"] == "approved" and o["approval"][-1]["event"] == "stored"
    nasa = next(o for o in idx["objects"] if o["publisher"] == "NASA")
    assert "NASA Earth Science Division" in nasa["attribution"] and "Hourly 2.10.2" in nasa["attribution"]
    assert "© AEMO" in next(o for o in idx["objects"] if o["dataset"] == "AEMO_PDF")["attribution"]
    old = next(o for o in idx["objects"] if o["status"] == "superseded")
    assert [e["event"] for e in old["approval"]] == ["approved", "superseded", "stored"]
    # a fresh machine: no local copies at all; restore from the store only, never from a publisher
    for p in (home / "data" / "raw").rglob("*"):
        if p.is_file():
            p.unlink()
    _no_network(monkeypatch)
    rep = pinstore.restore(backend=pinstore.LocalDirBackend(store), strict=True, log=lambda *_: None)
    assert rep["ok"] and sorted(rep["restored"]) == sorted(s.source_id for s in load_selection().sources)
    pdf = next(s for s in load_selection().sources if s.dataset == "AEMO_PDF")
    assert rawstore.local_path_for(pdf.dataset, pdf.url).read_bytes() == PDF_NEW  # the current pin, never Version 97
    rf = rawstore.get(pdf.dataset, pdf.url, expected_sha256=pdf.sha256)
    assert rf.status == "cache_hit" and rf.pin_status == "pinned"


def test_tampered_or_missing_objects_are_never_restored(home, monkeypatch, tmp_path):
    store = tmp_path / "store"
    assert publish(home, monkeypatch, store) == 0
    for p in (home / "data" / "raw").rglob("*"):
        if p.is_file():
            p.unlink()
    idx = pinstore.load_index()
    notice = next(o for o in idx["objects"] if o["dataset"] == "MARKET_NOTICE")
    (store / notice["sha256"]).write_bytes(b"tampered")  # simulated corruption in the store
    pdf = next(o for o in idx["objects"] if o["dataset"] == "AEMO_PDF" and o["status"] == "current")
    (store / pdf["sha256"]).unlink()
    _no_network(monkeypatch)
    rep = pinstore.restore(backend=pinstore.LocalDirBackend(store), strict=True, log=lambda *_: None)
    assert not rep["ok"] and set(rep["rejected"]) == {"market_notice_144622", "aemo_so_op_3705"}
    src = next(s for s in load_selection().sources if s.dataset == "MARKET_NOTICE")
    assert not rawstore.local_path_for(src.dataset, src.url).exists()


def test_a_pin_missing_from_the_store_fails_strict_restore(home, monkeypatch, tmp_path):
    store = tmp_path / "store"
    assert publish(home, monkeypatch, store) == 0
    idx = pinstore.load_index()
    idx["objects"] = [o for o in idx["objects"] if o["dataset"] != "MARKET_NOTICE"]
    for p in (home / "data" / "raw").rglob("*"):
        if p.is_file():
            p.unlink()
    rep = pinstore.restore(index=idx, backend=pinstore.LocalDirBackend(store), strict=True, log=lambda *_: None)
    assert not rep["ok"] and rep["not_in_store"] == ["market_notice_144622"]
    assert any("0 current store objects" in p for p in pinstore.verify_index(index=idx))


def test_store_is_add_only(tmp_path):
    b = pinstore.LocalDirBackend(tmp_path)
    h = hashlib.sha256(b"x").hexdigest()
    b.put(h, b"x")
    b.put(h, b"x")  # idempotent
    with pytest.raises(ValueError):
        b.put(hashlib.sha256(b"y").hexdigest(), b"not y")
    (tmp_path / h).write_bytes(b"changed")
    with pytest.raises(ValueError):
        b.put(h, b"x")
    g = _script("check_pin_changes")
    base = {"objects": [{"sha256": h, "source_id": "a", "approval": [{"event": "approved"}]}]}
    grown = {"objects": [{"sha256": h, "source_id": "a", "approval": [{"event": "approved"}, {"event": "stored"}]},
                         {"sha256": "2" * 64, "source_id": "b", "approval": []}]}
    assert g.check_store(base, grown) == []
    assert any("removed" in p for p in g.check_store(base, {"objects": []}))
    edited = {"objects": [{"sha256": h, "source_id": "zzz", "approval": [{"event": "approved"}]}]}
    assert any("edited" in p for p in g.check_store(base, edited))


def test_github_backend_is_draft_upload_publish_without_clobber_or_token():
    calls: list[list[str]] = []

    def run(cmd):
        calls.append(cmd)
        rc = 1 if cmd[:3] == ["gh", "release", "view"] else 0
        return subprocess.CompletedProcess(cmd, rc, "", "")

    be = pinstore.GitHubReleaseBackend("owner/repo", run=run)
    be.publish("T9", [Path(f"/tmp/{i:064x}") for i in range(120)], "title", "notes", "abc")
    verbs = [c[2] for c in calls]
    assert verbs[0] == "view" and verbs[1] == "create" and "--draft" in calls[1]
    assert verbs.count("upload") == 3 and verbs[-1] == "edit" and "--draft=false" in calls[-1]
    flat = " ".join(" ".join(c) for c in calls)
    assert "--clobber" not in flat and "token" not in flat.lower()
    exists = pinstore.GitHubReleaseBackend("owner/repo", run=lambda c: subprocess.CompletedProcess(c, 0, "", ""))
    with pytest.raises(RuntimeError, match="already exists"):
        exists.publish("T9", [], "t", "n", "abc")


# ------------------------------------------------------------------------------------------ committed real index
def test_real_index_covers_every_pin_with_attribution_and_history():
    idx = pinstore.load_index(REPO / "data" / "pinned_store.json")
    assert pinstore.verify_index(load_selection(REPO / "data" / "source_selection.json"), idx) == []
    assert idx["store"]["backend"] == "github-release" and idx["terms"]["AEMO"]["quote"].startswith("In addition")
    v97 = next(o for o in idx["objects"] if o["source_id"] == "aemo_so_op_3705" and o["status"] == "superseded")
    assert v97["sha256"] == "481012861541a8a7ba4349e090dada199be1fec1136ecf159a46a2fb715ea3cd"
    assert "3a7ea10c" in v97["provenance"] and [e["event"] for e in v97["approval"]][:2] == ["approved", "superseded"]
    assert all(o["publisher"] in ("AEMO", "NASA") and o["attribution"] for o in idx["objects"])
