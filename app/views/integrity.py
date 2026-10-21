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

from app.state import get_integrity_results, get_manifest
from src.integrity import IntegrityStatus, detection_self_test
from src.paths import MANIFEST_PATH, ORIGINALS_DIR

st.caption(
    "Compares the SHA-256 of every original on disk with the baseline recorded "
    "in `data/originals/manifest.json`. Mismatches and missing files are "
    "reported; the baseline is never updated automatically."
)

manifest = get_manifest(str(MANIFEST_PATH))
results, summary = get_integrity_results(str(MANIFEST_PATH), str(ORIGINALS_DIR))

if not manifest.entries:
    st.warning(
        "No baseline manifest found. Open the **Dataset** page and press "
        "*Initialise dataset* first."
    )
    st.stop()

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Match", summary.get("MATCH", 0))
col_b.metric("Mismatch", summary.get("MISMATCH", 0))
col_c.metric("Missing", summary.get("MISSING", 0))
col_d.metric("Unregistered", summary.get("UNREGISTERED", 0))

problems = [
    result for result in results if result.status is not IntegrityStatus.MATCH
]

if not problems:
    st.success(
        "All recorded originals match their baseline SHA-256. The evidence set is "
        "intact and the experiment can proceed."
    )
else:
    st.error(
        f"{len(problems)} integrity problem(s) detected. The baseline was **not** "
        "updated - investigate and restore from a trusted copy before running any "
        "experiment."
    )
    for result in problems:
        if result.status is IntegrityStatus.MISMATCH:
            st.error(
                f"**{result.filename} - content changed**\n\n"
                f"- Baseline SHA-256: `{result.expected_sha256}`\n"
                f"- Current SHA-256: `{result.actual_sha256}`\n"
                f"- Baseline size: {result.expected_size} bytes | "
                f"Current size: {result.actual_size} bytes\n\n"
                f"{result.message}"
            )
        elif result.status is IntegrityStatus.MISSING:
            st.error(
                f"**{result.filename} - file missing**\n\n"
                f"- Baseline SHA-256: `{result.expected_sha256}`\n"
                f"- Expected path: `{result.path}`\n\n"
                f"{result.message}"
            )
        elif result.status is IntegrityStatus.UNREGISTERED:
            st.warning(
                f"**{result.filename} - not in the baseline**\n\n"
                f"- Current SHA-256: `{result.actual_sha256}`\n"
                f"- Path: `{result.path}`\n\n"
                f"{result.message}"
            )

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
st.dataframe(table, hide_index=True)

st.download_button(
    "Download integrity report (CSV)",
    data=table.to_csv(index=False).encode("utf-8"),
    file_name="integrity_report.csv",
    mime="text/csv",
    icon=":material/download:",
)

with st.container(border=True):
    st.markdown("**Change-detection self-test**")
    st.caption(
        "Copies one original into a temporary directory, flips a single byte in "
        "the copy and re-runs the same verification routine. The original in "
        "`data/originals/` is never modified."
    )
    if st.button(
        "Run detection self-test",
        icon=":material/science:",
        help="Proves that a modified copy is detected, without touching the originals.",
    ):
        outcome = detection_self_test(manifest, ORIGINALS_DIR)
        if outcome.get("ok"):
            st.success(outcome.get("detail", "Self-test passed."))
            st.code(
                f"baseline SHA-256 : {outcome.get('expected_sha256')}\n"
                f"mutated  SHA-256 : {outcome.get('mutated_sha256')}",
                language="text",
            )
        else:
            st.warning(outcome.get("detail", "Self-test could not be completed."))
