"""Tests for the experiment runner.

A run must produce every artefact on disk, must append to the experiment log
and must never touch the originals.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiment_log import ExperimentLog
from src.experiments import (
    CARVE_REPORT_NAME,
    METRICS_NAME,
    experiment_id_for,
    load_experiment_metrics,
    run_all_conditions,
    run_condition,
)
from src.hashing import sha256_file


def _run(workspace, condition: str, log=None):
    return run_condition(
        condition,
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
        log=log,
    )


def test_the_experiment_id_is_deterministic() -> None:
    assert experiment_id_for("contiguous") == "exp-contiguous"
    assert experiment_id_for("fragmented") == "exp-fragmented"


def test_a_run_writes_every_artefact(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")

    experiment_dir = workspace.experiments_dir / "exp-contiguous"
    assert (experiment_dir / "image.bin").exists()
    assert (experiment_dir / "ground_truth.json").exists()
    assert (experiment_dir / CARVE_REPORT_NAME).exists()
    assert (experiment_dir / METRICS_NAME).exists()
    assert result.metrics is not None


def test_the_carved_candidates_are_written_to_the_recovered_folder(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")

    recovered = workspace.recovered_dir / "exp-contiguous"
    written = sorted(path.name for path in recovered.iterdir())
    assert written
    assert all(path.endswith((".jpg", ".pdf", ".zip")) for path in written)


def test_the_carve_report_contains_the_provenance(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    _run(workspace, "contiguous")

    report = json.loads(
        (workspace.experiments_dir / "exp-contiguous" / CARVE_REPORT_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert report["candidate_count"] == len(report["candidates"])
    first = report["candidates"][0]
    assert first["source_path"]
    assert first["source_sha256"]
    assert first["tool_version"]
    assert first["experiment_id"] == "exp-contiguous"
    assert first["condition"] == "contiguous"
    assert first["offset"] >= 0


def test_the_metrics_file_is_valid_json(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    _run(workspace, "contiguous")

    metrics = json.loads(
        (workspace.experiments_dir / "exp-contiguous" / METRICS_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert metrics["condition"] == "contiguous"
    assert metrics["detection"]["tp"] >= 0
    assert len(metrics["outcomes"]) == metrics["ground_truth_files"]


def test_a_run_does_not_modify_the_originals(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    before = {
        path.name: sha256_file(path)
        for path in sorted(workspace.originals_dir.iterdir())
        if path.is_file()
    }
    _run(workspace, "contiguous")
    after = {
        path.name: sha256_file(path)
        for path in sorted(workspace.originals_dir.iterdir())
        if path.is_file()
    }
    assert before == after


def test_a_run_appends_an_event_to_the_experiment_log(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    log = ExperimentLog(workspace.log_path)
    _run(workspace, "contiguous", log=log)

    events = log.read_events()
    assert len(events) == 1
    assert events[0]["event"] == "experiment_completed"
    assert events[0]["actor"] == "filecarvelab.stage2"
    assert events[0]["payload"]["condition"] == "contiguous"


def test_all_three_conditions_can_be_run(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    results = run_all_conditions(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
    )
    assert [item.condition for item in results] == [
        "contiguous",
        "fragmented",
        "overwritten",
    ]
    assert all(item.metrics is not None for item in results)


def test_the_measurements_can_be_read_back(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    run_all_conditions(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
    )
    metrics = load_experiment_metrics(workspace.experiments_dir)
    assert [item.condition for item in metrics] == [
        "contiguous",
        "fragmented",
        "overwritten",
    ]
    assert metrics[0].detection.tp > 0


def test_the_contiguous_condition_recovers_the_files_with_an_end_marker(
    initialised_workspace,
) -> None:
    """Only the fixtures that carry a terminator can be recovered byte-exactly."""
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")
    metrics = result.metrics
    assert metrics is not None

    exact = {outcome.file_id for outcome in metrics.outcomes if outcome.exact}
    assert "synthetic_len_photo_01.jpg" in exact
    assert "synthetic_len_doc_01.pdf" in exact
    assert "synthetic_len_archive_01.zip" in exact


def test_the_fragmented_condition_cannot_recover_a_file_byte_exactly(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "fragmented")
    metrics = result.metrics
    assert metrics is not None
    assert metrics.exact_recovery.tp == 0
    assert metrics.data_completeness == 1.0
    assert 0.0 < metrics.mean_byte_coverage < 1.0


def test_the_overwritten_condition_loses_data_completeness(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "overwritten")
    metrics = result.metrics
    assert metrics is not None
    assert metrics.data_completeness < 1.0
    assert metrics.exact_recovery.tp == 0


def test_the_planted_decoys_are_measured_as_false_positives(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")
    metrics = result.metrics
    assert metrics is not None
    assert metrics.detection.fp == 2
    assert metrics.detection.fn == 0
    assert metrics.detection.recall == 1.0
