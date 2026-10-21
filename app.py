"""Streamlit entry point for the FileCarveLab dashboard.

Run from the project root with:

    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.branding import APP_ICON, PAGE_TITLE, footer, sidebar_brand
from src.paths import ensure_project_directories

ensure_project_directories()

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Build the navigation and run the selected page."""
    sidebar_brand()

    page = st.navigation(
        {
            "": [
                st.Page(
                    "app/views/home.py",
                    title="Overview",
                    icon=":material/dashboard:",
                    default=True,
                )
            ],
            "Evidence": [
                st.Page(
                    "app/views/dataset.py",
                    title="Dataset",
                    icon=":material/folder_open:",
                ),
                st.Page(
                    "app/views/integrity.py",
                    title="Integrity",
                    icon=":material/fact_check:",
                ),
            ],
            "Carving": [
                st.Page(
                    "app/views/carve.py",
                    title="Carve",
                    icon=":material/content_cut:",
                ),
                st.Page(
                    "app/views/results.py",
                    title="Results",
                    icon=":material/query_stats:",
                ),
            ],
            "Provenance": [
                st.Page(
                    "app/views/log.py",
                    title="Experiment log",
                    icon=":material/description:",
                )
            ],
        },
        position="sidebar",
    )

    st.title(f"{page.icon} {page.title}")
    page.run()
    footer()


main()
