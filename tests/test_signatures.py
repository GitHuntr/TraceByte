"""Tests for the signature registry, the scanner and the extent policies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.signatures import (
    JPEG,
    PDF,
    ZIP,
    Detection,
    SignatureError,
    SignatureRegistry,
    SignatureSpec,
    default_registry,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"body" + b"\xff\xd9"
PDF_BYTES = b"%PDF-1.4\n" + b"body" + b"\n%%EOF"
ZIP_BYTES = b"PK\x03\x04" + b"body" + b"PK\x05\x06"


def test_default_registry_exposes_the_supported_formats() -> None:
    registry = default_registry()
    assert registry.names() == ["JPEG", "PDF", "ZIP"]
    assert registry.get(JPEG).magic == b"\xff\xd8\xff"
    assert registry.get(PDF).magic == b"%PDF-"
    assert registry.get(ZIP).magic == b"PK\x03\x04"
    assert registry.max_magic_length == len(b"%PDF-")


def test_registry_rejects_an_empty_magic_value() -> None:
    with pytest.raises(SignatureError):
        SignatureRegistry([SignatureSpec("X", b"", ".x", None, "d", "v")])


def test_registry_rejects_duplicate_names() -> None:
    spec = SignatureSpec("X", b"x", ".x", None, "d", "v")
    with pytest.raises(SignatureError):
        SignatureRegistry([spec, spec])


def test_registry_rejects_an_unknown_signature() -> None:
    with pytest.raises(SignatureError):
        default_registry().get("MP3")


def test_scan_bytes_finds_the_offset_of_a_signature() -> None:
    data = b"filler" + JPEG_BYTES
    detections = default_registry().scan_bytes(data)
    assert len(detections) == 1
    assert detections[0].signature == JPEG
    assert detections[0].offset == 6


def test_scan_bytes_reports_every_occurrence() -> None:
    data = JPEG_BYTES + b"gap" + JPEG_BYTES
    detections = default_registry().scan_bytes(data)
    assert [item.offset for item in detections] == [0, len(JPEG_BYTES) + 3]


def test_scan_bytes_detects_overlapping_signatures() -> None:
    registry = SignatureRegistry(
        [SignatureSpec("AA", b"\xaa\xaa", ".aa", None, "overlapping magic", "v")]
    )
    detections = registry.scan_bytes(b"\xaa\xaa\xaa")
    assert [item.offset for item in detections] == [0, 1]


def test_scan_bytes_does_not_invent_a_signature_at_a_wrong_offset() -> None:
    data = b"\xff\xd8\xff\xd8\xff"
    detections = default_registry().scan_bytes(data)
    assert [item.offset for item in detections] == [0, 2]


def test_scan_bytes_ignores_a_signature_at_the_wrong_place() -> None:
    data = b"\xff\xd8" + b"x" * 10
    assert default_registry().scan_bytes(data) == []


def test_scan_bytes_rejects_non_bytes_input() -> None:
    with pytest.raises(SignatureError):
        default_registry().scan_bytes("not bytes")  # type: ignore[arg-type]


def test_scan_file_finds_the_same_signatures_as_scan_bytes(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    data = b"noise" * 10 + JPEG_BYTES + b"more noise" + PDF_BYTES
    target.write_bytes(data)

    detections = default_registry().scan_file(target)
    expected = default_registry().scan_bytes(data)
    assert [item.offset for item in detections] == [item.offset for item in expected]


def test_scan_file_finds_a_signature_that_straddles_a_chunk_boundary(
    tmp_path: Path,
) -> None:
    target = tmp_path / "boundary.bin"
    data = b"a" * 5 + JPEG_BYTES
    target.write_bytes(data)

    detections = default_registry().scan_file(target, chunk_size=6)
    assert [item.offset for item in detections] == [5]


def test_scan_file_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        default_registry().scan_file(tmp_path / "nope.bin")


def test_scan_file_rejects_a_non_positive_chunk_size(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    target.write_bytes(b"data")
    with pytest.raises(SignatureError):
        default_registry().scan_file(target, chunk_size=0)


def test_find_extent_uses_the_end_marker_when_it_is_present() -> None:
    registry = default_registry()
    data = JPEG_BYTES
    detection = registry.scan_bytes(data)[0]
    extent = registry.find_extent(data, detection)

    assert extent.policy == "end_marker"
    assert extent.structurally_delimited is True
    assert extent.start == 0
    assert extent.end == len(data)


def test_find_extent_falls_back_to_the_next_signature() -> None:
    registry = default_registry()
    data = b"\xff\xd8\xff" + b"body without an end marker" + b"%PDF-1.4"
    detections = registry.scan_bytes(data)
    extent = registry.find_extent(
        data, detections[0], next_detection_offset=detections[1].offset
    )

    assert extent.policy == "next_signature"
    assert extent.structurally_delimited is False
    assert extent.end == detections[1].offset


def test_find_extent_falls_back_to_the_end_of_the_stream() -> None:
    registry = default_registry()
    data = b"\xff\xd8\xff" + b"body without an end marker"
    detection = registry.scan_bytes(data)[0]
    extent = registry.find_extent(data, detection)

    assert extent.policy == "eof"
    assert extent.structurally_delimited is False
    assert extent.end == len(data)


def test_find_extent_never_exceeds_the_maximum_size() -> None:
    registry = default_registry()
    data = b"\xff\xd8\xff" + b"x" * 100 + b"\xff\xd9"
    detection = registry.scan_bytes(data)[0]
    extent = registry.find_extent(data, detection, max_size=32)

    assert extent.length == 32


def test_find_extent_ignores_an_end_marker_beyond_the_size_cap() -> None:
    registry = default_registry()
    data = b"\xff\xd8\xff" + b"x" * 100 + b"\xff\xd9"
    detection = registry.scan_bytes(data)[0]
    extent = registry.find_extent(data, detection, max_size=32)

    assert extent.policy == "eof"
    assert extent.structurally_delimited is False


def test_detection_carries_no_recovery_claim() -> None:
    """A detection must not claim that the surrounding bytes form a file."""
    detection = default_registry().scan_bytes(JPEG_BYTES)[0]
    assert isinstance(detection, Detection)
    assert detection.description
    assert detection.validation_strategy
    assert set(detection.to_dict()) == {
        "signature",
        "offset",
        "magic_hex",
        "extension",
        "description",
        "validation_strategy",
        "source",
    }
