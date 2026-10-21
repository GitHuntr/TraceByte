"""Canonical filesystem locations for the project.

Every path is derived from the location of this file, so the library keeps
working regardless of the current working directory (Windows PowerShell, IDE
run configurations, pytest, CI, ...).

Directory contract
------------------
``data/originals/``   Ground-truth synthetic fixtures + the baseline manifest.
                      NEVER modified after creation by the application.
``data/experiments/`` Experimental inputs derived from the originals.
``data/recovered/``   Output of recovery attempts.
``logs/``             Append-only experiment log (JSON Lines).
``reports/``          Generated report artefacts.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
ORIGINALS_DIR: Path = DATA_DIR / "originals"
EXPERIMENTS_DIR: Path = DATA_DIR / "experiments"
RECOVERED_DIR: Path = DATA_DIR / "recovered"

LOGS_DIR: Path = PROJECT_ROOT / "logs"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"

MANIFEST_PATH: Path = ORIGINALS_DIR / "manifest.json"
EXPERIMENT_LOG_PATH: Path = LOGS_DIR / "experiment_log.jsonl"

#: Files that live inside ``data/originals/`` but are not evidence fixtures.
NON_FIXTURE_FILES: frozenset[str] = frozenset(
    {"manifest.json", "FIXTURE_NOTES.md", "README.md"}
)

#: Directories that make up the project layout and must exist on disk.
REQUIRED_DIRECTORIES: tuple[Path, ...] = (
    ORIGINALS_DIR,
    EXPERIMENTS_DIR,
    RECOVERED_DIR,
    LOGS_DIR,
    REPORTS_DIR,
)


def ensure_project_directories() -> None:
    """Create the canonical project directories if they do not exist yet."""
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def relative_to_project(path: Path | str) -> str:
    """Return *path* relative to the project root, using forward slashes."""
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return candidate.as_posix()
