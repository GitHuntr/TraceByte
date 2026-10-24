"""Canonical filesystem locations for the project.

Every path is derived from the location of this file, so the library keeps
working regardless of the current working directory (Windows PowerShell, IDE
run configurations, pytest, CI, ...).

Directory contract
------------------
``data/originals/``   Ground-truth synthetic fixtures + the baseline manifest.
                      NEVER modified after creation by the application.
``data/experiments/`` Experimental inputs derived from the originals.
``data/evidence/``    Content-addressed copies of user-supplied sources + scan reports.
``data/recovered/``   Output of recovery attempts.
``logs/``             Append-only experiment log (JSON Lines).
``reports/``          Generated report artefacts.

Derived paths follow their parent
---------------------------------
``MANIFEST_PATH``, ``EXPERIMENT_LOG_PATH`` and ``REQUIRED_DIRECTORIES`` are
*derived* from the directories above. Redirecting a parent directory moves its
derived paths with it::

    paths.ORIGINALS_DIR = tmp / "originals"
    paths.MANIFEST_PATH        # -> tmp / "originals" / "manifest.json"
    paths.EXPERIMENT_LOG_PATH  # -> unchanged, it belongs to LOGS_DIR

This is what keeps a test or a verification script from writing to the real
baseline manifest or to the real provenance log while it believes it works in
a sandbox. Setting a derived path directly is still allowed and is kept until
the next redirection of its parent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
ORIGINALS_DIR: Path = DATA_DIR / "originals"
EXPERIMENTS_DIR: Path = DATA_DIR / "experiments"
RECOVERED_DIR: Path = DATA_DIR / "recovered"

LOGS_DIR: Path = PROJECT_ROOT / "logs"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"

#: Name of the baseline manifest inside the originals directory.
MANIFEST_FILE_NAME = "manifest.json"

#: Name of the append-only provenance log inside the logs directory.
EXPERIMENT_LOG_FILE_NAME = "experiment_log.jsonl"

#: The baseline manifest. Derived from ``ORIGINALS_DIR`` (see the module
#: docstring): redirecting the originals directory redirects the manifest.
MANIFEST_PATH: Path = ORIGINALS_DIR / MANIFEST_FILE_NAME

#: The provenance log. Derived from ``LOGS_DIR``.
EXPERIMENT_LOG_PATH: Path = LOGS_DIR / EXPERIMENT_LOG_FILE_NAME

#: Files that live inside ``data/originals/`` but are not evidence fixtures.
NON_FIXTURE_FILES: frozenset[str] = frozenset(
    {"manifest.json", "FIXTURE_NOTES.md", "README.md"}
)

#: The directories that make up the project layout.
LAYOUT_DIRECTORIES: tuple[str, ...] = (
    "ORIGINALS_DIR",
    "EXPERIMENTS_DIR",
    "RECOVERED_DIR",
    "LOGS_DIR",
    "REPORTS_DIR",
)

#: Directories that make up the project layout and must exist on disk.
REQUIRED_DIRECTORIES: tuple[Path, ...] = (
    ORIGINALS_DIR,
    EXPERIMENTS_DIR,
    RECOVERED_DIR,
    LOGS_DIR,
    REPORTS_DIR,
)


#: The paths that are derived from a parent directory: derived path -> (parent, file name).
DERIVED_FILES: dict[str, tuple[str, str]] = {
    "MANIFEST_PATH": ("ORIGINALS_DIR", MANIFEST_FILE_NAME),
    "EXPERIMENT_LOG_PATH": ("LOGS_DIR", EXPERIMENT_LOG_FILE_NAME),
}


class _PathsModule(ModuleType):
    """Module type that keeps the derived paths in sync with their parents.

    Assigning a parent directory (``ORIGINALS_DIR``, ``LOGS_DIR``, ...) moves
    the paths derived from it and rebuilds ``REQUIRED_DIRECTORIES``.
    """

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)

        if name in DERIVED_FILES:
            # An explicit override of a derived path is kept as it is.
            return

        for derived, (parent, file_name) in DERIVED_FILES.items():
            if parent == name:
                super().__setattr__(derived, Path(value) / file_name)  # type: ignore[arg-type]

        if name in LAYOUT_DIRECTORIES:
            super().__setattr__(
                "REQUIRED_DIRECTORIES",
                tuple(Path(getattr(self, directory)) for directory in LAYOUT_DIRECTORIES),
            )


sys.modules[__name__].__class__ = _PathsModule


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
