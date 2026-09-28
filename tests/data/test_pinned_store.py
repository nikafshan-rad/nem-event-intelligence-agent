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


def _download_runner(results):
    """A fake `gh` that answers each `release download` with the next (returncode, stderr) and records the dirs."""
    calls, dirs = [], []

    def run(cmd):
        calls.append(cmd)
        dirs.append(Path(cmd[cmd.index("--dir") + 1]))
        rc, err = results[len(calls) - 1]
        if rc == 0:
            (dirs[-1] / "a").write_bytes(b"x")
        else:
            (dirs[-1] / "partial").write_bytes(b"half")  # a failed attempt may leave a partial file behind
        return subprocess.CompletedProcess(cmd, rc, "", err)
    return run, calls, dirs


def test_release_download_retries_transient_server_errors_only():
    """CI on a0f9995: one HTTP 500 on a release asset failed the restore step outright."""
    run, calls, dirs = _download_runner([(1, "HTTP 500 (https://api.github.com/repos/o/r/releases/assets/1)"),
                                         (1, "read: connection reset by peer"), (0, "")])
    waits, logs = [], []
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, sleep=waits.append, log=logs.append)
    d = be._download("T1")
    assert len(calls) == 3 and waits == [10.0, 30.0] and len(logs) == 2
    assert d == dirs[-1] and (d / "a").exists()
    assert not dirs[0].exists() and not dirs[1].exists()  # partial downloads are discarded, never reused
    assert be._download("T1") == d and len(calls) == 3    # downloaded once per run
    flat = " ".join(" ".join(c) for c in calls)
    assert "token" not in flat.lower()                    # authentication stays with gh (GH_TOKEN), not arguments


@pytest.mark.parametrize("err", ["HTTP 404: Not Found (https://api.github.com/repos/o/r/releases/tags/T1)",
                                 "HTTP 401: Bad credentials", "HTTP 403: Resource not accessible by integration",
                                 "release not found"])
def test_release_download_fails_at_once_on_permanent_errors(err):
    run, calls, _ = _download_runner([(1, err)] * 3)
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, sleep=lambda s: None, log=lambda *a: None)
    with pytest.raises(RuntimeError, match="attempt 1 of 3"):
        be._download("T1")
    assert len(calls) == 1


def test_release_download_gives_up_after_three_transient_errors():
    run, calls, _ = _download_runner([(1, "HTTP 502 Bad Gateway")] * 3)
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, sleep=lambda s: None, log=lambda *a: None)
    with pytest.raises(RuntimeError, match="attempt 3 of 3"):
        be._download("T1")
    assert len(calls) == 3


def test_restored_bytes_are_still_checked_against_their_sha256(tmp_path):
    """A retried download changes nothing about verification: bytes that do not hash to the pin are rejected."""
    obj = {"sha256": "0" * 64, "release": "T1", "size": 1}

    class Backend:
        def get(self, o):
            return b"not the pinned bytes"
    assert pinstore.satisfies(obj, Backend().get(obj), type("S", (), {"sha256": "0" * 64, "content_sha256": None,
                                                                       "dataset": "X"})()) is False


# ------------------------------------------------------------------------------------------ bundles (CI API quota)
# CI on the v4 freeze commit (0b667e2): restoring 307 assets one by one spent ~311 API calls per job, four jobs per
# push exhausted the workflow token's quota, and all four stopped with "HTTP 403: API rate limit exceeded for
# installation". A bundle is one asset holding many objects: two calls per restore.
def _objects(n: int = 5) -> list[tuple[dict, bytes]]:
    datas = [f"SYNTHETIC object {i}".encode() for i in range(n)]
    return [({"sha256": hashlib.sha256(d).hexdigest(), "release": "T1", "size": len(d)}, d) for d in datas]


def _bundle(tmp_path: Path, objs: list[tuple[dict, bytes]], name: str = "b.tar.gz") -> dict:
    built = _script("publish_store_bundle").build_bundle(objs, tmp_path / name)
    return {"release": "B1", "asset": name, **built, "created_at": "2026-09-28T00:00:00Z", "note": "SYNTHETIC"}


def _serving(tmp_path: Path, asset: str):
    """A fake `gh` that serves the bundle file for `--pattern <asset>` and records every call."""
    import shutil
    calls: list[list[str]] = []

    def run(cmd):
        calls.append(cmd)
        d = Path(cmd[cmd.index("--dir") + 1])
        if "--pattern" in cmd:
            shutil.copy(tmp_path / asset, d / asset)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run, calls


def test_a_bundle_restores_every_object_with_one_download(tmp_path):
    objs = _objects(5)
    entry = _bundle(tmp_path, objs)
    run, calls = _serving(tmp_path, entry["asset"])
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    assert all(be.get(o) == d for o, d in objs)
    assert len(calls) == 1 and calls[0][:4] == ["gh", "release", "download", "B1"]
    assert calls[0][calls[0].index("--pattern") + 1] == entry["asset"]
    assert _bundle(tmp_path, list(reversed(objs)), "c.tar.gz")["sha256"] == entry["sha256"]  # same objects, same bundle


def test_a_bundle_that_does_not_match_its_recorded_hash_is_refused(tmp_path):
    objs = _objects(3)
    entry = _bundle(tmp_path, objs) | {"sha256": "0" * 64}
    run, _ = _serving(tmp_path, entry["asset"])
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    with pytest.raises(RuntimeError, match="does not match its recorded SHA-256"):
        be.get(objs[0][0])


@pytest.mark.parametrize("member", ["../escape", "a" * 64, "subdir/" + "b" * 64])
def test_a_bundle_with_an_unlisted_or_path_member_is_refused(tmp_path, member):
    import io
    import tarfile
    objs = _objects(2)
    with tarfile.open(tmp_path / "bad.tar.gz", "w:gz") as tf:
        for name, data in [(objs[0][0]["sha256"], objs[0][1]), (member, b"x")]:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    blob = (tmp_path / "bad.tar.gz").read_bytes()
    entry = {"release": "B1", "asset": "bad.tar.gz", "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
             "objects": [o["sha256"] for o, _ in objs], "created_at": "t", "note": "SYNTHETIC"}
    run, _ = _serving(tmp_path, "bad.tar.gz")
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    with pytest.raises(RuntimeError, match="unexpected member"):
        be.get(objs[0][0])


def test_bytes_from_a_bundle_are_still_checked_against_their_key_and_pin(tmp_path):
    """The bundle's hash only proves it is the recorded bundle; each object is still verified by `satisfies`."""
    (good, _good_data), (_other, other_data) = _objects(2)
    entry = _bundle(tmp_path, [(good, other_data)])  # a key whose bytes are not the ones it names
    run, _ = _serving(tmp_path, entry["asset"])
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    got = be.get(good)
    src = type("S", (), {"sha256": good["sha256"], "content_sha256": None, "dataset": "X"})()
    assert got == other_data and pinstore.satisfies(good, got, src) is False


def test_objects_outside_every_bundle_still_come_from_their_own_release(tmp_path):
    objs = _objects(2)
    entry = _bundle(tmp_path, objs[:1])
    run, calls, _ = _download_runner([(0, "")])
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    be.get(objs[1][0])
    assert calls[0][:4] == ["gh", "release", "download", "T1"] and "--pattern" not in calls[0]


@pytest.mark.parametrize("err, cause", [
    ("HTTP 403: API rate limit exceeded for installation. If you reach out to GitHub Support", "rate limited"),
    ("HTTP 403: Resource not accessible by integration", "permission denied"),
    ("HTTP 404: Not Found (https://api.github.com/repos/o/r/releases/tags/T1)", "not found")])
def test_a_failed_download_names_its_cause_and_is_not_retried(err, cause):
    run, calls, _ = _download_runner([(1, err)] * 3)
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, sleep=lambda s: None, log=lambda *a: None)
    with pytest.raises(RuntimeError, match=cause):
        be._download("T1")
    assert len(calls) == 1


def test_bundles_are_add_only():
    check = _script("check_pin_changes").check_store
    b = {"release": "B1", "asset": "b.tar.gz", "sha256": "1" * 64, "size": 1, "objects": [], "created_at": "t",
         "note": "n"}
    base = {"objects": [], "bundles": [b]}
    assert check(base, {"objects": [], "bundles": [b, {**b, "sha256": "2" * 64}]}) == []   # appending is fine
    assert check(base, {"objects": [], "bundles": []})                                      # removal is not
    assert check(base, {"objects": [], "bundles": [{**b, "size": 2}]})                       # nor an edit


def test_real_index_restores_every_current_pin_from_one_bundle():
    """The committed index: one recorded bundle covers the current object of every pin, so a fresh CI runner
    restores all approved files with one bundle download."""
    idx = json.loads((REPO / "data" / "pinned_store.json").read_text())
    sel = load_selection(REPO / "data" / "source_selection.json")
    current = {pinstore.current_object(idx, s)["sha256"] for s in sel.sources}
    bundled = {x for b in idx.get("bundles", []) for x in b["objects"]}
    assert current <= bundled, f"{len(current - bundled)} current objects are in no bundle"
    assert pinstore.verify_index(sel, idx) == []


def _bundle_home(home, monkeypatch, tmp_path, tamper: bool):
    """Publish the synthetic pins to a local store, then serve their current objects as one bundle through a fake
    `gh`, on a fresh machine (no local copies, no network). With ``tamper``, the bundle (whose own hash is recorded
    correctly) still lists every object but omits one and alters another."""
    store = tmp_path / "store"
    assert publish(home, monkeypatch, store) == 0
    idx = pinstore.load_index()
    current = [o for o in idx["objects"] if o["status"] == "current"]
    objs = [(o, (store / o["sha256"]).read_bytes()) for o in current]
    if tamper:
        objs = [(objs[0][0], b"tampered bytes")] + objs[2:]  # objs[0] altered, objs[1] missing
    entry = _bundle(tmp_path, objs) | {"objects": sorted(o["sha256"] for o in current)}
    for p in (home / "data" / "raw").rglob("*"):
        if p.is_file():
            p.unlink()
    _no_network(monkeypatch)
    run, calls = _serving(tmp_path, entry["asset"])
    be = pinstore.GitHubReleaseBackend("owner/repo", run=run, bundles=[entry])
    return pinstore.restore(index=idx, backend=be, strict=True, log=lambda *_: None), calls, current


def test_a_fresh_restore_from_a_bundle_verifies_every_pin_with_one_download(home, monkeypatch, tmp_path):
    rep, calls, _ = _bundle_home(home, monkeypatch, tmp_path, tamper=False)
    assert rep["ok"] and sorted(rep["restored"]) == sorted(s.source_id for s in load_selection().sources)
    assert len(calls) == 1 and "--pattern" in calls[0]
    for s in load_selection().sources:  # every restored file is its approved bytes
        data = rawstore.local_path_for(s.dataset, s.url).read_bytes()
        assert hashlib.sha256(data).hexdigest() == s.sha256 or \
            rawstore.content_sha256(s.dataset, data) == s.content_sha256


def test_a_bundle_missing_or_altering_a_listed_object_fails_closed(home, monkeypatch, tmp_path):
    rep, _, current = _bundle_home(home, monkeypatch, tmp_path, tamper=True)
    bad = {current[0]["source_id"], current[1]["source_id"]}
    assert not rep["ok"] and set(rep["rejected"]) == bad
    for s in load_selection().sources:
        if s.source_id in bad:
            assert not rawstore.local_path_for(s.dataset, s.url).exists()  # nothing substituted, nothing written


# ------------------------------------------------------------------------------------------ names and re-pin coverage
@pytest.mark.parametrize("field, value", [("asset", "../escape.tar.gz"), ("asset", "dir/x.tar.gz"), ("asset", "*.tar.gz"),
                                          ("asset", ".hidden.tar.gz"), ("asset", ""), ("release", "../tag"),
                                          ("release", "tag name")])
def test_unsafe_bundle_names_are_refused_before_gh_is_called(tmp_path, field, value):
    objs = _objects(1)
    entry = _bundle(tmp_path, objs) | {field: value}
    calls: list = []
    be = pinstore.GitHubReleaseBackend("owner/repo", run=calls.append, bundles=[entry])
    with pytest.raises(RuntimeError, match="not a plain name"):
        be.get(objs[0][0])
    assert calls == []


def test_an_unsafe_release_tag_for_an_unbundled_object_is_refused_before_gh_is_called():
    calls: list = []
    be = pinstore.GitHubReleaseBackend("owner/repo", run=calls.append)
    with pytest.raises(RuntimeError, match="not a plain name"):
        be.get({"sha256": "0" * 64, "release": "../../x", "size": 1})
    assert calls == []


def _real_index():
    import copy
    return (copy.deepcopy(json.loads((REPO / "data" / "pinned_store.json").read_text())),
            load_selection(REPO / "data" / "source_selection.json"))


def test_store_verify_fails_while_a_current_pin_is_in_no_bundle():
    """A future approved re-pin: until a new verified bundle lists its new object, store-verify (a CI step) fails;
    registering such a bundle clears it (a later bundle takes precedence)."""
    idx, sel = _real_index()
    src = sel.sources[0]
    obj = pinstore.current_object(idx, src)
    idx["bundles"][0]["objects"].remove(obj["sha256"])  # as if this pin had moved to an object no bundle lists
    problems = pinstore.verify_index(sel, idx)
    assert any(src.source_id in p and "in no bundle" in p and "publish_store_bundle.py" in p for p in problems)
    idx["bundles"].append({**idx["bundles"][0], "release": "pinned-bytes-bundle-next", "sha256": "1" * 64,
                           "objects": [obj["sha256"]]})
    assert pinstore.verify_index(sel, idx) == []


def test_store_verify_flags_names_that_are_not_plain():
    idx, sel = _real_index()
    idx["bundles"][0]["asset"] = "../x.tar.gz"
    idx["objects"][0]["release"] = "a/b"
    problems = pinstore.verify_index(sel, idx)
    assert any("asset is not a plain name" in p for p in problems)
    assert any("release name 'a/b' is not a plain name" in p for p in problems)


def test_a_local_store_is_not_held_to_bundle_coverage(home, monkeypatch, tmp_path):
    assert publish(home, monkeypatch, tmp_path / "store") == 0  # a local-dir store has no bundles
    assert pinstore.verify_index() == []


def test_publish_store_bundle_refuses_an_unsafe_release_name_before_any_download(monkeypatch):
    mod = _script("publish_store_bundle")
    monkeypatch.setattr(sys, "argv", ["publish_store_bundle", "--release", "../evil", "--dry-run"])
    monkeypatch.setattr(pinstore.GitHubReleaseBackend, "_fetch", lambda *a, **k: pytest.fail("no download expected"))
    assert mod.main() == 2


def test_the_repin_procedure_requires_a_new_bundle():
    gov = (REPO / "docs" / "source-governance.md").read_text()
    assert "publish_store_bundle.py" in gov and "fails while any current pin is in no bundle" in gov
    assert "publish_store_bundle.py" in (REPO / "scripts" / "repin_source.py").read_text()
