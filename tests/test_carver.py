"""Tests for the carving engine.

The carver must never modify its input and must record full provenance for
every candidate it produces.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.carver import (
    STATUS_DELIMITED,
    STATUS_TRUNCATED,
    TOOL_VERSION,
    CarverError,
    carve_bytes,
    carve_file,
    load_candidate_report,
    write_candidate_report,
)
from src.hashing import sha256_file

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"body" + b"\xff\xd9"
FILLER = b"nothing to see here"


def _carve(tmp_path: Path, data: bytes, **kwargs):
    return carve_bytes(
        data,
        source_path="data/experiments/demo/image.bin",
        source_sha256="0" * 64,
        output_dir=tmp_path / "recovered",
        **kwargs,
    )


def test_carve_bytes_extracts_the_candidate_payload(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, FILLER + JPEG_BYTES)
    assert len(candidates) == 1

    candidate = candidates[0]
    assert candidate.signature == "JPEG"
    assert candidate.offset == len(FILLER)
    assert candidate.length == len(JPEG_BYTES)
    assert candidate.status == STATUS_DELIMITED
    assert candidate.structurally_delimited is True


def test_carve_bytes_writes_the_candidate_to_disk(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, FILLER + JPEG_BYTES)
    output = Path(candidates[0].output_path)
    assert output.exists()
    assert output.read_bytes() == JPEG_BYTES


def test_candidate_filename_encodes_the_provenance(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, FILLER + JPEG_BYTES, experiment_id="exp-demo")
    name = Path(candidates[0].output_path).name
    assert name.startswith("exp-demo__JPEG__")
    assert name.endswith(".jpg")
    assert candidates[0].output_sha256[:12] in name


def test_candidate_records_the_whole_provenance(tmp_path: Path) -> None:
    candidates = _carve(
        tmp_path,
        FILLER + JPEG_BYTES,
        experiment_id="exp-demo",
        condition="contiguous",
    )
    candidate = candidates[0]
    assert candidate.source_path == "data/experiments/demo/image.bin"
    assert candidate.source_sha256 == "0" * 64
    assert candidate.experiment_id == "exp-demo"
    assert candidate.condition == "contiguous"
    assert candidate.tool_version == TOOL_VERSION
    assert candidate.notes


def test_a_truncated_candidate_is_marked_as_such(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, b"\xff\xd8\xff" + b"body without an end marker")
    candidate = candidates[0]
    assert candidate.status == STATUS_TRUNCATED
    assert candidate.structurally_delimited is False


def test_carving_does_not_modify_the_source(tmp_path: Path) -> None:
    source = tmp_path / "image.bin"
    source.write_bytes(FILLER + JPEG_BYTES)
    before = sha256_file(source)

    carve_file(source, output_dir=tmp_path / "recovered")
    assert sha256_file(source) == before


def test_carve_file_uses_the_sha256_of_the_source(tmp_path: Path) -> None:
    source = tmp_path / "image.bin"
    source.write_bytes(FILLER + JPEG_BYTES)
    candidates = carve_file(source, output_dir=tmp_path / "recovered")
    assert candidates[0].source_sha256 == sha256_file(source)


def test_carve_file_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CarverError):
        carve_file(tmp_path / "missing.bin", output_dir=tmp_path / "recovered")


def test_carve_file_raises_for_a_directory(tmp_path: Path) -> None:
    with pytest.raises(CarverError):
        carve_file(tmp_path, output_dir=tmp_path / "recovered")


def test_carve_bytes_rejects_a_non_positive_max_size(tmp_path: Path) -> None:
    with pytest.raises(CarverError):
        _carve(tmp_path, JPEG_BYTES, max_size=0)


def test_carve_bytes_can_skip_writing_the_output(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, JPEG_BYTES, write_output=False)
    assert candidates[0].output_path is None
    assert not (tmp_path / "recovered").exists()


def test_candidate_report_round_trips(tmp_path: Path) -> None:
    candidates = _carve(tmp_path, FILLER + JPEG_BYTES)
    report = write_candidate_report(candidates, tmp_path / "carve_results.json")
    restored = load_candidate_report(report)

    assert len(restored) == 1
    assert restored[0].candidate_id == candidates[0].candidate_id
    assert restored[0].output_sha256 == candidates[0].output_sha256
    assert restored[0].status == candidates[0].status


def test_two_signatures_produce_two_candidates(tmp_path: Path) -> None:
    data = b"\xff\xd8\xff" + b"x" * 10 + b"\xff\xd9" + b"gap" + b"%PDF-1.4" + b"\n%%EOF"
    candidates = _carve(tmp_path, data)
    assert [item.signature for item in candidates] == ["JPEG", "PDF"]
    assert candidates[0].offset < candidates[1].offset
