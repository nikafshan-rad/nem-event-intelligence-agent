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
    rf = rawstore.get("NASA_POWER_HOURLY", url, expected_sha256=hashlib.sha256(recorded).hexdigest(),
                      expected_content_sha256=rawstore.content_sha256("NASA_POWER_HOURLY", recorded))
    assert rf.status == "failed" and not rawstore.local_path_for("NASA_POWER_HOURLY", url).exists()
    assert rawstore.content_sha256("NASA_POWER_HOURLY", revised) in rf.error
    assert "values changed" in rf.error and "scripts/repin_source.py" in rf.error
