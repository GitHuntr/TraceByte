"""Experiment runner: build an image, carve it, measure the result, log it.

Stage 2 component E.

The runner is the only place where the three stages meet:

1. :mod:`src.conditions` builds a controlled image and records the ground
   truth.
2. :mod:`src.carver` carves that image without ever seeing the ground truth.
3. :mod:`src.metrics` compares the carved candidates with the ground truth.

Every artefact is written to disk so that a run can be inspected, reproduced
and audited afterwards.

Artefact layout
---------------
Every run owns a directory of its own, so that two runs can never overwrite
each other and so that the candidates of a run stay together::

    <experiments_dir>/<run_id>/run.json                  # run manifest
    <experiments_dir>/<run_id>/exp-<condition>/image.bin
    <experiments_dir>/<run_id>/exp-<condition>/ground_truth.json
    <experiments_dir>/<run_id>/exp-<condition>/carve_results.json
    <experiments_dir>/<run_id>/exp-<condition>/metrics.json
    <recovered_dir>/<run_id>/exp-<condition>/<candidate files>

Nothing is ever deleted: an earlier run keeps its image, its measurements and
its candidates. The artefacts that were written before this layout existed
stay where they are and are exposed as the read-only ``legacy`` run.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths
from .carver import CarveCandidate, carve_file, write_candidate_report
from .conditions import (
    CONDITION_CONTIGUOUS,
    CONDITION_FRAGMENTED,
    CONDITION_OVERWRITTEN,
    BuiltImage,
    build_image,
    load_ground_truth,
)
from .experiment_log import ExperimentLog, utc_now_iso
from .manifest import Manifest, load_manifest, resolve_manifest_path
from .metrics import ConditionMetrics, evaluate_condition, summarise_runs
from .paths import relative_to_project

EXPERIMENT_ACTOR = "filecarvelab.stage2"

CARVE_REPORT_NAME = "carve_results.json"
METRICS_NAME = "metrics.json"
GROUND_TRUTH_NAME = "ground_truth.json"
IMAGE_NAME = "image.bin"

#: Name of the manifest that describes one experiment run.
RUN_MANIFEST_NAME = "run.json"

#: Identifier of the pseudo run that holds the artefacts written before the
#: per-run layout existed. It is read-only: those files are never modified.
LEGACY_RUN_ID = "legacy"


def experiment_id_for(condition: str) -> str:
    """Return the deterministic experiment identifier for *condition*."""
    return f"exp-{condition}"


def new_run_id(now: datetime | None = None) -> str:
    """Return a unique identifier for one experiment run.

    The identifier is timestamped so that runs sort chronologically and it
    carries a random suffix so that two runs started in the same second can
    never share a directory.
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:8]}"


def _utc_now_micro() -> str:
    """Return the current UTC time with microsecond precision.

    The run manifest needs a finer resolution than the provenance log: two
    runs can start within the same second and must still be ordered.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class RunInfo:
    """One experiment run and the artefacts it produced."""

    run_id: str
    created_utc: str
    path: Path
    legacy: bool = False
    conditions: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Return a human readable label for the run."""
        if self.legacy:
            return f"{LEGACY_RUN_ID} (artefacts from before the per-run layout)"
        return f"{self.run_id} ({self.created_utc})"


@dataclass
class ExperimentResult:
    """Everything one experimental run produced."""

    experiment_id: str
    condition: str
    image: BuiltImage
    run_id: str = ""
    candidates: list[CarveCandidate] = field(default_factory=list)
    metrics: ConditionMetrics | None = None
    artefacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "condition": self.condition,
            "run_id": self.run_id,
            "image": self.image.to_dict(),
            "candidate_count": len(self.candidates),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "artefacts": self.artefacts,
        }


def run_condition(
    condition: str,
    *,
    originals_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    experiments_dir: str | Path | None = None,
    recovered_dir: str | Path | None = None,
    manifest: Manifest | None = None,
    log: ExperimentLog | None = None,
    max_size: int = 8 * 1024 * 1024,
    run_id: str | None = None,
) -> ExperimentResult:
    """Run one storage condition end to end.

    The artefacts are written below ``<experiments_dir>/<run_id>/`` and
    ``<recovered_dir>/<run_id>/``. A run never overwrites the artefacts of
    another run and nothing is ever deleted.

    The canonical locations are resolved when the run starts, not when this
    module is imported, so a redirected workspace is honoured.
    """
    explicit_originals_dir = originals_dir is not None
    originals_dir = (
        Path(originals_dir) if originals_dir is not None else paths.ORIGINALS_DIR
    )
    manifest_path = resolve_manifest_path(
        originals_dir if explicit_originals_dir else None, manifest_path
    )
    experiments_dir = (
        Path(experiments_dir) if experiments_dir is not None else paths.EXPERIMENTS_DIR
    )
    recovered_dir = (
        Path(recovered_dir) if recovered_dir is not None else paths.RECOVERED_DIR
    )

    manifest = manifest if manifest is not None else load_manifest(manifest_path)
    experiment_id = experiment_id_for(condition)
    run_id = run_id or new_run_id()

    run_dir = experiments_dir / run_id
    experiment_dir = run_dir / experiment_id
    recovered_run_dir = recovered_dir / run_id

    image = build_image(
        condition,
        originals_dir=originals_dir,
        manifest=manifest,
        output_dir=run_dir,
        experiment_id=experiment_id,
    )

    image_file = experiment_dir / IMAGE_NAME

    candidates = carve_file(
        image_file,
        output_dir=recovered_run_dir / experiment_id,
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
        run_id=run_id,
    )

    metrics_path = experiment_dir / METRICS_NAME
    metrics_path.write_text(
        json.dumps(metrics.to_dict(), indent=2), encoding="utf-8"
    )

    result = ExperimentResult(
        experiment_id=experiment_id,
        condition=condition,
        image=image,
        run_id=run_id,
        candidates=candidates,
        metrics=metrics,
        artefacts={
            "image": relative_to_project(image_file),
            "ground_truth": relative_to_project(experiment_dir / GROUND_TRUTH_NAME),
            "carve_results": relative_to_project(carve_report),
            "metrics": relative_to_project(metrics_path),
            "recovered_dir": relative_to_project(recovered_run_dir / experiment_id),
        },
    )

    _record_run_manifest(
        run_dir,
        run_id=run_id,
        condition=condition,
        experiment_id=experiment_id,
        artefacts=result.artefacts,
        candidate_count=len(candidates),
    )

    if log is not None:
        log.append(
            "experiment_completed",
            {
                "experiment_id": experiment_id,
                "experiment_run_id": run_id,
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
    originals_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    experiments_dir: str | Path | None = None,
    recovered_dir: str | Path | None = None,
    manifest: Manifest | None = None,
    log: ExperimentLog | None = None,
    max_size: int = 8 * 1024 * 1024,
    run_id: str | None = None,
) -> list[ExperimentResult]:
    """Run all three storage conditions in order.

    The three conditions share one run identifier, so their artefacts form a
    single, self-contained run.
    """
    manifest_path = resolve_manifest_path(originals_dir, manifest_path)
    manifest = manifest if manifest is not None else load_manifest(manifest_path)
    run_id = run_id or new_run_id()
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
                run_id=run_id,
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


def _record_run_manifest(
    run_dir: Path,
    *,
    run_id: str,
    condition: str,
    experiment_id: str,
    artefacts: dict[str, str],
    candidate_count: int,
) -> Path:
    """Add one condition to the manifest of *run_dir* and write it to disk.

    The manifest of an existing run is updated in place, so the three
    conditions of one run end up in a single manifest.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / RUN_MANIFEST_NAME

    payload: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict):
            payload = existing

    payload["run_id"] = payload.get("run_id") or run_id
    payload["created_utc"] = payload.get("created_utc") or _utc_now_micro()
    payload["updated_utc"] = _utc_now_micro()
    payload["tool_version"] = payload.get("tool_version") or EXPERIMENT_ACTOR

    entries = [
        entry
        for entry in payload.get("conditions", [])
        if isinstance(entry, dict) and entry.get("experiment_id") != experiment_id
    ]
    entries.append(
        {
            "experiment_id": experiment_id,
            "condition": condition,
            "candidate_count": candidate_count,
            "artefacts": artefacts,
        }
    )
    entries.sort(key=lambda entry: entry.get("experiment_id", ""))
    payload["conditions"] = entries

    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def load_run_manifest(path: str | Path) -> dict[str, Any]:
    """Load the manifest of one run.

    A missing or unreadable manifest yields an empty dict instead of raising,
    so that a damaged run cannot hide the other runs.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def list_runs(experiments_dir: str | Path | None = None) -> list[RunInfo]:
    """Return every run found below *experiments_dir*, oldest first.

    The artefacts that were written before the per-run layout existed are
    exposed as a single read-only pseudo run called ``legacy``. They are never
    modified or deleted.
    """
    directory = Path(experiments_dir) if experiments_dir is not None else paths.EXPERIMENTS_DIR
    if not directory.is_dir():
        return []

    runs: list[RunInfo] = []
    legacy_dirs: list[Path] = []
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / RUN_MANIFEST_NAME
        if manifest_path.is_file():
            payload = load_run_manifest(manifest_path)
            conditions = tuple(
                entry.get("experiment_id", "")
                for entry in payload.get("conditions", [])
                if isinstance(entry, dict)
            )
            runs.append(
                RunInfo(
                    run_id=payload.get("run_id") or child.name,
                    created_utc=payload.get("created_utc", ""),
                    path=child,
                    legacy=False,
                    conditions=conditions,
                )
            )
        elif child.name.startswith("exp-"):
            legacy_dirs.append(child)

    if legacy_dirs:
        newest = max(path.stat().st_mtime for path in legacy_dirs)
        runs.append(
            RunInfo(
                run_id=LEGACY_RUN_ID,
                created_utc=datetime.fromtimestamp(newest, tz=timezone.utc).isoformat(
                    timespec="seconds"
                ),
                path=directory,
                legacy=True,
                conditions=tuple(path.name for path in legacy_dirs),
            )
        )

    runs.sort(key=lambda run: (run.created_utc, run.run_id))
    return runs


def latest_run(experiments_dir: str | Path | None = None) -> RunInfo | None:
    """Return the most recent run, or ``None`` when nothing was ever run.

    A real run always wins over the legacy pseudo run: the legacy artefacts
    are older by definition.
    """
    runs = list_runs(experiments_dir)
    real_runs = [run for run in runs if not run.legacy]
    if real_runs:
        return real_runs[-1]
    return runs[-1] if runs else None


def _resolve_run_id(directory: Path, run_id: str | None) -> str | None:
    """Return the run the caller asked for, or the latest one."""
    if run_id is not None:
        return run_id
    run = latest_run(directory)
    return run.run_id if run is not None else None


def metrics_files_for_run(
    experiments_dir: str | Path | None = None,
    run_id: str | None = None,
) -> list[Path]:
    """Return the metrics files that belong to one run.

    Without *run_id* the metrics of the latest run are returned.
    """
    directory = Path(experiments_dir) if experiments_dir is not None else paths.EXPERIMENTS_DIR
    resolved = _resolve_run_id(directory, run_id)
    if resolved is None:
        return []
    if resolved == LEGACY_RUN_ID:
        return sorted(directory.glob("*/metrics.json"))
    return sorted((directory / resolved).glob("*/metrics.json"))


def load_experiment_metrics(
    experiments_dir: str | Path | None = None,
    run_id: str | None = None,
) -> list[ConditionMetrics]:
    """Load the measurements of one run.

    Only the artefacts of the intended run are loaded: without *run_id* that
    is the latest run, with *run_id="legacy"* the artefacts that were written
    before the per-run layout existed.
    """
    directory = Path(experiments_dir) if experiments_dir is not None else paths.EXPERIMENTS_DIR
    resolved = _resolve_run_id(directory, run_id)
    metrics: list[ConditionMetrics] = []
    for path in metrics_files_for_run(directory, resolved):
        raw = json.loads(path.read_text(encoding="utf-8"))
        condition = _metrics_from_dict(raw)
        if not condition.run_id and resolved:
            condition.run_id = resolved
        metrics.append(condition)
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
        run_id=raw.get("run_id", ""),
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
