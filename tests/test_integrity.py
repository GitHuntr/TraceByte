"""Tests for evidence-integrity verification against the baseline."""

from __future__ import annotations

from pathlib import Path

from src.fixtures import initialize_dataset
from src.integrity import (
    IntegrityStatus,
    detection_self_test,
    detect_unregistered_files,
    run_integrity_check,
    summarize,
    verify_entry,
    verify_manifest,
)
from src.manifest import load_manifest

from .conftest import Workspace


def test_untouched_fixtures_verify_as_match(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)

    results = verify_manifest(manifest, workspace.originals_dir)
    assert len(results) == len(manifest.entries)
    assert all(result.status is IntegrityStatus.MATCH for result in results)
    assert all(result.is_ok for result in results)


def test_modified_copy_is_detected_as_changed(workspace: Workspace) -> None:
    """A modified *copy* must be reported as a mismatch."""
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    entry = manifest.entries["synthetic_doc_01.pdf"]

    copy_dir = workspace.root / "copy"
    copy_dir.mkdir()
    copy_path = copy_dir / entry.filename
    copy_path.write_bytes((workspace.originals_dir / entry.filename).read_bytes())

    assert verify_entry(entry, copy_dir).status is IntegrityStatus.MATCH

    data = bytearray(copy_path.read_bytes())
    data[0] = ord("%")
    data[1] = ord("X")
    copy_path.write_bytes(bytes(data))

    result = verify_entry(entry, copy_dir)
    assert result.status is IntegrityStatus.MISMATCH
    assert result.expected_sha256 == entry.sha256
    assert result.actual_sha256 != entry.sha256
    assert "not" in result.message.lower()


def test_missing_file_is_detected(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    entry = manifest.entries["synthetic_blob_01.bin"]
    (workspace.originals_dir / entry.filename).unlink()

    result = verify_entry(entry, workspace.originals_dir)
    assert result.status is IntegrityStatus.MISSING
    assert result.expected_sha256 == entry.sha256
    assert result.actual_sha256 == ""
    assert "missing" in result.message.lower()


def test_unregistered_file_is_detected(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    (workspace.originals_dir / "unexpected_extra.bin").write_bytes(b"surprise")

    results = detect_unregistered_files(manifest, workspace.originals_dir)
    assert len(results) == 1
    assert results[0].filename == "unexpected_extra.bin"
    assert results[0].status is IntegrityStatus.UNREGISTERED


def test_summary_counts_every_status(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    (workspace.originals_dir / "synthetic_blob_01.bin").unlink()
    (workspace.originals_dir / "extra.bin").write_bytes(b"x")

    results = run_integrity_check(manifest, workspace.originals_dir)
    summary = summarize(results)

    assert summary["MATCH"] == len(manifest.entries) - 1
    assert summary["MISSING"] == 1
    assert summary["UNREGISTERED"] == 1
    assert summary["MISMATCH"] == 0


def test_detection_self_test_does_not_touch_the_originals(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    before = {
        path.name: path.read_bytes()
        for path in workspace.originals_dir.iterdir()
        if path.is_file()
    }

    outcome = detection_self_test(manifest, workspace.originals_dir)

    after = {
        path.name: path.read_bytes()
        for path in workspace.originals_dir.iterdir()
        if path.is_file()
    }
    assert before == after, "the self-test modified the originals"
    assert outcome["ok"] is True
    assert outcome["baseline_status"] == "MATCH"
    assert outcome["mutated_status"] == "MISMATCH"
    assert outcome["mutated_sha256"] != outcome["expected_sha256"]


def test_verification_is_read_only(workspace: Workspace) -> None:
    """Verifying must not change the originals or the manifest."""
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest_path = workspace.manifest_path
    manifest_bytes_before = manifest_path.read_bytes()
    originals_before = {
        path.name: path.read_bytes()
        for path in workspace.originals_dir.iterdir()
        if path.is_file()
    }

    manifest = load_manifest(manifest_path)
    run_integrity_check(manifest, workspace.originals_dir)

    assert manifest_path.read_bytes() == manifest_bytes_before
    originals_after = {
        path.name: path.read_bytes()
        for path in workspace.originals_dir.iterdir()
        if path.is_file()
    }
    assert originals_before == originals_after
