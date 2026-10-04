# Amendment 1 to the review kit (disclosed; after the run)

**What this changes:** only the review packet of the end-to-end Live acceptance check of v13 request resolution.

**What it does not change:**
- the frozen `kit.py`: it is not modified, and its SHA-256 is still `30544278990c0cfe8502fb8388287b82cad5cdcb3faac314a0a14143d5aff8fa`, as frozen in `FREEZE.json`;
- `PROTOCOL.md`, `FREEZE.json` and `REVIEW_BRIEF.md`;
- the cases, gold, criteria, verdict rules and scorer (`score.py`);
- the run's records.

**Approval:** the owner, on 2026-10-04, after the paid run. The final assessment uses this disclosed amended review
kit. It is not the original protocol unchanged.

## Timing
- **2026-10-04T02:44:39Z:** the run ended, complete, with 8 of 8 cases saved. Its records are unchanged since.
- **About 02:45:00Z:** the frozen `score.py --measures` ran. The frozen `score.py --sheet`, which calls the frozen
  `kit.py`, then refused to write the sheets.
- **After that:** the refusal was reported to the owner, who approved this amendment only.
- **2026-10-04T02:52:06Z:** this record and `kit_amended.py` were written. No review had begun.

## Reason
The frozen kit refuses a packet in which any shown observation lacks its publication or availability time. Two
observations of the run lack them at item level. Both are dispatch net interchange from `get_price_timeline`:

| Case | Evidence | Source row (pinned store, `regionsum_5min`) | Published (UTC) | Available (UTC) |
| --- | --- | --- | --- | --- |
| D01 | `ev0723`, NSW1, −1,499.18 MW, interval ending 2026-07-29T10:05Z | `DISPATCHIS:PUBLIC_DISPATCHIS_202607292005_0000000529900364:L27` | 2026-07-29T10:00:13Z | 2026-07-29T10:53:13Z |
| F06 | `ev0438`, VIC1, −718.24 MW, interval ending 2026-08-19T23:10Z | `DISPATCHIS:PUBLIC_DISPATCHIS_202608200910_0000000533535901:L55` | 2026-08-19T23:05:08Z | 2026-08-19T23:58:08Z |

**The cause:** the application registers these items without `published_at_utc` and `available_at_utc`
(`src/nem_agent/tools/impl.py`, the `dispatch_netinterchange` item of `get_price_timeline`). Their exact source rows
hold both times.

**A metadata finding, not a safety violation:** it is reported as a finding and is not classified automatically as a
safety violation. Neither case has a cutoff, so neither value's availability at a cutoff is at stake. No application
change is made.

## The amendment (`kit_amended.py`)
**When it applies:** to an observed item that records no publication or availability time of its own. Derived items
and items that carry their times are untouched.

**Its exact source rows** are read from the pinned store, and each row's identity is verified:
- exactly one row in the store has that row ID;
- it is in the item's series table;
- it has the item's region, interval end and value.

**Every row keeps its own times:**
- no single time is inferred for the item;
- differing times are never collapsed;
- under a cutoff, each row says whether it was available by it, and the item-level `available_by_cutoff` stays null.

**Labelled:** "from pinned source rows; not recorded on the evidence item".

**The refusal is kept** when any row cannot be identified reliably:
- the row is missing from the store;
- its ID names more than one row;
- its table, region, interval end or value differs from the item;
- no exact row identity is defined for the metric;
- the item names no source rows;
- an identified row has no time of its own.

**Nothing is written back** to the run's records.

**Packet fields added,** only on such observations:
- `availability.item_times_recorded`: `false`;
- `availability.from_source_rows`:
  - `label`;
  - `rows[]`: `row_id`, `table`, `region`, `interval_end_utc`, `value_column`, `value`, `published_at_utc`,
    `available_at_utc` and `identity_verified`, plus `available_by_cutoff` under a cutoff;
  - `rows_differ`;
  - `identity_failures`;
- `availability.available_by_cutoff` is set to `null` (never inferred).

**Also:** each sheet gains a top-level `kit` note naming this amendment. Every other field of the packet is the frozen
kit's, unchanged.

**How the sheets are built:** by `build_amended_sheets.py`, which replaces only the frozen `score.py --sheet` step.
- the records are found as the frozen scorer finds them (`score.saved`);
- the brief is the frozen `REVIEW_BRIEF.md`;
- the verdict is computed by the unchanged frozen `score.py --review`, with the existing stricter-reading rule.

**Tests:** `tests/eval/test_livecheck_e2e_v13_amendment.py`:
- the two reproductions;
- differing row times;
- missing, duplicated or mismatched rows;
- complete evidence unchanged;
- the frozen kit's hash;
- this diff.

## Diff (`kit.py` → `kit_amended.py`)
```diff
--- eval/livecheck_e2e_v13/kit.py
+++ eval/livecheck_e2e_v13/kit_amended.py
@@ -17,11 +17,18 @@
 - **the gold,** with its sources.
 
 `build` refuses (`IncompleteKit`) when any of these is missing for an item the record holds.
+
+**Amendment 1** (`AMENDMENT_1.md`; approved by the owner on 2026-10-04, after the run; the frozen `kit.py` is unchanged).
+An observed item that records no publication or availability time of its own takes the actual times of its exact
+source rows in the pinned store, each row's identity verified, every row keeping its own times. The evidence is
+labelled "from pinned source rows; not recorded on the evidence item". Where the rows cannot be identified reliably,
+the kit still refuses.
 """
 
 from __future__ import annotations
 
 import copy
+import math
 import sys
 from datetime import datetime
 from pathlib import Path
@@ -31,6 +38,7 @@
 sys.path.insert(0, str(REPO / "src"))
 
 from nem_agent.aemo_schema import METRIC_DEFINITIONS  # noqa: E402
+from nem_agent.ingest import TABLES  # noqa: E402
 from nem_agent.timeutil import iso_utc, local_str, parse_iso  # noqa: E402
 
 AEMO_KEY = {"dispatch_totaldemand": "DISPATCH_TOTALDEMAND", "opdemand_actual": "OPERATIONAL_DEMAND",
@@ -85,6 +93,73 @@
                                     bool(_le(published, cutoff) and _le(available, cutoff)))}
 
 
+# ------------------------------------------------------------------------------------------------ Amendment 1
+FROM_ROWS = "from pinned source rows; not recorded on the evidence item"
+# the series whose rows can be identified exactly: metric -> (table, value column, interval-end column)
+ROW_IDENTITY = {"dispatch_netinterchange": ("regionsum_5min", "netinterchange_mw", "interval_end_utc"),
+                "dispatch_totaldemand": ("regionsum_5min", "totaldemand_mw", "interval_end_utc"),
+                "dispatch_rrp": ("price_5min", "rrp", "interval_end_utc"),
+                "opdemand_actual": ("opdemand_actual", "operational_demand_mw", "interval_end_utc"),
+                **{f"opdemand_forecast_{p}": ("opdemand_forecast", f"{p}_mw", "target_end_utc")
+                   for p in ("poe10", "poe50", "poe90")}}
+
+
+def _rows_with_id(store: Any, row_id: str) -> list[dict[str, Any]]:
+    """Every row of every table with this row ID: an identity is reliable only if there is exactly one."""
+    out: list[dict[str, Any]] = []
+    for t in TABLES:
+        if store.has_rows(t):
+            out += [{"table": t, **r} for r in store.query(f"SELECT * FROM {t} WHERE row_id = ?", [row_id])]
+    return out
+
+
+def _same(k: str, got: Any, want: Any) -> bool:
+    if k == "value" and got is not None and want is not None:
+        return math.isclose(float(got), float(want), rel_tol=0.0, abs_tol=1e-9)
+    return bool(got == want)
+
+
+def source_row_times(item: dict[str, Any], cutoff: str | None, store: Any) -> dict[str, Any]:
+    """The actual times of an observed item's exact source rows, read from the pinned store (Amendment 1).
+
+    Each row's identity is verified: exactly one row has that ID, and it is in the item's series table, with the item's
+    region, interval end and value. Every row keeps its own times. No time is inferred for the item, and differing times
+    are never collapsed. A row that cannot be identified is listed in ``identity_failures``, and the kit then refuses."""
+    spec = ROW_IDENTITY.get(str(item.get("metric")))
+    ids = list(item.get("source_row_ids") or [])
+    rows: list[dict[str, Any]] = []
+    failures = [] if ids else ["the evidence item names no source rows"]
+    if spec is None:
+        failures.append(f"no exact row identity is defined for metric {item.get('metric')!r}")
+        ids = []
+    for rid in ids:
+        assert spec is not None
+        table, col, end = spec
+        found = _rows_with_id(store, rid)
+        if len(found) != 1:
+            failures.append(f"{rid}: {len(found)} rows with this ID in the pinned store, not exactly one")
+            continue
+        r = found[0]
+        checks = {"table": (r["table"], table), "region": (r.get("region"), item.get("region")),
+                  "interval_end_utc": (_t(r.get(end)), item.get("valid_at_utc")), "value": (r.get(col), item.get("value"))}
+        bad = [k for k, (got, want) in checks.items() if not _same(k, got, want)]
+        if bad:
+            failures.append(f"{rid}: identity not verified: " + "; ".join(
+                f"{k} {checks[k][0]!r} in the store, {checks[k][1]!r} on the item" for k in bad))
+            continue
+        row = {"row_id": rid, "table": r["table"], "region": r.get("region"), "interval_end_utc": _t(r.get(end)),
+               "value_column": col, "value": r.get(col), "published_at_utc": _t(r.get("published_at_utc")),
+               "available_at_utc": _t(r.get("available_at_utc")), "identity_verified": True}
+        if cutoff is not None:
+            both = row["published_at_utc"] is not None and row["available_at_utc"] is not None
+            row["available_by_cutoff"] = (bool(_le(row["published_at_utc"], cutoff) and _le(row["available_at_utc"], cutoff))
+                                          if both else None)
+        rows.append(row)
+    return {"label": FROM_ROWS, "rows": rows,
+            "rows_differ": len({(x["published_at_utc"], x["available_at_utc"]) for x in rows}) > 1,
+            "identity_failures": failures}
+
+
 def observation_view(o: dict[str, Any], item: dict[str, Any] | None, cutoff: str | None, store: Any,
                      cache: dict[str, Any]) -> dict[str, Any]:
     view = {k: o.get(k) for k in ("metric", "value", "unit", "valid_at_utc", "valid_at_local", "interval_minutes",
@@ -92,13 +167,18 @@
     if item is None:
         return view | {"evidence_item": None}
     derived = item.get("evidence_class") == "derived"
+    availability = _availability(item.get("published_at_utc"), item.get("available_at_utc"), cutoff, derived)
+    if not availability["derived"] and (item.get("published_at_utc") is None or item.get("available_at_utc") is None):
+        # Amendment 1: no time is inferred for the item; each exact source row keeps its own
+        availability = availability | {"available_by_cutoff": None, "item_times_recorded": False,
+                                       "from_source_rows": source_row_times(item, cutoff, store)}
     return view | {
         "evidence_class": item.get("evidence_class"), "label": item.get("label") or o.get("label"),
         "definition": definition(item),
         "source": {"evidence_id": item["evidence_id"], "tool_call_id": item.get("tool_call_id"),
                    "source_rows": [_row(store, r, cache) for r in item.get("source_row_ids") or []],
                    "source_urls": item.get("source_urls") or []},
-        "availability": _availability(item.get("published_at_utc"), item.get("available_at_utc"), cutoff, derived),
+        "availability": availability,
         **({"coverage": item["coverage"]} if item.get("coverage") else {}),
     }
 
@@ -204,6 +284,17 @@
         out += [f"{tag}: source row {r['row_id']} is not in the pinned store" for r in src["source_rows"]
                 if r.get("table") is None]
         a = o["availability"]
+        fr = a.get("from_source_rows")
+        if fr is not None:  # Amendment 1: the times of the item's exact source rows, each identity verified
+            out += [f"{tag}: {f}" for f in fr["identity_failures"]]
+            if not fr["rows"]:
+                out.append(f"{tag}: no publication or availability time, and no identified source row")
+            out += [f"{tag}: source row {x['row_id']} has no publication or availability time" for x in fr["rows"]
+                    if x["published_at_utc"] is None or x["available_at_utc"] is None]
+            if view["cutoff_utc"]:
+                out += [f"{tag}: source row {x['row_id']}: availability at the cutoff not established"
+                        for x in fr["rows"] if x.get("available_by_cutoff") is None]
+            continue
         if not a["derived"] and (a["published_at_utc"] is None or a["available_at_utc"] is None):
             out.append(f"{tag}: no publication or availability time")
         if view["cutoff_utc"] and not a["derived"] and a["available_by_cutoff"] is None:
```
