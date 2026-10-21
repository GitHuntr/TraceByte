"""Tests for import-time package resolution and public API exposure.

These tests ensure that the ``src`` and ``app`` packages resolve to the
project's own code (not stray modules) and that critical public names are
importable.
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


def test_app_package_resolves_to_project() -> None:
    """``import app`` must resolve to the project's ``app`` package and
    expose the ``branding`` submodule.
    """
    import app

    assert hasattr(app, "__all__")
    assert "branding" in app.__all__


def test_sha256_file_is_importable() -> None:
    """``from src.hashing import sha256_file`` must succeed and return a
    callable.
    """
    from src.hashing import sha256_file

    assert callable(sha256_file)


def test_app_name_is_filecarvelab() -> None:
    """``from app.branding import APP_NAME`` must succeed and return the
    canonical product name.
    """
    from app.branding import APP_NAME

    assert APP_NAME == "FileCarveLab"
