"""Signature carving engine.

Stage 2 component B.

The carver scans a byte stream (usually a built experimental image), finds
signature hits and extracts a candidate byte range for each hit. For every
candidate it records full provenance: the source image, its SHA-256, the
offset, the extent policy that was used, the output hash and the tool
version.

Three claims are kept strictly apart and are reported separately:

``detected``
    A signature was found at an offset. Nothing more is claimed.

``carved``
    A candidate byte range was written to ``data/recovered/``. The range may
    still be wrong.

``validated``
    The carved bytes match a ground-truth original byte for byte. Only
    :mod:`src.metrics` establishes this, by comparing against the baseline
    manifest - the carver itself never sees the ground truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fixtures import write_bytes_atomically
from .hashing import sha256_bytes
from .paths import relative_to_project
from .signatures import (
    DEFAULT_MAX_CANDIDATE_SIZE,
    Detection,
    SignatureRegistry,
    default_registry,
)

TOOL_VERSION = "filecarvelab-carver/0.2.0"

STATUS_DELIMITED = "delimited"
STATUS_TRUNCATED = "truncated"
STATUS_EMPTY = "empty"


@dataclass
class CarveCandidate:
    """One extracted candidate with its full provenance."""

    candidate_id: str
    signature: str
    extension: str
    source_path: str
    source_sha256: str
    offset: int
    end_offset: int
    length: int
    extent_policy: str
    structurally_delimited: bool
    status: str
    output_path: str | None = None
    output_sha256: str | None = None
    experiment_id: str | None = None
    condition: str | None = None
    tool_version: str = TOOL_VERSION
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_truncated(self) -> bool:
        return self.status == STATUS_TRUNCATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "signature": self.signature,
            "extension": self.extension,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "offset": self.offset,
            "end_offset": self.end_offset,
            "length": self.length,
            "extent_policy": self.extent_policy,
            "structurally_delimited": self.structurally_delimited,
            "status": self.status,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "experiment_id": self.experiment_id,
            "condition": self.condition,
            "tool_version": self.tool_version,
            "notes": self.notes,
            "metadata": self.metadata,
        }


class CarverError(RuntimeError):
    """Raised when carving cannot be performed as requested."""


def _candidate_id(experiment_id: str | None, signature: str, offset: int) -> str:
    """Return a deterministic, traceable candidate identifier."""
    prefix = experiment_id or "adhoc"
    return f"{prefix}__{signature}__{offset:012d}"


def carve_bytes(
    data: bytes,
    *,
    source_path: str,
    source_sha256: str,
    output_dir: str | Path,
    registry: SignatureRegistry | None = None,
    experiment_id: str | None = None,
    condition: str | None = None,
    max_size: int = DEFAULT_MAX_CANDIDATE_SIZE,
    write_output: bool = True,
) -> list[CarveCandidate]:
    """Extract every signature candidate from *data*.

    The source is never modified. When *write_output* is true, each candidate
    is written to ``output_dir`` with a deterministic filename that encodes
    the experiment, the signature, the offset and the content hash.
    """
    registry = registry or default_registry()
    output_path = Path(output_dir)
    if max_size <= 0:
        raise CarverError("max_size must be a positive integer.")

    detections = registry.scan_bytes(data, source=source_path)
    candidates: list[CarveCandidate] = []

    for index, detection in enumerate(detections):
        next_offset = None
        for later in detections[index + 1 :]:
            if later.offset > detection.offset:
                next_offset = later.offset
                break

        extent = registry.find_extent(
            data, detection, max_size=max_size, next_detection_offset=next_offset
        )
        payload = data[extent.start : extent.end]

        if not payload:
            status = STATUS_EMPTY
        elif extent.structurally_delimited:
            status = STATUS_DELIMITED
        else:
            status = STATUS_TRUNCATED

        candidate_id = _candidate_id(experiment_id, detection.signature, detection.offset)
        output_sha256 = sha256_bytes(payload) if payload else None
        output_file: Path | None = None
        if payload and write_output:
            output_dir.mkdir(parents=True, exist_ok=True)
            short_hash = output_sha256[:12]
            output_file = output_path / (
                f"{candidate_id}__{short_hash}{detection.extension}"
            )
            write_bytes_atomically(output_file, payload)

        notes = _notes_for(status, extent.policy)
        candidates.append(
            CarveCandidate(
                candidate_id=candidate_id,
                signature=detection.signature,
                extension=detection.extension,
                source_path=source_path,
                source_sha256=source_sha256,
                offset=extent.start,
                end_offset=extent.end,
                length=extent.length,
                extent_policy=extent.policy,
                structurally_delimited=extent.structurally_delimited,
                status=status,
                output_path=relative_to_project(output_file) if output_file else None,
                output_sha256=output_sha256,
                experiment_id=experiment_id,
                condition=condition,
                tool_version=TOOL_VERSION,
                notes=notes,
                metadata={
                    "magic_hex": detection.magic_hex,
                    "validation_strategy": detection.validation_strategy,
                },
            )
        )

    return candidates


def _notes_for(status: str, policy: str) -> str:
    """Return an operator-facing note describing how the extent was found."""
    if status == STATUS_EMPTY:
        return "Empty candidate: the signature was at the very end of the stream."
    if status == STATUS_DELIMITED:
        return (
            "Extent delimited by the format's own end marker. The candidate is "
            "structurally complete, but it is only a recovered file once its "
            "SHA-256 matches the baseline of a known original."
        )
    return (
        f"Extent derived from the '{policy}' policy, not from a format structure. "
        "The candidate is therefore truncated and may contain unrelated bytes."
    )


def carve_file(
    path: str | Path,
    *,
    output_dir: str | Path,
    registry: SignatureRegistry | None = None,
    experiment_id: str | None = None,
    condition: str | None = None,
    max_size: int = DEFAULT_MAX_CANDIDATE_SIZE,
    write_output: bool = True,
    expected_source_sha256: str | None = None,
    max_candidates: int | None = None,
    max_output_bytes: int | None = None,
) -> list[CarveCandidate]:
    """Carve a file from disk using bounded memory; the source stays read-only.

    The scanner walks the source in chunks and only reads up to ``max_size``
    bytes around each hit. This lets the workbench analyze raw images without
    loading the entire image into memory.
    """
    source = Path(path)
    if not source.exists():
        raise CarverError(f"No such file: {source}")
    if source.is_dir():
        raise CarverError(f"Not a file: {source}")
    if max_size <= 0:
        raise CarverError("max_size must be a positive integer.")
    if max_output_bytes is not None and max_output_bytes < 0:
        raise CarverError("max_output_bytes cannot be negative.")

    registry = registry or default_registry()
    source_path = relative_to_project(source)
    detections, source_digest = registry.scan_file_with_hash(
        source, max_detections=max_candidates
    )
    if expected_source_sha256 and source_digest.lower() != expected_source_sha256.lower():
        raise CarverError("The evidence file changed after it was imported; scan stopped.")
    output_path = Path(output_dir)
    candidates: list[CarveCandidate] = []
    output_bytes = 0
    unique_offsets = sorted({item.offset for item in detections})
    following_offset = {
        offset: unique_offsets[index + 1] if index + 1 < len(unique_offsets) else None
        for index, offset in enumerate(unique_offsets)
    }

    with source.open("rb") as handle:
        for detection in detections:
            next_offset = following_offset[detection.offset]
            handle.seek(detection.offset)
            data = handle.read(max_size)
            local_detection = Detection(
                signature=detection.signature,
                offset=0,
                magic_hex=detection.magic_hex,
                extension=detection.extension,
                description=detection.description,
                validation_strategy=detection.validation_strategy,
                source=detection.source,
            )
            local_next = next_offset - detection.offset if next_offset is not None else None
            extent = registry.find_extent(
                data,
                local_detection,
                max_size=max_size,
                next_detection_offset=local_next,
            )
            payload = data[extent.start:extent.end]
            status = STATUS_EMPTY if not payload else STATUS_DELIMITED if extent.structurally_delimited else STATUS_TRUNCATED
            candidate_id = _candidate_id(experiment_id, detection.signature, detection.offset)
            output_digest = sha256_bytes(payload) if payload else None
            output_file: Path | None = None
            output_skipped_reason: str | None = None
            if payload and write_output:
                if max_output_bytes is not None and output_bytes + len(payload) > max_output_bytes:
                    output_skipped_reason = "The scan output limit was reached; candidate bytes were not written."
                else:
                    output_path.mkdir(parents=True, exist_ok=True)
                    output_file = output_path / f"{candidate_id}__{output_digest[:12]}{detection.extension}"
                    write_bytes_atomically(output_file, payload)
                    output_bytes += len(payload)

            candidates.append(
                CarveCandidate(
                    candidate_id=candidate_id,
                    signature=detection.signature,
                    extension=detection.extension,
                    source_path=source_path,
                    source_sha256=source_digest,
                    offset=detection.offset + extent.start,
                    end_offset=detection.offset + extent.end,
                    length=extent.length,
                    extent_policy=extent.policy,
                    structurally_delimited=extent.structurally_delimited,
                    status=status,
                    output_path=relative_to_project(output_file) if output_file else None,
                    output_sha256=output_digest,
                    experiment_id=experiment_id,
                    condition=condition,
                    tool_version=TOOL_VERSION,
                    notes=_notes_for(status, extent.policy),
                    metadata={
                        "magic_hex": detection.magic_hex,
                        "validation_strategy": detection.validation_strategy,
                        "output_skipped_reason": output_skipped_reason,
                    },
                )
            )

    return candidates


def write_candidate_report(
    candidates: list[CarveCandidate], path: str | Path
) -> Path:
    """Write the carve report (all candidates with provenance) to disk."""
    report_path = Path(path)
    payload = {
        "tool_version": TOOL_VERSION,
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    write_bytes_atomically(
        report_path, json.dumps(payload, indent=2).encode("utf-8")
    )
    return report_path


def load_candidate_report(path: str | Path) -> list[CarveCandidate]:
    """Load a carve report that was written by :func:`write_candidate_report`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates: list[CarveCandidate] = []
    for raw in data.get("candidates", []):
        candidates.append(
            CarveCandidate(
                candidate_id=raw.get("candidate_id", ""),
                signature=raw.get("signature", ""),
                extension=raw.get("extension", ""),
                source_path=raw.get("source_path", ""),
                source_sha256=raw.get("source_sha256", ""),
                offset=raw.get("offset", 0),
                end_offset=raw.get("end_offset", 0),
                length=raw.get("length", 0),
                extent_policy=raw.get("extent_policy", ""),
                structurally_delimited=raw.get("structurally_delimited", False),
                status=raw.get("status", ""),
                output_path=raw.get("output_path"),
                output_sha256=raw.get("output_sha256"),
                experiment_id=raw.get("experiment_id"),
                condition=raw.get("condition"),
                tool_version=raw.get("tool_version", TOOL_VERSION),
                notes=raw.get("notes", ""),
                metadata=raw.get("metadata", {}),
            )
        )
    return candidates
