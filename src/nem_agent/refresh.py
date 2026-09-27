"""Publisher-refresh check: what do the publishers serve *now*, compared with the reviewed pins?

This is deliberately separate from the pinned build (`make data` / `make index` / CI), which only ever uses content
whose hash matches ``data/source_selection.json``. The refresh check:

* downloads every selected source again, bypassing the cache, into a staging folder under
  ``artifacts/source_refresh/<run>/`` (never into ``data/raw``, the store, the index or the manifest);
* classifies each source as ``unchanged`` (same identity as the pin), ``changed`` (the publisher serves different
  content) or ``unavailable`` (not served, e.g. rolled off NEMWeb Current);
* for each changed source records the retrieval time, old and new hashes, safe HTTP metadata, document version or API
  metadata, a content diff against the locally held pinned bytes, the data tables / index documents / events /
  evaluation cases it feeds, and optionally the evaluation differences (baseline vs candidate sandboxes);
* writes ``report.json`` and a reviewer-facing ``report.md`` and prints the exact approval command.

Nothing is accepted here. A new version is used only after a reviewer runs ``scripts/repin_source.py`` with the
reviewed hash (docs/source-governance.md). No credentials are sent or recorded; only public URLs and a fixed set
of response headers appear in the report.
"""

from __future__ import annotations

import difflib
import hashlib
import html
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import http, paths, rawstore
from .selection import Selection, SourceEntry, load_selection
from .sources import refresh_dir
from .timeutil import iso_utc

SAFE_HEADERS = ("last-modified", "etag", "content-length", "content-type")
DATASET_TABLES = {
    "DISPATCHIS": ["price_5min", "regionsum_5min"], "DISPATCH_SCADA": ["scada_5min"],
    "OPDEM_FORECAST_HH": ["opdemand_forecast"], "OPDEM_ACTUAL_HH": ["opdemand_actual"],
    "OPDEM_ACTUAL_DAILY": ["opdemand_actual"], "MMSDM_DUDETAILSUMMARY": ["duid_region"],
    "NASA_POWER_HOURLY": ["weather_hourly"],
}
INDEXED = ("AEMO_PDF", "MMS_DATA_MODEL_HTML", "MARKET_NOTICE")
MAX_DIFF_LINES = 40


# ------------------------------------------------------------------------------------------ describe + diff
def _pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    return [re.sub(r"[ \t]+", " ", p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


def _html_text(data: bytes) -> list[str]:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", data.decode("utf-8", "replace"))
    t = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", t))
    return [ln.strip() for ln in t.splitlines() if ln.strip()]


def describe(dataset: str, data: bytes) -> dict[str, Any]:
    """Version / API metadata that a reviewer can compare (best effort; never guesses)."""
    try:
        if dataset == "AEMO_PDF":
            from pypdf import PdfReader

            r = PdfReader(io.BytesIO(data))
            head = re.sub(r"\s+", " ", " ".join((r.pages[i].extract_text() or "") for i in range(min(4, len(r.pages)))))
            meta = {k.lstrip("/"): str(v) for k, v in (r.metadata or {}).items()
                    if k in ("/Title", "/CreationDate", "/ModDate")}
            ver = re.search(r"(?i)\bversion\s*(?:no\.?|number)?\s*[:.]?\s*(\d+(?:\.\d+)?)", head)
            eff = re.search(r"(?i)effective date\s*[:.]?\s*(\d{1,2}\s+[A-Z][a-z]+\s+20\d\d|\d{1,2}/\d{1,2}/20\d\d)", head)
            return {"pages": len(r.pages), **meta, "version": ver.group(1) if ver else None,
                    "effective_date": eff.group(1) if eff else None}
        if dataset == "NASA_POWER_HOURLY":
            d = json.loads(data)
            h = d.get("header", {})
            return {"api": h.get("api"), "sources": h.get("sources"), "start": h.get("start"), "end": h.get("end"),
                    "parameters": sorted(d.get("properties", {}).get("parameter", {}))}
        if dataset in ("MMS_DATA_MODEL_HTML",):
            m = re.search(r"(?is)<title>(.*?)</title>", data.decode("utf-8", "replace"))
            return {"title": html.unescape(m.group(1).strip()) if m else None}
        if dataset == "MARKET_NOTICE":
            first = data.decode("utf-8", "replace").strip().splitlines()[:1]
            return {"first_line": first[0][:200] if first else None}
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return {"zip_members": [f"{i.filename} ({i.file_size} B)" for i in zf.infolist()][:10]}
    except Exception as exc:  # metadata is advisory; the hash comparison is what decides
        return {"metadata_error": f"{type(exc).__name__}: {exc}"[:200]}
    return {}


def _line_diff(old: list[str], new: list[str], label: str) -> dict[str, Any]:
    diff = [ln for ln in difflib.unified_diff(old, new, f"pinned {label}", f"current {label}", n=0, lineterm="")
            if not ln.startswith(("---", "+++"))]
    return {"lines_removed": sum(ln.startswith("-") for ln in diff), "lines_added": sum(ln.startswith("+") for ln in diff),
            "excerpt": [ln[:200] for ln in diff][:MAX_DIFF_LINES], "truncated": len(diff) > MAX_DIFF_LINES}


def _nasa_diff(old: bytes, new: bytes) -> dict[str, Any]:
    o, n = json.loads(old), json.loads(new)
    out: dict[str, Any] = {"header_changes": {k: [o["header"].get(k), n["header"].get(k)]
                                              for k in sorted(set(o.get("header", {})) | set(n.get("header", {})))
                                              if o["header"].get(k) != n["header"].get(k)}}
    po, pn = o["properties"]["parameter"], n["properties"]["parameter"]
    params = {}
    for p in sorted(set(po) | set(pn)):
        a, b = po.get(p, {}), pn.get(p, {})
        ch = [(t, a.get(t), b.get(t)) for t in sorted(set(a) | set(b)) if a.get(t) != b.get(t)]
        deltas = [abs(y - x) for _, x, y in ch if isinstance(x, (int, float)) and isinstance(y, (int, float))]
        params[p] = {"values": len(set(a) | set(b)), "changed": len(ch),
                     "max_abs_change": round(max(deltas), 4) if deltas else None,
                     "examples": [{"hour_utc": t, "pinned": x, "current": y} for t, x, y in ch[:3]]}
    out["parameters"] = params
    return out


def _zip_diff(old: bytes, new: bytes) -> dict[str, Any]:
    def members(b: bytes) -> dict[str, bytes]:
        with zipfile.ZipFile(io.BytesIO(b)) as zf:
            return {i.filename: zf.read(i) for i in zf.infolist() if not i.is_dir()}

    mo, mn = members(old), members(new)
    out: dict[str, Any] = {"members_added": sorted(set(mn) - set(mo)), "members_removed": sorted(set(mo) - set(mn)),
                           "members_changed": {}}
    for name in sorted(set(mo) & set(mn)):
        if mo[name] == mn[name]:
            continue
        if name.lower().endswith((".csv", ".txt")):
            a = mo[name].decode("utf-8", "replace").splitlines()
            b = mn[name].decode("utf-8", "replace").splitlines()
            out["members_changed"][name] = _line_diff(a, b, name)
        else:
            out["members_changed"][name] = {"bytes_pinned": len(mo[name]), "bytes_current": len(mn[name])}
    return out


def content_diff(dataset: str, old: bytes | None, new: bytes) -> dict[str, Any]:
    if old is None:
        return {"available": False,
                "why": "the pinned bytes are not held on this machine, so no content diff can be made (hashes and "
                       "metadata above still identify the change)"}
    try:
        if dataset == "AEMO_PDF":
            po, pn = _pdf_pages(old), _pdf_pages(new)
            changed_pages = [i + 1 for i in range(max(len(po), len(pn)))
                             if (po[i] if i < len(po) else None) != (pn[i] if i < len(pn) else None)]
            lo = [ln.strip() for p in po for ln in p.splitlines() if ln.strip()]
            ln_ = [ln.strip() for p in pn for ln in p.splitlines() if ln.strip()]
            return {"available": True, "kind": "pdf_text", "pages_pinned": len(po), "pages_current": len(pn),
                    "pages_with_text_changes": changed_pages[:60], **_line_diff(lo, ln_, "text")}
        if dataset == "NASA_POWER_HOURLY":
            return {"available": True, "kind": "api_values", **_nasa_diff(old, new)}
        if dataset == "MMS_DATA_MODEL_HTML":
            return {"available": True, "kind": "html_text", **_line_diff(_html_text(old), _html_text(new), "text")}
        if dataset == "MARKET_NOTICE":
            return {"available": True, "kind": "text", **_line_diff(old.decode("utf-8", "replace").splitlines(),
                                                                    new.decode("utf-8", "replace").splitlines(), "text")}
        if old[:2] == b"PK" and new[:2] == b"PK":
            return {"available": True, "kind": "zip_members", **_zip_diff(old, new)}
    except Exception as exc:
        return {"available": False, "why": f"diff failed: {type(exc).__name__}: {exc}"[:300]}
    return {"available": True, "kind": "bytes", "bytes_pinned": len(old), "bytes_current": len(new)}


# ------------------------------------------------------------------------------------------ impact
def affected(src: SourceEntry, cases: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"events": list(src.events)}
    if src.dataset in DATASET_TABLES:
        rows: dict[str, int | None] = {}
        try:
            from .store import Store

            st = Store()
            for t in DATASET_TABLES[src.dataset]:
                rows[t] = int(st.query(f"SELECT count(*) AS n FROM {t} WHERE source_url = ?", [src.url])[0]["n"])
        except Exception:
            rows = {t: None for t in DATASET_TABLES[src.dataset]}
        out["data_tables"] = rows
    if src.dataset in INDEXED:
        db = paths.index_dir() / "corpus.sqlite"
        n = None
        if db.exists():
            with sqlite3.connect(db) as con:
                n = con.execute("SELECT count(*) FROM chunks WHERE doc_id = ?", (src.source_id,)).fetchone()[0]
        out["index_document"] = {"doc_id": src.source_id, "chunks_now": n}
    out["evaluation_cases"] = sorted(
        c["case_id"] for c in cases
        if c["expected"].get("event_id") in src.events
        or (c["expected"].get("gold_citation") or {}).get("doc_id") == src.source_id)
    return out


# ------------------------------------------------------------------------------------------ main check
def _identity(src: SourceEntry, data: bytes) -> tuple[str, str | None]:
    digest = hashlib.sha256(data).hexdigest()
    return digest, rawstore.content_sha256(src.dataset, data)


def _pinned_local_bytes(src: SourceEntry) -> bytes | None:
    p = rawstore.local_path_for(src.dataset, src.url)
    if not p.exists():
        return None
    data = p.read_bytes()
    raw, content = _identity(src, data)
    return data if raw == src.sha256 or (content is not None and content == src.content_sha256) else None


def check_source(src: SourceEntry, staging: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    now = iso_utc(datetime.now(UTC))
    api = src.content_sha256 is not None
    # API servers can disagree with each other (NASA POWER, 2026-09-27): ask several times and report what was seen.
    tries = 1 + (rawstore.MISMATCH_RETRIES.get(src.dataset, 0) if api else 0)
    seen: list[tuple[http.HttpResult, str, str | None]] = []
    for _ in range(tries):
        res = http.fetch(src.url, max_bytes=60 * 1024 * 1024)
        if not res.ok or res.body is None:
            break
        raw, content = _identity(src, res.body)
        seen.append((res, raw, content))
    row: dict[str, Any] = {"source_id": src.source_id, "dataset": src.dataset, "url": src.url, "retrieved_at": now,
                           "http_status": res.status,
                           "headers": {k: v for k, v in (res.headers or {}).items() if k.lower() in SAFE_HEADERS}}
    if not seen:
        row.update(result="unavailable", error=(res.error or f"HTTP {res.status}")[:300],
                   expected_rolling_retention="/reports/current/" in src.url.lower())
        return row
    ident = (lambda r, c: c) if api else (lambda r, c: r)
    pin = src.content_sha256 if api else src.sha256
    idents = [ident(r, c) for _, r, c in seen]
    variants = sorted(set(i for i in idents if i != pin))
    res, raw, content = next(((x, r, c) for x, r, c in seen if ident(r, c) != pin), seen[0])
    body: bytes = res.body or b""  # every response in `seen` has a body
    row["pinned"] = {"sha256": src.sha256, "content_sha256": src.content_sha256, "size": src.size,
                     "retrieved_at": src.retrieved_at, "last_modified": src.last_modified}
    row["current"] = {"sha256": raw, "content_sha256": content, "size": len(body),
                      "last_modified": res.last_modified}
    row["requests"] = len(seen)
    if not variants:
        row["result"] = "unchanged"
        return row
    if pin in idents:  # the pinned content is still served, but not to every request
        row.update(result="inconsistent", variants_seen=variants,
                   note=f"{idents.count(pin)} of {len(seen)} responses matched the pin")
        return row
    old = _pinned_local_bytes(src)
    dest = staging / src.source_id / (Path(src.url.split("?")[0]).name or "content")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    if len(variants) > 1:
        row["variants_seen"] = variants
    row.update(result="changed", identity_kind="content_sha256" if api else "sha256",
               new_identity=content if api else raw, staged_path=str(dest.relative_to(paths.repo_root())),
               metadata={"pinned": describe(src.dataset, old) if old is not None else None,
                         "current": describe(src.dataset, body)},
               diff=content_diff(src.dataset, old, body), affected=affected(src, cases))
    return row


def run_refresh(sel: Selection | None = None, *, source_ids: list[str] | None = None,
                datasets: list[str] | None = None, with_eval: bool = False, log: Any = print) -> dict[str, Any]:
    sel = sel or load_selection()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = refresh_dir() / run_id
    staging = out / "candidates"
    cases = json.loads((paths.repo_root() / "eval" / "cases.json").read_text())["cases"] \
        if (paths.repo_root() / "eval" / "cases.json").exists() else []
    chosen = [s for s in sel.sources if (not source_ids or s.source_id in source_ids)
              and (not datasets or s.dataset in datasets)]
    rows = []
    for i, src in enumerate(chosen, 1):
        r = check_source(src, staging, cases)
        rows.append(r)
        if r["result"] != "unchanged":
            log(f"[refresh] {i}/{len(chosen)} {r['result'].upper():11s} {src.source_id}")
    notice_archive = None
    if any(r["result"] == "unavailable" and r["dataset"] == "MARKET_NOTICE" for r in rows):
        from .recover import notice_archive_listing

        lst = notice_archive_listing()
        notice_archive = {k: lst[k] for k in ("url", "http_status", "checked_at", "n_files")}
    changed = [r for r in rows if r["result"] == "changed"]
    unexpected = [r for r in rows if r["result"] == "unavailable" and not r["expected_rolling_retention"]]
    inconsistent = [r for r in rows if r["result"] == "inconsistent"]
    report: dict[str, Any] = {
        "run_id": run_id, "generated_at": iso_utc(datetime.now(UTC)),
        "selection_sha256": hashlib.sha256(paths.selection_path().read_bytes()).hexdigest(),
        "summary": {"checked": len(rows), "unchanged": sum(r["result"] == "unchanged" for r in rows),
                    "changed": len(changed), "inconsistent": len(inconsistent),
                    "unavailable": sum(r["result"] == "unavailable" for r in rows),
                    "unavailable_unexpected": len(unexpected)},
        "notice_archive_observed": notice_archive,
        "needs_review": bool(changed or unexpected),
        "sources": rows,
    }
    if changed and with_eval:
        report["evaluation_changes"] = candidate_evaluation(sel, changed, out, log=log)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "report.md").write_text(render_markdown(report, out))
    shutil.copy(out / "report.json", refresh_dir() / "latest.json")
    log(f"[refresh] checked={len(rows)} unchanged={report['summary']['unchanged']} changed={len(changed)} "
        f"unavailable={report['summary']['unavailable']} -> {out / 'report.md'}")
    return report


# ------------------------------------------------------------------------------------------ evaluation impact
def _sandbox(home: Path, sel_doc: dict[str, Any], sel: Selection, replace: dict[str, bytes]) -> None:
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "data" / "source_selection.json").write_text(json.dumps(sel_doc, indent=2) + "\n")
    shutil.copytree(paths.repo_root() / "eval", home / "eval", dirs_exist_ok=True)
    if paths.models_dir().exists():
        shutil.copytree(paths.models_dir(), home / "data" / "models", dirs_exist_ok=True)
    for src in sel.sources:
        p = rawstore.local_path_for(src.dataset, src.url)
        rel = p.relative_to(paths.raw_dir())
        dst = home / "data" / "raw" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.source_id in replace:
            data = replace[src.source_id]
            dst.write_bytes(data)
            meta = {"url": src.url, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                    "retrieved_at": iso_utc(datetime.now(UTC)), "content_sha256": rawstore.content_sha256(src.dataset, data),
                    "note": "refresh-check candidate (not a reviewed pin)"}
            dst.with_name(dst.name + ".meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        elif p.exists() and p.with_name(p.name + ".meta.json").exists():
            shutil.copy2(p, dst)
            shutil.copy2(p.with_name(p.name + ".meta.json"), dst.with_name(dst.name + ".meta.json"))


def _build_and_eval(home: Path) -> dict[str, Any]:
    env = {**{k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}, "NEM_AGENT_HOME": str(home)}
    py = sys.executable
    for cmd in (["build-data"], ["build-index"], ["eval", "--out", str(home / "artifacts" / "eval" / "offline.json")]):
        subprocess.run([py, "-m", "nem_agent.cli", *cmd], env=env, cwd=paths.repo_root(), capture_output=True, text=True,
                       timeout=3600)
    ret = subprocess.run([py, "-c", "import json; from nem_agent.evaluation.retrieval_eval import evaluate; r=evaluate(); "
                                    "print(json.dumps({k: r[k] for k in ('recall_at_k','hit_at_k','mrr_at_k')}))"],
                         env=env, cwd=paths.repo_root(), capture_output=True, text=True, timeout=1800)
    ev_path = home / "artifacts" / "eval" / "offline.json"
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    snap = home / "data" / "store" / "snapshot.json"
    man = home / "data" / "index" / "index_manifest.json"
    return {"eval": ev, "retrieval": json.loads(ret.stdout) if ret.returncode == 0 and ret.stdout.strip() else None,
            "snapshot": json.loads(snap.read_text()) if snap.exists() else {},
            "index": json.loads(man.read_text()) if man.exists() else {}}


def candidate_evaluation(sel: Selection, changed: list[dict[str, Any]], out: Path, log: Any = print) -> dict[str, Any]:
    """Build and evaluate the pinned set and the candidate set side by side in sandboxes; report the differences."""
    base_doc = json.loads(paths.selection_path().read_text())
    cand_doc = json.loads(paths.selection_path().read_text())
    replace = {}
    for r in changed:
        e = next(s for s in cand_doc["sources"] if s["source_id"] == r["source_id"])
        data = (paths.repo_root() / r["staged_path"]).read_bytes()
        replace[r["source_id"]] = data
        e.update(sha256=r["current"]["sha256"], size=r["current"]["size"])
        if r["current"]["content_sha256"] is not None:
            e["content_sha256"] = r["current"]["content_sha256"]
    log("[refresh] evaluating the pinned set and the candidate set in sandboxes (no hosted model is called)")
    base_home, cand_home = out / "sandbox_pinned", out / "sandbox_candidate"
    _sandbox(base_home, base_doc, sel, {})
    _sandbox(cand_home, cand_doc, sel, replace)
    b, c = _build_and_eval(base_home), _build_and_eval(cand_home)

    def metrics(x: dict[str, Any]) -> dict[str, Any]:
        t = x["eval"].get("summary", {}).get("system_test", {})
        keep = ("status_ok", "gold_numbers", "gold_forecast", "gold_citation", "as_of_leaks", "corpus_unavailable_cases")
        return {k: (t[k].get("numerator"), t[k].get("denominator")) if isinstance(t.get(k), dict) else t.get(k)
                for k in keep}

    rows_b = {r["case_id"]: r for r in x_rows(b)}
    case_changes = []
    for r in x_rows(c):
        o = rows_b.get(r["case_id"], {})
        diff = {k: [o.get(k), r.get(k)] for k in ("status", "status_ok", "gold_numbers_hit", "gold_forecast_ok",
                                                  "gold_citation_ok", "critical_final") if o.get(k) != r.get(k)}
        if diff:
            case_changes.append({"case_id": r["case_id"], **diff})
    rb, rc = b["retrieval"] or {}, c["retrieval"] or {}
    return {
        "versions": {"pinned": [b["snapshot"].get("data_version"), b["index"].get("corpus_version")],
                     "candidate": [c["snapshot"].get("data_version"), c["index"].get("corpus_version")]},
        "row_counts": {"pinned": b["snapshot"].get("row_counts"), "candidate": c["snapshot"].get("row_counts")},
        "index_chunks": {"pinned": b["index"].get("n_chunks"), "candidate": c["index"].get("n_chunks")},
        "held_out_metrics": {"pinned": metrics(b), "candidate": metrics(c)},
        "gate_checks_all_true": {"pinned": all(b["eval"].get("gate_checks", {"x": False}).values()),
                                 "candidate": all(c["eval"].get("gate_checks", {"x": False}).values())},
        "retrieval": {k: {"pinned": (rb.get(k) or {}).get("numerator", (rb.get(k) or {}).get("value")),
                          "candidate": (rc.get(k) or {}).get("numerator", (rc.get(k) or {}).get("value"))}
                      for k in ("recall_at_k", "hit_at_k", "mrr_at_k")},
        "case_changes": case_changes,
    }


def x_rows(x: dict[str, Any]) -> list[dict[str, Any]]:
    return list(x["eval"].get("rows", {}).get("system", []))


# ------------------------------------------------------------------------------------------ report
def render_markdown(r: dict[str, Any], out: Path) -> str:
    s = r["summary"]
    lines = [f"# Publisher refresh check {r['run_id']}", "",
             f"Generated {r['generated_at']} against `data/source_selection.json` (sha256 `{r['selection_sha256'][:16]}`).",
             "The application and its evaluation keep using the pinned versions; nothing below is accepted until a",
             "reviewer re-pins it (docs/source-governance.md).", "",
             f"**Checked {s['checked']}: unchanged {s['unchanged']}, changed {s['changed']}, inconsistent "
             f"{s['inconsistent']}, unavailable {s['unavailable']} ({s['unavailable_unexpected']} unexpected).** "
             f"Needs review: **{'yes' if r['needs_review'] else 'no'}**.", ""]
    inc = [x for x in r["sources"] if x["result"] == "inconsistent"]
    if inc:
        lines += ["## Inconsistent (the pinned content is still served, but not to every request)", ""]
        lines += [f"- `{x['source_id']}`: {x['note']}; other content seen: "
                  f"{', '.join('`' + v[:16] + '`' for v in x['variants_seen'])}" for x in inc] + [""]
    for c in [x for x in r["sources"] if x["result"] == "changed"]:
        lines += [f"## Changed: `{c['source_id']}`", "", f"- URL: {c['url']}", f"- Retrieved: {c['retrieved_at']}",
                  f"- Pinned: sha256 `{c['pinned']['sha256']}`"
                  + (f", content `{c['pinned']['content_sha256']}`" if c["pinned"]["content_sha256"] else "")
                  + f", {c['pinned']['size']} bytes, retrieved {c['pinned']['retrieved_at']}, Last-Modified "
                    f"{c['pinned']['last_modified']}",
                  f"- Current: sha256 `{c['current']['sha256']}`"
                  + (f", content `{c['current']['content_sha256']}`" if c["current"]["content_sha256"] else "")
                  + f", {c['current']['size']} bytes, Last-Modified {c['current']['last_modified']}",
                  f"- Metadata (pinned → current): `{json.dumps(c['metadata']['pinned'])}` → "
                  f"`{json.dumps(c['metadata']['current'])}`",
                  f"- Staged copy for review: `{c['staged_path']}`",
                  f"- Feeds: `{json.dumps(c['affected'])}`", "", "Content diff:", "", "```",
                  json.dumps({k: v for k, v in c["diff"].items() if k != "excerpt"}, indent=1)[:3000]]
        lines += c["diff"].get("excerpt", [])[:MAX_DIFF_LINES] + ["```", "",
                  "To accept after review (explicit reviewer action):", "", "```",
                  f"python scripts/repin_source.py --source-id {c['source_id']} --expect {c['new_identity']} \\",
                  f"    --report {out / 'report.json'} --approved-by <your name> \\",
                  "    --publisher-revision \"<what changed>\" --reason \"<why this version is acceptable>\"", "```", ""]
    if r.get("evaluation_changes"):
        e = r["evaluation_changes"]
        lines += ["## Evaluation if the changed sources were accepted (sandbox; offline replay only)", "",
                  "| | pinned | candidate |", "| --- | --- | --- |",
                  f"| data / corpus version | {e['versions']['pinned']} | {e['versions']['candidate']} |",
                  f"| index chunks | {e['index_chunks']['pinned']} | {e['index_chunks']['candidate']} |",
                  f"| gate checks all true | {e['gate_checks_all_true']['pinned']} | {e['gate_checks_all_true']['candidate']} |"]
        for k, v in e["held_out_metrics"]["pinned"].items():
            lines.append(f"| {k} | {v} | {e['held_out_metrics']['candidate'].get(k)} |")
        for k, v in e["retrieval"].items():
            lines.append(f"| retrieval {k} | {v['pinned']} | {v['candidate']} |")
        lines += ["", f"Cases whose result changes: {json.dumps(e['case_changes']) if e['case_changes'] else 'none'}", ""]
    un = [x for x in r["sources"] if x["result"] == "unavailable"]
    if un:
        lines += ["## Unavailable", ""]
        exp = [x for x in un if x["expected_rolling_retention"]]
        if exp:
            lines.append(f"- {len(exp)} NEMWeb `Reports/Current` files are no longer served (rolling retention), "
                         f"e.g. {', '.join(x['source_id'] for x in exp[:5])}.")
        if r.get("notice_archive_observed"):
            a = r["notice_archive_observed"]
            lines.append(f"- NEMWeb {a['url']} answered HTTP {a['http_status']} with {a['n_files']} file(s) listed "
                         f"(checked {a['checked_at']}).")
        for x in un:
            if not x["expected_rolling_retention"]:
                lines.append(f"- **Unexpected:** `{x['source_id']}` {x['url']}: {x['error']}")
        lines.append("")
    return "\n".join(lines) + "\n"
