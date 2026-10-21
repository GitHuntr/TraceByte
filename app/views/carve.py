"""Carve page: build the controlled images and run the carving engine.

The page shows which signatures the engine knows about and lets the operator
run the three storage conditions. A run writes to `data/experiments/` and
`data/recovered/` and appends to the experiment log. It never modifies
`data/originals/`.

Every run owns a directory of its own, so a new run never overwrites the
artefacts of an earlier one. The page can display any run that is still on
disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

import src.paths as paths
from app.state import clear_caches
from app.ui import (
    CONDITION_ICON,
    Kpi,
    empty_state,
    kpi_row,
    notice,
    page_header,
    section,
)
from src.conditions import CONDITION_DESCRIPTIONS, CONDITIONS
from src.experiment_log import default_log
from src.experiments import (
    LEGACY_RUN_ID,
    list_runs,
    metrics_files_for_run,
    run_all_conditions,
    summarise,
)
from src.hashing import human_size
from src.signatures import default_registry

page_header(
    "Carve",
    "Builds one controlled image per storage condition from the ground-truth "
    "originals, carves every signature it finds and measures the result. The "
    "originals in `data/originals/` are only ever read.",
    icon="content_cut",
)

with section(
    "Run the experiment",
    icon="play_arrow",
    caption="One run covers all three storage conditions and owns its own directory.",
):
    with st.container(horizontal=True, vertical_alignment="center"):
        run_clicked = st.button(
            "Run carving experiments",
            type="primary",
            icon=":material/play_arrow:",
            help=(
                "Builds the three images, carves them and writes the results. "
                "Every run gets its own directory, so earlier runs and their "
                "candidates are kept untouched."
            ),
        )
        st.caption(
            "Outputs go to `data/experiments/` and `data/recovered/`; the "
            "provenance log gets one `experiment_completed` event per condition."
        )

    if run_clicked:
        with st.spinner("Building images, carving and measuring..."):
            results = run_all_conditions(log=default_log())
        clear_caches()
        st.toast(f"{len(results)} experiments completed.")
        notice(f"Ran {len(results)} experiments.", kind="success")
        st.json(summarise(results), expanded=False)

with section(
    "Storage conditions",
    icon="view_stream",
    caption="The same ground truth, stored three different ways.",
):
    with st.container(horizontal=True):
        for condition in CONDITIONS:
            icon = CONDITION_ICON.get(condition, "view_stream")
            with st.container(border=True, width="content"):
                st.markdown(f":material/{icon}: **{condition.title()}**")
                st.caption(CONDITION_DESCRIPTIONS[condition])

with section(
    "Supported signatures",
    icon="data_object",
    caption="The scanner looks for these magic bytes; the end marker bounds the candidate.",
):
    registry = default_registry()
    rows = []
    for spec in registry.specs():
        rows.append(
            {
                "Signature": spec.name,
                "Magic bytes": f"`{spec.magic.hex()}`",
                "Extension": spec.extension,
                "End marker": f"`{spec.end_marker.hex()}`" if spec.end_marker else "none",
                "Validation strategy": spec.validation_strategy,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "Signature": st.column_config.TextColumn("Signature", pinned=True),
        },
    )

with section(
    "Runs",
    icon="history",
    caption="Every run keeps its own artefacts; the list holds all runs still on disk.",
):
    runs = list_runs(paths.EXPERIMENTS_DIR)
    if not runs:
        empty_state(
            "science",
            "No experiment has been run yet",
            "Press *Run carving experiments* to produce the first measurements.",
        )
        st.stop()

    run_labels = {
        run.run_id: f"{run.run_id}  ·  {run.created_utc[:19].replace('T', ' ')} UTC"
        for run in runs
    }
    selected_run = st.selectbox(
        "Run",
        options=[run.run_id for run in runs],
        index=len(runs) - 1,
        format_func=lambda run_id: run_labels.get(run_id, run_id),
        help=(
            "Every run keeps its own artefacts. The list contains all runs that "
            "are still on disk; the newest one is selected by default."
        ),
    )

    metrics_files = metrics_files_for_run(paths.EXPERIMENTS_DIR, selected_run)
    if not metrics_files:
        empty_state(
            "hourglass_empty",
            "This run has no measurements yet",
            "Press *Run carving experiments* to produce them.",
        )
        st.stop()

    summary_rows = []
    for path in metrics_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        detection = raw.get("detection", {})
        recovery = raw.get("exact_recovery", {})
        image_path = Path(raw.get("image_path", ""))
        image_bytes = image_path.stat().st_size if image_path.is_file() else 0
        summary_rows.append(
            {
                "Condition": raw.get("condition", ""),
                "Experiment": raw.get("experiment_id", ""),
                "Image bytes": image_bytes,
                "Detection P": detection.get("precision", 0.0),
                "Detection R": detection.get("recall", 0.0),
                "Exact recovery P": recovery.get("precision", 0.0),
                "Exact recovery R": recovery.get("recall", 0.0),
                "Mean byte coverage": raw.get("mean_byte_coverage", 0.0),
                "Data completeness": raw.get("data_completeness", 0.0),
            }
        )
    summary_table = pd.DataFrame(summary_rows)

    kpi_row(
        [
            Kpi(
                "Conditions measured",
                len(summary_table),
                help="Storage conditions in the selected run",
            ),
            Kpi(
                "Mean detection recall",
                f"{summary_table['Detection R'].mean():.0%}",
                help="Average detection recall across the conditions of this run",
            ),
            Kpi(
                "Mean byte coverage",
                f"{summary_table['Mean byte coverage'].mean():.0%}",
                help="Average share of the original bytes that were recovered",
            ),
            Kpi(
                "Image size",
                human_size(int(summary_table["Image bytes"].max())),
                help="Size of the largest image of this run",
            ),
        ]
    )

    st.dataframe(
        summary_table,
        hide_index=True,
        column_config={
            "Condition": st.column_config.TextColumn("Condition", pinned=True),
            "Image bytes": st.column_config.NumberColumn("Image bytes", format="%d"),
            "Detection P": st.column_config.NumberColumn("Detection precision", format="percent"),
            "Detection R": st.column_config.NumberColumn("Detection recall", format="percent"),
            "Exact recovery P": st.column_config.NumberColumn("Recovery precision", format="percent"),
            "Exact recovery R": st.column_config.NumberColumn("Recovery recall", format="percent"),
            "Mean byte coverage": st.column_config.NumberColumn("Mean byte coverage", format="percent"),
            "Data completeness": st.column_config.NumberColumn("Data completeness", format="percent"),
        },
    )

    chart = summary_table.melt(
        id_vars="Condition",
        value_vars=["Detection P", "Detection R", "Exact recovery P", "Exact recovery R"],
        var_name="Measure",
        value_name="Score",
    )
    chart["Measure"] = chart["Measure"].map(
        {
            "Detection P": "Detection precision",
            "Detection R": "Detection recall",
            "Exact recovery P": "Recovery precision",
            "Exact recovery R": "Recovery recall",
        }
    )
    st.bar_chart(chart, x="Condition", y="Score", color="Measure")

    if selected_run == LEGACY_RUN_ID:
        st.caption(
            f"Artefacts of the selected run: `{paths.EXPERIMENTS_DIR}` | "
            f"`{paths.RECOVERED_DIR}` (legacy layout, read-only)"
        )
    else:
        st.caption(
            f"Artefacts of the selected run: `{paths.EXPERIMENTS_DIR / selected_run}` | "
            f"`{paths.RECOVERED_DIR / selected_run}`"
        )

    st.download_button(
        "Download summary (CSV)",
        data=summary_table.to_csv(index=False).encode("utf-8"),
        file_name="carve_summary.csv",
        mime="text/csv",
        icon=":material/download:",
    )
