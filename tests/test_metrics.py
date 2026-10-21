"""Tests for the measurement layer.

The metrics must separate detection from recovery, must never invent a
number and must count the planted decoys as false positives.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.carver import CarveCandidate
from src.conditions import ByteRange, GroundTruthFile
from src.hashing import sha256_bytes
from src.metrics import (
    ConditionMetrics,
    Score,
    collect_instances,
    evaluate_condition,
    summarise_runs,
)

ORIGINAL = b"\xff\xd8\xff" + b"payload" + b"\xff\xd9"
DIGEST = sha256_bytes(ORIGINAL)


def _truth(signature: str | None = "JPEG", total: int = len(ORIGINAL)) -> GroundTruthFile:
    return GroundTruthFile(
        file_id="file.bin",
        fixture_id="fx-01",
        signature=signature,
        ranges=[ByteRange(100, 100 + total)],
        total_bytes=total,
        expected_sha256=DIGEST,
    )


def _candidate(
    offset: int = 100,
    signature: str = "JPEG",
    payload: bytes = ORIGINAL,
    length: int | None = None,
    candidate_id: str = "cand-1",
) -> CarveCandidate:
    return CarveCandidate(
        candidate_id=candidate_id,
        signature=signature,
        extension=".jpg",
        source_path="image.bin",
        source_sha256="0" * 64,
        offset=offset,
        end_offset=offset + (length if length is not None else len(payload)),
        length=length if length is not None else len(payload),
        extent_policy="end_marker",
        structurally_delimited=True,
        status="delimited",
        output_sha256=sha256_bytes(payload),
    )


def _evaluate(ground_truth, candidates, payloads=None, originals=None):
    return evaluate_condition(
        condition="contiguous",
        experiment_id="exp-test",
        image_path="image.bin",
        image_sha256="0" * 64,
        ground_truth=ground_truth,
        candidates=candidates,
        candidate_payloads=payloads or {},
        originals=originals or {},
    )


def test_a_correct_candidate_is_a_true_positive() -> None:
    metrics = _evaluate([_truth()], [_candidate()])
    assert metrics.detection.tp == 1
    assert metrics.detection.fp == 0
    assert metrics.detection.fn == 0
    assert metrics.detection.precision == 1.0
    assert metrics.detection.recall == 1.0


def test_a_candidate_at_the_wrong_offset_is_a_false_positive() -> None:
    metrics = _evaluate([_truth()], [_candidate(offset=500, candidate_id="cand-2")])
    assert metrics.detection.tp == 0
    assert metrics.detection.fp == 1
    assert metrics.detection.fn == 1
    assert metrics.detection.precision == 0.0
    assert metrics.detection.recall == 0.0


def test_a_candidate_with_the_wrong_signature_does_not_count() -> None:
    metrics = _evaluate([_truth()], [_candidate(signature="PDF", candidate_id="c2")])
    assert metrics.detection.tp == 0
    assert metrics.detection.fp == 1


def test_a_file_without_a_signature_is_not_part_of_the_detection_score() -> None:
    metrics = _evaluate([_truth(signature=None)], [_candidate(candidate_id="c2")])
    assert metrics.ground_truth_instances == 0
    assert metrics.detection.fn == 0


def test_an_embedded_signature_counts_as_its_own_instance() -> None:
    truth = _truth(signature=None)
    truth.embedded_signatures = [{"signature": "JPEG", "relative_offset": 16}]
    instances = collect_instances([truth])
    assert len(instances) == 1
    assert instances[0].offset == 116
    assert instances[0].kind == "embedded"


def test_a_byte_exact_candidate_is_a_validated_recovery() -> None:
    metrics = _evaluate([_truth()], [_candidate()])
    assert metrics.exact_recovery.tp == 1
    assert metrics.outcomes[0].exact is True
    assert metrics.outcomes[0].detected is True


def test_a_wrong_candidate_is_carved_but_not_validated() -> None:
    metrics = _evaluate([_truth()], [_candidate(payload=b"different bytes")])
    assert metrics.exact_recovery.tp == 0
    assert metrics.outcomes[0].detected is True
    assert metrics.outcomes[0].exact is False
    assert "not validated" in metrics.outcomes[0].note


def test_a_candidate_longer_than_the_original_is_reported_as_over_carving() -> None:
    candidate = _candidate(payload=ORIGINAL + b"extra")
    metrics = _evaluate([_truth()], [candidate])
    assert metrics.outcomes[0].exact is False
    assert "over-carved" in metrics.outcomes[0].note


def test_the_byte_coverage_is_measured_against_the_original() -> None:
    candidate = _candidate(payload=ORIGINAL[:5])
    metrics = _evaluate(
        [_truth()],
        [candidate],
        payloads={"cand-1": ORIGINAL[:5]},
        originals={"file.bin": ORIGINAL},
    )
    assert metrics.outcomes[0].byte_coverage == pytest.approx(5 / len(ORIGINAL))
    assert metrics.mean_byte_coverage == pytest.approx(5 / len(ORIGINAL))


def test_the_data_completeness_drops_when_data_was_overwritten() -> None:
    truth = _truth()
    truth.overwritten = True
    truth.overwritten_ranges = [ByteRange(110, 120)]
    metrics = _evaluate([truth], [])
    assert metrics.data_completeness == pytest.approx(1 - 10 / len(ORIGINAL))


def test_the_per_signature_breakdown_is_reported() -> None:
    metrics = _evaluate([_truth()], [_candidate()])
    assert "JPEG" in metrics.per_signature
    assert metrics.per_signature["JPEG"].tp == 1


def test_the_false_positives_are_listed_with_their_offset() -> None:
    metrics = _evaluate([_truth()], [_candidate(offset=900, candidate_id="c2")])
    assert len(metrics.false_positives) == 1
    assert metrics.false_positives[0]["offset"] == 900


def test_the_summary_covers_every_condition() -> None:
    first = _evaluate([_truth()], [_candidate()])
    second = _evaluate([_truth()], [])
    summary = summarise_runs([first, second])
    assert [item["condition"] for item in summary["conditions"]] == [
        "contiguous",
        "contiguous",
    ]
    assert summary["conditions"][0]["detection_recall"] == 1.0


def test_an_empty_score_does_not_divide_by_zero() -> None:
    score = Score()
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0
