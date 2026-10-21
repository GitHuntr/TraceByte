"""Tests for the chunked SHA-256 hashing utility."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.hashing import (
    DEFAULT_CHUNK_SIZE,
    human_size,
    is_sha256,
    sha256_bytes,
    sha256_file,
    sha256_text,
    shorten,
)

SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
SHA256_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_of_known_vector(tmp_path: Path) -> None:
    target = tmp_path / "abc.bin"
    target.write_bytes(b"abc")
    assert sha256_file(target) == SHA256_ABC


def test_sha256_of_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    assert sha256_file(target) == SHA256_EMPTY


def test_chunked_read_matches_single_shot_hash(tmp_path: Path) -> None:
    """The digest must not depend on the chunk size used to read the file."""
    payload = bytes(range(256)) * 4096  # 1 MiB of non-uniform data
    target = tmp_path / "large.bin"
    target.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_file(target, chunk_size=1) == expected
    assert sha256_file(target, chunk_size=1024) == expected
    assert sha256_file(target, chunk_size=DEFAULT_CHUNK_SIZE) == expected


def test_hash_is_stable_across_repeated_calls(tmp_path: Path) -> None:
    target = tmp_path / "stable.bin"
    target.write_bytes(b"tracebyte" * 1000)
    digests = {sha256_file(target, chunk_size=7) for _ in range(5)}
    assert len(digests) == 1


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "does_not_exist.bin")


def test_invalid_chunk_size_raises_value_error(tmp_path: Path) -> None:
    target = tmp_path / "x.bin"
    target.write_bytes(b"x")
    with pytest.raises(ValueError):
        sha256_file(target, chunk_size=0)
    with pytest.raises(ValueError):
        sha256_file(target, chunk_size=-1)


def test_bytes_and_text_helpers() -> None:
    assert sha256_bytes(b"abc") == SHA256_ABC
    assert sha256_text("abc") == SHA256_ABC
    assert sha256_bytes(b"") == SHA256_EMPTY


def test_is_sha256_and_shorten() -> None:
    assert is_sha256(SHA256_ABC)
    assert is_sha256(SHA256_ABC.upper())
    assert not is_sha256("abc")
    assert not is_sha256("z" * 64)
    assert not is_sha256(SHA256_ABC + "0")
    assert shorten(SHA256_ABC, 8) == SHA256_ABC[:8]
    with pytest.raises(ValueError):
        shorten(SHA256_ABC, 2)


def test_human_size() -> None:
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KiB"
    assert human_size(5 * 1024 * 1024) == "5.0 MiB"
