"""SYNTHETIC: source governance. Pinned content only; revisions detected, reported and never substituted.

No network: publisher responses are stubbed. Covers unchanged, changed, inconsistent and unavailable content, what the
application reports for each, the pin-change guard and the notice archive lookup.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from nem_agent import http, nemweb, rawstore, recover, refresh, sources
from nem_agent.selection import load_selection
from tests.helpers import plant_cache

pytestmark = pytest.mark.synthetic
REPO = Path(__file__).resolve().parents[2]
NASA = {"header": {"api": {"version": "v2.10.2"}, "sources": ["MERRA2"]},
        "properties": {"parameter": {"T2M": {"2026073000": 10.0, "2026073001": 11.0}}}, "times": {"data": 0.3}}


def tiny_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF whose text pypdf can extract."""
    content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({ln}) Tj 0 -14 Td" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


V97 = tiny_pdf(["Power System Security Guidelines", "Version 97", "Effective date: 1 April 2026", "Dispatch rules A"])
V98 = tiny_pdf(["Power System Security Guidelines", "Version 98", "Effective date: 23 September 2026", "Dispatch rules B"])


@pytest.fixture
def home(synthetic_home):
    """A home whose selection pins a PDF (V97), a NASA response and a market notice."""
    sel = json.loads((REPO / "data" / "source_selection.json").read_text())
    pick = {"aemo_so_op_3705": None, "nasa_power_sa1_20260730_20260731": None, "market_notice_144622": None}
    sel["sources"] = [s for s in sel["sources"] if s["source_id"] in pick]
    for s in sel["sources"]:
        s.pop("superseded", None)
        if s["dataset"] == "AEMO_PDF":
            s.update(sha256=hashlib.sha256(V97).hexdigest(), size=len(V97))
        if s["dataset"] == "NASA_POWER_HOURLY":
            b = json.dumps(NASA).encode()
            s.update(sha256=hashlib.sha256(b).hexdigest(), size=len(b),
                     content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", b))
    (synthetic_home / "data" / "source_selection.json").write_text(json.dumps(sel, indent=2) + "\n")
    (synthetic_home / "eval").mkdir()
    (synthetic_home / "eval" / "cases.json").write_text(json.dumps({"cases": [
        {"case_id": "C1", "expected": {"event_id": "SA1-20260731T0235-hi"}}]}))
    return synthetic_home


def serve(monkeypatch, table: dict[str, list]) -> None:
    """Stub the publishers: url -> list of bodies (bytes) or HTTP status codes, served in order, last one repeated."""
    count: dict[str, int] = {}

    def fetch(url, **_):
        i = count[url] = count.get(url, 0) + 1
        item = table[url][min(i, len(table[url])) - 1]
        if isinstance(item, int):
            return http.HttpResult(url=url, status=item, error=f"HTTP {item}")
        return http.HttpResult(url=url, status=200, body=item, headers={"Last-Modified": "Wed, 23 Sep 2026",
                                                                        "Set-Cookie": "session=secret"})

    monkeypatch.setattr(http, "fetch", fetch)
    monkeypatch.setattr(rawstore, "fetch", fetch)
    monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)


def _src(sid: str):
    return next(s for s in load_selection().sources if s.source_id == sid)


# ------------------------------------------------------------------------------------------ what the builds record
def test_build_status_distinguishes_pinned_revised_and_unavailable(home, monkeypatch):
    pdf = _src("aemo_so_op_3705")
    notice = _src("market_notice_144622")
    serve(monkeypatch, {pdf.url: [V98], notice.url: [404]})
    rf = rawstore.get(pdf.dataset, pdf.url, expected_sha256=pdf.sha256)
    assert (rf.pin_status, rf.upstream) == ("revised", "revised")        # never the new bytes
    plant_cache(home, pdf.dataset, pdf.url, V97)
    rf = rawstore.get(pdf.dataset, pdf.url, expected_sha256=pdf.sha256)
    assert (rf.status, rf.pin_status, rf.upstream) == ("cache_hit", "pinned", "not_checked")
    rf = rawstore.get(pdf.dataset, pdf.url, expected_sha256=pdf.sha256, refresh=True)
    assert (rf.status, rf.pin_status, rf.upstream) == ("cache_fallback", "pinned", "revised")
    assert rawstore.local_path_for(pdf.dataset, pdf.url).read_bytes() == V97
    rf = rawstore.get(notice.dataset, notice.url, expected_sha256=notice.sha256)
    assert (rf.pin_status, rf.upstream, rf.rolled_off) == ("unavailable", "unavailable", True)


def test_application_reports_the_three_categories(home):
    snap = {"data_version": "d1", "sources": {
        "nasa_power_sa1_20260730_20260731": {"dataset": "NASA_POWER_HOURLY", "pin_status": "revised",
                                              "upstream": "revised", "ingested": False, "error": "sha256 mismatch"}}}
    (home / "data" / "store").mkdir()
    (home / "data" / "store" / "snapshot.json").write_text(json.dumps(snap))
    man = {"corpus_version": "c1", "sources": [
        {"source_id": "aemo_so_op_3705", "ok": True, "pin_status": "pinned", "upstream": "not_checked"},
        {"source_id": "market_notice_144622", "ok": False, "pin_status": "unavailable", "upstream": "unavailable",
         "error": "HTTP 404", "rolled_off": True}]}
    (home / "data" / "index").mkdir()
    (home / "data" / "index" / "index_manifest.json").write_text(json.dumps(man))
    st = sources.source_statuses()
    by = {r["source_id"]: r for r in st["sources"]}
    assert (st["data_version"], st["corpus_version"]) == ("d1", "c1")
    assert (by["aemo_so_op_3705"]["category"], by["aemo_so_op_3705"]["in_use"]) == ("pinned", True)
    assert (by["nasa_power_sa1_20260730_20260731"]["category"], by["nasa_power_sa1_20260730_20260731"]["in_use"]) == \
        ("revised", False)
    assert (by["market_notice_144622"]["category"], by["market_notice_144622"]["in_use"]) == ("unavailable", False)
    # a later refresh check that saw a new upstream version flags the pinned PDF as revised but still in use
    rdir = sources.refresh_dir()
    rdir.mkdir(parents=True)
    (rdir / "latest.json").write_text(json.dumps({"generated_at": "t", "summary": {"changed": 1}, "sources": [
        {"source_id": "aemo_so_op_3705", "result": "changed", "retrieved_at": "t"}]}))
    st = sources.source_statuses()
    pdf = next(r for r in st["sources"] if r["source_id"] == "aemo_so_op_3705")
    assert (pdf["category"], pdf["in_use"]) == ("revised", True) and "review" in pdf["reason"]
    assert st["summary"] == {"pinned": 0, "revised_in_use_pending_review": 1, "revised_excluded": 1,
                             "unavailable_excluded": 1}
    from nem_agent import api

    assert api.sources()["summary"] == st["summary"]


# ------------------------------------------------------------------------------------------ publisher refresh check
def test_refresh_reports_unchanged_changed_inconsistent_and_unavailable(home, monkeypatch):
    pdf, nasa, notice = _src("aemo_so_op_3705"), _src("nasa_power_sa1_20260730_20260731"), _src("market_notice_144622")
    plant_cache(home, pdf.dataset, pdf.url, V97)
    pinned_nasa = json.dumps({**NASA, "times": {"data": 0.9}}).encode()
    variant = json.dumps({**NASA, "properties": {"parameter": {"T2M": {"2026073000": 10.4, "2026073001": 11.0}}}}).encode()
    before = (home / "data" / "source_selection.json").read_bytes()
    serve(monkeypatch, {pdf.url: [V98], nasa.url: [variant, pinned_nasa], notice.url: [404]})
    monkeypatch.setattr(nemweb, "list_dir", lambda d: (http.HttpResult(url=d, status=200), []))
    recover._notice_listing.clear()
    rep = refresh.run_refresh(log=lambda *_: None)
    by = {r["source_id"]: r for r in rep["sources"]}
    assert by[nasa.source_id]["result"] == "inconsistent" and "2 of 3" in by[nasa.source_id]["note"]
    c = by[pdf.source_id]
    assert c["result"] == "changed" and c["new_identity"] == hashlib.sha256(V98).hexdigest()
    assert c["pinned"]["sha256"] == pdf.sha256 and c["current"]["sha256"] == hashlib.sha256(V98).hexdigest()
    assert c["metadata"]["pinned"]["version"] == "97" and c["metadata"]["current"]["version"] == "98"
    assert c["metadata"]["current"]["effective_date"] == "23 September 2026"
    assert "+Version 98" in c["diff"]["excerpt"] and "-Version 97" in c["diff"]["excerpt"]
    assert c["affected"]["index_document"]["doc_id"] == "aemo_so_op_3705"
    u = by[notice.source_id]
    assert u["result"] == "unavailable" and u["expected_rolling_retention"]
    assert rep["notice_archive_observed"]["n_files"] == 0
    assert rep["needs_review"] and rep["summary"]["changed"] == 1
    # nothing was accepted: the manifest and the pinned cache are untouched, the candidate is only staged
    assert (home / "data" / "source_selection.json").read_bytes() == before
    assert rawstore.local_path_for(pdf.dataset, pdf.url).read_bytes() == V97
    assert (home / c["staged_path"]).read_bytes() == V98 and "source_refresh" in c["staged_path"]
    text = (sources.refresh_dir() / rep["run_id"] / "report.md").read_text()
    assert "scripts/repin_source.py --source-id aemo_so_op_3705" in text and "--approved-by" in text
    raw = json.dumps(rep) + text
    assert "secret" not in raw and "Set-Cookie" not in raw  # only a fixed set of safe headers is recorded
    assert json.loads((sources.refresh_dir() / "latest.json").read_text())["run_id"] == rep["run_id"]


def test_refresh_nothing_to_review_when_unchanged(home, monkeypatch):
    pdf = _src("aemo_so_op_3705")
    serve(monkeypatch, {pdf.url: [V97]})
    rep = refresh.run_refresh(source_ids=["aemo_so_op_3705"], log=lambda *_: None)
    assert rep["sources"][0]["result"] == "unchanged" and not rep["needs_review"]


def test_changed_without_local_pinned_bytes_says_why_there_is_no_diff(home, monkeypatch):
    pdf = _src("aemo_so_op_3705")
    serve(monkeypatch, {pdf.url: [V98]})
    rep = refresh.run_refresh(source_ids=["aemo_so_op_3705"], log=lambda *_: None)
    d = rep["sources"][0]["diff"]
    assert rep["sources"][0]["result"] == "changed" and not d["available"] and "not held on this machine" in d["why"]


def test_unexpected_unavailability_needs_review(home, monkeypatch):
    pdf = _src("aemo_so_op_3705")
    serve(monkeypatch, {pdf.url: [503]})
    rep = refresh.run_refresh(source_ids=["aemo_so_op_3705"], log=lambda *_: None)
    assert rep["summary"]["unavailable_unexpected"] == 1 and rep["needs_review"]


def test_nasa_value_diff_is_meaningful():
    old = json.dumps(NASA).encode()
    new = json.dumps({**NASA, "header": {**NASA["header"], "sources": ["GEOSIT"]},
                      "properties": {"parameter": {"T2M": {"2026073000": 11.5, "2026073001": 11.0}}}}).encode()
    d = refresh.content_diff("NASA_POWER_HOURLY", old, new)
    assert d["parameters"]["T2M"]["changed"] == 1 and d["parameters"]["T2M"]["max_abs_change"] == 1.5
    assert d["header_changes"]["sources"] == [["MERRA2"], ["GEOSIT"]]


# ------------------------------------------------------------------------------------------ notices in the Archive
def test_rolled_off_notice_recovered_from_archive_only_on_hash_match(home, monkeypatch):
    import io
    import zipfile

    notice = _src("market_notice_144622")
    name = notice.url.rsplit("/", 1)[-1]
    base = "https://nemweb.com.au/Reports/Archive/Market_Notice/"
    good = b"exact pinned notice bytes"
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr(name, good)
    entries = [nemweb.ListingEntry(name=n, url=base + n, listed_at_market=None, listed_at_utc=None, size=1, is_dir=False)
               for n in (name, "NOTICES_202607.zip")]
    monkeypatch.setattr(nemweb, "list_dir", lambda d: (http.HttpResult(url=d, status=200), entries))
    recover._notice_listing.clear()
    serve(monkeypatch, {base + name: [b"a different notice text"], base + "NOTICES_202607.zip": [bundle.getvalue()]})
    # the plain file with the same name does not match the pin and is rejected; the bundle member does and is used
    rf = recover.recover_from_archive(notice.dataset, notice.url, hashlib.sha256(good).hexdigest(), log=lambda *_: None)
    assert rf is not None and rf.pin_status == "pinned" and Path(rf.local_path).read_bytes() == good
    assert "NOTICES_202607.zip" in rf.error  # records where it came from
    # with no matching bytes anywhere, nothing is recovered (and nothing is substituted)
    recover._notice_listing.clear()
    assert recover.recover_from_archive(notice.dataset, notice.url, "0" * 64, log=lambda *_: None) is None


# ------------------------------------------------------------------------------------------ pin-change guard
def _guard():
    spec = importlib.util.spec_from_file_location("check_pin_changes", REPO / "scripts" / "check_pin_changes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_pin_guard_accepts_reviewed_repin_and_rejects_silent_changes():
    g = _guard()
    base = {"sources": [{"source_id": "a", "url": "u", "sha256": "1" * 64, "content_sha256": None}]}
    assert g.check(base, base) == []
    silent = {"sources": [{**base["sources"][0], "sha256": "2" * 64}]}
    assert any("without exactly one new `superseded` entry" in p for p in g.check(base, silent))
    rec = {"sha256": "1" * 64, "new_sha256": "2" * 64, "reason": "r", "publisher_revision": "v2", "approved_by": "rev"}
    reviewed = {"sources": [{**silent["sources"][0], "superseded": [rec]}]}
    assert g.check(base, reviewed) == []
    unapproved = {"sources": [{**silent["sources"][0], "superseded": [{**rec, "approved_by": ""}]}]}
    assert any("lacks `approved_by`" in p for p in g.check(base, unapproved))
    added = {"sources": base["sources"] + [{"source_id": "b", "url": "v", "sha256": "3" * 64}]}
    assert any("added to the selection" in p for p in g.check(base, added))
    edited = {"sources": [{**base["sources"][0], "superseded": [rec]}]}
    assert any("history edited" in p for p in g.check(base, edited))


def test_missing_weather_is_explained_by_source_status():
    """Fail-closed answers say why data is missing: a revised or unavailable pinned source, never a substitute."""
    from types import SimpleNamespace

    from nem_agent.tools.impl import _source_gap_note

    srcs = [SimpleNamespace(source_id="nasa_power_sa1_x", dataset="NASA_POWER_HOURLY", events=["SA1-20260731T0235-hi"]),
            SimpleNamespace(source_id="nasa_power_vic1_x", dataset="NASA_POWER_HOURLY", events=["VIC1-20260731T0730-hi"])]
    ctx = SimpleNamespace(selection=SimpleNamespace(sources=srcs), store=SimpleNamespace(snapshot={"sources": {
        "nasa_power_sa1_x": {"pin_status": "revised"}, "nasa_power_vic1_x": {"pin_status": "unavailable"}}}))
    note = _source_gap_note(ctx, "NASA_POWER_HOURLY", "SA1")
    assert "nasa_power_sa1_x is revised by the publisher" in note and "no other version is substituted" in note
    assert "vic1" not in note
    ctx.store.snapshot["sources"]["nasa_power_sa1_x"]["pin_status"] = "pinned"
    assert _source_gap_note(ctx, "NASA_POWER_HOURLY", "SA1") == ""
