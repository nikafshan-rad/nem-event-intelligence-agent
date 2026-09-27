"""Raw-cache identity: byte identity for publisher files; canonical content identity for volatile API responses."""

from __future__ import annotations

import hashlib
import json

import pytest

from nem_agent import rawstore
from tests.helpers import plant_cache

pytestmark = pytest.mark.synthetic
DOC = {"header": {"api": {"version": "v2.x"}}, "properties": {"parameter": {"T2M": {"2099010100": 12.5}}},
       "times": {"data": 0.349, "process": 0.01}}


def _bytes(doc):
    return json.dumps(doc).encode()


def test_volatile_times_do_not_change_content_hash():
    a = _bytes(DOC)
    b = _bytes({**DOC, "times": {"data": 0.258, "process": 0.02}})
    c = _bytes({**DOC, "properties": {"parameter": {"T2M": {"2099010100": 13.0}}}})
    assert hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest()
    assert rawstore.content_sha256("NASA_POWER_HOURLY", a) == rawstore.content_sha256("NASA_POWER_HOURLY", b)
    assert rawstore.content_sha256("NASA_POWER_HOURLY", a) != rawstore.content_sha256("NASA_POWER_HOURLY", c)
    assert rawstore.content_sha256("DISPATCHIS", a) is None  # publisher files keep strict byte identity


def test_cache_accepts_same_values_and_rejects_changed_values(synthetic_home):
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point?SYNTHETIC=1"
    recorded = _bytes(DOC)
    expected_raw = hashlib.sha256(recorded).hexdigest()
    expected_content = rawstore.content_sha256("NASA_POWER_HOURLY", recorded)
    plant_cache(synthetic_home, "NASA_POWER_HOURLY", url, _bytes({**DOC, "times": {"data": 9.9}}))
    rf = rawstore.get("NASA_POWER_HOURLY", url, expected_sha256=expected_raw, expected_content_sha256=expected_content)
    assert rf.status == "cache_hit"
    plant_cache(synthetic_home, "NASA_POWER_HOURLY", url,
                _bytes({**DOC, "properties": {"parameter": {"T2M": {"2099010100": 99.0}}}}))
    assert not rawstore._matches("NASA_POWER_HOURLY", "x", rawstore.local_path_for("NASA_POWER_HOURLY", url).read_bytes(),
                                 expected_raw, expected_content)


def test_changed_api_values_fail_with_the_content_hash_named(synthetic_home, monkeypatch):
    """A revised API response is refused, and the error says the values changed (raw bytes always differ)."""
    from nem_agent.http import HttpResult

    url = "https://power.larc.nasa.gov/api/temporal/hourly/point?SYNTHETIC=2"
    recorded = _bytes(DOC)
    revised = _bytes({**DOC, "properties": {"parameter": {"T2M": {"2099010100": 14.1}}}})
    monkeypatch.setattr(rawstore, "fetch", lambda *a, **k: HttpResult(url=url, status=200, body=revised))
    monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)
    rf = rawstore.get("NASA_POWER_HOURLY", url, expected_sha256=hashlib.sha256(recorded).hexdigest(),
                      expected_content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", recorded))
    assert rf.status == "failed" and not rawstore.local_path_for("NASA_POWER_HOURLY", url).exists()
    assert rawstore.content_sha256("NASA_POWER_HOURLY", revised) in rf.error
    assert "values changed" in rf.error and "scripts/repin_source.py" in rf.error


def _serve(monkeypatch, url, bodies):
    from nem_agent.http import HttpResult

    calls = []

    def fetch(*a, **k):
        calls.append(1)
        return HttpResult(url=url, status=200, body=bodies[min(len(calls), len(bodies)) - 1])

    monkeypatch.setattr(rawstore, "fetch", fetch)
    monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)
    return calls


def test_inconsistent_api_server_is_asked_again_and_only_the_pin_is_accepted(synthetic_home, monkeypatch):
    """NASA POWER served other values to some requests (CI, 2026-09-27); the pinned content is accepted, nothing else."""
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point?SYNTHETIC=3"
    pinned = _bytes(DOC)
    variant = _bytes({**DOC, "properties": {"parameter": {"T2M": {"2099010100": 12.9}}}})
    calls = _serve(monkeypatch, url, [variant, _bytes({**DOC, "times": {"data": 0.1}})])
    rf = rawstore.get("NASA_POWER_HOURLY", url, expected_sha256=hashlib.sha256(pinned).hexdigest(),
                      expected_content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", pinned))
    assert rf.status == "downloaded" and len(calls) == 2
    stored = rawstore.local_path_for("NASA_POWER_HOURLY", url).read_bytes()
    assert rawstore.content_sha256("NASA_POWER_HOURLY", stored) == rawstore.content_sha256("NASA_POWER_HOURLY", pinned)
    kept = synthetic_home / "data" / "raw" / "_rejected" / "NASA_POWER_HOURLY"
    assert (kept / f"{rawstore.content_sha256('NASA_POWER_HOURLY', variant)}.bin").read_bytes() == variant
    events = [json.loads(ln) for ln in rawstore.paths.manifest_path().read_text().splitlines()]
    assert any(e["event"] == "checksum_mismatch_variants" and e["accepted_after_attempts"] == 2 for e in events)


def test_every_response_different_is_still_refused(synthetic_home, monkeypatch):
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point?SYNTHETIC=4"
    pinned = _bytes(DOC)
    variant = _bytes({**DOC, "properties": {"parameter": {"T2M": {"2099010100": 15.0}}}})
    calls = _serve(monkeypatch, url, [variant])
    rf = rawstore.get("NASA_POWER_HOURLY", url, expected_sha256=hashlib.sha256(pinned).hexdigest(),
                      expected_content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", pinned))
    assert rf.status == "failed" and len(calls) == 1 + rawstore.MISMATCH_RETRIES["NASA_POWER_HOURLY"]
    assert "3 attempts" in rf.error and not rawstore.local_path_for("NASA_POWER_HOURLY", url).exists()


def test_publisher_files_are_not_retried(synthetic_home, monkeypatch):
    url = "https://nemweb.com.au/Reports/Archive/SYNTHETIC/x.zip"
    calls = _serve(monkeypatch, url, [b"PK other bytes"])
    rf = rawstore.get("DISPATCHIS", url, expected_sha256="0" * 64)
    assert rf.status == "failed" and len(calls) == 1
