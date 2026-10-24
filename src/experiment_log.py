"""Append-only experiment log (JSON Lines).

Every mutating action performed by FileCarveLab is recorded here so that a
third party can reconstruct what happened, when it happened, with which tool
versions and with which parameters.

The log is *append only*: existing records are never rewritten or removed.
"""

from __future__ import annotations

import json
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

LOG_FILE_NAME = "experiment_log.jsonl"


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string ending in ``Z``."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def tool_versions() -> dict[str, str]:
    """Return versions of the tools that can influence recorded results."""
    versions: dict[str, str] = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }
    for module_name in ("pytest",):
        try:
            from importlib.metadata import version

            versions[module_name] = version(module_name)
        except Exception:  # pragma: no cover - defensive, package may be absent
            versions[module_name] = "not-installed"
    versions["filecarvelab"] = "0.1.0"
    return versions


class ExperimentLog:
    """Thin writer around a JSON Lines log file."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        enabled: bool = True,
        run_id: str | None = None,
    ) -> None:
        # The path is resolved when the log is created, not when this module
        # is imported, so that a caller can redirect the canonical location
        # (tests, sandboxes) and still be honoured.
        self.path = Path(path) if path is not None else paths.EXPERIMENT_LOG_PATH
        self.enabled = enabled
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._versions = tool_versions()

    # -- writing ---------------------------------------------------------
    def append(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "filecarvelab.stage1",
    ) -> dict[str, Any]:
        """Append one event record and return the written record."""
        record: dict[str, Any] = {
            "timestamp_utc": utc_now_iso(),
            "run_id": self.run_id,
            "event": event,
            "actor": actor,
            "tool_versions": self._versions,
            "payload": payload or {},
        }
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # One JSON object per line: this is the JSON Lines convention and it
            # keeps the file append-friendly and machine-readable.
            with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    # -- reading ---------------------------------------------------------
    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return the recorded events, oldest first.

        Malformed lines are skipped instead of raising, so a truncated write
        cannot hide the rest of the log.
        """
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit is not None:
            events = events[-limit:]
        return events

    def event_count(self) -> int:
        """Return the number of recorded events."""
        return len(self.read_events())


def default_log() -> ExperimentLog:
    """Return an experiment log bound to the canonical project location."""
    return ExperimentLog()


if __name__ == "__main__":  # pragma: no cover - manual smoke test helper
    log = default_log()
    log.append("smoke_test", {"argv": sys.argv[1:]})
    print(f"Log file: {log.path}")
