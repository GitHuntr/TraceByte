"""Measurement of carving accuracy against the measured ground truth.

Stage 2 component D.

Three claims are scored separately, because they are different things:

``detection``
    Did the scanner find the file signature at the right offset?
    Precision and recall are computed over *signature instances* (a ground
    truth file contributes one instance at its start offset, plus one for
    every signature embedded inside it).

``recovery``
    Did the carver produce a byte range that matches the original file?
    Scored over whole files: a true positive is a candidate whose bytes are
    byte-for-byte identical to the ground-truth original.

``validation``
    The candidate is validated against the baseline manifest hash. Validation
    is what turns a *carved* candidate into a *recovered* file. A candidate
    can be detected and carved and still fail validation.

All numbers are derived from the ground-truth map written before carving and
from the baseline manifest. Nothing here is estimated, assumed or hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .carver import CarveCandidate
from .conditions import ByteRange, GroundTruthFile


@dataclass
class Score:
    """A precision / recall / F1 triple with its raw counts."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def _score(tp: int, fp: int, fn: int) -> Score:
    """Build a score, using 0.0 instead of an undefined division."""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return Score(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


@dataclass
class SignatureInstance:
    """A place in the image where a signature is expected to be found."""

    offset: int
    signature: str
    file_id: str
    kind: str  # "file_start" | "embedded"


@dataclass
class FileOutcome:
    """Per-file result of one condition."""

    file_id: str
    signature: str | None
    detected: bool = False
    detection_offset: int | None = None
    embedded_detected: bool = False
    carved: bool = False
    candidate_id: str | None = None
    status: str = "not-detected"
    extent_policy: str = ""
    exact: bool = False
    span: bool = False
    byte_coverage: float = 0.0
    expected_sha256: str = ""
    actual_sha256: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "signature": self.signature,
            "detected": self.detected,
            "detection_offset": self.detection_offset,
            "embedded_detected": self.embedded_detected,
            "carved": self.carved,
            "candidate_id": self.candidate_id,
            "status": self.status,
            "extent_policy": self.extent_policy,
            "exact": self.exact,
            "span": self.span,
            "byte_coverage": round(self.byte_coverage, 4),
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "note": self.note,
        }


@dataclass
class ConditionMetrics:
    """All measured results for one storage condition."""

    condition: str
    experiment_id: str
    image_path: str
    image_sha256: str
    run_id: str = ""
    ground_truth_files: int = 0
    ground_truth_instances: int = 0
    detection: Score = field(default_factory=Score)
    exact_recovery: Score = field(default_factory=Score)
    span_recovery: int = 0
    mean_byte_coverage: float = 0.0
    data_completeness: float = 0.0
    per_signature: dict[str, Score] = field(default_factory=dict)
    outcomes: list[FileOutcome] = field(default_factory=list)
    false_positives: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "experiment_id": self.experiment_id,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "run_id": self.run_id,
            "ground_truth_files": self.ground_truth_files,
            "ground_truth_instances": self.ground_truth_instances,
            "detection": self.detection.to_dict(),
            "exact_recovery": self.exact_recovery.to_dict(),
            "span_recovery": self.span_recovery,
            "mean_byte_coverage": round(self.mean_byte_coverage, 4),
            "data_completeness": round(self.data_completeness, 4),
            "per_signature": {
                name: score.to_dict() for name, score in self.per_signature.items()
            },
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "false_positives": self.false_positives,
            "notes": self.notes,
        }


def collect_instances(ground_truth: list[GroundTruthFile]) -> list[SignatureInstance]:
    """Return every signature instance the scanner is expected to find."""
    instances: list[SignatureInstance] = []
    for truth in ground_truth:
        if truth.signature and truth.ranges:
            instances.append(
                SignatureInstance(
                    offset=truth.start_offset,
                    signature=truth.signature,
                    file_id=truth.file_id,
                    kind="file_start",
                )
            )
        for embedded in truth.embedded_signatures:
            instances.append(
                SignatureInstance(
                    offset=truth.start_offset + int(embedded["relative_offset"]),
                    signature=str(embedded["signature"]),
                    file_id=truth.file_id,
                    kind="embedded",
                )
            )
    return instances


def _coverage(candidate_payload: bytes, original: bytes) -> float:
    """Return the fraction of the original recovered under a naive mapping."""
    if not original:
        return 0.0
    limit = min(len(candidate_payload), len(original))
    if limit == 0:
        return 0.0
    matching = sum(
        1 for index in range(limit) if candidate_payload[index] == original[index]
    )
    return matching / len(original)


def _data_completeness(ground_truth: list[GroundTruthFile]) -> float:
    """Return the fraction of every original that is still present in the image."""
    if not ground_truth:
        return 0.0
    values: list[float] = []
    for truth in ground_truth:
        if truth.total_bytes == 0:
            values.append(0.0)
            continue
        overwritten = sum(item.length for item in truth.overwritten_ranges)
        values.append(max(0.0, (truth.total_bytes - overwritten) / truth.total_bytes))
    return sum(values) / len(values)


def evaluate_condition(
    *,
    condition: str,
    experiment_id: str,
    image_path: str,
    image_sha256: str,
    ground_truth: list[GroundTruthFile],
    candidates: list[CarveCandidate],
    candidate_payloads: dict[str, bytes] | None = None,
    originals: dict[str, bytes] | None = None,
    run_id: str = "",
) -> ConditionMetrics:
    """Score one condition against its ground-truth map.

    Args:
        candidate_payloads: optional mapping ``candidate_id -> carved bytes``,
            used to compute byte coverage.
        originals: optional mapping ``file_id -> original bytes``, used to
            compute byte coverage.
        run_id: optional identifier of the experiment run the measurement
            belongs to.
    """
    candidate_payloads = candidate_payloads or {}
    originals = originals or {}

    metrics = ConditionMetrics(
        condition=condition,
        experiment_id=experiment_id,
        image_path=image_path,
        image_sha256=image_sha256,
        run_id=run_id,
        ground_truth_files=len(ground_truth),
    )

    instances = collect_instances(ground_truth)
    metrics.ground_truth_instances = len(instances)

    # -- detection -------------------------------------------------------
    matched_candidate_ids: set[str] = set()
    detection_tp = 0
    for instance in instances:
        hit = None
        for candidate in candidates:
            if (
                candidate.offset == instance.offset
                and candidate.signature == instance.signature
            ):
                hit = candidate
                break
        if hit is not None:
            detection_tp += 1
            matched_candidate_ids.add(hit.candidate_id)
        else:
            metrics.notes.append(
                f"Missed {instance.signature} signature for '{instance.file_id}' "
                f"at offset {instance.offset}."
            )

    false_positives = [
        {
            "candidate_id": candidate.candidate_id,
            "signature": candidate.signature,
            "offset": candidate.offset,
            "length": candidate.length,
            "note": "No ground-truth file starts at this offset with this signature.",
        }
        for candidate in candidates
        if candidate.candidate_id not in matched_candidate_ids
    ]
    metrics.false_positives = false_positives
    metrics.detection = _score(
        tp=detection_tp,
        fp=len(false_positives),
        fn=len(instances) - detection_tp,
    )

    # -- per signature breakdown -----------------------------------------
    for signature in sorted({instance.signature for instance in instances}):
        signature_instances = [
            instance for instance in instances if instance.signature == signature
        ]
        tp = 0
        for instance in signature_instances:
            if any(
                candidate.offset == instance.offset
                and candidate.signature == signature
                for candidate in candidates
            ):
                tp += 1
        fp = sum(
            1
            for candidate in candidates
            if candidate.signature == signature and candidate.candidate_id not in matched_candidate_ids
        )
        fn = len(signature_instances) - tp
        metrics.per_signature[signature] = _score(tp=tp, fp=fp, fn=fn)

    # -- recovery / validation -------------------------------------------
    recovery_tp = 0
    recovery_fp = 0
    file_count = 0
    coverages: list[float] = []

    for truth in ground_truth:
        outcome = FileOutcome(
            file_id=truth.file_id,
            signature=truth.signature,
            expected_sha256=truth.expected_sha256,
        )
        file_count += 1

        candidates_for_file = [
            candidate
            for candidate in candidates
            if candidate.offset == truth.start_offset and candidate.signature == truth.signature
        ]
        if truth.embedded_signatures:
            outcome.embedded_detected = any(
                candidate.offset == truth.start_offset + int(embedded["relative_offset"])
                and candidate.signature == str(embedded["signature"])
                for embedded in truth.embedded_signatures
                for candidate in candidates
            )
        if not candidates_for_file:
            outcome.note = "No candidate was produced at the ground-truth offset."
            if truth.embedded_signatures:
                outcome.note += (
                    " The embedded signature was "
                    + ("detected." if outcome.embedded_detected else "not detected.")
                )
            metrics.outcomes.append(outcome)
            continue

        candidate = candidates_for_file[0]
        outcome.detected = True
        outcome.detection_offset = candidate.offset
        outcome.carved = candidate.output_path is not None
        outcome.candidate_id = candidate.candidate_id
        outcome.status = candidate.status
        outcome.extent_policy = candidate.extent_policy
        outcome.actual_sha256 = candidate.output_sha256

        if candidate.output_sha256 == truth.expected_sha256:
            outcome.exact = True
            outcome.note = (
                "Recovered byte-for-byte: the carved bytes match the baseline "
                "SHA-256 of the original."
            )
            recovery_tp += 1
        else:
            outcome.note = (
                "Carved but not validated: the carved bytes differ from the "
                "baseline SHA-256 of the original."
            )
            recovery_fp += 1
            if candidate.length > truth.total_bytes:
                outcome.note += (
                    " The candidate is longer than the original "
                    f"({candidate.length} > {truth.total_bytes} bytes), so it was "
                    "over-carved: the delimiter that ended it belonged to a later "
                    "file, not to this one."
                )

        if candidate.end_offset >= truth.end_offset and candidate.offset <= truth.start_offset:
            outcome.span = True
            metrics.span_recovery += 1

        payload = candidate_payloads.get(candidate.candidate_id)
        original = originals.get(truth.file_id)
        if payload is not None and original is not None:
            outcome.byte_coverage = _coverage(payload, original)

        coverages.append(outcome.byte_coverage)
        metrics.outcomes.append(outcome)

    metrics.exact_recovery = _score(
        tp=recovery_tp,
        fp=recovery_fp,
        fn=max(0, file_count - recovery_tp),
    )
    metrics.mean_byte_coverage = (
        sum(coverages) / len(coverages) if coverages else 0.0
    )
    metrics.data_completeness = _data_completeness(ground_truth)

    if metrics.exact_recovery.fn:
        metrics.notes.append(
            f"{metrics.exact_recovery.fn} ground-truth file(s) were not recovered "
            "byte-for-byte in this condition."
        )

    return metrics


def load_originals(originals_dir: str | Path, file_ids: list[str]) -> dict[str, bytes]:
    """Read the ground-truth originals for the given file identifiers."""
    directory = Path(originals_dir)
    payloads: dict[str, bytes] = {}
    for file_id in file_ids:
        path = directory / file_id
        if path.exists():
            payloads[file_id] = path.read_bytes()
    return payloads


def summarise_runs(metrics: list[ConditionMetrics]) -> dict[str, Any]:
    """Return a compact overview across all conditions."""
    return {
        "conditions": [
            {
                "condition": item.condition,
                "detection_precision": round(item.detection.precision, 4),
                "detection_recall": round(item.detection.recall, 4),
                "exact_recovery_precision": round(item.exact_recovery.precision, 4),
                "exact_recovery_recall": round(item.exact_recovery.recall, 4),
                "span_recovery": item.span_recovery,
                "mean_byte_coverage": round(item.mean_byte_coverage, 4),
                "data_completeness": round(item.data_completeness, 4),
            }
            for item in metrics
        ]
    }


def byte_ranges_overlap(first: ByteRange, second: ByteRange) -> bool:
    """Return ``True`` when two byte ranges overlap."""
    return first.start < second.end and second.start < first.end
