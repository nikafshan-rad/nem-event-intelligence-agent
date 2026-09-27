"""Which pinned source versions the application is using, and what is known about the publishers' current versions.

Three categories, shown by the API (``/sources``, ``/health``), the UI sidebar and ``nem-agent sources``:

* ``pinned``       the reviewed, pinned bytes (verified by hash) are in use;
* ``revised``      the publisher now serves different content. If a verified copy of the pinned version is still
                   available it stays in use (``in_use: true``, review pending); otherwise the source is excluded;
* ``unavailable``  the publisher does not serve it (e.g. rolled off NEMWeb Current) and no verified copy exists; the
                   source is excluded.

Excluded sources never have content substituted: tools report the gap as missing evidence and answers abstain
or carry caveats. Upstream knowledge comes from the builds and from the latest publisher-refresh report
(``nem-agent refresh-check``, docs/source-governance.md); nothing here makes a network request.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from . import paths
from .selection import Selection, load_selection

# Datasets the builds do not use (PUBLIC_PRICES was only scanned by the probe; TOC/cover pages are metadata).
_NOT_USED_ROLES = ("document_toc", "document_cover")


def refresh_dir() -> Path:
    return paths.artifacts_dir() / "source_refresh"


def latest_refresh() -> dict[str, Any] | None:
    p = refresh_dir() / "latest.json"
    return json.loads(p.read_text()) if p.exists() else None


def _read(p: Path) -> dict[str, Any] | None:
    return json.loads(p.read_text()) if p.exists() else None


def category(pin_status: str, upstream: str) -> tuple[str, bool]:
    """(category, in_use) for one source."""
    if pin_status == "pinned":
        return ("revised" if upstream == "revised" else "pinned"), True
    return ("revised" if pin_status == "revised" else "unavailable"), False


def source_statuses(sel: Selection | None = None) -> dict[str, Any]:
    sel = sel or load_selection()
    snap = _read(paths.store_dir() / "snapshot.json") or {}
    man = _read(paths.index_dir() / "index_manifest.json") or {}
    built: dict[str, dict[str, Any]] = dict(snap.get("sources", {}))
    for s in man.get("sources", []):
        built[s["source_id"]] = s
    refresh = latest_refresh()
    checked = {r["source_id"]: r for r in (refresh or {}).get("sources", [])}
    rows = []
    for src in sel.sources:
        b = built.get(src.source_id)
        if b is None or src.dataset == "PUBLIC_PRICES" or src.role in _NOT_USED_ROLES:
            if b is None and src.dataset != "PUBLIC_PRICES" and src.role not in _NOT_USED_ROLES:
                rows.append({"source_id": src.source_id, "dataset": src.dataset, "category": "unavailable",
                             "in_use": False, "reason": "not built yet (run make data / make index)"})
            continue
        upstream = b.get("upstream", "not_checked")
        r = checked.get(src.source_id)
        if r is not None:  # the refresh check asked the publisher more recently than a cache hit did
            upstream = {"unchanged": "matches_pin", "changed": "revised", "unavailable": "unavailable"}[r["result"]]
        cat, in_use = category(b.get("pin_status", "pinned" if b.get("ok", b.get("ingested")) else "unavailable"),
                               upstream)
        row: dict[str, Any] = {"source_id": src.source_id, "dataset": src.dataset, "category": cat, "in_use": in_use,
                               "upstream": upstream, "pinned_sha256": src.sha256}
        if not in_use:
            row["reason"] = b.get("error")
        elif cat == "revised":
            row["reason"] = "publisher serves a newer version; the pinned version stays in use until a reviewer re-pins"
        elif upstream == "unavailable":
            row["note"] = "publisher no longer serves it; a verified copy of the pinned version is in use"
        if r is not None:
            row["upstream_checked_at"] = r.get("retrieved_at")
        if src.superseded:
            row["superseded_pins"] = len(src.superseded)
        rows.append(row)
    counts = Counter(r["category"] for r in rows)
    return {
        "data_version": snap.get("data_version"), "corpus_version": man.get("corpus_version"),
        "summary": {"pinned": counts.get("pinned", 0),
                    "revised_in_use_pending_review": sum(r["category"] == "revised" and r["in_use"] for r in rows),
                    "revised_excluded": sum(r["category"] == "revised" and not r["in_use"] for r in rows),
                    "unavailable_excluded": counts.get("unavailable", 0)},
        "refresh_check": {"report": str(refresh_dir() / "latest.json"), "generated_at": refresh.get("generated_at"),
                          "changed": refresh.get("summary", {}).get("changed")} if refresh else None,
        "sources": rows,
    }
