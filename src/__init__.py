"""TraceByte / FileCarveLab core library.

Stage 1 (foundation):
    * deterministic synthetic fixture generation
    * chunked SHA-256 hashing
    * immutable baseline manifest handling
    * evidence integrity verification
    * append-only experiment log

Stage 2 (carving engine and measurement):
    * file signature registry and scanner
    * three controlled storage conditions (contiguous, fragmented, overwritten)
    * signature carving engine with full provenance
    * detection / recovery / validation metrics
    * experiment runner (build → carve → measure → log)
"""

from __future__ import annotations

__all__ = [
    "carver",
    "conditions",
    "experiment_log",
    "experiments",
    "fixtures",
    "hashing",
    "integrity",
    "manifest",
    "metrics",
    "paths",
    "signatures",
]

__version__ = "0.1.0"
__stage__ = "Stage 2 - Signature Carving Engine & Measurement"
