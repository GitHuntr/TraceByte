"""Tests for the controlled storage conditions.

The conditions must be deterministic, must never modify the originals and
must keep the experiment under control: the filler may not contain any
signature, so the only false positives are the deliberately planted decoys.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.conditions import (
    CONDITION_CONTIGUOUS,
    CONDITION_FRAGMENTED,
    CONDITION_OVERWRITTEN,
    ConditionError,
    build_image,
    load_ground_truth,
)
from src.hashing import sha256_bytes, sha256_file
from src.manifest import load_manifest
from src.signatures import default_registry


def _build(workspace, condition: str, **kwargs):
    manifest = load_manifest(workspace.manifest_path)
    return build_image(
        condition,
        originals_dir=workspace.originals_dir,
        manifest=manifest,
        output_dir=workspace.experiments_dir,
        experiment_id=f"exp-{condition}",
        **kwargs,
    )


def test_build_image_writes_the_image_and_the_ground_truth(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS)

    image_file = workspace.experiments_dir / "exp-contiguous" / "image.bin"
    truth_file = workspace.experiments_dir / "exp-contiguous" / "ground_truth.json"
    assert image_file.exists()
    assert truth_file.exists()
    assert image.image_sha256 == sha256_file(image_file)
    assert image.size_bytes == image_file.stat().st_size


def test_ground_truth_records_every_original(initialised_workspace) -> None:
    workspace, report = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS)

    assert len(image.ground_truth) == len(report.actions)
    for truth in image.ground_truth:
        assert truth.expected_sha256
        assert truth.total_bytes > 0
        assert truth.ranges


def test_building_an_image_does_not_modify_the_originals(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    before = {
        path.name: sha256_file(path)
        for path in sorted(workspace.originals_dir.iterdir())
        if path.is_file()
    }
    _build(workspace, CONDITION_CONTIGUOUS)
    after = {
        path.name: sha256_file(path)
        for path in sorted(workspace.originals_dir.iterdir())
        if path.is_file()
    }
    assert before == after


def test_the_contiguous_condition_stores_the_originals_unchanged(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS)
    payload = (workspace.experiments_dir / "exp-contiguous" / "image.bin").read_bytes()

    for truth in image.ground_truth:
        original = (workspace.originals_dir / truth.file_id).read_bytes()
        start = truth.ranges[0].start
        assert payload[start : start + len(original)] == original


def test_the_fragmented_condition_scatters_the_originals(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_FRAGMENTED)
    payload = (workspace.experiments_dir / "exp-fragmented" / "image.bin").read_bytes()

    for truth in image.ground_truth:
        assert len(truth.ranges) == 3
        original = (workspace.originals_dir / truth.file_id).read_bytes()
        position = 0
        for item in truth.ranges:
            chunk = payload[item.start : item.end]
            assert chunk == original[position : position + len(chunk)]
            position += len(chunk)
        # The fragments are separated, so the original is not contiguous.
        assert truth.ranges[0].end < truth.ranges[1].start


def test_the_overwritten_condition_replaces_a_range_of_every_original(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_OVERWRITTEN)
    payload = (workspace.experiments_dir / "exp-overwritten" / "image.bin").read_bytes()

    for truth in image.ground_truth:
        assert truth.overwritten is True
        assert truth.overwritten_ranges
        original = (workspace.originals_dir / truth.file_id).read_bytes()
        window = truth.overwritten_ranges[0]
        stored = payload[window.start : window.end]
        assert stored != original[window.start - truth.ranges[0].start :][: len(stored)]
        assert len(stored) == window.length


def test_the_filler_contains_no_signature(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS)
    payload = (workspace.experiments_dir / "exp-contiguous" / "image.bin").read_bytes()

    registry = default_registry()
    expected = {truth.start_offset for truth in image.ground_truth if truth.signature}
    expected.update(
        truth.start_offset + int(embedded["relative_offset"])
        for truth in image.ground_truth
        for embedded in truth.embedded_signatures
    )
    expected.update(int(decoy["offset"]) for decoy in image.planted_false_positives)

    assert {item.offset for item in registry.scan_bytes(payload)} == expected


def test_the_planted_decoys_are_recorded(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS, planted_false_positives=2)
    assert len(image.planted_false_positives) == 2
    assert all(decoy["offset"] >= 0 for decoy in image.planted_false_positives)


def test_no_decoys_can_be_planted(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_CONTIGUOUS, planted_false_positives=0)
    assert image.planted_false_positives == []


def test_building_the_same_condition_twice_gives_the_same_image(
    initialised_workspace,
) -> None:
    workspace, _ = initialised_workspace
    first = _build(workspace, CONDITION_CONTIGUOUS)
    second = _build(workspace, CONDITION_CONTIGUOUS)
    assert first.image_sha256 == second.image_sha256


def test_the_ground_truth_can_be_loaded_again(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_FRAGMENTED)
    restored = load_ground_truth(
        workspace.experiments_dir / "exp-fragmented" / "ground_truth.json"
    )
    assert len(restored) == len(image.ground_truth)
    assert restored[0].file_id == image.ground_truth[0].file_id
    assert restored[0].ranges == image.ground_truth[0].ranges


def test_an_unknown_condition_is_rejected(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    with pytest.raises(ConditionError):
        _build(workspace, "smudged")


def test_a_missing_original_is_reported(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    (workspace.originals_dir / "synthetic_blob_01.bin").unlink()
    with pytest.raises(ConditionError):
        _build(workspace, CONDITION_CONTIGUOUS)


def test_the_image_hash_matches_the_written_file(initialised_workspace) -> None:
    workspace, _ = initialised_workspace
    image = _build(workspace, CONDITION_OVERWRITTEN)
    payload = (workspace.experiments_dir / "exp-overwritten" / "image.bin").read_bytes()
    assert sha256_bytes(payload) == image.image_sha256
