"""Results page: the measured accuracy of the carving engine.

Everything on this page is read back from the artefacts that a run produced.
The page separates the three claims that the engine makes:

* **detected** - a signature was found at the right offset,
* **carved** - a byte range was written to `data/recovered/`,
* **validated** - the carved bytes match a baseline SHA-256 byte for byte.
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

from app.state import get_experiment_metrics
from src.paths import EXPERIMENTS_DIR

st.caption(
    "Read-only view of the measurements produced by the carving experiments. "
    "Detection, carving and validation are reported separately: a signature "
    "hit is a detection, a written byte range is a carved candidate, and only "
    "a matching baseline SHA-256 makes it a validated recovery."
)

metrics = get_experiment_metrics(str(EXPERIMENTS_DIR))
if not metrics:
    st.info(
        "No measurements available. Open the **Carve** page and run the "
        "experiments first."
    )
    st.stop()

st.subheader("Comparison across conditions")
overview_rows = []
for item in metrics:
    overview_rows.append(
        {
            "Condition": item.condition,
            "Ground-truth files": item.ground_truth_files,
            "Signature instances": item.ground_truth_instances,
            "Detection P": round(item.detection.precision, 4),
            "Detection R": round(item.detection.recall, 4),
            "Detection F1": round(item.detection.f1, 4),
            "False positives": item.detection.fp,
            "Validated recoveries": item.exact_recovery.tp,
            "Recovery P": round(item.exact_recovery.precision, 4),
            "Recovery R": round(item.exact_recovery.recall, 4),
            "Mean byte coverage": round(item.mean_byte_coverage, 4),
            "Data completeness": round(item.data_completeness, 4),
        }
    )
overview = pd.DataFrame(overview_rows)
st.dataframe(overview, hide_index=True)

st.download_button(
    "Download overview (CSV)",
    data=overview.to_csv(index=False).encode("utf-8"),
    file_name="carve_results_overview.csv",
    mime="text/csv",
    icon=":material/download:",
)

for item in metrics:
    st.subheader(f"Condition: {item.condition}")
    st.caption(
        f"Experiment `{item.experiment_id}` | image `{item.image_path}` | "
        f"SHA-256 `{item.image_sha256}`"
    )

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Detection recall", f"{item.detection.recall:.2f}")
    col_b.metric("Detection precision", f"{item.detection.precision:.2f}")
    col_c.metric("Validated recoveries", item.exact_recovery.tp)
    col_d.metric("Mean byte coverage", f"{item.mean_byte_coverage:.0%}")

    per_file_rows = []
    for outcome in item.outcomes:
        per_file_rows.append(
            {
                "File": outcome.file_id,
                "Signature": outcome.signature or "none",
                "Detected": outcome.detected,
                "Embedded detected": outcome.embedded_detected,
                "Carved": outcome.carved,
                "Validated": outcome.exact,
                "Extent policy": outcome.extent_policy or "-",
                "Byte coverage": round(outcome.byte_coverage, 4),
                "Expected SHA-256": (outcome.expected_sha256 or "")[:16] or "-",
                "Actual SHA-256": (outcome.actual_sha256 or "")[:16] or "-",
                "Note": outcome.note,
            }
        )
    st.dataframe(pd.DataFrame(per_file_rows), hide_index=True)

    if item.per_signature:
        st.markdown("**Per-signature detection**")
        signature_rows = [
            {
                "Signature": name,
                "TP": score.tp,
                "FP": score.fp,
                "FN": score.fn,
                "Precision": round(score.precision, 4),
                "Recall": round(score.recall, 4),
                "F1": round(score.f1, 4),
            }
            for name, score in sorted(item.per_signature.items())
        ]
        st.dataframe(pd.DataFrame(signature_rows), hide_index=True)

    if item.false_positives:
        st.markdown("**False positives**")
        fp_rows = [
            {
                "Signature": item["signature"],
                "Offset": item["offset"],
                "Length": item["length"],
                "Note": item["note"],
            }
            for item in item.false_positives
        ]
        st.dataframe(pd.DataFrame(fp_rows), hide_index=True)

    if item.notes:
        with st.expander("Notes"):
            for note in item.notes:
                st.markdown(f"- {note}")

    metrics_path = Path(EXPERIMENTS_DIR) / item.experiment_id / "metrics.json"
    if metrics_path.exists():
        st.download_button(
            f"Download metrics ({item.experiment_id})",
            data=metrics_path.read_bytes(),
            file_name=f"{item.experiment_id}_metrics.json",
            mime="application/json",
            icon=":material/download:",
            key=f"download_metrics_{item.experiment_id}",
        )
