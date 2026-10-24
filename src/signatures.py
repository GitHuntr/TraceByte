"""File signature registry and scanner.

Stage 2 component A.

The scanner answers exactly one question: *where does a known file signature
occur in this byte stream?* A signature hit is a **detection**, never a
recovered file. Recovery is a separate claim that is established later by
comparing the carved bytes with the ground truth.

Scanning is performed in chunks with an overlap of ``len(magic) - 1`` bytes so
that a signature straddling a chunk boundary is still found.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .hashing import DEFAULT_CHUNK_SIZE

#: Signature names supported by the engine.
JPEG = "JPEG"
PNG = "PNG"
GIF = "GIF"
PDF = "PDF"
ZIP = "ZIP"

#: Default maximum number of bytes a single carved candidate may span.
DEFAULT_MAX_CANDIDATE_SIZE = 8 * 1024 * 1024


class SignatureError(RuntimeError):
    """Raised for invalid input handed to the scanner."""


@dataclass(frozen=True)
class SignatureSpec:
    """Definition of one supported file signature."""

    name: str
    magic: bytes
    extension: str
    end_marker: bytes | None
    description: str
    validation_strategy: str

    @property
    def magic_hex(self) -> str:
        return self.magic.hex()


@dataclass(frozen=True)
class Detection:
    """A single signature hit inside a byte stream.

    This is a *detection* record. It carries no claim that the surrounding
    bytes form a valid file.
    """

    signature: str
    offset: int
    magic_hex: str
    extension: str
    description: str
    validation_strategy: str
    source: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "signature": self.signature,
            "offset": self.offset,
            "magic_hex": self.magic_hex,
            "extension": self.extension,
            "description": self.description,
            "validation_strategy": self.validation_strategy,
            "source": self.source,
        }


@dataclass(frozen=True)
class Extent:
    """The byte range a candidate is considered to span."""

    start: int
    end: int
    policy: str
    structurally_delimited: bool

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


def default_registry() -> "SignatureRegistry":
    """Return the registry with the formats supported by this project."""
    return SignatureRegistry(
        [
            SignatureSpec(
                name=PNG,
                magic=bytes.fromhex("89504E470D0A1A0A"),
                extension=".png",
                end_marker=bytes.fromhex("0000000049454E44AE426082"),
                description="PNG file signature (89 50 4E 47 0D 0A 1A 0A).",
                validation_strategy=(
                    "Candidate ends at the PNG IEND chunk marker. Validate the PNG "
                    "chunk structure and CRCs with a format parser; byte-exact "
                    "recovery requires comparison with a known original."
                ),
            ),
            SignatureSpec(
                name=GIF,
                magic=b"GIF8",
                extension=".gif",
                end_marker=b";",
                description="GIF87a or GIF89a file signature (GIF8).",
                validation_strategy=(
                    "Candidate ends at the GIF trailer byte. Validate the complete "
                    "GIF structure with a format parser; byte-exact recovery "
                    "requires comparison with a known original."
                ),
            ),
            SignatureSpec(
                name=JPEG,
                magic=b"\xff\xd8\xff",
                extension=".jpg",
                end_marker=b"\xff\xd9",
                description="JPEG start-of-image marker (FF D8 FF).",
                validation_strategy=(
                    "Candidate must be delimited by the JPEG end-of-image marker "
                    "(FF D9) and the carved bytes must match a ground-truth "
                    "original byte for byte."
                ),
            ),
            SignatureSpec(
                name=PDF,
                magic=b"%PDF-",
                extension=".pdf",
                end_marker=b"%%EOF",
                description="PDF document header (%PDF-).",
                validation_strategy=(
                    "Candidate must be delimited by the %%EOF trailer and the "
                    "carved bytes must match a ground-truth original byte for byte."
                ),
            ),
            SignatureSpec(
                name=ZIP,
                magic=b"PK\x03\x04",
                extension=".zip",
                end_marker=b"PK\x05\x06",
                description="ZIP local file header (PK 03 04).",
                validation_strategy=(
                    "Candidate must be delimited by the end-of-central-directory "
                    "record (PK 05 06) and the carved bytes must match a "
                    "ground-truth original byte for byte."
                ),
            ),
        ]
    )


class SignatureRegistry:
    """A registry of known file signatures and the scanner built on it."""

    def __init__(self, specs: Iterable[SignatureSpec]) -> None:
        self._specs: dict[str, SignatureSpec] = {}
        for spec in specs:
            if not spec.magic:
                raise SignatureError(f"Signature '{spec.name}' has an empty magic value.")
            if spec.name in self._specs:
                raise SignatureError(f"Duplicate signature name '{spec.name}'.")
            self._specs[spec.name] = spec

    # -- registry --------------------------------------------------------
    def names(self) -> list[str]:
        """Return the registered signature names, sorted."""
        return sorted(self._specs)

    def specs(self) -> list[SignatureSpec]:
        """Return the registered signature definitions, sorted by name."""
        return [self._specs[name] for name in self.names()]

    def get(self, name: str) -> SignatureSpec:
        """Return the definition of *name*."""
        try:
            return self._specs[name]
        except KeyError as exc:
            raise SignatureError(
                f"Unknown signature '{name}'. Known signatures: {self.names()}"
            ) from exc

    @property
    def max_magic_length(self) -> int:
        """Return the longest magic value, used to size the scan overlap."""
        return max(len(spec.magic) for spec in self._specs.values())

    # -- scanning --------------------------------------------------------
    def scan_bytes(self, data: bytes, source: str = "") -> list[Detection]:
        """Return every signature detection inside *data*, ordered by offset.

        Overlapping and repeated signatures are all reported; each occurrence
        is a separate detection.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise SignatureError("scan_bytes expects a bytes-like object.")
        detections: list[Detection] = []
        for spec in self._specs.values():
            detections.extend(self._scan_for(data, spec, source))
        detections.sort(key=lambda detection: (detection.offset, detection.signature))
        return detections

    def _scan_for(
        self, data: bytes, spec: SignatureSpec, source: str
    ) -> Iterator[Detection]:
        start = 0
        while True:
            index = data.find(spec.magic, start)
            if index < 0:
                return
            yield Detection(
                signature=spec.name,
                offset=index,
                magic_hex=spec.magic_hex,
                extension=spec.extension,
                description=spec.description,
                validation_strategy=spec.validation_strategy,
                source=source,
            )
            # +1 keeps overlapping occurrences visible.
            start = index + 1

    def scan_file(self, path: str | Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[Detection]:
        """Scan a file for signatures using chunked reads with overlap."""
        return self.scan_file_with_hash(path, chunk_size)[0]

    def scan_file_with_hash(
        self,
        path: str | Path,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        *,
        max_detections: int | None = None,
    ) -> tuple[list[Detection], str]:
        """Scan a file for signatures using chunked reads with overlap.

        Raises:
            FileNotFoundError: if the file does not exist.
            SignatureError: if *chunk_size* is not positive.
        """
        file_path = Path(path)
        if chunk_size <= 0:
            raise SignatureError("chunk_size must be a positive integer.")
        if max_detections is not None and max_detections <= 0:
            raise SignatureError("max_detections must be a positive integer.")
        if not file_path.exists():
            raise FileNotFoundError(f"No such file: {file_path}")

        overlap = max(0, self.max_magic_length - 1)
        detections: list[Detection] = []
        seen: set[tuple[str, int]] = set()
        digest = hashlib.sha256()
        buffer = b""
        absolute = 0

        with open(file_path, "rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                window = buffer + chunk
                window_start = absolute - len(buffer)
                for detection in self.scan_bytes(window, source=str(file_path)):
                    absolute_offset = window_start + detection.offset
                    key = (detection.signature, absolute_offset)
                    if key in seen:
                        continue
                    if max_detections is not None and len(detections) >= max_detections:
                        raise SignatureError(
                            f"The scan found more than {max_detections:,} signature matches; "
                            "use a smaller evidence file for this scan."
                        )
                    seen.add(key)
                    detections.append(
                        Detection(
                            signature=detection.signature,
                            offset=absolute_offset,
                            magic_hex=detection.magic_hex,
                            extension=detection.extension,
                            description=detection.description,
                            validation_strategy=detection.validation_strategy,
                            source=str(file_path),
                        )
                    )
                absolute += len(chunk)
                buffer = window[-overlap:] if overlap else b""

        detections.sort(key=lambda detection: (detection.offset, detection.signature))
        return detections, digest.hexdigest()

    # -- extent ----------------------------------------------------------
    def find_extent(
        self,
        data: bytes,
        detection: Detection,
        *,
        max_size: int = DEFAULT_MAX_CANDIDATE_SIZE,
        next_detection_offset: int | None = None,
    ) -> Extent:
        """Determine the byte range a candidate spans.

        Policies, in order of preference:

        1. ``end_marker`` - the format's own terminator was found. The extent
           is structurally delimited, which is what makes a byte-exact
           recovery possible.
        2. ``next_signature`` - the next signature in the stream. The extent is
           *not* structurally delimited, so the candidate is truncated.
        3. ``eof`` - the end of the stream was reached without any delimiter.

        In every case the candidate is capped at *max_size* bytes.
        """
        spec = self.get(detection.signature)
        start = detection.offset
        limit = min(len(data), start + max_size)

        if spec.end_marker:
            marker_index = data.find(spec.end_marker, start + len(spec.magic))
            if marker_index >= 0 and marker_index + len(spec.end_marker) <= limit:
                return Extent(
                    start=start,
                    end=marker_index + len(spec.end_marker),
                    policy="end_marker",
                    structurally_delimited=True,
                )

        if next_detection_offset is not None and next_detection_offset > start:
            end = min(next_detection_offset, limit)
            return Extent(
                start=start,
                end=end,
                policy="next_signature",
                structurally_delimited=False,
            )

        return Extent(
            start=start,
            end=limit,
            policy="eof",
            structurally_delimited=False,
        )


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 digest of *data* (convenience wrapper)."""
    return hashlib.sha256(data).hexdigest()
