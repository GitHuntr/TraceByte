"""HTTP smoke tests for the TraceByte Forensic Workbench."""

from __future__ import annotations

import json
import hashlib
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.paths as paths
from server import TraceByteHandler


@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the workbench to a temporary evidence workspace."""
    originals = tmp_path / "originals"
    logs = tmp_path / "logs"
    experiments = tmp_path / "experiments"
    recovered = tmp_path / "recovered"
    data = tmp_path / "data"
    for directory in (originals, logs, experiments, recovered, data):
        directory.mkdir()
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)
    monkeypatch.setattr(paths, "MANIFEST_PATH", originals / "manifest.json")
    monkeypatch.setattr(paths, "EXPERIMENT_LOG_PATH", logs / "experiment_log.jsonl")
    monkeypatch.setattr(paths, "EXPERIMENTS_DIR", experiments)
    monkeypatch.setattr(paths, "RECOVERED_DIR", recovered)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    return originals


@pytest.fixture()
def workbench(isolated_paths: Path):
    """Serve the real request handler on an ephemeral loopback port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), TraceByteHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def request(
    workbench: str,
    route: str,
    method: str = "GET",
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, object, str]:
    request_body = body if body is not None else b"{}" if method == "POST" else None
    req = Request(workbench + route, data=request_body, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                body = json.loads(body)
            return response.status, body, content_type
    except HTTPError as error:
        return error.code, json.loads(error.read()), error.headers.get("Content-Type", "")


def test_workbench_serves_shell_and_health(workbench: str) -> None:
    status, body, content_type = request(workbench, "/")
    assert status == 200
    assert "text/html" in content_type
    assert b"TRACEBYTE" in body

    status, payload, _ = request(workbench, "/api/health")
    assert status == 200
    assert payload["status"] == "ok"


def test_dataset_initialization_and_hex_preview_are_available(workbench: str) -> None:
    status, result, _ = request(workbench, "/api/dataset/initialize", "POST")
    assert status == 200
    assert result["created_count"] > 0

    status, data, _ = request(workbench, "/api/dataset")
    assert status == 200
    assert len(data["manifest"]["entries"]) == result["created_count"]

    status, preview, _ = request(workbench, "/api/fixtures/synthetic_photo_01.jpg/hex")
    assert status == 200
    assert preview["lines"]
    assert preview["lines"][0]["offset"] == "00000000"


def test_integrity_status_and_change_detection_self_test(workbench: str) -> None:
    request(workbench, "/api/dataset/initialize", "POST")
    status, report, _ = request(workbench, "/api/integrity")
    assert status == 200
    assert report["summary"]["MATCH"] > 0
    assert all(row["status"] == "MATCH" for row in report["results"])

    status, result, _ = request(workbench, "/api/integrity/self-test", "POST")
    assert status == 200
    assert result["ok"] is True


def test_run_api_persists_and_reads_measurements_in_isolation(workbench: str) -> None:
    request(workbench, "/api/dataset/initialize", "POST")
    status, result, _ = request(workbench, "/api/runs", "POST")
    assert status == 200
    assert result["run_id"].startswith("run-")

    status, data, _ = request(workbench, f"/api/runs/{result['run_id']}")
    assert status == 200
    assert len(data["records"]) == 3
    assert {row["condition"] for row in data["records"]} == {
        "contiguous", "fragmented", "overwritten"
    }


def test_log_endpoint_supports_event_filters(workbench: str) -> None:
    request(workbench, "/api/dataset/initialize", "POST")
    status, all_events, _ = request(workbench, "/api/log")
    assert status == 200
    assert all_events["events"]

    status, filtered, _ = request(workbench, "/api/log?event=dataset.initialize")
    assert status == 200
    assert filtered["events"]
    assert all(row["event"] == "dataset.initialize" for row in filtered["events"])


def test_hex_preview_rejects_unregistered_fixture(workbench: str) -> None:
    status, payload, _ = request(workbench, "/api/fixtures/%2E%2E%2FREADME.md/hex")
    assert status == 404
    assert "error" in payload


def test_real_evidence_import_scan_and_candidate_download(workbench: str) -> None:
    original = b"header" + b"\xff\xd8\xff\xe0photo-data\xff\xd9" + b"tail"
    status, source, _ = request(
        workbench,
        "/api/evidence/import",
        "POST",
        body=original,
        headers={
            "Content-Type": "application/octet-stream",
            "X-TraceByte-Filename": "camera%20copy.bin",
        },
    )
    assert status == 201
    assert source["original_name"] == "camera copy.bin"
    assert source["sha256"] == hashlib.sha256(original).hexdigest()

    status, scan, _ = request(
        workbench,
        "/api/evidence/scans",
        "POST",
        body=json.dumps({"source_id": source["source_id"], "candidate_max_size_mb": 8}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 201
    assert scan["candidate_count"] == 1
    assert scan["candidates"][0]["signature"] == "JPEG"
    assert "source_path" not in scan["candidates"][0]
    assert "output_path" not in scan["candidates"][0]

    candidate_name = scan["candidates"][0]["output_name"]
    status, carved, _ = request(
        workbench,
        f"/api/evidence/scans/{scan['scan_id']}/files/{candidate_name}",
    )
    assert status == 200
    assert carved == b"\xff\xd8\xff\xe0photo-data\xff\xd9"

    status, report, content_type = request(
        workbench,
        f"/api/evidence/scans/{scan['scan_id']}/report",
    )
    assert status == 200
    assert "application/octet-stream" in content_type
    report_data = json.loads(report)
    assert report_data["source"]["sha256"] == source["sha256"]
    assert report_data["candidate_count"] == 1


def test_real_evidence_png_import_finds_and_downloads_candidate(workbench: str) -> None:
    png = bytes.fromhex("89504E470D0A1A0A") + b"\x00\x00\x00\x00IEND" + bytes.fromhex("AE426082")
    status, source, _ = request(
        workbench,
        "/api/evidence/import",
        "POST",
        body=png,
        headers={
            "Content-Type": "application/octet-stream",
            "X-TraceByte-Filename": "screen.png",
        },
    )
    assert status == 201

    status, scan, _ = request(
        workbench,
        "/api/evidence/scans",
        "POST",
        body=json.dumps({"source_id": source["source_id"], "candidate_max_size_mb": 8}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 201
    assert scan["candidate_count"] == 1
    assert scan["candidates"][0]["signature"] == "PNG"

    candidate_name = scan["candidates"][0]["output_name"]
    status, carved, _ = request(
        workbench,
        f"/api/evidence/scans/{scan['scan_id']}/files/{candidate_name}",
    )
    assert status == 200
    assert carved == png
