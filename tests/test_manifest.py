"""Tests for the baseline manifest and the preservation guarantees.

The central property under test: a recorded baseline SHA-256 is written once
and is never silently replaced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experiment_log import ExperimentLog
from src.fixtures import initialize_dataset
from src.hashing import sha256_file
from src.manifest import (
    FixtureEntry,
    Manifest,
    load_manifest,
    rebaseline_entry,
    save_manifest,
)
from src.paths import NON_FIXTURE_FILES

from .conftest import Workspace


def _entry(filename: str = "a.bin", digest: str = "a" * 64) -> FixtureEntry:
    return FixtureEntry(
        fixture_id="fx-a",
        filename=filename,
        relative_path=f"data/originals/{filename}",
        size_bytes=10,
        sha256=digest,
        description="test fixture",
    )


def test_record_baseline_creates_then_preserves() -> None:
    manifest = Manifest()
    action, stored = manifest.record_baseline(_entry())
    assert action == "created"
    assert stored.sha256 == "a" * 64

    action, stored = manifest.record_baseline(_entry(digest="b" * 64))
    assert action == "preserved"
    assert stored.sha256 == "a" * 64, "an existing baseline was replaced"
    assert manifest.baseline_sha256("a.bin") == "a" * 64


def test_missing_manifest_returns_empty_manifest(tmp_path: Path) -> None:
    manifest = load_manifest(tmp_path / "nothing.json")
    assert manifest.entries == {}


def test_corrupt_manifest_raises_value_error(tmp_path: Path) -> None:
    broken = tmp_path / "manifest.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(broken)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    manifest = Manifest()
    manifest.record_baseline(_entry())
    path = save_manifest(manifest, tmp_path / "manifest.json")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["manifest_version"]
    assert data["fixtures"][0]["filename"] == "a.bin"

    reloaded = load_manifest(path)
    assert reloaded.baseline_sha256("a.bin") == "a" * 64


def test_save_manifest_leaves_no_temporary_file(tmp_path: Path) -> None:
    manifest = Manifest()
    manifest.record_baseline(_entry())
    save_manifest(manifest, tmp_path / "manifest.json")
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_reinitialisation_does_not_update_the_baseline_hash(
    workspace: Workspace,
) -> None:
    """The acceptance criterion: originals and baselines survive a re-run."""
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest_before = load_manifest(workspace.manifest_path)
    baseline_before = {
        name: entry.sha256 for name, entry in manifest_before.entries.items()
    }

    # Tamper with one original, exactly like an accidental or hostile edit.
    victim = workspace.originals_dir / "synthetic_photo_01.jpg"
    tampered = bytearray(victim.read_bytes())
    tampered[10] ^= 0xFF
    victim.write_bytes(bytes(tampered))

    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    manifest_after = load_manifest(workspace.manifest_path)
    baseline_after = {
        name: entry.sha256 for name, entry in manifest_after.entries.items()
    }

    assert baseline_before == baseline_after, "a baseline hash was regenerated"
    assert manifest_after.baseline_sha256("synthetic_photo_01.jpg") == baseline_before[
        "synthetic_photo_01.jpg"
    ]

    # The tampered original must not have been silently restored or overwritten.
    assert victim.read_bytes() == bytes(tampered)

    # ... but the mismatch must be reported.
    assert report.mismatch_count == 1
    assert report.preserved_count == len(baseline_before)
    assert any("synthetic_photo_01.jpg" in warning for warning in report.warnings)


def test_reinitialisation_preserves_untouched_originals_byte_for_byte(
    workspace: Workspace,
) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    before = {
        path.name: sha256_file(path)
        for path in workspace.originals_dir.iterdir()
        if path.is_file() and path.name not in NON_FIXTURE_FILES
    }

    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    after = {
        path.name: sha256_file(path)
        for path in workspace.originals_dir.iterdir()
        if path.is_file() and path.name not in NON_FIXTURE_FILES
    }
    assert before == after

    # The manifest itself is refreshed (updated_utc), but its baseline records
    # must be byte-identical.
    manifest_after = load_manifest(workspace.manifest_path)
    assert {
        name: entry.sha256 for name, entry in manifest_after.entries.items()
    } == before


def test_existing_file_without_baseline_is_adopted_and_flagged(
    workspace: Workspace,
) -> None:
    """An unknown file on disk must be flagged, never silently baselined."""
    stranger = workspace.originals_dir / "synthetic_photo_01.jpg"
    stranger.write_bytes(b"unknown-content")

    report = initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )

    manifest = load_manifest(workspace.manifest_path)
    entry = manifest.entries["synthetic_photo_01.jpg"]
    assert entry.baseline_origin == "adopted-existing-unregistered"
    assert entry.sha256 == sha256_file(stranger)
    assert report.adopted_count == 1
    assert any("without a baseline entry" in warning for warning in report.warnings)


def test_rebaseline_requires_a_reason_and_is_logged(workspace: Workspace) -> None:
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    log = ExperimentLog(workspace.log_path)

    with pytest.raises(ValueError):
        rebaseline_entry(
            manifest,
            "synthetic_photo_01.jpg",
            "f" * 64,
            reason="   ",
            log=log,
            manifest_path=workspace.manifest_path,
        )

    rebaseline_entry(
        manifest,
        "synthetic_photo_01.jpg",
        "f" * 64,
        reason="fixture regenerated after a documented re-seed",
        log=log,
        manifest_path=workspace.manifest_path,
    )

    updated = load_manifest(workspace.manifest_path)
    assert updated.baseline_sha256("synthetic_photo_01.jpg") == "f" * 64
    assert updated.entries["synthetic_photo_01.jpg"].baseline_origin == (
        "rebaselined-by-operator"
    )

    events = ExperimentLog(workspace.log_path, enabled=False).read_events()
    assert any(event["event"] == "manifest.rebaseline" for event in events)


def test_rebaseline_on_unknown_fixture_raises(tmp_path: Path) -> None:
    manifest = Manifest()
    with pytest.raises(KeyError):
        rebaseline_entry(
            manifest,
            "nope.bin",
            "f" * 64,
            reason="does not exist",
            manifest_path=tmp_path / "manifest.json",
        )


def test_manifest_summary_returns_documented_keys(workspace: Workspace) -> None:
    """manifest_summary() must return exactly the documented keys and the
    fixture_count / total_bytes values must agree with the entry list.
    """
    from src.manifest import manifest_summary

    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    summary = manifest_summary(manifest)

    expected_keys = {
        "manifest_version",
        "project",
        "dataset_name",
        "created_utc",
        "updated_utc",
        "fixture_count",
        "total_bytes",
        "tool_versions",
    }
    assert set(summary.keys()) == expected_keys

    assert summary["fixture_count"] == len(manifest.entries)
    assert summary["total_bytes"] == sum(
        entry.size_bytes for entry in manifest.entries.values()
    )


def test_iter_entries_yields_sorted_by_filename(workspace: Workspace) -> None:
    """iter_entries() must yield entries in ascending filename order."""
    from src.manifest import iter_entries

    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=None,
    )
    manifest = load_manifest(workspace.manifest_path)
    filenames = [entry.filename for entry in iter_entries(manifest)]
    assert filenames == sorted(filenames)
    assert len(filenames) == len(manifest.entries)


def test_signature_offset_none_round_trips_as_json_null(tmp_path: Path) -> None:
    """A FixtureEntry with signature_offset=None must serialise as JSON null
    and deserialise back to None — not 0, not a missing key.
    """
    manifest = Manifest()
    entry = _entry()
    entry.signature_offset = None
    manifest.record_baseline(entry)

    path = save_manifest(manifest, tmp_path / "manifest.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    fixture_record = raw["fixtures"][0]
    assert "signature_offset" in fixture_record
    assert fixture_record["signature_offset"] is None

    reloaded = load_manifest(path)
    reloaded_entry = reloaded.entries["a.bin"]
    assert reloaded_entry.signature_offset is None

