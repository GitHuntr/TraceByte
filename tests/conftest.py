"""Shared pytest fixtures.

Every test runs against an isolated temporary workspace so that the real
``data/originals`` evidence set is never modified by the test suite.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class Workspace:
    """An isolated project workspace used by the tests."""

    root: Path
    originals_dir: Path
    manifest_path: Path
    log_path: Path

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    @property
    def recovered_dir(self) -> Path:
        return self.root / "recovered"


@pytest.fixture()
def workspace(tmp_path: Path) -> Workspace:
    """Return an empty, isolated evidence workspace."""
    originals_dir = tmp_path / "originals"
    logs_dir = tmp_path / "logs"
    originals_dir.mkdir()
    logs_dir.mkdir()
    return Workspace(
        root=tmp_path,
        originals_dir=originals_dir,
        manifest_path=originals_dir / "manifest.json",
        log_path=logs_dir / "experiment_log.jsonl",
    )


@pytest.fixture()
def initialised_workspace(workspace: Workspace):
    """Return a workspace whose dataset has been initialised once."""
    from src.fixtures import initialize_dataset

    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    return workspace, report
