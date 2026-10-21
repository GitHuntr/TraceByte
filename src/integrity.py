"""Evidence-integrity verification against the baseline manifest.

The verification is strictly read-only: nothing in this module modifies an
original, a baseline or the manifest. It reports one of four states per
fixture:

``match``        content and size equal the recorded baseline
``mismatch``     content differs from the recorded baseline
``missing``      the file is recorded in the manifest but absent on disk
``unregistered`` a file exists on disk but is not recorded in the manifest
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .hashing import sha256_file
from .manifest import FixtureEntry, Manifest
from .paths import NON_FIXTURE_FILES


class IntegrityStatus(str, Enum):
    """Outcome of a single integrity check."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"
    UNREGISTERED = "unregistered"

    @property
    def label(self) -> str:
        return {
            IntegrityStatus.MATCH: "MATCH",
            IntegrityStatus.MISMATCH: "MISMATCH",
            IntegrityStatus.MISSING: "MISSING",
            IntegrityStatus.UNREGISTERED: "UNREGISTERED",
        }[self]


@dataclass
class IntegrityResult:
    """Result of verifying one file against the baseline manifest."""

    fixture_id: str
    filename: str
    path: str
    status: IntegrityStatus
    expected_sha256: str = ""
    actual_sha256: str = ""
    expected_size: int | None = None
    actual_size: int | None = None
    description: str = ""
    message: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status is IntegrityStatus.MATCH


MATCH_MESSAGE = (
    "Content hash and size match the recorded baseline. The original is intact."
)

MISMATCH_MESSAGE = (
    "The file content does NOT match the recorded baseline SHA-256. The baseline "
    "has deliberately not been updated. Treat this original as suspect: restore "
    "it from a trusted copy before running any experiment, and record the reason "
    "for the change in the experiment log."
)

MISSING_MESSAGE = (
    "The original is recorded in the baseline manifest but is missing on disk. The "
    "baseline entry has been kept. Restore the file from a trusted copy before "
    "running experiments."
)

UNREGISTERED_MESSAGE = (
    "A file is present on disk but is not recorded in the baseline manifest. It has "
    "no ground-truth baseline, so it must not be used as an evaluated original "
    "until an operator records its provenance."
)


def _relative(path: Path) -> str:
    from .paths import relative_to_project

    return relative_to_project(path)


def verify_entry(entry: FixtureEntry, originals_dir: str | Path) -> IntegrityResult:
    """Verify a single manifest entry against the file on disk."""
    originals_dir = Path(originals_dir)
    target = originals_dir / entry.filename

    if not target.exists():
        return IntegrityResult(
            fixture_id=entry.fixture_id,
            filename=entry.filename,
            path=_relative(target),
            status=IntegrityStatus.MISSING,
            expected_sha256=entry.sha256,
            expected_size=entry.size_bytes,
            description=entry.description,
            message=MISSING_MESSAGE,
        )

    actual_sha256 = sha256_file(target)
    actual_size = target.stat().st_size

    if actual_sha256 == entry.sha256:
        status = IntegrityStatus.MATCH
        message = MATCH_MESSAGE
    else:
        status = IntegrityStatus.MISMATCH
        message = MISMATCH_MESSAGE

    return IntegrityResult(
        fixture_id=entry.fixture_id,
        filename=entry.filename,
        path=_relative(target),
        status=status,
        expected_sha256=entry.sha256,
        actual_sha256=actual_sha256,
        expected_size=entry.size_bytes,
        actual_size=actual_size,
        description=entry.description,
        message=message,
    )


def verify_manifest(
    manifest: Manifest, originals_dir: str | Path
) -> list[IntegrityResult]:
    """Verify every fixture recorded in the manifest."""
    originals_dir = Path(originals_dir)
    results: list[IntegrityResult] = []
    for filename in manifest.filenames():
        results.append(verify_entry(manifest.entries[filename], originals_dir))
    return results


def detect_unregistered_files(
    manifest: Manifest, originals_dir: str | Path
) -> list[IntegrityResult]:
    """Return files present in the originals directory but absent from the manifest."""
    originals_dir = Path(originals_dir)
    if not originals_dir.exists():
        return []

    results: list[IntegrityResult] = []
    for path in sorted(originals_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in NON_FIXTURE_FILES:
            continue
        if path.name in manifest.entries:
            continue
        results.append(
            IntegrityResult(
                fixture_id="",
                filename=path.name,
                path=_relative(path),
                status=IntegrityStatus.UNREGISTERED,
                actual_sha256=sha256_file(path),
                actual_size=path.stat().st_size,
                message=UNREGISTERED_MESSAGE,
            )
        )
    return results


def run_integrity_check(
    manifest: Manifest, originals_dir: str | Path
) -> list[IntegrityResult]:
    """Run the full check: manifest entries plus unregistered files."""
    return verify_manifest(manifest, originals_dir) + detect_unregistered_files(
        manifest, originals_dir
    )


def summarize(results: list[IntegrityResult]) -> dict[str, int]:
    """Return a status -> count summary for a list of integrity results."""
    summary = {status.label: 0 for status in IntegrityStatus}
    for result in results:
        summary[result.status.label] += 1
    return summary


def detection_self_test(
    manifest: Manifest, originals_dir: str | Path
) -> dict[str, object]:
    """Demonstrate change detection on a **copy** of an original.

    The original is never touched. The copy is written to a temporary
    directory, one byte is flipped, and the verification routine is run on
    both. This proves that the detection logic works without risking the
    evidence set.
    """
    filenames = manifest.filenames()
    if not filenames:
        return {
            "ok": False,
            "detail": "The baseline manifest contains no fixtures yet.",
        }

    filename = filenames[0]
    entry = manifest.entries[filename]
    source = Path(originals_dir) / filename

    if not source.exists():
        return {
            "ok": False,
            "detail": f"'{filename}' is recorded in the manifest but missing on disk.",
        }

    with tempfile.TemporaryDirectory(prefix="filecarvelab-selftest-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        copy_path = tmp_path / filename
        shutil.copy2(source, copy_path)

        before = verify_entry(entry, tmp_path)

        data = bytearray(copy_path.read_bytes())
        if not data:
            return {
                "ok": False,
                "detail": "The fixture is empty; nothing could be mutated.",
            }
        data[len(data) // 2] ^= 0xFF
        copy_path.write_bytes(bytes(data))

        after = verify_entry(entry, tmp_path)

    return {
        "ok": before.status is IntegrityStatus.MATCH
        and after.status is IntegrityStatus.MISMATCH,
        "filename": filename,
        "baseline_status": before.status.label,
        "mutated_status": after.status.label,
        "expected_sha256": entry.sha256,
        "mutated_sha256": after.actual_sha256,
        "detail": (
            f"Copy of '{filename}' verified as {before.status.label}; after flipping "
            f"a single byte the same copy verified as {after.status.label}. "
            "The original in data/originals was not modified."
        ),
    }
