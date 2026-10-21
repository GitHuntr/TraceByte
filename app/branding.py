"""Product branding and shared UI copy for FileCarveLab.

The repository is named **TraceByte**; the research dashboard built on top of
it is branded **FileCarveLab** (Digital Forensics PBL, ref. DF-PBL-016).
"""

from __future__ import annotations

import streamlit as st

import src.paths as paths
from src.experiment_log import ExperimentLog
from src.experiments import list_runs

APP_NAME = "FileCarveLab"
APP_ICON = ":material/fingerprint:"
PROJECT_NAME = "TraceByte"
PROJECT_REFERENCE = "Digital Forensics PBL | DF-PBL-016"
TAGLINE = "File signature carving evaluation"
STAGE_LABEL = "Stage 2 | Signature carving engine and measurement"
PAGE_TITLE = f"{APP_NAME} | {PROJECT_NAME}"

DISCLAIMER = (
    "All data handled by this dashboard is synthetic and generated locally. "
    "No real device, account or third-party data is involved, and no destructive "
    "disk operation is performed."
)


def sidebar_brand() -> None:
    """Render the FileCarveLab brand block in the sidebar."""
    st.markdown(f":material/fingerprint: **{APP_NAME}**")
    st.caption(TAGLINE)
    st.caption(f"{PROJECT_NAME} · {PROJECT_REFERENCE}")
    st.caption(STAGE_LABEL)


def _status_row(label: str, value: str) -> None:
    """Render one label/value row of the status card."""
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.caption(label)
        st.markdown(f"**{value}**")


def sidebar_status() -> None:
    """Render the read-only system status below the navigation.

    It answers the two questions an operator has before touching anything:
    *is the evidence set still intact* and *what has already been run*.
    """
    from app.state import get_integrity_results, get_manifest

    manifest = get_manifest(str(paths.MANIFEST_PATH))
    _results, summary = get_integrity_results(
        str(paths.MANIFEST_PATH), str(paths.ORIGINALS_DIR)
    )
    runs = list_runs(paths.EXPERIMENTS_DIR)
    events = ExperimentLog(paths.EXPERIMENT_LOG_PATH, enabled=False)

    with st.container(border=True):
        st.markdown("##### System status")
        if not manifest.entries:
            _status_row("Evidence set", "not initialised")
        else:
            total = sum(summary.get(key, 0) for key in ("MATCH", "MISMATCH", "MISSING"))
            intact = summary.get("MATCH", 0)
            _status_row("Fixtures", f"{intact}/{total} match")
        _status_row("Experiment runs", str(len(runs)))
        _status_row("Logged events", str(events.event_count()))
        st.caption(STAGE_LABEL)


def footer() -> None:
    """Render the standard footer with the data-handling disclaimer."""
    st.caption(DISCLAIMER)
