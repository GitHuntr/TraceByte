"""Deterministic synthetic fixtures and dataset initialisation.

All fixtures are generated from a documented, deterministic algorithm
(SHA-256 counter-mode expansion of a fixed seed string). Re-running the
generator produces byte-identical files, which is what makes the baseline
hashes meaningful and the experiment reproducible.

FORENSIC NOTE
-------------
Every fixture is **synthetic**. Some of them deliberately start with a real
file signature (JPEG SOI, ``%PDF-``, ZIP local file header) so that a carving
engine has something meaningful to find, but none of them is a fully
parseable, valid JPEG / PDF / ZIP file. Each one carries an embedded
``SYNTHETIC-FIXTURE`` marker and a descriptive filename, and the manifest
records the flag ``fully_parseable = false``.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .experiment_log import ExperimentLog, tool_versions, utc_now_iso
from .hashing import sha256_file
from .manifest import (
    BASELINE_ORIGIN_ADOPTED,
    BASELINE_ORIGIN_GENERATED,
    FixtureEntry,
    Manifest,
    load_manifest,
    save_manifest,
)
from .paths import MANIFEST_PATH, NON_FIXTURE_FILES, ORIGINALS_DIR, relative_to_project

SEED_NAMESPACE = "FileCarveLab/v1"

#: Marker embedded in (nearly) every fixture so a human or tool can tell that
#: the file is synthetic at a glance.
SYNTHETIC_MARKER = b"SYNTHETIC-FIXTURE"

JPEG_APP0_HEADER = bytes.fromhex("FFD8FFE000104A46494600010100000100010000")
PDF_HEADER = b"%PDF-1.4\n"
ZIP_LOCAL_HEADER = bytes.fromhex("504B0304140000000800")


def expand_seed(seed: str, length: int) -> bytes:
    """Return *length* deterministic bytes derived from *seed*.

    SHA-256 in counter mode is used instead of a random number generator so
    that the output does not depend on the Python version or the platform.
    """
    if length < 0:
        raise ValueError("length must not be negative")
    output = bytearray()
    counter = 0
    prefix = seed.encode("utf-8")
    while len(output) < length:
        output.extend(hashlib.sha256(prefix + b"|" + str(counter).encode("ascii")).digest())
        counter += 1
    return bytes(output[:length])


@dataclass(frozen=True)
class FixtureSpec:
    """Declarative description of one synthetic fixture."""

    fixture_id: str
    filename: str
    description: str
    signature_hex: str = ""
    signature_offset: int | None = 0
    notes: str = ""
    _builder: Callable[[], bytes] = field(repr=False, default=lambda: b"")

    def build(self) -> bytes:
        """Return the deterministic byte content of this fixture."""
        return self._builder()


def _build_jpeg() -> bytes:
    marker = (
        b"\nSYNTHETIC-FIXTURE:synthetic_photo_01 (FileCarveLab) - "
        b"NOT A VALID JPEG - deterministic filler body follows\n"
    )
    return JPEG_APP0_HEADER + marker + expand_seed(f"{SEED_NAMESPACE}/synthetic_photo_01", 3072)


def _build_pdf() -> bytes:
    marker = (
        b"% SYNTHETIC-FIXTURE:synthetic_doc_01 (FileCarveLab) - "
        b"NOT A VALID PDF - no xref table, no trailer, no objects\n"
    )
    return PDF_HEADER + marker + expand_seed(f"{SEED_NAMESPACE}/synthetic_doc_01", 2048)


def _build_zip() -> bytes:
    marker = (
        b"SYNTHETIC-FIXTURE:synthetic_archive_01 (FileCarveLab) - "
        b"NOT A VALID ZIP - no central directory, no end-of-archive record\n"
    )
    return ZIP_LOCAL_HEADER + marker + expand_seed(f"{SEED_NAMESPACE}/synthetic_archive_01", 1536)


def _build_blob() -> bytes:
    return expand_seed(f"{SEED_NAMESPACE}/synthetic_blob_01", 4096)


def _build_container() -> bytes:
    head = expand_seed(f"{SEED_NAMESPACE}/synthetic_container_01/head", 1024)
    embedded = (
        JPEG_APP0_HEADER
        + b"SYNTHETIC-FIXTURE:embedded segment at offset 1024\n"
        + expand_seed(f"{SEED_NAMESPACE}/synthetic_container_01/embedded", 1024)
    )
    tail = expand_seed(f"{SEED_NAMESPACE}/synthetic_container_01/tail", 1024)
    return head + embedded + tail


FIXTURE_SPECS: tuple[FixtureSpec, ...] = (
    FixtureSpec(
        fixture_id="fx-photo-01",
        filename="synthetic_photo_01.jpg",
        description=(
            "Synthetic JPEG-signature fixture. Begins with a JPEG SOI marker and a "
            "JFIF APP0 header, but the body is deterministic filler: there is no "
            "quantisation table, no Huffman table and no entropy-coded scan, so this "
            "is NOT a valid, fully parseable JPEG file."
        ),
        signature_hex=JPEG_APP0_HEADER[:4].hex(),
        signature_offset=0,
        notes="Used later as the 'contiguous file' ground truth.",
        _builder=_build_jpeg,
    ),
    FixtureSpec(
        fixture_id="fx-doc-01",
        filename="synthetic_doc_01.pdf",
        description=(
            "Synthetic PDF-signature fixture. Begins with the '%PDF-' header so that "
            "signature detection has a realistic target, but the file has no xref "
            "table, no trailer and no object structure: it is NOT a valid, fully "
            "parseable PDF file."
        ),
        signature_hex=PDF_HEADER.strip().hex(),
        signature_offset=0,
        notes="Used later as a second contiguous ground truth.",
        _builder=_build_pdf,
    ),
    FixtureSpec(
        fixture_id="fx-archive-01",
        filename="synthetic_archive_01.zip",
        description=(
            "Synthetic ZIP-signature fixture. Starts with a ZIP local file header "
            "(PK\\x03\\x04) followed by a synthetic marker, but there is no central "
            "directory and no end-of-central-directory record, so it is NOT a valid "
            "archive."
        ),
        signature_hex=ZIP_LOCAL_HEADER[:4].hex(),
        signature_offset=0,
        notes="Used later as a third contiguous ground truth.",
        _builder=_build_zip,
    ),
    FixtureSpec(
        fixture_id="fx-blob-01",
        filename="synthetic_blob_01.bin",
        description=(
            "Signature-free control fixture. Pure deterministic filler with no file "
            "signature at all. It exists so that signature detection can be measured "
            "against a negative case (no signature => nothing may be carved)."
        ),
        signature_hex="",
        signature_offset=None,
        notes="Negative control for false-positive measurements.",
        _builder=_build_blob,
    ),
    FixtureSpec(
        fixture_id="fx-container-01",
        filename="synthetic_container_01.bin",
        description=(
            "Synthetic container with a JPEG signature embedded at byte offset 1024, "
            "surrounded by unrelated filler. The embedded segment is NOT a valid, "
            "fully parseable JPEG - it has no entropy-coded scan. This is the "
            "planned ground truth for the fragmented-file experiment and for the "
            "'signature inside noise' case."
        ),
        signature_hex=JPEG_APP0_HEADER[:4].hex(),
        signature_offset=1024,
        notes="Planned ground truth for fragmented carving.",
        _builder=_build_container,
    ),
)

FIXTURE_NOTES_FILENAME = "FIXTURE_NOTES.md"


def fixture_notes_markdown() -> str:
    """Return the human-readable note stored alongside the fixtures."""
    lines = [
        "# FileCarveLab synthetic fixture notes",
        "",
        "All files in this directory are **synthetic** and were generated by "
        "`src/fixtures.py` from a deterministic seed. No real-world data, no real "
        "device and no real account was involved.",
        "",
        "Files that start with a real file signature (JPEG / PDF / ZIP) are **not** "
        "valid, fully parseable files. They exist so that a carving engine has a "
        "realistic signature to detect; they must never be presented as valid "
        "recovered media or documents.",
        "",
        "| Fixture | Bytes | Signature | Offset | Fully parseable | Purpose |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for spec in FIXTURE_SPECS:
        signature = spec.signature_hex.upper() if spec.signature_hex else "none"
        offset = "n/a" if spec.signature_offset is None else str(spec.signature_offset)
        purpose = spec.notes or spec.description
        lines.append(
            f"| `{spec.filename}` | {len(spec.build())} | `{signature}` | {offset} | "
            f"No | {purpose} |"
        )
    lines += [
        "",
        "The authoritative baseline (size + SHA-256) lives in `manifest.json`.",
        "Verify it with the **Integrity** screen of the FileCarveLab dashboard.",
        "",
    ]
    return "\n".join(lines)


@dataclass
class FixtureAction:
    """Outcome of processing one fixture during dataset initialisation."""

    fixture_id: str
    filename: str
    path: str
    action: str
    status: str
    baseline_sha256: str
    current_sha256: str
    size_bytes: int
    baseline_preserved: bool
    message: str


@dataclass
class DatasetInitReport:
    """Aggregated result of a dataset initialisation run."""

    manifest_path: str
    manifest_created: bool
    actions: list[FixtureAction] = field(default_factory=list)
    log_path: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return sum(1 for action in self.actions if action.action == "created")

    @property
    def preserved_count(self) -> int:
        return sum(1 for action in self.actions if action.action == "preserved")

    @property
    def adopted_count(self) -> int:
        return sum(1 for action in self.actions if action.action == BASELINE_ORIGIN_ADOPTED)

    @property
    def mismatch_count(self) -> int:
        return sum(1 for action in self.actions if action.status == "mismatch")

    @property
    def new_count(self) -> int:
        return sum(1 for action in self.actions if action.status == "new")


def _write_file_atomically(target: Path, data: bytes) -> None:
    """Write *data* to *target* without ever truncating an existing original."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb",
        dir=target.parent,
        prefix=f".{target.name}-",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def initialize_dataset(
    originals_dir: str | Path = ORIGINALS_DIR,
    manifest_path: str | Path = MANIFEST_PATH,
    *,
    log: ExperimentLog | None = None,
    specs: tuple[FixtureSpec, ...] = FIXTURE_SPECS,
    write_notes: bool = True,
) -> DatasetInitReport:
    """Create the synthetic dataset and its baseline manifest.

    Guarantees
    ----------
    * A fixture file that already exists is **never** overwritten.
    * A baseline SHA-256 that is already recorded is **never** replaced.
    * If a file exists on disk but has no baseline entry, it is adopted as a
      baseline *and clearly flagged* (``adopted-existing-unregistered``) in the
      manifest and in the experiment log - never silently.
    """
    originals_dir = Path(originals_dir)
    manifest_path = Path(manifest_path)
    originals_dir.mkdir(parents=True, exist_ok=True)

    manifest_existed = manifest_path.exists()
    manifest = load_manifest(manifest_path)
    now = utc_now_iso()
    if not manifest.created_utc:
        manifest.created_utc = now

    actions: list[FixtureAction] = []
    warnings: list[str] = []

    for spec in specs:
        target = originals_dir / spec.filename
        relative_path = relative_to_project(target)

        if not target.exists():
            data = spec.build()
            _write_file_atomically(target, data)
            current_sha = sha256_file(target)
            entry = FixtureEntry(
                fixture_id=spec.fixture_id,
                filename=spec.filename,
                relative_path=relative_path,
                size_bytes=target.stat().st_size,
                sha256=current_sha,
                description=spec.description,
                signature_hex=spec.signature_hex,
                signature_offset=spec.signature_offset,
                synthetic=True,
                fully_parseable=False,
                created_utc=now,
                baseline_origin=BASELINE_ORIGIN_GENERATED,
                notes=spec.notes,
            )
            action, _ = manifest.record_baseline(entry)
            actions.append(
                FixtureAction(
                    fixture_id=spec.fixture_id,
                    filename=spec.filename,
                    path=relative_path,
                    action=action,
                    status="new",
                    baseline_sha256=current_sha,
                    current_sha256=current_sha,
                    size_bytes=entry.size_bytes,
                    baseline_preserved=False,
                    message="Fixture created and baseline SHA-256 recorded.",
                )
            )
            continue

        # The original already exists: preserve it, never regenerate the hash.
        current_sha = sha256_file(target)
        current_size = target.stat().st_size
        baseline = manifest.entries.get(spec.filename)

        if baseline is not None:
            if current_sha == baseline.sha256:
                status = "match"
                message = (
                    "Original preserved. Content matches the recorded baseline; "
                    "no baseline hash was regenerated."
                )
            else:
                status = "mismatch"
                message = (
                    "Original preserved. Content NO LONGER matches the recorded "
                    "baseline. The baseline hash was NOT updated - treat this file "
                    "as suspect and restore it from a trusted copy."
                )
                warnings.append(
                    f"{spec.filename}: content differs from the recorded baseline "
                    f"(expected {baseline.sha256}, found {current_sha})."
                )
            actions.append(
                FixtureAction(
                    fixture_id=spec.fixture_id,
                    filename=spec.filename,
                    path=relative_path,
                    action="preserved",
                    status=status,
                    baseline_sha256=baseline.sha256,
                    current_sha256=current_sha,
                    size_bytes=current_size,
                    baseline_preserved=True,
                    message=message,
                )
            )
        else:
            entry = FixtureEntry(
                fixture_id=spec.fixture_id,
                filename=spec.filename,
                relative_path=relative_path,
                size_bytes=current_size,
                sha256=current_sha,
                description=spec.description,
                signature_hex=spec.signature_hex,
                signature_offset=spec.signature_offset,
                synthetic=True,
                fully_parseable=False,
                created_utc=now,
                baseline_origin=BASELINE_ORIGIN_ADOPTED,
                notes=(
                    "File was already present on disk without a baseline entry. Its "
                    "bytes were preserved and the current hash was recorded as the "
                    "first baseline. This is flagged, not silent - verify the origin "
                    "of this file manually before using it as ground truth."
                ),
            )
            manifest.record_baseline(entry)
            warnings.append(
                f"{spec.filename}: existed on disk without a baseline entry; adopted "
                "as baseline with the flag 'adopted-existing-unregistered'."
            )
            actions.append(
                FixtureAction(
                    fixture_id=spec.fixture_id,
                    filename=spec.filename,
                    path=relative_path,
                    action=BASELINE_ORIGIN_ADOPTED,
                    status="unregistered",
                    baseline_sha256=current_sha,
                    current_sha256=current_sha,
                    size_bytes=current_size,
                    baseline_preserved=False,
                    message=(
                        "File already existed without a baseline entry. Bytes were "
                        "preserved and the current hash was recorded as the first "
                        "baseline. Flagged as 'adopted-existing-unregistered'."
                    ),
                )
            )

    if write_notes:
        notes_path = originals_dir / FIXTURE_NOTES_FILENAME
        notes_text = fixture_notes_markdown()
        if not notes_path.exists() or notes_path.read_text(encoding="utf-8") != notes_text:
            _write_file_atomically(notes_path, notes_text.encode("utf-8"))

    manifest.updated_utc = now
    manifest.tool_versions = tool_versions()
    save_manifest(manifest, manifest_path)

    report = DatasetInitReport(
        manifest_path=relative_to_project(manifest_path),
        manifest_created=not manifest_existed,
        actions=actions,
        log_path=str(log.path) if log else "",
        warnings=warnings,
    )

    if log is not None:
        log.append(
            "dataset.initialize",
            {
                "manifest_path": report.manifest_path,
                "manifest_created": report.manifest_created,
                "created": report.created_count,
                "preserved": report.preserved_count,
                "adopted": report.adopted_count,
                "mismatches": report.mismatch_count,
                "fixtures": [
                    {
                        "filename": action.filename,
                        "action": action.action,
                        "status": action.status,
                        "baseline_sha256": action.baseline_sha256,
                        "current_sha256": action.current_sha256,
                        "size_bytes": action.size_bytes,
                        "baseline_preserved": action.baseline_preserved,
                    }
                    for action in report.actions
                ],
                "warnings": report.warnings,
            },
        )

    return report


def dataset_state(originals_dir: str | Path = ORIGINALS_DIR) -> dict[str, Any]:
    """Return a small dict describing the current state of the dataset."""
    originals_dir = Path(originals_dir)
    present = sorted(
        path.name
        for path in originals_dir.glob("*")
        if path.is_file() and path.name not in NON_FIXTURE_FILES
    )
    return {
        "originals_dir": relative_to_project(originals_dir),
        "files_present": present,
        "file_count": len(present),
    }
