"""Product branding and shared UI copy for FileCarveLab.

The repository is named **TraceByte**; the research dashboard built on top of
it is branded **FileCarveLab** (Digital Forensics PBL, ref. DF-PBL-016).
"""

from __future__ import annotations

import streamlit as st

APP_NAME = "FileCarveLab"
APP_ICON = ":material/fingerprint:"
PROJECT_NAME = "TraceByte"
PROJECT_REFERENCE = "Digital Forensics PBL | DF-PBL-016"
TAGLINE = "File signature carving evaluation"
STAGE_LABEL = "Stage 1 | Foundation and evidence integrity"
PAGE_TITLE = f"{APP_NAME} | {PROJECT_NAME}"

DISCLAIMER = (
    "All data handled by this dashboard is synthetic and generated locally. "
    "No real device, account or third-party data is involved, and no destructive "
    "disk operation is performed."
)


def sidebar_brand() -> None:
    """Render the FileCarveLab brand block in the sidebar."""
    st.markdown(f"### {APP_NAME}")
    st.caption(TAGLINE)
    st.caption(f"{PROJECT_NAME} | {PROJECT_REFERENCE}")
    st.caption(STAGE_LABEL)
    st.divider()


def footer() -> None:
    """Render the standard footer with the data-handling disclaimer."""
    st.divider()
    st.caption(DISCLAIMER)
