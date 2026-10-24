"""Tests for the canonical filesystem layout and path utilities.

These tests verify that the project-directory contract is upheld and that
helper functions produce correct, portable path representations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.paths as paths
from src.fixtures import FIXTURE_SPECS


def test_ensure_project_directories_creates_required_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure_project_directories() must create every directory listed in
    REQUIRED_DIRECTORIES; calling it a second time must not raise and must
    leave the directories intact (idempotency).
    """
    temp_dirs = tuple(tmp_path / f"dir_{i}" for i in range(len(paths.REQUIRED_DIRECTORIES)))
    monkeypatch.setattr(paths, "REQUIRED_DIRECTORIES", temp_dirs)

    paths.ensure_project_directories()
    for directory in temp_dirs:
        assert directory.is_dir(), f"{directory} was not created"

    paths.ensure_project_directories()
    for directory in temp_dirs:
        assert directory.is_dir(), f"{directory} disappeared after idempotent call"


def test_relative_to_project_inside_project() -> None:
    """A path inside the project root must be returned as a posix-style
    relative string (no leading slash, forward-slash separators).
    """
    inside = paths.PROJECT_ROOT / "data" / "originals" / "sample.bin"
    result = paths.relative_to_project(inside)
    assert result == "data/originals/sample.bin"
    assert "\\" not in result


def test_relative_to_project_outside_project() -> None:
    """A path outside the project root must be returned as an absolute
    posix-style string.
    """
    outside = paths.PROJECT_ROOT.parent / "outside-workspace" / "some" / "file.txt"
    result = paths.relative_to_project(outside)
    assert Path(result).is_absolute() or result.startswith("/")
    assert "\\" not in result


def test_non_fixture_files_excludes_actual_fixtures() -> None:
    """NON_FIXTURE_FILES must contain the known non-fixture entries and must
    not contain any of the five fixture filenames declared in FIXTURE_SPECS.
    """
    assert "manifest.json" in paths.NON_FIXTURE_FILES
    assert "FIXTURE_NOTES.md" in paths.NON_FIXTURE_FILES

    fixture_filenames = {spec.filename for spec in FIXTURE_SPECS}
    overlap = fixture_filenames & paths.NON_FIXTURE_FILES
    assert overlap == set(), f"fixture filenames found in NON_FIXTURE_FILES: {overlap}"
