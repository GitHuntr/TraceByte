"""TraceByte / FileCarveLab core library.

Stage 1 scope only:
    * deterministic synthetic fixture generation
    * chunked SHA-256 hashing
    * immutable baseline manifest handling
    * evidence integrity verification
    * append-only experiment log

The carving engine, recovery algorithms, precision/recall metrics and the
final report are deliberately NOT implemented yet (see README roadmap).
"""

from __future__ import annotations

__all__ = [
    "experiment_log",
    "fixtures",
    "hashing",
    "integrity",
    "manifest",
    "paths",
]

__version__ = "0.1.0"
__stage__ = "Stage 1 - Foundation & Evidence Integrity"
