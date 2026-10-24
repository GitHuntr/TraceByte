"""Regression tests for the isolation of the test suite and web workbench.

The Phase 1.2 audit found that the interface tests wrote to the real
``data/experiments``, ``data/recovered`` and ``logs`` directories, because the
canonical locations were captured when the modules were imported instead of
when a run started.

These tests pin that behaviour down:

* a workbench run must not change a single byte of the real project state,
  including the ground-truth originals and the baseline manifest,
* the canonical locations must be resolved when a run starts, so a redirected
  workspace is honoured - including the paths derived from a parent directory
  (the manifest follows the originals directory, the provenance log follows
  the logs directory).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

import src.paths as paths
from src.experiment_log import default_log
from src.experiments import run_all_conditions
from src.fixtures import initialize_dataset

#: The canonical project locations, captured before any test redirects them.
REAL_ORIGINALS_DIR = PROJECT_ROOT / "data" / "originals"
REAL_EXPERIMENTS_DIR = PROJECT_ROOT / "data" / "experiments"
REAL_RECOVERED_DIR = PROJECT_ROOT / "data" / "recovered"
REAL_EXPERIMENT_LOG_PATH = PROJECT_ROOT / "logs" / "experiment_log.jsonl"
REAL_MANIFEST_PATH = REAL_ORIGINALS_DIR / "manifest.json"


def _fingerprint(targets: list[Path]) -> dict[str, tuple[str, int, int]]:
    """Return ``path -> (sha256, size, mtime_ns)`` for every file below the targets."""
    state: dict[str, tuple[str, int, int]] = {}
    for target in targets:
        if target.is_file():
            files = [target]
        elif target.is_dir():
            files = sorted(path for path in target.rglob("*") if path.is_file())
        else:
            continue
        for path in files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stat = path.stat()
            state[str(path)] = (digest, stat.st_size, stat.st_mtime_ns)
    return state


def _real_project_targets() -> list[Path]:
    """Return the real project locations that a test run must not touch.

    ``ORIGINALS_DIR`` covers the ground-truth fixtures *and* the baseline
    manifest, ``EXPERIMENTS_DIR``/``RECOVERED_DIR`` the per-run artefacts and
    ``EXPERIMENT_LOG_PATH`` the provenance log.

    The canonical locations are captured at import time on purpose: a test
    that redirects ``paths.*`` must still be checked against the *real*
    project, not against its own temporary workspace.
    """
    return [
        REAL_ORIGINALS_DIR,
        REAL_EXPERIMENTS_DIR,
        REAL_RECOVERED_DIR,
        REAL_EXPERIMENT_LOG_PATH,
    ]


def _real_manifest_digest() -> str:
    """Return the SHA-256 of the committed baseline manifest."""
    manifest = REAL_MANIFEST_PATH
    if not manifest.is_file():
        return ""
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def _run_workbench_experiments() -> list[object]:
    """Exercise the same dataset and run actions exposed by the local API."""
    initialize_dataset(log=default_log())
    return run_all_conditions(log=default_log())


@pytest.fixture()
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every canonical location into a temporary workspace."""
    originals = tmp_path / "originals"
    logs = tmp_path / "logs"
    experiments = tmp_path / "experiments"
    recovered = tmp_path / "recovered"
    for directory in (originals, logs, experiments, recovered):
        directory.mkdir()
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)
    monkeypatch.setattr(paths, "MANIFEST_PATH", originals / "manifest.json")
    monkeypatch.setattr(paths, "EXPERIMENT_LOG_PATH", logs / "experiment_log.jsonl")
    monkeypatch.setattr(paths, "EXPERIMENTS_DIR", experiments)
    monkeypatch.setattr(paths, "RECOVERED_DIR", recovered)
    return originals


def test_the_workbench_run_does_not_touch_the_real_project_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workbench must not change real originals, manifest, candidates or log."""
    real_targets = _real_project_targets()
    before = _fingerprint(real_targets)
    manifest_digest_before = _real_manifest_digest()

    isolated = tmp_path / "workspace"
    for name in ("originals", "logs", "experiments", "recovered"):
        (isolated / name).mkdir(parents=True)
    monkeypatch.setattr(paths, "ORIGINALS_DIR", isolated / "originals")
    monkeypatch.setattr(paths, "MANIFEST_PATH", isolated / "originals" / "manifest.json")
    monkeypatch.setattr(paths, "EXPERIMENT_LOG_PATH", isolated / "logs" / "experiment_log.jsonl")
    monkeypatch.setattr(paths, "EXPERIMENTS_DIR", isolated / "experiments")
    monkeypatch.setattr(paths, "RECOVERED_DIR", isolated / "recovered")

    _run_workbench_experiments()

    after = _fingerprint(real_targets)
    assert after == before
    assert _real_manifest_digest() == manifest_digest_before, (
        "the real baseline manifest was rewritten by a workbench run"
    )

    # The run must really have happened - inside the temporary workspace.
    assert list((isolated / "experiments").glob("*/run.json"))
    assert list((isolated / "recovered").glob("*/*"))
    assert (isolated / "logs" / "experiment_log.jsonl").is_file()
    assert (isolated / "originals" / "manifest.json").is_file()


def test_the_experiment_paths_are_resolved_when_the_run_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The canonical locations are read at call time, not at import time."""
    from src.fixtures import initialize_dataset

    originals = tmp_path / "originals"
    experiments = tmp_path / "experiments"
    recovered = tmp_path / "recovered"
    for directory in (originals, experiments, recovered):
        directory.mkdir()
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)
    monkeypatch.setattr(paths, "MANIFEST_PATH", originals / "manifest.json")
    monkeypatch.setattr(paths, "EXPERIMENTS_DIR", experiments)
    monkeypatch.setattr(paths, "RECOVERED_DIR", recovered)

    initialize_dataset(originals_dir=originals, manifest_path=originals / "manifest.json")

    # No path arguments at all: the redirected locations must be used.
    results = run_all_conditions()

    assert results
    assert list(experiments.glob("*/run.json"))
    assert list(recovered.glob("*/*"))
    for result in results:
        artefact = Path(result.artefacts["image"])
        if not artefact.is_absolute():
            artefact = PROJECT_ROOT / artefact
        assert artefact.resolve().is_relative_to(experiments.resolve())


def test_the_experiment_log_path_is_resolved_when_the_log_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "logs" / "experiment_log.jsonl"
    monkeypatch.setattr(paths, "EXPERIMENT_LOG_PATH", log_path)

    log = default_log()
    assert log.path == log_path

    log.append("isolation_check", {"ok": True})
    assert log_path.is_file()
    assert log.event_count() == 1


def test_the_isolated_workspace_is_used_by_the_workbench(
    isolated_workspace: Path, tmp_path: Path
) -> None:
    """The workbench writes into the temporary workspace, nowhere else."""
    _run_workbench_experiments()

    experiments = tmp_path / "experiments"
    recovered = tmp_path / "recovered"
    log_path = tmp_path / "logs" / "experiment_log.jsonl"

    assert list(experiments.glob("*/run.json"))
    assert list(recovered.glob("*/*"))
    assert log_path.is_file()

    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completed = [event for event in events if event["event"] == "experiment_completed"]
    assert len(completed) == 3


def test_the_manifest_path_follows_the_originals_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redirecting the originals directory moves the manifest with it."""
    originals = tmp_path / "originals"
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)

    assert paths.MANIFEST_PATH == originals / "manifest.json"


def test_the_experiment_log_path_follows_the_logs_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redirecting the logs directory moves the provenance log with it."""
    logs = tmp_path / "logs"
    monkeypatch.setattr(paths, "LOGS_DIR", logs)

    assert paths.EXPERIMENT_LOG_PATH == logs / "experiment_log.jsonl"


def test_initialisation_with_a_redirected_originals_directory_stays_in_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redirected originals directory must never reach the real manifest."""
    from src.fixtures import initialize_dataset

    real_manifest = REAL_MANIFEST_PATH
    digest_before = (
        hashlib.sha256(real_manifest.read_bytes()).hexdigest()
        if real_manifest.is_file()
        else ""
    )

    originals = tmp_path / "originals"
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)

    # The resolution is asserted *before* anything is written: a broken
    # resolution must fail the test instead of touching the real baseline.
    assert paths.MANIFEST_PATH == originals / "manifest.json"

    report = initialize_dataset()

    reported_manifest = Path(report.manifest_path)
    if not reported_manifest.is_absolute():
        reported_manifest = PROJECT_ROOT / reported_manifest
    assert reported_manifest.resolve() == (originals / "manifest.json").resolve()
    assert (originals / "manifest.json").is_file()
    if real_manifest.is_file():
        assert hashlib.sha256(real_manifest.read_bytes()).hexdigest() == digest_before


def test_an_explicit_originals_directory_keeps_its_own_manifest(
    tmp_path: Path,
) -> None:
    """A workspace handed in explicitly gets its own manifest, not the canonical one."""
    from src.fixtures import initialize_dataset

    real_manifest = REAL_MANIFEST_PATH
    digest_before = (
        hashlib.sha256(real_manifest.read_bytes()).hexdigest()
        if real_manifest.is_file()
        else ""
    )

    workspace = tmp_path / "workspace" / "originals"
    report = initialize_dataset(originals_dir=workspace)

    reported_manifest = Path(report.manifest_path)
    if not reported_manifest.is_absolute():
        reported_manifest = PROJECT_ROOT / reported_manifest
    assert reported_manifest.resolve() == (workspace / "manifest.json").resolve()
    assert (workspace / "manifest.json").is_file()
    if real_manifest.is_file():
        assert hashlib.sha256(real_manifest.read_bytes()).hexdigest() == digest_before
