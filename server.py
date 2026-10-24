"""Local web workstation for TraceByte.

This HTTP layer only adapts requests to the existing ``src`` library. The
forensic engine, artefact format, and persistence rules remain in ``src``.
Run with ``python server.py`` and open http://127.0.0.1:8510.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.paths as paths
from src.experiment_log import ExperimentLog, default_log
from src.experiments import list_runs, metrics_files_for_run, run_all_conditions, summarise
from src.evidence import (
    MAX_EVIDENCE_BYTES,
    EvidenceError,
    candidate_file,
    get_scan,
    import_evidence,
    list_scans,
    list_sources,
    scan_report_file,
    scan_evidence,
)
from src.fixtures import FIXTURE_SPECS, initialize_dataset
from src.integrity import detection_self_test, run_integrity_check, summarize
from src.manifest import load_manifest
from src.signatures import default_registry


def _manifest() -> object:
    return load_manifest(paths.MANIFEST_PATH)


def _integrity_payload() -> dict[str, object]:
    manifest = _manifest()
    results = run_integrity_check(manifest, paths.ORIGINALS_DIR)
    summary = summarize(results)
    return {
        "summary": summary,
        "results": [
            {
                "fixture_id": item.fixture_id,
                "filename": item.filename,
                "path": item.path,
                "status": item.status.label,
                "expected_sha256": item.expected_sha256,
                "actual_sha256": item.actual_sha256,
                "expected_size": item.expected_size,
                "actual_size": item.actual_size,
                "description": item.description,
                "message": item.message,
            }
            for item in results
        ],
    }


def _runs_payload() -> list[dict[str, object]]:
    return [
        {
            "run_id": run.run_id,
            "created_utc": run.created_utc,
            "legacy": run.legacy,
            "conditions": list(run.conditions),
            "status": run.status,
        }
        for run in list_runs(paths.EXPERIMENTS_DIR)
    ]


def _dataset_payload() -> dict[str, object]:
    manifest = _manifest()
    integrity = _integrity_payload()
    entries = [manifest.entries[name].to_dict() for name in manifest.filenames()]
    return {
        "manifest": {
            "version": manifest.manifest_version,
            "name": manifest.dataset_name,
            "description": manifest.dataset_description,
            "created_utc": manifest.created_utc,
            "updated_utc": manifest.updated_utc,
            "tool_versions": manifest.tool_versions,
            "entries": entries,
        },
        "integrity": integrity["summary"],
        "catalogue": [
            {
                "fixture_id": spec.fixture_id,
                "filename": spec.filename,
                "description": spec.description,
                "signature_hex": spec.signature_hex.upper(),
                "signature_offset": spec.signature_offset,
                "notes": spec.notes,
            }
            for spec in FIXTURE_SPECS
        ],
    }


def _log_payload(query: dict[str, list[str]]) -> dict[str, object]:
    events = ExperimentLog(paths.EXPERIMENT_LOG_PATH, enabled=False).read_events()
    event_type = (query.get("event") or [""])[0]
    actor = (query.get("actor") or [""])[0]
    filtered = [
        item for item in events
        if (not event_type or item.get("event") == event_type)
        and (not actor or item.get("actor") == actor)
    ]
    return {
        "events": list(reversed(filtered)),
        "event_types": sorted({str(item.get("event", "")) for item in events}),
        "actors": sorted({str(item.get("actor", "")) for item in events}),
    }


def _evidence_scan_payload(record: dict[str, object]) -> dict[str, object]:
    """Expose candidate filenames without returning local filesystem paths."""
    payload = dict(record)
    candidates = []
    raw_candidates = record.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        output_path = candidate.pop("output_path", None)
        candidate.pop("source_path", None)
        candidate["output_name"] = Path(output_path).name if output_path else None
        candidates.append(candidate)
    payload["candidates"] = candidates
    return payload


class TraceByteHandler(BaseHTTPRequestHandler):
    server_version = "TraceByte/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send(self, status: int, payload: object, content_type: str = "application/json; charset=utf-8") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_attachment(self, path: Path, filename: str) -> None:
        data = path.read_bytes()
        safe_name = "".join(
            char for char in Path(filename).name
            if ord(char) < 128 and (char.isalnum() or char in "._-")
        )[:180] or "download.bin"
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        try:
            if route == "/api/health":
                return self._send(200, {"status": "ok", "project": "TraceByte", "reference": "DF-PBL-016"})
            if route == "/api/overview":
                integrity = _integrity_payload()
                events = ExperimentLog(paths.EXPERIMENT_LOG_PATH, enabled=False)
                return self._send(200, {
                    "integrity": integrity["summary"],
                    "fixture_count": len(_manifest().entries),
                    "runs": _runs_payload(),
                    "event_count": events.event_count(),
                    "latest_events": list(reversed(events.read_events(limit=5))),
                })
            if route == "/api/dataset":
                return self._send(200, _dataset_payload())
            if route == "/api/integrity":
                return self._send(200, _integrity_payload())
            if route == "/api/runs":
                return self._send(200, {"runs": _runs_payload()})
            if route == "/api/evidence":
                return self._send(200, {"sources": list_sources(), "scans": list_scans()})
            if route.startswith("/api/evidence/scans/"):
                parts = route.removeprefix("/api/evidence/scans/").split("/")
                if len(parts) == 1:
                    return self._send(200, _evidence_scan_payload(get_scan(unquote(parts[0]))))
                if len(parts) == 2 and parts[1] == "report":
                    path, filename = scan_report_file(unquote(parts[0]))
                    return self._send_attachment(path, filename)
                if len(parts) == 3 and parts[1] == "files":
                    path, filename = candidate_file(unquote(parts[0]), unquote(parts[2]))
                    return self._send_attachment(path, filename)
            if route.startswith("/api/fixtures/") and route.endswith("/hex"):
                filename = unquote(route.removeprefix("/api/fixtures/").removesuffix("/hex").strip("/"))
                entry = _manifest().entries.get(filename)
                if entry is None or Path(filename).name != filename:
                    return self._send(404, {"error": "Fixture not found in the recorded baseline"})
                source = paths.ORIGINALS_DIR / filename
                if not source.is_file():
                    return self._send(404, {"error": "Fixture is missing from disk"})
                content = source.read_bytes()[:128]
                lines = []
                for offset in range(0, len(content), 16):
                    chunk = content[offset:offset + 16]
                    hex_part = " ".join(f"{value:02X}" for value in chunk).ljust(47)
                    ascii_part = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
                    lines.append({"offset": f"{offset:08X}", "hex": hex_part, "ascii": ascii_part})
                return self._send(200, {"filename": filename, "size_bytes": source.stat().st_size, "lines": lines})
            if route.startswith("/api/runs/"):
                run_id = unquote(route.removeprefix("/api/runs/"))
                files = metrics_files_for_run(paths.EXPERIMENTS_DIR, run_id)
                records = []
                for path in files:
                    try:
                        records.append(json.loads(path.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError):
                        continue
                return self._send(200, {"run_id": run_id, "records": records})
            if route == "/api/log":
                return self._send(200, _log_payload(query))
            return self._send_static(route)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            if self.path == "/api/evidence/import":
                raw_length = self.headers.get("Content-Length")
                if raw_length is None:
                    return self._send(411, {"error": "A file size is required for evidence upload."})
                try:
                    length = int(raw_length)
                except ValueError:
                    return self._send(400, {"error": "The upload size is invalid."})
                if length > MAX_EVIDENCE_BYTES:
                    return self._send(413, {"error": "Evidence files may be up to 2 GiB."})
                filename = unquote(self.headers.get("X-TraceByte-Filename", "evidence.bin"))
                record = import_evidence(filename, length, self.rfile, log=default_log())
                return self._send(201, record)
            if self.path == "/api/evidence/scans":
                body = self._body()
                record = scan_evidence(
                    str(body.get("source_id", "")),
                    candidate_max_size_mb=body.get("candidate_max_size_mb", 8),
                    log=default_log(),
                )
                return self._send(201, _evidence_scan_payload(record))
            if self.path == "/api/dataset/initialize":
                report = initialize_dataset(log=default_log())
                return self._send(200, {
                    "created_count": report.created_count,
                    "preserved_count": report.preserved_count,
                    "adopted_count": report.adopted_count,
                    "mismatch_count": report.mismatch_count,
                    "manifest_written": report.manifest_written,
                    "actions": [vars(action) for action in report.actions],
                    "warnings": report.warnings,
                })
            if self.path == "/api/integrity/self-test":
                result = detection_self_test(_manifest(), paths.ORIGINALS_DIR)
                return self._send(200, result)
            if self.path == "/api/runs":
                report = run_all_conditions(log=default_log())
                return self._send(200, {
                    "run_id": report[0].run_id if report else "",
                    "summary": summarise(report),
                })
            return self._send(404, {"error": "Endpoint not found"})
        except EvidenceError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def _send_static(self, route: str) -> None:
        relative = "index.html" if route == "/" else route.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return self._send(404, {"error": "Not found"})
        if not target.is_file():
            return self._send(404, {"error": "Not found"})
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        return self._send(200, target.read_bytes(), content_type)


def main() -> None:
    paths.ensure_project_directories()
    host = os.environ.get("TRACEBYTE_HOST", "127.0.0.1")
    configured_port = os.environ.get("TRACEBYTE_PORT")
    port = int(configured_port or "8510")
    try:
        server = ThreadingHTTPServer((host, port), TraceByteHandler)
    except OSError:
        if configured_port is not None:
            raise
        requested_port = port
        for candidate_port in range(requested_port + 1, min(requested_port + 20, 65536)):
            try:
                server = ThreadingHTTPServer((host, candidate_port), TraceByteHandler)
                port = candidate_port
                break
            except OSError:
                continue
        else:
            raise OSError(
                f"Ports {requested_port}-{min(requested_port + 19, 65535)} are unavailable. "
                "Set TRACEBYTE_PORT to choose an open port."
            )
    print(f"TraceByte workstation: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTraceByte workstation stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
