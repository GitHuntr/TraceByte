"""Tests for the append-only experiment log."""

from __future__ import annotations

import json
from pathlib import Path

from src.experiment_log import ExperimentLog, tool_versions, utc_now_iso
from src.fixtures import initialize_dataset

from .conftest import Workspace


def test_append_creates_jsonl_records(workspace: Workspace) -> None:
    log = ExperimentLog(workspace.log_path)
    log.append("unit_test", {"value": 1})

    lines = workspace.log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "unit_test"
    assert record["payload"] == {"value": 1}
    assert record["timestamp_utc"].endswith("Z")
    assert record["run_id"]
    assert record["tool_versions"]["python"]


def test_log_is_append_only(workspace: Workspace) -> None:
    log = ExperimentLog(workspace.log_path)
    log.append("first", {"n": 1})
    original = workspace.log_path.read_text(encoding="utf-8")

    log.append("second", {"n": 2})
    updated = workspace.log_path.read_text(encoding="utf-8")

    assert updated.startswith(original)
    assert len(ExperimentLog(workspace.log_path, enabled=False).read_events()) == 2


def test_read_events_skips_malformed_lines(workspace: Workspace) -> None:
    log = ExperimentLog(workspace.log_path)
    log.append("good", {"n": 1})
    with open(workspace.log_path, "a", encoding="utf-8") as handle:
        handle.write("{truncated\n")

    events = ExperimentLog(workspace.log_path, enabled=False).read_events()
    assert len(events) == 1
    assert events[0]["event"] == "good"


def test_initialisation_is_recorded_in_the_log(workspace: Workspace) -> None:
    log = ExperimentLog(workspace.log_path)
    initialize_dataset(
        originals_dir=workspace.originals_dir,
        manifest_path=workspace.manifest_path,
        log=log,
    )

    events = log.read_events()
    assert len(events) == 1
    payload = events[0]["payload"]
    assert events[0]["event"] == "dataset.initialize"
    assert payload["created"] == len(payload["fixtures"])
    assert all("baseline_sha256" in item for item in payload["fixtures"])


def test_tool_versions_and_timestamp_helpers() -> None:
    versions = tool_versions()
    assert versions["python"]
    assert "filecarvelab" in versions
    assert utc_now_iso().endswith("Z")
