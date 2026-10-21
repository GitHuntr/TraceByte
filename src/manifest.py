"""Baseline manifest for the ground-truth fixture set.

Design rules enforced by this module
-------------------------------------
* A baseline SHA-256 is written **once**. ``Manifest.record_baseline`` never
  replaces an existing entry, so re-running dataset initialisation can not
  silently re-baseline an original.
* The manifest is the *evidence record* of the ground truth. It records file
  size, digest, timestamps, tool versions and the fixture description.
* Changing a baseline requires the explicit :func:`rebaseline_entry` helper,
  which demands a written reason and produces an experiment-log event.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .experiment_log import utc_now_iso
from .paths import MANIFEST_PATH

MANIFEST_VERSION = "1.0"
PROJECT_NAME = "TraceByte"
PRODUCT_NAME = "FileCarveLab"

#: Recognised values for ``FixtureEntry.baseline_origin``.
BASELINE_ORIGIN_GENERATED = "generated"
BASELINE_ORIGIN_ADOPTED = "adopted-existing-unregistered"
BASELINE_ORIGIN_REBASELINED = "rebaselined-by-operator"


@dataclass
class FixtureEntry:
    """Baseline record for a single ground-truth fixture."""

    fixture_id: str
    filename: str
    relative_path: str
    size_bytes: int
    sha256: str
    description: str
    signature_hex: str = ""
    signature_offset: int | None = 0
    synthetic: bool = True
    fully_parseable: bool = False
    created_utc: str = ""
    baseline_origin: str = BASELINE_ORIGIN_GENERATED
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FixtureEntry":
        known = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class Manifest:
    """In-memory representation of ``data/originals/manifest.json``."""

    manifest_version: str = MANIFEST_VERSION
    project: str = f"{PROJECT_NAME} / {PRODUCT_NAME}"
    dataset_name: str = "FileCarveLab synthetic ground-truth set"
    dataset_description: str = (
        "Synthetic, deterministic fixtures used to evaluate file-signature "
        "carving accuracy under contiguous, fragmented and partially "
        "overwritten conditions. No real-world data is used."
    )
    created_utc: str = ""
    updated_utc: str = ""
    tool_versions: dict[str, str] = field(default_factory=dict)
    experiment_parameters: dict[str, Any] = field(default_factory=dict)
    entries: dict[str, FixtureEntry] = field(default_factory=dict)

    # -- queries ---------------------------------------------------------
    def baseline_sha256(self, filename: str) -> str | None:
        """Return the recorded baseline digest for *filename* (or ``None``)."""
        entry = self.entries.get(filename)
        return entry.sha256 if entry else None

    def get(self, filename: str) -> FixtureEntry | None:
        """Return the baseline entry for *filename* (or ``None``)."""
        return self.entries.get(filename)

    def filenames(self) -> list[str]:
        """Return the recorded fixture filenames, sorted."""
        return sorted(self.entries)

    # -- mutation --------------------------------------------------------
    def record_baseline(self, entry: FixtureEntry) -> tuple[str, FixtureEntry]:
        """Record a baseline, never replacing an existing one.

        Returns:
            ``(action, entry)`` where *action* is ``"created"`` when the entry
            was added and ``"preserved"`` when an existing baseline was kept
            untouched.
        """
        existing = self.entries.get(entry.filename)
        if existing is not None:
            return "preserved", existing
        self.entries[entry.filename] = entry
        return "created", entry

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "project": self.project,
            "dataset_name": self.dataset_name,
            "dataset_description": self.dataset_description,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
            "tool_versions": self.tool_versions,
            "experiment_parameters": self.experiment_parameters,
            "fixtures": [self.entries[name].to_dict() for name in self.filenames()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        fixtures = data.get("fixtures") or []
        entries: dict[str, FixtureEntry] = {}
        for raw in fixtures:
            entry = FixtureEntry.from_dict(raw)
            entries[entry.filename] = entry
        return cls(
            manifest_version=data.get("manifest_version", MANIFEST_VERSION),
            project=data.get("project", f"{PROJECT_NAME} / {PRODUCT_NAME}"),
            dataset_name=data.get("dataset_name", ""),
            dataset_description=data.get("dataset_description", ""),
            created_utc=data.get("created_utc", ""),
            updated_utc=data.get("updated_utc", ""),
            tool_versions=data.get("tool_versions", {}) or {},
            experiment_parameters=data.get("experiment_parameters", {}) or {},
            entries=entries,
        )


def load_manifest(path: str | Path = MANIFEST_PATH) -> Manifest:
    """Load the manifest from disk.

    A missing manifest yields an empty manifest (and does not raise); a
    corrupted manifest raises ``ValueError`` so that the operator is never
    silently handed an empty baseline.
    """
    manifest_path = Path(path)
    if not manifest_path.exists():
        return Manifest(created_utc=utc_now_iso(), updated_utc=utc_now_iso())
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Manifest at {manifest_path} is not valid JSON: {exc}. "
            "Restore it from version control; do not regenerate baselines."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"Manifest at {manifest_path} does not contain a JSON object.")
    return Manifest.from_dict(data)


def save_manifest(manifest: Manifest, path: str | Path = MANIFEST_PATH) -> Path:
    """Write the manifest to disk atomically.

    The file is written to a temporary file in the same directory and then
    moved into place, so an interrupted write cannot corrupt the baseline.
    """
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=False) + "\n"

    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=manifest_path.parent,
        prefix=".manifest-",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, manifest_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return manifest_path


def rebaseline_entry(
    manifest: Manifest,
    filename: str,
    new_sha256: str,
    *,
    reason: str,
    log: Any | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
) -> FixtureEntry:
    """Deliberately replace a baseline digest.

    This is the *only* code path that may change a recorded baseline hash. It
    requires an explicit reason, is written to the experiment log and is
    recorded on the entry itself. It is intentionally not exposed in the
    dashboard UI for Stage 1.
    """
    entry = manifest.entries.get(filename)
    if entry is None:
        raise KeyError(f"'{filename}' is not present in the manifest.")
    if not reason or not reason.strip():
        raise ValueError("A written reason is required to re-baseline an entry.")

    previous = entry.sha256
    entry.sha256 = new_sha256
    entry.baseline_origin = BASELINE_ORIGIN_REBASELINED
    entry.notes = (
        f"Baseline changed from {previous} to {new_sha256} on {utc_now_iso()}. "
        f"Reason: {reason.strip()}"
    )
    manifest.updated_utc = utc_now_iso()
    save_manifest(manifest, manifest_path)
    if log is not None:
        log.append(
            "manifest.rebaseline",
            {
                "filename": filename,
                "previous_sha256": previous,
                "new_sha256": new_sha256,
                "reason": reason.strip(),
            },
        )
    return entry


def manifest_summary(manifest: Manifest) -> dict[str, Any]:
    """Return a small summary dict for display in the dashboard."""
    entries = list(manifest.entries.values())
    return {
        "manifest_version": manifest.manifest_version,
        "project": manifest.project,
        "dataset_name": manifest.dataset_name,
        "created_utc": manifest.created_utc,
        "updated_utc": manifest.updated_utc,
        "fixture_count": len(entries),
        "total_bytes": sum(entry.size_bytes for entry in entries),
        "tool_versions": manifest.tool_versions,
    }


def iter_entries(manifest: Manifest) -> Iterable[FixtureEntry]:
    """Iterate over the manifest entries in filename order."""
    for name in manifest.filenames():
        yield manifest.entries[name]
