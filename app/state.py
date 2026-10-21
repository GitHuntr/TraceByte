"""Shared, cached read-only state helpers for the FileCarveLab pages."""

from __future__ import annotations

import streamlit as st

from src.integrity import IntegrityResult, run_integrity_check, summarize
from src.manifest import Manifest, load_manifest
from src.metrics import ConditionMetrics


@st.cache_data(ttl="30s", show_spinner=False)
def get_manifest(manifest_path: str) -> Manifest:
    """Return the baseline manifest (read-only)."""
    return load_manifest(manifest_path)


@st.cache_data(ttl="10s", show_spinner=False)
def get_experiment_metrics(experiments_dir: str) -> list[ConditionMetrics]:
    """Return the metrics of every experiment that was run (read-only)."""
    from src.experiments import load_experiment_metrics

    return load_experiment_metrics(experiments_dir)


@st.cache_data(ttl="30s", show_spinner=False)
def get_integrity_results(
    manifest_path: str, originals_dir: str
) -> tuple[list[IntegrityResult], dict[str, int]]:
    """Return the integrity results for the current state of the evidence set."""
    manifest = load_manifest(manifest_path)
    results = run_integrity_check(manifest, originals_dir)
    return results, summarize(results)


def clear_caches() -> None:
    """Drop cached snapshots after a dataset mutation."""
    get_manifest.clear()
    get_integrity_results.clear()
    get_experiment_metrics.clear()
