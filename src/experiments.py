"""Experiment runner: build an image, carve it, measure the result, log it.

Stage 2 component E.

The runner is the only place where the three stages meet:

1. :mod:`src.conditions` builds a controlled image and records the ground
   truth.
2. :mod:`src.carver` carves that image without ever seeing the ground truth.
3. :mod:`src.metrics` compares the carved candidates with the ground truth.

Every artefact is written to disk so that a run can be inspected, reproduced
and audited afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .carver import CarveCandidate, carve_file, write_candidate_report
from .conditions import (
    CONDITION_CONTIGUOUS,
    CONDITION_FRAGMENTED,
    CONDITION_OVERWRITTEN,
    BuiltImage,
    build_image,
    load_ground_truth,
)
from .experiment_log import ExperimentLog
from .manifest import Manifest, load_manifest
from .metrics import ConditionMetrics, evaluate_condition, summarise_runs
from .paths import EXPERIMENTS_DIR, MANIFEST_PATH, ORIGINALS_DIR, RECOVERED_DIR, relative_to_project

EXPERIMENT_ACTOR = "filecarvelab.stage2"

CARVE_REPORT_NAME = "carve_results.json"
METRICS_NAME = "metrics.json"
GROUND_TRUTH_NAME = "ground_truth.json"
IMAGE_NAME = "image.bin"


def experiment_id_for(condition: str) -> str:
    """Return the deterministic experiment identifier for *condition*."""
    return f"exp-{condition}"


@dataclass
class ExperimentResult:
    """Everything one experimental run produced."""

    experiment_id: str
    condition: str
    image: BuiltImage
    candidates: list[CarveCandidate] = field(default_factory=list)
    metrics: ConditionMetrics | None = None
    artefacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "condition": self.condition,
            "image": self.image.to_dict(),
            "candidate_count": len(self.candidates),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "artefacts": self.artefacts,
        }


def run_condition(
    condition: str,
    *,
    originals_dir: str | Path = ORIGINALS_DIR,
    manifest_path: str | Path = MANIFEST_PATH,
    experiments_dir: str | Path = EXPERIMENTS_DIR,
    recovered_dir: str | Path = RECOVERED_DIR,
    manifest: Manifest | None = None,
    log: ExperimentLog | None = None,
    max_size: int = 8 * 1024 * 1024,
) -> ExperimentResult:
    """Run one storage condition end to end."""
    originals_dir = Path(originals_dir)
    experiments_dir = Path(experiments_dir)
    recovered_dir = Path(recovered_dir)

    manifest = manifest if manifest is not None else load_manifest(manifest_path)
    experiment_id = experiment_id_for(condition)

    image = build_image(
        condition,
        originals_dir=originals_dir,
        manifest=manifest,
        output_dir=experiments_dir,
        experiment_id=experiment_id,
    )

    experiment_dir = experiments_dir / experiment_id
    image_file = experiment_dir / IMAGE_NAME

    candidates = carve_file(
        image_file,
        output_dir=recovered_dir / experiment_id,
        experiment_id=experiment_id,
        condition=condition,
        max_size=max_size,
    )

    carve_report = write_candidate_report(
        candidates, experiment_dir / CARVE_REPORT_NAME
    )

    candidate_payloads = _load_candidate_payloads(candidates)
    originals = {
        filename: (originals_dir / filename).read_bytes()
        for filename in manifest.filenames()
        if (originals_dir / filename).exists()
    }

    metrics = evaluate_condition(
        condition=condition,
        experiment_id=experiment_id,
        image_path=image.image_path,
        image_sha256=image.image_sha256,
        ground_truth=image.ground_truth,
        candidates=candidates,
        candidate_payloads=candidate_payloads,
        originals=originals,
    )

    metrics_path = experiment_dir / METRICS_NAME
    metrics_path.write_text(
        json.dumps(metrics.to_dict(), indent=2), encoding="utf-8"
    )

    result = ExperimentResult(
        experiment_id=experiment_id,
        condition=condition,
        image=image,
        candidates=candidates,
        metrics=metrics,
        artefacts={
            "image": relative_to_project(image_file),
            "ground_truth": relative_to_project(experiment_dir / GROUND_TRUTH_NAME),
            "carve_results": relative_to_project(carve_report),
            "metrics": relative_to_project(metrics_path),
            "recovered_dir": relative_to_project(recovered_dir / experiment_id),
        },
    )

    if log is not None:
        log.append(
            "experiment_completed",
            {
                "experiment_id": experiment_id,
                "condition": condition,
                "image_sha256": image.image_sha256,
                "image_size_bytes": image.size_bytes,
                "candidate_count": len(candidates),
                "detection": metrics.detection.to_dict(),
                "exact_recovery": metrics.exact_recovery.to_dict(),
                "mean_byte_coverage": round(metrics.mean_byte_coverage, 4),
                "data_completeness": round(metrics.data_completeness, 4),
                "artefacts": result.artefacts,
            },
            actor=EXPERIMENT_ACTOR,
        )

    return result


def run_all_conditions(
    *,
    originals_dir: str | Path = ORIGINALS_DIR,
    manifest_path: str | Path = MANIFEST_PATH,
    experiments_dir: str | Path = EXPERIMENTS_DIR,
    recovered_dir: str | Path = RECOVERED_DIR,
    manifest: Manifest | None = None,
    log: ExperimentLog | None = None,
    max_size: int = 8 * 1024 * 1024,
) -> list[ExperimentResult]:
    """Run all three storage conditions in order."""
    manifest = manifest if manifest is not None else load_manifest(manifest_path)
    results: list[ExperimentResult] = []
    for condition in (
        CONDITION_CONTIGUOUS,
        CONDITION_FRAGMENTED,
        CONDITION_OVERWRITTEN,
    ):
        results.append(
            run_condition(
                condition,
                originals_dir=originals_dir,
                manifest_path=manifest_path,
                experiments_dir=experiments_dir,
                recovered_dir=recovered_dir,
                manifest=manifest,
                log=log,
                max_size=max_size,
            )
        )
    return results


def _load_candidate_payloads(candidates: list[CarveCandidate]) -> dict[str, bytes]:
    """Read back the carved candidate bytes, keyed by candidate identifier."""
    payloads: dict[str, bytes] = {}
    for candidate in candidates:
        if not candidate.output_path:
            continue
        path = Path(candidate.output_path)
        if not path.is_absolute():
            from .paths import PROJECT_ROOT

            path = PROJECT_ROOT / candidate.output_path
        if path.exists():
            payloads[candidate.candidate_id] = path.read_bytes()
    return payloads


def load_experiment_metrics(
    experiments_dir: str | Path = EXPERIMENTS_DIR,
) -> list[ConditionMetrics]:
    """Load the metrics of every experiment that was run so far."""
    directory = Path(experiments_dir)
    metrics: list[ConditionMetrics] = []
    for path in sorted(directory.glob("*/metrics.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        metrics.append(_metrics_from_dict(raw))
    return metrics


def _metrics_from_dict(raw: dict[str, Any]) -> ConditionMetrics:
    """Rebuild a :class:`ConditionMetrics` object from its serialised form."""
    from .metrics import FileOutcome, Score

    def _score(raw_score: dict[str, Any]) -> Score:
        return Score(
            tp=raw_score.get("tp", 0),
            fp=raw_score.get("fp", 0),
            fn=raw_score.get("fn", 0),
            precision=raw_score.get("precision", 0.0),
            recall=raw_score.get("recall", 0.0),
            f1=raw_score.get("f1", 0.0),
        )

    return ConditionMetrics(
        condition=raw.get("condition", ""),
        experiment_id=raw.get("experiment_id", ""),
        image_path=raw.get("image_path", ""),
        image_sha256=raw.get("image_sha256", ""),
        ground_truth_files=raw.get("ground_truth_files", 0),
        ground_truth_instances=raw.get("ground_truth_instances", 0),
        detection=_score(raw.get("detection", {})),
        exact_recovery=_score(raw.get("exact_recovery", {})),
        span_recovery=raw.get("span_recovery", 0),
        mean_byte_coverage=raw.get("mean_byte_coverage", 0.0),
        data_completeness=raw.get("data_completeness", 0.0),
        per_signature={
            name: _score(value) for name, value in raw.get("per_signature", {}).items()
        },
        outcomes=[
            FileOutcome(
                file_id=item.get("file_id", ""),
                signature=item.get("signature"),
                detected=item.get("detected", False),
                detection_offset=item.get("detection_offset"),
                carved=item.get("carved", False),
                candidate_id=item.get("candidate_id"),
                status=item.get("status", ""),
                extent_policy=item.get("extent_policy", ""),
                exact=item.get("exact", False),
                span=item.get("span", False),
                byte_coverage=item.get("byte_coverage", 0.0),
                expected_sha256=item.get("expected_sha256", ""),
                actual_sha256=item.get("actual_sha256"),
                note=item.get("note", ""),
            )
            for item in raw.get("outcomes", [])
        ],
        false_positives=raw.get("false_positives", []),
        notes=raw.get("notes", []),
    )


def summarise(results: list[ExperimentResult]) -> dict[str, Any]:
    """Return a cross-condition overview of a set of experiment results."""
    metrics = [result.metrics for result in results if result.metrics is not None]
    return summarise_runs(metrics)


if __name__ == "__main__":  # pragma: no cover - manual helper
    from .experiment_log import default_log

    run_results = run_all_conditions(log=default_log())
    print(json.dumps(summarise(run_results), indent=2))
