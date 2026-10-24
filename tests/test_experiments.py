"""Tests for the experiment runner.

A run must produce every artefact on disk, must append to the experiment log
and must never touch the originals.

Every run owns a directory of its own, so a later run can never overwrite the
artefacts of an earlier one.
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
    LEGACY_RUN_ID,
    METRICS_NAME,
    RUN_MANIFEST_NAME,
    experiment_id_for,
    latest_run,
    list_runs,
    load_experiment_metrics,
    load_run_manifest,
    new_run_id,
    run_all_conditions,
    run_condition,
)
from src.hashing import sha256_file
from src.manifest import Manifest, load_manifest


def _run(workspace, condition: str, log=None, **kwargs):
    return run_condition(
        condition,
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
        log=log,
        **kwargs,
    )


def test_the_experiment_id_is_deterministic() -> None:
    assert experiment_id_for("contiguous") == "exp-contiguous"
    assert experiment_id_for("fragmented") == "exp-fragmented"


def test_the_run_id_is_unique() -> None:
    first = new_run_id()
    second = new_run_id()
    assert first != second
    assert first.startswith("run-")


def test_a_run_writes_every_artefact(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")

    experiment_dir = workspace.experiments_dir / result.run_id / "exp-contiguous"
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

    recovered = workspace.recovered_dir / result.run_id / "exp-contiguous"
    written = sorted(path.name for path in recovered.iterdir())
    assert written
    assert all(path.endswith((".jpg", ".pdf", ".zip")) for path in written)


def test_the_carve_report_contains_the_provenance(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    result = _run(workspace, "contiguous")

    report = json.loads(
        (
            workspace.experiments_dir
            / result.run_id
            / "exp-contiguous"
            / CARVE_REPORT_NAME
        ).read_text(encoding="utf-8")
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
    result = _run(workspace, "contiguous")

    metrics = json.loads(
        (
            workspace.experiments_dir
            / result.run_id
            / "exp-contiguous"
            / METRICS_NAME
        ).read_text(encoding="utf-8")
    )
    assert metrics["condition"] == "contiguous"
    assert metrics["detection"]["tp"] >= 0
    assert len(metrics["outcomes"]) == metrics["ground_truth_files"]
    assert metrics["run_id"] == result.run_id


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
    result = _run(workspace, "contiguous", log=log)

    events = log.read_events()
    assert len(events) == 1
    assert events[0]["event"] == "experiment_completed"
    assert events[0]["actor"] == "filecarvelab.stage2"
    assert events[0]["payload"]["condition"] == "contiguous"
    assert events[0]["payload"]["experiment_run_id"] == result.run_id


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


# -- artefact hygiene ----------------------------------------------------


def test_each_run_gets_its_own_output_directory(initialised_workspace) -> None:
    """Two runs never share a directory, so they cannot overwrite each other."""
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    second = _run(workspace, "contiguous")

    assert first.run_id != second.run_id
    assert (workspace.experiments_dir / first.run_id / "exp-contiguous").is_dir()
    assert (workspace.experiments_dir / second.run_id / "exp-contiguous").is_dir()


def test_a_later_run_never_deletes_the_earlier_candidates(
    initialised_workspace,
) -> None:
    """A new run must leave the candidates of an earlier run untouched."""
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    first_dir = workspace.recovered_dir / first.run_id / "exp-contiguous"
    before = {
        path.name: sha256_file(path) for path in sorted(first_dir.iterdir())
    }
    assert before

    second = _run(workspace, "fragmented")

    after = {path.name: sha256_file(path) for path in sorted(first_dir.iterdir())}
    assert after == before
    assert (workspace.recovered_dir / second.run_id / "exp-fragmented").is_dir()


def test_a_run_with_fewer_candidates_keeps_the_earlier_artefacts(
    initialised_workspace,
) -> None:
    """A run that produces fewer candidates must not remove the old ones.

    The second run builds its image from a reduced manifest, so it finds
    fewer signatures and carves fewer candidates than the first run.
    """
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    first_dir = workspace.recovered_dir / first.run_id / "exp-contiguous"
    first_files = sorted(path.name for path in first_dir.iterdir())
    assert first_files

    full_manifest = load_manifest(workspace.manifest_path)
    reduced_manifest = Manifest(
        entries=dict(list(full_manifest.entries.items())[:2]),
    )
    second = _run(workspace, "contiguous", manifest=reduced_manifest)
    second_dir = workspace.recovered_dir / second.run_id / "exp-contiguous"
    second_files = sorted(path.name for path in second_dir.iterdir())

    assert len(second_files) < len(first_files)
    assert sorted(path.name for path in first_dir.iterdir()) == first_files
    assert first_dir != second_dir


def test_the_metrics_of_an_earlier_run_are_still_readable(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    second = _run(workspace, "fragmented")

    first_metrics = load_experiment_metrics(workspace.experiments_dir, first.run_id)
    second_metrics = load_experiment_metrics(workspace.experiments_dir, second.run_id)

    assert [item.condition for item in first_metrics] == ["contiguous"]
    assert [item.condition for item in second_metrics] == ["fragmented"]
    assert first_metrics[0].run_id == first.run_id
    assert second_metrics[0].run_id == second.run_id


def test_only_the_latest_run_is_loaded_by_default(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    second = _run(workspace, "fragmented")

    metrics = load_experiment_metrics(workspace.experiments_dir)
    assert [item.condition for item in metrics] == ["fragmented"]
    assert metrics[0].run_id == second.run_id

    latest = latest_run(workspace.experiments_dir)
    assert latest is not None
    assert latest.run_id == second.run_id
    assert first.run_id != latest.run_id


def test_the_run_manifest_records_every_condition(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    results = run_all_conditions(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
    )
    run_id = results[0].run_id

    manifest = load_run_manifest(workspace.experiments_dir / run_id / RUN_MANIFEST_NAME)
    assert manifest["run_id"] == run_id
    assert manifest["created_utc"]
    assert [entry["experiment_id"] for entry in manifest["conditions"]] == [
        "exp-contiguous",
        "exp-fragmented",
        "exp-overwritten",
    ]


def test_the_runs_on_disk_are_discovered(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    first = _run(workspace, "contiguous")
    second = _run(workspace, "fragmented")

    runs = list_runs(workspace.experiments_dir)
    assert [run.run_id for run in runs] == [first.run_id, second.run_id]
    assert all(not run.legacy for run in runs)


def test_the_artefacts_of_the_old_layout_are_still_readable(
    initialised_workspace,
) -> None:
    """Artefacts written before the per-run layout stay accessible."""
    workspace, _ = initialised_workspace
    legacy_dir = workspace.experiments_dir / "exp-contiguous"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / METRICS_NAME).write_text(
        json.dumps(
            {
                "condition": "contiguous",
                "experiment_id": "exp-contiguous",
                "image_path": "legacy/image.bin",
                "image_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    runs = list_runs(workspace.experiments_dir)
    legacy_runs = [run for run in runs if run.legacy]
    assert len(legacy_runs) == 1
    assert legacy_runs[0].run_id == LEGACY_RUN_ID

    metrics = load_experiment_metrics(workspace.experiments_dir, LEGACY_RUN_ID)
    assert [item.condition for item in metrics] == ["contiguous"]
    assert metrics[0].run_id == LEGACY_RUN_ID


def test_invalid_run_ids_and_path_traversal_are_rejected(initialised_workspace) -> None:
    """Run identifiers with traversal characters or wrong format must be rejected."""
    workspace, _ = initialised_workspace
    import pytest

    for bad_id in ("../escaped", "sub/dir", "...", "run-invalid-format", "run/123"):
        with pytest.raises(ValueError, match="Invalid run_id"):
            run_condition("contiguous", originals_dir=workspace.originals_dir,
                          manifest_path=workspace.manifest_path,
                          experiments_dir=workspace.experiments_dir,
                          recovered_dir=workspace.recovered_dir,
                          run_id=bad_id)


def test_existing_condition_within_run_cannot_be_overwritten(initialised_workspace) -> None:
    """Attempting to rerun the same condition with the same run_id must raise ValueError."""
    workspace, _ = initialised_workspace
    import pytest

    rid = new_run_id()
    _run(workspace, "contiguous", run_id=rid)
    with pytest.raises(ValueError, match="already exists"):
        _run(workspace, "contiguous", run_id=rid)


def test_run_manifest_has_explicit_status(initialised_workspace) -> None:
    """Full run has status='complete' and single-condition run has status='partial'."""
    workspace, _ = initialised_workspace

    # Single condition run
    rid = new_run_id()
    _run(workspace, "contiguous", run_id=rid)
    rm = load_run_manifest(workspace.experiments_dir / rid / RUN_MANIFEST_NAME)
    assert rm.get("status") == "partial"

    # Full multi-condition run
    full_results = run_all_conditions(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        experiments_dir=workspace.experiments_dir,
        recovered_dir=workspace.recovered_dir,
    )
    full_rid = full_results[0].run_id
    full_rm = load_run_manifest(workspace.experiments_dir / full_rid / RUN_MANIFEST_NAME)
    assert full_rm.get("status") == "complete"
    assert full_rm.get("run_id") == full_rid


def test_directory_without_run_manifest_is_discovered_as_unknown(initialised_workspace) -> None:
    """Directories created without run.json remain discoverable as status='unknown'."""
    workspace, _ = initialised_workspace

    incomplete_dir = workspace.experiments_dir / "run-20261021T120000Z-deadbeef"
    incomplete_dir.mkdir(parents=True)
    (incomplete_dir / "exp-contiguous").mkdir()
    (incomplete_dir / "exp-contiguous" / METRICS_NAME).write_text("{}", encoding="utf-8")

    runs = list_runs(workspace.experiments_dir)
    matching = [r for r in runs if r.run_id == incomplete_dir.name]
    assert len(matching) == 1
    assert matching[0].status == "unknown"


def test_malformed_run_manifest_does_not_crash_list_runs(initialised_workspace) -> None:
    """A corrupted run.json is handled gracefully and does not crash list_runs."""
    workspace, _ = initialised_workspace

    bad_dir = workspace.experiments_dir / "run-20261021T120000Z-badbad00"
    bad_dir.mkdir(parents=True)
    (bad_dir / RUN_MANIFEST_NAME).write_text("{corrupt json!!", encoding="utf-8")

    # Does not raise
    runs = list_runs(workspace.experiments_dir)
    assert isinstance(runs, list)

