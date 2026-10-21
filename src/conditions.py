"""Construction of the three controlled storage conditions.

Stage 2 component C.

An *image* is a controlled byte stream that emulates a disk area containing
the ground-truth originals plus surrounding filler. Three conditions are
supported:

``contiguous``
    Every original is stored in one continuous run of bytes.

``fragmented``
    Every original is split into several fragments that are scattered across
    the image, separated by filler.

``overwritten``
    Like ``contiguous``, but an internal byte range of every original has been
    replaced by filler, i.e. the data has been overwritten by later writes.

For every image the module records a **ground-truth map**: where each original
lives in the image, which bytes were overwritten and what the original hash
is. The map is the reference against which carving results are measured. It is
produced *before* carving and never by the carver.

Experimental control
--------------------
The filler between the originals is generated so that it contains **no**
registered signature and **no** end marker. Without that control the result
would depend on chance: a random 'FFD9' in the filler would silently truncate
every JPEG carve, and a random '%PDF-' would create an unreported false
positive. Instead, the number of false positives is *designed*: a fixed number
of decoy signatures is planted in the filler, and the image is verified
afterwards so that the only detections in it are the ground-truth signatures
and the planted decoys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fixtures import expand_seed, write_bytes_atomically
from .hashing import sha256_bytes
from .manifest import Manifest
from .paths import relative_to_project
from .signatures import SignatureRegistry, default_registry

CONDITION_CONTIGUOUS = "contiguous"
CONDITION_FRAGMENTED = "fragmented"
CONDITION_OVERWRITTEN = "overwritten"

CONDITIONS: tuple[str, ...] = (
    CONDITION_CONTIGUOUS,
    CONDITION_FRAGMENTED,
    CONDITION_OVERWRITTEN,
)

CONDITION_DESCRIPTIONS: dict[str, str] = {
    CONDITION_CONTIGUOUS: (
        "Every original is stored in one continuous run of bytes, separated from "
        "its neighbours by filler."
    ),
    CONDITION_FRAGMENTED: (
        "Every original is split into several fragments that are scattered across "
        "the image and separated by filler."
    ),
    CONDITION_OVERWRITTEN: (
        "Every original is stored contiguously, but an internal byte range has "
        "been replaced by filler, i.e. overwritten by later data."
    ),
}

DEFAULT_NOISE_GAP_MIN = 1024
DEFAULT_NOISE_GAP_MAX = 8192
DEFAULT_FRAGMENT_COUNT = 3
DEFAULT_OVERWRITE_FRACTION = 0.25
DEFAULT_OVERWRITE_START_FRACTION = 0.35
DEFAULT_PLANTED_FALSE_POSITIVES = 2
NOISE_NAMESPACE = "TraceByte/v1/noise"

#: Number of filler bytes appended to a planted decoy.
DECOY_TAIL_SIZE = 32


class ConditionError(RuntimeError):
    """Raised when an image cannot be built as requested."""


@dataclass(frozen=True)
class ByteRange:
    """A half-open byte range ``[start, end)``."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)

    def to_list(self) -> list[int]:
        return [self.start, self.end]


@dataclass
class GroundTruthFile:
    """Where one original lives inside an image."""

    file_id: str
    fixture_id: str
    signature: str | None
    ranges: list[ByteRange] = field(default_factory=list)
    total_bytes: int = 0
    expected_sha256: str = ""
    overwritten: bool = False
    overwritten_ranges: list[ByteRange] = field(default_factory=list)
    embedded_signatures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def start_offset(self) -> int:
        """Absolute offset of the first fragment inside the image."""
        return self.ranges[0].start if self.ranges else -1

    @property
    def end_offset(self) -> int:
        """Absolute offset just past the last fragment inside the image."""
        return self.ranges[-1].end if self.ranges else -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "fixture_id": self.fixture_id,
            "signature": self.signature,
            "ranges": [item.to_list() for item in self.ranges],
            "total_bytes": self.total_bytes,
            "expected_sha256": self.expected_sha256,
            "overwritten": self.overwritten,
            "overwritten_ranges": [item.to_list() for item in self.overwritten_ranges],
            "embedded_signatures": self.embedded_signatures,
        }


@dataclass
class BuiltImage:
    """A built image together with its ground-truth map."""

    experiment_id: str
    condition: str
    image_path: str
    image_sha256: str
    size_bytes: int
    parameters: dict[str, Any]
    ground_truth: list[GroundTruthFile]
    planted_false_positives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "condition": self.condition,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "size_bytes": self.size_bytes,
            "parameters": self.parameters,
            "ground_truth": [item.to_dict() for item in self.ground_truth],
            "planted_false_positives": self.planted_false_positives,
        }


def avoid_sequences(registry: SignatureRegistry | None = None) -> tuple[bytes, ...]:
    """Return every byte sequence the filler must not contain."""
    registry = registry or default_registry()
    sequences: list[bytes] = []
    for spec in registry.specs():
        sequences.append(spec.magic)
        if spec.end_marker:
            sequences.append(spec.end_marker)
    return tuple(sequences)


def _noise(seed: str, length: int, avoid: tuple[bytes, ...] = ()) -> bytes:
    """Return deterministic filler bytes that contain none of *avoid*."""
    counter = 0
    while True:
        data = expand_seed(f"{NOISE_NAMESPACE}/{seed}/{counter}", length)
        if not any(sequence and sequence in data for sequence in avoid):
            return data
        counter += 1


def _gap_length(seed: str, minimum: int, maximum: int) -> int:
    """Return a deterministic gap length between *minimum* and *maximum*."""
    span = max(0, maximum - minimum)
    raw = expand_seed(f"{NOISE_NAMESPACE}/{seed}/gap", 8)
    return minimum + (int.from_bytes(raw, "big") % (span + 1))


def _split_sizes(total: int, parts: int) -> list[int]:
    """Split *total* bytes into *parts* nearly equal chunks."""
    if parts <= 0:
        raise ConditionError("parts must be positive")
    base, remainder = divmod(total, parts)
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def _overwrite_window(total: int, fraction: float, start_fraction: float) -> tuple[int, int]:
    """Return the ``[start, end)`` range of the file that gets overwritten."""
    if total <= 0:
        return (0, 0)
    window = max(1, int(total * fraction))
    start = int(total * start_fraction)
    start = min(start, max(0, total - window))
    return (start, min(total, start + window))


def _signature_name_for(signature_hex: str) -> str | None:
    """Map a manifest signature hex value onto a registry signature name."""
    value = signature_hex.lower()
    if value.startswith("ffd8ff"):
        return "JPEG"
    if value.startswith("25504446"):  # "%PDF"
        return "PDF"
    if value.startswith("504b0304"):
        return "ZIP"
    return None


def _embedded_signatures(entry) -> list[dict[str, Any]]:
    """Return the signatures embedded inside an original, if the manifest knows them."""
    if entry.signature_hex.lower() != "ffd8ffe0" or not entry.signature_offset:
        return []
    if entry.signature_offset <= 0:
        return []
    return [
        {
            "signature": "JPEG",
            "relative_offset": entry.signature_offset,
            "note": "JPEG-like signature embedded inside a signature-free original.",
        }
    ]


def _start_signature(entry) -> str | None:
    """Return the signature at the very start of an original, if it has one.

    A signature that is recorded at a non-zero offset belongs to an embedded
    segment, not to the start of the file, so the file itself is a negative
    control for start-of-file detection.
    """
    if not entry.signature_hex:
        return None
    if entry.signature_offset is None or entry.signature_offset != 0:
        return None
    return _signature_name_for(entry.signature_hex)


def _decoy_schedule(file_count: int, decoys: int) -> dict[int, int]:
    """Return the number of decoys to plant after each file index."""
    schedule: dict[int, int] = {}
    if decoys <= 0 or file_count == 0:
        return schedule
    for index in range(file_count):
        before = (index * decoys) // file_count
        after = ((index + 1) * decoys) // file_count
        if after > before:
            schedule[index] = after - before
    return schedule


def build_image(
    condition: str,
    *,
    originals_dir: str | Path,
    manifest: Manifest,
    output_dir: str | Path,
    experiment_id: str,
    noise_gap_min: int = DEFAULT_NOISE_GAP_MIN,
    noise_gap_max: int = DEFAULT_NOISE_GAP_MAX,
    fragment_count: int = DEFAULT_FRAGMENT_COUNT,
    overwrite_fraction: float = DEFAULT_OVERWRITE_FRACTION,
    overwrite_start_fraction: float = DEFAULT_OVERWRITE_START_FRACTION,
    planted_false_positives: int = DEFAULT_PLANTED_FALSE_POSITIVES,
    registry: SignatureRegistry | None = None,
) -> BuiltImage:
    """Build one experimental image for *condition* and write it to disk.

    The originals are only ever read. The image is written to
    ``<output_dir>/<experiment_id>/image.bin`` and the ground-truth map to
    ``<output_dir>/<experiment_id>/ground_truth.json``.
    """
    if condition not in CONDITIONS:
        raise ConditionError(
            f"Unknown condition '{condition}'. Known conditions: {list(CONDITIONS)}"
        )

    registry = registry or default_registry()
    avoid = avoid_sequences(registry)
    specs = registry.specs()

    originals_dir = Path(originals_dir)
    output_dir = Path(output_dir)
    experiment_dir = output_dir / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=True)

    filenames = manifest.filenames()
    schedule = _decoy_schedule(len(filenames), planted_false_positives)

    parameters: dict[str, Any] = {
        "condition": condition,
        "noise_gap_min": noise_gap_min,
        "noise_gap_max": noise_gap_max,
        "fragment_count": fragment_count if condition == CONDITION_FRAGMENTED else None,
        "overwrite_fraction": (
            overwrite_fraction if condition == CONDITION_OVERWRITTEN else None
        ),
        "overwrite_start_fraction": (
            overwrite_start_fraction if condition == CONDITION_OVERWRITTEN else None
        ),
        "planted_false_positives": planted_false_positives,
        "filler_contains_signatures": False,
        "layout": CONDITION_DESCRIPTIONS[condition],
    }

    image = bytearray()
    ground_truth: list[GroundTruthFile] = []
    planted: list[dict[str, Any]] = []
    cursor = 0
    decoys_placed = 0

    for index, filename in enumerate(filenames):
        entry = manifest.entries[filename]
        source = originals_dir / filename
        if not source.exists():
            raise ConditionError(
                f"Original '{filename}' is missing from {originals_dir}; the image "
                "cannot be built from a complete ground truth."
            )
        original = source.read_bytes()

        gap_size = _gap_length(
            f"{condition}/{filename}", noise_gap_min, noise_gap_max
        )
        decoys_here = schedule.get(index, 0)
        head_noise = gap_size // 2
        tail_noise = gap_size - head_noise

        image.extend(_noise(f"{condition}/{filename}/pre", head_noise, avoid))
        cursor += head_noise

        for decoy_index in range(decoys_here):
            spec = specs[decoys_placed % len(specs)]
            decoy_bytes = spec.magic + _noise(
                f"{condition}/{filename}/decoy{decoy_index}",
                DECOY_TAIL_SIZE,
                avoid,
            )
            decoy_offset = cursor
            image.extend(decoy_bytes)
            cursor += len(decoy_bytes)
            planted.append(
                {
                    "offset": decoy_offset,
                    "signature": spec.name,
                    "length": len(decoy_bytes),
                    "note": "Deliberately planted signature-like data in the filler.",
                }
            )
            decoys_placed += 1

        image.extend(_noise(f"{condition}/{filename}/post", tail_noise, avoid))
        cursor += tail_noise

        if condition == CONDITION_FRAGMENTED:
            sizes = _split_sizes(len(original), fragment_count)
            ranges: list[ByteRange] = []
            relative = 0
            for part, size in enumerate(sizes):
                fragment_gap = _gap_length(
                    f"{condition}/{filename}/frag{part}", noise_gap_min, noise_gap_max
                )
                image.extend(
                    _noise(
                        f"{condition}/{filename}/frag{part}",
                        fragment_gap,
                        avoid,
                    )
                )
                cursor += fragment_gap

                chunk = original[relative : relative + size]
                image.extend(chunk)
                ranges.append(ByteRange(cursor, cursor + len(chunk)))
                cursor += len(chunk)
                relative += size
            truth = GroundTruthFile(
                file_id=filename,
                fixture_id=entry.fixture_id,
                signature=_start_signature(entry),
                ranges=ranges,
                total_bytes=len(original),
                expected_sha256=entry.sha256,
                overwritten=False,
                embedded_signatures=_embedded_signatures(entry),
            )
        else:
            payload = original
            overwritten_ranges: list[ByteRange] = []
            if condition == CONDITION_OVERWRITTEN:
                start, end = _overwrite_window(
                    len(original), overwrite_fraction, overwrite_start_fraction
                )
                if end > start:
                    replacement = _noise(
                        f"{condition}/{filename}/overwrite", end - start, avoid
                    )
                    payload = original[:start] + replacement + original[end:]
                    overwritten_ranges.append(ByteRange(cursor + start, cursor + end))
            image.extend(payload)
            ranges = [ByteRange(cursor, cursor + len(payload))]
            cursor += len(payload)
            truth = GroundTruthFile(
                file_id=filename,
                fixture_id=entry.fixture_id,
                signature=_start_signature(entry),
                ranges=ranges,
                total_bytes=len(original),
                expected_sha256=entry.sha256,
                overwritten=bool(overwritten_ranges),
                overwritten_ranges=overwritten_ranges,
                embedded_signatures=_embedded_signatures(entry),
            )

        ground_truth.append(truth)

    # A trailing gap keeps the last original from being recovered "by luck"
    # when the extent policy runs to the end of the stream.
    trailing = _gap_length(f"{condition}/trailing", noise_gap_min, noise_gap_max)
    image.extend(_noise(f"{condition}/trailing", trailing, avoid))
    cursor += trailing

    image_bytes = bytes(image)
    _verify_image(image_bytes, ground_truth, planted, registry)

    image_path = experiment_dir / "image.bin"
    write_bytes_atomically(image_path, image_bytes)

    truth_path = experiment_dir / "ground_truth.json"
    write_bytes_atomically(
        truth_path,
        json.dumps(
            {
                "experiment_id": experiment_id,
                "condition": condition,
                "image_path": relative_to_project(image_path),
                "image_sha256": sha256_bytes(image_bytes),
                "size_bytes": len(image_bytes),
                "parameters": parameters,
                "ground_truth": [item.to_dict() for item in ground_truth],
                "planted_false_positives": planted,
            },
            indent=2,
        ).encode("utf-8"),
    )

    return BuiltImage(
        experiment_id=experiment_id,
        condition=condition,
        image_path=relative_to_project(image_path),
        image_sha256=sha256_bytes(image_bytes),
        size_bytes=len(image_bytes),
        parameters=parameters,
        ground_truth=ground_truth,
        planted_false_positives=planted,
    )


def _verify_image(
    image: bytes,
    ground_truth: list[GroundTruthFile],
    planted: list[dict[str, Any]],
    registry: SignatureRegistry,
) -> None:
    """Check that the image contains only the expected signature hits.

    Every detection must be either a ground-truth signature or a deliberately
    planted decoy. Anything else means the image is not under experimental
    control and the measurement would be contaminated by chance.
    """
    expected: set[int] = set()
    for truth in ground_truth:
        if truth.signature and truth.ranges:
            expected.add(truth.start_offset)
        for embedded in truth.embedded_signatures:
            expected.add(truth.start_offset + int(embedded["relative_offset"]))
    for decoy in planted:
        expected.add(int(decoy["offset"]))

    detected = {detection.offset for detection in registry.scan_bytes(image)}
    unexpected = sorted(detected - expected)
    if unexpected:
        raise ConditionError(
            "The image contains signature hits that are neither a ground-truth "
            f"signature nor a planted decoy: {unexpected}. The experimental "
            "control is broken; the measurement would be contaminated."
        )


def load_ground_truth(path: str | Path) -> list[GroundTruthFile]:
    """Load a ground-truth map that was written by :func:`build_image`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    truth: list[GroundTruthFile] = []
    for raw in data.get("ground_truth", []):
        truth.append(
            GroundTruthFile(
                file_id=raw["file_id"],
                fixture_id=raw.get("fixture_id", ""),
                signature=raw.get("signature"),
                ranges=[ByteRange(item[0], item[1]) for item in raw.get("ranges", [])],
                total_bytes=raw.get("total_bytes", 0),
                expected_sha256=raw.get("expected_sha256", ""),
                overwritten=raw.get("overwritten", False),
                overwritten_ranges=[
                    ByteRange(item[0], item[1]) for item in raw.get("overwritten_ranges", [])
                ],
                embedded_signatures=raw.get("embedded_signatures", []),
            )
        )
    return truth
