"""Read-only query layer over the Parquet store (DuckDB). Tools never receive SQL from a model."""

from __future__ import annotations

import json
import re
from functools import cached_property
from pathlib import Path
from typing import Any

import duckdb

from . import paths, rawstore
from .ingest import TABLES
from .mmscsv import iter_csv_members


class StoreMissingError(RuntimeError):
    pass


class Store:
    def __init__(self, store_dir: Path | None = None) -> None:
        self.dir = store_dir or paths.store_dir()
        if not (self.dir / "snapshot.json").exists():
            raise StoreMissingError(f"no data snapshot in {self.dir}; run `make data`")
        self.con = duckdb.connect(database=":memory:")
        self.con.execute("SET TimeZone='UTC'")
        for t in TABLES:
            f = self.dir / f"{t}.parquet"
            if f.exists():
                self.con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{f.as_posix()}')")

    @cached_property
    def snapshot(self) -> dict[str, Any]:
        return json.loads((self.dir / "snapshot.json").read_text())

    @property
    def data_version(self) -> str:
        return str(self.snapshot["data_version"])

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def has_rows(self, table: str) -> bool:
        return int(self.snapshot["row_counts"].get(table, 0)) > 0

    def row(self, row_id: str) -> dict[str, Any] | None:
        for t in TABLES:
            if not self.has_rows(t):
                continue
            rows = self.query(f"SELECT * FROM {t} WHERE row_id = ?", [row_id])
            if rows:
                return {"table": t, **rows[0]}
        return None


_ROW_RE = re.compile(r"^(?P<ds>[A-Z_]+):(?P<stem>[^:]+):L(?P<line>\d+)$")


def trace_row(store: Store, row_id: str) -> dict[str, Any]:
    """Re-open the raw publisher file and return the exact CSV line behind ``row_id`` with checksums."""
    m = _ROW_RE.match(row_id)
    if not m:
        raise ValueError(f"not a source-row id: {row_id!r}")
    rec = store.row(row_id)
    if rec is None:
        raise KeyError(f"row {row_id} not in store {store.data_version}")
    local = rawstore.local_path_for(m.group("ds"), rec["source_url"])
    container_sha = rawstore.sha256_file(local)
    for member, csvb in iter_csv_members(local.read_bytes(), local.name):
        if member == rec["member"]:
            import hashlib

            lines = csvb.decode("utf-8-sig").splitlines()
            return {
                "row_id": row_id, "table": rec["table"], "source_url": rec["source_url"],
                "container_sha256_recorded": rec["container_sha256"], "container_sha256_recomputed": container_sha,
                "member": member, "member_sha256_recomputed": hashlib.sha256(csvb).hexdigest(),
                "member_sha256_recorded": rec.get("member_sha256"), "line_no": int(m.group("line")),
                "raw_line": lines[int(m.group("line")) - 1],
            }
    raise KeyError(f"member {rec['member']} not found in {local}")
