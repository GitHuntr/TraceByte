"""Tests for dataset initialisation and the synthetic fixture generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.fixtures import (
    FIXTURE_SPECS,
    JPEG_APP0_HEADER,
    PDF_HEADER,
    SYNTHETIC_MARKER,
    ZIP_LOCAL_HEADER,
    initialize_dataset,
)
from src.hashing import sha256_file
from src.manifest import load_manifest
from src.paths import NON_FIXTURE_FILES

from .conftest import Workspace


def test_fixture_generation_is_deterministic() -> None:
    for spec in FIXTURE_SPECS:
        first = spec.build()
        second = spec.build()
        assert first == second, f"{spec.filename} is not deterministic"
        assert len(first) > 0


def test_signature_bearing_fixtures_start_with_their_signature() -> None:
    by_name = {spec.filename: spec for spec in FIXTURE_SPECS}
    assert by_name["synthetic_photo_01.jpg"].build().startswith(JPEG_APP0_HEADER)
    assert by_name["synthetic_doc_01.pdf"].build().startswith(PDF_HEADER)
    assert by_name["synthetic_archive_01.zip"].build().startswith(ZIP_LOCAL_HEADER)


def test_blob_fixture_has_no_known_signature() -> None:
    blob = next(spec for spec in FIXTURE_SPECS if spec.filename == "synthetic_blob_01.bin")
    assert blob.signature_hex == ""
    assert blob.signature_offset is None
    assert blob.build()[:2] != b"\xff\xd8"


def test_fixtures_are_labelled_as_synthetic() -> None:
    for spec in FIXTURE_SPECS:
        if spec.filename == "synthetic_blob_01.bin":
            continue
        assert SYNTHETIC_MARKER in spec.build(), spec.filename
        assert "synthetic" in spec.filename
        assert "NOT A VALID" in spec.description or "not" in spec.description.lower()


def test_embedded_signature_fixture_has_signature_at_declared_offset() -> None:
    container = next(
        spec for spec in FIXTURE_SPECS if spec.filename == "synthetic_container_01.bin"
    )
    payload = container.build()
    assert container.signature_offset == 1024
    assert payload[1024:1028] == JPEG_APP0_HEADER[:4]


def test_initialize_dataset_creates_files_and_manifest(workspace: Workspace) -> None:
    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    assert report.manifest_created is True
    assert report.created_count == len(FIXTURE_SPECS)
    assert report.preserved_count == 0
    assert report.mismatch_count == 0

    for spec in FIXTURE_SPECS:
        target = workspace.originals_dir / spec.filename
        assert target.exists(), f"{spec.filename} was not created"
        assert target.stat().st_size == len(spec.build())

    assert workspace.manifest_path.exists()
    manifest = load_manifest(workspace.manifest_path)
    assert len(manifest.entries) == len(FIXTURE_SPECS)


def test_manifest_records_size_hash_and_description(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    raw = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert raw["manifest_version"]
    assert raw["created_utc"]
    assert raw["updated_utc"]
    assert raw["tool_versions"]["python"]
    assert len(raw["fixtures"]) == len(FIXTURE_SPECS)

    for record in raw["fixtures"]:
        assert record["filename"]
        assert record["size_bytes"] > 0
        assert len(record["sha256"]) == 64
        assert record["description"]
        assert record["synthetic"] is True
        assert record["fully_parseable"] is False

        target = workspace.originals_dir / record["filename"]
        assert sha256_file(target) == record["sha256"]
        assert target.stat().st_size == record["size_bytes"]


def test_initialize_dataset_leaves_no_temporary_files(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    leftovers = [
        path.name
        for path in workspace.originals_dir.iterdir()
        if path.name.endswith(".tmp") or path.name.startswith(".")
    ]
    assert leftovers == []


def test_initialize_dataset_is_idempotent(workspace: Workspace) -> None:
    """A second run must not rewrite the originals or their baseline hashes."""
    first = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest_before = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    stat_before = {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in workspace.originals_dir.iterdir()
        if path.is_file() and path.name not in NON_FIXTURE_FILES
    }

    second = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest_after = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    stat_after = {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in workspace.originals_dir.iterdir()
        if path.is_file() and path.name not in NON_FIXTURE_FILES
    }

    assert second.manifest_created is False
    assert second.created_count == 0
    assert second.preserved_count == len(FIXTURE_SPECS)
    assert second.mismatch_count == 0

    assert stat_before == stat_after, "an original was rewritten during re-initialisation"
    assert manifest_before["fixtures"] == manifest_after["fixtures"], (
        "baseline hashes changed during re-initialisation"
    )
    assert first.created_count == second.preserved_count


def test_repeated_initialisation_leaves_the_manifest_byte_identical(
    workspace: Workspace,
) -> None:
    """An unchanged baseline must not be rewritten - byte for byte.

    The manifest is the evidence record of the ground truth. Re-running the
    initialisation must not touch it, not even its ``updated_utc`` stamp.
    """
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    bytes_before = workspace.manifest_path.read_bytes()
    digest_before = sha256_file(workspace.manifest_path)
    updated_before = json.loads(bytes_before)["updated_utc"]

    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    bytes_after = workspace.manifest_path.read_bytes()
    assert report.manifest_written is False
    assert bytes_after == bytes_before, "the manifest was rewritten without a reason"
    assert sha256_file(workspace.manifest_path) == digest_before
    assert json.loads(bytes_after)["updated_utc"] == updated_before
    assert json.loads(bytes_after)["fixtures"] == json.loads(bytes_before)["fixtures"]


def test_the_manifest_is_refreshed_when_the_tool_versions_change(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded tool versions are the one metadata block that is refreshed.

    If they change, the manifest is rewritten and ``updated_utc`` moves - and
    nothing else about the baseline changes.
    """
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    before = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    changed = dict(before["tool_versions"])
    changed["python"] = "0.0.0-test"

    monkeypatch.setattr("src.fixtures.tool_versions", lambda: changed)
    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    refreshed = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert report.manifest_written is True
    assert refreshed["tool_versions"]["python"] == "0.0.0-test"
    assert refreshed["fixtures"] == before["fixtures"], "a baseline hash changed"


def test_dataset_notes_are_written_next_to_the_fixtures(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    notes = workspace.originals_dir / "FIXTURE_NOTES.md"
    assert notes.exists()
    text = notes.read_text(encoding="utf-8")
    assert "synthetic" in text.lower()
    assert "not" in text.lower()


def test_dataset_state_excludes_non_fixtures(workspace: Workspace) -> None:
    """dataset_state() must list only actual fixture files, excluding
    manifest.json and FIXTURE_NOTES.md.
    """
    from src.fixtures import dataset_state

    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    state = dataset_state(workspace.originals_dir)
    expected_names = sorted(spec.filename for spec in FIXTURE_SPECS)
    assert state["files_present"] == expected_names
    assert state["file_count"] == len(FIXTURE_SPECS)
    assert "manifest.json" not in state["files_present"]
    assert "FIXTURE_NOTES.md" not in state["files_present"]


def test_initialize_dataset_with_custom_spec(workspace: Workspace) -> None:
    """Passing a single custom FixtureSpec via specs= must create ONLY that
    fixture and record only that entry in the manifest.
    """
    from src.fixtures import FixtureSpec

    custom = FixtureSpec(
        fixture_id="fx-custom-01",
        filename="custom_test.bin",
        description="Custom test fixture",
        _builder=lambda: b"CUSTOM-CONTENT-1234",
    )
    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
        specs=(custom,),
        write_notes=False,
    )
    assert report.created_count == 1
    assert (workspace.originals_dir / "custom_test.bin").exists()
    assert (workspace.originals_dir / "custom_test.bin").read_bytes() == b"CUSTOM-CONTENT-1234"

    manifest = load_manifest(workspace.manifest_path)
    assert list(manifest.entries.keys()) == ["custom_test.bin"]

    for spec in FIXTURE_SPECS:
        assert not (workspace.originals_dir / spec.filename).exists()


def test_initialize_dataset_write_notes_false(workspace: Workspace) -> None:
    """When write_notes=False, FIXTURE_NOTES.md must not be created in the
    originals directory.
    """
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
        write_notes=False,
    )
    assert not (workspace.originals_dir / "FIXTURE_NOTES.md").exists()

