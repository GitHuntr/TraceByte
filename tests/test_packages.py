"""Tests for import-time package resolution and public API exposure.

These tests ensure that the forensic engine and local web entry point expose
the project's own code and critical public callables.
"""

from __future__ import annotations


def test_src_package_resolves_to_project() -> None:
    """``import src`` must resolve to the project's ``src`` package and
    expose the expected submodule names.
    """
    import src

    assert hasattr(src, "__version__")
    assert hasattr(src, "__all__")
    for name in ("hashing", "manifest", "fixtures", "integrity", "paths", "experiment_log"):
        assert name in src.__all__


def test_sha256_file_is_importable() -> None:
    """``from src.hashing import sha256_file`` must succeed and return a
    callable.
    """
    from src.hashing import sha256_file

    assert callable(sha256_file)


def test_workbench_entrypoint_is_importable() -> None:
    """The standard-library workbench server exposes its launcher."""
    from server import main

    assert callable(main)
