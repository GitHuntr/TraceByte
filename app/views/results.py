"""Results page: the measured performance of the carving engine.

The page shows one run at a time. Every run owns its own artefacts, so the
numbers of an earlier run are never mixed with the numbers of a newer one.
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
from app.ui import CONDITION_ICON, Kpi, empty_state, kpi_row, notice, page_header, section
from src.experiments import LEGACY_RUN_ID, list_runs, metrics_files_for_run
from src.hashing import human_size

page_header(
    "Results",
    "The measurement layer of the project. Detection, carving and validation "
    "are scored separately against the ground truth, so a candidate that was "
    "found but not recovered correctly is visible instead of being hidden "
    "inside a single recovery number.",
    icon="query_stats",
)

runs = list_runs(paths.EXPERIMENTS_DIR)

if not runs:
    empty_state(
        "science",
        "No measurements yet",
        "Run the experiment on the **Carve** page; the results of every run "
        "stay available here.",
    )
    st.stop()

run_labels = {
    run.run_id: f"{run.run_id}  ·  {run.created_utc[:19].replace('T', ' ')} UTC"
    + (f" [{run.status}]" if getattr(run, "status", "complete") != "complete" else "")
    for run in runs
}
selected_run = st.selectbox(
    "Run",
    options=[run.run_id for run in runs],
    index=len(runs) - 1,
    format_func=lambda run_id: run_labels.get(run_id, run_id),
    help=(
        "Every run keeps its own artefacts. The list contains all runs that are "
        "still on disk; the newest one is selected by default."
    ),
)

if selected_run == LEGACY_RUN_ID:
    artefacts = f"`{paths.EXPERIMENTS_DIR}` and `{paths.RECOVERED_DIR}` (legacy layout, read-only)"
    notice("Legacy artifacts are read-only. Unreferenced candidate files are reported separately and are never counted as validated recoveries.", kind="warning")
else:
    artefacts = (
        f"`{paths.EXPERIMENTS_DIR / selected_run}` and "
        f"`{paths.RECOVERED_DIR / selected_run}`"
    )
st.caption(f"Showing run **{selected_run}** - artefacts in {artefacts}.")

metrics_files = metrics_files_for_run(paths.EXPERIMENTS_DIR, selected_run)

if not metrics_files:
    empty_state(
        "hourglass_empty",
        "This run has no measurements yet",
        "Press *Run carving experiments* on the **Carve** page to produce them.",
    )
    st.stop()

records = []
for path in metrics_files:
    try:
        records.append(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        notice(f"Malformed metrics in {path.name}: {e}", kind="error")
records.sort(key=lambda raw: raw.get("condition", "")) if records else None
if not records:
    empty_state(
        "error",
        "No valid measurements found for this run",
        "The run may be incomplete, failed, or contain malformed artefacts.",
    )
    st.stop()

summary = pd.DataFrame(
    [
        {
            "Condition": raw.get("condition", ""),
            "Detection precision": raw.get("detection", {}).get("precision", 0.0),
            "Detection recall": raw.get("detection", {}).get("recall", 0.0),
            "Recovery precision": raw.get("exact_recovery", {}).get("precision", 0.0),
            "Recovery recall": raw.get("exact_recovery", {}).get("recall", 0.0),
            "Mean byte coverage": raw.get("mean_byte_coverage", 0.0),
            "Data completeness": raw.get("data_completeness", 0.0),
        }
        for raw in records
    ]
)

kpi_row(
    [
        Kpi(
            "Detection recall",
            f"{summary['Detection recall'].mean():.0%}",
            help="Average share of the planted files that were found at all",
        ),
        Kpi(
            "Exact recovery",
            f"{summary['Recovery recall'].mean():.0%}",
            help="Average share of the planted files that were recovered byte for byte",
        ),
        Kpi(
            "Byte coverage",
            f"{summary['Mean byte coverage'].mean():.0%}",
            help="Average share of the original bytes present in the carved candidates",
        ),
        Kpi(
            "Data completeness",
            f"{summary['Data completeness'].mean():.0%}",
            help="Share of the original bytes that were planted into the images",
        ),
    ]
)

with section(
    "Conditions compared",
    icon="bar_chart",
    caption="Detection asks whether the file was found; recovery asks whether the bytes are correct.",
):
    st.dataframe(
        summary,
        hide_index=True,
        column_config={
            "Condition": st.column_config.TextColumn("Condition", pinned=True),
            "Detection precision": st.column_config.NumberColumn("Detection precision", format="percent"),
            "Detection recall": st.column_config.NumberColumn("Detection recall", format="percent"),
            "Recovery precision": st.column_config.NumberColumn("Recovery precision", format="percent"),
            "Recovery recall": st.column_config.NumberColumn("Recovery recall", format="percent"),
            "Mean byte coverage": st.column_config.NumberColumn("Mean byte coverage", format="percent"),
            "Data completeness": st.column_config.NumberColumn("Data completeness", format="percent"),
        },
    )

    chart = summary.melt(
        id_vars="Condition",
        value_vars=[
            "Detection precision",
            "Detection recall",
            "Recovery precision",
            "Recovery recall",
        ],
        var_name="Measure",
        value_name="Score",
    )
    st.bar_chart(chart, x="Condition", y="Score", color="Measure")

    st.download_button(
        "Download comparison (CSV)",
        data=summary.to_csv(index=False).encode("utf-8"),
        file_name="results_comparison.csv",
        mime="text/csv",
        icon=":material/download:",
    )

for raw in records:
    condition = raw.get("condition", "")
    icon = CONDITION_ICON.get(condition, "view_stream")
    detection = raw.get("detection", {})
    recovery = raw.get("exact_recovery", {})

    with section(
        f"Condition: {condition}",
        icon=icon,
        caption=(
            f"{raw.get('ground_truth_files', 0)} ground-truth files, "
            f"{raw.get('ground_truth_instances', 0)} planted instances."
        ),
    ):
        st.subheader(f"Condition: {condition} - detection and recovery")

        st.markdown(
            f":material/check_circle: **{detection.get('tp', 0)} true positives** · "
            f":material/close: **{detection.get('fp', 0)} false positives** · "
            f":material/cancel: **{detection.get('fn', 0)} false negatives** · "
            f":material/percent: detection F1 **{detection.get('f1', 0.0):.0%}** · "
            f":material/content_copy: exact recovery **{recovery.get('tp', 0)}/"
            f"{recovery.get('tp', 0) + recovery.get('fn', 0)} "
            f"({recovery.get('recall', 0.0):.0%})**"
        )

        outcomes = pd.DataFrame(
            [
                {
                    "File": outcome.get("file_id", ""),
                    "Signature": outcome.get("signature") or "-",
                    "Detected": bool(outcome.get("detected")),
                    "Carved": bool(outcome.get("carved")),
                    "Exact": bool(outcome.get("exact")),
                    "Span": bool(outcome.get("span")),
                    "Byte coverage": float(outcome.get("byte_coverage") or 0.0),
                    "Status": outcome.get("status") or "-",
                }
                for outcome in raw.get("outcomes", [])
            ]
        )
        st.dataframe(
            outcomes,
            hide_index=True,
            column_config={
                "File": st.column_config.TextColumn("File", pinned=True),
                "Detected": st.column_config.CheckboxColumn("Detected"),
                "Carved": st.column_config.CheckboxColumn("Carved"),
                "Exact": st.column_config.CheckboxColumn("Exact"),
                "Span": st.column_config.CheckboxColumn("Span"),
                "Byte coverage": st.column_config.ProgressColumn(
                    "Byte coverage", min_value=0.0, max_value=1.0, format="%.0f%%"
                ),
            },
        )

        per_signature = pd.DataFrame(
            [
                {
                    "Signature": name,
                    "TP": score.get("tp", 0),
                    "FP": score.get("fp", 0),
                    "FN": score.get("fn", 0),
                    "Precision": score.get("precision", 0.0),
                    "Recall": score.get("recall", 0.0),
                    "F1": score.get("f1", 0.0),
                }
                for name, score in raw.get("per_signature", {}).items()
            ]
        )
        if not per_signature.empty:
            st.caption("Per signature")
            st.dataframe(
                per_signature,
                hide_index=True,
                column_config={
                    "Signature": st.column_config.TextColumn("Signature", pinned=True),
                    "TP": st.column_config.NumberColumn("TP", format="%d"),
                    "FP": st.column_config.NumberColumn("FP", format="%d"),
                    "FN": st.column_config.NumberColumn("FN", format="%d"),
                    "Precision": st.column_config.NumberColumn("Precision", format="percent"),
                    "Recall": st.column_config.NumberColumn("Recall", format="percent"),
                    "F1": st.column_config.NumberColumn("F1", format="percent"),
                },
            )

        false_positives = raw.get("false_positives", [])
        if false_positives:
            with st.expander(f"False positives ({len(false_positives)})", icon=":material/warning:"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Candidate": fp.get("candidate_id", ""),
                                "Signature": fp.get("signature", ""),
                                "Offset": fp.get("offset", 0),
                                "Length": human_size(int(fp.get("length", 0))),
                                "Note": fp.get("note", ""),
                            }
                            for fp in false_positives
                        ]
                    ),
                    hide_index=True,
                    column_config={
                        "Candidate": st.column_config.TextColumn("Candidate", pinned=True),
                        "Offset": st.column_config.NumberColumn("Offset", format="%d"),
                    },
                )

        for note in raw.get("notes", []):
            notice(note, kind="warning")

# Report unreferenced candidate files for legacy layout separately (once, outside condition loop)
if selected_run == LEGACY_RUN_ID:
    try:
        exp_dir = paths.EXPERIMENTS_DIR
        rec_dir = paths.RECOVERED_DIR
        ref = set()
        for cdir in exp_dir.iterdir():
            if cdir.is_dir() and cdir.name.startswith("exp-"):
                cr = cdir / "carve_results.json"
                if cr.exists():
                    try:
                        cd = json.loads(cr.read_text(encoding="utf-8"))
                        for cand in cd.get("candidates", []):
                            op = cand.get("output_path") or cand.get("filename") or cand.get("candidate_id")
                            if op:
                                ref.add(Path(op).name)
                    except Exception:
                        pass
        disk = set()
        for p in rec_dir.rglob("*"):
            if p.is_file() and p.name != ".gitkeep":
                disk.add(p.name)
        unref = sorted(list(disk - ref))
        if unref:
            with st.expander(f"Unreferenced candidate files ({len(unref)}) - not counted as recoveries", icon=":material/report:"):
                st.dataframe(pd.DataFrame({"Unreferenced file": unref}), hide_index=True)
    except Exception:
        pass

st.caption(
    "Detection, exact recovery and span recovery are three different questions. "
    "A file counts as detected when a candidate starts at its ground-truth "
    "offset, as exactly recovered when the carved bytes match the baseline "
    "SHA-256, and as span recovered when the candidate covers the original "
    "byte range."
)
