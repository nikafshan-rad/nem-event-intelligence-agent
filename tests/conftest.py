"""Shared fixtures.

Real-data tests use the store built by `make data` (they skip with an explicit reason if it is absent).
Synthetic fixtures are built in temp directories and are clearly named SYNTHETIC; they never enter the real
store and are never presented as energy observations.
"""

from __future__ import annotations

import pytest

from nem_agent import paths


@pytest.fixture(scope="session")
def real_store():
    from nem_agent.store import Store, StoreMissingError

    try:
        return Store()
    except StoreMissingError as exc:
        pytest.skip(f"real data store not built: {exc}")


@pytest.fixture(scope="session")
def selection():
    from nem_agent.selection import load_selection

    if not paths.selection_path().exists():
        pytest.skip("data/source_selection.json missing (run make probe)")
    return load_selection()


@pytest.fixture
def synthetic_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NEM_AGENT_HOME", str(tmp_path))
    (tmp_path / "data").mkdir()
    return tmp_path


def require_notice(doc_id: str) -> None:
    """Skip (with the reason) when an AEMO market notice has rolled off NEMWeb Current and is not in the index."""
    import sqlite3

    db = paths.index_dir() / "corpus.sqlite"
    if not db.exists():
        pytest.skip("document index not built")
    con = sqlite3.connect(db)
    present = con.execute("SELECT 1 FROM chunks WHERE doc_id=? LIMIT 1", [doc_id]).fetchone()
    con.close()
    if not present:
        pytest.skip(f"{doc_id} not in corpus: NEMWeb Current notices have rolling retention (docs/decisions.md D2)")
