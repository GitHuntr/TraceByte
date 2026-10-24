"""Local intake and repeatable scans for user-supplied evidence files.

Imported sources are content-addressed copies. The original selected by the
operator is never opened or modified by this module after upload; scans use the
stored copy and record its SHA-256 alongside every candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Any

from . import paths
from .carver import TOOL_VERSION, carve_file
from .experiment_log import ExperimentLog, utc_now_iso
from .signatures import DEFAULT_MAX_CANDIDATE_SIZE

MAX_EVIDENCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_EVIDENCE_CANDIDATES = 5000
MAX_EVIDENCE_OUTPUT_BYTES = 512 * 1024 * 1024
EVIDENCE_CANDIDATE_SIZES_MB = (8, 16, 32, 64)
UPLOAD_CHUNK_SIZE = 1024 * 1024
_SOURCE_ID = re.compile(r"^[0-9a-f]{64}$")
_SCAN_ID = re.compile(r"^evidence-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


class EvidenceError(ValueError):
    """Raised when evidence intake or lookup cannot be completed safely."""


def _root() -> Path:
    return paths.DATA_DIR / "evidence"


def _source_dir() -> Path:
    return _root() / "sources"


def _scan_dir() -> Path:
    return _root() / "scans"


def _ensure_dirs() -> None:
    _source_dir().mkdir(parents=True, exist_ok=True)
    _scan_dir().mkdir(parents=True, exist_ok=True)
    (paths.RECOVERED_DIR / "evidence").mkdir(parents=True, exist_ok=True)


def _display_name(filename: str) -> str:
    value = str(filename or "evidence.bin").replace("\\", "/").split("/")[-1]
    value = "".join(char for char in value if ord(char) >= 32 and ord(char) != 127)
    value = value.strip(" .")[:240]
    return value or "evidence.bin"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"Saved evidence record could not be read: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"Saved evidence record is invalid: {path.name}")
    return value


def import_evidence(
    filename: str,
    expected_size: int,
    stream: BinaryIO,
    *,
    log: ExperimentLog | None = None,
) -> dict[str, Any]:
    """Stream an upload to a new, immutable, SHA-256-addressed source copy."""
    if expected_size <= 0:
        raise EvidenceError("Choose a non-empty evidence file.")
    if expected_size > MAX_EVIDENCE_BYTES:
        raise EvidenceError("Evidence files may be up to 2 GiB.")

    _ensure_dirs()
    fd, temp_name = tempfile.mkstemp(prefix=".incoming-", dir=_source_dir())
    digest = hashlib.sha256()
    received = 0
    try:
        with os.fdopen(fd, "wb") as output:
            while received < expected_size:
                chunk = stream.read(min(UPLOAD_CHUNK_SIZE, expected_size - received))
                if not chunk:
                    raise EvidenceError("The upload ended before the complete file arrived.")
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
            output.flush()
            os.fsync(output.fileno())

        source_id = digest.hexdigest()
        source_path = _source_dir() / f"{source_id}.source"
        metadata_path = _source_dir() / f"{source_id}.json"
        duplicate = source_path.exists()
        if duplicate:
            if source_path.stat().st_size != expected_size:
                raise EvidenceError("A stored source with this fingerprint has an unexpected size.")
            # Content addressing must never cause an existing source to be replaced.
            from .hashing import sha256_file

            if sha256_file(source_path) != source_id:
                raise EvidenceError("The stored evidence copy failed its SHA-256 check.")
        else:
            try:
                os.link(temp_name, source_path)
            except FileExistsError:
                duplicate = True
            if duplicate:
                from .hashing import sha256_file

                if source_path.stat().st_size != expected_size or sha256_file(source_path) != source_id:
                    raise EvidenceError("A stored source with this fingerprint failed verification.")

        if metadata_path.exists():
            record = _load_json(metadata_path)
        else:
            record = {
                "source_id": source_id,
                "original_name": _display_name(filename),
                "size_bytes": expected_size,
                "sha256": source_id,
                "imported_utc": utc_now_iso(),
                "storage_name": source_path.name,
            }
            _write_json(metadata_path, record)
        record = {**record, "duplicate": duplicate}
        if log:
            log.append(
                "evidence.imported",
                {
                    "source_id": source_id,
                    "original_name": record["original_name"],
                    "size_bytes": expected_size,
                    "sha256": source_id,
                    "duplicate": duplicate,
                },
                actor="tracebyte.web",
            )
        return record
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _source_record(source_id: str) -> tuple[dict[str, Any], Path]:
    if not _SOURCE_ID.fullmatch(str(source_id)):
        raise EvidenceError("Evidence source was not found.")
    source_dir = _source_dir()
    record = _load_json(source_dir / f"{source_id}.json")
    source_path = source_dir / f"{source_id}.source"
    if not source_path.is_file():
        raise EvidenceError("The stored evidence copy is missing.")
    if record.get("source_id") != source_id or record.get("sha256") != source_id:
        raise EvidenceError("The stored evidence record does not match its source.")
    return record, source_path


def list_sources() -> list[dict[str, Any]]:
    _ensure_dirs()
    records: list[dict[str, Any]] = []
    for path in _source_dir().glob("*.json"):
        try:
            records.append(_load_json(path))
        except EvidenceError:
            continue
    records.sort(key=lambda item: str(item.get("imported_utc", "")), reverse=True)
    scans = list_scans()
    latest_by_source: dict[str, dict[str, Any]] = {}
    for scan in scans:
        source_id = str(scan.get("source_id", ""))
        if source_id and source_id not in latest_by_source:
            latest_by_source[source_id] = scan
    for record in records:
        latest = latest_by_source.get(str(record.get("source_id", "")))
        record["latest_scan_id"] = latest.get("scan_id") if latest else None
        record["scan_count"] = sum(1 for scan in scans if scan.get("source_id") == record.get("source_id"))
    return records


def list_scans() -> list[dict[str, Any]]:
    _ensure_dirs()
    records: list[dict[str, Any]] = []
    for path in _scan_dir().glob("*/scan.json"):
        if not _SCAN_ID.fullmatch(path.parent.name):
            continue
        try:
            record = _load_json(path)
            # Keep lists small in the workspace overview; details load on demand.
            records.append({key: value for key, value in record.items() if key != "candidates"})
        except EvidenceError:
            continue
    records.sort(key=lambda item: str(item.get("created_utc", "")), reverse=True)
    return records


def get_scan(scan_id: str) -> dict[str, Any]:
    if not _SCAN_ID.fullmatch(str(scan_id)):
        raise EvidenceError("Evidence scan was not found.")
    return _load_json(_scan_dir() / scan_id / "scan.json")


def scan_evidence(
    source_id: str,
    *,
    candidate_max_size_mb: int = DEFAULT_MAX_CANDIDATE_SIZE // (1024 * 1024),
    log: ExperimentLog | None = None,
) -> dict[str, Any]:
    """Scan an imported source copy and save a candidate report and outputs."""
    if (
        isinstance(candidate_max_size_mb, bool)
        or not isinstance(candidate_max_size_mb, int)
        or candidate_max_size_mb not in EVIDENCE_CANDIDATE_SIZES_MB
    ):
        choices = ", ".join(str(value) for value in EVIDENCE_CANDIDATE_SIZES_MB)
        raise EvidenceError(f"Candidate size must be one of {choices} MiB.")
    source, source_path = _source_record(source_id)
    now = datetime.now(timezone.utc)
    scan_id = f"evidence-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    metadata_path = _scan_dir() / scan_id / "scan.json"
    output_dir = paths.RECOVERED_DIR / "evidence" / scan_id
    record: dict[str, Any] = {
        "scan_id": scan_id,
        "source_id": source_id,
        "original_name": source["original_name"],
        "size_bytes": source["size_bytes"],
        "source_sha256": source["sha256"],
        "created_utc": now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "candidate_max_size_bytes": candidate_max_size_mb * 1024 * 1024,
        "status": "running",
        "candidate_count": 0,
        "delimited_count": 0,
        "truncated_count": 0,
        "candidates": [],
        "report_name": "carve_results.json",
    }
    _write_json(metadata_path, record)
    try:
        candidates = carve_file(
            source_path,
            output_dir=output_dir,
            experiment_id=scan_id,
            condition="real_evidence",
            max_size=candidate_max_size_mb * 1024 * 1024,
            expected_source_sha256=str(source["sha256"]),
            max_candidates=MAX_EVIDENCE_CANDIDATES,
            max_output_bytes=MAX_EVIDENCE_OUTPUT_BYTES,
        )
        report_path = metadata_path.parent / "carve_results.json"
        _write_json(
            report_path,
            {
                "tool_version": TOOL_VERSION,
                "scan": {
                    "scan_id": scan_id,
                    "created_utc": record["created_utc"],
                    "candidate_max_size_bytes": record["candidate_max_size_bytes"],
                },
                "source": {
                    "original_name": source["original_name"],
                    "size_bytes": source["size_bytes"],
                    "sha256": source["sha256"],
                },
                "candidate_count": len(candidates),
                "candidates": [item.to_dict() for item in candidates],
            },
        )
        record.update(
            {
                "status": "complete",
                "candidate_count": len(candidates),
                "delimited_count": sum(item.structurally_delimited for item in candidates),
                "truncated_count": sum(item.is_truncated for item in candidates),
                "output_limited_count": sum(
                    bool(item.metadata.get("output_skipped_reason")) for item in candidates
                ),
                "formats_found": sorted({item.signature for item in candidates}),
                "report_name": report_path.name,
                "candidates": [item.to_dict() for item in candidates],
            }
        )
        _write_json(metadata_path, record)
        if log:
            log.append(
                "evidence.scan_completed",
                {
                    "scan_id": scan_id,
                    "source_id": source_id,
                    "source_sha256": source["sha256"],
                    "candidate_count": len(candidates),
                    "delimited_count": record["delimited_count"],
                    "truncated_count": record["truncated_count"],
                    "report": f"data/evidence/scans/{scan_id}/{report_path.name}",
                },
                actor="tracebyte.web",
            )
        return record
    except Exception as exc:
        record.update({"status": "failed", "error": str(exc)})
        _write_json(metadata_path, record)
        from .signatures import SignatureError

        if isinstance(exc, SignatureError):
            raise EvidenceError(str(exc)) from exc
        raise


def candidate_file(scan_id: str, output_name: str) -> tuple[Path, str]:
    """Return a safe candidate download path and its generated filename."""
    scan = get_scan(scan_id)
    if Path(output_name).name != output_name:
        raise EvidenceError("Candidate file was not found.")
    for candidate in scan.get("candidates", []):
        output_path = candidate.get("output_path")
        if output_path and Path(output_path).name == output_name:
            path = paths.PROJECT_ROOT / Path(output_path)
            root = (paths.RECOVERED_DIR / "evidence" / scan_id).resolve()
            try:
                path.resolve().relative_to(root)
            except ValueError as exc:
                raise EvidenceError("Candidate file was not found.") from exc
            if path.is_file():
                return path, output_name
    raise EvidenceError("Candidate file was not found.")


def scan_report_file(scan_id: str) -> tuple[Path, str]:
    """Return the saved JSON provenance report for a completed scan."""
    scan = get_scan(scan_id)
    report_name = str(scan.get("report_name", "carve_results.json"))
    if Path(report_name).name != report_name:
        raise EvidenceError("Scan report was not found.")
    path = _scan_dir() / scan_id / report_name
    root = (_scan_dir() / scan_id).resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise EvidenceError("Scan report was not found.") from exc
    if not path.is_file():
        raise EvidenceError("This scan has no downloadable report.")
    return path, report_name
