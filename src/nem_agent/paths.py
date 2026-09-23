"""Filesystem layout. Override the root with ``NEM_AGENT_HOME`` (used by tests and clean-checkout runs)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("NEM_AGENT_HOME")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "nem_agent").exists():
            return parent
    return Path.cwd().resolve()


def data_dir() -> Path:
    return repo_root() / "data"


def raw_dir() -> Path:
    return data_dir() / "raw"


def store_dir() -> Path:
    return data_dir() / "store"


def index_dir() -> Path:
    return data_dir() / "index"


def models_dir() -> Path:
    return data_dir() / "models"


def manifest_path() -> Path:
    return data_dir() / "manifest" / "raw_manifest.jsonl"


def selection_path() -> Path:
    return data_dir() / "source_selection.json"


def artifacts_dir() -> Path:
    return repo_root() / "artifacts"


def case_notes_dir() -> Path:
    return data_dir() / "case_notes"
