"""NASA POWER inconsistent responses, through the real HTTP layer (a local test server; no internet).

Observed 2026-09-27: NASA POWER returned values different from the pin to some requests while other requests got the
pinned values. The build accepts only the pinned content (asking again, bounded), the refresh check reports
"inconsistent", and a build restored from the approved-bytes store does not contact NASA at all.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nem_agent import pinstore, rawstore, refresh
from nem_agent.selection import SourceEntry

pytestmark = pytest.mark.synthetic
PINNED = {"header": {"api": {"version": "v2.10.2"}, "sources": ["MERRA2"]},
          "properties": {"parameter": {"T2M": {"2026073000": 10.0, "2026073001": 11.0}}}}
VARIANT = {**PINNED, "properties": {"parameter": {"T2M": {"2026073000": 10.3, "2026073001": 11.0}}}}


def body(doc, t):
    return json.dumps({**doc, "times": {"data": t}}).encode()  # volatile timing differs on every response


@pytest.fixture
def server():
    state = {"plan": [], "hits": 0}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            i = state["hits"]
            state["hits"] += 1
            doc = state["plan"][min(i, len(state["plan"]) - 1)]
            b = body(doc, 0.1 + i)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/api/temporal/hourly/point?start=20260730"
    yield state
    srv.shutdown()


def pins():
    b = body(PINNED, 0.0)
    return hashlib.sha256(b).hexdigest(), rawstore.content_sha256("NASA_POWER_HOURLY", b)


def test_variant_then_pinned_is_accepted_only_as_the_pinned_content(server, synthetic_home, monkeypatch):
    monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)
    server["plan"] = [VARIANT, PINNED]
    raw, content = pins()
    rf = rawstore.get("NASA_POWER_HOURLY", server["url"], expected_sha256=raw, expected_content_sha256=content)
    assert rf.status == "downloaded" and server["hits"] == 2
    stored = rawstore.local_path_for("NASA_POWER_HOURLY", server["url"]).read_bytes()
    assert rawstore.content_sha256("NASA_POWER_HOURLY", stored) == content
    kept = synthetic_home / "data" / "raw" / "_rejected" / "NASA_POWER_HOURLY"
    assert (kept / f"{rawstore.content_sha256('NASA_POWER_HOURLY', body(VARIANT, 0))}.bin").exists()


def test_every_response_different_is_refused(server, synthetic_home, monkeypatch):
    monkeypatch.setattr(rawstore, "MISMATCH_RETRY_WAIT_S", 0)
    server["plan"] = [VARIANT]
    raw, content = pins()
    rf = rawstore.get("NASA_POWER_HOURLY", server["url"], expected_sha256=raw, expected_content_sha256=content)
    assert rf.status == "failed" and rf.pin_status == "revised" and server["hits"] == 3
    assert not rawstore.local_path_for("NASA_POWER_HOURLY", server["url"]).exists()


def test_refresh_check_reports_inconsistent(server, synthetic_home):
    server["plan"] = [VARIANT, PINNED, VARIANT]
    raw, content = pins()
    src = SourceEntry.model_construct(source_id="nasa_test", dataset="NASA_POWER_HOURLY", url=server["url"],
                                      sha256=raw, content_sha256=content, size=100, retrieved_at="t",
                                      last_modified=None, events=[], superseded=[])
    row = refresh.check_source(src, synthetic_home / "staging", [])
    assert row["result"] == "inconsistent" and row["note"] == "1 of 3 responses matched the pin"
    assert row["variants_seen"] == [rawstore.content_sha256("NASA_POWER_HOURLY", body(VARIANT, 0))]


def test_store_restored_build_does_not_contact_nasa(server, synthetic_home, tmp_path):
    server["plan"] = [VARIANT]
    raw, content = pins()
    data = body(PINNED, 7.0)
    src = SourceEntry.model_construct(source_id="nasa_test", dataset="NASA_POWER_HOURLY", url=server["url"],
                                      sha256=raw, content_sha256=content, size=len(data), retrieved_at="t",
                                      last_modified=None, events=[], superseded=[])
    store = pinstore.LocalDirBackend(tmp_path / "store")
    h = hashlib.sha256(data).hexdigest()
    store.put(h, data)
    idx = {"objects": [{"sha256": h, "size": len(data), "source_id": "nasa_test", "status": "current",
                        "pin": {"kind": "content_sha256", "value": content}, "retrieved_at": "t", "release": "T"}]}
    sel = type("Sel", (), {"sources": [src]})()
    rep = pinstore.restore(sel, index=idx, backend=store, strict=True, log=lambda *_: None)
    assert rep["ok"] and rep["restored"] == ["nasa_test"]
    rf = rawstore.get("NASA_POWER_HOURLY", server["url"], expected_sha256=raw, expected_content_sha256=content)
    assert rf.status == "cache_hit" and server["hits"] == 0  # NASA's inconsistency cannot reach a pinned build
