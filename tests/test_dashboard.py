"""Smoke tests for the FileCarveLab dashboard.

These tests drive the real Streamlit application through
``streamlit.testing.v1.AppTest`` (no browser, no server required). All file
system access is redirected to a temporary directory, so the real evidence set
in ``data/originals`` is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

import src.paths as paths


@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the application to a temporary evidence workspace."""
    originals = tmp_path / "originals"
    logs = tmp_path / "logs"
    originals.mkdir()
    logs.mkdir()
    monkeypatch.setattr(paths, "ORIGINALS_DIR", originals)
    monkeypatch.setattr(paths, "MANIFEST_PATH", originals / "manifest.json")
    monkeypatch.setattr(paths, "EXPERIMENT_LOG_PATH", logs / "experiment_log.jsonl")
    return originals


def _app() -> AppTest:
    return AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60)


def _button(app: AppTest, label: str):
    matches = [button for button in app.button if button.label == label]
    assert matches, f"button '{label}' not found on the page"
    return matches[0]


def test_dashboard_launches_without_error(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    assert not app.exception
    assert app.title


def test_dataset_page_creates_the_manifest(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/dataset.py")
    app.run()
    assert not app.exception

    _button(app, "Initialise dataset").click().run()

    assert not app.exception
    manifest_path = isolated_paths / "manifest.json"
    assert manifest_path.exists()
    assert (isolated_paths / "synthetic_photo_01.jpg").exists()


def test_integrity_page_reports_matching_hashes(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/dataset.py")
    app.run()
    _button(app, "Initialise dataset").click().run()

    app.switch_page("app/views/integrity.py")
    app.run()
    assert not app.exception
    assert any("match their baseline" in message.value for message in app.success)


def test_integrity_page_detects_a_modified_copy(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/dataset.py")
    app.run()
    _button(app, "Initialise dataset").click().run()

    # Tamper with one original after the baseline was recorded.
    victim = isolated_paths / "synthetic_photo_01.jpg"
    data = bytearray(victim.read_bytes())
    data[0] = 0x00
    victim.write_bytes(bytes(data))

    app.switch_page("app/views/integrity.py")
    app.run()
    assert not app.exception
    assert any("content changed" in message.value for message in app.error)


def test_overview_page_renders_metrics(isolated_paths: Path) -> None:
    """The Overview page (home.py) must render without exception and
    produce metric widgets and markdown content.
    """
    app = _app()
    app.run()
    app.switch_page("app/views/home.py")
    app.run()
    assert not app.exception
    assert len(app.metric) > 0
    assert len(app.markdown) > 0


def test_experiment_log_page_renders(isolated_paths: Path) -> None:
    """The Experiment log page (log.py) must render without exception."""
    app = _app()
    app.run()
    app.switch_page("app/views/log.py")
    app.run()
    assert not app.exception


def test_carve_page_renders_and_lists_the_signatures(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/carve.py")
    app.run()
    assert not app.exception
    assert any("Supported signatures" in block.value for block in app.markdown)


def test_carve_page_runs_the_experiments(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/dataset.py")
    app.run()
    _button(app, "Initialise dataset").click().run()

    app.switch_page("app/views/carve.py")
    app.run()
    _button(app, "Run carving experiments").click().run()
    assert not app.exception
    assert any("Ran 3 experiments" in message.value for message in app.success)


def test_results_page_reports_the_measurements(isolated_paths: Path) -> None:
    app = _app()
    app.run()
    app.switch_page("app/views/dataset.py")
    app.run()
    _button(app, "Initialise dataset").click().run()

    app.switch_page("app/views/carve.py")
    app.run()
    _button(app, "Run carving experiments").click().run()

    app.switch_page("app/views/results.py")
    app.run()
    assert not app.exception
    assert len(app.metric) > 0
    assert any("contiguous" in block.value for block in app.subheader)

