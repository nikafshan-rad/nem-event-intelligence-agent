"""AEMO MMS CSV parser contract (SYNTHETIC fixtures in AEMO format; no real observations)."""

import pytest

from nem_agent.mmscsv import MmsFormatError, SchemaDriftError, iter_csv_members, parse_mms_csv, require_fields
from tests.helpers import mms_csv, zip_bytes

pytestmark = pytest.mark.synthetic
FIELDS = ["REGIONID", "INTERVAL_DATETIME", "LOAD_DATE", "OPERATIONAL_DEMAND_POE10", "OPERATIONAL_DEMAND_POE50",
          "OPERATIONAL_DEMAND_POE90", "LASTCHANGED"]
ROW = ["SA1", '"2099/01/01 00:30:00"', '"2099/01/01 00:00:00"', "10", "9", "8", '"2099/01/01 00:00:00"']


def test_valid_file_parses_with_line_numbers():
    mf, recs = parse_mms_csv(mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW, ROW]), "x.CSV")
    assert mf.report_name == "OPERATIONAL_DEMAND_FORECAST"
    assert [r.line_no for r in recs] == [3, 4]
    assert recs[0].values["OPERATIONAL_DEMAND_POE50"] == "9"
    assert mf.created_at_utc.isoformat() == "2098-12-31T14:00:00+00:00"  # 00:00 NEM time = 14:00Z previous day


def test_truncated_file_without_trailer_is_rejected():
    with pytest.raises(MmsFormatError, match="END OF REPORT"):
        parse_mms_csv(mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW], trailer=False), "x.CSV")


def test_line_count_mismatch_is_rejected():
    with pytest.raises(MmsFormatError, match="END OF REPORT says"):
        parse_mms_csv(mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW], declared_lines=99), "x.CSV")


def test_field_count_mismatch_is_rejected():
    with pytest.raises(MmsFormatError, match="values but table"):
        parse_mms_csv(mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW[:-2]]), "x.CSV")


def test_undeclared_table_is_rejected():
    data = mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW]).replace(b"D,OPERATIONAL_DEMAND,FORECAST",
                                                                                b"D,OPERATIONAL_DEMAND,ACTUAL")
    with pytest.raises(MmsFormatError, match="undeclared"):
        parse_mms_csv(data, "x.CSV")


def test_schema_drift_missing_required_field():
    drifted = [f for f in FIELDS if f != "OPERATIONAL_DEMAND_POE50"]
    row = [v for f, v in zip(FIELDS, ROW, strict=True) if f != "OPERATIONAL_DEMAND_POE50"]
    mf, _ = parse_mms_csv(mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", drifted, [row]), "x.CSV")
    with pytest.raises(SchemaDriftError, match="OPERATIONAL_DEMAND_POE50"):
        require_fields(mf, "OPERATIONAL_DEMAND", "FORECAST", ["REGIONID", "OPERATIONAL_DEMAND_POE50"])


def test_nested_archive_members_are_walked():
    inner = zip_bytes({"A.CSV": mms_csv("OPERATIONAL_DEMAND", "FORECAST", "1", FIELDS, [ROW])})
    outer = zip_bytes({"A.zip": inner, "B.zip": inner})
    members = list(iter_csv_members(outer, "outer.zip"))
    assert [m for m, _ in members] == ["A.zip/A.CSV", "B.zip/A.CSV"]


def test_bad_zip_is_rejected():
    with pytest.raises(MmsFormatError, match="not a valid zip"):
        list(iter_csv_members(b"<html>Sorry, your request has failed</html>", "x.zip"))
