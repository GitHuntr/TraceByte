"""Integration tests against the committed baseline evidence set.

These tests verify the ground truth tracked in git. They are strictly
read-only — nothing in this module writes to ``data/originals/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.fixtures import FIXTURE_SPECS
from src.hashing import sha256_file
from src.manifest import load_manifest
from src.paths import EXPERIMENTS_DIR, ORIGINALS_DIR, RECOVERED_DIR

MANIFEST_PATH = ORIGINALS_DIR / "manifest.json"
EXPECTED_FILENAMES = sorted(spec.filename for spec in FIXTURE_SPECS)


def _skip_if_no_baseline() -> None:
    if not MANIFEST_PATH.exists():
        pytest.skip("Baseline manifest not found; skipping repo-baseline checks.")


@pytest.mark.integration
def test_baseline_hashes_match_files_on_disk() -> None:
    """Every entry in the committed manifest must match the SHA-256 digest
    and file size of the corresponding file in data/originals/.
    """
    _skip_if_no_baseline()
    manifest = load_manifest(MANIFEST_PATH)

    for filename in manifest.filenames():
        entry = manifest.entries[filename]
        file_path = ORIGINALS_DIR / filename
        assert file_path.exists(), f"{filename} is recorded but missing on disk"
        assert sha256_file(file_path) == entry.sha256, (
            f"{filename}: SHA-256 mismatch"
        )
        assert file_path.stat().st_size == entry.size_bytes, (
            f"{filename}: size mismatch"
        )


@pytest.mark.integration
def test_baseline_entries_are_synthetic_and_not_fully_parseable() -> None:
    """Every fixture in the committed manifest must be flagged as synthetic
    and not fully parseable, because no fixture is a valid media file.
    """
    _skip_if_no_baseline()
    manifest = load_manifest(MANIFEST_PATH)

    for filename in manifest.filenames():
        entry = manifest.entries[filename]
        assert entry.synthetic is True, f"{filename}: synthetic flag is not True"
        assert entry.fully_parseable is False, (
            f"{filename}: fully_parseable flag is not False"
        )


@pytest.mark.integration
def test_expected_fixture_filenames_are_present() -> None:
    """The five declared fixture filenames must all appear in the committed
    manifest, and no more and no fewer.
    """
    _skip_if_no_baseline()
    manifest = load_manifest(MANIFEST_PATH)
    assert sorted(manifest.filenames()) == EXPECTED_FILENAMES


@pytest.mark.integration
def test_experiments_and_recovered_contain_no_fixture_files() -> None:
    """The data/experiments/ and data/recovered/ directories must not contain
    any of the five fixture filenames — originals are never copied there.
    """
    _skip_if_no_baseline()
    fixture_names = {spec.filename for spec in FIXTURE_SPECS}

    for directory in (EXPERIMENTS_DIR, RECOVERED_DIR):
        if not directory.exists():
            continue
        names_on_disk = {p.name for p in directory.iterdir() if p.is_file()}
        overlap = fixture_names & names_on_disk
        assert overlap == set(), (
            f"fixture files found in {directory.name}/: {overlap}"
        )
