"""Experiment log page: read-only view of the append-only provenance record."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from src.experiment_log import ExperimentLog
from src.paths import EXPERIMENT_LOG_PATH


@st.cache_data(ttl="5s", show_spinner=False)
def load_log_rows(path: str, limit: int) -> list[dict]:
    """Return the most recent log events, newest first."""
    events = ExperimentLog(path, enabled=False).read_events()
    return list(reversed(events[-limit:])) if limit else list(reversed(events))


st.caption(
    "Every mutating action is appended to `logs/experiment_log.jsonl` together "
    "with a UTC timestamp, the run identifier, the tool versions in use and the "
    "parameters of the action. Records are never rewritten or deleted."
)

limit = st.slider(
    "Number of records to display",
    min_value=10,
    max_value=500,
    value=50,
    step=10,
    help="Only the most recent records are loaded into the table.",
)

events = load_log_rows(str(EXPERIMENT_LOG_PATH), limit)

if not events:
    st.info(
        "The experiment log is empty. It is written automatically when the dataset "
        "is initialised from the **Dataset** page."
    )
    st.stop()

rows = []
for event in events:
    payload = event.get("payload", {})
    rows.append(
        {
            "Timestamp (UTC)": event.get("timestamp_utc", ""),
            "Run ID": event.get("run_id", ""),
            "Event": event.get("event", ""),
            "Actor": event.get("actor", ""),
            "Payload": payload,
        }
    )

st.dataframe(pd.DataFrame(rows), hide_index=True)

with st.expander("Raw record (most recent)"):
    st.json(events[0])
