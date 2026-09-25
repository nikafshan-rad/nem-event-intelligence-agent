"""Rolling retention: simulated 404s and recovery of rolled-off Current files from NEMWeb Archive bundles."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from nem_agent import rawstore
from nem_agent.http import fetch
from nem_agent.recover import extract_verified_member, recover_from_archive
from tests.helpers import zip_bytes


@pytest.mark.synthetic
def test_extract_member_requires_matching_checksum():
    member = zip_bytes({"PUBLIC_X_20990101_20990102044000.CSV": b"SYNTHETIC"})
    outer = zip_bytes({"PUBLIC_X_20990101_20990102044000.zip": member, "other.zip": zip_bytes({"a.CSV": b"x"})})
    good = hashlib.sha256(member).hexdigest()
    assert extract_verified_member(outer, "PUBLIC_X_20990101_20990102044000.zip", good) == member
    assert extract_verified_member(outer, "PUBLIC_X_20990101_20990102044000.zip", "0" * 64) is None


def test_simulation_switch_only_affects_nemweb_current(monkeypatch):
    monkeypatch.setenv("NEM_AGENT_SIMULATE_ROLLED_OFF", "1")
    r = fetch("https://nemweb.com.au/Reports/CURRENT/Market_Notice/NEMITWEB1_MKTNOTICE_20260730.R144692")
    assert r.status == 404 and "SIMULATED" in (r.error or "") and r.attempts == 0


@pytest.mark.network
def test_real_rolled_off_file_is_recovered_from_archive(selection, synthetic_home):
    """A July next-day file that has really left NEMWeb Current is recovered, byte-identical, from the archive."""
    if os.environ.get("NEM_OFFLINE") == "1":
        pytest.skip("offline")
    real_home = Path(__file__).resolve().parents[2]
    src = next(s for s in selection.sources if s.source_id == "opdem_actual_daily_20260701")
    cached = real_home / "data" / "raw" / "OPDEM_ACTUAL_DAILY" / Path(src.url).name
    if not cached.exists():
        pytest.skip("July monthly archive not cached")
    with zipfile.ZipFile(cached) as zf:
        name = next(n for n in zf.namelist() if "_DAILY_20260710_" in n)
        data = zf.read(name)
    url = f"https://nemweb.com.au/Reports/CURRENT/Operational_Demand/ACTUAL_DAILY/{Path(name).name}"
    sha = hashlib.sha256(data).hexdigest()
    rf = rawstore.get("OPDEM_ACTUAL_DAILY", url, expected_sha256=sha)
    assert rf.rolled_off, "file expected to have rolled off NEMWeb Current already"
    rec = recover_from_archive("OPDEM_ACTUAL_DAILY", url, sha, log=lambda *_: None)
    assert rec is not None and rec.status == "recovered_from_archive"
    assert rawstore.sha256_file(Path(rec.local_path)) == sha
