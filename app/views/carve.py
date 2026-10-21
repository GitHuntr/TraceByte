"""Carve page: build the controlled images and run the carving engine.

The page shows which signatures the engine knows about and lets the operator
run the three storage conditions. A run writes to `data/experiments/` and
`data/recovered/` and appends to the experiment log. It never modifies
`data/originals/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from app.state import clear_caches
from src.conditions import CONDITION_DESCRIPTIONS, CONDITIONS
from src.experiment_log import default_log
from src.experiments import run_all_conditions, summarise
from src.paths import EXPERIMENTS_DIR, RECOVERED_DIR
from src.signatures import default_registry

st.caption(
    "Builds one controlled image per storage condition from the ground-truth "
    "originals, carves every signature it finds and measures the result. "
    "Outputs are written to `data/experiments/` and `data/recovered/`; the "
    "originals in `data/originals/` are only ever read."
)

registry = default_registry()
with st.container(border=True):
    st.markdown("**Supported signatures**")
    rows = []
    for spec in registry.specs():
        rows.append(
            {
                "Signature": spec.name,
                "Magic bytes": f"`{spec.magic_hex}`",
                "Extension": spec.extension,
                "End marker": f"`{spec.end_marker.hex()}`" if spec.end_marker else "none",
                "Validation strategy": spec.validation_strategy,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)

with st.container(border=True):
    st.markdown("**Storage conditions**")
    condition_rows = [
        {"Condition": name, "Description": CONDITION_DESCRIPTIONS[name]}
        for name in CONDITIONS
    ]
    st.dataframe(pd.DataFrame(condition_rows), hide_index=True)

run_clicked = st.button(
    "Run carving experiments",
    type="primary",
    icon=":material/play_arrow:",
    help=(
        "Builds the three images, carves them and writes the results. "
        "Re-running overwrites the previous outputs of the same experiment."
    ),
)

if run_clicked:
    with st.spinner("Building images, carving and measuring..."):
        results = run_all_conditions(log=default_log())
    clear_caches()
    st.success(f"Ran {len(results)} experiments.")
    st.json(summarise(results), expanded=False)

st.subheader("Latest run")

metrics_files = sorted(Path(EXPERIMENTS_DIR).glob("*/metrics.json"))
if not metrics_files:
    st.info(
        "No experiment has been run yet. Press *Run carving experiments* to "
        "produce the first measurements."
    )
    st.stop()

summary_rows = []
for path in metrics_files:
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    detection = raw.get("detection", {})
    recovery = raw.get("exact_recovery", {})
    summary_rows.append(
        {
            "Condition": raw.get("condition", ""),
            "Experiment": raw.get("experiment_id", ""),
            "Image bytes": raw.get("size_bytes", 0),
            "Detection P": detection.get("precision", 0.0),
            "Detection R": detection.get("recall", 0.0),
            "Exact recovery P": recovery.get("precision", 0.0),
            "Exact recovery R": recovery.get("recall", 0.0),
            "Mean byte coverage": raw.get("mean_byte_coverage", 0.0),
            "Data completeness": raw.get("data_completeness", 0.0),
        }
    )
summary_table = pd.DataFrame(summary_rows)
st.dataframe(summary_table, hide_index=True)

st.caption(f"Artefacts: `{EXPERIMENTS_DIR}` | `{RECOVERED_DIR}`")

st.download_button(
    "Download summary (CSV)",
    data=summary_table.to_csv(index=False).encode("utf-8"),
    file_name="carve_summary.csv",
    mime="text/csv",
    icon=":material/download:",
)
