"""Dataset page: create the synthetic ground-truth set and its baseline manifest."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from app.state import clear_caches, get_manifest
from src.experiment_log import ExperimentLog
from src.fixtures import FIXTURE_SPECS, initialize_dataset
from src.hashing import human_size, shorten
from src.paths import EXPERIMENT_LOG_PATH, MANIFEST_PATH, ORIGINALS_DIR

st.caption(
    "Creates deterministic synthetic fixtures in `data/originals/` and records a "
    "SHA-256 baseline for each of them. Existing originals are never overwritten "
    "and recorded baseline hashes are never regenerated."
)

with st.container(horizontal=True):
    initialise = st.button(
        "Initialise dataset",
        type="primary",
        icon=":material/play_arrow:",
        help=(
            "Creates any missing synthetic fixture and records its baseline hash. "
            "Existing files and existing baselines are preserved untouched."
        ),
    )
    st.caption("Non-destructive: safe to run more than once.")

if initialise:
    log = ExperimentLog(EXPERIMENT_LOG_PATH)
    with st.spinner("Generating synthetic fixtures and recording baselines..."):
        report = initialize_dataset(
            originals_dir=ORIGINALS_DIR,
            manifest_path=MANIFEST_PATH,
            log=log,
        )
    st.session_state["dataset_report"] = report
    clear_caches()
    st.success(
        f"Dataset initialisation finished: {report.created_count} created, "
        f"{report.preserved_count} preserved, {report.adopted_count} adopted, "
        f"{report.mismatch_count} integrity mismatch(es)."
    )

report = st.session_state.get("dataset_report")

if report is not None:
    with st.container(border=True):
        st.markdown("**Last initialisation run**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Created", report.created_count)
        m2.metric("Preserved", report.preserved_count)
        m3.metric("Adopted", report.adopted_count)
        m4.metric("Mismatches", report.mismatch_count)

        actions = pd.DataFrame(
            [
                {
                    "Fixture": action.filename,
                    "Action": action.action,
                    "Result": action.status,
                    "Size (bytes)": action.size_bytes,
                    "Baseline SHA-256": shorten(action.baseline_sha256, 16),
                    "Current SHA-256": shorten(action.current_sha256, 16),
                    "Baseline preserved": action.baseline_preserved,
                }
                for action in report.actions
            ]
        )
        st.dataframe(actions, hide_index=True)

        for action in report.actions:
            if action.status == "mismatch":
                st.error(f"{action.filename}: {action.message}")
            elif action.status == "unregistered":
                st.warning(f"{action.filename}: {action.message}")
        for warning in report.warnings:
            st.warning(warning)

manifest = get_manifest(str(MANIFEST_PATH))

with st.container(border=True):
    st.markdown("**Baseline manifest**")
    if not manifest.entries:
        st.info(
            "No baseline recorded yet. Press *Initialise dataset* to create the "
            "synthetic ground truth and its manifest."
        )
    else:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Manifest version", manifest.manifest_version)
        col_b.metric("Fixtures", len(manifest.entries))
        col_c.metric(
            "Total size",
            human_size(sum(entry.size_bytes for entry in manifest.entries.values())),
        )
        st.caption(f"Created: {manifest.created_utc or 'n/a'} | Updated: {manifest.updated_utc or 'n/a'}")

        rows = []
        for filename in manifest.filenames():
            entry = manifest.entries[filename]
            rows.append(
                {
                    "Fixture": filename,
                    "ID": entry.fixture_id,
                    "Size (bytes)": entry.size_bytes,
                    "SHA-256": entry.sha256,
                    "Signature": entry.signature_hex.upper() or "none",
                    "Offset": str(entry.signature_offset) if entry.signature_offset is not None else "n/a",
                    "Fully parseable": entry.fully_parseable,
                    "Baseline origin": entry.baseline_origin,
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True)

        st.download_button(
            "Download manifest (JSON)",
            data=MANIFEST_PATH.read_text(encoding="utf-8")
            if MANIFEST_PATH.exists()
            else "{}",
            file_name="manifest.json",
            mime="application/json",
            icon=":material/download:",
        )

with st.container(border=True):
    st.markdown("**Synthetic fixture catalogue**")
    st.caption(
        "None of these files is a valid, fully parseable JPEG, PDF or ZIP. They "
        "only carry realistic signatures so that a carving engine has a "
        "meaningful target, and they are labelled as synthetic everywhere."
    )
    catalogue = pd.DataFrame(
        [
            {
                "Fixture": spec.filename,
                "Bytes": len(spec.build()),
                "Signature": spec.signature_hex.upper() or "none",
                "Offset": str(spec.signature_offset) if spec.signature_offset is not None else "n/a",
                "Description": spec.description,
            }
            for spec in FIXTURE_SPECS
        ]
    )
    st.dataframe(catalogue, hide_index=True)
