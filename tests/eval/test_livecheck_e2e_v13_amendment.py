"""Amendment 1 to the review kit of the end-to-end Live check of v13 request resolution
(eval/livecheck_e2e_v13/AMENDMENT_1.md, kit_amended.py), offline. Nothing here calls a model or changes a record.

An observed item with no item-level publication or availability time takes the actual times of its exact source rows
in the pinned store, each row's identity verified, every row keeping its own times. Where the rows cannot be
identified, the kit still refuses. The frozen kit.py is unchanged.

The two reproductions are the run's own evidence items, copied verbatim from its records (D01 ev0723, F06 ev0438);
their source rows are read from the real pinned store. The other variants use a SYNTHETIC store."""

from __future__ import annotations

import copy
import difflib
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "eval" / "livecheck_e2e_v13"
RUN = ROOT / "artifacts" / "live" / "LC-e2e-v13-run"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"lce2e_amend_{name}", DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KIT = _load("kit")
AMENDED = _load("kit_amended")
FREEZE = json.loads((DIR / "FREEZE.json").read_text())
NETX = "DISPATCHREGIONSUM.NETINTERCHANGE ('Net interconnector flow from the regional reference node')"
# copied verbatim from the run's records: the two items the frozen kit refused for want of item-level times
D01_ITEM = {"evidence_id": "ev0723", "evidence_class": "observed", "metric": "dispatch_netinterchange",
            "value": -1499.18, "unit": "MW", "region": "NSW1", "valid_at_utc": "2026-07-29T10:05:00Z",
            "interval_minutes": 5, "source_row_ids": ["DISPATCHIS:PUBLIC_DISPATCHIS_202607292005_0000000529900364:L27"],
            "source_urls": ["https://nemweb.com.au/Reports/ARCHIVE/DispatchIS_Reports/PUBLIC_DISPATCHIS_20260729.zip"],
            "tool_call_id": "call_3VlYoDulRu5vUqtTPSWZiXj5", "published_at_utc": None, "available_at_utc": None,
            "derivation": None, "label": NETX}
F06_ITEM = {"evidence_id": "ev0438", "evidence_class": "observed", "metric": "dispatch_netinterchange",
            "value": -718.24, "unit": "MW", "region": "VIC1", "valid_at_utc": "2026-08-19T23:10:00Z",
            "interval_minutes": 5, "source_row_ids": ["DISPATCHIS:PUBLIC_DISPATCHIS_202608200910_0000000533535901:L55"],
            "source_urls": ["https://nemweb.com.au/Reports/ARCHIVE/DispatchIS_Reports/PUBLIC_DISPATCHIS_20260820.zip"],
            "tool_call_id": "call_oAEMVao2Bb5kb4gc0gy3x2JW", "published_at_utc": None, "available_at_utc": None,
            "derivation": None, "label": NETX}
# a complete item from the same run (D01 ev0704), for the unchanged control
COMPLETE_ITEM = {"evidence_id": "ev0704", "evidence_class": "observed", "metric": "dispatch_totaldemand",
                 "value": 10890.3, "unit": "MW", "region": "NSW1", "valid_at_utc": "2026-07-29T09:35:00Z",
                 "interval_minutes": 5,
                 "source_row_ids": ["DISPATCHIS:PUBLIC_DISPATCHIS_202607291935_0000000529897139:L27"],
                 "source_urls": ["https://nemweb.com.au/Reports/ARCHIVE/DispatchIS_Reports/PUBLIC_DISPATCHIS_20260729.zip"],
                 "tool_call_id": "call_3VlYoDulRu5vUqtTPSWZiXj5", "published_at_utc": "2026-07-29T09:30:09Z",
                 "available_at_utc": "2026-07-29T10:23:09Z", "derivation": None,
                 "label": "DISPATCHREGIONSUM.TOTALDEMAND ('Demand (less loads)'); not operational demand"}


def _obs(item: dict) -> dict:
    return {k: item[k] for k in ("metric", "value", "unit", "valid_at_utc", "interval_minutes", "evidence_id",
                                 "source_row_ids", "evidence_class", "label")} | {"valid_at_local": "local"}


def _rec(*items: dict, cutoff: str | None = None) -> dict:
    return {"request": {"as_of_utc": cutoff} if cutoff else {},
            "report": {"observations": [_obs(i) for i in items], "results": [], "numeric_claims": [], "citations": [],
                       "answer": []},
            "evidence": {i["evidence_id"]: i for i in items}, "cited_passages": {}}


class Store:
    """SYNTHETIC pinned store: rows by table, answering the two queries the kits make."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]):
        self.rows = rows

    def has_rows(self, table: str) -> bool:
        return bool(self.rows.get(table))

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        table = re.search(r"FROM (\w+)", sql).group(1)  # type: ignore[union-attr]
        return [dict(r) for r in self.rows.get(table, []) if r["row_id"] == (params or [None])[0]]

    def row(self, row_id: str) -> dict[str, Any] | None:
        for t, rows in self.rows.items():
            for r in rows:
                if r["row_id"] == row_id:
                    return {"table": t, **r}
        return None


def _od_row(rid: str, published: str, available: str, value: float = 500.0, end: str = "2026-01-01T00:30:00Z") -> dict:
    return {"row_id": rid, "region": "SA1", "interval_end_utc": end, "operational_demand_mw": value,
            "published_at_utc": published, "available_at_utc": available, "source_url": "u", "member": "m"}


OD_ITEM = {"evidence_id": "ev0001", "evidence_class": "observed", "metric": "opdemand_actual", "value": 500.0,
           "unit": "MW", "region": "SA1", "valid_at_utc": "2026-01-01T00:30:00Z", "interval_minutes": 30,
           "source_row_ids": ["a", "b"], "source_urls": ["u"], "tool_call_id": "t", "published_at_utc": None,
           "available_at_utc": None, "derivation": None, "label": "SYNTHETIC operational demand"}


# ------------------------------------------------------------------------------------------------ the frozen kit
def test_the_frozen_kit_is_unchanged_and_the_recorded_diff_is_exact():
    rel = "eval/livecheck_e2e_v13/kit.py"
    assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == FREEZE["files_sha256"][rel]
    diff = "".join(difflib.unified_diff((DIR / "kit.py").read_text().splitlines(keepends=True),
                                        (DIR / "kit_amended.py").read_text().splitlines(keepends=True),
                                        "eval/livecheck_e2e_v13/kit.py", "eval/livecheck_e2e_v13/kit_amended.py"))
    record = (DIR / "AMENDMENT_1.md").read_text()
    assert f"```diff\n{diff}```" in record


# ------------------------------------------------------------------------------------------------ the two reproductions
@pytest.mark.parametrize("item,times", [
    (D01_ITEM, ("2026-07-29T10:00:13Z", "2026-07-29T10:53:13Z")),
    (F06_ITEM, ("2026-08-19T23:05:08Z", "2026-08-19T23:58:08Z")),
])
def test_the_two_reproductions_take_their_exact_source_rows_times(item, times, real_store):
    rec = _rec(item)
    frozen = KIT.evidence_view(rec, real_store)
    assert any("no publication or availability time" in p for p in KIT.missing(frozen))  # the frozen kit refuses
    view = AMENDED.evidence_view(rec, real_store)
    assert AMENDED.missing(view) == []
    a = view["observations"][0]["availability"]
    assert (a["published_at_utc"], a["available_at_utc"], a["item_times_recorded"]) == (None, None, False)
    fr = a["from_source_rows"]
    assert fr["label"] == "from pinned source rows; not recorded on the evidence item"
    assert fr["identity_failures"] == [] and not fr["rows_differ"]
    (row,) = fr["rows"]
    assert row["row_id"] == item["source_row_ids"][0] and row["identity_verified"]
    assert (row["table"], row["region"], row["interval_end_utc"], row["value_column"], row["value"]) == (
        "regionsum_5min", item["region"], item["valid_at_utc"], "netinterchange_mw", item["value"])
    assert (row["published_at_utc"], row["available_at_utc"]) == times
    assert AMENDED._rows_with_id(real_store, row["row_id"])[0]["table"] == "regionsum_5min"
    assert len(AMENDED._rows_with_id(real_store, row["row_id"])) == 1  # the row ID names exactly one row
    assert rec["evidence"][item["evidence_id"]] == item  # nothing is written back to the record


# ------------------------------------------------------------------------------------------------ differing row times
def test_differing_row_times_are_kept_per_row_and_never_collapsed():
    """SYNTHETIC: two source rows of one item (two revisions of the same value), published at different times."""
    store = Store({"opdemand_actual": [_od_row("a", "2026-01-01T03:00:00Z", "2026-01-01T03:10:00Z"),
                                       _od_row("b", "2026-01-02T03:00:00Z", "2026-01-02T03:10:00Z")]})
    view = AMENDED.evidence_view(_rec(OD_ITEM), store)
    a = view["observations"][0]["availability"]
    fr = a["from_source_rows"]
    assert fr["rows_differ"] and [(r["row_id"], r["published_at_utc"], r["available_at_utc"]) for r in fr["rows"]] == [
        ("a", "2026-01-01T03:00:00Z", "2026-01-01T03:10:00Z"), ("b", "2026-01-02T03:00:00Z", "2026-01-02T03:10:00Z")]
    assert (a["published_at_utc"], a["available_at_utc"]) == (None, None)  # no single time inferred for the item
    assert AMENDED.missing(view) == []
    cut = AMENDED.evidence_view(_rec(OD_ITEM, cutoff="2026-01-01T12:00:00Z"), store)
    a = cut["observations"][0]["availability"]
    assert a["available_by_cutoff"] is None  # never collapsed: each row says for itself
    assert [r["available_by_cutoff"] for r in a["from_source_rows"]["rows"]] == [True, False]
    assert AMENDED.missing(cut) == []


# ------------------------------------------------------------------------------------------------ missing source rows
@pytest.mark.parametrize("label,rows,item,expect", [
    ("a source row missing from the store", {"opdemand_actual": [_od_row("a", "2026-01-01T03:00:00Z",
                                                                         "2026-01-01T03:10:00Z")]},
     OD_ITEM, "b: 0 rows with this ID"),
    ("a row ID naming two rows", {"opdemand_actual": [_od_row("a", "2026-01-01T03:00:00Z", "2026-01-01T03:10:00Z")] * 2
                                  + [_od_row("b", "2026-01-01T03:00:00Z", "2026-01-01T03:10:00Z")]},
     OD_ITEM, "a: 2 rows with this ID"),
    ("a row whose value differs", {"opdemand_actual": [_od_row("a", "x", "y", value=501.0),
                                                       _od_row("b", "x", "y")]}, OD_ITEM, "value 501.0"),
    ("a row whose interval differs", {"opdemand_actual": [_od_row("a", "x", "y", end="2026-01-01T01:00:00Z"),
                                                          _od_row("b", "x", "y")]}, OD_ITEM, "interval_end_utc"),
    ("a row in another table", {"price_5min": [_od_row("a", "x", "y")],
                                "opdemand_actual": [_od_row("b", "x", "y")]}, OD_ITEM, "table 'price_5min'"),
    ("a metric with no exact row identity", {}, dict(OD_ITEM, metric="weather_t2m"), "no exact row identity"),
    ("an item naming no source rows", {}, dict(OD_ITEM, source_row_ids=[]), "names no source rows"),
])
def test_rows_that_cannot_be_identified_keep_the_refusal(label, rows, item, expect):
    """SYNTHETIC: the refusal stays whenever a row cannot be identified reliably."""
    store = Store(rows)
    probs = AMENDED.missing(AMENDED.evidence_view(_rec(item), store))
    assert any(expect in p for p in probs), (label, probs)
    case = {"case_id": "X01", "e2e_group": "answerable", "question": "q", "expected": {}}
    gold = {"X01": {"reading": None, "result": None, "copied_from": {"maxima": None}, "maxima_gold": None}}
    with pytest.raises(AMENDED.IncompleteKit, match="X01"):
        AMENDED.build([case], gold, {"X01": _rec(item)}, {"A01": "X01"}, store)


def test_a_source_row_without_its_own_times_keeps_the_refusal():
    """SYNTHETIC: the row is identified, but the store holds no time for it."""
    store = Store({"opdemand_actual": [_od_row("a", None, None), _od_row("b", "x", "y")]})  # type: ignore[arg-type]
    probs = AMENDED.missing(AMENDED.evidence_view(_rec(OD_ITEM), store))
    assert any("source row a has no publication or availability time" in p for p in probs)


# ------------------------------------------------------------------------------------------------ unchanged evidence
def test_complete_evidence_is_unchanged(real_store):
    rec = _rec(COMPLETE_ITEM, cutoff=None)
    assert AMENDED.evidence_view(rec, real_store) == KIT.evidence_view(rec, real_store)
    assert AMENDED.missing(AMENDED.evidence_view(rec, real_store)) == []
    cut = _rec(COMPLETE_ITEM, cutoff="2026-07-29T10:00:00Z")
    assert AMENDED.evidence_view(cut, real_store) == KIT.evidence_view(cut, real_store)
    derived = dict(COMPLETE_ITEM, evidence_class="derived", published_at_utc=None, available_at_utc=None,
                   derivation="SYNTHETIC mean of registered items")
    assert AMENDED.evidence_view(_rec(derived), real_store) == KIT.evidence_view(_rec(derived), real_store)


@pytest.mark.skipif(not (RUN / "D01.json").exists(), reason="the run's records are not in this checkout")
def test_on_the_run_records_only_the_two_observations_change_and_no_record_is_written(real_store):
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RUN.glob("*.json")}
    changed = []
    for p in sorted(RUN.glob("*.json")):
        rec = json.loads(p.read_text())
        frozen, amended = KIT.evidence_view(rec, real_store), AMENDED.evidence_view(rec, real_store)
        assert AMENDED.missing(amended) == [], p.name
        for o, o2 in zip(frozen["observations"], amended["observations"], strict=True):
            if o != o2:
                assert o2["availability"]["from_source_rows"]["label"] == AMENDED.FROM_ROWS
                assert {k: v for k, v in o2.items() if k != "availability"} == {
                    k: v for k, v in o.items() if k != "availability"}
                changed.append((p.stem, o["evidence_id"]))
        rest = copy.deepcopy(amended)
        rest["observations"] = frozen["observations"]
        assert rest == frozen, p.name  # everything else in the packet is the frozen kit's
    assert changed == [("D01", "ev0723"), ("F06", "ev0438")]
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RUN.glob("*.json")} == before
