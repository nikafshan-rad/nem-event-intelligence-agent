"""Change detection for publisher schema drift (the parser must fail loudly, never guess columns)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nem_agent import rawstore
from nem_agent.aemo_schema import CONTRACTS
from nem_agent.mmscsv import SchemaDriftError, iter_csv_members, parse_mms_csv, require_fields
from tests.helpers import mms_multi, zip_bytes


def test_recorded_probe_schemas_contain_every_contract_field(selection):
    """The probe recorded the headers it saw; each must still satisfy the project's contract."""
    for s in selection.sources:
        if s.dataset not in CONTRACTS or not s.schema_fields:
            continue
        for c in CONTRACTS[s.dataset]:
            keys = [k for k in s.schema_fields if k.startswith(f"{c.report}/{c.subtype}/")]
            assert keys, (s.source_id, c.report, c.subtype)
            assert set(c.required) <= set(s.schema_fields[keys[-1]]), (s.source_id, keys[-1])


def test_cached_files_still_match_recorded_headers(selection):
    """Detects a publisher re-issuing a file with different columns than the probe recorded."""
    checked = 0
    for s in selection.sources:
        if s.dataset not in ("OPDEM_FORECAST_HH", "OPDEM_ACTUAL_HH", "MMSDM_DUDETAILSUMMARY") or not s.schema_fields:
            continue
        p = rawstore.local_path_for(s.dataset, s.url)
        if not p.exists():
            continue
        mp, csvb = next(iter_csv_members(p.read_bytes(), Path(p).name))
        mf, _ = parse_mms_csv(csvb, mp, line_prefixes=())
        for key, fields in mf.tables.items():
            recorded = s.schema_fields.get(f"{key[0]}/{key[1]}/v{key[2]}")
            if recorded is not None:
                assert fields == recorded, f"schema drift in {s.source_id} {key}: {set(fields) ^ set(recorded)}"
                checked += 1
    if checked == 0:
        pytest.skip("no cached raw files to compare")


@pytest.mark.synthetic
def test_renamed_price_column_is_detected():
    t = '"2099/01/01 00:05:00"'
    drifted = mms_multi("DISPATCHIS", [("DISPATCH", "PRICE", "6", ["SETTLEMENTDATE", "RUNNO", "REGIONID", "INTERVENTION",
                                                                   "RRP_NEW", "ROP", "PRICE_STATUS"],
                                        [[t, "1", "SA1", "0", "100", "100", "FIRM"]])])
    mp, csvb = next(iter_csv_members(zip_bytes({"x.zip": zip_bytes({"x.CSV": drifted})}), "outer.zip"))
    mf, _ = parse_mms_csv(csvb, mp)
    with pytest.raises(SchemaDriftError, match="RRP"):
        require_fields(mf, "DISPATCH", "PRICE", CONTRACTS["DISPATCHIS"][0].required)
