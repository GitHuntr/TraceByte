"""Dataset page: create the synthetic ground-truth set and its baseline manifest."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

import src.paths as paths
from app.state import clear_caches, get_manifest
from app.ui import Kpi, empty_state, kpi_row, notice, page_header, section
from src.experiment_log import ExperimentLog
from src.fixtures import FIXTURE_SPECS, initialize_dataset
from src.hashing import human_size, shorten

page_header(
    "Dataset",
    "Creates the deterministic synthetic ground truth in `data/originals/` and "
    "records a SHA-256 baseline for every file. Existing originals are never "
    "overwritten and recorded baseline hashes are never regenerated.",
    icon="folder_open",
)

with section(
    "Initialise dataset",
    icon="play_arrow",
    caption="Non-destructive: safe to run as often as you like.",
):
    with st.container(horizontal=True, vertical_alignment="center"):
        initialise = st.button(
            "Initialise dataset",
            type="primary",
            icon=":material/play_arrow:",
            help=(
                "Creates any missing synthetic fixture and records its baseline "
                "hash. Existing files and existing baselines are preserved "
                "untouched."
            ),
        )
        st.caption(
            "Writes the manifest only when its content actually changed, so an "
            "unchanged baseline stays byte for byte identical."
        )

    if initialise:
        log = ExperimentLog(paths.EXPERIMENT_LOG_PATH)
        with st.spinner("Generating synthetic fixtures and recording baselines..."):
            report = initialize_dataset(log=log)
        st.session_state["dataset_report"] = report
        clear_caches()
        st.toast(
            f"{report.created_count} created, {report.preserved_count} preserved, "
            f"{report.mismatch_count} mismatch(es)."
        )
        notice(
            f"Dataset initialisation finished: {report.created_count} created, "
            f"{report.preserved_count} preserved, {report.adopted_count} adopted, "
            f"{report.mismatch_count} integrity mismatch(es).",
            kind="success",
        )

report = st.session_state.get("dataset_report")

if report is not None:
    with section("Last initialisation run", icon="history"):
        kpi_row(
            [
                Kpi("Created", report.created_count, help="Files generated in this run"),
                Kpi("Preserved", report.preserved_count, help="Files that already existed and were left alone"),
                Kpi("Adopted", report.adopted_count, help="Files that existed without a baseline entry"),
                Kpi("Mismatches", report.mismatch_count, help="Files whose content no longer matches the baseline"),
            ]
        )

        actions = pd.DataFrame(
            [
                {
                    "Fixture": action.filename,
                    "Action": action.action,
                    "Result": action.status,
                    "Size": human_size(action.size_bytes),
                    "Baseline SHA-256": shorten(action.baseline_sha256, 16),
                    "Current SHA-256": shorten(action.current_sha256, 16),
                    "Baseline preserved": action.baseline_preserved,
                }
                for action in report.actions
            ]
        )
        st.dataframe(
            actions,
            hide_index=True,
            column_config={
                "Fixture": st.column_config.TextColumn("Fixture", pinned=True),
                "Size": st.column_config.TextColumn("Size"),
                "Baseline SHA-256": st.column_config.TextColumn("Baseline SHA-256"),
                "Current SHA-256": st.column_config.TextColumn("Current SHA-256"),
                "Baseline preserved": st.column_config.CheckboxColumn("Baseline preserved"),
            },
        )

        for action in report.actions:
            if action.status == "mismatch":
                notice(f"{action.filename}: {action.message}", kind="error")
            elif action.status == "unregistered":
                notice(f"{action.filename}: {action.message}", kind="warning")
        for warning in report.warnings:
            notice(warning, kind="warning")

manifest = get_manifest(str(paths.MANIFEST_PATH))

with section(
    "Baseline manifest",
    icon="verified",
    caption="The evidence record of the ground truth: one SHA-256 per original.",
):
    if not manifest.entries:
        empty_state(
            "description",
            "No baseline recorded yet",
            "Press *Initialise dataset* to create the synthetic ground truth and "
            "its manifest.",
        )
    else:
        kpi_row(
            [
                Kpi("Manifest version", manifest.manifest_version),
                Kpi("Fixtures", len(manifest.entries)),
                Kpi(
                    "Total size",
                    human_size(sum(entry.size_bytes for entry in manifest.entries.values())),
                ),
                Kpi("Last updated", (manifest.updated_utc or "n/a")[:19].replace("T", " ")),
            ]
        )
        st.caption(
            f"Created {manifest.created_utc or 'n/a'} · updated "
            f"{manifest.updated_utc or 'n/a'}"
        )

        rows = []
        for filename in manifest.filenames():
            entry = manifest.entries[filename]
            rows.append(
                {
                    "Fixture": filename,
                    "ID": entry.fixture_id,
                    "Size": human_size(entry.size_bytes),
                    "SHA-256": entry.sha256,
                    "Signature": entry.signature_hex.upper() or "none",
                    "Offset": str(entry.signature_offset) if entry.signature_offset is not None else "n/a",
                    "Fully parseable": entry.fully_parseable,
                    "Baseline origin": entry.baseline_origin,
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            column_config={
                "Fixture": st.column_config.TextColumn("Fixture", pinned=True),
                "SHA-256": st.column_config.TextColumn("SHA-256"),
                "Fully parseable": st.column_config.CheckboxColumn("Fully parseable"),
            },
        )

        st.download_button(
            "Download manifest (JSON)",
            data=paths.MANIFEST_PATH.read_text(encoding="utf-8")
            if paths.MANIFEST_PATH.exists()
            else "{}",
            file_name="manifest.json",
            mime="application/json",
            icon=":material/download:",
        )

with section(
    "Synthetic fixture catalogue",
    icon="inventory_2",
    caption=(
        "None of these files is a valid, fully parseable JPEG, PDF or ZIP. They "
        "only carry realistic signatures so that a carving engine has a "
        "meaningful target, and they are labelled as synthetic everywhere."
    ),
):
    catalogue = pd.DataFrame(
        [
            {
                "Fixture": spec.filename,
                "Signature": spec.signature_hex.upper() or "none",
                "Offset": str(spec.signature_offset) if spec.signature_offset is not None else "n/a",
                "Description": spec.description,
                "Notes": spec.notes,
            }
            for spec in FIXTURE_SPECS
        ]
    )
    st.dataframe(
        catalogue,
        hide_index=True,
        column_config={
            "Fixture": st.column_config.TextColumn("Fixture", pinned=True),
        },
    )

with section(
    "Where the files live",
    icon="folder_open",
    caption="Ground truth, experimental inputs and recovered output never share a directory.",
):
    st.code(
        "data/\n"
        "├── originals/      ground truth + manifest.json   (read-only after creation)\n"
        "├── experiments/    <run_id>/<experiment>/          (one directory per run)\n"
        "└── recovered/      <run_id>/<experiment>/          (carved candidates)\n"
        "logs/\n"
        "└── experiment_log.jsonl                            (append-only provenance)",
        language="text",
    )
