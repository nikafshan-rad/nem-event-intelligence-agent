"""The evidence-complete review kit of the end-to-end Live acceptance check of v13 request resolution (PROTOCOL.md,
"Reviews"). Offline: it reads saved records and the pinned store, and calls no model.

For each answer it gives what was shown and, for every item shown, the evidence behind it. This is what the maxima
check's sheet left out:
- **every observation:**
  - its label;
  - its metric's definition (AEMO's, from `aemo_schema.METRIC_DEFINITIONS`, or for a project-derived value its
    derivation);
  - its source references (evidence ID, source rows with their tables, source URLs);
  - its availability evidence (publication and availability times; under a cutoff, whether it was available by it);
- **every computed result:**
  - its source rows with their times;
  - under a cutoff, every interval of the window, with its rows' times and eligibility;
- **every numeric claim:** its evidence item;
- **every cited passage:** its document, section, publication date, eligibility and text;
- **the gold,** with its sources.

`build` refuses (`IncompleteKit`) when any of these is missing for an item the record holds.
"""

from __future__ import annotations

import copy
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from nem_agent.aemo_schema import METRIC_DEFINITIONS  # noqa: E402
from nem_agent.timeutil import iso_utc, local_str, parse_iso  # noqa: E402

AEMO_KEY = {"dispatch_totaldemand": "DISPATCH_TOTALDEMAND", "opdemand_actual": "OPERATIONAL_DEMAND",
            "dispatch_rrp": "DISPATCH_RRP", "dispatch_netinterchange": "DISPATCH_NETINTERCHANGE"}
WINDOW_TABLE = {"total demand": ("regionsum_5min", "totaldemand_mw", None),
                "operational demand": ("opdemand_actual", "operational_demand_mw", "revision")}


class IncompleteKit(SystemExit):
    """The kit would leave out evidence the record holds."""


def _t(x: Any) -> str | None:
    if x is None:
        return None
    return iso_utc(x) if isinstance(x, datetime) else str(x)


def _le(a: str | None, b: str | None) -> bool | None:
    return None if a is None or b is None else parse_iso(a) <= parse_iso(b)


def definition(item: dict[str, Any]) -> dict[str, Any]:
    """What the metric is: AEMO's definition for an AEMO series (a forecast is of operational demand), otherwise the
    project's derivation and label."""
    metric = str(item.get("metric") or "")
    key = AEMO_KEY.get(metric) or ("OPERATIONAL_DEMAND" if metric.startswith("opdemand_forecast_") else None)
    if key:
        d = METRIC_DEFINITIONS[key]
        return {"source": f"AEMO (aemo_schema.METRIC_DEFINITIONS['{key}'])", **{k: d[k] for k in d},
                **({"forecast_of": "operational demand; the label gives the probability of exceedance"}
                   if metric.startswith("opdemand_forecast_") else {})}
    return {"source": "project-derived", "derivation": item.get("derivation"), "label": item.get("label")}


def _row(store: Any, row_id: str, cache: dict[str, Any]) -> dict[str, Any]:
    if row_id not in cache:
        r = store.row(row_id)
        cache[row_id] = None if r is None else {
            "row_id": row_id, "table": r["table"], "source_url": r.get("source_url"), "member": r.get("member"),
            "published_at_utc": _t(r.get("published_at_utc")), "available_at_utc": _t(r.get("available_at_utc"))}
    return cache[row_id] or {"row_id": row_id, "table": None}


def _availability(published: str | None, available: str | None, cutoff: str | None, derived: bool) -> dict[str, Any]:
    if derived and published is None and available is None:
        return {"derived": True, "note": "computed by project code during the run from registered items; see the "
                                         "derivation", "published_at_utc": None, "available_at_utc": None,
                "available_by_cutoff": None}
    return {"derived": False, "published_at_utc": published, "available_at_utc": available,
            "available_by_cutoff": (None if cutoff is None else
                                    bool(_le(published, cutoff) and _le(available, cutoff)))}


def observation_view(o: dict[str, Any], item: dict[str, Any] | None, cutoff: str | None, store: Any,
                     cache: dict[str, Any]) -> dict[str, Any]:
    view = {k: o.get(k) for k in ("metric", "value", "unit", "valid_at_utc", "valid_at_local", "interval_minutes",
                                  "evidence_id")}
    if item is None:
        return view | {"evidence_item": None}
    derived = item.get("evidence_class") == "derived"
    return view | {
        "evidence_class": item.get("evidence_class"), "label": item.get("label") or o.get("label"),
        "definition": definition(item),
        "source": {"evidence_id": item["evidence_id"], "tool_call_id": item.get("tool_call_id"),
                   "source_rows": [_row(store, r, cache) for r in item.get("source_row_ids") or []],
                   "source_urls": item.get("source_urls") or []},
        "availability": _availability(item.get("published_at_utc"), item.get("available_at_utc"), cutoff, derived),
        **({"coverage": item["coverage"]} if item.get("coverage") else {}),
    }


def window_availability(identity: dict[str, Any], cutoff: str | None, store: Any) -> dict[str, Any]:
    """The rows of the result's window and their times. Under a cutoff: every interval, with whether each row was
    eligible (published and available by the cutoff). Without one: a summary."""
    table, col, rev = WINDOW_TABLE[identity["measure"]]
    w0, w1 = identity["window_utc"]
    rows = store.query(f"SELECT row_id, interval_end_utc, {col} AS value{', ' + rev + ' AS revision' if rev else ''}, "
                       f"published_at_utc, available_at_utc FROM {table} WHERE region = ? AND interval_end_utc > ? "
                       f"AND interval_end_utc <= ? ORDER BY interval_end_utc, available_at_utc",
                       [identity["region"], w0, w1])
    view = [{"interval_end_utc": _t(r["interval_end_utc"]), "row_id": r["row_id"], "value": r["value"],
             "revision": r.get("revision"), "published_at_utc": _t(r["published_at_utc"]),
             "available_at_utc": _t(r["available_at_utc"])} for r in rows]
    summary = {"table": table, "window_utc": [w0, w1], "rows": len(view),
               "intervals_with_a_row": len({r["interval_end_utc"] for r in view}),
               "latest_published_at_utc": max((r["published_at_utc"] for r in view), default=None),
               "latest_available_at_utc": max((r["available_at_utc"] for r in view), default=None)}
    if cutoff is None:
        return summary | {"cutoff_utc": None}
    for r in view:
        r["eligible_at_cutoff"] = bool(_le(r["published_at_utc"], cutoff) and _le(r["available_at_utc"], cutoff))
    ends = sorted({r["interval_end_utc"] for r in view})
    eligible = {r["interval_end_utc"] for r in view if r["eligible_at_cutoff"]}
    return summary | {"cutoff_utc": cutoff, "intervals_eligible_at_cutoff": len(eligible),
                      "intervals_without_eligible_row": len([e for e in ends if e not in eligible]),
                      "rows_excluded_by_cutoff": sum(not r["eligible_at_cutoff"] for r in view), "intervals": view}


def result_view(r: dict[str, Any], item: dict[str, Any] | None, store: Any, cache: dict[str, Any]) -> dict[str, Any]:
    res, ver = r["result"], r["server_verification"]
    ident = res["identity"]
    est = res["status"] == "established"
    ends = res["interval_ends_utc"] if est else res["highest_held_interval_ends_utc"]
    return {
        "result_id": res["result_id"], "status": res["status"], "verification": ver["outcome"],
        "rendered": None if item is None else {k: item.get(k) for k in ("status", "verification", "statement")},
        "measure": ident["measure"], "region": ident["region"], "window_utc": ident["window_utc"],
        "window_kind": ident["window_kind"], "cutoff_utc": ident["cutoff_utc"], "metric": res.get("metric"),
        "definition": definition({"metric": res.get("metric")}),
        "value": res["maximum"] if est else res["highest_held"], "value_is": "maximum" if est else "highest held, "
                                                                                                    "not a maximum",
        "unit": res["unit"], "interval_ends_utc": ends,
        "interval_ends_local": [local_str(parse_iso(e), ident["region"]) for e in ends],
        "coverage": res.get("coverage"), "limitations": [x.get("text") for x in res.get("limitations") or []],
        "source_rows": [_row(store, x, cache) for x in res.get("source_row_ids") or []],
        "availability": window_availability(ident, ident["cutoff_utc"], store),
    }


def claim_view(c: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    item = evidence.get(c.get("evidence_id") or "")
    return {k: c.get(k) for k in ("claim_id", "text", "value", "unit", "evidence_id")} | {
        "evidence_item": None if item is None else {k: item.get(k) for k in (
            "metric", "value", "unit", "valid_at_utc", "label", "evidence_class", "source_row_ids")}}


def passage_view(cid: str, p: dict[str, Any] | None, cutoff: str | None) -> dict[str, Any]:
    if p is None:
        return {"chunk_id": cid, "found": False}
    return {"chunk_id": cid, "found": True, **{k: p.get(k) for k in ("doc_id", "title", "url", "section", "page", "doc_type",
                                                       "publication_date", "eligible", "eligibility_reason", "text")},
            "available_by_cutoff": None if cutoff is None else _le(p.get("publication_date"), cutoff)}


def evidence_view(rec: dict[str, Any], store: Any, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every item shown, with its evidence."""
    cache = {} if cache is None else cache
    rep = rec.get("report") or {}
    ev = rec.get("evidence") or {}
    cutoff = (rec.get("request") or {}).get("as_of_utc") or rep.get("as_of")
    answers = {a["result_id"]: a for a in rep.get("answer") or []}
    return {
        "cutoff_utc": cutoff,
        "observations": [observation_view(o, ev.get(o.get("evidence_id") or ""), cutoff, store, cache)
                         for o in rep.get("observations") or []],
        "computed_results": [result_view(r, answers.get(r["result"]["result_id"]), store, cache)
                             for r in rep.get("results") or []],
        "numeric_claims": [claim_view(c, ev) for c in rep.get("numeric_claims") or []],
        "cited_passages": [passage_view(c["chunk_id"], (rec.get("cited_passages") or {}).get(c["chunk_id"]), cutoff)
                           for c in rep.get("citations") or [] if c.get("chunk_id")],
    }


def missing(view: dict[str, Any]) -> list[str]:
    """What the evidence view leaves out for an item the record holds: any non-empty list means the kit refuses."""
    out = []
    for o in view["observations"]:
        tag = f"observation {o.get('evidence_id')} ({o.get('metric')})"
        if "label" not in o:
            out.append(f"{tag}: its evidence item is not in the record")
            continue
        if not o["label"]:
            out.append(f"{tag}: no label")
        d = o["definition"]
        if not (d.get("aemo_definition") or d.get("derivation") or d.get("label")):
            out.append(f"{tag}: no definition")
        src = o["source"]
        if not src["source_rows"] and not o["availability"]["derived"]:
            out.append(f"{tag}: no source rows")
        out += [f"{tag}: source row {r['row_id']} is not in the pinned store" for r in src["source_rows"]
                if r.get("table") is None]
        a = o["availability"]
        if not a["derived"] and (a["published_at_utc"] is None or a["available_at_utc"] is None):
            out.append(f"{tag}: no publication or availability time")
        if view["cutoff_utc"] and not a["derived"] and a["available_by_cutoff"] is None:
            out.append(f"{tag}: availability at the cutoff not established")
    for r in view["computed_results"]:
        tag = f"computed result {r['result_id'][:12]}"
        out += [f"{tag}: source row {x['row_id']} is not in the pinned store" for x in r["source_rows"]
                if x.get("table") is None]
        out += [f"{tag}: source row {x['row_id']} has no publication or availability time" for x in r["source_rows"]
                if x.get("table") and (x.get("published_at_utc") is None or x.get("available_at_utc") is None)]
        if r["cutoff_utc"] and not r["availability"].get("intervals"):
            out.append(f"{tag}: no per-interval availability under its cutoff")
    out += [f"numeric claim {c['claim_id']}: its evidence item is not in the record" for c in view["numeric_claims"]
            if c["evidence_item"] is None]
    for p in view["cited_passages"]:
        if not p["found"]:
            out.append(f"cited passage {p['chunk_id']}: not in the record")
        elif "publication_date" not in p or p.get("text") in (None, ""):
            out.append(f"cited passage {p['chunk_id']}: no publication date field or no text")
    return out


def shown(rec: dict[str, Any]) -> dict[str, Any]:
    """What was shown, as the maxima check's sheet gave it."""
    rep = rec.get("report") or {}
    prov = (rec.get("display") or {}).get("result_provenance") or {}
    return {"status": rep.get("status"), "label": prov.get("label"), "interpretation": prov.get("interpretation"),
            "validation": prov.get("validation"), "headline": rep.get("headline"),
            "computed_answer": [{k: a.get(k) for k in ("status", "verification", "statement", "limitations")}
                                for a in rep.get("answer") or []],
            "summary": rep.get("summary"),
            "possible_explanations": [h.get("statement") for h in rep.get("possible_explanations") or []],
            "ruled_out_explanations": [h.get("statement") for h in rep.get("ruled_out_explanations") or []],
            "published_findings": [f.get("statement") for f in rep.get("published_findings") or []],
            "uncertainties": rep.get("uncertainties"), "missing_evidence": rep.get("missing_evidence")}


def gold_view(case: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """The gold, with its sources."""
    src = {"copied_from": gold["copied_from"], "maxima_gold_independently_checked": gold.get("maxima_gold") is not None}
    group = case["e2e_group"]
    if group == "answerable":
        return {"kind": "requested maximum", "reading": gold["reading"], "result": gold["result"], **src}
    if group == "clarification_control":
        need = "the cutoff (its time cannot be read)" if case["case_id"] == "F07N" else "the measure (none is named)"
        return {"kind": "must be sent back for clarification: no value is the answer to what the question leaves "
                        "open", "required_clarification": need, **src}
    return {"kind": "non-maximum control: no maximum is asked for", "gold_run": gold["answer"]["gold_run"],
            "gold_numbers": gold["answer"]["gold_numbers"], "routing_binding": gold["routing"]["forecast_run"], **src}


def fill(case: dict[str, Any]) -> dict[str, Any]:
    answerable = case["e2e_group"] == "answerable"
    control = case["e2e_group"] == "non_maximum_control"
    return {"outcome": None, "H2_manual": None, "H4_manual": None,
            "correct_result_shown": None if answerable else "n/a",
            "unadmitted_or_observation_presented_as_maximum": None,
            "interpretation_contradicts_answer": None if answerable else "n/a",
            "gold_items": [{"gold": g.get("label") or g.get("metric"), "correct": None}
                           for g in case["expected"].get("gold_numbers") or []] if control else [],
            "interpretation_note": "", "note": ""}


def build(cases: list[dict[str, Any]], gold: dict[str, dict[str, Any]], records: dict[str, dict[str, Any] | None],
          blind_order: dict[str, str], store: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The developer's sheet (case IDs) and the blind sheet (A01-A08 in the frozen order, without IDs or groups).
    Raises ``IncompleteKit`` if any evidence the records hold would be left out."""
    dev, problems, cache = [], [], {}
    for c in cases:
        cid = c["case_id"]
        rec = records.get(cid)
        ev = evidence_view(rec, store, cache) if rec else None
        if ev is not None:
            problems += [f"{cid}: {p}" for p in missing(ev)]
        dev.append({"case_id": cid, "e2e_group": c["e2e_group"], "question": c["question"],
                    "request": c.get("request", {}), "saved": rec is not None, "shown": shown(rec) if rec else None,
                    "evidence": ev, "gold": gold_view(c, gold[cid]), "fill": fill(c)})
    if problems:
        raise IncompleteKit("the review kit would leave out evidence the records hold:\n" + "\n".join(problems))
    blind = []
    for aid, cid in blind_order.items():
        d = copy.deepcopy(next(x for x in dev if x["case_id"] == cid))
        # the gold's sources by file only: an entry's case ID would identify the answer
        d["gold"]["copied_from"] = {k: v.split(" ")[0] if v else v for k, v in d["gold"]["copied_from"].items()}
        blind.append({"answer_id": aid, **{k: v for k, v in d.items() if k not in ("case_id", "e2e_group")}})
    return {"reviewer": "developer", "cases": dev}, {"reviewer": "independent", "answers": blind}
