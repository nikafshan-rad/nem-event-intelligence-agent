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


@pytest.fixture(scope="session", autouse=True)
def _session_budget_ledger(tmp_path_factory):
    """Module- and session-scoped fixtures run outside the per-test fixture below, so the whole session also points
    at a scratch ledger (a module fixture running the fake transport once wrote to the real one)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("NEM_AGENT_BUDGET_LEDGER", str(tmp_path_factory.mktemp("ledger") / "budget_ledger.jsonl"))
        for name in _ROUTE_PLAN_SETTINGS:
            mp.delenv(name, raising=False)
        yield


# D31 Amendment 1: the request plan is opt-in; tests that use it turn it on themselves, so a setting in the shell
# never changes which routing contract the suite exercises
_ROUTE_PLAN_SETTINGS = ("NEM_AGENT_ROUTE_PLAN", "NEM_AGENT_PLAN_POLICY")


@pytest.fixture(autouse=True)
def _isolated_budget_ledger(tmp_path, monkeypatch):
    """Tests never touch the real task-wide spending ledger (nem_agent.budget)."""
    monkeypatch.setenv("NEM_AGENT_BUDGET_LEDGER", str(tmp_path / "budget_ledger.jsonl"))
    for name in _ROUTE_PLAN_SETTINGS:
        monkeypatch.delenv(name, raising=False)
