"""Integrity page: verify the originals against the recorded SHA-256 baseline.

This page is strictly read-only. It never writes to `data/originals/` and
never updates a baseline hash.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

import src.paths as paths
from app.state import get_integrity_results, get_manifest
from app.ui import Kpi, empty_state, kpi_row, notice, page_header, section
from src.integrity import IntegrityStatus, detection_self_test

page_header(
    "Integrity",
    "Compares the SHA-256 of every original on disk with the baseline recorded "
    "in `data/originals/manifest.json`. Mismatches and missing files are "
    "reported; the baseline is never updated automatically.",
    icon="fact_check",
)

manifest = get_manifest(str(paths.MANIFEST_PATH))
results, summary = get_integrity_results(
    str(paths.MANIFEST_PATH), str(paths.ORIGINALS_DIR)
)

if not manifest.entries:
    empty_state(
        "folder_open",
        "No baseline manifest found",
        "Open **Dataset** and press *Initialise dataset* first - there is "
        "nothing to verify against yet.",
    )
    st.stop()

problems = [result for result in results if result.status is not IntegrityStatus.MATCH]

kpi_row(
    [
        Kpi("Match", summary.get("MATCH", 0), help="Originals identical to their recorded baseline"),
        Kpi("Mismatch", summary.get("MISMATCH", 0), help="Originals whose content changed"),
        Kpi("Missing", summary.get("MISSING", 0), help="Originals recorded but absent from disk"),
        Kpi("Unregistered", summary.get("UNREGISTERED", 0), help="Files on disk that the baseline does not know"),
    ]
)

with section("Verification result", icon="verified"):
    if not problems:
        notice(
            "All recorded originals match their baseline SHA-256. The evidence set "
            "is intact and the experiment can proceed.",
            kind="success",
        )
    else:
        notice(
            f"{len(problems)} integrity problem(s) detected. The baseline was **not** "
            "updated - investigate and restore from a trusted copy before running "
            "any experiment.",
            kind="error",
        )
        for result in problems:
            if result.status is IntegrityStatus.MISMATCH:
                notice(
                    f"**{result.filename} - content changed**\n\n"
                    f"- Baseline SHA-256: `{result.expected_sha256}`\n"
                    f"- Current SHA-256: `{result.actual_sha256}`\n"
                    f"- Baseline size: {result.expected_size} bytes | "
                    f"Current size: {result.actual_size} bytes\n\n"
                    f"{result.message}",
                    kind="error",
                )
            elif result.status is IntegrityStatus.MISSING:
                notice(
                    f"**{result.filename} - file missing**\n\n"
                    f"- Baseline SHA-256: `{result.expected_sha256}`\n"
                    f"- Expected path: `{result.path}`\n\n"
                    f"{result.message}",
                    kind="error",
                )
            elif result.status is IntegrityStatus.UNREGISTERED:
                notice(
                    f"**{result.filename} - not in the baseline**\n\n"
                    f"- Current SHA-256: `{result.actual_sha256}`\n"
                    f"- Path: `{result.path}`\n\n"
                    f"{result.message}",
                    kind="warning",
                )

with section(
    "Per-file verification",
    icon="table",
    caption="One row per original: the recorded baseline next to what is on disk right now.",
):
    rows = []
    for result in results:
        rows.append(
            {
                "Fixture": result.filename,
                "Status": result.status.label,
                "Baseline SHA-256": result.expected_sha256 or "n/a",
                "Current SHA-256": result.actual_sha256 or "n/a",
                "Baseline bytes": result.expected_size if result.expected_size is not None else "n/a",
                "Current bytes": result.actual_size if result.actual_size is not None else "n/a",
                "Path": result.path,
            }
        )
    table = pd.DataFrame(rows)

    def _paint(value: str) -> str:
        return {
            "MATCH": "color: #34D399; font-weight: 600",
            "MISMATCH": "color: #F87171; font-weight: 600",
            "MISSING": "color: #FB923C; font-weight: 600",
            "UNREGISTERED": "color: #FACC15; font-weight: 600",
        }.get(value, "")

    st.dataframe(
        table.style.map(_paint, subset=["Status"]),
        hide_index=True,
        column_config={
            "Fixture": st.column_config.TextColumn("Fixture", pinned=True),
            "Status": st.column_config.TextColumn("Status"),
            "Baseline SHA-256": st.column_config.TextColumn("Baseline SHA-256"),
            "Current SHA-256": st.column_config.TextColumn("Current SHA-256"),
            "Baseline bytes": st.column_config.NumberColumn("Baseline bytes", format="%d"),
            "Current bytes": st.column_config.NumberColumn("Current bytes", format="%d"),
        },
    )

    st.download_button(
        "Download integrity report (CSV)",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name="integrity_report.csv",
        mime="text/csv",
        icon=":material/download:",
    )

with section(
    "Change-detection self-test",
    icon="science",
    caption=(
        "Copies one original into a temporary directory, flips a single byte in "
        "the copy and re-runs the same verification routine. The original in "
        "`data/originals/` is never modified."
    ),
):
    if st.button(
        "Run detection self-test",
        icon=":material/science:",
        help="Proves that a modified copy is detected, without touching the originals.",
    ):
        with st.status("Running the change-detection self-test...", expanded=True) as status:
            outcome = detection_self_test(manifest, paths.ORIGINALS_DIR)
            if outcome.get("ok"):
                status.update(label="Self-test passed", state="complete")
                st.code(
                    f"baseline SHA-256 : {outcome.get('expected_sha256')}\n"
                    f"mutated  SHA-256 : {outcome.get('mutated_sha256')}",
                    language="text",
                )
                st.caption(str(outcome.get("detail", "Self-test passed.")))
            else:
                status.update(label="Self-test could not be completed", state="error")
                st.caption(str(outcome.get("detail", "Self-test could not be completed.")))
