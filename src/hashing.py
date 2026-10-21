"""SHA-256 helpers used for evidence-integrity verification.

All hashing is done on file content in fixed-size chunks so that arbitrarily
large files can be hashed with constant memory usage.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

#: Default chunk size for streaming reads (1 MiB).
DEFAULT_CHUNK_SIZE: int = 1024 * 1024


def sha256_file(path: str | Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Return the lowercase hex SHA-256 digest of a file.

    The file is read in chunks of *chunk_size* bytes; the digest is identical
    to hashing the whole file in memory.

    Raises:
        FileNotFoundError: if *path* does not exist.
        IsADirectoryError: if *path* is a directory.
        ValueError: if *chunk_size* is not a positive integer.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in _iter_chunks(handle, chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_chunks(handle: BinaryIO, chunk_size: int):
    """Yield successive *chunk_size* byte blocks until the stream is exhausted."""
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            return
        yield chunk


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of an in-memory byte string."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the lowercase hex SHA-256 digest of a UTF-8 encoded string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_sha256(value: str) -> bool:
    """Return ``True`` when *value* looks like a 64-character hex digest."""
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def shorten(digest: str, length: int = 12) -> str:
    """Return a shortened digest for display purposes only.

    Shortened digests are for human eyes; never use them for verification.
    """
    if length < 4:
        raise ValueError("length must be at least 4 characters")
    return digest[:length]


def human_size(num_bytes: int) -> str:
    """Return a human readable representation of a byte count."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"
